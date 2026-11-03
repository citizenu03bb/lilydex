"""Shared links and search-engine indexing, with a disposable synthetic collection only."""
import json
import re
from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from test_public_storefront import shop  # noqa: F401
from test_public_storefront_p2 import replace_photo

from pokeprice.webapp import create_app, indexing_enabled

ORIGIN = "https://shop.example"


class Head(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.meta, self.links, self.data, self._ld = {}, [], [], None
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("name") or attrs.get("property")] = attrs.get("content")
        elif tag == "link" and attrs.get("rel") in ("canonical", "alternate"):
            self.links.append(attrs)
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self._ld = ""

    def handle_data(self, data):
        if self._ld is not None:
            self._ld += data

    def handle_endtag(self, tag):
        if tag == "script" and self._ld is not None:
            self.data.append(json.loads(self._ld))
            self._ld = None

    def canonical(self):
        return [l["href"] for l in self.links if l["rel"] == "canonical"]

    def hreflang(self):
        return {l["hreflang"]: l["href"] for l in self.links if l["rel"] == "alternate"}


@pytest.fixture
def indexed(shop):  # noqa: F811
    _, _, store, _, single, lot = shop
    with TestClient(create_app(store.root, public_origin=ORIGIN, indexing=True)) as client:
        yield client, store, single, lot


@pytest.mark.parametrize("query", ["fbclid=IwAR0abc", "utm_source=facebook&utm_medium=social",
                                   "gclid=xyz", "igshid=abc", "inconnu=1"])
def test_shared_links_with_tracking_parameters_serve_the_storefront(shop, query):  # noqa: F811
    _, visitor, *_ = shop
    response = visitor.get(f"/?{query}", follow_redirects=False)
    assert response.status_code == 200 and "/assets/storefront.js" in response.text


@pytest.mark.parametrize("query", ["view=sales", "q=Zarbi", "album=A", "stock=deleted", "status=review",
                                   "variant=x", "sort=price", "review=1", "threshold=5", "limit=80",
                                   "offset=40", "display=editions", "fbclid=abc&view=audience"])
def test_former_management_links_still_redirect(shop, query):  # noqa: F811
    _, visitor, *_ = shop
    response = visitor.get(f"/?{query}", follow_redirects=False)
    assert response.status_code == 301 and response.headers["location"] == f"/gestion?{query}"


def test_a_shared_link_counts_as_a_visit(shop, monkeypatch):  # noqa: F811
    _, _, store, *_ = shop
    from pokeprice import audience
    seen = []
    monkeypatch.setattr(audience.Audience, "record", lambda self, kind, key, *rest: seen.append((kind, key)))
    with TestClient(create_app(store.root)) as visitor:
        browser = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0", "accept": "text/html",
                   "accept-language": "fr", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"}
        assert visitor.get("/?fbclid=IwAR0abc", headers=browser).status_code == 200
        assert visitor.get("/", headers=browser).status_code == 200
    assert seen.count(("page", "accueil")) == 2


def test_indexing_is_off_by_default(shop, monkeypatch):  # noqa: F811
    _, _, store, _, single, _ = shop
    monkeypatch.delenv("POKEPRICE_INDEXING", raising=False)
    with TestClient(create_app(store.root, public_origin=ORIGIN)) as visitor:
        for path in ("/", "/en/", "/a-propos", "/en/a-propos", f"/carte/{single['id']}"):
            assert Head(visitor.get(path).text).meta["robots"] == "noindex", path
        assert visitor.get("/robots.txt").status_code == 404
        assert visitor.get("/sitemap.xml").status_code == 404
        photo = visitor.get(f"/api/public/listings/{single['id']}/photo")
        assert photo.status_code == 200 and photo.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("value, expected", [("", False), ("0", False), ("off", False), ("non", False),
                                             ("1", True), ("on", True), ("true", True), (" Oui ", True)])
def test_the_indexing_setting_is_read_from_the_environment(value, expected, tmp_path, monkeypatch):
    assert indexing_enabled(value) is expected
    monkeypatch.setenv("POKEPRICE_INDEXING", value)
    with TestClient(create_app(tmp_path / "inventory")) as client:
        assert (client.get("/robots.txt").status_code == 200) is expected
        assert ("robots" in Head(client.get("/").text).meta) is not expected


def test_indexing_on_opens_public_pages_only(indexed):
    client, store, single, lot = indexed
    for path in ("/", "/en/", "/a-propos", "/en/a-propos", f"/carte/{single['id']}", f"/en/carte/{lot['id']}"):
        response = client.get(path)
        assert response.status_code == 200 and "robots" not in Head(response.text).meta, path
        assert "x-robots-tag" not in response.headers
    gone = client.get("/carte/absente")
    assert gone.status_code == 404 and Head(gone.text).meta["robots"] == "noindex"
    assert client.get("/gestion").headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/api/public/listings").headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get(f"/api/public/listings/{single['id']}").headers["x-robots-tag"] == "noindex, nofollow"
    photo = client.get(f"/api/public/listings/{single['id']}/photo")
    assert photo.status_code == 200 and "x-robots-tag" not in photo.headers


def test_robots_txt_keeps_management_out_and_points_to_the_sitemap(indexed):
    client, *_ = indexed
    response = client.get("/robots.txt")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert "Disallow: /gestion" in lines and "Disallow: /api/" in lines
    assert "Allow: /api/public/listings/*/photo" in lines
    assert f"Sitemap: {ORIGIN}/sitemap.xml" in lines


def test_the_sitemap_lists_home_about_and_listings_on_sale_in_both_languages(indexed):
    client, store, single, lot = indexed
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET state='offline' WHERE id=?", (lot["id"],))
    response = client.get("/sitemap.xml", headers={"x-forwarded-host": "attacker.example"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/xml")
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    root = ElementTree.fromstring(response.content)
    urls = {u.find("s:loc", ns).text: u for u in root.findall("s:url", ns)}
    card = f"carte/{single['id']}"
    assert set(urls) == {f"{ORIGIN}/", f"{ORIGIN}/en/", f"{ORIGIN}/a-propos", f"{ORIGIN}/en/a-propos",
                         f"{ORIGIN}/{card}", f"{ORIGIN}/en/{card}"}
    alternates = {l.get("hreflang"): l.get("href") for l in urls[f"{ORIGIN}/en/{card}"].findall("x:link", ns)}
    assert alternates == {"fr": f"{ORIGIN}/{card}", "en": f"{ORIGIN}/en/{card}", "x-default": f"{ORIGIN}/{card}"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", urls[f"{ORIGIN}/{card}"].find("s:lastmod", ns).text)
    assert lot["id"] not in response.text and "attacker.example" not in response.text


def test_without_public_origin_there_is_no_sitemap(shop):  # noqa: F811
    _, _, store, *_ = shop
    with TestClient(create_app(store.root, public_origin="", indexing=True)) as client:
        assert client.get("/sitemap.xml").status_code == 404
        assert "Sitemap:" not in client.get("/robots.txt").text
        assert Head(client.get("/").text).canonical() == []


def test_public_head_has_canonical_and_hreflang_without_tracking_parameters(indexed):
    client, store, single, _ = indexed
    head = Head(client.get("/?fbclid=abc&utm_source=x").text)
    assert head.canonical() == [f"{ORIGIN}/"]
    assert head.hreflang() == {"fr": f"{ORIGIN}/", "en": f"{ORIGIN}/en/", "x-default": f"{ORIGIN}/"}
    about = Head(client.get("/en/a-propos").text)
    assert about.canonical() == [f"{ORIGIN}/en/a-propos"]
    assert about.hreflang()["fr"] == f"{ORIGIN}/a-propos"
    card = Head(client.get(f"/en/carte/{single['id']}").text)
    assert card.canonical() == [f"{ORIGIN}/en/carte/{single['id']}"]
    assert card.hreflang()["x-default"] == f"{ORIGIN}/carte/{single['id']}"
    assert Head(client.get("/carte/absente").text).canonical() == []


def test_a_fiche_is_a_product_with_an_offer(indexed):
    client, store, single, lot = indexed
    replace_photo(store, single["items"][0]["id"])
    head = Head(client.get(f"/carte/{single['id']}").text)
    assert head.meta["og:type"] == "product"
    assert head.meta["twitter:card"] == "summary_large_image"
    (product,) = head.data
    assert product["@context"] == "https://schema.org" and product["@type"] == "Product"
    assert product["name"] == single["items"][0]["name"]
    assert product["url"] == f"{ORIGIN}/carte/{single['id']}"
    assert product["image"].startswith(f"{ORIGIN}/api/public/listings/{single['id']}/photo")
    offer = product["offers"]
    assert offer == {"@type": "Offer", "price": "1.20", "priceCurrency": "EUR",
                     "availability": "https://schema.org/InStock",
                     "itemCondition": "https://schema.org/UsedCondition", "url": product["url"]}
    home = Head(client.get("/").text)
    assert home.data == [] and home.meta["og:type"] == "website" and home.meta["twitter:card"] == "summary"


def test_json_ld_cannot_close_its_block(indexed):
    client, store, _, lot = indexed
    title = 'Lot </script><script>alert(1)</script>'
    with store.connect(write=True) as db:
        db.execute("UPDATE listings SET title=? WHERE id=?", (title, lot["id"]))
    response = client.get(f"/carte/{lot['id']}")
    assert "</script><script>alert" not in response.text
    (product,) = Head(response.text).data
    assert product["name"] == title and product["offers"]["price"] == "2.00"
    # The CSP still forbids inline scripts: the JSON-LD block is data, not code.
    assert "script-src 'self';" in response.headers["content-security-policy"]
