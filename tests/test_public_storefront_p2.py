"""Public P2 contracts, with a disposable synthetic collection only."""
import html
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_public_storefront import shop  # noqa: F401

from pokeprice.webapp import create_app


class Head(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.meta = {}
        self.title = ""
        self.in_title = False
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("name") or attrs.get("property")] = attrs.get("content")
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def replace_photo(store, copy_id, size=(1064, 1573), color="#ebeedc"):
    payload = BytesIO()
    Image.new("RGB", size, color).save(payload, "JPEG", quality=94)
    name = store.save_photo(payload.getvalue())
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET photo=? WHERE id=?", (name, copy_id))
    return name


def test_condition_is_public_confirmation_and_matches_one_lot_member(shop):  # noqa: F811
    _, visitor, store, _, single, lot = shop
    with store.connect(write=True) as db:
        for item, language, grade, confirmed in [
            (single["items"][0], "fr", "NM/EX", 1),
            (lot["items"][0], "ja", "NM", 0),
            (lot["items"][1], "fr", "MT", 1),
        ]:
            db.execute("UPDATE copies SET language=?,condition=?,condition_confirmed=?,finish='reverse' WHERE id=?",
                       (language, grade, confirmed, item["id"]))
    search = lambda **query: visitor.get("/api/public/listings", params=query).json()
    assert search(condition="NM")["total"] == 0  # never expose the private estimate
    assert [p["id"] for p in search(condition="NM/EX")["items"]] == [single["id"]]
    assert [p["id"] for p in search(condition="MT")["items"]] == [lot["id"]]
    assert search(condition="MT", language="ja", finish="reverse")["total"] == 0
    unknown = search(condition="unknown", language="ja", finish="reverse")
    assert unknown["total"] == 1 and len(unknown["items"][0]["items"]) == 2
    assert unknown["items"][0]["price_cents"] == 200
    assert unknown["items"][0]["items"][0]["condition"] is None
    assert search(q="absent", offset=50)["conditions"] == ["MT", "NM/EX", "unknown"]
    assert visitor.get("/api/public/listings", params={"condition": "mint"}).status_code == 422
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET condition='',condition_confirmed=1 WHERE id=?", (single["items"][0]["id"],))
    assert search(condition="unknown")["total"] == 2
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET stock_state='reserved' WHERE id=?", (lot["items"][0]["id"],))
    assert search()["conditions"] == ["unknown"]


def test_media_metadata_and_generated_bytes_match_without_private_paths(shop):  # noqa: F811
    _, visitor, store, _, single, _ = shop
    name = replace_photo(store, single["items"][0]["id"])
    detail = visitor.get(f"/api/public/listings/{single['id']}").json()
    media = detail["items"][0]["media"]["front"]
    assert (media["width"], media["height"]) == (1064, 1573)
    assert name not in str(detail) and single["items"][0]["id"] not in str(detail)
    assert "back" not in detail["items"][0]["media"]
    assert {v["size"] for v in media["variants"]} == {"thumb", "grid2", "grid3", "view", "view2"}
    for variant in media["variants"]:
        assert set(variant) == {"size", "format", "width", "height", "url"}
        response = visitor.get(variant["url"])
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"] == "image/" + variant["format"]
        with Image.open(BytesIO(response.content)) as picture:
            assert picture.size == (variant["width"], variant["height"])
            assert picture.width <= 1064 and picture.height <= 1573
    for query in ({"size": "gigantic"}, {"size": "full", "format": "webp"}, {"size": "view", "format": "png"}):
        assert visitor.get(f"/api/public/listings/{single['id']}/photo", params=query).status_code == 422


def test_derivative_cache_obeys_replacement_withdrawal_and_reservation(shop):  # noqa: F811
    admin, visitor, store, _, single, lot = shop
    copy_id = single["items"][0]["id"]
    replace_photo(store, copy_id)
    path = f"/api/public/listings/{single['id']}/photo?size=view"
    first = visitor.get(path)
    assert first.status_code == 200
    replace_photo(store, copy_id, size=(600, 900), color="#1c3244")
    replaced = visitor.get(path, headers={"if-none-match": first.headers.get("etag", "")})
    assert replaced.status_code == 200 and replaced.content != first.content
    with Image.open(BytesIO(replaced.content)) as image:
        assert image.size == (600, 900)  # no upscaling
    assert admin.delete(f"/api/copies/{copy_id}/listing").status_code == 200
    assert visitor.get(path, headers={"if-none-match": replaced.headers.get("etag", "")}).status_code == 404
    lot_path = f"/api/public/listings/{lot['id']}/photo?size=grid2"
    assert visitor.get(lot_path).status_code == 200
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET stock_state='reserved' WHERE id=?", (lot["items"][0]["id"],))
    assert visitor.get(lot_path).status_code == 404


def test_broken_photo_does_not_hide_catalogue_or_serve_an_existing_derivative(shop):  # noqa: F811
    _, visitor, store, _, single, _ = shop
    name = replace_photo(store, single["items"][0]["id"])
    path = f"/api/public/listings/{single['id']}/photo"
    assert visitor.get(path, params={"size": "view"}).status_code == 200
    (store.photos / name).unlink()
    for size in ("thumb", "view", "full"):
        assert visitor.get(path, params={"size": size}).status_code == 404
    detail = visitor.get(f"/api/public/listings/{single['id']}").json()
    assert detail["items"][0]["media"] == {}
    assert visitor.get("/api/public/listings").json()["total"] == 2


def test_server_previews_are_localized_escaped_and_use_configured_origin(shop):  # noqa: F811
    _, _, store, _, single, lot = shop
    title = 'Lot public <script> & "cartes"'
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET title=? WHERE id=?", (title, lot["id"]))
    with TestClient(create_app(store.root, public_origin="https://shop.example")) as visitor:
        for language, prefix in (("fr", ""), ("en", "/en")):
            response = visitor.get(f"{prefix}/carte/{lot['id']}", headers={"x-forwarded-host": "attacker.example"})
            assert response.status_code == 200
            head = Head(response.text)
            assert title in head.title and title in head.meta["og:title"]
            assert html.escape(title) in response.text and title not in response.text
            assert head.meta["og:url"] == f"https://shop.example{prefix}/carte/{lot['id']}"
            assert head.meta["og:type"] == "website" and head.meta["robots"] == "noindex"
            assert "2" in head.meta["og:description"]
            assert ("2,00" if language == "fr" else "2.00") in head.meta["og:description"]
            assert "attacker.example" not in response.text
            picture = urlsplit(head.meta["og:image"])
            assert picture.scheme == "https" and picture.netloc == "shop.example"
            assert picture.path.startswith(f"/api/public/listings/{lot['id']}/photo")
            assert head.meta["og:image:alt"] and head.meta["twitter:image"] == head.meta["og:image"]
            assert "Note privée" not in response.text and "Album A" not in response.text
            assert response.headers["cache-control"] == "no-store"
        with TestClient(create_app(store.root, public_origin="")) as no_origin:
            head = Head(no_origin.get(f"/carte/{single['id']}").text)
            assert "og:url" not in head.meta and "og:image" not in head.meta
            assert single["items"][0]["name"] in head.title


def test_missing_previews_are_generic_and_do_not_retain_withdrawn_information(shop):  # noqa: F811
    _, _, store, _, single, _ = shop
    with TestClient(create_app(store.root, public_origin="https://shop.example")) as visitor:
        path = f"/carte/{single['id']}"
        assert "og:image" in Head(visitor.get(path).text).meta
        with store.connect(write=True) as db:
            db.execute("UPDATE copies SET photo=NULL WHERE id=?", (single["items"][0]["id"],))
        assert "og:image" not in Head(visitor.get(path).text).meta
        with store.connect(write=True) as db:
            db.execute("UPDATE listings SET state='offline' WHERE id=?", (single["id"],))
        response = visitor.get(path)
        assert response.status_code == 404
        head = Head(response.text)
        assert "og:image" not in head.meta and single["items"][0]["name"] not in head.title
        assert head.meta["og:url"] == "https://shop.example/"
        assert head.meta["robots"] == "noindex"


@pytest.mark.parametrize("origin", ["http://shop.example", "https://user:secret@shop.example", "https://shop.example/a", "https://shop.example/?x=1", "https://shop.example/#x", "https://shop.example/?", "https://shop.example/#", "https://shop.example\\a", "javascript:alert(1)", "https://shop.example:bad"])
def test_public_origin_rejects_unsafe_or_non_origin_values(tmp_path, origin):
    with pytest.raises(ValueError):
        create_app(tmp_path / "unused", public_origin=origin)
    assert not (tmp_path / "unused").exists()


def test_public_origin_can_be_configured_without_using_request_headers(shop, monkeypatch):  # noqa: F811
    _, _, store, _, single, _ = shop
    monkeypatch.setenv("POKEPRICE_PUBLIC_ORIGIN", "https://configured.example/")
    with TestClient(create_app(store.root)) as visitor:
        head = Head(visitor.get(f"/carte/{single['id']}", headers={"forwarded": "host=evil.example;proto=http"}).text)
        assert head.meta["og:url"] == f"https://configured.example/carte/{single['id']}"
