import io
import json

import pytest

from pokeprice.pricing import fetch_card, fetch_catalogue_card


def test_finish_metadata_is_available_without_a_cardmarket_price(monkeypatch):
    catalogue = {
        "id": "np-29",
        "variants": {"normal": False, "holo": True, "reverse": False},
        "pricing": {"cardmarket": None},
    }
    calls = []

    def request(req, **_):
        calls.append(req.full_url)
        return io.BytesIO(json.dumps(catalogue).encode())

    monkeypatch.setattr("pokeprice.pricing.urlopen", request)
    assert fetch_catalogue_card("np-29", "fr") == catalogue
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="sans prix Cardmarket"):
        fetch_card("np-29", "fr")
    assert len(calls) == 3  # Price lookup tries French, then English.


def test_price_lookup_still_uses_english_fallback_when_french_has_no_quote(monkeypatch):
    def request(req, **_):
        data = {
            "id": "test-1",
            "pricing": {
                "cardmarket": {"unit": "EUR", "trend": 1.2}
                if "/en/" in req.full_url
                else None,
            },
        }
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr("pokeprice.pricing.urlopen", request)
    assert fetch_card("test-1", "fr")["pricing"]["cardmarket"]["trend"] == 1.2


def test_wrong_edition_metadata_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "pokeprice.pricing.urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b'{"id":"other-29"}'),
    )
    with pytest.raises(RuntimeError):
        fetch_catalogue_card("np-29", "fr")
