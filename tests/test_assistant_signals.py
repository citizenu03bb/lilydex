"""The chat's failures, captured for the bench (decision 0038): fake model only, no key."""

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_assistant import CLIENT_EMAIL, CLIENT_NAME, ask, env, login, sse  # noqa: F401

from pokeprice.assistant import DEFECT_REPLY, FLAGGED_RETENTION, RETENTION, Journal
from pokeprice.assistant_model import ModelError
from pokeprice.assistant_signals import REPHRASE_SECONDS, defect, drafts, rephrased, sanitize
from pokeprice.manage import write_assistant_drafts

ROOT = Path(__file__).resolve().parents[1]


def flags(store):
    return Journal(store.root).flags()


def done(events):
    assert events[-1][0] == "done", events
    return events[-1][1]


# -- The heuristics -------------------------------------------------------------


def test_defect_is_a_question_that_starts_with_defaut():
    assert defect("Défaut : il dit 3 au lieu de 5") == "il dit 3 au lieu de 5"
    assert defect("  defaut: mauvaise carte") == "mauvaise carte"
    assert defect("DÉFAUT :") == ""
    assert defect("Quel défaut a cette carte ?") is None
    assert defect("Défauts de la carte ?") is None


def test_a_rephrased_question_is_close_and_soon():
    first = "pourquoi le dracaufeu il est pas en vente ?"
    assert rephrased(first, "pourquoi mon dracaufeu n'est pas en vente", 20)
    assert rephrased(first, "Pourquoi le Dracaufeu est-il pas en vente ?", 60)
    # Too late: a new question on the same card, not a retry.
    assert not rephrased(first, "pourquoi mon dracaufeu n'est pas en vente", REPHRASE_SECONDS + 1)
    # A follow-up shares too little.
    assert not rephrased(first, "et la première ?", 10)
    assert not rephrased("combien j'ai vendu cette semaine ?", "qu'est-ce qui m'attend ?", 10)
    # A « Défaut : » report is its own signal.
    assert not rephrased(first, "Défaut : pourquoi le dracaufeu pas en vente", 10)


def test_sanitize_takes_out_ids_amounts_addresses_and_known_names():
    slots = {}
    text = sanitize(f"la demande de {CLIENT_NAME} ({CLIENT_EMAIL}) pour EX-0101 à 12,50 € le 03/11/2026 "
                    "appelle 06 12 34 56 78", {CLIENT_NAME}, slots)
    for secret in (CLIENT_NAME, CLIENT_EMAIL, "EX-0101", "12,50", "03/11", "06 12"):
        assert secret not in text
    assert "<A_REMPLACER_1>" in text and "<EMAIL_1>" in text and "<MONTANT_1>" in text
    # The same value gets the same placeholder across the draft.
    assert sanitize(CLIENT_NAME.lower(), {CLIENT_NAME}, slots) == "<A_REMPLACER_1>"
    assert sanitize("pourquoi le dracaufeu est pas en vente ?") == "pourquoi le dracaufeu est pas en vente ?"


# -- The 👎 ---------------------------------------------------------------------


def test_thumbs_down_under_an_answer_with_a_note(env):
    env["model"].script = [{"text": "Tu as 2 cartes."}]
    answer = done(sse(ask(env["owner"], "combien de cartes ?")))
    message_id = answer["message_id"]
    sent = env["owner"].post(f"/api/assistant/answers/{message_id}/flag", json={"note": "il y en a 3"})
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"message_id": message_id, "flagged": True}
    # A second press replaces the note, one flag per answer.
    env["owner"].post(f"/api/assistant/answers/{message_id}/flag", json={})
    [flag] = flags(env["store"])
    assert flag["kind"] == "thumbs_down" and flag["answer_id"] == message_id and flag["note"] == ""
    assert flag["question_id"] and flag["asked_id"] == message_id - 1
    state = env["owner"].get("/api/assistant").json()
    assert state["conversation"]["flagged"] == [message_id]
    assert [m["id"] for m in state["conversation"]["messages"]] == [message_id - 1, message_id]


def test_thumbs_down_only_on_ones_own_answers(env):
    env["model"].script = [{"text": "Tu as 2 cartes."}]
    message_id = done(sse(ask(env["owner"], "combien de cartes ?")))["message_id"]
    lily = login(env["app"], "lily")
    assert lily.post(f"/api/assistant/answers/{message_id}/flag", json={}).status_code == 404
    # The question itself is not an answer.
    assert env["owner"].post(f"/api/assistant/answers/{message_id - 1}/flag", json={}).status_code == 404
    from fastapi.testclient import TestClient

    assert TestClient(env["app"]).post(f"/api/assistant/answers/{message_id}/flag",
                                       json={}).status_code == 401
    too_long = env["owner"].post(f"/api/assistant/answers/{message_id}/flag", json={"note": "x" * 501})
    assert too_long.status_code == 422
    assert flags(env["store"]) == []


# -- The automatic signals -------------------------------------------------------


def test_a_model_error_is_a_signal(env):
    env["model"].script = [ModelError("boom")]
    events = sse(ask(env["owner"], "qu'est-ce qui m'attend ?"))
    assert events[-1][0] == "error"
    [flag] = flags(env["store"])
    assert flag["kind"] == "model_error" and flag["answer_id"] is None and flag["asked_id"]


def test_a_tool_error_and_the_ceiling_of_rounds_are_signals(env):
    env["model"].script = lambda system, messages, tools, allow: (
        {"calls": [{"name": "get_copy", "args": {"copy_id": "inexistant"}}]} if allow
        else {"calls": [{"name": "todo_queue", "args": {}}], "text": "Je n’ai pas trouvé."})
    answer = done(sse(ask(env["owner"], "ouvre la carte inexistant")))
    kinds = {f["kind"]: f for f in flags(env["store"])}
    assert set(kinds) == {"tool_error", "max_rounds"}
    assert kinds["tool_error"]["note"] == "get_copy : not_found"
    assert all(f["answer_id"] == answer["message_id"] for f in kinds.values())


def test_a_question_asked_again_flags_the_previous_answer(env):
    env["model"].script = [{"text": "Je ne sais pas."}, {"text": "Elle attend une photo."}]
    first = done(sse(ask(env["owner"], "pourquoi le gourgeist il est pas en vente ?")))
    second = done(sse(ask(env["owner"], "pourquoi mon gourgeist n'est pas en vente",
                          conversation_id=first["conversation_id"])))
    [flag] = flags(env["store"])
    assert flag["kind"] == "rephrased" and flag["answer_id"] == first["message_id"]
    assert flag["answer_id"] != second["message_id"]


def test_a_follow_up_is_not_a_rephrasing(env):
    env["model"].script = [{"text": "Deux cartes."}, {"text": "La première est en vente."}]
    first = done(sse(ask(env["owner"], "combien de gourgeist j'ai ?")))
    sse(ask(env["owner"], "et la première ?", conversation_id=first["conversation_id"]))
    assert flags(env["store"]) == []


def test_a_defect_report_is_noted_and_never_sent_to_the_model(env):
    env["model"].script = [{"text": "Tu as 2 cartes."}]
    first = done(sse(ask(env["owner"], "combien de cartes ?")))
    seen = len(env["model"].seen)
    events = sse(ask(env["owner"], "Défaut : il y en a 3, pas 2",
                     conversation_id=first["conversation_id"]))
    assert len(env["model"].seen) == seen
    assert "".join(d["text"] for k, d in events if k == "text") == DEFECT_REPLY
    assert done(events)["input_tokens"] == 0
    [flag] = flags(env["store"])
    assert flag["kind"] == "defect" and flag["note"] == "il y en a 3, pas 2"
    # Attached to the answer it reports.
    assert flag["answer_id"] == first["message_id"]


# -- Retention ------------------------------------------------------------------


def test_flagged_conversations_escape_the_30_days_purge(env):
    env["model"].script = [{"text": "Réponse fausse."}, {"text": "Réponse juste."}]
    kept = done(sse(ask(env["owner"], "combien de cartes ?")))
    gone = done(sse(ask(env["owner"], "qu'est-ce qui m'attend ?")))
    env["owner"].post(f"/api/assistant/answers/{kept['message_id']}/flag", json={"note": "faux"})
    journal = Journal(env["store"].root)
    later = time.time() + RETENTION.total_seconds() + 3600
    result = journal.purge(at=later)
    assert result["conversations"] == 1 and len(journal.flags()) == 1
    with sqlite3.connect(Path(env["store"].root) / "assistant.sqlite3") as db:
        ids = {r[0] for r in db.execute("SELECT id FROM conversations")}
        assert ids == {kept["conversation_id"]} and gone["conversation_id"] not in ids
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
    # Not for ever: the bench has six months to take it.
    result = journal.purge(at=time.time() + FLAGGED_RETENTION.total_seconds() + 3600)
    assert result["conversations"] == 1
    assert journal.flags() == []


def test_a_flagged_conversation_stays_erasable_by_its_author(env):
    env["model"].script = [{"text": "Réponse fausse."}]
    answer = done(sse(ask(env["owner"], "combien de cartes ?")))
    env["owner"].post(f"/api/assistant/answers/{answer['message_id']}/flag", json={"note": "faux"})
    assert env["owner"].delete("/api/assistant/conversations").json() == {"deleted": 1}
    assert flags(env["store"]) == []


def test_the_flag_table_migrates_an_existing_journal(tmp_path):
    with sqlite3.connect(tmp_path / "assistant.sqlite3") as db:
        from pokeprice.assistant import SCHEMA

        db.executescript(SCHEMA)
    Journal(tmp_path)
    Journal(tmp_path)  # idempotent
    with sqlite3.connect(tmp_path / "assistant.sqlite3") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='assistant_flags'").fetchone()


# -- Drafts for the bench --------------------------------------------------------


def load_bench():
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "bench" / "assistant" / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_run"] = module
    spec.loader.exec_module(module)
    return module


def flagged_exchange(env):
    card = env["cards"][0]
    env["model"].script = [
        {"calls": [{"name": "get_copy", "args": {"copy_id": card["id"]}}]},
        {"text": f"La demande de {CLIENT_NAME} porte sur [{card['id']}] à 3 €."},
    ]
    question = f"où en est la demande de {CLIENT_NAME} ({CLIENT_EMAIL}) sur {card['id']} à 3 € ?"
    answer = done(sse(ask(env["owner"], question)))
    env["owner"].post(f"/api/assistant/answers/{answer['message_id']}/flag",
                      json={"note": f"{CLIENT_NAME} a payé 3 €, la carte est vendue"})
    return card


def test_drafts_carry_no_real_datum(env):
    card = flagged_exchange(env)
    journal = Path(env["store"].root) / "assistant.sqlite3"
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    result = drafts(env["store"].root)
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before  # read-only
    [case] = result["cases"]
    text = json.dumps(result, ensure_ascii=False)
    for secret in (CLIENT_NAME, CLIENT_EMAIL, card["id"], "3 €", "Ondine"):
        assert secret.lower() not in text.lower(), secret
    assert case["draft"] is True and case["id"] == "brouillon-001"
    assert case["brouillon"]["signals"] == ["thumbs_down"]
    assert case["brouillon"]["calls"] == [{"tool": "get_copy", "args": {"copy_id": "<COPY_ID>"},
                                           "outcome": "ok"}]
    # The same name gets the same placeholder in the question and in the note.
    name = case["brouillon"]["note"].split(" ")[0]
    assert name.startswith("<A_REMPLACER_") and name in case["prompt"]
    assert case["prompt"].startswith("où en est la demande de")
    # The answer, which carries the collection's data, never leaves.
    assert "porte sur" not in text


def test_the_bench_refuses_a_draft_left_as_is(env, tmp_path):
    flagged_exchange(env)
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps(drafts(env["store"].root), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="brouillon"):
        load_bench().load_cases(path)


def test_the_command_reads_an_explicit_base_and_never_overwrites(env, tmp_path, capsys):
    flagged_exchange(env)
    write_assistant_drafts(env["store"].root)
    assert json.loads(capsys.readouterr().out)["cases"][0]["draft"] is True
    target = tmp_path / "drafts.json"
    write_assistant_drafts(env["store"].root, target)
    assert json.loads(target.read_text(encoding="utf-8"))["cases"]
    with pytest.raises(FileExistsError):
        write_assistant_drafts(env["store"].root, target)
    with pytest.raises(SystemExit, match="Pas de journal"):
        write_assistant_drafts(tmp_path / "vide")
    refused = subprocess.run([sys.executable, "-m", "pokeprice.manage", "assistant-drafts"],
                             capture_output=True, text=True, cwd=tmp_path)
    assert refused.returncode == 2 and "--data explicite" in refused.stderr
