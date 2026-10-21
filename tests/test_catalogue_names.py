from urllib.parse import parse_qs, urlsplit

import pytest
import test_intake
from test_intake import values

from pokeprice.intake import catalogue_candidates


@pytest.fixture
def client(tmp_path):
    yield from test_intake.client.__wrapped__(tmp_path)


def detail(ident="test-65", name="Noeunoeuf δ", **extra):
    return {
        "id": ident,
        "name": name,
        "localId": "65",
        "hp": 50,
        "set": {"name": "Test", "cardCount": {"official": 110}},
        **extra,
    }


def lookup(details):
    def get(url):
        if "?" in url:
            return details
        return next(c for c in details if url.endswith("/" + c["id"]))

    return get


def test_missing_delta_marker_discovers_candidate_without_weakening_identity():
    candidates = [
        detail(),
        detail("other-65", "Noeunoeuf de la Team Rocket"),
        detail("wrong-count-65", set={"name": "Wrong", "cardCount": {"official": 111}}),
        detail("wrong-hp-65", hp=70),
    ]
    query = {"name": "Noeunoeuf", "number": "65/110", "language": "fr", "hp": 50}
    result = catalogue_candidates(query, lookup(candidates))
    assert [c["id"] for c in result["candidates"]] == ["test-65"]
    assert result["candidates"][0]["name"] == "Noeunoeuf δ"
    assert result["candidates"][0]["printed_name"] == "Noeunoeuf"
    assert not catalogue_candidates({**query, "number": "64/110"}, lookup(candidates))[
        "candidates"
    ]
    # An explicitly printed Delta marker must not become a normal printing.
    assert not catalogue_candidates(
        {**query, "name": "Noeunoeuf δ"}, lookup([detail(name="Noeunoeuf")])
    )["candidates"]


@pytest.mark.parametrize("both_queries_match", [False, True])
@pytest.mark.parametrize(
    "printed,official",
    [
        ("Récupération d'Énergie", "Récupération d’Énergie"),
        ("Récupération d’Énergie", "Récupération d'Énergie"),
    ],
)
def test_quote_spellings_are_searched_and_duplicates_do_not_duplicate_candidates(
    printed, official, both_queries_match
):
    card = detail(name=official)
    calls = []

    def get(url):
        calls.append(url)
        if "?" not in url:
            return card
        name = parse_qs(urlsplit(url).query)["name"][0]
        return [card] if name == official or both_queries_match else []

    result = catalogue_candidates(
        {"name": printed, "number": "65/110", "language": "fr", "hp": 50}, get
    )
    assert [c["id"] for c in result["candidates"]] == [card["id"]]
    assert sum("?" not in url for url in calls) == 1


def test_equivalent_printed_name_can_be_saved_only_after_explicit_edition_choice(
    client,
):
    service = client.app.state.intake
    candidate = detail()
    service.lookup = lambda query: catalogue_candidates(query, lookup([candidate]))
    token = client.post("/api/intake/drafts").json()["token"]
    query = {"name": "Noeunoeuf", "number": "65/110", "language": "fr", "hp": 50}
    response = client.post(f"/api/intake/{token}/catalogue", json=query)
    assert response.status_code == 200, response.text
    assert [c["id"] for c in response.json()["candidates"]] == [candidate["id"]]
    for fields in (
        {"chosen_catalog_id": None},
        {"name": "Noeunoeuf de la Team Rocket"},
    ):
        rejected = client.post(
            f"/api/intake/{token}/save",
            json=values(
                client,
                **{
                    **query,
                    "set_name": "Test",
                    "chosen_catalog_id": candidate["id"],
                    "human_confirmed": True,
                    **fields,
                },
            ),
        )
        assert rejected.status_code == 422, rejected.text
    response = client.post(
        f"/api/intake/{token}/save",
        json=values(
            client,
            **query,
            set_name="Test",
            chosen_catalog_id=candidate["id"],
            human_confirmed=True,
        ),
    )
    assert response.status_code == 201, response.text
    card = response.json()
    assert (
        card["catalog_id"] == candidate["id"]
        and card["identification_status"] == "confirmed"
    )
    assert card["name"] == query["name"] and card["reference_cents"] is None
    assert not card["variant_confirmed"] and not card["condition_confirmed"]


def test_name_missing_its_delta_suffix_is_never_an_exact_match():
    """The δ edition may be proposed, but never preselected without a choice."""
    query = {"name": "Noeunoeuf", "number": "65/110", "language": "fr", "hp": 50}
    result = catalogue_candidates(query, lookup([detail()]))
    assert [c["id"] for c in result["candidates"]] == ["test-65"]
    assert result["exact"] is False
    exact = catalogue_candidates({**query, "name": "Noeunoeuf δ"}, lookup([detail()]))
    assert exact["exact"] is True
