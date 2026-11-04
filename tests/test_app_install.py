"""The management app is installable: manifest, service worker, offline page (docs/APP.md)."""

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pokeprice.brand import SITE_NAME
from pokeprice.webapp import APP_SHELL, create_app, interface_version

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/pokeprice/web"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "inventory")) as http:
        yield http


def test_manifest_makes_the_management_app_installable(client):
    response = client.get("/gestion/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.headers["cache-control"] == "no-cache"
    manifest = json.loads(response.text)
    assert manifest["name"] == SITE_NAME == "Les cartes de Lily"
    assert 0 < len(manifest["short_name"]) <= 12
    assert manifest["start_url"] == manifest["scope"] == manifest["id"] == "/gestion"
    assert manifest["display"] == "standalone"
    themes = (WEB / "themes.css").read_text()
    for key in ("theme_color", "background_color"):
        assert manifest[key].lower() in themes.lower(), key
    sizes = {}
    for icon in manifest["icons"]:
        image = client.get(icon["src"])
        assert image.status_code == 200, icon["src"]
        width, height = Image.open(io.BytesIO(image.content)).size
        assert icon["sizes"] == f"{width}x{height}" and width == height
        sizes.setdefault(icon["purpose"], set()).add(width)
    assert {192, 512} <= sizes["any"]
    assert 512 in sizes["maskable"]


def test_only_the_management_page_links_the_manifest(client):
    page = client.get("/gestion").text
    assert '<link rel="manifest" href="/gestion/manifest.webmanifest" />' in page
    assert '<meta name="theme-color"' in page
    assert '<script src="/assets/pwa.js" defer></script>' in page
    for public in ("/", "/en/", "/a-propos", "/conditions"):
        text = client.get(public).text
        assert 'rel="manifest"' not in text and "pwa.js" not in text, public


def test_service_worker_is_revalidated_and_reaches_the_management_page(client):
    response = client.get("/gestion/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["service-worker-allowed"] == "/gestion"
    # The CSP of webapp.py stays: the worker only talks to its own origin.
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "{{" not in response.text
    version = re.search(r'const VERSION = "([0-9a-f]{16})";', response.text)[1]
    assert version == interface_version(WEB)
    precache = json.loads(re.search(r"const PRECACHE = (\[.*?\]);", response.text)[1])
    assert precache == list(APP_SHELL)
    for path in precache:
        assert not path.startswith("/api"), path
        assert client.get(path).status_code == 200, path


def test_shell_never_holds_collection_data():
    assert all(not path.startswith(("/api", "/vitrine", "/carte")) for path in APP_SHELL)
    assert all(path.startswith(("/gestion/", "/assets/", "/favicon")) for path in APP_SHELL)


def test_cache_name_follows_the_interface_content(tmp_path):
    folder = tmp_path / "web"
    shutil.copytree(WEB, folder)
    before = interface_version(folder)
    assert before == interface_version(folder)
    (folder / "app.js").write_text((folder / "app.js").read_text() + "\n// next deployment\n")
    assert interface_version(folder) != before
    (folder / "app.js").unlink()
    shutil.copy(WEB / "app.js", folder / "app.js")
    assert interface_version(folder) == before
    (folder / "messages/en.json").write_text("{}")
    assert interface_version(folder) != before


def test_offline_page_needs_no_login_and_points_back(client):
    response = client.get("/gestion/hors-ligne")
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert 'href="/gestion"' in response.text
    assert "Hors ligne" in response.text
    assert "<script" not in response.text


def test_service_worker_caches_the_shell_and_never_the_api(client, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the service worker")
    served = tmp_path / "sw.js"
    served.write_text(client.get("/gestion/sw.js").text)
    result = subprocess.run(
        [node, str(ROOT / "tests/web_service_worker_runtime.cjs"), str(served)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
