import os

# The real private Drive folder lives in local configuration, never in tests.
os.environ["POKEPRICE_DRIVE_FOLDER"] = "test-drive-folder"
import urllib.parse

import dotenv
import pytest

from pokeprice import passwords
from pokeprice.tcgdex import TCGdexClient


@pytest.fixture(autouse=True)
def cheap_scrypt(request, monkeypatch):
    # Hundreds of test logins would otherwise pay the production hashing cost.
    if not request.node.get_closest_marker("real_scrypt"):
        monkeypatch.setattr(passwords, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})


# Read from ~/.env by the application: a test never sees a real key or channel.
PRIVATE_VARIABLES = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "POKEPRICE_CONTACT_EMAIL",
    "POKEPRICE_NTFY_URL",
    "POKEPRICE_NTFY_TOKEN",
    "POKEPRICE_SMTP_HOST",
    "POKEPRICE_SMTP_PORT",
    "POKEPRICE_SMTP_SECURITY",
    "POKEPRICE_SMTP_USER",
    "POKEPRICE_SMTP_PASSWORD",
    "POKEPRICE_SMTP_FROM",
    "POKEPRICE_NOTIFY_EMAIL",
    "POKEPRICE_VAPID_PUBLIC_KEY",
    "POKEPRICE_VAPID_PRIVATE_KEY",
    "POKEPRICE_VAPID_SUBJECT",
)


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch):
    # Backup keys and other per-user configuration never come from the real home.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # ~/.env is loaded into os.environ on demand, and load_dotenv() without a
    # path walks up to the developer's home: a storefront request in a test
    # would alert the real seller. No .env is read during the tests.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for name in PRIVATE_VARIABLES:
        monkeypatch.delenv(name, raising=False)


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


def pytest_addoption(parser):
    # Stored expectations (tests/snapshots/) are rewritten only on purpose:
    # a change that alters a route, a header or the schema updates them in the same diff.
    parser.addoption(
        "--update-snapshots", action="store_true", default=False,
        help="Rewrite the stored expectations of tests/snapshots/ instead of comparing.",
    )
