"""The application's outer protections: allowed hosts, same-origin writes, response headers.

``TrustedHostMiddleware`` is added first and ``protect`` last, so ``protect`` is
the outermost layer: even a rejected host gets the security headers.
"""

from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .errors import error_response
from .web_constants import APP_NO_CACHE, PUBLIC_PHOTO


def install_security(app: FastAPI, *, allowed_hosts, secure_cookie, indexing) -> None:
    """Add the host check, then the ``protect`` middleware, to the application."""
    # The public name, plus loopback: commands run on the server itself (the agent
    # client's default URL) reach the app without going out through Caddy.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(dict.fromkeys([*allowed_hosts, "127.0.0.1", "localhost"])),
    )

    @app.middleware("http")
    async def protect(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            base = urlsplit(str(request.base_url))
            if origin and origin != f"{base.scheme}://{base.netloc}":
                return error_response("Origine interdite.", 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return error_response("Origine interdite.", 403)
        if (
            request.method == "GET"
            and request.url.path == "/api/copies"
            and "text/html" in request.headers.get("accept", "")
            and request.headers.get("sec-fetch-dest", "") in ("", "document")
        ):
            response = RedirectResponse("/gestion?" + request.url.query, status_code=303)
        else:
            response = await call_next(request)
        if secure_cookie:
            # Behind HTTPS only: browsers then refuse plain HTTP for a year.
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith(("/gestion", "/api/")) and not (
            indexing and PUBLIC_PHOTO.fullmatch(request.url.path)
        ):
            # The seller's login and data never belong in a search engine; with
            # indexing on, the public photos may illustrate the cards.
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        cache_policy = "no-store"
        if response.status_code in (200, 304):
            if request.url.path == "/favicon.ico":
                cache_policy = "public, max-age=86400"
            elif request.url.path.startswith("/assets/"):
                cache_policy = "public, no-cache"
            elif request.url.path in APP_NO_CACHE:
                cache_policy = "no-cache"
        response.headers["Cache-Control"] = cache_policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://assets.tcgdex.net; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response
