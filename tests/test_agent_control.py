import hashlib
import io
import json
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_storefront_access import STOREFRONT, api_routes, dependencies

from pokeprice.agent import AgentService, digest
from pokeprice.agent_api import PREFIX, schema
from pokeprice.inventory import SCHEMA_VERSION, Store, now
from pokeprice.inventory_backup import backup, export_data, restore_backup
from pokeprice.webapp import UserCreate, add_user, create_app

PASSWORD = "Agent-test-password!"


def add_copy(store, n, *, album="a", price=100, **overrides):
    values = {
        "name": "Gourgeist",
        "set_name": "Test set",
        "number": "1/20",
        "language": "fr",
        "catalog_id": "test-1",
        "identification_status": "confirmed",
        "album_id": album,
        "page": 1,
        "position": n,
        "finish": "non_holo",
        "variant_confirmed": True,
        "stamp_state": "absent",
        "distribution_state": "absent",
        "condition": "EX",
        "reference_cents": price,
        "price_source": "TCGdex",
        "price_date": now(),
        "notes": "PRIVATE-NOTE-DO-NOT-EXPOSE",
    }
    values.update(overrides)
    card = store.create_copy(values, "owner", "Synthetic card")
    if price is not None:
        with store.connect(write=True) as db:
            store.event(
                db,
                card["id"],
                "owner",
                "price-snapshot",
                "Synthetic prices",
                {},
                {
                    "catalog_id": values["catalog_id"],
                    "updated": "2026-10-01",
                    "source": "TCGdex",
                    "variant": "normal",
                    "variants": {"normal": True, "reverse": False},
                    "raw": {
                        "cardmarket": {
                            "trend": price / 100,
                            "avg30": price / 100,
                            "unit": "EUR",
                        }
                    },
                },
            )
    return card


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        user = add_user(
            db, UserCreate(username="owner", password=PASSWORD, role="admin")
        )
        db.executemany(
            "INSERT INTO albums VALUES(?,?)", [("a", "Album A"), ("b", "Album B")]
        )
    cards = [add_copy(store, n) for n in range(1, 5)]
    other = add_copy(store, 1, album="b", name="PRIVATE-OTHER-ALBUM")

    def no_network(*args, **kwargs):
        raise AssertionError("This workflow must never call a model or catalogue")

    app = create_app(
        store.root,
        intake_reader=no_network,
        intake_lookup=no_network,
        price_fetch=no_network,
        variant_fetch=no_network,
        market_fetch=no_network,
    )
    service = AgentService(store)
    grant = service.issue(
        "Assistant",
        "owner",
        "a",
        client="Synthetic HTTP client",
        permissions=["copies:read", "drafts:create", "photos:read"],
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + grant["token"]
        yield client, service, grant, cards, other, user


def request_for(cards, **overrides):
    return {
        "title": "Doublons français",
        "reason": "Synthetic lot",
        "description": "",
        "copies": [{"id": c["id"], "expected_version": c["version"]} for c in cards],
        **overrides,
    }


def post_draft(client, payload, key="lot-1"):
    return client.post(
        PREFIX + "/drafts", json=payload, headers={"Idempotency-Key": key}
    )


def tables(store, names):
    with store.connect() as db:
        return {
            name: [
                tuple(r)
                for r in db.execute("SELECT * FROM " + name + " ORDER BY rowid")
            ]
            for name in names
        }


UNCHANGED = (
    "copies",
    "editions",
    "sources",
    "events",
    "prices",
    "verifications",
    "condition_assessments",
    "listings",
    "listing_items",
    "requests",
    "request_items",
)


def test_scoped_facts_search_and_projection_without_business_mutations(shop):
    client, service, grant, cards, other, _ = shop
    before = tables(service.store, UNCHANGED + ("sales", "sale_items", "sale_events"))
    response = client.get(PREFIX + "/copies")
    assert response.status_code == 200
    result = response.json()
    assert (
        result["total"] == 4 and result["items"][0]["valuation"]["prudent_cents"] == 100
    )
    assert "PRIVATE-" not in response.text and "notes" not in result["items"][0]
    assert "source_key" not in result["items"][0] and "source" not in result["items"][0]
    assert (
        client.get(
            PREFIX + "/copies", params={"q": "PRIVATE-NOTE-DO-NOT-EXPOSE"}
        ).json()["total"]
        == 0
    )
    assert (
        client.get(PREFIX + "/copies", params={"limit": 2, "offset": 2}).json()["items"]
        == result["items"][2:]
    )
    assert client.get(PREFIX + "/copies/" + other["id"]).status_code == 404
    assert client.get(PREFIX + "/copies/" + cards[0]["id"]).status_code == 200
    assert tables(service.store, tuple(before)) == before
    with service.store.connect() as db:
        row = db.execute("SELECT * FROM agent_grants").fetchone()
        assert row["token_hash"] == digest(grant["token"]) and grant[
            "token"
        ] not in str(tuple(row))


def test_bearer_never_authenticates_human_management_routes(shop):
    client, _, _, cards, _, _ = shop
    for route in api_routes(client.app.routes):
        if route.path.startswith((PREFIX + "/",) + STOREFRONT):
            continue
        if "staff" not in set(dependencies(route.dependant)):
            continue
        path = route.path
        for param in route.param_convertors:
            path = path.replace("{" + param + "}", cards[0]["id"])
        for method in route.methods:
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.text)


def test_cookie_and_bearer_are_ambiguous_and_cookie_alone_is_not_agent(shop):
    client, _, _, _, _, _ = shop
    assert (
        client.post(
            "/api/login", json={"username": "owner", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert client.get(PREFIX + "/capabilities").status_code == 401
    client.headers.pop("Authorization")
    assert client.get(PREFIX + "/capabilities").status_code == 401
    assert client.get("/api/copies").status_code == 200


@pytest.mark.parametrize(
    "change", ["revoked", "expired", "disabled", "refused", "client"]
)
def test_live_access_state_is_checked(shop, change):
    client, service, grant, _, _, user = shop
    with service.store.connect(write=True) as db:
        if change == "revoked":
            db.execute(
                "UPDATE agent_grants SET revoked_at='revoked' WHERE id=?",
                (grant["id"],),
            )
        elif change == "expired":
            db.execute(
                "UPDATE agent_grants SET expires_at=? WHERE id=?",
                (int(time.time()) - 1, grant["id"]),
            )
        else:
            field, value = {
                "disabled": ("disabled", 1),
                "refused": ("status", "refused"),
                "client": ("role", "client"),
            }[change]
            db.execute(
                "UPDATE users SET " + field + "=? WHERE id=?", (value, user["id"])
            )
    assert client.get(PREFIX + "/copies").status_code == 401


def test_readonly_and_demoted_grants_cannot_write_or_download_photos(shop):
    client, service, _grant, cards, _, user = shop
    readonly = service.issue("Reader", "owner", "a", client="text-only")
    with TestClient(client.app) as reader:
        reader.headers["Authorization"] = "Bearer " + readonly["token"]
        assert reader.get(PREFIX + "/copies").status_code == 200
        assert (
            reader.get(PREFIX + "/copies/" + cards[0]["id"] + "/photo").status_code
            == 403
        )
        assert post_draft(reader, request_for(cards[1:])).status_code == 403
        assert (
            "create-draft"
            not in reader.get(PREFIX + "/capabilities").json()["operations"]
        )
    with service.store.connect(write=True) as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (user["id"],))
    assert post_draft(client, request_for(cards[1:])).status_code == 403
    assert client.get(PREFIX + "/copies").status_code == 200
    with pytest.raises(ValueError, match="lecteur"):
        service.issue(
            "Invalid", "owner", "a", client="text-only", permissions=["drafts:create"]
        )


def test_photo_permissions_scope_and_hash(shop):
    client, service, _, cards, other, _ = shop
    output = io.BytesIO()
    Image.new("RGB", (40, 60), "purple").save(output, "JPEG")
    name = service.store.save_photo(output.getvalue())
    service.store.patch(cards[0]["id"], {"photo": name}, 1, "owner", "Synthetic photo")
    response = client.get(PREFIX + "/copies/" + cards[0]["id"] + "/photo")
    assert response.status_code == 200 and response.content == output.getvalue()
    assert response.headers["x-photo-sha256"] == name[:-4]
    assert client.get(PREFIX + "/copies/" + other["id"] + "/photo").status_code == 404
    assert (
        client.get(PREFIX + "/copies/" + cards[1]["id"] + "/photo").status_code == 404
    )
    assert (
        client.get(
            PREFIX + "/copies/" + cards[0]["id"] + "/photo?side=../../other"
        ).status_code
        == 422
    )


def test_prepare_lot_uses_physical_reference_risk_and_stock(shop):
    client, service, _, _cards, _, _ = shop
    cases = [
        add_copy(service.store, 5, catalog_id="other-1", language="en"),
        add_copy(service.store, 6, finish="", variant_confirmed=False),
        add_copy(service.store, 7, stamp_state="unobserved"),
        add_copy(service.store, 8, price=None),
        add_copy(service.store, 9, price=1500),
        add_copy(
            service.store,
            10,
            catalog_id=None,
            identification_status="review",
            price=None,
            variant_confirmed=False,
        ),
        add_copy(service.store, 11),
    ]
    with service.store.connect(write=True) as db:
        db.execute(
            "UPDATE copies SET stock_state='reserved' WHERE id=?", (cases[-1]["id"],)
        )
    response = client.get(PREFIX + "/prepare-lot", params={"keep": 2, "language": "fr"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["selected"]) == 2 and len(result["retained"]) == 2
    assert result["asking_cents"] is None and result["reference_subtotal_cents"] == 200
    assert "état à vérifier" in result["description"]
    assert (
        "finition mate" in result["description"]
        and "non_holo" not in result["description"]
    )
    reasons = {entry["copy"]["id"]: entry["reasons"] for entry in result["excluded"]}
    for card, reason in zip(
        cases,
        [
            "other_language",
            "physical_details_unknown",
            "physical_details_unknown",
            "price_incomplete",
            "valuable_card",
            "identity_unconfirmed",
            "stock_unavailable",
        ],
    ):
        assert reason in reasons[card["id"]]
    assert len(client.get(PREFIX + "/prepare-lot?maximum=1").json()["selected"]) == 1


def test_draft_is_visible_in_management_unknown_price_and_idempotent(shop):
    client, service, grant, cards, _, _ = shop
    before = tables(service.store, UNCHANGED)
    payload = request_for(cards[1:], description="Texte agent proposé, à relire.")
    response = post_draft(client, payload)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["status"] == "draft" and receipt["amount_cents"] is None
    assert tables(service.store, UNCHANGED) == before
    assert post_draft(client, payload).json() == receipt
    changed = post_draft(client, {**payload, "title": "Different"})
    assert (
        changed.status_code == 409 and changed.json()["code"] == "idempotency_conflict"
    )
    sale = next(s for s in service.store.sales() if s["id"] == receipt["id"])
    assert sale["amount_cents"] is None and sale["net_cents"] is None
    exported = export_data(service.store)
    assert exported["tables"]["sales"][0]["amount_cents"] is None
    assert exported["tables"]["agent_drafts"][0]["amount_known"] == 0
    assert grant["token"] not in json.dumps(exported)
    assert (
        sale["agent_preparation"]["origin"] == "agent"
        and not sale["agent_preparation"]["stale"]
    )
    with TestClient(client.app) as human:
        human.post("/api/login", json={"username": "owner", "password": PASSWORD})
        assert human.get("/api/sales").json()[0]["id"] == receipt["id"]
        missing_amount = human.patch(
            "/api/sales/" + receipt["id"],
            json={"expected_version": 1, "reason": "Reserve", "status": "reserved"},
        )
        assert missing_amount.status_code == 422
    with service.store.connect() as db:
        event = db.execute(
            "SELECT actor FROM sale_events WHERE sale_id=?", (receipt["id"],)
        ).fetchone()
        assert event[0] == "agent:" + grant["id"]
        assert db.execute("SELECT count(*) FROM sales").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sale_items WHERE active=1").fetchone()
    fresh = TestClient(create_app(service.store.root))
    fresh.headers["Authorization"] = client.headers["Authorization"]
    service.store.patch(
        cards[1]["id"], {"notes": "Human note changed"}, 1, "owner", "Concurrent edit"
    )
    assert post_draft(fresh, payload).json() == receipt
    assert fresh.get(PREFIX + "/drafts/" + receipt["id"]).json()["stale"]
    assert service.store.sales()[0]["agent_preparation"]["stale"]
    service.revoke(grant["id"])
    assert post_draft(fresh, payload).status_code == 401


@pytest.mark.parametrize(
    "attack",
    [
        "other_album",
        "stale",
        "duplicate",
        "all_copies",
        "unknown",
        "confirmation",
        "keep",
    ],
)
def test_draft_rejects_bad_selection_without_partial_writes(shop, attack):
    client, service, _, cards, other, _ = shop
    payload = request_for(cards[1:])
    if attack == "other_album":
        payload["copies"][-1]["id"] = other["id"]
    elif attack == "stale":
        payload["copies"][-1]["expected_version"] = 10
    elif attack == "duplicate":
        payload["copies"][-1] = payload["copies"][0]
    elif attack == "all_copies":
        payload = request_for(cards)
    elif attack == "unknown":
        payload["copies"][-1]["id"] = "missing"
    elif attack == "confirmation":
        payload["human_confirmed"] = True
    else:
        payload["keep_per_reference"] = 2
    before = tables(
        service.store,
        UNCHANGED + ("sales", "sale_items", "sale_events", "agent_drafts"),
    )
    assert post_draft(client, payload).status_code in (404, 409, 422)
    assert tables(service.store, tuple(before)) == before


def test_creation_revalidates_valuable_and_published_cards(shop):
    client, service, _, cards, _, _ = shop
    high = add_copy(service.store, 10, price=1500)
    assert post_draft(client, request_for([high])).status_code == 409
    from pokeprice.listings import Listings

    Listings(service.store).publish([cards[1]["id"]], "owner", price_cents=100)
    assert post_draft(client, request_for([cards[1]])).status_code == 409


def test_concurrent_retries_create_one_draft(shop):
    client, service, _, cards, _, _ = shop
    payload = request_for(cards[1:])

    def create(_):
        with TestClient(client.app) as fresh:
            fresh.headers["Authorization"] = client.headers["Authorization"]
            response = post_draft(fresh, payload)
            assert response.status_code == 201, response.text
            return response.json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(create, range(4)))
    assert all(r == receipts[0] for r in receipts)
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_drafts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sale_events").fetchone()[0] == 1


def test_draft_transaction_rolls_back_when_receipt_cannot_be_written(shop, monkeypatch):
    client, service, _grant, cards, _, _ = shop
    store = client.app.state.agents.store
    original = store.create_sale
    before = tables(
        service.store,
        UNCHANGED + ("sales", "sale_items", "sale_events", "agent_drafts"),
    )

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Interrupted before the receipt")

    monkeypatch.setattr(store, "create_sale", interrupted)
    with pytest.raises(RuntimeError, match="Interrupted"):
        post_draft(client, request_for(cards[1:]))
    assert tables(service.store, tuple(before)) == before


def test_creation_rechecks_authorization_after_the_http_dependency(shop, monkeypatch):
    client, service, grant, cards, _, _ = shop
    actual = client.app.state.agents.create_draft

    def revoked_before_write(*args, **kwargs):
        service.revoke(grant["id"])
        return actual(*args, **kwargs)

    monkeypatch.setattr(client.app.state.agents, "create_draft", revoked_before_write)
    assert post_draft(client, request_for(cards[1:])).status_code == 401
    assert service.store.sales() == []


def test_grants_do_not_share_drafts_even_in_the_same_album(shop):
    client, service, _, cards, _, _ = shop
    sale_id = post_draft(client, request_for(cards[1:])).json()["id"]
    other = service.issue(
        "Other agent", "owner", "a", client="Other client", permissions=["photos:read"]
    )
    with TestClient(client.app) as visitor:
        visitor.headers["Authorization"] = "Bearer " + other["token"]
        assert visitor.get(PREFIX + "/drafts/" + sale_id).status_code == 404
        assert (
            visitor.get(PREFIX + "/drafts/" + sale_id + "/package").status_code == 404
        )


def test_package_requires_photos_permission_and_is_explicitly_regenerated(shop):
    client, service, _, cards, _, _ = shop
    no_photos = service.issue(
        "Text only", "owner", "a", client="local", permissions=["drafts:create"]
    )
    with TestClient(client.app) as text:
        text.headers["Authorization"] = "Bearer " + no_photos["token"]
        sale_id = post_draft(text, request_for(cards[1:])).json()["id"]
        assert text.get(PREFIX + "/drafts/" + sale_id + "/package").status_code == 403
    sale_id = post_draft(client, request_for(cards[1:])).json()["id"]
    service.store.patch(
        cards[1]["id"], {"notes": "PRIVATE-CHANGED"}, 1, "owner", "Change"
    )
    response = client.get(PREFIX + "/drafts/" + sale_id + "/package")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        all_text = "\n".join(
            archive.read(n).decode() for n in archive.namelist() if n.endswith(".txt")
        )
        assert (
            "PRIVATE-" not in all_text
            and "régénéré" in all_text
            and "fiches ont changé" in all_text
        )
        assert "proposition-agent.txt" in archive.namelist()
    with service.store.connect(write=True) as db:
        db.execute("UPDATE copies SET album_id='b' WHERE id=?", (cards[1]["id"],))
    assert client.get(PREFIX + "/drafts/" + sale_id).status_code == 404
    assert client.get(PREFIX + "/drafts/" + sale_id + "/package").status_code == 404


def test_migration_backup_restore_neutralize_access_and_keep_drafts(shop, tmp_path):
    client, service, grant, cards, _, _ = shop
    sale_id = post_draft(client, request_for(cards[1:])).json()["id"]
    archive = tmp_path / "backup.zip"
    backup(service.store, archive)
    assert client.get(PREFIX + "/copies").status_code == 200
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    saved = Store(restored)
    with saved.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 19
        assert db.execute("SELECT sale_id FROM agent_drafts").fetchone()[0] == sale_id
        assert (
            db.execute("SELECT token_hash,revoked_at FROM agent_grants").fetchone()[
                "token_hash"
            ]
            is None
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with TestClient(create_app(restored)) as fresh:
        fresh.headers["Authorization"] = "Bearer " + grant["token"]
        assert fresh.get(PREFIX + "/copies").status_code == 401
    assert saved.sales()[0]["agent_preparation"]["origin"] == "agent"
    # An archive made by an older tool may still carry a valid credential.
    with zipfile.ZipFile(archive) as source:
        files = {name: source.read(name) for name in source.namelist()}
    old_db = tmp_path / "old-archive.sqlite3"
    old_db.write_bytes(files["collection.sqlite3"])
    with sqlite3.connect(old_db) as db:
        db.execute(
            "UPDATE agent_grants SET token_hash=?,revoked_at=''",
            (digest(grant["token"]),),
        )
    files["collection.sqlite3"] = old_db.read_bytes()
    manifest = json.loads(files["manifest.json"])
    manifest["files"]["collection.sqlite3"] = hashlib.sha256(
        files["collection.sqlite3"]
    ).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    old_archive = tmp_path / "old-tool.zip"
    with zipfile.ZipFile(old_archive, "w") as target:
        for name, body in files.items():
            target.writestr(name, body)
    old_restored = tmp_path / "old-restored"
    restore_backup(old_archive, old_restored)
    with TestClient(create_app(old_restored)) as old:
        old.headers["Authorization"] = "Bearer " + grant["token"]
        assert old.get(PREFIX + "/copies").status_code == 401
    # Rehearse 17 -> current schema with existing accounts, photos, events and sales preserved.
    with saved.connect(write=True) as db:
        db.execute("DROP TABLE agent_drafts")
        db.execute("DROP TABLE agent_grants")
        db.execute("PRAGMA user_version=17")
    again = Store(restored)
    with again.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT id FROM sales").fetchone()[0] == sale_id
    assert list((tmp_path / "backups").glob(f"before-schema{SCHEMA_VERSION}-from17-*"))


def test_contract_limits_disable_switch_and_rate_limit(shop):
    client, service, _, _cards, _, _ = shop
    contract = schema()
    assert all(p.startswith(PREFIX + "/") for p in contract["paths"])
    assert "/api/copies" not in contract["paths"]
    assert client.get("/openapi.json").status_code == 404
    assert client.get(PREFIX + "/copies?limit=101").status_code == 422
    assert client.post(PREFIX + "/drafts", content=b"x" * 65537).status_code == 413
    grant = service.issue("Limited", "owner", "a", client="synthetic")
    with TestClient(client.app) as limited:
        limited.headers["Authorization"] = "Bearer " + grant["token"]
        for _ in range(60):
            assert limited.get(PREFIX + "/capabilities").status_code == 200
        assert limited.get(PREFIX + "/capabilities").status_code == 429
    with TestClient(create_app(service.store.root, agent_enabled=False)) as disabled:
        assert disabled.get(PREFIX + "/copies").status_code == 404
