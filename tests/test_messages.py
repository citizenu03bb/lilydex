"""The interface dictionaries: every key used exists, none is orphaned, every language agrees."""

import html
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from pokeprice.inventory import Store
from pokeprice.webapp import ERROR_CODES, TEXT_KEY, create_app

SOURCE = Path(__file__).resolve().parents[1] / "src/pokeprice"
WEB = SOURCE / "web"
PAGES = ("storefront.html", "index.html", "about.html", "about.en.html")
SCRIPTS = ("storefront.js", "components.js")
LITERAL = re.compile(r"""\bt\(\s*["']([\w.]+)["']""")
# A key built at run time, such as t(`language.${code}`): every key under it counts as used.
FAMILY = re.compile(r"\bt\(\s*`([\w.]*)\$\{")


def dictionaries():
    return {p.stem: json.loads(p.read_text()) for p in sorted((WEB / "messages").glob("*.json"))}


def used():
    html_keys = {k for name in PAGES for k in TEXT_KEY.findall((WEB / name).read_text())}
    scripts = "".join((WEB / name).read_text() for name in SCRIPTS)
    return html_keys, set(LITERAL.findall(scripts)), set(FAMILY.findall(scripts))


def test_every_language_has_the_same_keys_and_plurals():
    found = dictionaries()
    assert set(found) == {"fr", "en"}
    reference = found["fr"]
    for language, words in found.items():
        assert set(words) == set(reference), language
        for key, value in words.items():
            assert type(value) is type(reference[key]), (language, key)


def test_every_key_used_exists_and_none_is_orphaned():
    words = dictionaries()["fr"]
    html_keys, script_keys, families = used()
    assert html_keys - set(words) == set()
    assert script_keys - set(words) == set()
    orphans = {
        k for k in words
        if k not in html_keys | script_keys and not any(k.startswith(f) for f in families)
    }
    assert orphans == set()


def test_markup_and_plurals_stay_where_they_belong():
    words = dictionaries()["fr"]
    html_keys, script_keys, _ = used()
    # The script writes text only: markup never reaches it.
    assert {k for k in script_keys if k.endswith("_html")} == set()
    # The server inserts strings; a plural needs a count, known only in the script.
    assert {k for k in html_keys if not isinstance(words[k], str)} == set()
    for key, value in words.items():
        forms = value.values() if isinstance(value, dict) else [value]
        assert all(isinstance(form, str) and form for form in forms), key
        if isinstance(value, dict):
            assert "other" in value, key


def test_the_storefront_html_holds_no_text_of_its_own():
    source = (WEB / "storefront.html").read_text()
    body = source[source.index("<body"):]
    text = re.sub(r"<[^>]+>|\{\{[^}]+\}\}", " ", body)
    # Only symbols are left: close, arrows, separators, the empty basket count.
    assert set(text.split()) <= {"×", "‹", "›", "·", "0"}
    for value in re.findall(r'(?:aria-label|placeholder|alt|title)="([^"]*)"', body):
        assert not re.sub(r"\{\{[^}]+\}\}", "", value).strip(" ,"), value


def test_pages_are_served_with_their_texts_and_dictionary(tmp_path):
    store = Store(tmp_path / "inventory")
    words = dictionaries()["fr"]
    with TestClient(create_app(store.root)) as client:
        for path in ("/", "/a-propos", "/gestion"):
            page = client.get(path).text
            assert "{{" not in page and '<html lang="fr"' in page, path
            block = re.search(r'<script id="messages" type="application/json">(.*?)</script>', page)
            assert json.loads(block.group(1)) == words, path
        page = client.get("/").text
    assert words["hero.title_html"] in page
    assert html.escape(words["basket.data_html"], quote=False) not in page
    assert words["basket.data_html"] in page
    assert f"<h2 id=\"filter-title\">{words['filters.title']}</h2>" in page


def test_the_storefront_speaks_english_under_its_prefix(tmp_path):
    store = Store(tmp_path / "inventory")
    words = dictionaries()["en"]
    with TestClient(create_app(store.root)) as client:
        assert client.get("/en", follow_redirects=False).headers["location"] == "/en/"
        page = client.get("/en/").text
        gone = client.get("/en/carte/inconnue")
        french = client.get("/carte/inconnue").text
    assert '<html lang="en-GB" data-home="/en/">' in page and "{{" not in page
    assert words["meta.title"] in page and words["hero.title_html"] in page
    block = re.search(r'<script id="messages" type="application/json">(.*?)</script>', page)
    assert json.loads(block.group(1)) == words
    # Each page links to the other language at the same address.
    assert 'id="language-switch" href="/"' in page and 'href="/en/a-propos"' in page
    assert gone.status_code == 404 and words["filters.title"] in gone.text
    assert 'id="language-switch" href="/en/carte/inconnue"' in french


def test_the_about_page_has_an_english_translation_and_the_french_prevails(tmp_path, monkeypatch):
    monkeypatch.setenv("POKEPRICE_CONTROLLER_NAME", "Camille")
    store = Store(tmp_path / "inventory")
    with TestClient(create_app(store.root)) as client:
        english = client.get("/en/a-propos").text
        french = client.get("/a-propos").text
    assert '<html lang="en-GB">' in english and "{{" not in english
    assert "the French version prevails" in english and 'href="/a-propos" hreflang="fr"' in english
    assert "Data controller: Camille, as a private individual" in english
    assert "The seller tells you in their reply how to pay." in english
    assert "Responsable du traitement" not in english and "comment payer" not in english
    assert 'href="/en/a-propos" hreflang="en"' in french
    # The translation keeps every section, so a link to #donnees lands in both.
    for anchor in ('id="donnees"', 'id="contact"'):
        assert anchor in english and anchor in french
    sections = lambda text: len(re.findall(r"<h[23]>", text))
    assert sections(english) == sections(french)


def test_every_error_code_has_its_text_and_the_french_is_the_detail():
    found = dictionaries()
    sources = "".join(
        (SOURCE / name).read_text() for name in ("webapp.py", "reservations.py", "listings.py")
    )
    assert len(set(ERROR_CODES.values())) == len(ERROR_CODES)
    for detail, code in ERROR_CODES.items():
        # The table and the raise share the text: a reworded message keeps its code.
        assert sources.count(detail) >= 2, detail
        assert found["fr"][f"error.{code}"] == detail, code
        assert found["en"][f"error.{code}"], code


def test_errors_a_visitor_meets_carry_their_code(tmp_path):
    store = Store(tmp_path / "inventory")
    guest = {"email": "ondine@example.org", "display_name": "Ondine", "listing_ids": ["x"], "consent": True}
    with TestClient(create_app(store.root)) as client:
        login = client.post("/api/login", json={"username": "personne", "password": "faux-mot-de-passe"})
        foreign = client.post("/api/logout", headers={"origin": "https://ailleurs.example"})
        closed = client.post("/api/public/requests", json=guest)
        me = client.get("/api/me")
    assert login.status_code == 401 and login.json()["code"] == "wrong_credentials"
    assert foreign.status_code == 403 and foreign.json()["code"] == "origin_forbidden"
    assert closed.status_code == 409 and closed.json()["code"] == "requests_closed"
    assert me.json() == {
        "detail": "Connectez-vous pour consulter la collection.", "code": "login_required"
    }
