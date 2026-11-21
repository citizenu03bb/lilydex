"""Private FastAPI inventory API and a dependency-free French web interface."""

from fastapi import FastAPI

from .web_constants import (
    APP_SHELL,
    LANGUAGES,
    TEXT_KEY,
    indexing_enabled,
    interface_version,
)
from .schemas import UserCreate
from .errors import ERROR_CODES, install_handlers
from .passwords import add_user, password_hash, password_valid
from .routes.auth import register_auth, register_logout
from .routes.backup import register_backup
from .routes.binder_imports import register_binder_imports
from .routes.capture import register_capture
from .routes.checks import register_checks, register_conditions
from .routes.client_requests import register_client_requests
from .routes.closeups import register_closeups
from .routes.accounts import register_accounts
from .routes.context import build_services
from .routes.copies import register_copies, register_copy_images
from .routes.exports import register_exports
from .routes.floor_requests import register_floor_requests
from .routes.hooks import build_hooks
from .routes.intake import register_intake
from .routes.listings import register_listings
from .routes.move_batches import register_move_batches
from .routes.photo_batches import register_photo_batches
from .routes.public import (
    register_public_listing,
    register_public_requests,
    register_public_search,
    register_public_signup,
)
from .routes.push import register_push
from .routes.sales import register_sales
from .routes.settings import register_settings
from .routes.shell import register_shell
from .routes.statistics import register_statistics
from .routes.storefront import register_card_pages, register_storefront_pages, visit_counter
from .routes.todo import register_todo
from .routes.users import register_users
from .security import install_security

# Names that tests and other modules still import from here.
__all__ = [
    "APP_SHELL", "ERROR_CODES", "LANGUAGES", "TEXT_KEY", "UserCreate", "add_user",
    "build_services", "create_app", "indexing_enabled", "interface_version",
    "password_hash", "password_valid",
]


def create_app(
    directory="data/inventory",
    *,
    secure_cookie=False,
    allowed_hosts=None,
    public_origin=None,
    intake_reader=None,
    intake_lookup=None,
    condition_reader=None,
    variant_reader=None,
    edition_reader=None,
    edition_get_json=None,
    edition_fetch=None,
    auto_checks=False,
    price_fetch=None,
    variant_fetch=None,
    market_fetch=None,
    agent_enabled=True,
    indexing=None,
    assistant_model=None,
):
    ctx = build_services(
        directory,
        secure_cookie=secure_cookie,
        allowed_hosts=allowed_hosts,
        public_origin=public_origin,
        intake_reader=intake_reader,
        intake_lookup=intake_lookup,
        condition_reader=condition_reader,
        variant_reader=variant_reader,
        edition_reader=edition_reader,
        edition_get_json=edition_get_json,
        edition_fetch=edition_fetch,
        price_fetch=price_fetch,
        variant_fetch=variant_fetch,
        market_fetch=market_fetch,
        indexing=indexing,
        assistant_model=assistant_model,
    )
    indexing = ctx.indexing
    allowed_hosts = ctx.allowed_hosts
    store = ctx.store
    intake = ctx.intake
    conditions = ctx.conditions
    variant_checks = ctx.variant_checks
    edition_checks = ctx.edition_checks
    market = ctx.market
    pricing = ctx.pricing
    variant_catalogue = ctx.variant_catalogue
    notifier = ctx.notifier
    moves = ctx.moves
    review = ctx.review
    todo = ctx.todo
    assistant = ctx.assistant
    failures = ctx.limits.failures
    public_hits = ctx.limits.public_hits
    signups = ctx.limits.signups
    guests = ctx.limits.guests
    app = FastAPI(
        title="Poképrice — collection privée",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.intake = intake
    app.state.conditions = conditions
    app.state.variant_checks = variant_checks
    app.state.edition_checks = edition_checks
    app.state.market = market
    app.state.pricing = pricing
    app.state.variant_catalogue = variant_catalogue
    install_security(app, allowed_hosts=allowed_hosts, secure_cookie=secure_cookie, indexing=indexing)
    install_handlers(app)

    count_visit = visit_counter(ctx)

    register_storefront_pages(app, ctx, count_visit)

    register_shell(app, ctx)

    app.state.rate_limits = {"public": public_hits, "login": failures}

    register_card_pages(app, ctx, count_visit)

    register_public_search(app, ctx)

    app.state.notifier = notifier
    app.state.rate_limits["signup"] = signups

    register_public_signup(app, ctx)

    app.state.rate_limits["guest"] = guests

    register_public_requests(app, ctx)

    register_accounts(app, ctx)

    register_settings(app, ctx)
    register_binder_imports(app, ctx)
    register_client_requests(app, ctx)

    register_public_listing(app, ctx, count_visit)

    register_statistics(app, ctx)


    register_auth(app, ctx)

    register_push(app, ctx)

    register_logout(app, ctx)
    register_users(app, ctx)

    register_copies(app, ctx)

    app.state.moves = moves

    hooks = build_hooks(ctx, auto_checks)
    register_capture(app, ctx, hooks)
    register_photo_batches(app, ctx, hooks)
    register_move_batches(app, ctx)

    register_intake(app, ctx, hooks)

    register_copy_images(app, ctx, hooks)
    register_closeups(app, ctx, hooks)

    register_conditions(app, ctx)

    app.state.agent_review = review

    register_checks(app, ctx)


    register_listings(app, ctx)
    register_floor_requests(app, ctx)

    register_sales(app, ctx)
    register_exports(app, ctx)
    register_backup(app, ctx)

    app.state.todo = todo

    register_todo(app, ctx)

    # The management chat, V1 (assistant.py, decisions 0029 and 0034): it reads
    # through the closed tools and writes nothing. Off without its own key.
    from .routes.assistant import register_assistant

    app.state.assistant = assistant
    register_assistant(app, ctx)

    if agent_enabled:
        from .agent_api import install

        install(app, store)
    return app
