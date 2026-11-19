"""The public storefront: its pages, a card's own address, robots.txt and the sitemap."""

import html
import logging
import sqlite3
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ..audience import counted
from ..web_constants import LANGUAGES, MANAGEMENT_QUERY
from .context import AppContext


def visit_counter(ctx: AppContext):
    """The storefront visit counter, shared by the pages and the public listing."""
    audience = ctx.audience
    current_user = ctx.auth.current_user

    def count_visit(request, kind, key):
        """Count a storefront visit; the seller's team is not an audience."""
        headers = request.headers
        if request.method != "GET" or not counted(headers.get("user-agent", ""), headers):
            return
        if request.cookies.get("pokeprice_session"):
            try:
                if current_user(request)["role"] != "client":
                    return
            except HTTPException:
                pass
        try:
            audience.record(
                kind, key, request.client.host if request.client else "local",
                headers["user-agent"], headers.get("referer", ""),
            )
        except sqlite3.Error as error:
            # A lost count never costs a visitor the page, but it shows in the journal.
            logging.getLogger("uvicorn.error").warning("Visite non comptée : %s", error)

    return count_visit


def register_storefront_pages(app, ctx: AppContext, count_visit):
    """Register the storefront, about and conditions pages, where ``create_app`` had them."""
    page = ctx.pages.page
    about_page = ctx.pages.about_page
    conditions_page = ctx.pages.conditions_page

    # The public storefront is the home page; management lives at /gestion.
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if MANAGEMENT_QUERY & set(request.query_params.keys()):
            # Former management links (/?view=sales, filters) keep working; a
            # shared link's fbclid, utm_* or gclid stays on the storefront.
            return RedirectResponse("/gestion?" + request.url.query, status_code=301)
        count_visit(request, "page", "accueil")
        return page("storefront.html", public="")

    @app.get("/en", include_in_schema=False)
    def home_en_slash():
        return RedirectResponse("/en/", status_code=301)

    # The same storefront in English; the visit counts with the French one.
    @app.get("/en/", response_class=HTMLResponse)
    def home_en(request: Request):
        count_visit(request, "page", "accueil")
        return page("storefront.html", "en", public="")

    @app.get("/a-propos", response_class=HTMLResponse)
    def about(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("fr")

    # The English page translates the French one, which prevails.
    @app.get("/en/a-propos", response_class=HTMLResponse)
    def about_en(request: Request):
        count_visit(request, "page", "a-propos")
        return about_page("en")

    @app.get("/conditions", response_class=HTMLResponse)
    def conditions_fr(request: Request):
        count_visit(request, "page", "conditions")
        return conditions_page("fr")

    @app.get("/en/conditions", response_class=HTMLResponse)
    def conditions_en(request: Request):
        count_visit(request, "page", "conditions")
        return conditions_page("en")


def register_card_pages(app, ctx: AppContext, count_visit):
    """Register the card pages, robots.txt and the sitemap, where ``create_app`` had them."""
    public_origin = ctx.public_origin
    indexing = ctx.indexing
    store = ctx.store
    storefront = ctx.storefront
    page = ctx.pages.page
    public_rate = ctx.limits.public_rate

    @app.get("/vitrine")
    def storefront_page():
        return RedirectResponse("/", status_code=301)

    # A card's own address, to share it: the storefront opens on its fiche.
    @app.get("/carte/{listing_id}", response_class=HTMLResponse)
    def card_page(listing_id: str, request: Request, _=Depends(public_rate)):
        return card(listing_id, request, "fr")

    @app.get("/en/carte/{listing_id}", response_class=HTMLResponse)
    def card_page_en(listing_id: str, request: Request, _=Depends(public_rate)):
        return card(listing_id, request, "en")

    def card(listing_id, request, language):
        try:
            listing = storefront.get(listing_id)
        except KeyError:
            # The page still loads and says the card is no longer for sale.
            return HTMLResponse(page("storefront.html", language, "carte/" + quote(listing_id, safe="")), status_code=404)
        count_visit(request, "page", "carte")
        rest = "carte/" + quote(listing_id, safe="")
        return page("storefront.html", language, rest, listing=listing, public=rest)

    def online_listings():
        """The publications on sale, newest first, for the sitemap."""
        with store.connect() as db:
            rows = [r for r in storefront.rows(db) if storefront.cards(db, r["id"])]
        return sorted(rows, key=lambda r: r["published_at"] or "", reverse=True)

    if indexing:
        @app.get("/robots.txt", include_in_schema=False)
        def robots():
            lines = [
                "User-agent: *",
                "Allow: /api/public/listings/*/photo",
                "Disallow: /gestion",
                "Disallow: /api/",
            ]
            if public_origin:
                lines.append(f"Sitemap: {public_origin}/sitemap.xml")
            return Response("\n".join(lines) + "\n", media_type="text/plain")

        @app.get("/sitemap.xml", include_in_schema=False)
        def sitemap():
            if not public_origin:
                # Absolute addresses come from configuration, never from Host.
                raise HTTPException(404, "Plan du site indisponible sans origine publique.")
            entries = [("", None), ("a-propos", None), ("conditions", None)] + [
                ("carte/" + quote(r["id"], safe=""), (r["price_date"] or r["published_at"])[:10])
                for r in online_listings()
            ]
            urls = []
            for rest, modified in entries:
                alternates = "".join(
                    f'<xhtml:link rel="alternate" hreflang="{code}" href="{html.escape(public_origin + home + rest)}"/>'
                    for code, (_, home) in LANGUAGES.items()
                ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{html.escape(public_origin + "/" + rest)}"/>'
                for _, home in LANGUAGES.values():
                    lastmod = f"<lastmod>{html.escape(modified)}</lastmod>" if modified else ""
                    urls.append(f"<url><loc>{html.escape(public_origin + home + rest)}</loc>{lastmod}{alternates}</url>")
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n"
            )
            return Response(body, media_type="application/xml")
