import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_agent_client
from fastapi.testclient import TestClient

from pokeprice.agent import AgentService
from pokeprice.agent_corrections import CorrectionService
from pokeprice.inventory import SCHEMA_VERSION, Conflict, Store
from pokeprice.webapp import UserCreate, add_user, create_app

PREFIX = "/api/agent/v1"


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        user = add_user(
            db,
            UserCreate(username="owner", password="Synthetic-password!", role="admin"),
        )
        db.executemany(
            "INSERT INTO albums VALUES(?,?)", [("a", "Album A"), ("b", "Album B")]
        )
    values = {
        "name": "Gourgeist",
        "set_name": "",
        "number": "1/20",
        "language": "fr",
        "hp": 50,
        "identification_status": "confirmed",
        "album_id": "a",
        "page": 1,
        "position": 1,
        "finish": "non_holo",
        "variant_confirmed": True,
        "stamp_state": "absent",
        "distribution_state": "absent",
        "condition": "LP",
        "condition_confirmed": True,
        "notes": "Private note remains unchanged",
    }
    cards = [
        store.create_copy({**values, "position": n}, "owner", "Synthetic observation")
        for n in (1, 2)
    ]
    other = store.create_copy(
        {**values, "album_id": "b"}, "owner", "Synthetic other album"
    )

    def no_network(*_args, **_kwargs):
        raise AssertionError("No network in correction tests")

    app = create_app(
        store.root,
        intake_reader=no_network,
        intake_lookup=no_network,
        price_fetch=no_network,
        variant_fetch=no_network,
        market_fetch=no_network,
    )
    agents = AgentService(store)
    grant = agents.issue(
        "Assistant",
        "owner",
        "a",
        client="Synthetic client",
        permissions=["copies:read", "corrections:apply"],
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + grant["token"]
        yield client, agents, grant, cards, other, user


@pytest.fixture
def live_server(shop):
    yield from test_agent_client.live_server.__wrapped__(shop)


def native(ident="test-1", language="fr"):
    return {
        "id": ident,
        "name": "Gourgeist",
        "localId": "1",
        "hp": 50,
        "set": {"name": "Test edition", "cardCount": {"official": 20}},
        "variants": {"normal": True, "holo": False, "reverse": False},
        "pricing": {
            "cardmarket": {
                "unit": "EUR",
                "trend": 1.2,
                "avg30": 1.1,
                "idProduct": 12345,
                "updated": "2026-10-01",
            }
        },
        "_acquisition": {
            "provider": "TCGdex",
            "source": f"https://api.tcgdex.net/v2/{language}/cards/{ident}",
        },
    }


def approve(shop, *, fetch=native, cards=None):
    _client, agents, grant, originals, _other, _user = shop
    return CorrectionService(agents.store, fetch=fetch).approve(
        grant["id"],
        [
            {"id": c["id"], "expected_version": c["version"], "catalog_id": "test-1"}
            for c in (cards or originals[:1])
        ],
        "Explicit user approval of the catalogue plan",
    )


def payload(approval):
    return {key: approval[key] for key in ("expected_version", "approval_sha256")}


def apply(client, approval, **extra):
    return client.post(
        PREFIX + "/copies/" + approval["id"] + "/apply-correction",
        json={**payload(approval), **extra},
    )


def test_approved_http_write_is_sourced_audited_and_does_not_invent_physical_confirmation(
    shop,
):
    client, agents, grant, cards, _other, _user = shop
    before = cards[0]
    approval = approve(shop)[0]
    with agents.store.connect() as db:
        assert dict(agents.store.get(db, before["id"])) == before
    assert (
        "apply-correction" in client.get(PREFIX + "/capabilities").json()["operations"]
    )
    pending = client.get(PREFIX + "/corrections").json()["items"]
    assert pending[0]["approval_sha256"] == approval["approval_sha256"]
    result = apply(client, approval)
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert (
        receipt["agent_id"] == grant["id"]
        and not receipt["physical_confirmation_created"]
    )
    with agents.store.connect() as db:
        after = agents.store.get(db, before["id"])
        events = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM events WHERE actor=?", ("agent:" + grant["id"],)
            )
        ]
    assert after["reference_cents"] == 120 and after["catalog_id"] == "test-1"
    assert after["version"] == before["version"] + 1
    for key in (
        "finish",
        "stamp_state",
        "distribution_state",
        "condition",
        "condition_confirmed",
        "notes",
        "stock_state",
        "observation_provenance",
    ):
        assert after[key] == before[key]
    assert not after["variant_confirmed"] and not after["variant_verified_by"]
    assert {e["kind"] for e in events} == {
        "correction",
        "price-snapshot",
        "agent-correction",
    }
    assert all("confirmation humaine" not in e["reason"] for e in events)
    assert apply(client, approval).json() == receipt
    with agents.store.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM events WHERE actor=?", ("agent:" + grant["id"],)
        ).fetchone()[0] == len(events)
    assert client.get("/api/copies").status_code == 401


@pytest.mark.parametrize(
    "change,status",
    [("revoke", 401), ("expire", 401), ("demote", 403), ("permission", 403)],
)
def test_access_changes_block_pending_and_replayed_corrections(shop, change, status):
    client, agents, grant, _cards, _other, _user = shop
    approval = approve(shop)[0]
    if change == "revoke":
        assert apply(client, approval).status_code == 200
        agents.revoke(grant["id"])
    else:
        with agents.store.connect(write=True) as db:
            if change == "expire":
                db.execute(
                    "UPDATE agent_grants SET expires_at=1 WHERE id=?", (grant["id"],)
                )
            elif change == "demote":
                db.execute("UPDATE users SET role='reader' WHERE username='owner'")
            else:
                db.execute(
                    "UPDATE agent_grants SET permissions_json='[\"copies:read\"]' WHERE id=?",
                    (grant["id"],),
                )
    assert apply(client, approval).status_code == status


def test_wrong_scope_other_grant_and_extra_fields_cannot_authorize_writes(shop):
    client, agents, _grant, cards, other, _user = shop
    approval = approve(shop)[0]
    assert (
        client.post(
            PREFIX + "/copies/" + other["id"] + "/apply-correction",
            json=payload(approval),
        ).status_code
        == 404
    )
    assert (
        client.post(
            PREFIX + "/copies/" + cards[1]["id"] + "/apply-correction",
            json=payload(approval),
        ).status_code
        == 403
    )
    for extra in (
        {"variant_confirmed": True},
        {"reference_cents": 999},
        {"changes": {"condition": "NM"}},
    ):
        assert apply(client, approval, **extra).status_code == 422
    other_grant = agents.issue(
        "Other", "owner", "a", client="Other client", permissions=["corrections:apply"]
    )
    client.headers["Authorization"] = "Bearer " + other_grant["token"]
    assert apply(client, approval).status_code == 403
    with agents.store.connect() as db:
        assert agents.store.get(db, cards[0]["id"])["reference_cents"] is None


def test_stale_and_tampered_approvals_leave_cards_unchanged(shop):
    client, agents, grant, cards, _other, _user = shop
    approval = approve(shop)[0]
    assert apply(client, approval, approval_sha256="0" * 64).status_code == 409
    after = agents.store.patch(
        cards[0]["id"],
        {"notes": "New human note"},
        cards[0]["version"],
        "owner",
        "New note",
    )
    assert apply(client, approval).status_code == 409
    with agents.store.connect() as db:
        assert agents.store.get(db, cards[0]["id"]) == after
    approval2 = approve(shop, cards=cards[1:])[0]
    with agents.store.connect(write=True) as db:
        row = db.execute(
            "SELECT plan_json FROM agent_corrections WHERE grant_id=? AND copy_id=?",
            (grant["id"], cards[1]["id"]),
        ).fetchone()
        plan = json.loads(row[0])
        plan["changes"]["reference_cents"] = 999
        db.execute(
            "UPDATE agent_corrections SET plan_json=? WHERE grant_id=? AND copy_id=?",
            (json.dumps(plan), grant["id"], cards[1]["id"]),
        )
    assert apply(client, approval2).status_code == 409


def test_approval_rechecks_versions_after_network_and_has_no_partial_registration(shop):
    _client, agents, _grant, cards, _other, _user = shop
    called = False

    def racing(ident, language):
        nonlocal called
        if not called:
            agents.store.patch(
                cards[1]["id"],
                {"notes": "Changed while fetching"},
                cards[1]["version"],
                "owner",
                "Concurrent edit",
            )
            called = True
        return native(ident, language)

    with pytest.raises(Conflict):
        approve(shop, fetch=racing, cards=cards)
    with agents.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_corrections").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["missing", "usd", "wrong_product"])
def test_unavailable_or_wrong_market_price_does_not_become_a_reference(shop, mode):
    client, agents, _grant, cards, _other, _user = shop
    data = native()
    if mode == "missing":
        data["pricing"] = {}
    elif mode == "usd":
        data["pricing"]["cardmarket"]["unit"] = "USD"
    else:
        with agents.store.connect(write=True) as db:
            agents.store.event(
                db,
                cards[0]["id"],
                "owner",
                "market-product",
                "Wrong product",
                {},
                {"catalog_id": "test-1", "id_product": 12345, "verdict": "wrong"},
            )
    approval = approve(shop, fetch=lambda *_: copy.deepcopy(data))[0]
    assert apply(client, approval).status_code == 200
    with agents.store.connect() as db:
        card = agents.store.get(db, cards[0]["id"])
    assert card["catalog_id"] == "test-1" and card["reference_cents"] is None


def test_new_wrong_product_verdict_blocks_prepared_price(shop):
    client, agents, _grant, cards, _other, _user = shop
    approval = approve(shop)[0]
    with agents.store.connect(write=True) as db:
        agents.store.event(
            db,
            cards[0]["id"],
            "owner",
            "market-product",
            "Wrong product",
            {},
            {"catalog_id": "test-1", "id_product": 12345, "verdict": "wrong"},
        )
    assert apply(client, approval).status_code == 409


def test_schema18_migration_preserves_cards_and_keeps_old_database(shop):
    _client, agents, _grant, cards, _other, _user = shop
    with agents.store.connect(write=True) as db:
        db.execute("DROP TABLE agent_corrections")
        db.execute("PRAGMA user_version=18")
    reopened = Store(agents.store.root)
    with reopened.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert reopened.get(db, cards[0]["id"]) == cards[0]
        assert db.execute("SELECT count(*) FROM agent_corrections").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert list(
        (reopened.root.parent / "backups").glob(f"before-schema{SCHEMA_VERSION}-from18-*.sqlite3")
    )


def test_real_http_cli_applies_approved_plan_and_reuses_receipt(live_server, tmp_path):
    url, shop = live_server
    _client, _agents, grant, _cards, _other, _user = shop
    approval = approve(shop)[0]
    token = tmp_path / "token"
    token.write_text(grant["token"])
    token.chmod(0o600)
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "src/pokeprice/agent_client.py"),
        "--url",
        url,
        "--token-file",
        str(token),
    ]
    env = os.environ.copy()
    env.pop("POKEPRICE_AGENT_TOKEN", None)
    env.pop("POKEPRICE_AGENT_TOKEN_FILE", None)

    def cli(*args):
        result = subprocess.run(
            [*command, *map(str, args)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert grant["token"] not in result.stdout + result.stderr
        return json.loads(result.stdout)

    assert cli("corrections")["items"][0]["id"] == approval["id"]
    args = (
        "apply-correction",
        approval["id"],
        "--expected-version",
        approval["expected_version"],
        "--approval-sha256",
        approval["approval_sha256"],
    )
    receipt = cli(*args)
    assert cli(*args) == receipt and receipt["reference_cents"] == 120


def test_read_only_delegation_cannot_read_plans_or_apply_or_approve(shop):
    client, agents, _grant, cards, _other, _user = shop
    approval = approve(shop)[0]
    readonly = agents.issue("Read only", "owner", "a", client="Read only")
    client.headers["Authorization"] = "Bearer " + readonly["token"]
    assert client.get(PREFIX + "/corrections").status_code == 403
    assert apply(client, approval).status_code == 403
    from pokeprice.agent import AgentError

    with pytest.raises(AgentError):
        CorrectionService(agents.store, fetch=native).approve(
            readonly["id"],
            [
                {
                    "id": cards[0]["id"],
                    "expected_version": cards[0]["version"],
                    "catalog_id": "test-1",
                }
            ],
            "Explicit authorization",
        )
    with agents.store.connect(write=True) as db:
        db.execute("UPDATE users SET role='reader' WHERE username='owner'")
    with pytest.raises(ValueError):
        agents.issue(
            "No writes",
            "owner",
            "a",
            client="Reader",
            permissions=["corrections:apply"],
        )


def test_altered_native_source_blocks_apply_without_changing_copy(shop):
    client, agents, grant, cards, _other, _user = shop
    approval = approve(shop)[0]
    with agents.store.connect(write=True) as db:
        db.execute(
            "UPDATE agent_corrections SET source_json='{}' WHERE grant_id=?",
            (grant["id"],),
        )
    assert apply(client, approval).status_code == 409
    with agents.store.connect() as db:
        assert agents.store.get(db, cards[0]["id"]) == cards[0]
