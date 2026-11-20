"""M2 slice 5: when the catalogue finds nothing, the image proposes an edition."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_condition_assessment import picture
from test_edition_check import png

from pokeprice.edition_check import (
    EditionSuggester,
    SetCounts,
    digital_only,
    image_proposal,
    number_filter,
    read_name_gallery,
)
from pokeprice.intake import catalogue_candidates
from pokeprice.webapp import create_app

API = "https://api.tcgdex.net/v2"
SETS = {"pl1": 127, "sv5": 162, "ex3": 97, "neo3": 64, "promo": 40}
PRINTS = {
    "pl1-120": {"name": "Fossile Crâne", "localId": "120"},
    "sv5-150": {"name": "Fossile Crâne", "localId": "150"},
    "ex3-69": {"name": "Chamallot", "localId": "69"},
    "ex3-70": {"name": "Chamallot", "localId": "70"},
    "neo3-58": {"name": "Zarbi K", "localId": "58"},
    "promo-4": {"name": "Chamallot", "localId": "4", "image": None},
    "decoy-1": {"name": "Fossile Crâne Ancien", "localId": "1"},
}
OBSERVATION = {
    "name": "Fossile crâne",
    "number": "",
    "language": "fr",
    "hp": None,
    "readable_front": True,
    "flaws": "",
    "notes": "",
}


def image(card_id, language="fr"):
    if card_id in PRINTS and "image" in PRINTS[card_id]:
        return PRINTS[card_id]["image"]
    return f"https://assets.tcgdex.net/{language}/x/{card_id}"


class Catalogue:
    """TCGdex as the slice reads it: a contains search, card details, sets."""

    def __init__(self, prints=PRINTS):
        self.prints, self.urls = prints, []

    def __call__(self, url):
        self.urls.append(url)
        language, rest = url.removeprefix(API + "/").split("/", 1)
        if rest == "sets":
            return [{"id": i, "cardCount": {"official": n}} for i, n in SETS.items()]
        if rest.startswith("cards?"):
            word = parse_qs(urlsplit(url).query)["name"][0].casefold()
            found = [
                {"id": i, "localId": p["localId"], "name": p["name"], "image": image(i, language)}
                for i, p in self.prints.items()
                if word in p["name"].casefold()
            ]
            # A TCG Pocket print exists only in the app, never in a binder.
            return found + [
                {"id": "A1-1", "name": "Fossile Crâne", "image": "https://assets.tcgdex.net/fr/tcgp/A1/1"}
            ]
        card_id = rest.removeprefix("cards/")
        if card_id not in self.prints:
            return None
        return {
            "id": card_id,
            **self.prints[card_id],
            "set": {"name": f"Série {card_id.split('-')[0]}", "cardCount": {"official": SETS[card_id.split("-")[0]]}},
            "image": image(card_id, language),
        }


class Reader:
    source, model, protocol = "fake", "fake-dino", "edition-same-name-v1"

    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def __call__(self, photo, references):
        self.calls.append(sorted(references))
        return {i: self.scores[i] for i in references}, "", {"seconds": 0.1}


def no_image_for(*ids):
    def fetch(url):
        if any(f"/{i}" in url or f"/{i.split('-')[1]}_hires" in url for i in ids):
            raise OSError("introuvable")
        return png()

    return fetch


@pytest.mark.parametrize(
    "read, expected",
    [
        ("Fossile crâne", ["pl1-120", "sv5-150"]),  # Another case, accents kept.
        ("FOSSILE CRANE", ["pl1-120", "sv5-150"]),  # Upper case, no accent.
        ("Zarbi [K]", ["neo3-58"]),  # Brackets around the letter.
    ],
)
def test_gallery_of_the_name_read_ignores_case_accents_and_brackets(read, expected):
    catalogue = Catalogue()
    gallery = read_name_gallery(read, "fr", catalogue)
    # The French and English searches find the same prints, recorded once.
    assert [g["id"] for g in gallery] == expected
    assert all(g["language"] == "fr" for g in gallery)
    # A search by content on the longest word, not an exact (case-sensitive) one.
    assert all("eq%3A" not in u for u in catalogue.urls)


def refs(*ids, count=None):
    return [
        {"id": i, "local_id": i.split("-")[1], "count": count or SETS[i.split("-")[0]], "image": image(i)}
        for i in ids
    ]


def test_number_filter_keeps_the_number_or_the_set_size_even_misread():
    prints = refs("ex3-69", "ex3-70", "promo-4")
    # « 68/97 » is misread, but its set size keeps the 97-card set.
    kept, discarded = number_filter("68/97", prints)
    assert [r["id"] for r in kept] == ["ex3-69", "ex3-70"]
    assert [r["id"] for r in discarded] == ["promo-4"]
    # A partial number keeps the prints with that number.
    assert [r["id"] for r in number_filter("69/", prints)[0]] == ["ex3-69"]
    assert [r["id"] for r in number_filter("004", prints)[0]] == ["promo-4"]
    # Without any number read, nothing is filtered.
    assert number_filter("", prints) == (prints, [])


def test_proposal_needs_a_clear_gap_and_every_kept_print_seen():
    one, two = refs("ex3-69"), refs("ex3-69", "ex3-70")
    alone = image_proposal(one, {"ex3-69": 0.4}, filtered=True)
    assert alone["status"] == "proposed" and alone["top"] == "ex3-69"
    clear = image_proposal(two, {"ex3-69": 0.90, "ex3-70": 0.80}, filtered=True)
    assert clear["status"] == "proposed" and clear["gap"] == 0.1
    close = image_proposal(two, {"ex3-69": 0.90, "ex3-70": 0.88}, filtered=True)
    assert close["status"] == "undecided" and close["top"] == "ex3-69"
    # The number kept a print without image: it may be the true one.
    unseen = image_proposal(two, {"ex3-69": 0.90}, filtered=True)
    assert unseen["status"] == "none" and unseen["missing_images"] == ["ex3-70"]
    # Without a number, the proposal stands and names the unseen print.
    named = image_proposal(two, {"ex3-69": 0.90}, filtered=False)
    assert named["status"] == "proposed" and "ex3-70" in named["reason"]
    assert image_proposal([], {}, filtered=True)["status"] == "none"


def test_catalogue_compares_names_without_case():
    def get(url):
        if "?" in url:
            return [{"id": "pl1-120", "name": "Fossile Crâne", "localId": "120"}]
        return {
            "id": "pl1-120",
            "name": "Fossile Crâne",
            "localId": "120",
            "set": {"name": "Rivaux Émergents", "cardCount": {"official": 127}},
        }

    query = {"name": "Fossile crâne", "number": "120/127", "language": "fr", "hp": None}
    result = catalogue_candidates(query, get)
    assert [c["id"] for c in result["candidates"]] == ["pl1-120"]


def test_set_sizes_come_from_tcgdex_sets_once_then_from_the_cache(tmp_path):
    catalogue = Catalogue()
    counts = SetCounts(catalogue, tmp_path)
    assert counts("fr")["ex3"] == 97 and counts("fr")["pl1"] == 127
    assert catalogue.urls == [f"{API}/fr/sets"]
    # A restart reads the file instead of asking TCGdex again.
    again = Catalogue()
    assert SetCounts(again, tmp_path)("fr")["ex3"] == 97 and again.urls == []


def suggester(tmp_path, scores, download=None):
    class Checks:  # The parts of EditionCheckService the suggester uses.
        from pokeprice.edition_check import EditionCheckService as _service

        get_json, references = Catalogue(), tmp_path / "refs"
        reader = Reader(scores)
        fetch = staticmethod(download or (lambda url: png()))
        image = _service.image
        set_name = _service.set_name

    return EditionSuggester(Checks()), Checks


def test_a_print_without_image_kept_by_the_number_blocks_the_proposal(tmp_path):
    suggest, checks = suggester(
        tmp_path, {"ex3-69": 0.9, "ex3-70": 0.7, "promo-4": 0.95}, no_image_for("promo-4")
    )
    query = {"name": "Chamallot", "number": "4/40", "language": "fr"}
    blocked = suggest(b"photo", query)
    assert "candidates" not in blocked
    assert blocked["image_proposal"]["missing_images"] == ["promo-4"]
    # A number that sets the promo aside lets the image decide.
    [candidate] = suggest(b"photo", {**query, "number": "69/97"})["candidates"]
    assert candidate["id"] == "ex3-69"
    # Without any number, the proposal names the print the image cannot see.
    loose = suggest(b"photo", {**query, "number": ""})
    assert loose["candidates"][0]["id"] == "ex3-69"
    assert "promo-4" in loose["image_proposal"]["reason"]


def test_tcg_pocket_prints_are_left_out_even_without_image():
    assert digital_only({"id": "A4-127", "image": None})
    assert digital_only({"id": "P-A-12"})
    assert not digital_only({"id": "bw1-75", "image": "https://assets.tcgdex.net/fr/bw/bw1/75"})


def test_partial_number_narrows_then_the_image_proposes(tmp_path):
    suggest, checks = suggester(tmp_path, {"ex3-69": 0.70, "ex3-70": 0.90})
    prints = {k: v for k, v in PRINTS.items() if k != "promo-4"}
    checks.get_json.prints = prints
    result = suggest(b"photo", {"name": "chamallot", "number": "68/97", "language": "fr"})
    [candidate] = result["candidates"]
    assert candidate["id"] == "ex3-70" and candidate["proposed_by"] == "image"
    assert candidate["number"] == "70/97" and candidate["printed_number"] == "70/97"
    assert candidate["language"] == "fr" and candidate["name"] == "Chamallot"
    assert result["image_proposal"]["status"] == "proposed"
    assert checks.reader.calls == [["ex3-69", "ex3-70"]]


def test_a_failing_image_reader_never_breaks_the_intake(tmp_path):
    suggest, checks = suggester(tmp_path, {})
    checks.reader = lambda photo, references: (_ for _ in ()).throw(RuntimeError("hors test"))
    result = suggest(b"photo", {"name": "Fossile crâne", "number": "", "language": "fr"})
    assert result["image_proposal"]["status"] == "none" and "candidates" not in result


@pytest.fixture
def app(tmp_path):
    reader = Reader({"pl1-120": 0.91, "sv5-150": 0.60})
    with TestClient(
        create_app(
            tmp_path / "inventory",
            intake_reader=lambda data: (OBSERVATION.copy(), json.dumps(OBSERVATION)),
            intake_lookup=lambda query: {"candidates": [], "message": "Aucune édition."},
            variant_reader=lambda photo: (_ for _ in ()).throw(RuntimeError("hors test")),
            edition_reader=reader,
            edition_get_json=Catalogue(),
            edition_fetch=lambda url: png(),
            auto_checks=False,
            price_fetch=lambda catalog_id, *_: {"id": catalog_id, "variants": {}},
        )
    ) as client:
        client.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"})
        client.post("/api/albums", json={"name": "Test"})
        yield client, reader


def test_intake_offers_the_image_edition_and_a_person_confirms_it(app):
    client, reader = app
    token = client.post("/api/intake/photo", content=picture((40, 90, 160))).json()["token"]
    analysis = client.post(f"/api/intake/{token}/analyze").json()
    [candidate] = analysis["candidates"]
    assert candidate["id"] == "pl1-120" and candidate["proposed_by"] == "image"
    assert not analysis["exact"] and "Proposée par l’image" in analysis["message"]
    album = client.get("/api/summary").json()["albums"][0]["id"]
    saved = client.post(
        f"/api/intake/{token}/save",
        json={
            "name": candidate["printed_name"],
            "number": candidate["printed_number"],
            "set_name": candidate["set_name"],
            "language": candidate["language"],
            "hp": None,
            "album_id": album,
            "page": 1,
            "position": 1,
            "reason": "Édition proposée par l’image, confirmée",
            "chosen_catalog_id": candidate["id"],
            "human_confirmed": True,
        },
    )
    assert saved.status_code == 201, saved.text
    card = saved.json()
    assert card["catalog_id"] == "pl1-120" and card["identification_status"] == "confirmed"
    # The history says the edition came from the image, not from the catalogue.
    source = client.get(f"/api/copies/{card['id']}").json()["source"]["data"]
    assert source["chosen_proposed_by"] == "image" and source["human_confirmed"]
    assert source["searches"][-1]["image_proposal"]["status"] == "proposed"


def test_an_injected_catalogue_never_reaches_tcgdex_for_the_image(tmp_path):
    app = create_app(
        tmp_path / "inventory",
        intake_lookup=lambda query: {"candidates": [], "message": ""},
        edition_reader=Reader({}),
    )
    assert app.state.intake.suggest is None
