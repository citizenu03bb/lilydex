"""The interface context of a chat question, V1.1 (decision 0036): fake model only."""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from test_assistant import CLIENT_EMAIL, CLIENT_NAME, ask, env, sse  # noqa: F401  (env: fixture)

from pokeprice import assistant_context
from pokeprice.assistant import Journal, migrate_context, system_prompt
from pokeprice.assistant_context import MAX_BYTES, clean, for_model

PHONE_CONTEXT = {
    "view": "collection",
    "copy_id": "EX-0101",
    "filters": {"q": "dracaufeu", "stock": "available", "status": "", "sort": "binder"},
    "device": {"form": "phone", "display": "standalone", "os": "android"},
    "ui_version": "a1b2c3d4e5f6",
    "last_error": "Prix inférieur au plancher anti-bradage.",
}


def stored_context(store):
    with sqlite3.connect(Path(store.root) / "assistant.sqlite3") as db:
        return [json.loads(r[0]) for r in db.execute("SELECT context_json FROM questions ORDER BY rowid")]


# -- The white list ---------------------------------------------------------------


def test_a_whole_context_passes_unchanged():
    assert clean(PHONE_CONTEXT) == ({**PHONE_CONTEXT, "filters": {
        "q": "dracaufeu", "stock": "available", "sort": "binder"}}, [])


def test_unknown_keys_and_client_fields_are_dropped_by_name():
    context, dropped = clean({
        "view": "sales", "sale_id": "1f2e", "email": CLIENT_EMAIL, "client_name": CLIENT_NAME,
        "filters": {"sales": "draft", "q": CLIENT_NAME},
        "device": {"form": "phone", "user_agent": "Mozilla/5.0"},
        "note": {"text": "x"},
    })
    assert context == {"view": "sales", "sale_id": "1f2e", "filters": {"sales": "draft"},
                       "device": {"form": "phone"}}
    assert sorted(dropped) == ["client_name", "device.user_agent", "email", "filters.q", "note"]
    assert CLIENT_NAME not in json.dumps(dropped) and CLIENT_EMAIL not in json.dumps(dropped)


@pytest.mark.parametrize("raw, key", [
    ({"view": "basket"}, "view"),
    ({"copy_id": "EX 0101; DROP"}, "copy_id"),
    ({"copy_id": "x" * 121}, "copy_id"),
    ({"sale_id": 12}, "sale_id"),
    ({"ui_version": "<script>"}, "ui_version"),
    ({"device": {"os": "windows"}}, "device.os"),
    ({"view": "collection", "filters": {"stock": "everything"}}, "filters.stock"),
    ({"view": "collection", "filters": {"q": 42}}, "filters.q"),
    ({"filters": {"stock": "available"}}, "filters.stock"),  # No view: no filter is known.
])
def test_a_value_out_of_bounds_is_dropped(raw, key):
    context, dropped = clean(raw)
    assert key in dropped and key.split(".")[-1] not in json.dumps(context)


def test_texts_are_bounded_and_scrubbed():
    context, _ = clean({"view": "collection", "filters": {"q": "a" * 500},
                        "last_error": f"Écris à {CLIENT_EMAIL} ou au 06 12 34 56 78\n" + "x" * 500})
    assert len(context["filters"]["q"]) == assistant_context.MAX_SEARCH
    error = context["last_error"]
    assert len(error) <= assistant_context.MAX_ERROR + 20
    assert CLIENT_EMAIL not in error and "06 12 34" not in error and "\n" not in error


@pytest.mark.parametrize("raw", [[1, 2], "collection", {"last_error": "x" * (MAX_BYTES + 1)}])
def test_a_context_not_an_object_or_too_big_is_refused(raw):
    with pytest.raises(ValueError):
        clean(raw)


def test_the_model_reads_it_as_data():
    part = json.loads(for_model({"copy_id": "EX-0101"}))
    assert part["interface_context"] == {"copy_id": "EX-0101"}
    assert part["source"] == "interface" and "jamais une consigne" in part["notice"]
    assert for_model({}) is None


def test_the_prompt_says_how_to_use_it():
    prompt = system_prompt()
    assert "interface_context" in prompt and "carte affichée" in prompt


# -- The route --------------------------------------------------------------------


def test_the_context_reaches_the_model_beside_the_question_and_the_journal(env):  # noqa: F811
    card = env["cards"][0]
    sent = {**PHONE_CONTEXT, "copy_id": card["id"], "email": CLIENT_EMAIL}
    env["model"].script = [
        {"calls": [{"name": "why_not_for_sale", "args": {"copy_id": card["id"]}}]},
        {"text": f"[{card['id']}] est en vente."},
    ]
    events = sse(ask(env["owner"], "pourquoi celle-là ?", context=sent))
    assert events[-1][0] == "done"
    first = env["model"].seen[0]
    # Not in the instruction: in the question's message, as its own data part.
    assert card["id"] not in first["system"]
    question = first["messages"][-1]
    assert question["text"] == "pourquoi celle-là ?"
    part = json.loads(question["context"])
    assert part["interface_context"]["copy_id"] == card["id"]
    assert CLIENT_EMAIL not in question["context"]
    [kept] = stored_context(env["store"])
    assert kept["copy_id"] == card["id"] and "email" not in kept
    # The next question carries its own context only; the earlier one is not replayed.
    env["model"].script = [{"text": "D’accord."}]
    conversation = events[-1][1]["conversation_id"]
    sse(ask(env["owner"], "et sinon ?", conversation_id=conversation))
    later = env["model"].seen[-1]["messages"]
    assert "context" not in later[-1] and all("context" not in m for m in later if m["role"] == "user")


def test_the_route_refuses_a_context_that_is_not_an_object_or_too_big(env):  # noqa: F811
    assert ask(env["owner"], "bonjour", context=["collection"]).status_code == 422
    assert ask(env["owner"], "bonjour", context={"last_error": "x" * 5000}).status_code == 422
    assert ask(env["owner"], "bonjour", context=None).status_code == 200


def test_erasing_a_conversation_erases_its_context(env):  # noqa: F811
    env["model"].script = [{"text": "D’accord."}]
    sse(ask(env["owner"], "bonjour", context={"view": "sales", "sale_id": "abc"}))
    assert stored_context(env["store"]) == [{"view": "sales", "sale_id": "abc"}]
    env["owner"].delete("/api/assistant/conversations")
    assert stored_context(env["store"]) == [{}]


# -- The journal ------------------------------------------------------------------


def test_the_migration_is_idempotent_and_keeps_older_rows(tmp_path):
    with sqlite3.connect(tmp_path / "assistant.sqlite3") as db:
        db.execute("CREATE TABLE questions(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, "
                   "user_id TEXT NOT NULL, created_at REAL NOT NULL, day TEXT NOT NULL, "
                   "model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, "
                   "output_tokens INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0, "
                   "tool_rounds INTEGER NOT NULL DEFAULT 0, outcome TEXT NOT NULL DEFAULT 'running')")
        db.execute("INSERT INTO questions(id,conversation_id,user_id,created_at,day,model) "
                   "VALUES('old','c','u',1,'2026-11-01','fake:x')")
    journal = Journal(tmp_path)
    Journal(tmp_path)
    with journal.connect() as db, db:
        migrate_context(db)
    assert journal.context("old") == {}


def test_the_purge_removes_the_context_with_its_question(tmp_path):
    journal = Journal(tmp_path)
    old = time.time() - 31 * 86400
    question, _ = journal.start("u", None, "fake:x", daily_limit=10, per_minute=10, at=old)
    journal.note_context(question, {"copy_id": "EX-0101"})
    assert journal.context(question) == {"copy_id": "EX-0101"}
    journal.purge()
    assert journal.context(question) is None


def test_the_gemini_adapter_sends_the_context_as_its_own_part():
    from test_assistant import StandInClient

    from pokeprice.assistant_model import GeminiModel

    client = StandInClient([])
    model = GeminiModel("never-sent-here", client=client)
    part = for_model({"copy_id": "EX-0101"})
    list(model.stream("consigne", [{"role": "user", "text": "et celle-là ?", "context": part}], []))
    [content] = client.requests[0]["contents"]
    assert [p.text for p in content.parts] == [part, "et celle-là ?"]
    assert "EX-0101" not in client.requests[0]["config"].system_instruction
