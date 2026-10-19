import os

# The real private Drive folder lives in local configuration, never in tests.
os.environ["POKEPRICE_DRIVE_FOLDER"] = "test-drive-folder"
import urllib.parse

import pytest

from pokeprice import webapp
from pokeprice.tcgdex import TCGdexClient


@pytest.fixture(autouse=True)
def cheap_scrypt(request, monkeypatch):
    # Hundreds of test logins would otherwise pay the production hashing cost.
    if not request.node.get_closest_marker("real_scrypt"):
        monkeypatch.setattr(webapp, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch):
    # Backup keys and other per-user configuration never come from the real home.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("POKEPRICE_CONTACT_EMAIL", raising=False)


@pytest.fixture
def client_factory():
    def make(details, names=None):
        client = TCGdexClient.__new__(TCGdexClient)
        client.language = "fr"
        client.base_url = "https://api.tcgdex.net/v2/fr"
        client.name_map = names or {
            d["name"].lower(): d["name"]
            for d in details
            if d.get("language", "fr") == "fr"
        }
        client.last_match_reason = ""
        queries = []

        def get(url):
            queries.append(url)
            parts = urllib.parse.urlsplit(url)
            language = parts.path.split("/")[2]
            if parts.query:
                name = urllib.parse.parse_qs(parts.query)["name"][0]
                return [
                    {"id": d["id"], "name": d["name"], "localId": d["localId"]}
                    for d in details
                    if d.get("language", "fr") == language and d["name"] == name
                ]
            cid = parts.path.rsplit("/", 1)[-1]
            return next(
                (
                    d
                    for d in details
                    if d["id"] == cid and d.get("language", "fr") == language
                ),
                None,
            )

        client._get_json = get
        client.queries = queries
        return client

    return make


def card(cid, name, number, count, hp=80, **extras):
    return {
        "id": cid,
        "name": name,
        "localId": str(number),
        "hp": hp,
        "set": {
            "id": cid.rsplit("-", 1)[0],
            "name": "Test set",
            "cardCount": {"official": count},
        },
        "rarity": "Rare",
        "image": "https://assets.example.test/card",
        "pricing": {
            "cardmarket": {
                "trend": 10.0,
                "trend-holo": 12.0,
                "updated": "2026-10-04T00:00:00Z",
            }
        },
        **extras,
    }
