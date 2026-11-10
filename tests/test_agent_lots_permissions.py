"""Lots permissions on agent keys: admin only, live per call, journalled, no endpoint yet."""

import json
import sys

import pytest
from fastapi.testclient import TestClient
from test_agent_control import PASSWORD, shop  # noqa: F401

from pokeprice.agent import (
    GRANT_CREATED,
    GRANT_REVOKED,
    LOTS_MAX_CEILING_CENTS,
    AgentError,
    AgentService,
    digest,
    lots_ceiling_cents,
    permitted,
)
from pokeprice.agent_api import PREFIX
from pokeprice.manage import main as manage
from pokeprice.webapp import UserCreate, add_user

LOTS = ["lots:read", "lots:compose", "lots:publish"]


def lots_key(service, owner="owner", **options):
    options.setdefault("permissions", LOTS)
    return service.issue("Lots", owner, "a", client="Synthetic lots client", **options)


def authorize(service, grant, permission):
    with service.store.connect() as db:
        return AgentService.authorize(db, digest(grant["token"]), permission)


def bearer(app, grant):
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + grant["token"]
    return client


def grant_events(store, grant_id=None):
    """Grant journal rows; the fixture's own key is journalled too, hence the filter."""
    with store.connect() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT copy_id,actor,kind,before_json,after_json FROM events "
                "WHERE kind IN (?,?) ORDER BY id",
                (GRANT_CREATED, GRANT_REVOKED),
            )
        ]
    if grant_id is None:
        return rows
    return [r for r in rows if json.loads(r["after_json"])["grant_id"] == grant_id]


def add_account(store, username, role):
    with store.connect(write=True) as db:
        return add_user(db, UserCreate(username=username, password=PASSWORD, role=role))


def test_permitted_strips_lots_scopes_from_every_non_admin_role():
    held = {"copies:read", "assistant:read", *LOTS}
    assert permitted(held, "admin") == held
    assert permitted(held, "editor") == {"copies:read", "assistant:read"}
    assert permitted(held, "reader") == {"copies:read"}


@pytest.mark.parametrize("role", ["editor", "reader"])
def test_only_an_active_admin_may_issue_lots_permissions(shop, role):
    _, service, *_ = shop
    journal = grant_events(service.store)
    add_account(service.store, "staff", role)
    for permission in LOTS:
        with pytest.raises(ValueError, match="administrateur"):
            lots_key(service, "staff", permissions=[permission])
    with service.store.connect(write=True) as db:
        db.execute("UPDATE users SET role='admin',disabled=1 WHERE username='staff'")
    with pytest.raises(ValueError, match="actif"):
        lots_key(service, "staff")
    assert grant_events(service.store) == journal


def test_publish_does_not_imply_compose(shop):
    _, service, *_ = shop
    grant = lots_key(service, permissions=["lots:publish"])
    assert grant["permissions"] == ["copies:read", "lots:publish"]
    assert authorize(service, grant, "lots:publish")
    for permission in ("lots:compose", "lots:read"):
        with pytest.raises(AgentError) as refused:
            authorize(service, grant, permission)
        assert refused.value.status == 403


@pytest.mark.parametrize(
    "other", ["corrections:apply", "drafts:create", "assistant:read"]
)
@pytest.mark.parametrize("permission", LOTS)
def test_a_lots_key_does_not_combine_with_writes_or_the_assistant(
    shop, permission, other
):
    _, service, *_ = shop
    journal = grant_events(service.store)
    with pytest.raises(ValueError, match="lots ne se combine"):
        lots_key(service, permissions=[permission, other])
    assert grant_events(service.store) == journal


@pytest.mark.parametrize("change", ["demoted", "disabled"])
def test_demoted_or_disabled_owner_loses_lots_on_the_next_call(shop, change):
    client, service, _, _, _, user = shop
    grant = lots_key(service)
    assert authorize(service, grant, "lots:compose")
    with bearer(client.app, grant) as agent:
        assert "lots" in agent.get(PREFIX + "/capabilities").json()
        with service.store.connect(write=True) as db:
            if change == "demoted":
                db.execute("UPDATE users SET role='editor' WHERE id=?", (user["id"],))
            else:
                db.execute("UPDATE users SET disabled=1 WHERE id=?", (user["id"],))
        response = agent.get(PREFIX + "/capabilities")
    if change == "demoted":
        view = response.json()
        assert "lots" not in view and not any(
            op.startswith("lots-") for op in view["operations"]
        )
        assert view["permissions"] == ["copies:read"]
        for permission in LOTS:
            with pytest.raises(AgentError) as refused:
                authorize(service, grant, permission)
            assert refused.value.status == 403
        assert authorize(service, grant, "copies:read")
    else:
        assert response.status_code == 401
        with pytest.raises(AgentError) as refused:
            authorize(service, grant, "lots:read")
        assert refused.value.status == 401


def test_value_ceiling_defaults_and_is_clamped_for_lots_keys(shop):
    _, service, *_ = shop
    assert lots_key(service)["value_ceiling_cents"] == 1000
    clamped = lots_key(service, value_ceiling_cents=5000)
    assert clamped["value_ceiling_cents"] == LOTS_MAX_CEILING_CENTS
    assert lots_key(service, value_ceiling_cents=1500)["value_ceiling_cents"] == 1500
    # A plain key keeps the ceiling it was given.
    plain = service.issue("Plain", "owner", "a", client="c", value_ceiling_cents=5000)
    assert plain["value_ceiling_cents"] == 5000
    # Whatever the row says, a lots operation never goes above the code maximum.
    with service.store.connect(write=True) as db:
        db.execute(
            "UPDATE agent_grants SET value_ceiling_cents=90000 WHERE id=?",
            (clamped["id"],),
        )
    assert lots_ceiling_cents(authorize(service, clamped, "lots:read")) == 2000


def test_lots_keys_last_seven_days_by_default(shop):
    _, service, *_ = shop
    grant = lots_key(service)
    assert grant["expires_in_days"] == 7


def test_issue_and_revoke_are_journalled_without_secrets_or_migration(shop):
    _, service, *_ = shop
    with service.store.connect() as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
    grant = lots_key(service, permissions=["lots:read"], actor="owner")
    service.revoke(grant["id"])
    with pytest.raises(KeyError):
        service.revoke("unknown")
    created, revoked = grant_events(service.store, grant["id"])
    assert created["copy_id"] is None and revoked["copy_id"] is None
    assert (created["actor"], created["kind"]) == ("owner", GRANT_CREATED)
    assert (revoked["actor"], revoked["kind"]) == ("system:manage", GRANT_REVOKED)
    details = json.loads(created["after_json"])
    assert details["grant_id"] == grant["id"]
    assert details["permissions"] == ["copies:read", "lots:read"]
    assert details["value_ceiling_cents"] == 1000
    assert json.loads(revoked["before_json"])["revoked_at"] == ""
    assert json.loads(revoked["after_json"])["revoked_at"]
    journal = json.dumps(grant_events(service.store, grant["id"]))
    assert grant["token"] not in journal and digest(grant["token"]) not in journal
    with pytest.raises(AgentError) as refused:
        authorize(service, grant, "lots:read")
    assert refused.value.status == 401
    with service.store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version


def test_capabilities_list_lots_operations_per_permission_collection_wide(shop):
    client, service, *_ = shop
    grant = lots_key(service, permissions=["lots:read", "lots:publish"])
    with bearer(client.app, grant) as agent:
        view = agent.get(PREFIX + "/capabilities").json()
    assert view["lots"] == {
        "scope": "collection",
        "permissions": ["lots:publish", "lots:read"],
        "operations": [
            "lots-publish",
            "lots-unpublish",
            "lots-pool",
            "lots-status",
            "lots-plan",
        ],
        "value_ceiling_cents": 1000,
    }
    assert "lots-compose" not in view["operations"]
    assert set(view["lots"]["operations"]) <= set(view["operations"])


def test_a_grant_without_lots_permissions_sees_what_it_saw_before(shop):
    client, service, grant, *_ = shop
    plain = service.issue("Reader", "owner", "a", client="text-only")
    expected = {
        grant["id"]: (
            ["copies", "copy", "prepare-lot", "draft", "photo", "package", "create-draft"],
            ["copies:read", "drafts:create", "photos:read"],
        ),
        plain["id"]: (
            ["copies", "copy", "prepare-lot", "draft"],
            ["copies:read"],
        ),
    }
    for key in (grant, plain):
        with bearer(client.app, key) as agent:
            view = agent.get(PREFIX + "/capabilities").json()
        assert "lots" not in view
        assert (view["operations"], view["permissions"]) == expected[key["id"]]
        assert view["limits"] == {
            "copies_per_page": 100,
            "copies_per_draft": 20,
            "requests_per_minute": 60,
        }
        assert set(view) == {
            "contract_version",
            "agent_id",
            "name",
            "album_id",
            "client",
            "permissions",
            "expires_at",
            "value_ceiling_cents",
            "limits",
            "operations",
            "request_id",
        }


def test_manage_issues_a_lots_key_with_a_collection_wide_note(
    shop, tmp_path, monkeypatch, capsys
):
    _, service, *_ = shop
    token = tmp_path / "lots.token"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pokeprice-manage",
            "--data",
            str(service.store.root),
            "agent-create",
            "Lots agent",
            "--owner",
            "owner",
            "--album",
            "a",
            "--client",
            "Synthetic lots client",
            "--lots-read",
            "--lots-publish",
            "--value-ceiling-eur",
            "50",
            "--token-file",
            str(token),
        ],
    )
    manage()
    printed = capsys.readouterr()
    issued = json.loads(printed.out)
    assert issued["permissions"] == ["copies:read", "lots:publish", "lots:read"]
    assert issued["value_ceiling_cents"] == 2000
    assert "toute la collection" in printed.err and "20.00 €" in printed.err
    assert token.read_text().strip() not in printed.out + printed.err
    (created,) = grant_events(service.store, issued["id"])
    assert created["actor"] == "system:manage"
