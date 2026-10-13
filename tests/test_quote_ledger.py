"""Bound-price correction transactions with synthetic market evidence."""

import copy

import pytest
from test_print_reference import quote, reference_data
from test_reference_service import (
    client_context,
    create,
    install_fixture_reference,
    state,
)

from pokeprice.inventory import Conflict
from pokeprice.print_reference import validate_ruleset
from pokeprice.quote_ledger import (
    current,
    recheck_selection,
    restore_selection,
    select_acquisition,
)
from pokeprice.reference_service import ReferenceService


@pytest.fixture
def reference():
    return reference_data()


@pytest.fixture
def client(tmp_path):
    with client_context(tmp_path) as client:
        yield client


def acquisition(reference, **changes):
    record = quote(reference)
    return {
        **record,
        "native_metric": "trend-holo",
        "source_payload": {
            "product": "fixture:product-A",
            "trend-holo": 12.00,
            "avg30-holo": 9.00,
        },
        **changes,
    }


@pytest.fixture
def priced(client, reference):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp_state="absent",
        foil=True,
        variant_confirmed=True,
        variant_observation="Synthetic fixture",
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    result = select_acquisition(
        store,
        card["id"],
        card["version"],
        acquisition(reference),
        "pat",
        "Native price observed",
    )
    return store, result["card"], result["quote"]


def selected(store, card):
    with store.connect() as db:
        return current(db, card["id"])


def test_c01_bound_finish_clarification_preserves_quote_date_and_source(priced):
    store, card, original_quote = priced
    original_attestation = card["variant_verified_at"]
    changed = store.patch(
        card["id"],
        {"finish": "holo_border"},
        card["version"],
        "pat",
        "More precise physical finish",
    )
    assert changed["reference_cents"] == original_quote["amount_cents"]
    assert (
        changed["price_source"] == original_quote["source"]
        and changed["price_date"] == original_quote["observed_at"]
    )
    assert (
        not changed["variant_confirmed"]
        and changed["variant_verified_at"] != original_attestation
    )
    assert selected(store, changed)["quote"] == original_quote


def test_c03_same_foil_different_product_suspends_immutable_quote(priced):
    store, card, original_quote = priced
    changed = store.patch(
        card["id"],
        {"stamp_state": "present", "stamp": "EX Test"},
        card["version"],
        "pat",
        "Different observed stamp",
    )
    assert card["foil"] == changed["foil"]
    assert (
        changed["reference_cents"] is None
        and selected(store, changed)["state"] == "suspended"
    )
    assert selected(store, changed)["quote"] == original_quote
    assert store.listing()["reference_total_cents"] == 0


def test_c02_bound_stamp_alias_preserves_quote(client, reference):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp="EX Test",
        stamp_state="present",
        foil=True,
        variant_confirmed=True,
        variant_observation="Synthetic fixture",
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    observed = acquisition(
        reference,
        **quote(reference, "B"),
        source_payload={
            "product": "fixture:product-B",
            "trend-holo": 12,
            "avg30-holo": 9,
        },
    )
    result = select_acquisition(
        store,
        card["id"],
        card["version"],
        observed,
        "pat",
        "Native price for fixture B",
    )
    changed = store.patch(
        card["id"],
        {"stamp": "Test"},
        result["card"]["version"],
        "pat",
        "Equivalent stamp spelling",
    )
    assert (
        changed["reference_cents"] == observed["amount_cents"]
        and changed["price_date"] == observed["observed_at"]
    )
    assert selected(store, changed)["state"] == "active"


def test_bound_quote_and_recorded_decision_survive_restore(priced, tmp_path):
    from pokeprice.inventory import Store
    from pokeprice.inventory_backup import backup, restore_backup

    store, card, original_quote = priced
    path = tmp_path / "bound-backup.zip"
    backup(store, path)
    restore_backup(path, tmp_path / "restored")
    restored = Store(tmp_path / "restored")
    assert selected(restored, card)["quote"] == original_quote
    assert state(restored, card["id"]) == card
    result = restored.reference.replay(1)
    assert result["status"] == "reproduced" and result["proof_status"] == "available"


def test_c13_rule_label_update_preserves_then_binding_change_suspends(
    priced, reference
):
    store, card, original_quote = priced
    attestations = {
        k: v
        for k, v in card.items()
        if k.startswith("variant_")
        or k in ("finish", "stamp", "stamp_state", "condition_confirmed")
    }
    reference["content_version"] = "test.2"
    reference["bindings"]["A"]["label"] = "New label"
    store.reference = ReferenceService(store, validate_ruleset(reference))
    unchanged = recheck_selection(
        store, card["id"], card["version"], "maintenance", "Rules version update"
    )
    assert unchanged == card and selected(store, card)["quote"] == original_quote
    reference["bindings"]["A"]["product_ref"] = "fixture:product-C"
    store.reference = ReferenceService(store, validate_ruleset(reference))
    changed = recheck_selection(
        store, card["id"], card["version"], "maintenance", "Binding changed"
    )
    assert (
        changed["reference_cents"] is None
        and selected(store, changed)["state"] == "suspended"
    )
    assert {k: changed[k] for k in attestations} == attestations


def test_c15_suspend_return_and_audited_restoration(priced):
    store, card, original_quote = priced
    changed = store.patch(
        card["id"],
        {"stamp_state": "present", "stamp": "Test"},
        card["version"],
        "pat",
        "Different product",
    )
    returned = store.patch(
        card["id"],
        {"stamp_state": "absent", "stamp": ""},
        changed["version"],
        "pat",
        "Original observation corrected",
    )
    assert (
        returned["reference_cents"] is None
        and selected(store, returned)["state"] == "suspended"
    )
    before = copy.deepcopy(returned)
    restored = restore_selection(
        store,
        card["id"],
        returned["version"],
        original_quote["id"],
        "maintenance",
        "Explicit restoration with unchanged full binding",
    )
    assert restored["price_date"] == original_quote["observed_at"]
    assert restored["reference_cents"] == original_quote["amount_cents"]
    assert restored["variant_verified_at"] == before["variant_verified_at"]
    assert restored["observation_provenance"] == before["observation_provenance"]


def test_c15_deliberate_clear_prevents_restoration(priced):
    store, card, original_quote = priced
    cleared = store.patch(
        card["id"],
        {"reference_cents": None, "price_source": "", "price_date": ""},
        card["version"],
        "pat",
        "Explicitly removed this quote",
    )
    assert selected(store, cleared)["state"] == "revoked"
    with pytest.raises(ValueError, match="retirée"):
        restore_selection(
            store,
            card["id"],
            cleared["version"],
            original_quote["id"],
            "maintenance",
            "Do not resurrect",
        )
    assert state(store, card["id"]) == cleared


def test_c19_bound_valuation_only_combines_one_native_acquisition(priced, reference):
    store, card, _ = priced
    valued = store.listing()["items"][0]["valuation"]
    # One acquisition carries both metrics; the reference column stays the trend.
    assert valued["trend_cents"] == 1200 and valued["prudent_cents"] == 900
    assert card["reference_cents"] == 1200
    newer = acquisition(
        reference,
        acquisition_id="batch-B",
        observed_at="2026-01-01",
        source_payload={"trend-holo": 11.00, "avg30-holo": 8.00},
    )
    select_acquisition(
        store,
        card["id"],
        card["version"],
        newer,
        "pat",
        "Different acquisition",
    )
    valued = store.listing()["items"][0]["valuation"]
    # Metrics of batch A and batch B are never mixed.
    assert valued["trend_cents"] == 1100 and valued["prudent_cents"] == 800


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "USD"},
        {"source_payload": {"trend-holo": 12.00}},
        {"population": {"language": "en"}},
        {"source_payload": {}},
    ],
)
def test_incompatible_acquisition_cannot_replace_current_quote(
    priced, reference, changes
):
    store, card, original_quote = priced
    with pytest.raises(ValueError):
        select_acquisition(
            store,
            card["id"],
            card["version"],
            acquisition(reference, **changes),
            "pat",
            "Invalid acquisition",
        )
    assert (
        state(store, card["id"]) == card
        and selected(store, card)["quote"] == original_quote
    )


def test_c20_price_acquired_before_concurrent_edit_is_rejected_atomically(
    priced, reference
):
    store, card, original_quote = priced
    changed = store.patch(
        card["id"],
        {"notes": "Concurrent edit"},
        card["version"],
        "pat",
        "Newer correction",
    )
    with pytest.raises(Conflict):
        select_acquisition(
            store,
            card["id"],
            card["version"],
            acquisition(reference),
            "pat",
            "Stale network acquisition",
        )
    assert state(store, card["id"]) == changed
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM reference_quotes").fetchone()[0] == 2
        assert (
            db.execute("SELECT count(*) FROM reference_quote_events").fetchone()[0] == 1
        )


def test_manual_price_after_revocation_survives_unrelated_edit(priced):
    store, card, _ = priced
    manual = store.patch(
        card["id"],
        {"reference_cents": 4200, "price_source": "Manuel", "price_date": "2026-10-13"},
        card["version"],
        "pat",
        "Prix relevé à la main",
    )
    assert selected(store, manual)["state"] == "revoked"
    noted = store.patch(
        card["id"], {"notes": "Rangée"}, manual["version"], "pat", "Note"
    )
    assert noted["reference_cents"] == 4200 and noted["price_source"] == "Manuel"
    assert selected(store, noted)["state"] == "revoked"


def test_dispute_suspends_in_journal_and_withdrawal_does_not_resurrect(client, priced):
    store, card, original_quote = priced

    def dispute(version, active):
        response = client.post(
            f"/api/copies/{card['id']}/reference-dispute",
            json={
                "expected_version": version,
                "reason": "Produit contesté",
                "active": active,
                "affects": "market",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    disputed = dispute(card["version"], True)
    assert disputed["reference_cents"] is None
    assert selected(store, disputed)["state"] == "suspended"
    assert disputed["reference_resolution"]["price_selection"]["state"] == "suspended"
    withdrawn = dispute(disputed["version"], False)
    assert withdrawn["reference_cents"] is None
    assert selected(store, withdrawn)["state"] == "suspended"
    restored = restore_selection(
        store,
        card["id"],
        withdrawn["version"],
        original_quote["id"],
        "pat",
        "Contestation levée, correspondance vérifiée",
    )
    assert restored["reference_cents"] == original_quote["amount_cents"]


def test_rules_update_suspension_is_listed_then_journaled(priced, reference):
    from pokeprice.quote_ledger import recheck_all

    store, card, _ = priced
    changed = copy.deepcopy(reference)
    changed["bindings"]["A"]["product_ref"] = "fixture:product-C"
    store.reference = ReferenceService(store, validate_ruleset(changed))
    assert store.reference.audit()["counts"]["recheck_needed"] == 1
    listed = recheck_all(store, "system:test", "Nouvelle version")
    assert [s["copy_id"] for s in listed["suspensions"]] == [card["id"]]
    assert selected(store, card)["state"] == "active"
    applied = recheck_all(store, "system:test", "Nouvelle version", apply=True)
    assert applied["applied"] and selected(store, card)["state"] == "suspended"
    # Reverting the rules does not revive the price by itself.
    store.reference = ReferenceService(store, validate_ruleset(reference))
    assert selected(store, card)["state"] == "suspended"
    assert state(store, card["id"])["reference_cents"] is None
    assert store.reference.audit()["counts"]["recheck_needed"] == 0


def test_bound_quote_entry_from_card_records_one_acquisition(client, reference):
    card = create(
        client,
        catalog_id="synthetic-1",
        language="fr",
        number="1/1",
        identification_status="confirmed",
        finish="holo",
        stamp_state="absent",
        foil=True,
        variant_confirmed=True,
        variant_observation="Synthetic fixture",
    )
    store = client.app.state.store
    install_fixture_reference(store, reference)
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["reference_binding"]["product_ref"] == "fixture:product-A"
    entry = {
        "expected_version": detail["version"],
        "metrics": {"trend": "12.00"},
        "observed_on": "2026-01-02",
        "reason": "Cardmarket page read",
    }
    incomplete = client.post(f"/api/copies/{card['id']}/bound-quote", json=entry)
    assert incomplete.status_code == 422 and "ensemble" in incomplete.json()["detail"]
    entry["metrics"]["avg30"] = "9.00"
    future = client.post(
        f"/api/copies/{card['id']}/bound-quote",
        json={**entry, "observed_on": "2999-01-01"},
    )
    assert future.status_code == 422
    response = client.post(
        f"/api/copies/{card['id']}/bound-quote",
        json={**entry, "capture_sha256": "a" * 64},
    )
    assert response.status_code == 201, response.text
    quotes = response.json()["quotes"]
    assert {q["metric"]: q["amount_cents"] for q in quotes} == {
        "avg30": 900,
        "trend": 1200,
    }
    assert len({q["acquisition_id"] for q in quotes}) == 1
    assert quotes[0]["source_payload"] == {
        "trend-holo": 12.0,
        "avg30-holo": 9.0,
        "entry": "transcription",
        "capture_sha256": "a" * 64,
    }
    after = client.get(f"/api/copies/{card['id']}").json()
    assert after["reference_cents"] == 1200 and after["price_date"] == "2026-01-02"
    assert after["reference_resolution"]["price_selection"]["state"] == "active"
    stale = client.post(f"/api/copies/{card['id']}/bound-quote", json=entry)
    assert stale.status_code == 409


def test_bound_quote_entry_refused_without_verified_binding(client):
    card = create(client, catalog_id="synthetic-1", language="fr", number="1/1")
    detail = client.get(f"/api/copies/{card['id']}").json()
    assert detail["reference_binding"] is None
    response = client.post(
        f"/api/copies/{card['id']}/bound-quote",
        json={
            "expected_version": detail["version"],
            "metrics": {"trend": "1", "avg30": "1"},
            "observed_on": "2026-01-02",
            "reason": "No binding",
        },
    )
    assert response.status_code == 422
