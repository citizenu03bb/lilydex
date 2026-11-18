"""The web application's start-up (routes/context.py): its order and its shared services."""

import ast
import dataclasses
from pathlib import Path

import pytest

from pokeprice import agent_api, webapp
from pokeprice.notifications import Notifier
from pokeprice.routes import context
from pokeprice.inventory import Conflict

SOURCE = Path(webapp.__file__).parent
# app.state name -> AppContext field, for the services the routes share.
PUBLISHED = {
    "store": "store", "intake": "intake", "conditions": "conditions",
    "variant_checks": "variant_checks", "edition_checks": "edition_checks", "market": "market",
    "pricing": "pricing", "variant_catalogue": "variant_catalogue", "notifier": "notifier",
    "moves": "moves", "agent_review": "review", "todo": "todo", "assistant": "assistant",
}


def no_service(*args, **kwargs):
    raise AssertionError("no network in tests")


def built(monkeypatch):
    seen = []
    original = webapp.build_services

    def spy(*args, **kwargs):
        seen.append(original(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(webapp, "build_services", spy)
    return seen


def test_store_then_notifier_then_handlers_then_agent_api(tmp_path, monkeypatch):
    events = []

    class Store(context.Store):
        def __init__(self, *args, **kwargs):
            events.append("store")
            super().__init__(*args, **kwargs)

    start, install = Notifier.start, agent_api.install
    monkeypatch.setattr(context, "Store", Store)
    monkeypatch.setattr(Notifier, "start", lambda self: events.append("notifier.start") or start(self))

    def spy_install(app, store):
        # The agent API keeps the application's handlers as its fallbacks.
        assert Conflict in app.exception_handlers and ValueError in app.exception_handlers
        events.append("agent_api.install")
        return install(app, store)

    monkeypatch.setattr(agent_api, "install", spy_install)
    webapp.create_app(tmp_path / "inventory", price_fetch=no_service)
    assert events == ["store", "notifier.start", "agent_api.install"]


def test_without_the_agent_api_nothing_is_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_api, "install", no_service)
    webapp.create_app(tmp_path / "inventory", price_fetch=no_service, agent_enabled=False)


def test_app_state_publishes_the_context_objects_themselves(tmp_path, monkeypatch):
    seen = built(monkeypatch)
    app = webapp.create_app(tmp_path / "inventory", price_fetch=no_service)
    (ctx,) = seen
    for name, field in PUBLISHED.items():
        assert getattr(app.state, name) is getattr(ctx, field), name
    assert ctx.review.inputs is ctx.variant_inputs
    assert ctx.assistant.todo is ctx.todo
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.store = None


def test_the_catalogue_images_keep_the_fetch_bound_at_start_up(tmp_path, monkeypatch):
    # Bound once: replacing variant_catalogue.fetch later does not reach the images.
    seen = built(monkeypatch)
    webapp.create_app(tmp_path / "inventory", price_fetch=no_service)
    (ctx,) = seen
    bound = ctx.catalogue_images.fetch
    assert bound == ctx.variant_catalogue.fetch
    ctx.variant_catalogue.fetch = no_service
    assert ctx.catalogue_images.fetch is bound


def test_the_web_modules_never_import_webapp():
    # One-way imports: webapp assembles the parts, no part reaches back into it.
    parts = [SOURCE / "web_constants.py", SOURCE / "schemas.py", SOURCE / "passwords.py",
             SOURCE / "errors.py", SOURCE / "security.py",
             *sorted((SOURCE / "routes").glob("*.py"))]
    for path in parts:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            assert not any(name.split(".")[-1] == "webapp" for name in names), path.name


def test_no_postponed_annotations_where_fastapi_reads_them():
    # FastAPI resolves body models from their annotations at registration.
    for path in [SOURCE / "schemas.py", *sorted((SOURCE / "routes").glob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                assert "annotations" not in [alias.name for alias in node.names], path.name
