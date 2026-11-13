"""Safety nets for splitting webapp.py: what the application exposes, pinned in readable files.

The stored expectations live in tests/snapshots/:

- web_routes.json: every route in registration order (methods, path, endpoint
  name, status code, response model and class, schema inclusion, dependency
  names in resolution order), with `only` naming the settings a conditional
  route needs. It is checked for every combination of `indexing`,
  `agent_enabled` and `secure_cookie`;
- web_openapi_agent.json and web_openapi_sans_agent.json: the OpenAPI schema
  with and without the agent API;
- web_app.json: middleware order, exception handlers (with the handler each
  agent handler falls back to) and the names published on `app.state`;
- web_headers.json: status and security/cache headers of representative
  requests, for `indexing` and `secure_cookie` on and off.

A change that alters one of them on purpose regenerates them in the same diff:

    uv run --extra web --extra dev pytest tests/test_web_snapshots.py --update-snapshots

then the diff of tests/snapshots/ shows exactly what changed. Names are kept
without their module, so moving a handler or a model to another module leaves
the files unchanged.
"""

import inspect
import itertools
import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match
from test_library import inputs

from pokeprice import passwords, webapp
from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection
from pokeprice.webapp import UserCreate, add_user, create_app

SNAPSHOTS = Path(__file__).with_name("snapshots")
SETTINGS = ("indexing", "agent_enabled", "secure_cookie")
CONFIGS = [dict(zip(SETTINGS, values)) for values in itertools.product((True, False), repeat=3)]
ORIGIN = "https://cartes.example"
PASSWORD = "Instantane-admin-2026!"
DOTTED = re.compile(r"\b(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)")


def no_service(*args, **kwargs):
    raise AssertionError("A snapshot never calls an external service")


SERVICES = {
    name: no_service for name in (
        "intake_reader", "intake_lookup", "condition_reader", "variant_reader", "edition_reader",
        "edition_get_json", "edition_fetch", "price_fetch", "variant_fetch", "market_fetch",
    )
}


def config_name(config):
    return ",".join(f"{key}={'on' if config[key] else 'off'}" for key in SETTINGS)


@pytest.fixture(scope="module")
def admin_store(tmp_path_factory):
    # An HTTPS deployment refuses to start without a local admin.
    store = Store(tmp_path_factory.mktemp("snapshots") / "inventory")
    with store.connect(write=True) as db:
        add_user(db, UserCreate(username="admin", password=PASSWORD, role="admin"))
    return store


def build(store, config):
    return create_app(store.root, public_origin=ORIGIN, **config, **SERVICES)


def matches(request, name, value):
    """Compare `value` with the stored file, or rewrite it with --update-snapshots."""
    path = SNAPSHOTS / name
    text = json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if request.config.getoption("--update-snapshots"):
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text)
        return
    assert path.is_file(), f"{name} is missing: run pytest {__file__} --update-snapshots"
    assert json.loads(path.read_text()) == json.loads(text), (
        f"{name} differs from the application; if the change is wanted, rerun with --update-snapshots"
    )


def short(value):
    """A type or callable by its name only, without the module that holds it."""
    if value is None:
        return None
    value = getattr(value, "value", value)  # FastAPI's DefaultPlaceholder
    if isinstance(value, type):
        return value.__name__
    return DOTTED.sub(r"\1", str(value))


def dependency_names(dependant):
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield getattr(dependency.call, "__name__", type(dependency.call).__name__)
        yield from dependency_names(dependency)


def flat_routes(routes):
    """The routes as the router tries them, lazy included routers opened in place."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None)
        assert nested is not None, f"Unexamined route type: {type(route)}"
        # Their paths are full and no dependency is added on inclusion.
        assert route.include_context.prefix == "" and not route.include_context.dependencies
        yield from flat_routes(nested.routes)


def describe(route):
    return {
        "methods": sorted(route.methods),
        "path": route.path,
        "name": route.name,
        "status_code": route.status_code,
        "response_model": short(route.response_model),
        "response_class": short(route.response_class),
        "include_in_schema": route.include_in_schema,
        "dependencies": list(dependency_names(route.dependant)),
    }


def route_table(app):
    return [describe(route) for route in flat_routes(app.routes)]


def condition(present):
    """The fewest settings whose values select exactly the configurations in `present`."""
    for size in range(len(SETTINGS) + 1):
        for keys in itertools.combinations(SETTINGS, size):
            for values in itertools.product((True, False), repeat=size):
                rule = dict(zip(keys, values))
                if present == {i for i, c in enumerate(CONFIGS) if all(c[k] == v for k, v in rule.items())}:
                    return rule
    raise AssertionError(f"No setting explains where a route exists: {present}")


def selected(rule, config):
    return all(config[key] == value for key, value in rule.items())


def test_route_table_in_every_configuration(admin_store, request):
    tables = [route_table(build(admin_store, config)) for config in CONFIGS]
    full = tables[CONFIGS.index({"indexing": True, "agent_enabled": True, "secure_cookie": True})]
    stored = []
    for route in full:
        present = {i for i, table in enumerate(tables) if route in table}
        stored.append({**route, "only": condition(present)})
    for config, table in zip(CONFIGS, tables):
        # Every configuration is the full table minus its conditional routes, in the same order.
        assert table == [{k: v for k, v in r.items() if k != "only"} for r in stored if selected(r["only"], config)], (
            config_name(config)
        )
    matches(request, "web_routes.json", stored)


def test_route_counts(admin_store):
    counts = {config_name(c): len(route_table(build(admin_store, c))) for c in CONFIGS}
    stored = json.loads((SNAPSHOTS / "web_routes.json").read_text())
    for config in CONFIGS:
        assert counts[config_name(config)] == sum(selected(r["only"], config) for r in stored)


def sample_path(route):
    # Each path parameter gets a value its convertor accepts.
    samples = {"str": "echantillon", "path": "echantillon/x", "int": "7", "float": "1.5",
               "uuid": "00000000-0000-4000-8000-000000000000"}
    return re.sub(r"\{(\w+)(?::(\w+))?\}", lambda m: samples[m[2] or "str"], route.path)


def resolve(routes, method, path):
    """The route the router picks for a request, trying routes in registration order."""
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
    for route in routes:
        match, _ = route.matches(scope)
        if match != Match.FULL:
            continue
        if isinstance(route, APIRoute):
            return route
        found = resolve(route.original_router.routes, method, path)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("config", CONFIGS, ids=config_name)
def test_every_route_is_reached_by_its_own_address(admin_store, config):
    # A route registered after a broader one with the same method would be shadowed.
    app = build(admin_store, config)
    shadowed = []
    for route in flat_routes(app.routes):
        path = sample_path(route)
        for method in sorted(route.methods):
            found = resolve(app.routes, method, path)
            if found is not route:
                shadowed.append((method, route.path, found and found.path))
    assert shadowed == []


def test_openapi_with_and_without_the_agent_api(admin_store, request):
    for agent in (True, False):
        schemas = [build(admin_store, c).openapi() for c in CONFIGS if c["agent_enabled"] is agent]
        # Only the agent API changes the schema: indexed and HTTPS routes stay out of it.
        assert all(schema == schemas[0] for schema in schemas)
        matches(request, f"web_openapi_{'agent' if agent else 'sans_agent'}.json", schemas[0])


def middleware(app):
    layers = []
    for layer in app.user_middleware:
        options = {key: (value.__name__ if callable(value) else value) for key, value in layer.kwargs.items()}
        layers.append({"class": layer.cls.__name__, **options})
    return layers


def exception_handlers(app):
    handlers = []
    for kind, handler in app.exception_handlers.items():
        entry = {"exception": f"{kind.__module__}.{kind.__qualname__}", "handler": handler.__name__}
        previous = inspect.signature(handler).parameters.get("previous")
        if previous is not None:
            # The agent API wraps the handler installed before it.
            entry["falls_back_to"] = previous.default.__name__
        handlers.append(entry)
    return handlers


def test_middleware_handlers_and_state(admin_store, request):
    stored = {}
    for config in CONFIGS:
        app = build(admin_store, config)
        found = {"middleware": middleware(app), "exception_handlers": exception_handlers(app),
                 "state": sorted(app.state._state)}
        key = "agent" if config["agent_enabled"] else "sans_agent"
        assert stored.setdefault(key, found) == found, config_name(config)
    matches(request, "web_app.json", stored)


HEADERS = (
    "content-type", "cache-control", "content-security-policy", "strict-transport-security",
    "x-robots-tag", "x-frame-options", "x-content-type-options", "referrer-policy",
)


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    # A small collection with one card on sale, so a public photo exists.
    root = tmp_path_factory.mktemp("headers")
    store = Store(root / "inventory")
    import_collection(store, inputs(root))
    with TestClient(build(store, {"indexing": True, "agent_enabled": False, "secure_cookie": False})) as admin:
        assert admin.post("/api/setup", json={"username": "admin", "password": PASSWORD}).status_code == 200
        card = next(c for c in admin.get("/api/copies", params={"limit": 100}).json()["items"]
                    if c["identification_status"] == "confirmed")
        listing = admin.put(f"/api/copies/{card['id']}/listing", json={"price_eur": "1.20"}).json()
    return store, listing["id"]


def test_security_and_cache_headers(published, request):
    store, listing = published
    requests = {
        "gestion": ("/gestion", {}),
        "storefront": ("/", {}),
        "api_anonymous": ("/api/summary", {}),
        "api_read": ("/api/summary", {}),
        "asset": ("/assets/app.js", {}),
        "favicon": ("/favicon.ico", {}),
        "service_worker": ("/gestion/sw.js", {}),
        "public_photo": (f"/api/public/listings/{listing}/photo", {}),
        "rejected_host": ("/gestion", {"host": "intrus.example"}),
        "robots": ("/robots.txt", {}),
        "sitemap": ("/sitemap.xml", {}),
    }
    stored = {}
    for indexing, secure in itertools.product((True, False), repeat=2):
        config = {"indexing": indexing, "agent_enabled": True, "secure_cookie": secure}
        seen = {}
        with TestClient(build(store, config), base_url="https://testserver") as client:
            for label, (path, headers) in requests.items():
                if label == "api_read":
                    login = client.post("/api/login", json={"username": "admin", "password": PASSWORD})
                    assert login.status_code == 200, login.text
                response = client.get(path, headers=headers)
                seen[label] = {"status": response.status_code,
                               **{name: response.headers.get(name) for name in HEADERS}}
        assert seen["api_read"]["status"] == 200 and seen["api_anonymous"]["status"] == 401
        assert seen["rejected_host"]["status"] == 400 and seen["public_photo"]["status"] == 200
        stored[f"indexing={'on' if indexing else 'off'},secure_cookie={'on' if secure else 'off'}"] = seen
    matches(request, "web_headers.json", stored)


def test_price_source_replaced_after_creation_reaches_the_variant_catalogue(tmp_path):
    # Tests replace app.state.pricing.fetch after create_app: the catalogue reads it at call time.
    app = create_app(tmp_path / "inventory", price_fetch=no_service)
    calls = []
    app.state.pricing.fetch = lambda *args: calls.append(args) or {"id": "x"}
    assert app.state.variant_catalogue.fetch("swsh1-1", "fr") == {"id": "x"}
    assert calls == [("swsh1-1", "fr")]


def test_services_on_app_state_share_one_instance_each(tmp_path):
    app = create_app(tmp_path / "inventory", **SERVICES)
    state = app.state
    for name, service in state._state.items():
        if hasattr(service, "store"):
            assert service.store is state.store, name
    assert state.pricing.market is state.market
    assert state.agent_review.variant_checks is state.variant_checks
    assert state.agent_review.conditions is state.conditions
    assert state.agent_review.edition_checks is state.edition_checks
    assert state.assistant.todo is state.todo
    # Tests rebind readers and channels on these objects after create_app.
    state.conditions.reader = no_service
    assert app.state.conditions.reader is no_service


def test_cheap_hashing_patch_reaches_password_hash():
    # conftest patches passwords.SCRYPT, the name password_hash reads. webapp must not
    # re-export it: a patch on a copy would silently stop applying and slow every login test.
    assert passwords.SCRYPT["n"] == 2**10
    assert passwords.password_hash("Mot-de-passe-2026!").startswith("scrypt$n=1024,")
    assert webapp.password_hash("Mot-de-passe-2026!").startswith("scrypt$n=1024,")
    assert not hasattr(webapp, "SCRYPT") and not hasattr(webapp, "LEGACY_SCRYPT")
