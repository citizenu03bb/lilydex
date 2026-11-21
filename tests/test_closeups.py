"""Close-up shots in series (decision 0048): the queue, the shot, the new reading."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_agent_review import (
    MATTE_WITH_REVERSE,
    Stakes,
    card_of,
    imported,
    make_app,
    open_gate,
)
from test_condition_assessment import picture
from test_verification import reading

from pokeprice.closeups import STALE_AFTER


PASSWORD = "Collection-test-2026!"


@pytest.fixture
def env(tmp_path):
    app, readers = make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/setup", json={"username": "pat", "password": PASSWORD})
        client.post("/api/albums", json={"name": "Test"})
        stakes = Stakes()
        app.state.agent_review.inputs = stakes
        yield client, app.state.closeups, readers, stakes


def checked(client, card):
    """The import's own checks on the copy, as the worker runs them."""
    state = client.app.state
    review = state.agent_review
    state.variant_checks.evaluate_new_copy(
        card["id"], "pat", lambda copy_id: review.inputs(copy_id, 1000))
    state.edition_checks.evaluate_new_copy(card["id"], "pat")
    state.conditions.evaluate(card["id"], card_of(client, card)["version"], "pat")
    return card_of(client, card)


def shoot(client, card, view, color=(90, 40, 160), version=None):
    version = version or card_of(client, card)["version"]
    return client.put(
        f"/api/closeups/{card['id']}/shot?version={version}&view={view}",
        content=picture(color), headers={"Content-Type": "image/jpeg"},
    )


def queue(client, **scope):
    response = client.post("/api/closeups/queue", json=scope)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def binder(env):
    """Two imported cards: pocket 2 a possible reverse, pocket 1 corners unreadable."""
    client, closeups, readers, stakes = env
    reverse = imported(client, position=2)
    stakes.snapshot = MATTE_WITH_REVERSE
    readers["finish"].result = reading(artwork="matte")
    checked(client, reverse)
    corners = imported(client, position=1, color=(10, 200, 30))
    readers["finish"].result = reading()
    readers["condition"].quality = "limited"
    checked(client, corners)
    readers["condition"].quality = "adequate"
    return {"reverse": reverse, "corners": corners}


def history(client, card, kind):
    return [e for e in card_of(client, card)["history"] if e["kind"] == kind]


def test_the_queue_follows_the_binder_and_writes_nothing_in_simulation(env, binder):
    client, *_ = env
    before = {k: card_of(client, c)["version"] for k, c in binder.items()}
    result = queue(client, album="Test")
    assert result["apply"] is False and result["cards"] == 2 and result["shots"] == 2
    steps = result["steps"]
    assert [(s["album"], s["page"], s["position"]) for s in steps] == [("Test", 3, 1), ("Test", 3, 2)]
    assert [[v["view"] for v in s["views"]] for s in steps] == [["corner"], ["holo"]]
    assert steps[1]["views"][0]["glint"] is True and steps[1]["views"][0]["side"] == "front"
    assert steps[0]["grid"] == "3x3" and "coins" in steps[0]["views"][0]["reason"]
    # Simulation: no request recorded, no run, no version moved.
    assert client.get("/api/photo-requests").json() == []
    assert client.app.state.agent_review.runs() == []
    assert {k: card_of(client, c)["version"] for k, c in binder.items()} == before


def test_scope_by_copies_or_import_and_admins_only(env, binder):
    client, *_ = env
    only = queue(client, copy_ids=[binder["reverse"]["id"]])
    assert [s["copy_id"] for s in only["steps"]] == [binder["reverse"]["id"]]
    # The import's copies carry its id in their source key (binder:imp:...).
    assert queue(client, import_id="imp")["cards"] == 2
    assert queue(client, import_id="autre")["steps"] == []
    assert client.post("/api/closeups/queue", json={}).status_code == 422
    client.post("/api/users", json={"username": "lily", "password": PASSWORD, "role": "editor"})
    client.post("/api/logout")
    client.post("/api/login", json={"username": "lily", "password": PASSWORD})
    assert client.post("/api/closeups/queue", json={"album": "Test"}).status_code == 403
    assert shoot(client, binder["reverse"], "holo").status_code == 403


def test_the_pocket_is_drawn_on_the_import_grid(env, binder):
    client, *_ = env
    created = client.post("/api/binder-imports", json={"album_name": "Test", "grid": "4x3"})
    assert created.status_code == 201, created.text
    assert {s["grid"] for s in queue(client, album="Test")["steps"]} == {"4x3"}


def test_a_glint_shot_takes_the_glint_path_then_the_agent_reads_again(env, binder):
    client, closeups, readers, _ = env
    card = binder["reverse"]
    response = shoot(client, card, "holo")
    assert response.status_code == 200, response.text
    detail = card_of(client, card)
    assert response.json()["version"] == detail["version"]
    glints = history(client, card, "glint-photo")
    assert len(glints) == 1 and '"photo": "' + detail["photo"] in glints[0]["after_json"]
    assert len(history(client, card, "closeup-shot")) == 1
    # Until its new reading comes back, the card is out of the queue.
    result = queue(client, album="Test")
    assert [s["copy_id"] for s in result["pending"]] == [card["id"]]
    assert card["id"] not in [s["copy_id"] for s in result["steps"]]
    # Matte under the lamp: the glint shot settles the Standard (decision 0047).
    readers["finish"].result = reading(artwork="matte", background_shine="not_visible")
    verdict = closeups.after_shot(card["id"])
    assert verdict["applied"] is False and verdict["outcome"] == "confirm", verdict
    detail = card_of(client, card)
    assert detail["identification_status"] == "review" and not detail["variant_confirmed"]
    assert len(history(client, card, "closeup-review")) == 1
    assert queue(client, album="Test")["pending"] == []
    results = client.post("/api/closeups/results", json={"album": "Test"}).json()
    assert [(r["copy_id"], r["album"], r["shots"], r["verdict"]["outcome"]) for r in results] == [
        (card["id"], "Test", ["holo"], "confirm")
    ]


def test_a_view_shot_once_is_not_asked_again(env, binder):
    client, closeups, readers, _ = env
    card = binder["reverse"]
    shoot(client, card, "holo")
    readers["finish"].result = reading(artwork="matte", background_shine="unclear")
    verdict = closeups.after_shot(card["id"])
    assert verdict["outcome"] == "photo" and verdict["views"] == ["holo"]
    result = queue(client, album="Test")
    assert card["id"] not in [s["copy_id"] for s in result["steps"]]
    assert [h["copy_id"] for h in result["handed"]] == [card["id"]]
    assert "reste en l’état" in result["handed"][0]["reason"]


def test_a_back_shot_completes_the_back_only(env, binder):
    client, *_ = env
    card = binder["corners"]
    front = card_of(client, card)["photo"]
    response = shoot(client, card, "back", (200, 200, 200))
    assert response.status_code == 200, response.text
    detail = card_of(client, card)
    assert detail["photo"] == front and detail["back_photo"]
    assert history(client, card, "glint-photo") == []


def test_a_stale_version_is_refused(env, binder):
    client, *_ = env
    assert shoot(client, binder["corners"], "corner", version=1).status_code == 409


def test_with_the_gate_open_the_new_reading_writes(env, binder):
    client, closeups, readers, _ = env
    open_gate(client)
    card = binder["corners"]
    shoot(client, card, "corner", (12, 190, 40))
    verdict = closeups.after_shot(card["id"])
    assert verdict["applied"] is True and verdict["outcome"] == "confirm", verdict
    detail = card_of(client, card)
    assert detail["identification_status"] == "confirmed"
    assert detail["variant_confirmed"] and detail["condition_confirmed"]


def test_a_failed_reading_is_logged_never_raised(env, binder, monkeypatch):
    client, closeups, *_ = env
    card = binder["corners"]
    shoot(client, card, "corner")
    monkeypatch.setattr(closeups.review, "read_missing", lambda *a: 1 / 0)
    verdict = closeups.after_shot(card["id"])
    assert verdict["outcome"] == "error" and verdict["errors"] == ["ZeroDivisionError"]


def test_the_server_reads_again_after_the_response(tmp_path):
    app, readers = make_app(tmp_path, auto_checks=True)
    with TestClient(app) as client:
        client.post("/api/setup", json={"username": "pat", "password": PASSWORD})
        client.post("/api/albums", json={"name": "Test"})
        app.state.agent_review.inputs = Stakes()
        card = imported(client)
        response = shoot(client, card, "corner")
        assert response.status_code == 200, response.text
        assert len(history(client, card, "closeup-review")) == 1


def test_a_lost_reading_is_started_again_when_the_queue_opens(tmp_path):
    app, readers = make_app(tmp_path, auto_checks=True)
    with TestClient(app) as client:
        client.post("/api/setup", json={"username": "pat", "password": PASSWORD})
        client.post("/api/albums", json={"name": "Test"})
        app.state.agent_review.inputs = Stakes()
        closeups = app.state.closeups
        card = imported(client)
        after_shot = closeups.after_shot
        closeups.after_shot = lambda *a: None  # the service restarts: the work is lost
        assert shoot(client, card, "corner").status_code == 200
        closeups.after_shot = after_shot
        assert history(client, card, "closeup-review") == []

        fresh = queue(client, copy_ids=[card["id"]])
        assert [p["copy_id"] for p in fresh["pending"]] == [card["id"]]
        assert fresh["pending"][0]["stale"] is False and fresh["resumed"] == []
        assert history(client, card, "closeup-review") == []

        real_clock = closeups.clock
        closeups.clock = lambda: real_clock() + STALE_AFTER + timedelta(minutes=1)
        late = queue(client, copy_ids=[card["id"]])
        assert late["resumed"] == [card["id"]]
        assert len(history(client, card, "closeup-review")) == 1
        closeups.clock = real_clock
        assert queue(client, copy_ids=[card["id"]])["pending"] == []


def test_two_readings_of_one_card_wait_for_each_other(env, binder, monkeypatch):
    import threading
    import time

    _, closeups, _, _ = env
    card = binder["corners"]
    inside, most = [0], [0]
    lock = threading.Lock()

    def slow(copy_id, threshold_cents):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        with lock:
            inside[0] -= 1
        return []

    monkeypatch.setattr(closeups.review, "read_missing", slow)
    threads = [threading.Thread(target=closeups.after_shot, args=(card["id"],)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most[0] == 1
