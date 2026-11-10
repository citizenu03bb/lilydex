"""Read routes of the lots tool on the agent API: pool, status, plan, publication."""

import pytest
from fastapi.testclient import TestClient
from test_pokeprice_lots import add_copy, test_db  # noqa: F401 - fixture

import pokeprice.agent_lots_api as lots_api
from pokeprice.agent import AgentService
from pokeprice.agent_api import PREFIX, schema
from pokeprice.lots import DEFAULT_ACTOR, LotsEngine
from pokeprice.lots.agent_recipe import AgentRecipe, to_recipe
from pokeprice.pricing import set_lot_max_margin
from pokeprice.webapp import UserCreate, add_user, create_app

PASSWORD = "Lots-api-test-password!"
LOTS = PREFIX + "/lots"
ADDED = {"scope", "max_per_lot", "value_ceiling_cents", "request_id", "excluded_truncated", "to_price_truncated"}
RECIPE = {
    "title": "Doublons Duels au Sommet",
    "summary": "Les doublons de la série.",
    "bundle_rules": {"target_count": 3, "diversity": "any"},
}


def no_network(*args, **kwargs):
    raise AssertionError("A lots read must never call a model or a catalogue")


@pytest.fixture
def lots(test_db):  # noqa: F811
    """The synthetic base of the lots tool tests, plus two more duplicate references."""
    _, store = test_db
    with store.connect(write=True) as db:
        user = add_user(db, UserCreate(username="owner", password=PASSWORD, role="admin"))
    for position in (10, 11, 12):
        add_copy(store, "b", position, price=150, name="Kabuto", catalog_id="dp5-60", number="60/100")
    app = create_app(
        store.root,
        intake_reader=no_network,
        intake_lookup=no_network,
        price_fetch=no_network,
        variant_fetch=no_network,
        market_fetch=no_network,
    )
    service = AgentService(store)
    grant = service.issue("Lots", "owner", "a", client="Synthetic lots client", permissions=["lots:read"])
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + grant["token"]
        yield client, service, grant, user


def engine(store):
    return LotsEngine(store, value_ceiling_cents=1000)


def snapshot(store):
    with store.connect() as db:
        return list(db.iterdump())


def tool_draft(store, copy_ids, price_cents, title="Lot outil"):
    lot = {
        "title": title,
        "summary": "Lot de test",
        "total_reference_cents": 0,
        "asking_cents": price_cents,
        "copies": [{"id": c} for c in copy_ids],
    }
    with store.connect(write=True) as db:
        return engine(store).create_draft(db, lot, DEFAULT_ACTOR)


def human_draft(store, copy_ids, title="Vinted pour une amie"):
    with store.connect(write=True) as db:
        return store.create_sale(
            {"title": title, "channel": "Lot", "amount_cents": 500, "asking_cents": 500}, copy_ids, "owner", _db=db
        )


def duplicate_ids(store):
    with store.connect() as db:
        return [c["id"] for c in engine(store).classify_pool(db)["duplicates"]]


def test_the_contract_lists_the_lots_read_routes():
    paths = schema()["paths"]
    assert set(paths[LOTS + "/pool"]) == {"get"}
    assert set(paths[LOTS + "/status"]) == {"get"}
    assert set(paths[LOTS + "/plan"]) == {"post"}
    assert set(paths[LOTS + "/{sale_id}/publication"]) == {"get"}


def test_pool_is_the_engine_analysis(lots):
    client, service, *_ = lots
    response = client.get(LOTS + "/pool", params={"max_per_lot": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    with service.store.connect() as db:
        expected = engine(service.store).analyze(db, max_cards_per_lot=5)
    assert {k: v for k, v in body.items() if k not in ADDED} == expected
    assert body["scope"] == "duplicates" and body["max_per_lot"] == 5
    assert body["value_ceiling_cents"] == 1000 and body["request_id"]
    copies = [c for lot in body["lots"] for c in lot["copies"]]
    assert copies and all(c["version"] >= 1 and c["id"] for c in copies)
    assert not any(c["from_album"] for c in copies)


def test_pool_caps_its_lists_but_keeps_the_totals(lots, monkeypatch):
    client, service, *_ = lots
    for position in (20, 21, 22):  # the first stays in the album, out of the report
        add_copy(service.store, "a", position, price=None, name="Sans prix", catalog_id="dp5-70", number="70/100")
    monkeypatch.setattr(lots_api, "LIST_CAP", 1)
    body = client.get(LOTS + "/pool").json()
    assert len(body["excluded"]) == 1 and body["excluded_count"] >= 2 and body["excluded_truncated"]
    assert len(body["to_price"]) == 1 and body["to_price_count"] >= 2 and body["to_price_truncated"]


@pytest.mark.parametrize("value", [2, 51, "x"])
def test_pool_bounds_max_per_lot(lots, value):
    client, *_ = lots
    response = client.get(LOTS + "/pool", params={"max_per_lot": value})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "detail", "request_id"}


def test_status_marks_tool_made_drafts_and_hides_human_titles(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    mine = tool_draft(service.store, free[:2], 400)
    theirs = human_draft(service.store, free[2:3])
    body = client.get(LOTS + "/status").json()
    with service.store.connect() as db:
        expected = engine(service.store).status(db)
    drafts = {d["id"]: d for d in body["active_drafts"]}
    assert set(drafts) == {mine, theirs} == {d["id"] for d in expected["active_drafts"]}
    assert drafts[mine]["tool_made"] is True and drafts[mine]["title"] == "Lot outil"
    assert drafts[theirs]["tool_made"] is False and drafts[theirs]["title"] is None
    assert body["max_drafts"] == 5 and body["cap_used"] == 2 and body["tool_made_drafts_count"] == 1
    assert body["online_drafts_count"] == 0 and body["blocked_by"] == []
    assert "Vinted pour une amie" not in client.get(LOTS + "/status").text


def test_status_says_when_the_cap_blocks_new_lots(lots):
    client, service, *_ = lots
    for position in range(30, 40):
        add_copy(service.store, "b", position, price=120, name="Amonita", catalog_id="dp5-61", number="61/100")
    free = duplicate_ids(service.store)
    for n in range(5):
        tool_draft(service.store, free[2 * n : 2 * n + 2], 400, title=f"Lot {n}")
    body = client.get(LOTS + "/status").json()
    assert body["cap_used"] == 5 and body["capacity_available"] == 0
    assert [b["code"] for b in body["blocked_by"]] == ["draft_cap_reached"]


def test_a_draft_from_the_agent_drafts_route_is_not_tool_made(lots):
    _, service, grant, _ = lots
    free = duplicate_ids(service.store)
    with service.store.connect(write=True) as db:
        sale_id = service.store.create_sale({"title": "Album", "amount_cents": 0}, free[:1], "agent:" + grant["id"], _db=db)
        assert not LotsEngine.tool_made(db, sale_id)


def test_plan_is_the_engine_composition_and_writes_nothing(lots):
    client, service, *_ = lots
    before = snapshot(service.store)
    response = client.post(LOTS + "/plan", json={"recipe": RECIPE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert snapshot(service.store) == before
    with service.store.connect() as db:
        expected = engine(service.store).compose_from_recipe(db, to_recipe(AgentRecipe.model_validate(RECIPE)))
    lot = body["lot"]
    assert [(c["id"], c["version"]) for c in lot["copies"] + lot["bonus"]] == [
        (c["id"], c["version"]) for c in expected["lot"]["copies"]
    ]
    assert lot["asking_cents"] == expected["lot"]["asking_cents"]
    assert lot["margin"] == 15
    assert lot["floor_cents"] == max(50, -(-lot["total_reference_cents"] * 85 // 100))
    assert lot["asking_cents"] >= lot["floor_cents"]
    assert body["scope"] == "duplicates" and not lot["contains_album_copies"]
    assert set(c["id"] for c in lot["copies"]) <= set(duplicate_ids(service.store))
    assert len(body["plan_id"]) == 64
    assert client.post(LOTS + "/plan", json={"recipe": RECIPE}).json()["plan_id"] == body["plan_id"]


def test_plan_id_follows_copy_versions_and_the_margin(lots):
    client, service, *_ = lots
    first = client.post(LOTS + "/plan", json={"recipe": RECIPE}).json()
    chosen = first["lot"]["copies"][0]["id"]
    with service.store.connect(write=True) as db:
        db.execute("UPDATE copies SET version=version+1 WHERE id=?", (chosen,))
    second = client.post(LOTS + "/plan", json={"recipe": RECIPE}).json()
    assert second["plan_id"] != first["plan_id"]
    set_lot_max_margin(service.store, 20, "owner")
    third = client.post(LOTS + "/plan", json={"recipe": RECIPE}).json()
    assert third["lot"]["margin"] == 20 and third["plan_id"] != second["plan_id"]


def test_plan_without_a_match_has_no_plan_id_and_no_foreign_titles(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    human_draft(service.store, free[:1], title="Titre privé")
    recipe = {**RECIPE, "filters": {"pokemon_names": ["Zarbi", "Mewtwo"], "min_cents": 999}}
    body = client.post(LOTS + "/plan", json={"recipe": recipe}).json()
    assert body["lot"] is None and body["plan_id"] is None
    assert "Titre privé" not in str(body)


@pytest.mark.parametrize(
    "payload",
    [
        {"recipe": RECIPE, "scope": "all"},
        {"recipe": {**RECIPE, "actor": "pokeprice-lots"}},
        {"recipe": {**RECIPE, "filters": {"margin": 0}}},
        {"recipe": {**RECIPE, "title": "Voir https://exemple.test"}},
        {"recipe": {**RECIPE, "title": "Lot sur exemple.com"}},
        {"recipe": {**RECIPE, "title": "<b>Lot</b>"}},
        {"recipe": {**RECIPE, "summary": "Écrivez à vente@exemple"}},
        {"recipe": {**RECIPE, "title": "x" * 121}},
        {"recipe": {**RECIPE, "summary": "x" * 501}},
        {"recipe": {**RECIPE, "title": ""}},
        {"recipe": {**RECIPE, "filters": {"pokemon_names": ["Pikachu"] * 21}}},
        {"recipe": {**RECIPE, "filters": {"pokemon_names": ["<script>"]}}},
        {"recipe": {**RECIPE, "filters": {"eras": ["dp_platine; DROP"]}}},
        {"recipe": {**RECIPE, "filters": {"finishes": ["gold"]}}},
        {"recipe": {**RECIPE, "filters": {"min_cents": "100"}}},
        {"recipe": {**RECIPE, "bundle_rules": {"target_count": 51}}},
        {"recipe": {**RECIPE, "scoring": {"value_intent": "steal"}}},
        {"recipe": {key: value for key, value in RECIPE.items() if key != "title"}},
    ],
)
def test_plan_refuses_a_loose_recipe(lots, payload):
    client, service, *_ = lots
    before = snapshot(service.store)
    response = client.post(LOTS + "/plan", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_request"
    assert snapshot(service.store) == before


def test_the_strict_recipe_converts_without_changing_the_script_recipe():
    recipe = AgentRecipe.model_validate(
        {**RECIPE, "filters": {"pokemon_names": ["Nidoran♀", "M. Mime"], "eras": ["dp_platine"]}}
    )
    converted = to_recipe(recipe)
    assert converted.title == RECIPE["title"] and converted.filters.pokemon_names == ["Nidoran♀", "M. Mime"]
    # The script still accepts what it accepted, URL and unknown fields included.
    loose = type(converted).model_validate({"title": "https://exemple.test", "summary": "", "extra": 1})
    assert loose.title == "https://exemple.test"


def test_publication_reports_a_publishable_tool_draft_without_writing(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    sale_id = tool_draft(service.store, free[:3], 1000)
    before = snapshot(service.store)
    body = client.get(f"{LOTS}/{sale_id}/publication").json()
    assert snapshot(service.store) == before
    assert body["publishable"] is True and body["floor_refused"] is False
    assert body["copies_count"] == 3 and body["price_cents"] == 1000 and body["waiver"] is None
    with service.store.connect() as db:
        _, copy_ids, to_unpublish, price = engine(service.store).publication_plan(db, sale_id)
    assert body["copy_ids"] == copy_ids and body["unpublish_count"] == len(to_unpublish)


def test_publication_reports_a_floor_refusal_and_other_refusals(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    low = tool_draft(service.store, free[:3], 60, title="Lot bradé")
    body = client.get(f"{LOTS}/{low}/publication").json()
    assert body["publishable"] is False and body["floor_refused"] is True
    assert body["price_cents"] == 60 and body["floor_cents"] > 60 and body["margin"] == 15
    single = tool_draft(service.store, free[3:4], 500, title="Lot seul")
    body = client.get(f"{LOTS}/{single}/publication").json()
    assert body["publishable"] is False and body["floor_refused"] is False
    assert "au moins deux" in body["refusal"]


def test_publication_of_a_human_or_unknown_draft_is_not_found(lots):
    client, service, *_ = lots
    free = duplicate_ids(service.store)
    theirs = human_draft(service.store, free[:2])
    for sale_id in (theirs, "inconnu"):
        response = client.get(f"{LOTS}/{sale_id}/publication")
        assert response.status_code == 404
        assert set(response.json()) == {"code", "detail", "request_id"}
        assert "Vinted" not in response.text


def calls(sale_id="inconnu"):
    return [
        ("get", LOTS + "/pool", None),
        ("get", LOTS + "/status", None),
        ("post", LOTS + "/plan", {"recipe": RECIPE}),
        ("get", f"{LOTS}/{sale_id}/publication", None),
    ]


@pytest.mark.parametrize("permissions", [["copies:read"], ["lots:compose"], ["lots:publish"]])
def test_every_lots_route_requires_lots_read(lots, permissions):
    client, service, *_ = lots
    other = service.issue("Autre", "owner", "a", client="Synthetic", permissions=permissions)
    for method, path, body in calls():
        response = getattr(client, method)(
            path, headers={"Authorization": "Bearer " + other["token"]}, **({"json": body} if body else {})
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize("change", ["demoted", "disabled"])
def test_a_demoted_or_disabled_owner_loses_lots_on_the_next_call(lots, change):
    client, service, _, user = lots
    assert client.get(LOTS + "/status").status_code == 200
    with service.store.connect(write=True) as db:
        if change == "demoted":
            db.execute("UPDATE users SET role='editor' WHERE id=?", (user["id"],))
        else:
            db.execute("UPDATE users SET disabled=1 WHERE id=?", (user["id"],))
    expected = 403 if change == "demoted" else 401
    for method, path, body in calls():
        response = getattr(client, method)(path, **({"json": body} if body else {}))
        assert response.status_code == expected, (path, response.text)


def test_heavy_routes_share_a_stricter_per_grant_limit(lots):
    client, *_ = lots
    for _ in range(lots_api.HEAVY_PER_MINUTE // 2):
        assert client.get(LOTS + "/pool").status_code == 200
        assert client.post(LOTS + "/plan", json={"recipe": RECIPE}).status_code == 200
    refused = client.get(LOTS + "/pool")
    assert refused.status_code == 429 and refused.headers["Retry-After"] == "60"
    assert refused.json()["code"] == "rate_limited"
    assert client.post(LOTS + "/plan", json={"recipe": RECIPE}).status_code == 429
    # The light routes keep the general limit.
    assert client.get(LOTS + "/status").status_code == 200


def test_a_grant_without_lots_read_does_not_use_the_heavy_budget(lots):
    client, service, *_ = lots
    other = service.issue("Autre", "owner", "a", client="Synthetic", permissions=["lots:compose"])
    for _ in range(lots_api.HEAVY_PER_MINUTE + 2):
        response = client.get(LOTS + "/pool", headers={"Authorization": "Bearer " + other["token"]})
        assert response.status_code == 403
