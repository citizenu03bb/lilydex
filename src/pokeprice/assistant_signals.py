"""The chat's failures, captured for the bench (decision 0038).

Two sources mark an exchange: the 👎 of the person who asked, with a free
note, and the automatic signals the server sees itself (a model or tool error,
the ceiling of tool rounds, a question asked again in other words, a
« Défaut : … » report). They are kept in ``assistant.sqlite3`` beside the
exchange (``assistant.Journal``) and escape the 30 days' purge.

``drafts`` turns them into draft cases of ``bench/assistant/commands.json``.
It opens the files read-only, writes nothing, and puts a placeholder in place
of every identifier, amount, date, address and known name: a draft never
carries a real datum of the collection or of a client.
"""

import json
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

KINDS = ("thumbs_down", "defect", "model_error", "tool_error", "max_rounds", "rephrased")
MAX_NOTE = 500
# A question asked again within this delay after the answer, and close enough to the
# previous one, is taken for a rephrasing: the answer did not help.
REPHRASE_SECONDS = 180
REPHRASE_RATIO = 0.6
DEFECT = re.compile(r"^\s*d[ée]faut\s*:\s*", re.IGNORECASE)
TODO = "<À COMPLÉTER>"
PLACEHOLDER = re.compile(r"(<[A-Z_]+_\d+>)")
STOPWORDS = frozenset(
    "les des une est pas que qui quoi dans pour sur avec mes mon ma tes ton ta son sa ses "
    "elle il ils elles moi toi cette ces cet quel quelle quels quelles combien comment pourquoi "
    "est-ce estce alors donc mais ou et ya y a de la le du au aux en un je tu on nous vous "
    "ai as avez avons sont ont fait faire peux peut veux".split())


def fold(text):
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def defect(text):
    """The note of a « Défaut : … » report, or None for an ordinary question."""
    match = DEFECT.match(text or "")
    return text[match.end():].strip()[:MAX_NOTE] if match else None


def words(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", fold(text)) if w not in STOPWORDS}


def rephrased(previous, current, elapsed):
    """True when ``current`` repeats ``previous`` in other words, soon after its answer.

    Both conditions: the question comes back within ``REPHRASE_SECONDS``, and
    either half its content words are shared or the two texts read alike. A
    follow-up (« et la première ? ») shares too little to count.
    """
    if elapsed is None or elapsed < 0 or elapsed > REPHRASE_SECONDS:
        return False
    if defect(current) is not None:
        return False
    a, b = words(previous), words(current)
    if not a or not b:
        return False
    overlap = len(a & b) / len(a | b)
    ratio = SequenceMatcher(None, fold(previous).strip(), fold(current).strip()).ratio()
    return overlap >= REPHRASE_RATIO - 0.1 or ratio >= REPHRASE_RATIO + 0.15


# -- Drafts for the bench ------------------------------------------------------

PATTERNS = (
    # Order matters: the longest shapes first, so a date is not read as amounts.
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("LIEN", re.compile(r"https?://\S+")),
    ("ID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
    ("DATE", re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")),
    ("TELEPHONE", re.compile(r"(?:\+\d{1,3}[\s.]?)?(?:\d[\s.]?){9,}\d")),
    ("MONTANT", re.compile(r"\d+(?:[.,]\d+)?\s?(?:€|eur(?:os?)?\b)", re.I)),
    ("ID", re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{6,}\b")),
    ("NOMBRE", re.compile(r"\b\d{3,}\b")),
)


def known_values(collection):
    """Names, addresses and ids of the base, to take out of a draft wherever they appear."""
    found = set()
    if not collection or not Path(collection).exists():
        return found
    queries = (
        "SELECT username, email, display_name FROM users",
        "SELECT id FROM copies",
        "SELECT id, title FROM listings",
        "SELECT id, message FROM requests",
    )
    with sqlite3.connect(f"file:{Path(collection)}?mode=ro", uri=True) as db:
        for query in queries:
            try:
                rows = db.execute(query).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                for value in row:
                    if not isinstance(value, str):
                        continue
                    value = value.strip()
                    if len(value) >= 3:
                        found.add(value)
                    # A display name also appears by its parts (« la demande de Martin »).
                    if " " in value and "@" not in value and len(value) < 60:
                        found.update(p for p in value.split() if len(p) >= 3)
    return found


def sanitize(text, known=(), slots=None):
    """Replace every identifier, amount, date, address and known name by a placeholder.

    ``slots`` numbers the placeholders across one draft: the same value gets
    the same placeholder in the prompt, the note and the tool arguments.
    """
    slots = {} if slots is None else slots
    text = str(text or "")

    def slot(kind, value):
        key = (kind, fold(value))
        if key not in slots:
            slots[key] = f"<{kind}_{sum(1 for k in slots if k[0] == kind) + 1}>"
        return slots[key]

    # Known values, the longest first, matched without case or accents.
    folded = fold(text)
    for value in sorted({fold(v) for v in known}, key=len, reverse=True):
        start = 0
        while value and (index := folded.find(value, start)) >= 0:
            end = index + len(value)
            before = folded[index - 1] if index else " "
            after = folded[end] if end < len(folded) else " "
            if before.isalnum() or after.isalnum():
                start = end
                continue
            mark = slot("A_REMPLACER", value)
            text = text[:index] + mark + text[end:]
            folded = folded[:index] + fold(mark) + folded[end:]
            start = index + len(mark)
    for kind, pattern in PATTERNS:
        # A placeholder already set is left whole.
        parts = PLACEHOLDER.split(text)
        text = "".join(part if PLACEHOLDER.fullmatch(part)
                       else pattern.sub(lambda m, k=kind: slot(k, m.group(0)), part)
                       for part in parts)
    return text


def arguments(values, known, slots):
    """Tool arguments with every text value replaced; enums, booleans and bounds stay."""
    out = {}
    for key, value in (values or {}).items():
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value if key in ("limit", "days", "offset") else f"<NOMBRE_{key}>"
        elif isinstance(value, str) and re.fullmatch(r"[a-z_]{2,30}", value) and key not in (
                "query", "copy_id", "listing_id", "request_id", "name", "since", "until"):
            out[key] = value  # an enum value (status, kind), never a datum
        else:
            out[key] = f"<{key.upper()}>"
    return out


def drafts(directory, *, limit=200):
    """The flagged exchanges of ``directory`` as draft bench cases; reads only."""
    directory = Path(directory)
    journal = directory / "assistant.sqlite3"
    if not journal.exists():
        raise FileNotFoundError(f"Pas de journal du chat dans {directory}.")
    known = known_values(directory / "collection.sqlite3")
    cases = []
    with sqlite3.connect(f"file:{journal}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        try:
            flagged = db.execute(
                "SELECT question_id, conversation_id, MIN(created_at) at, "
                "GROUP_CONCAT(kind) kinds, GROUP_CONCAT(note, ' / ') notes FROM assistant_flags "
                "GROUP BY COALESCE(question_id, conversation_id) ORDER BY at LIMIT ?",
                (limit,)).fetchall()
        except sqlite3.OperationalError:
            flagged = []
        for index, row in enumerate(flagged, 1):
            slots = {}
            question = db.execute(
                "SELECT created_at, outcome, tool_rounds FROM questions WHERE id=?",
                (row["question_id"],)).fetchone() if row["question_id"] else None
            prompt = ""
            if question:
                # The question is the user message that opened this exchange.
                found = db.execute(
                    "SELECT text FROM messages WHERE conversation_id=? AND role='user' "
                    "AND created_at<=? ORDER BY created_at DESC, id DESC LIMIT 1",
                    (row["conversation_id"], question["created_at"] + 1)).fetchone()
                prompt = found["text"] if found else ""
            calls = [] if not row["question_id"] else [
                {"tool": c["tool"], "args": arguments(json.loads(c["arguments_json"] or "{}"),
                                                      known, slots), "outcome": c["outcome"]}
                for c in db.execute("SELECT tool, arguments_json, outcome FROM tool_calls "
                                    "WHERE question_id=? ORDER BY id", (row["question_id"],))]
            kinds = sorted(set((row["kinds"] or "").split(",")) - {""})
            notes = [n for n in (row["notes"] or "").split(" / ") if n]
            cases.append({
                "id": f"brouillon-{index:03d}",
                "category": TODO,
                "draft": True,
                "prompt": sanitize(prompt, known, slots) or TODO,
                "expect": {"tool": TODO, "args": {}},
                "brouillon": {
                    "signals": kinds,
                    "note": sanitize(" / ".join(notes), known, slots),
                    "outcome": question["outcome"] if question else None,
                    "tool_rounds": question["tool_rounds"] if question else None,
                    "calls": calls,
                },
            })
    return {
        "_note": ("Brouillons tirés des échanges signalés du chat (fiche 0038). Chaque <…> est un "
                  "emplacement à compléter avec une donnée synthétique de fixtures.json ; retirer "
                  "\"draft\" et \"brouillon\" une fois le cas écrit, avant de le copier dans "
                  "commands.json."),
        "cases": cases,
    }
