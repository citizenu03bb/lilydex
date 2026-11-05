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
collection's backups, kept 30 days at most, purged by ``pokeprice-manage
purge`` and erasable by their author. The log keeps the tool, its arguments,
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

from . import assistant_context, assistant_tools
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


def system_prompt(today=None):
    """The one system instruction, shared with the bench (bench/assistant/run.py)."""
    today = today or datetime.now(timezone.utc).date()
    text = f"{DAYS[today.weekday()]} {today.day} {MONTHS[today.month - 1]} {today.year}"
    return PROMPT.read_text(encoding="utf-8").replace("{date_du_jour}", text)


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

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return closing(db)

    # -- Conversations --------------------------------------------------------

    def conversation(self, user_id, conversation_id):
        with self.connect() as db:
            row = db.execute("SELECT id FROM conversations WHERE id=? AND user_id=?",
                             (conversation_id, user_id)).fetchone()
            if not row:
                raise KeyError("Conversation introuvable.")
            return [self.message(m) for m in db.execute(
                "SELECT role,text,cards_json,created_at FROM messages "
                "WHERE conversation_id=? ORDER BY id", (conversation_id,))]

    @staticmethod
    def message(row):
        return {"role": row["role"], "text": row["text"], "cards": json.loads(row["cards_json"]),
                "at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat()}

    def latest(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT id FROM conversations WHERE user_id=? "
                             "ORDER BY updated_at DESC LIMIT 1", (user_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "messages": self.conversation(user_id, row["id"])}

    def add(self, conversation_id, role, text, cards=(), at=None):
        at = at or time.time()
        with self.connect() as db, db:
            db.execute("INSERT INTO messages(conversation_id,role,text,cards_json,created_at) "
                       "VALUES(?,?,?,?,?)",
                       (conversation_id, role, text, json.dumps(list(cards), ensure_ascii=False), at))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (at, conversation_id))

    def delete(self, user_id, conversation_id=None):
        """Erase one conversation of this person, or all of them, with their tool log."""
        with self.connect() as db, db:
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
        """Nothing older than 30 days: messages, questions and their tool calls."""
        cutoff = (at or time.time()) - RETENTION.total_seconds()
        with self.connect() as db, db:
            messages = db.execute("DELETE FROM messages WHERE created_at<?", (cutoff,)).rowcount
            questions = db.execute("DELETE FROM questions WHERE created_at<?", (cutoff,)).rowcount
            conversations = db.execute(
                "DELETE FROM conversations WHERE updated_at<? OR NOT EXISTS "
                "(SELECT 1 FROM messages m WHERE m.conversation_id=conversations.id) "
                "AND created_at<?", (cutoff, cutoff)).rowcount
        return {"conversations": conversations, "messages": messages, "questions": questions}

    # -- Questions and limits --------------------------------------------------

    def start(self, user_id, conversation_id, model, *, daily_limit, per_minute, at=None):
        """Reserve a question within the day's ceiling and the account's rate."""
        at = at or time.time()
        with self.lock, self.connect() as db, db:
            if conversation_id:
                if not db.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=?",
                                  (conversation_id, user_id)).fetchone():
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
            db.execute("INSERT INTO tool_calls(question_id,tool,arguments_json,duration_ms,outcome,"
                       "created_at) VALUES(?,?,?,?,?,?)",
                       (question_id, tool[:60], json.dumps(arguments, ensure_ascii=False)[:2000],
                        duration_ms, outcome, time.time()))

    # -- Interface context (V1.1, decision 0036) ---------------------------------

    def note_context(self, question_id, context):
        with self.connect() as db, db:
            db.execute("UPDATE questions SET context_json=? WHERE id=?",
                       (json.dumps(context, ensure_ascii=False), question_id))

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


@dataclass
class Question:
    id: str
    conversation_id: str
    user_id: str
    text: str
    history: list = field(default_factory=list)
    context: dict = field(default_factory=dict)  # V1.1: the interface context, cleaned.


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
        principal(self.store, user_id)
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
        self.journal.add(conversation_id, "user", text)
        if context:
            self.journal.note_context(question_id, context)
        return Question(question_id, conversation_id, user_id, text, history[-HISTORY_MESSAGES:],
                        context)

    def messages(self, question):
        from .assistant_model import Turn

        out = []
        for m in question.history:
            out.append({"role": "user", "text": m["text"]} if m["role"] == "user"
                       else {"role": "assistant", "turn": Turn(text=m["text"])})
        last = {"role": "user", "text": question.text}
        # The interface context, as data beside the question; never in the instruction.
        if question.context:
            last["context"] = assistant_context.for_model(question.context)
        out.append(last)
        return out

    def tool(self, question, call):
        """Run one call the model proposed, after the principal's check; the result is data."""
        name, args = call.get("name", ""), call.get("args")
        started = time.perf_counter()
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
        started = self.clock()
        tokens = {"input_tokens": 0, "output_tokens": 0}
        schemas = assistant_tools.tool_schemas()["tools"]
        system = system_prompt()
        messages = self.messages(question)
        answer, seen, topics, rounds, outcome, finished = [], {}, [], 0, "ok", False
        try:
            for round_ in range(MAX_TOOL_ROUNDS + 1):
                if self.clock() - started > QUESTION_SECONDS:
                    raise ModelError("délai de la question dépassé")
                allow = round_ < MAX_TOOL_ROUNDS
                turn = None
                for kind, value in self.model.stream(system, messages, schemas, allow_tools=allow):
                    if kind == "text" and value:
                        answer.append(value)
                        yield "text", {"text": value}
                    elif kind == "turn":
                        turn = value
                if turn is None:
                    raise ModelError("tour sans fin")
                tokens["input_tokens"] += turn.input_tokens
                tokens["output_tokens"] += turn.output_tokens
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
            self.journal.add(question.conversation_id, "assistant", text, cards)
            self.close(question, started, rounds, outcome, tokens)
            finished = True
            yield "done", {"conversation_id": question.conversation_id, **tokens,
                           "usage": self.journal.usage(self.daily_limit)}
        except GeneratorExit:  # The phone left: the question ends, its count stays.
            outcome = "interrupted"
            raise
        except AgentError as error:  # The account lost its right during the question.
            outcome = error.code
            yield "error", {"code": error.code, "message": str(error)}
        except ModelError as error:
            outcome = "model_error"
            logger.warning("assistant model error=%s question=%s", error, question.id)
            yield "error", {"code": "model_error",
                            "message": "Le modèle ne répond pas pour l’instant : réessaie dans un moment."}
        finally:
            if not finished:
                self.close(question, started, rounds, outcome, tokens)

    def close(self, question, started, rounds, outcome, tokens):
        duration = int((self.clock() - started) * 1000)
        self.journal.finish(question.id, duration_ms=duration, tool_rounds=rounds,
                            outcome=outcome, **tokens)
        logger.info("assistant question=%s rounds=%d outcome=%s ms=%d in=%d out=%d", question.id,
                    rounds, outcome, duration, tokens["input_tokens"], tokens["output_tokens"])
