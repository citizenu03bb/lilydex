"""Audit regressions: temporary journals and fake models, without any service."""

import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from test_assistant import ask, env, sse  # noqa: F401

from pokeprice import assistant_tools
from pokeprice.assistant import ConversationErased, Journal, retention_warning
from pokeprice.assistant_signals import drafts, known_values, sanitize
from pokeprice.manage import send_brief


def test_erasure_is_final_for_late_tool_arguments_context_answers_and_flags(tmp_path):
    writer, other_tab = Journal(tmp_path), Journal(tmp_path)
    qid, cid = writer.start("u", None, "fake", daily_limit=10, per_minute=10)
    writer.add(cid, "user", "question privée")
    other_tab.delete("u", cid)
    with pytest.raises(ConversationErased):
        writer.call(qid, "search_copies", {"query": "nom privé"}, 1, "ok")
    with pytest.raises(ConversationErased):
        writer.note_context(qid, {"filters": {"q": "nom privé"}})
    with pytest.raises(ConversationErased):
        writer.add(cid, "assistant", "réponse privée")
    writer.flag(cid, "u", "model_error", note="nom privé")
    with writer.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM assistant_flags").fetchone()[0] == 0
        row = db.execute("SELECT conversation_id,context_json FROM questions").fetchone()
        assert tuple(row) == ("", "{}")
    assert writer.usage(10)["today"]["questions"] == 1


def test_opening_an_old_journal_removes_existing_late_erased_payloads(tmp_path):
    journal = Journal(tmp_path)
    qid, cid = journal.start("u", None, "fake", daily_limit=10, per_minute=10)
    journal.delete("u", cid)
    # The audit reproduced these writes against the old implementation after
    # deletion; the account's quota counter intentionally still exists.
    with journal.connect() as db, db:
        db.execute("INSERT INTO tool_calls(question_id,tool,arguments_json,duration_ms,outcome,created_at) "
                   "VALUES(?,?,?,?,?,?)", (qid, "search_copies", '{"query":"secret"}', 1, "ok", time.time()))
        db.execute("UPDATE questions SET context_json=? WHERE id=?", ('{"filters":{"q":"secret"}}', qid))
    reopened = Journal(tmp_path)
    assert reopened.calls(qid) == []
    assert reopened.context(qid) == {}
    assert reopened.usage(10)["today"]["questions"] == 1


def test_bench_drafts_redact_request_owned_guest_names(tmp_path):
    collection = tmp_path / "collection.sqlite3"
    with sqlite3.connect(collection) as db:
        # These contacts are stored on the request, never in the guest's user
        # row; the sanitizer must know them too. Earlier schemas can omit them.
        db.execute("CREATE TABLE requests(client_email TEXT,client_name TEXT)")
        db.execute("INSERT INTO requests VALUES(?,?)", ("guest@example.test", "Camille-Rayon"))
    text = sanitize("Demande de Camille-Rayon à guest@example.test", known_values(collection))
    assert "Camille-Rayon" not in text and "guest@example.test" not in text


def test_bench_drafts_redact_historical_names_that_differ_from_current_contact(tmp_path):
    collection = tmp_path / "collection.sqlite3"
    identities = json.dumps([
        {"name": "Éloïse Lanterne", "email": "old-contact@example.test", "extra": "unrelated-metadata"},
        {"name": {"nested": "not-a-name"}, "email": ["not-an-address"]},
    ], ensure_ascii=False)
    with sqlite3.connect(collection) as db:
        db.execute("CREATE TABLE requests(client_email TEXT,client_name TEXT,identity_json TEXT)")
        db.executemany("INSERT INTO requests VALUES(?,?,?)", [
            ("current@example.test", "Camille-Rayon", identities),
            ("current@example.test", "Camille-Rayon", "not JSON"),
            ("current@example.test", "Camille-Rayon", '{"name":"not-a-list"}'),
        ])
    journal = Journal(tmp_path)
    qid, cid = journal.start("u", None, "fake", daily_limit=10, per_minute=10)
    asked = journal.add(cid, "user", "Comment traiter la demande de Eloise Lanterne ?")
    journal.flag(cid, "u", "defect", question_id=qid, asked_id=asked,
                 note="ELOISE utilisait old-contact@example.test ; le nom courant diffère.")

    [case] = drafts(tmp_path)["cases"]
    payload = json.dumps(case, ensure_ascii=False)
    for secret in ("Eloise", "Lanterne", "ELOISE", "old-contact@example.test"):
        assert secret not in payload
    assert "demande de" in case["prompt"] and "nom courant diffère" in case["brouillon"]["note"]
    known = known_values(collection)
    assert identities not in known
    assert "unrelated-metadata" not in known and "not-a-name" not in known
    assert all(isinstance(value, str) for value in known)


def test_delete_between_tool_event_and_execution_stops_the_model(env):
    assistant = env["app"].state.assistant
    env["model"].script = [{"calls": [{"name": "search_copies", "args": {"query": "secret"}}]},
                             {"text": "ne doit pas être demandé"}]
    with env["store"].connect() as db:
        uid = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
    question = assistant.prepare(uid, "une question")
    stream = assistant.run(question)
    assert next(stream)[0] == "start"
    assert next(stream)[0] == "tool"
    Journal(env["store"].root).delete(uid, question.conversation_id)
    remaining = list(stream)
    assert remaining[0][0] == "error" and remaining[0][1]["code"] == "conversation_erased"
    assert not any(kind == "done" for kind, _ in remaining)
    assert len(env["model"].seen) == 1
    assert assistant.journal.calls(question.id) == []
    assert assistant.journal.flags() == []


def test_delete_during_tool_execution_never_logs_its_late_arguments(env, monkeypatch):
    assistant = env["app"].state.assistant
    env["model"].script = [{"calls": [{"name": "search_copies", "args": {"query": "secret"}}]},
                             {"text": "ne doit pas être demandé"}]

    def deleting_tool(*args, **kwargs):
        with env["store"].connect() as db:
            uid = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        Journal(env["store"].root).delete(uid)
        return {"found": "résultat privé"}

    monkeypatch.setattr(assistant_tools, "call", deleting_tool)
    events = sse(ask(env["owner"], "une question"))
    assert events[-1][0] == "error" and events[-1][1]["code"] == "conversation_erased"
    assert len(env["model"].seen) == 1
    with assistant.journal.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM assistant_flags").fetchone()[0] == 0


def test_expired_text_never_reaches_chat_or_model_even_when_flagged(env):
    assistant = env["app"].state.assistant
    first = sse(ask(env["owner"], "ancienne question privée"))[-1][1]
    journal = assistant.journal
    with journal.connect() as db, db:
        old = time.time() - 31 * 86400
        db.execute("UPDATE messages SET created_at=?", (old,))
        db.execute("UPDATE questions SET created_at=?", (old,))
        db.execute("UPDATE conversations SET created_at=?,updated_at=?", (old, old))
        uid = db.execute("SELECT user_id FROM conversations").fetchone()[0]
    journal.flag(first["conversation_id"], uid, "model_error", note="à étudier")
    assert env["owner"].get("/api/assistant").json()["conversation"] is None
    assert ask(env["owner"], "suite", conversation_id=first["conversation_id"]).status_code == 404
    assert len(drafts(env["store"].root)["cases"]) == 1
    sse(ask(env["owner"], "question récente"))
    assert "ancienne question privée" not in json.dumps(env["model"].seen[-1], default=str)
    with journal.connect() as db, db:
        db.execute("UPDATE assistant_flags SET created_at=?", (time.time() - 181 * 86400,))
    assert journal.flags() == []
    assert drafts(env["store"].root)["cases"] == []


def test_recent_conversation_excludes_old_messages_from_model_history(env):
    first = sse(ask(env["owner"], "ancien contenu privé"))[-1][1]
    journal = env["app"].state.assistant.journal
    with journal.connect() as db, db:
        db.execute("UPDATE messages SET created_at=?", (time.time() - 31 * 86400,))
    sse(ask(env["owner"], "nouvelle question", conversation_id=first["conversation_id"]))
    assert len(env["model"].seen[-1]["messages"]) == 1


def test_missed_purge_appears_in_the_morning_brief(env):
    journal = env["app"].state.assistant.journal
    _, cid = journal.start("u", None, "fake", daily_limit=10, per_minute=10,
                           at=time.time() - 32 * 86400)
    journal.add(cid, "user", "ancienne", at=time.time() - 32 * 86400)
    assert "retard" in retention_warning(env["store"].root)
    assert "purge" in send_brief(env["store"])["text"]
    journal.purge()
    assert retention_warning(env["store"].root) is None


def test_incomplete_chat_streams_offer_retry_and_keep_the_conversation_id():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root / "tests/assistant_stream_runtime.cjs"),
                    str(root / "src/pokeprice/web/assistant.js")], check=True, capture_output=True, text=True)
