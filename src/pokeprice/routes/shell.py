"""The installable management shell (docs/APP.md), its static assets and the favicon."""

import hashlib
import json
from typing import Literal

from fastapi import Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from ..brand import SITE_NAME
from ..web_constants import APP_SHELL, interface_version
from .context import AppContext


def register_shell(app, ctx: AppContext):
    """Register the management shell, its manifest, worker and offline page, the assets and the favicon, where ``create_app`` had them."""
    static = ctx.pages.static
    dictionaries = ctx.pages.dictionaries
    page = ctx.pages.page

    @app.get("/gestion", response_class=HTMLResponse)
    def index():
        return page("index.html")

    # The management app is installable (docs/APP.md): manifest, service
    # worker and offline page, all public and free of any collection data.
    @app.get("/gestion/manifest.webmanifest", include_in_schema=False)
    def app_manifest():
        words = dictionaries["fr"]
        icons = [
            {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
        manifest = {
            "id": "/gestion",
            "name": SITE_NAME,
            "short_name": "Cartes Lily",
            "description": words["install.description"],
            "lang": "fr",
            "dir": "ltr",
            "start_url": "/gestion",
            "scope": "/gestion",
            "display": "standalone",
            # Herbier theme (themes.css): --surface-1 for the bar, --surface-0 behind.
            "theme_color": "#ffffff",
            "background_color": "#f6f5f0",
            "icons": icons,
        }
        return Response(
            json.dumps(manifest, ensure_ascii=False),
            media_type="application/manifest+json",
        )

    @app.get("/gestion/sw.js", include_in_schema=False)
    def service_worker():
        script = (
            static.joinpath("sw.js").read_text()
            .replace("{{version}}", interface_version(static))
            .replace("{{precache}}", json.dumps(list(APP_SHELL)))
        )
        # Its own folder would cap its reach at /gestion/; the page is /gestion.
        return Response(
            script,
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/gestion"},
        )

    @app.get("/gestion/hors-ligne", response_class=HTMLResponse, include_in_schema=False)
    def offline_page():
        return page("offline.html")

    @app.get("/assets/{name}")
    def assets(
        request: Request,
        name: Literal[
            "app.js",
            "app-requests.js",
            "app-moves.js",
            "app-assistant.js",
            "app-boot.js",
            "media.js", "workflows.js", "gallery.js", "style.css",
            "storefront.js", "storefront.css", "themes.css", "components.js",
            "photo-zoom.js", "photo-zoom.css", "pwa.js", "assistant.js",
            "logo.png", "apple-touch-icon.png", "mascotte.png",
            "icon-192.png", "icon-512.png", "icon-maskable-512.png",
        ],
    ):
        path = static / name
        etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return FileResponse(path, headers={"ETag": etag})

    # Browsers ask for /favicon.ico on their own, before reading any page.
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon(request: Request):
        path = static / "favicon.ico"
        etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return FileResponse(path, media_type="image/x-icon", headers={"ETag": etag})
