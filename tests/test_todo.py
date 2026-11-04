"""The management assistant: the brief, the « À toi » queue and the pushed brief."""

import sys

import pytest
from fastapi.testclient import TestClient
from test_reservations import activate, client_of, shop, signup  # noqa: F401 - fixture

from pokeprice.manage import main, send_brief
from pokeprice.todo import Todo, brief_text, parse_since
from pokeprice.webapp import create_app

assert shop  # The fixture is used by name below.


def request_cards(admin, store, listings, email="sacha@example.org"):
    signup(store, email)
    activate(admin, email)
    me = client_of(store, email)
    sent = me.post("/api/me/requests", json={"listing_ids": [listings[0]["id"], listings[1]["id"]]})
    assert sent.status_code == 201, sent.text
    return sent.json()


def ask_photo(store, card, view="back", reason="Le verso manque."):
    with store.connect(write=True) as db:
        store.event(db, card["id"], "agent:revue", "photo-request", "Photo demandée", {}, {
            "run_id": "run-1", "view": view, "reason": reason,
            "photos": {"photo": card["photo"] or "", "back_photo": card["back_photo"] or ""},
        })


def test_an_empty_day_waits_for_nothing(shop):
    admin, *_ = shop
    brief = admin.get("/api/todo").json()
    assert brief["waiting"] == [] and brief["minutes"] == 0
    assert brief["done_since"]["requests"] == {"received": 0, "answered": {}}
    # The three listings of the fixture were published a moment ago.
    assert brief["done_since"]["listings"]["published"] == 3


def test_a_request_then_its_lot_follow_the_queue_until_shipped(shop):
    admin, store, listings = shop
    request = request_cards(admin, store, listings)
    waiting = admin.get("/api/todo").json()["waiting"]
    assert [i["kind"] for i in waiting] == ["request"]
    item = waiting[0]
    assert item["title"] == "Demande : 2 cartes, 4,70 €" and item["minutes"] == 3
    assert item["action"] == {"view": "sales", "target": f"demande-{request['id']}",
                              "request_id": request["id"]}
    # Nothing in the queue names the client.
    assert "sacha" not in str(waiting).lower()

    staff_view = admin.get("/api/requests").json()[0]
    accepted = admin.post(
        f"/api/requests/{request['id']}/accept",
        json={"expected_version": staff_view["version"], "listing_ids": [listings[0]["id"]]},
    ).json()
    waiting = admin.get("/api/todo").json()["waiting"]
    assert [i["kind"] for i in waiting] == ["payment"]
    assert waiting[0]["action"]["target"] == f"vente-{accepted['sale_id']}"
    assert "Vérifier si le paiement" in waiting[0]["reason"]

    sale = next(s for s in admin.get("/api/sales").json() if s["id"] == accepted["sale_id"])
    sale = admin.patch(f"/api/sales/{sale['id']}", json={
        "expected_version": sale["version"], "status": "sold", "paid": True, "reason": "Payé"
    }).json()
    brief = admin.get("/api/todo").json()
    assert [i["kind"] for i in brief["waiting"]] == ["ship"]
    assert brief["minutes"] == 10
    done = brief["done_since"]
    assert done["requests"] == {"received": 1, "answered": {"partially_accepted": 1}}
    assert done["sales"]["transitions"] == {"reserved": 1, "sold": 1}
    assert done["sales"]["sold_cents"] == 120

    admin.patch(f"/api/sales/{sale['id']}", json={
        "expected_version": sale["version"], "status": "shipped", "reason": "Postée"
    })
    assert admin.get("/api/todo").json()["waiting"] == []


def test_photos_follow_the_binder_and_come_after_money(shop):
    admin, store, listings = shop
    cards = admin.get("/api/copies", params={"limit": 100}).json()["items"]
    cards = sorted(cards, key=lambda c: (c["page"], c["position"]))
    later, sooner = cards[-1], cards[0]
    ask_photo(store, later)
    ask_photo(store, sooner, view="corner", reason="Les coins sont flous.")
    request_cards(admin, store, listings)
    waiting = admin.get("/api/todo").json()["waiting"]
    assert [i["kind"] for i in waiting] == ["request", "photo", "photo"]
    assert [i["order"] for i in waiting] == [0, 1, 2]
    first = waiting[1]
    assert first["data"]["copy_id"] == sooner["id"] and first["reason"] == "Les coins sont flous."
    assert first["action"] == {"view": "collection", "copy_id": sooner["id"],
                               "target": f"photo-request-{sooner['id']}-front"}
    assert waiting[2]["action"]["target"] == f"photo-request-{later['id']}-back"
    # The queue lists exactly what the « Photos à reprendre » panel lists.
    panel = admin.get("/api/photo-requests").json()
    assert [r["copy_id"] for r in panel] == [i["data"]["copy_id"] for i in waiting[1:]]


def test_floor_waivers_join_the_queue_after_the_requests(shop):
    """The floor service (decision 0030) is one more source of the queue."""
    admin, store, listings = shop
    open_requests = [{"id": "f1", "title": "", "copy_ids": ["c1"],
                      "items": [{"name": "Dracaufeu", "number": "4/102"}],
                      "price_cents": 900, "floor_cents": 1200, "current_floor_cents": 1500,
                      "reason": "Offre Vinted."}]
    todo = Todo(store, floor_requests=lambda: open_requests)
    request_cards(admin, store, listings)
    waiting = todo.waiting()
    assert [i["kind"] for i in waiting] == ["request", "floor"]
    floor = waiting[1]
    assert floor["title"] == "Dracaufeu 4/102" and floor["minutes"] == 2
    assert floor["reason"] == "9,00 € demandé, plancher 15,00 €. Offre Vinted."
    assert floor["action"]["target"] == "floor-request-f1"
    assert "floor" not in Todo(store).sources
    # The application plugs the real service in.
    assert "floor" in create_app(store.root).state.todo.sources


def test_done_since_counts_agent_runs_and_lots_but_not_undone_ones(shop):
    admin, store, listings = shop
    with store.connect(write=True) as db:
        for run_id, kind in (("kept", "agent-review"), ("gone", "agent-review"),
                             ("gone", "agent-review-undo")):
            store.event(db, None, "agent:revue", kind, "Passage", {}, {
                "run_id": run_id, "confirmed": [{"copy_id": "a"}, {"copy_id": "b"}],
                "photo_requests": 1,
            })
    free = [c for c in admin.get("/api/copies", params={"limit": 100}).json()["items"]
            if c["identification_status"] == "confirmed" and c["stock_state"] == "available"]
    free = [c for c in free if not admin.get(f"/api/copies/{c['id']}/listing").json()["listing"]]
    lot = admin.post("/api/listings", json={
        "copy_ids": [free[0]["id"], free[1]["id"]], "lot": True, "price_eur": "5", "title": "Lot"
    })
    assert lot.status_code == 201, lot.text
    admin.post(f"/api/listings/{listings[2]['id']}/unpublish",
               json={"expected_version": listings[2]["version"], "reason": "Retrait"})
    done = admin.get("/api/todo").json()["done_since"]
    assert done["agent"] == {"passes": 1, "confirmed": 2, "photos_asked": 1}
    assert done["listings"] == {"published": 4, "lots": 1, "cards": 5, "unpublished": 1}
    # A later start leaves everything out.
    later = admin.get("/api/todo", params={"since": "2999-01-01"}).json()["done_since"]
    assert later["agent"]["passes"] == 0 and later["listings"]["published"] == 0
    assert admin.get("/api/todo", params={"since": "hier"}).status_code == 422


def test_the_queue_is_for_editors(shop):
    admin, store, _ = shop
    assert admin.post("/api/users", json={
        "username": "lecture", "password": "Collection-test-2026!", "role": "reader"
    }).status_code == 201
    with TestClient(create_app(store.root)) as reader:
        assert reader.get("/api/todo").status_code == 401
        reader.post("/api/login", json={"username": "lecture", "password": "Collection-test-2026!"})
        assert reader.get("/api/todo").status_code == 403


def test_since_reads_a_date_as_utc():
    assert parse_since("2026-11-03") == "2026-11-03T00:00:00+00:00"
    assert parse_since("2026-11-03T08:00:00+01:00") == "2026-11-03T07:00:00+00:00"


def test_the_brief_text_counts_without_naming_anyone():
    brief = {
        "minutes": 13, "waiting": [{"kind": "request"}, {"kind": "ship"}],
        "done_since": {
            "agent": {"passes": 1, "confirmed": 4, "photos_asked": 0},
            "listings": {"published": 2, "lots": 1, "cards": 3, "unpublished": 0},
            "sales": {"transitions": {"sold": 1}, "sold_cents": 1250},
            "requests": {"received": 1, "answered": {}},
        },
    }
    title, body = brief_text(brief)
    assert title == "À toi : 2 choses, environ 13 min"
    assert body == (
        "Fait : 4 carte(s) confirmée(s) par l’agent, 2 annonce(s) publiée(s), "
        "1 vente(s), 12,50 €, 1 demande(s) reçue(s).\n"
        "À toi : 1 demande(s) à répondre, 1 lot(s) à expédier."
    )
    empty = {**brief, "waiting": [], "minutes": 0}
    assert brief_text(empty)[0] == "Rien ne t’attend aujourd’hui"


def test_the_brief_counts_photos_asked_and_requests_answered():
    """An agent pass that only asks for photos is still something done."""
    brief = {
        "minutes": 5, "waiting": [{"kind": "photo"}] * 5,
        "done_since": {
            "agent": {"passes": 2, "confirmed": 0, "photos_asked": 5},
            "listings": {"published": 0, "lots": 0, "cards": 0, "unpublished": 0},
            "sales": {"transitions": {}, "sold_cents": 0},
            "requests": {"received": 0, "answered": {"refused": 2}},
        },
    }
    assert brief_text(brief)[1].splitlines()[0] == (
        "Fait : 5 photo(s) demandée(s) par l’agent, 2 demande(s) traitée(s)."
    )
    idle = {**brief, "done_since": {**brief["done_since"],
            "agent": {"passes": 1, "confirmed": 0, "photos_asked": 0},
            "requests": {"received": 0, "answered": {}}}}
    assert brief_text(idle)[1].splitlines()[0] == "Fait : 1 passage(s) de l’agent, sans changement."
    nothing = {**idle, "done_since": {**idle["done_since"], "agent": {"passes": 0, "confirmed": 0}}}
    assert brief_text(nothing)[1].splitlines()[0] == "Fait : rien de nouveau."


class Channel:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.sent = name, fail, []

    def send(self, title, body, link):
        if self.fail:
            raise OSError("hors ligne")
        self.sent.append((title, body, link))


def test_the_brief_prints_and_only_notifies_on_request(shop):
    admin, store, listings = shop
    request_cards(admin, store, listings)
    printed = send_brief(store)
    assert printed["waiting"] == 1 and "notified" not in printed
    push, mail = Channel("ntfy"), Channel("email", fail=True)
    sent = send_brief(store, "2026-01-01", notify=True, channels=[push, mail],
                      origin="https://cartes.example/")
    assert sent["notified"] == ["ntfy"] and sent["errors"] == {"email": "OSError"}
    title, body, link = push.sent[0]
    assert title == "À toi : 1 chose, environ 3 min"
    assert link == "https://cartes.example/gestion" and body.endswith(link)
    assert "sacha" not in body.lower()
    with pytest.raises(ValueError, match="Aucun canal"):
        send_brief(store, notify=True, channels=[])
    with pytest.raises(RuntimeError, match="non envoyé"):
        send_brief(store, notify=True, channels=[Channel("ntfy", fail=True)])


def test_the_brief_command_needs_an_explicit_base(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "brief"])
    with pytest.raises(SystemExit):
        main()
    assert "--data explicite" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["pokeprice-manage", "--data", str(tmp_path), "brief"])
    main()
    assert '"waiting": 0' in capsys.readouterr().out
