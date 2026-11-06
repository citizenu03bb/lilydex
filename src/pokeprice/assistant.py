"""The management chat, V1: it explains and searches, it writes nothing (decision 0029).

One question runs a short loop: the model reads the question, may call the
read-only tools of ``assistant_tools`` (four rounds at most), then answers.
The tools run here, never in the model: each call is checked against the
chat's principal, which holds only ``assistant:read`` and goes through the
same check as an agent's delegation (``agent.permitted``/``agent.require``).
Their results go back to the model as data, in the provider's function
response channel, never in the instructions.

The conversations, the question log and the token counts live beside the
collection base, in ``assistant.sqlite3`` (decision 0034): out of the
collection's backups, readable for 30 days, purged nightly by ``pokeprice-manage
purge`` and erasable by their author. Flagged exchanges have a separate
180-day retention for the bench. The log keeps the tool, its arguments,
its duration and the tokens, never the text of a result. It also keeps the
interface context sent with each question (``assistant_context``, decision
0036): erased with the question's text, purged with it after 30 days.
"""

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import assistant_context, assistant_signals, assistant_tools
from .agent import AgentError, permitted, require
from .assistant_model import ModelError

PROMPT = Path(__file__).with_name("assistant_prompt.md")
PERMISSIONS = frozenset({assistant_tools.PERMISSION})
MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 6
QUESTION_SECONDS = 90
HISTORY_MESSAGES = 6
MAX_QUESTION = 1000
MAX_CARDS = 5
RETENTION = timedelta(days=30)
FLAGGED_RETENTION = timedelta(days=180)  # a flagged exchange, for the bench (decision 0038)
DEFECT_REPLY = "Noté : le défaut est enregistré pour le banc d’essai."
DEFAULT_DAILY_LIMIT = 100
DEFAULT_PER_MINUTE = 6
FALLBACK = "Je n’ai pas su répondre : reformule ta question, ou regarde la file « À toi »."
CITED = re.compile(r"\[([A-Za-z0-9_-]{1,120})\]")
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")
logger = logging.getLogger("pokeprice.assistant")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_user ON conversations(user_id, updated_at);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')), text TEXT NOT NULL,
    cards_json TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL, created_at REAL NOT NULL, day TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0, tool_rounds INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT 'running');
CREATE INDEX IF NOT EXISTS questions_day ON questions(day);
CREATE INDEX IF NOT EXISTS questions_user ON questions(user_id, created_at);
CREATE TABLE IF NOT EXISTS tool_calls(id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    tool TEXT NOT NULL, arguments_json TEXT NOT NULL, duration_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL, created_at REAL NOT NULL);
"""


def migrate_context(db):
    """V1.1 (decision 0036): the interface context of each question. Idempotent."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(questions)")}
    if "context_json" not in columns:
        db.execute("ALTER TABLE questions ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")


class Refused(Exception):
    """A question the server does not send to the model."""

    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class ConversationErased(Refused):
    """The conversation disappeared while a question was in flight."""

    def __init__(self):
        super().__init__(404, "Cette conversation est effacée ou expirée : ouvrez-en une nouvelle.")


def retention_warning(directory, at=None):
    """The morning brief detects a missed night's purge, without reading any text."""
    path = Path(directory) / "assistant.sqlite3"
    if not path.exists():
        return None
    at = time.time() if at is None else at
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT 1 FROM messages m WHERE m.created_at<? AND NOT EXISTS "
                "(SELECT 1 FROM assistant_flags f WHERE f.conversation_id=m.conversation_id "
                "AND f.created_at>=?) UNION ALL SELECT 1 FROM assistant_flags WHERE created_at<? LIMIT 1",
                (at - RETENTION.total_seconds() - 86400,
                 at - FLAGGED_RETENTION.total_seconds(),
                 at - FLAGGED_RETENTION.total_seconds() - 86400)).fetchone()
    except sqlite3.Error:
        return "La purge du chat ne peut pas être contrôlée : vérifiez le journal du serveur."
    if row:
        return "La purge nocturne du chat est en retard : vérifiez le service de sauvegarde."
    return None


PARIS = ZoneInfo("Europe/Paris")
# What each role sees, in the words of the app map (assistant_prompt.md).
ROLE_LABELS = {
    "admin": "administrateur : voit tous les onglets, dont Statistiques et Réglages",
    "editor": "équipe : voit Collection et Ventes, pas Statistiques ni Réglages",
    "reader": "lecture seule : consulte, ne modifie rien",
}


def system_prompt(today=None):
    """The one system instruction, shared with the bench (bench/assistant/run.py)."""
    today = today or datetime.now(PARIS).date()
    text = f"{DAYS[today.weekday()]} {today.day} {MONTHS[today.month - 1]} {today.year}"
    return PROMPT.read_text(encoding="utf-8").replace("{date_du_jour}", text)


def now_text(moment=None):
    """« vendredi 6 novembre 2026, 7 h 05 », in Paris time."""
    moment = (moment or datetime.now(timezone.utc)).astimezone(PARIS)
    return (f"{DAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]} {moment.year}, "
            f"{moment.hour} h {moment.minute:02d}")


def server_facts(role, moment=None):
    """What the server knows for sure about this question: the time and who asks."""
    return {"now": now_text(moment), "timezone": "Europe/Paris",
            "role": ROLE_LABELS.get(role, role or "inconnu")}


def day_of(moment):
    return datetime.fromtimestamp(moment, timezone.utc).date().isoformat()


class Journal:
    """Conversations, question log and tokens, in their own file beside the base."""

    def __init__(self, directory):
        self.path = Path(directory) / "assistant.sqlite3"
        self.lock = threading.Lock()
        with self.connect() as db, db:
            db.executescript(SCHEMA)
            migrate_context(db)
            self.migrate_flags(db)
            # Earlier versions could append tool arguments after deletion. A
            # question without a live conversation is only a quota counter.
            db.execute("DELETE FROM tool_calls WHERE NOT EXISTS "
                       "(SELECT 1 FROM questions q JOIN conversations c ON c.id=q.conversation_id "
                       "WHERE q.id=tool_calls.question_id)")
            db.execute("UPDATE questions SET conversation_id='',context_json='{}' "
                       "WHERE (conversation_id!='' OR context_json!='{}') AND NOT EXISTS "
                       "(SELECT 1 FROM conversations c WHERE c.id=questions.conversation_id)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return closing(db)

    # -- Conversations --------------------------------------------------------

    def conversation(self, user_id, conversation_id):
        cutoff = time.time() - RETENTION.total_seconds()
        with self.connect() as db:
            row = db.execute("SELECT id FROM conversations WHERE id=? AND user_id=? AND updated_at>=?",
                             (conversation_id, user_id, cutoff)).fetchone()
            if not row:
                raise KeyError("Conversation introuvable.")
            return [self.message(m) for m in db.execute(
                "SELECT id,role,text,cards_json,created_at FROM messages "
                "WHERE conversation_id=? AND created_at>=? ORDER BY id", (conversation_id, cutoff))]

    @staticmethod
    def message(row):
        return {"id": row["id"], "role": row["role"], "text": row["text"],
                "cards": json.loads(row["cards_json"]),
                "at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat()}

    def latest(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT id FROM conversations WHERE user_id=? "
                             "AND updated_at>=? ORDER BY updated_at DESC LIMIT 1",
                             (user_id, time.time() - RETENTION.total_seconds())).fetchone()
        if not row:
            return None
        try:
            messages = self.conversation(user_id, row["id"])
        except KeyError:  # Deleted in another tab between the two reads.
            return None
        return {"id": row["id"], "messages": messages,
                "flagged": self.thumbs(user_id, row["id"])}

    def add(self, conversation_id, role, text, cards=(), at=None):
        at = at or time.time()
        with self.connect() as db, db:
            row = db.execute("INSERT INTO messages(conversation_id,role,text,cards_json,created_at) "
                             "SELECT ?,?,?,?,? WHERE EXISTS (SELECT 1 FROM conversations WHERE id=?)",
                             (conversation_id, role, text, json.dumps(list(cards), ensure_ascii=False),
                              at, conversation_id))
            if not row.rowcount:
                raise ConversationErased()
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (at, conversation_id))
        return row.lastrowid

    def delete(self, user_id, conversation_id=None):
        """Erase one conversation of this person, or all of them, with their tool log."""
        with self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            where, args = "user_id=?", [user_id]
            if conversation_id:
                where, args = where + " AND id=?", args + [conversation_id]
            ids = [r[0] for r in db.execute(f"SELECT id FROM conversations WHERE {where}", args)]
            for cid in ids:
                # The counts stay for the day's ceiling and the token total; the text and
                # the tool arguments go.
                db.execute("DELETE FROM tool_calls WHERE question_id IN "
                           "(SELECT id FROM questions WHERE conversation_id=?)", (cid,))
                db.execute("UPDATE questions SET conversation_id='', context_json='{}' "
                           "WHERE conversation_id=?", (cid,))
                db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        return {"deleted": len(ids)}

    def purge(self, at=None):
        """Nothing older than 30 days: messages, questions and their tool calls.

        A flagged conversation (decision 0038) stays for the bench, up to
        ``FLAGGED_RETENTION``; its author can still erase it.
        """
        at = at or time.time()
        cutoff = at - RETENTION.total_seconds()
        with self.connect() as db, db:
            self.expire_flags(db, at)
            kept = "conversation_id NOT IN (SELECT conversation_id FROM assistant_flags)"
            messages = db.execute(f"DELETE FROM messages WHERE created_at<? AND {kept}",
                                  (cutoff,)).rowcount
            questions = db.execute(f"DELETE FROM questions WHERE created_at<? AND {kept}",
                                   (cutoff,)).rowcount
            conversations = db.execute(
                "DELETE FROM conversations WHERE (updated_at<? OR NOT EXISTS "
                "(SELECT 1 FROM messages m WHERE m.conversation_id=conversations.id) "
                "AND created_at<?) AND id NOT IN (SELECT conversation_id FROM assistant_flags)",
                (cutoff, cutoff)).rowcount
        return {"conversations": conversations, "messages": messages, "questions": questions}

    # -- Questions and limits --------------------------------------------------

    def start(self, user_id, conversation_id, model, *, daily_limit, per_minute, at=None):
        """Reserve a question within the day's ceiling and the account's rate."""
        at = at or time.time()
        with self.lock, self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            if conversation_id:
                if not db.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=? AND updated_at>=?",
                                  (conversation_id, user_id, at - RETENTION.total_seconds())).fetchone():
                    raise KeyError("Conversation introuvable.")
            if db.execute("SELECT COUNT(*) FROM questions WHERE day=?",
                          (day_of(at),)).fetchone()[0] >= daily_limit:
                raise Refused(429, "Plafond de questions du jour atteint : le chat revient demain.")
            if db.execute("SELECT COUNT(*) FROM questions WHERE user_id=? AND created_at>?",
                          (user_id, at - 60)).fetchone()[0] >= per_minute:
                raise Refused(429, "Trop de questions d’affilée : attends une minute.", 60)
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
                db.execute("INSERT INTO conversations VALUES(?,?,?,?)",
                           (conversation_id, user_id, at, at))
            question_id = str(uuid.uuid4())
            db.execute("INSERT INTO questions(id,conversation_id,user_id,created_at,day,model) "
                       "VALUES(?,?,?,?,?,?)",
                       (question_id, conversation_id, user_id, at, day_of(at), model))
        return question_id, conversation_id

    def finish(self, question_id, *, input_tokens, output_tokens, duration_ms, tool_rounds, outcome):
        with self.connect() as db, db:
            db.execute("UPDATE questions SET input_tokens=?,output_tokens=?,duration_ms=?,"
                       "tool_rounds=?,outcome=? WHERE id=?",
                       (input_tokens, output_tokens, duration_ms, tool_rounds, outcome, question_id))

    def call(self, question_id, tool, arguments, duration_ms, outcome):
        # The arguments are the model's, bounded by the schemas; the result is never kept.
        with self.connect() as db, db:
            written = db.execute("INSERT INTO tool_calls(question_id,tool,arguments_json,duration_ms,outcome,"
                       "created_at) SELECT ?,?,?,?,?,? WHERE EXISTS "
                       "(SELECT 1 FROM questions q JOIN conversations c ON c.id=q.conversation_id WHERE q.id=?)",
                       (question_id, tool[:60], json.dumps(arguments, ensure_ascii=False)[:2000],
                        duration_ms, outcome, time.time(), question_id))
            if not written.rowcount:
                raise ConversationErased()

    def require_question(self, question_id):
        """An erased question keeps counters only; it cannot resume work or send data."""
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM questions q JOIN conversations c "
                             "ON c.id=q.conversation_id WHERE q.id=? AND q.created_at>=?",
                             (question_id, time.time() - RETENTION.total_seconds())).fetchone()
        if not row:
            raise ConversationErased()

    # -- Interface context (V1.1, decision 0036) ---------------------------------

    def note_context(self, question_id, context):
        with self.connect() as db, db:
            written = db.execute("UPDATE questions SET context_json=? WHERE id=? AND EXISTS "
                                 "(SELECT 1 FROM conversations c WHERE c.id=questions.conversation_id)",
                                 (json.dumps(context, ensure_ascii=False), question_id))
            if not written.rowcount:
                raise ConversationErased()

    def context(self, question_id):
        with self.connect() as db:
            row = db.execute("SELECT context_json FROM questions WHERE id=?", (question_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def calls(self, question_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT tool,arguments_json,duration_ms,outcome FROM tool_calls "
                "WHERE question_id=? ORDER BY id", (question_id,))]

    def usage(self, daily_limit, at=None):
        at = at or time.time()
        with self.connect() as db:
            today = db.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o "
                "FROM questions WHERE day=?", (day_of(at),)).fetchone()
            month = db.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o "
                "FROM questions WHERE created_at>?", (at - RETENTION.total_seconds(),)).fetchone()
        return {
            "daily_limit": daily_limit,
            "today": {"questions": today["n"], "input_tokens": today["i"], "output_tokens": today["o"]},
            "last_30_days": {"questions": month["n"], "input_tokens": month["i"],
                             "output_tokens": month["o"]},
        }

    # -- Chantier V1.1 « capture des échecs » (decision 0038) ------------------
    # The 👎 and the automatic signals, in their own table; a flagged
    # conversation escapes the 30 days' purge and goes when its author erases it.

    FLAGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS assistant_flags(id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL, question_id TEXT, asked_id INTEGER, answer_id INTEGER,
        kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS assistant_flags_conversation ON assistant_flags(conversation_id);
    """

    @classmethod
    def migrate_flags(cls, db):
        """Idempotent: the table appears on the first start after the update."""
        db.executescript(cls.FLAGS_SCHEMA)

    @staticmethod
    def expire_flags(db, at):
        return db.execute("DELETE FROM assistant_flags WHERE created_at<?",
                          (at - FLAGGED_RETENTION.total_seconds(),)).rowcount

    def flag(self, conversation_id, user_id, kind, *, question_id=None, asked_id=None,
             answer_id=None, note=""):
        if kind not in assistant_signals.KINDS:
            raise ValueError(kind)
        with self.connect() as db, db:
            db.execute("INSERT INTO assistant_flags(conversation_id,user_id,question_id,asked_id,"
                       "answer_id,kind,note,created_at) SELECT ?,?,?,?,?,?,?,? "
                       "WHERE EXISTS (SELECT 1 FROM conversations WHERE id=?)",
                       (conversation_id, user_id, question_id, asked_id, answer_id, kind,
                        (note or "")[:assistant_signals.MAX_NOTE], time.time(), conversation_id))

    def thumbs_down(self, user_id, message_id, note=""):
        """The 👎 of the author on one answer; a second press replaces the note."""
        note = (note or "").strip()[:assistant_signals.MAX_NOTE]
        with self.connect() as db, db:
            db.execute("BEGIN IMMEDIATE")
            answer = db.execute(
                "SELECT m.id, m.conversation_id FROM messages m JOIN conversations c "
                "ON c.id=m.conversation_id WHERE m.id=? AND m.role='assistant' AND c.user_id=? "
                "AND m.created_at>=?",
                (message_id, user_id, time.time() - RETENTION.total_seconds())).fetchone()
            if not answer:
                raise KeyError("Réponse introuvable.")
            asked = db.execute("SELECT id, created_at FROM messages WHERE conversation_id=? "
                               "AND role='user' "
                               "AND id<? ORDER BY id DESC LIMIT 1",
                               (answer["conversation_id"], message_id)).fetchone()
            question = self.asked_in(db, answer["conversation_id"], asked)
            existing = db.execute("SELECT id FROM assistant_flags WHERE answer_id=? "
                                  "AND kind='thumbs_down'", (message_id,)).fetchone()
            if existing:
                db.execute("UPDATE assistant_flags SET note=?, created_at=? WHERE id=?",
                           (note, time.time(), existing["id"]))
            else:
                db.execute("INSERT INTO assistant_flags(conversation_id,user_id,question_id,asked_id,"
                           "answer_id,kind,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (answer["conversation_id"], user_id,
                            question,
                            asked["id"] if asked else None, message_id, "thumbs_down", note,
                            time.time()))
        return {"message_id": message_id, "flagged": True}

    @staticmethod
    def asked_in(db, conversation_id, asked):
        """The question row of a user message: the last one started before it was written."""
        if not asked:
            return None
        row = db.execute("SELECT id FROM questions WHERE conversation_id=? AND created_at<=? "
                         "ORDER BY created_at DESC LIMIT 1",
                         (conversation_id, asked["created_at"])).fetchone()
        return row[0] if row else None

    def thumbs(self, user_id, conversation_id):
        with self.connect() as db:
            return [r[0] for r in db.execute(
                "SELECT answer_id FROM assistant_flags WHERE conversation_id=? AND user_id=? "
                "AND kind='thumbs_down'", (conversation_id, user_id))]

    def flags(self, conversation_id=None):
        with self.connect() as db:
            where, args = "WHERE created_at>=?", (time.time() - FLAGGED_RETENTION.total_seconds(),)
            if conversation_id:
                where, args = where + " AND conversation_id=?", (*args, conversation_id)
            return [dict(r) for r in db.execute(
                f"SELECT conversation_id,question_id,asked_id,answer_id,kind,note "
                f"FROM assistant_flags {where} ORDER BY id", args)]

    def previous_exchange(self, conversation_id, asked_id):
        """The question and answer before ``asked_id``: (question_id, asked, answer) or None."""
        with self.connect() as db:
            rows = db.execute("SELECT id,role,text,created_at FROM messages WHERE conversation_id=? "
                              "AND id<? AND created_at>=? ORDER BY id DESC LIMIT 2",
                              (conversation_id, asked_id, time.time() - RETENTION.total_seconds())).fetchall()
            if len(rows) < 2 or rows[0]["role"] != "assistant" or rows[1]["role"] != "user":
                return None
            question = self.asked_in(db, conversation_id, rows[1])
        return question, dict(rows[1]), dict(rows[0])
    # -- V1.1, cost alert (decision 0039) ---------------------------------------
    # The month's tokens per model, apart from the questions: the 30 days' purge
    # never empties a calendar month before its cost is read. Counts only, no text,
    # kept 13 months. Own tables, created when first used: no migration of the rest.

    def cost_tables(self, db):
        db.executescript(COST_SCHEMA)

    def count_month(self, month, model, input_tokens, output_tokens):
        with self.connect() as db, db:
            self.cost_tables(db)
            db.execute(
                "INSERT INTO token_months(month,model,questions,input_tokens,output_tokens) "
                "VALUES(?,?,1,?,?) ON CONFLICT(month,model) DO UPDATE SET "
                "questions=questions+1,input_tokens=input_tokens+excluded.input_tokens,"
                "output_tokens=output_tokens+excluded.output_tokens",
                (month, model, input_tokens, output_tokens))
            db.execute("DELETE FROM token_months WHERE month<?", (month_shift(month, -12),))
            db.execute("DELETE FROM cost_alerts WHERE month<?", (month_shift(month, -12),))

    def month_tokens(self, month):
        with self.connect() as db, db:
            self.cost_tables(db)
            return [dict(r) for r in db.execute(
                "SELECT model,questions,input_tokens,output_tokens FROM token_months "
                "WHERE month=? ORDER BY model", (month,))]

    def claim_alert(self, month, cost, now):
        """Take the month's alert: once sent, never again; a failed send waits a lease."""
        with self.lock, self.connect() as db, db:
            self.cost_tables(db)
            row = db.execute("SELECT sent_at,claimed_at FROM cost_alerts WHERE month=?",
                             (month,)).fetchone()
            if row and (row["sent_at"] or row["claimed_at"] > now - ALERT_LEASE):
                return False
            db.execute("INSERT INTO cost_alerts(month,claimed_at,cost) VALUES(?,?,?) "
                       "ON CONFLICT(month) DO UPDATE SET claimed_at=excluded.claimed_at,"
                       "cost=excluded.cost", (month, now, cost))
            return True

    def alert_done(self, month, now, error=""):
        with self.connect() as db, db:
            db.execute("UPDATE cost_alerts SET sent_at=?,error=? WHERE month=?",
                       (None if error else now, error, month))

    def alert_state(self, month):
        with self.connect() as db, db:
            self.cost_tables(db)
            row = db.execute("SELECT * FROM cost_alerts WHERE month=?", (month,)).fetchone()
            return dict(row) if row else None


@dataclass
class Question:
    id: str
    conversation_id: str
    user_id: str
    text: str
    history: list = field(default_factory=list)
    asked_id: int = 0  # V1.1 « capture des échecs »: the user message, and a « Défaut : » note.
    defect: str | None = None
    context: dict = field(default_factory=dict)  # V1.1: the interface context, cleaned.
    role: str = ""  # The account's role, read from the base: never from the interface.


def principal(store, user_id):
    """The chat's principal: this account, holding ``assistant:read`` only.

    Read again from the base on each check, so a disabled account or one made
    reader stops the chat at its next tool call, as a revoked delegation does.
    """
    with store.connect() as db:
        row = db.execute(
            "SELECT role FROM users WHERE id=? AND disabled=0 AND status='active' "
            "AND role IN ('admin','editor','reader')", (user_id,)).fetchone()
    if not row:
        raise AgentError(401, "unauthenticated", "Compte absent ou désactivé.")
    grant = {"owner_id": user_id, "role": row["role"], "permissions": permitted(PERMISSIONS, row["role"])}
    require(grant, assistant_tools.PERMISSION)
    return grant


def cards_in(value, found):
    """The copies a tool result names: {id: {copy_id, name, number, set_name}}."""
    if isinstance(value, dict):
        copy_id = value.get("copy_id") or (value.get("id") if "set_name" in value else None)
        if isinstance(copy_id, str) and copy_id not in found:
            found[copy_id] = {"copy_id": copy_id, **{k: value[k] for k in ("name", "number", "set_name")
                                                    if isinstance(value.get(k), str)}}
        elif isinstance(copy_id, str):
            for key in ("name", "number", "set_name"):
                if isinstance(value.get(key), str):
                    found[copy_id].setdefault(key, value[key])
        for item in value.values():
            cards_in(item, found)
    elif isinstance(value, list):
        for item in value:
            cards_in(item, found)
    return found


class Assistant:
    def __init__(self, store, todo, model, *, daily_limit=DEFAULT_DAILY_LIMIT,
                 per_minute=DEFAULT_PER_MINUTE, journal=None, clock=time.monotonic):
        self.store, self.todo, self.model = store, todo, model
        self.daily_limit, self.per_minute = daily_limit, per_minute
        self.journal = journal or Journal(store.root)
        self.clock = clock

    @property
    def enabled(self):
        return self.model is not None

    def state(self, user_id):
        return {
            "enabled": self.enabled,
            "model": self.model.name if self.enabled else None,
            "usage": self.journal.usage(self.daily_limit),
            "conversation": self.journal.latest(user_id),
        }

    def prepare(self, user_id, text, conversation_id=None, context=None):
        """Every check before anything leaves the server; raises Refused or AgentError."""
        if not self.enabled:
            raise Refused(503, "Chat désactivé : la clé du modèle n’est pas configurée.")
        role = principal(self.store, user_id)["role"]
        text = (text or "").strip()
        if not text or len(text) > MAX_QUESTION:
            raise Refused(422, f"Question vide ou trop longue ({MAX_QUESTION} caractères au plus).")
        try:
            context, dropped = assistant_context.clean(context)
        except ValueError as error:
            raise Refused(422, str(error)) from None
        if dropped:
            logger.info("assistant context dropped=%s", ",".join(dropped[:10]))
        question_id, conversation_id = self.journal.start(
            user_id, conversation_id, self.model.name,
            daily_limit=self.daily_limit, per_minute=self.per_minute)
        # Only the questions and answers before: never the earlier tool results.
        history = [m for m in self.journal.conversation(user_id, conversation_id) if m["text"]]
        asked_id = self.journal.add(conversation_id, "user", text)
        if context:
            self.journal.note_context(question_id, context)
        question = Question(question_id, conversation_id, user_id, text, history[-HISTORY_MESSAGES:],
                            context=context, asked_id=asked_id, defect=assistant_signals.defect(text),
                            role=role)
        self.rephrase_signal(question)
        return question

    # -- Chantier V1.1 « capture des échecs » (decision 0038) --------------------

    def rephrase_signal(self, question):
        """Flag the previous exchange when this question asks it again in other words."""
        previous = self.journal.previous_exchange(question.conversation_id, question.asked_id)
        if not previous or question.defect is not None:
            return
        question_id, asked, answer = previous
        if assistant_signals.rephrased(asked["text"], question.text, time.time() - answer["created_at"]):
            self.journal.flag(question.conversation_id, question.user_id, "rephrased",
                              question_id=question_id, asked_id=asked["id"], answer_id=answer["id"])

    def report_defect(self, question):
        """« Défaut : … » is a report, not a question: noted, never sent to the model."""
        previous = self.journal.previous_exchange(question.conversation_id, question.asked_id)
        question_id, asked, answer = previous or (question.id, {"id": question.asked_id}, {"id": None})
        self.journal.flag(question.conversation_id, question.user_id, "defect",
                          question_id=question_id, asked_id=asked["id"], answer_id=answer["id"],
                          note=question.defect or question.text)
        yield "text", {"text": DEFECT_REPLY}
        answer_id = self.journal.add(question.conversation_id, "assistant", DEFECT_REPLY)
        self.journal.finish(question.id, input_tokens=0, output_tokens=0, duration_ms=0,
                            tool_rounds=0, outcome="defect")
        yield "done", {"conversation_id": question.conversation_id, "message_id": answer_id,
                       "input_tokens": 0, "output_tokens": 0,
                       "usage": self.journal.usage(self.daily_limit)}

    def signal(self, question, signals, answer_id):
        for kind, note in dict(signals).items():
            self.journal.flag(question.conversation_id, question.user_id, kind,
                              question_id=question.id, asked_id=question.asked_id or None,
                              answer_id=answer_id, note=note)

    def messages(self, question):
        from .assistant_model import Turn

        out = []
        for m in question.history:
            out.append({"role": "user", "text": m["text"]} if m["role"] == "user"
                       else {"role": "assistant", "turn": Turn(text=m["text"])})
        last = {"role": "user", "text": question.text}
        # The interface context and the server's facts (time, role), as data beside the
        # question; never in the instruction, which stays the same all day.
        last["context"] = assistant_context.for_model(question.context, server_facts(question.role))
        out.append(last)
        return out

    def tool(self, question, call):
        """Run one call the model proposed, after the principal's check; the result is data."""
        name, args = call.get("name", ""), call.get("args")
        started = time.perf_counter()
        self.journal.require_question(question.id)
        try:
            if name not in assistant_tools.TOOLS:
                raise AgentError(404, "unknown_tool", "Outil inconnu : aucun outil de ce nom.")
            if not isinstance(args, dict):
                raise AgentError(422, "invalid_arguments", "Les arguments forment un objet JSON.")
            principal(self.store, question.user_id)
            result = assistant_tools.call(assistant_tools.Context(self.store, self.todo), name, args)
            outcome = "ok"
        except AgentError as error:
            result = {"error": error.code, "detail": str(error)}
            outcome = error.code
        duration = int((time.perf_counter() - started) * 1000)
        self.journal.call(question.id, name, args if isinstance(args, dict) else {}, duration, outcome)
        logger.info("assistant tool=%s outcome=%s ms=%d question=%s", name[:60], outcome, duration,
                    question.id)
        return result, outcome

    def run(self, question):
        """Answer one prepared question; yields the events of the route."""
        yield "start", {"conversation_id": question.conversation_id}
        if question.defect is not None:
            try:
                self.journal.require_question(question.id)
                yield from self.report_defect(question)
            except ConversationErased as error:
                yield "error", {"code": "conversation_erased", "message": str(error)}
            return
        started = self.clock()
        signals, answer_id = [], None  # V1.1 « capture des échecs »
        tokens = {"input_tokens": 0, "output_tokens": 0}
        schemas = assistant_tools.tool_schemas()["tools"]
        system = system_prompt()
        messages = self.messages(question)
        answer, seen, topics, rounds, outcome, finished = [], {}, [], 0, "ok", False
        try:
            for round_ in range(MAX_TOOL_ROUNDS + 1):
                self.journal.require_question(question.id)
                if self.clock() - started > QUESTION_SECONDS:
                    raise ModelError("délai de la question dépassé")
                allow = round_ < MAX_TOOL_ROUNDS
                turn = None
                for kind, value in self.model.stream(system, messages, schemas, allow_tools=allow):
                    self.journal.require_question(question.id)
                    if kind == "text" and value:
                        answer.append(value)
                        yield "text", {"text": value}
                    elif kind == "turn":
                        turn = value
                if turn is None:
                    raise ModelError("tour sans fin")
                tokens["input_tokens"] += turn.input_tokens
                tokens["output_tokens"] += turn.output_tokens
                if turn.calls and not allow:
                    signals.append(("max_rounds", f"{MAX_TOOL_ROUNDS} tours d’outils"))
                if not turn.calls or not allow:
                    break
                rounds += 1
                messages.append({"role": "assistant", "turn": turn})
                results = []
                for index, call in enumerate(turn.calls):
                    if index >= MAX_CALLS_PER_ROUND:
                        result = {"error": "too_many_calls",
                                  "detail": f"{MAX_CALLS_PER_ROUND} appels d’outils au plus par tour."}
                    else:
                        known = call.get("name") in assistant_tools.TOOLS
                        yield "tool", {"tool": call.get("name") if known else "unknown"}
                        result, status = self.tool(question, call)
                        if status != "ok":
                            signals.append(("tool_error", f"{str(call.get('name'))[:60]} : {status}"))
                        if status == "ok":
                            cards_in(result, seen)
                            copy_id = (call.get("args") or {}).get("copy_id")
                            if copy_id in seen and copy_id not in topics:
                                topics.append(copy_id)
                    results.append({"id": call.get("id", ""), "name": call.get("name", ""),
                                    "content": json.dumps(result, ensure_ascii=False)})
                messages.append({"role": "tool", "results": results})
            text = "".join(answer).strip()
            if not text:
                text = FALLBACK
                yield "text", {"text": text}
            # Only copies a tool returned for this question: never an id the model made up.
            cited = [c for c in CITED.findall(text) if c in seen]
            cards = [seen[c] for c in dict.fromkeys([*cited, *topics])][:MAX_CARDS]
            for card in cards:
                yield "card", card
            answer_id = self.journal.add(question.conversation_id, "assistant", text, cards)
            self.close(question, started, rounds, outcome, tokens)
            self.signal(question, reversed(signals), answer_id)
            finished = True
            yield "done", {"conversation_id": question.conversation_id, "message_id": answer_id, **tokens,
                           "usage": self.journal.usage(self.daily_limit)}
        except GeneratorExit:  # The phone left: the question ends, its count stays.
            outcome = "interrupted"
            raise
        except ConversationErased as error:
            outcome = "erased"
            yield "error", {"code": "conversation_erased", "message": str(error)}
        except AgentError as error:  # The account lost its right during the question.
            outcome = error.code
            signals.append(("tool_error", error.code))
            yield "error", {"code": error.code, "message": str(error)}
        except ModelError as error:
            outcome = "model_error"
            signals.append(("model_error", str(error)[:200]))
            logger.warning("assistant model error=%s question=%s", error, question.id)
            yield "error", {"code": "model_error",
                            "message": "Le modèle ne répond pas pour l’instant : réessaie dans un moment."}
        finally:
            if not finished:
                self.close(question, started, rounds, outcome, tokens)
            if not finished and outcome not in ("interrupted", "erased"):
                self.signal(question, reversed(signals), None)

    def close(self, question, started, rounds, outcome, tokens):
        duration = int((self.clock() - started) * 1000)
        self.journal.finish(question.id, duration_ms=duration, tool_rounds=rounds,
                            outcome=outcome, **tokens)
        logger.info("assistant question=%s rounds=%d outcome=%s ms=%d in=%d out=%d", question.id,
                    rounds, outcome, duration, tokens["input_tokens"], tokens["output_tokens"])
        self.count_cost(tokens)  # V1.1, cost alert (decision 0039).

    # -- V1.1, cost alert (decision 0039) ---------------------------------------
    cost_alert = None  # A CostAlert, set by the web app; None in the tests that need none.

    def count_cost(self, tokens):
        """The question's tokens join the month's; never stops the answer."""
        try:
            month = month_of(time.time())
            self.journal.count_month(month, self.model.name, tokens["input_tokens"],
                                     tokens["output_tokens"])
            if self.cost_alert is not None:
                self.cost_alert.check(month)
        except Exception:  # noqa: BLE001 - a cost count never breaks the chat.
            logger.exception("assistant cost count failed")


# -- V1.1, cost alert (decision 0039) -------------------------------------------
# The chat's cost on the calendar month (UTC, like the day's ceiling): the month's
# tokens per model times the public price in assistant_pricing.json, the file the
# bench reads too. The price is in dollars; the threshold in euros, through a fixed
# rate that can be set. At the threshold, one alert a month on the alert channels.

PRICING = Path(__file__).with_name("assistant_pricing.json")
COST_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_months(month TEXT NOT NULL, model TEXT NOT NULL,
    questions INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(month, model));
CREATE TABLE IF NOT EXISTS cost_alerts(month TEXT PRIMARY KEY, claimed_at REAL NOT NULL,
    sent_at REAL, cost REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
"""
DEFAULT_COST_ALERT_EUR = 30.0
# Above the rate of the day it was set (about 0.86 €): the cost in euros reads a
# little high, so the alert comes early rather than late.
DEFAULT_EUR_PER_USD = 0.95
ALERT_LEASE = 600  # Seconds before a failed send is tried again, at the next question.
COST_ALERT_VARIABLE = "POKEPRICE_ASSISTANT_COST_ALERT_EUR"
RATE_VARIABLE = "POKEPRICE_ASSISTANT_EUR_PER_USD"


def month_of(moment):
    return datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m")


def month_shift(month, months):
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def load_pricing(path=PRICING):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def price_of(pricing, model, month):
    """Dollars per million tokens for the month, or None for a model without a price."""
    price = (pricing.get("models") or {}).get(model)
    if not price or "input" not in price or "output" not in price:
        return None
    current = {"input": price["input"], "output": price["output"]}
    for change in sorted(price.get("changes") or [], key=lambda c: c["from"]):
        if change["from"] <= month:
            current = {"input": change["input"], "output": change["output"]}
    return current


def month_cost(rows, pricing, month, eur_per_usd):
    """The month's estimated cost; the models without a price are named, not counted."""
    usd, unknown = 0.0, []
    for row in rows:
        price = price_of(pricing, row["model"], month)
        if price is None:
            if row["model"].split(":")[0] != "fake":
                unknown.append(row["model"])
            continue
        usd += (row["input_tokens"] * price["input"]
                + row["output_tokens"] * price["output"]) / 1_000_000
    return {"month": month, "usd": round(usd, 4), "eur": round(usd * eur_per_usd, 4),
            "unpriced_models": unknown}


def euro_text(value):
    return f"{value:.2f} €".replace(".", ",")


class CostAlert:
    """One alert a calendar month once the chat's estimated cost reaches the threshold.

    ``channels`` are the alert channels (``Notifier.channels``: Web Push, e-mail).
    The send runs in a thread (``spawn``): the answer never waits on a push service.
    """

    def __init__(self, journal, channels, origin="", *, threshold_eur=DEFAULT_COST_ALERT_EUR,
                 eur_per_usd=DEFAULT_EUR_PER_USD, pricing=None, spawn=None, clock=time.time):
        self.journal, self.channels = journal, list(channels)
        self.link = origin.rstrip("/") + "/gestion"
        self.threshold, self.rate = threshold_eur, eur_per_usd
        self.pricing = load_pricing() if pricing is None else pricing
        self.spawn = spawn or (lambda job: threading.Thread(
            target=job, name="pokeprice-cost-alert", daemon=True).start())
        self.clock = clock
        self.warned = set()

    @property
    def enabled(self):
        return self.threshold > 0 and bool(self.channels)

    def cost(self, month):
        return month_cost(self.journal.month_tokens(month), self.pricing, month, self.rate)

    def check(self, month=None):
        """After a question: the month's cost, and the alert when it is due; returns the cost."""
        month = month or month_of(self.clock())
        cost = self.cost(month)
        for model in set(cost["unpriced_models"]) - self.warned:
            self.warned.add(model)
            logger.warning("assistant cost: no price for model=%s in %s, its tokens are not "
                           "counted", model, PRICING.name)
        if self.enabled and cost["eur"] >= self.threshold and \
                self.journal.claim_alert(month, cost["eur"], self.clock()):
            self.spawn(lambda: self.send(month, cost))
        return cost

    def text(self, cost):
        title = f"Chat : coût estimé {euro_text(cost['eur'])} ce mois-ci"
        body = (f"{title}, seuil {euro_text(self.threshold)}. Usage inhabituel ou tarif changé : "
                f"regarder le journal du chat.")
        return title, body

    def send(self, month, cost):
        title, body = self.text(cost)
        sent, errors = [], []
        for channel in self.channels:
            try:
                channel.send(title, f"{body}\n{self.link}", self.link)
                sent.append(channel.name)
            except Exception as error:  # noqa: BLE001 - one channel down never hides the other.
                errors.append(type(error).__name__)  # The class only, never an address.
        error = "" if sent else ", ".join(errors) or "aucun canal"
        self.journal.alert_done(month, self.clock(), error)
        if error:
            logger.warning("assistant cost alert not sent month=%s error=%s", month, error)
        else:
            logger.info("assistant cost alert sent month=%s eur=%.2f channels=%s", month,
                        cost["eur"], ",".join(sent))
