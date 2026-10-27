import json
import threading

import pytest
from fastapi.testclient import TestClient
from test_library import inputs

from pokeprice.inventory import Conflict, Store
from pokeprice.inventory_import import import_collection
from pokeprice.listings import Storefront
from pokeprice.reservations import Reservations
from pokeprice.webapp import create_app

PASSWORD = "Client-test-2026!"


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    with TestClient(create_app(store.root)) as admin:
        assert admin.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
        cards = [c for c in admin.get("/api/copies", params={"limit": 100}).json()["items"] if c["identification_status"] == "confirmed"]
        listings = [
            admin.put(f"/api/copies/{cards[i]['id']}/listing", json={"price_eur": price}).json()
            for i, price in ((0, "1.20"), (1, "3.50"), (2, "0.80"))
        ]
        yield admin, store, listings


def signup(store, email, name="Sacha"):
    with TestClient(create_app(store.root)) as visitor:
        return visitor.post(
            "/api/public/signup",
            json={"email": email, "display_name": name, "password": PASSWORD, "consent": True},
        )


def client_of(store, email):
    visitor = TestClient(create_app(store.root))
    visitor.__enter__()
    assert visitor.post("/api/login", json={"username": email, "password": PASSWORD}).status_code == 200
    return visitor


def activate(admin, email):
    client = next(c for c in admin.get("/api/clients").json() if c["email"] == email)
    assert admin.patch(f"/api/clients/{client['id']}", json={"status": "active"}).status_code == 200
    return client


def test_signup_waits_for_validation_and_never_reveals_known_addresses(shop):
    admin, store, _ = shop
    first = signup(store, "sacha+cartes@example.org")
    again = signup(store, "Sacha+Cartes@example.org", "Autre")
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    clients = admin.get("/api/clients").json()
    assert [(c["email"], c["status"], c["display_name"]) for c in clients] == [("sacha+cartes@example.org", "pending", "Sacha")]
    assert clients[0]["consent_at"]
    with TestClient(create_app(store.root)) as visitor:
        pending = visitor.post("/api/login", json={"username": "sacha+cartes@example.org", "password": PASSWORD})
        assert pending.status_code == 403 and "attente" in pending.json()["detail"]
    activate(admin, "sacha+cartes@example.org")
    me = client_of(store, "sacha+cartes@example.org")
    assert me.get("/api/me").json() == {"email": "sacha+cartes@example.org", "display_name": "Sacha"}
    assert me.get("/api/copies").status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"email": "pas-une-adresse", "display_name": "A", "password": PASSWORD, "consent": True},
        {"email": "a@example.org", "display_name": "A", "password": PASSWORD, "consent": False},
        {"email": "a@example.org", "display_name": "A", "password": "court", "consent": True},
    ],
)
def test_invalid_signups_are_refused(shop, body):
    _, store, _ = shop
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.post("/api/public/signup", json=body).status_code == 422


def test_signups_are_limited_per_address(shop):
    _, store, _ = shop
    with TestClient(create_app(store.root)) as visitor:
        statuses = [
            visitor.post("/api/public/signup", json={"email": f"x{i}@example.org", "display_name": "X", "password": PASSWORD, "consent": True}).status_code
            for i in range(6)
        ]
    assert statuses == [202] * 5 + [429]


def test_a_request_reserves_nothing_until_partial_acceptance(shop):
    admin, store, listings = shop
    signup(store, "sacha@example.org")
    activate(admin, "sacha@example.org")
    me = client_of(store, "sacha@example.org")
    ids = [listings[0]["id"], listings[1]["id"]]
    sent = me.post("/api/me/requests", json={"listing_ids": ids, "message": "Remise en main propre"})
    assert sent.status_code == 201
    request = sent.json()
    assert request["status"] == "sent" and request["total_cents"] == 470 and "client_id" not in request
    assert all("copies" not in i for i in request["items"])
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.get("/api/public/listings").json()["total"] == 3  # nothing blocked yet

    staff_view = admin.get("/api/requests").json()[0]
    assert staff_view["email"] == "sacha@example.org" and staff_view["message"] == "Remise en main propre"
    accepted = admin.post(
        f"/api/requests/{request['id']}/accept",
        json={"expected_version": staff_view["version"], "listing_ids": [listings[0]["id"]]},
    ).json()
    assert accepted["status"] == "partially_accepted"
    sale = next(s for s in admin.get("/api/sales").json() if s["id"] == accepted["sale_id"])
    assert sale["status"] == "reserved" and sale["amount_cents"] == 120 and sale["channel"] == "Vitrine"
    assert [i["id"] for i in sale["items"]] == [listings[0]["items"][0]["id"]]
    with TestClient(create_app(store.root)) as visitor:
        assert {l["id"] for l in visitor.get("/api/public/listings").json()["items"]} == {listings[1]["id"], listings[2]["id"]}
    mine = me.get("/api/me/requests").json()[0]
    assert mine["status_label"] == "Réservée"
    assert {i["listing_id"]: i["outcome"] for i in mine["items"]} == {listings[0]["id"]: "accepted", listings[1]["id"]: "refused"}
    history = admin.get(f"/api/copies/{listings[0]['items'][0]['id']}").json()["history"]
    assert "storefront-request" in [e["kind"] for e in history]


def test_two_requests_for_one_card_cannot_both_be_accepted(shop):
    admin, store, listings = shop
    for email in ("a@example.org", "b@example.org"):
        signup(store, email)
        activate(admin, email)
        client_of(store, email).post("/api/me/requests", json={"listing_ids": [listings[2]["id"]]})
    first, second = sorted(admin.get("/api/requests").json(), key=lambda r: r["email"])
    assert admin.post(f"/api/requests/{first['id']}/accept", json={"expected_version": first["version"], "listing_ids": [listings[2]["id"]]}).status_code == 200
    late = admin.post(f"/api/requests/{second['id']}/accept", json={"expected_version": second["version"], "listing_ids": [listings[2]["id"]]})
    assert late.status_code == 409
    assert len(admin.get("/api/sales").json()) == 1  # no stray draft
    refused = admin.post(f"/api/requests/{second['id']}/refuse", json={"expected_version": second["version"], "reason": "Déjà réservée"})
    assert refused.status_code == 200
    mine = client_of(store, "b@example.org").get("/api/me/requests").json()[0]
    assert mine["status"] == "refused" and mine["decision"] == "Déjà réservée"


def interleave(monkeypatch, store, rival):
    """Run `rival` in another thread right after accept() has checked the request."""
    original, outcome = store.create_sale, {}

    def run():
        try:
            outcome["rival"] = rival()
        except Conflict as exc:
            outcome["rival"] = exc

    def create_sale(*args, **kwargs):
        monkeypatch.setattr(store, "create_sale", original)
        outcome["thread"] = threading.Thread(target=run)
        outcome["thread"].start()
        # A non-atomic acceptance lets the rival finish here; an atomic one
        # holds the write lock, so the rival waits for the acceptance to end.
        outcome["thread"].join(timeout=1)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "create_sale", create_sale)
    return outcome


def race_accept(shop, monkeypatch, rival):
    admin, store, listings = shop
    signup(store, "sacha@example.org")
    activate(admin, "sacha@example.org")
    ids = [listings[0]["id"], listings[1]["id"]]
    client_of(store, "sacha@example.org").post("/api/me/requests", json={"listing_ids": ids})
    request = admin.get("/api/requests").json()[0]
    service = Reservations(store, Storefront(store))
    outcome = interleave(monkeypatch, store, lambda: rival(service, request, ids[1]))
    try:
        outcome["accept"] = service.accept(request["id"], request["version"], [ids[0]], "pat")
    except Conflict as exc:
        outcome["accept"] = exc
    outcome["thread"].join()
    final = next(r for r in admin.get("/api/requests").json() if r["id"] == request["id"])
    reserved = [s["id"] for s in admin.get("/api/sales").json() if s["status"] == "reserved"]
    winners = [k for k in ("accept", "rival") if not isinstance(outcome[k], Exception)]
    return winners, final, reserved


def test_a_cancellation_racing_an_acceptance_cannot_both_win(shop, monkeypatch):
    winners, final, reserved = race_accept(
        shop, monkeypatch,
        lambda service, request, _: service.cancel(request["client_id"], request["id"], request["version"]),
    )
    assert len(winners) == 1
    if final["status"] == "cancelled":
        assert reserved == [] and final["sale_id"] is None
    else:
        assert final["status"] == "partially_accepted" and reserved == [final["sale_id"]]


def test_a_refusal_racing_an_acceptance_cannot_both_win(shop, monkeypatch):
    winners, final, reserved = race_accept(
        shop, monkeypatch,
        lambda service, request, _: service.refuse(request["id"], request["version"], "lea", "Plus en stock"),
    )
    assert len(winners) == 1
    if final["status"] == "refused":
        assert reserved == [] and final["sale_id"] is None
    else:
        assert reserved == [final["sale_id"]]


def test_two_partial_acceptances_of_one_request_cannot_both_win(shop, monkeypatch):
    winners, final, reserved = race_accept(
        shop, monkeypatch,
        lambda service, request, other: service.accept(request["id"], request["version"], [other], "lea"),
    )
    # A reserved lot detached from its request would leave a card "refused" yet blocked.
    assert len(winners) == 1 and reserved == [final["sale_id"]]
    accepted = [i["listing_id"] for i in final["items"] if i["outcome"] == "accepted"]
    assert len(accepted) == 1


def test_clients_cancel_their_own_requests_and_old_ones_expire(shop):
    admin, store, listings = shop
    for email in ("a@example.org", "b@example.org"):
        signup(store, email)
        activate(admin, email)
    a, b = client_of(store, "a@example.org"), client_of(store, "b@example.org")
    first = a.post("/api/me/requests", json={"listing_ids": [listings[0]["id"]]}).json()
    second = a.post("/api/me/requests", json={"listing_ids": [listings[1]["id"]]}).json()
    assert b.post(f"/api/me/requests/{first['id']}/cancel", json={"expected_version": 1}).status_code == 404
    assert b.get("/api/me/requests").json() == []
    assert a.post(f"/api/me/requests/{first['id']}/cancel", json={"expected_version": 1}).json()["status"] == "cancelled"
    with store.connect(write=True) as db:
        db.execute("UPDATE requests SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (second["id"],))
    statuses = {r["id"]: r["status"] for r in a.get("/api/me/requests").json()}
    assert statuses == {first["id"]: "cancelled", second["id"]: "expired"}
    unpublished = admin.delete(f"/api/copies/{listings[2]['items'][0]['id']}/listing")
    assert unpublished.status_code == 200
    assert a.post("/api/me/requests", json={"listing_ids": [listings[2]["id"]]}).status_code == 409


def test_roles_around_requests(shop):
    admin, store, listings = shop
    signup(store, "a@example.org")
    activate(admin, "a@example.org")
    me = client_of(store, "a@example.org")
    request = me.post("/api/me/requests", json={"listing_ids": [listings[0]["id"]]}).json()
    assert me.get("/api/requests").status_code == 403
    assert me.get("/api/clients").status_code == 403
    assert admin.post("/api/users", json={"username": "lecteur", "password": "Lecture-test-2026!", "role": "reader"}).status_code == 201
    with TestClient(create_app(store.root)) as reader:
        reader.post("/api/login", json={"username": "lecteur", "password": "Lecture-test-2026!"})
        assert reader.get("/api/requests").status_code == 200
        assert reader.get("/api/clients").status_code == 403
        assert reader.post(f"/api/requests/{request['id']}/accept", json={"expected_version": 1, "listing_ids": [listings[0]["id"]]}).status_code == 403
        assert reader.get("/api/me/requests").status_code == 403
    staff_view = json.dumps(admin.get("/api/requests").json())
    assert listings[0]["items"][0]["id"] in staff_view  # the seller sees the copies
    assert listings[0]["items"][0]["id"] not in json.dumps(me.get("/api/me/requests").json())


def test_clients_stay_out_of_the_staff_accounts_screen(shop):
    admin, store, _ = shop
    signup(store, "a@example.org")
    client = activate(admin, "a@example.org")
    assert [u["username"] for u in admin.get("/api/users").json()] == ["pat"]
    promoted = admin.patch(f"/api/users/{client['id']}", json={"role": "admin", "disabled": False})
    assert promoted.status_code == 404
    with store.connect() as db:
        assert db.execute("SELECT role FROM users WHERE id=?", (client["id"],)).fetchone()[0] == "client"


def guest(store, email, listing_ids, name="Ondine", message=""):
    with TestClient(create_app(store.root)) as visitor:
        return visitor.post(
            "/api/public/requests",
            json={"email": email, "display_name": name, "listing_ids": listing_ids,
                  "message": message, "consent": True},
        )


def test_a_visitor_reserves_without_an_account_and_acceptance_validates_it(shop):
    admin, store, listings = shop
    sent = guest(store, "ondine@example.org", [listings[0]["id"]], message="Envoi suivi")
    assert sent.status_code == 202 and "ondine@example.org" in sent.json()["detail"]
    client = next(c for c in admin.get("/api/clients").json() if c["email"] == "ondine@example.org")
    assert client["status"] == "pending" and client["consent_at"]
    request = admin.get("/api/requests").json()[0]
    assert request["client_status"] == "pending" and request["message"] == "Envoi suivi"
    # No password was chosen: nothing opens the account, whatever is tried.
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.post("/api/login", json={"username": "ondine@example.org", "password": ""}).status_code == 422
        assert visitor.post("/api/login", json={"username": "ondine@example.org", "password": PASSWORD}).status_code == 401
    admin.post(
        f"/api/requests/{request['id']}/accept",
        json={"expected_version": request["version"], "listing_ids": [listings[0]["id"]]},
    ).raise_for_status()
    assert next(c for c in admin.get("/api/clients").json() if c["email"] == "ondine@example.org")["status"] == "active"


def test_a_guest_request_never_reveals_known_addresses(shop):
    admin, store, listings = shop
    signup(store, "sacha@example.org")
    refused = signup(store, "refuse@example.org")
    assert refused.status_code == 202
    clients = {c["email"]: c["id"] for c in admin.get("/api/clients").json()}
    admin.patch(f"/api/clients/{clients['refuse@example.org']}", json={"status": "refused"})
    admin.post("/api/users", json={"username": "equipe@example.org", "password": PASSWORD, "role": "editor"}).raise_for_status()
    answers = [
        guest(store, email, [listings[1]["id"]])
        for email in ("Sacha@example.org", "refuse@example.org", "equipe@example.org", "nouveau@example.org")
    ]
    assert len({(a.status_code, a.json()["detail"].split(" à ")[0]) for a in answers}) == 1
    owners = {r["email"] for r in admin.get("/api/requests").json()}
    # The known client gets the request; a refused account and a staff name get nothing.
    assert owners == {"sacha@example.org", "nouveau@example.org"}
    assert [c["display_name"] for c in admin.get("/api/clients").json() if c["email"] == "sacha@example.org"] == ["Sacha"]


def test_guest_requests_are_limited(shop):
    _, store, listings = shop
    ids = [l["id"] for l in listings]
    statuses = [guest(store, "ondine@example.org", [i]).status_code for i in ids]
    assert statuses == [202, 202, 202]
    assert guest(store, "ondine@example.org", [ids[0]]).status_code == 409
    with TestClient(create_app(store.root)) as visitor:
        statuses = [
            visitor.post(
                "/api/public/requests",
                json={"email": f"x{i}@example.org", "display_name": "X", "listing_ids": [ids[0]], "consent": True},
            ).status_code
            for i in range(6)
        ]
    assert statuses == [202] * 5 + [429]
    assert guest(store, "autre@example.org", ["inconnue"]).status_code == 409
    assert guest(store, "pas-une-adresse", [ids[0]]).status_code == 422


def test_a_password_link_opens_the_account_once(shop):
    admin, store, listings = shop
    guest(store, "ondine@example.org", [listings[0]["id"]])
    client = next(c for c in admin.get("/api/clients").json() if c["email"] == "ondine@example.org")
    first = admin.post(f"/api/clients/{client['id']}/password-link")
    assert first.status_code == 201
    link = admin.post(f"/api/clients/{client['id']}/password-link").json()
    with TestClient(create_app(store.root)) as visitor:
        # A newer link replaces the older one.
        stale = visitor.post("/api/public/password", json={"token": first.json()["token"], "password": PASSWORD})
        assert stale.status_code == 422
        assert visitor.post("/api/public/password", json={"token": link["token"], "password": PASSWORD}).status_code == 200
        assert visitor.get("/api/me").json()["email"] == "ondine@example.org"
        assert len(visitor.get("/api/me/requests").json()) == 1
        again = visitor.post("/api/public/password", json={"token": link["token"], "password": "Autre-mot-2026!"})
        assert again.status_code == 422
    assert next(c for c in admin.get("/api/clients").json() if c["id"] == client["id"])["status"] == "active"
    client_of(store, "ondine@example.org")


def test_password_links_are_for_open_client_accounts_only(shop):
    admin, store, _ = shop
    signup(store, "refuse@example.org")
    refused = admin.get("/api/clients").json()[0]
    admin.patch(f"/api/clients/{refused['id']}", json={"status": "refused"})
    assert admin.post(f"/api/clients/{refused['id']}/password-link").status_code == 409
    staff = admin.get("/api/users").json()[0]
    assert admin.post(f"/api/clients/{staff['id']}/password-link").status_code == 404
    # Expired: the link is refused.
    signup(store, "sacha@example.org")
    sacha = next(c for c in admin.get("/api/clients").json() if c["email"] == "sacha@example.org")
    link = admin.post(f"/api/clients/{sacha['id']}/password-link").json()
    with store.connect(write=True) as db:
        db.execute("UPDATE password_links SET expires_at='2000-01-01T00:00:00+00:00'")
    with TestClient(create_app(store.root)) as visitor:
        assert visitor.post("/api/public/password", json={"token": link["token"], "password": PASSWORD}).status_code == 422


def test_a_pending_client_is_kept_90_days_after_their_last_request(shop):
    from datetime import datetime, timedelta, timezone

    from pokeprice.privacy import Privacy

    admin, store, listings = shop
    guest(store, "ondine@example.org", [listings[0]["id"]])
    signup(store, "oublie@example.org")
    at = datetime.now(timezone.utc)
    with store.connect(write=True) as db:
        db.execute("UPDATE users SET created_at=? WHERE role='client'", ((at - timedelta(days=120)).isoformat(),))
    assert Privacy(store).purge(at)["clients"] == {"Compte jamais validé": 1}
    assert [c["email"] for c in admin.get("/api/clients").json()] == ["ondine@example.org"]
