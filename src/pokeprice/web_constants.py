"""Constants and small helpers of the web application, shared by its modules.

A leaf module: it imports nothing from ``webapp``, so every part of the web
application can read these names without an import cycle.
"""

import hashlib
import re
from pathlib import Path

from .brand import SITE_NAME

# A page's text, as written in the HTML: {{t:filters.title}}.
TEXT_KEY = re.compile(r"\{\{t:([\w.]+)\}\}")
# The management app's offline shell (docs/APP.md, « Application installable »):
# the only addresses its service worker ever writes to its cache. Never /api.
APP_SHELL = (
    "/gestion/hors-ligne", "/gestion/manifest.webmanifest",
    "/assets/themes.css", "/assets/style.css", "/assets/photo-zoom.css",
    "/assets/components.js", "/assets/photo-zoom.js", "/assets/media.js",
    "/assets/app.js", "/assets/workflows.js", "/assets/gallery.js", "/assets/pwa.js",
    "/assets/assistant.js",
    "/assets/logo.png", "/assets/icon-192.png", "/assets/icon-512.png",
    "/assets/icon-maskable-512.png", "/assets/apple-touch-icon.png", "/favicon.ico",
)


def interface_version(folder: Path) -> str:
    """A digest of the interface files as deployed: it names the service worker's cache.

    Any deployment that changes a page, a script, a style, a text or an icon
    changes it, so the phone drops the old cache; no date to bump by hand.
    """
    digest = hashlib.sha256(SITE_NAME.encode())
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


# Served with no-cache so a deployment reaches the phone at the next visit.
APP_NO_CACHE = ("/gestion/sw.js", "/gestion/manifest.webmanifest")
# The storefront's languages: dictionary, <html lang> and home address. French is the
# reference; another language lives under its prefix (docs/decisions/0020).
LANGUAGES = {"fr": ("fr", "/"), "en": ("en-GB", "/en/")}
# The query keys of the former management links (/?view=sales, filters), read by
# app.js. Any other parameter on / (fbclid, utm_*, gclid…) leaves the storefront.
MANAGEMENT_QUERY = {
    "view", "display", "q", "album", "stock", "status", "variant", "sort",
    "review", "threshold", "limit", "offset",
}
NOINDEX = '<meta name="robots" content="noindex" />'
PUBLIC_PHOTO = re.compile(r"/api/public/listings/[^/]+/photo")


def indexing_enabled(value):
    """POKEPRICE_INDEXING: on unless explicitly switched off."""
    return str(value).strip().lower() not in {"0", "false", "no", "off", "non"}


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
