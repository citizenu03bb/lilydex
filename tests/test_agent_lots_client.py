"""HTTP client of the lots tool and the ``--api`` mode of ``scripts/pokeprice_lots.py``.

The client's opener is bridged to the agent app in process: every request goes
through the real routes, with no socket, no real service and no real key.
"""

import io
import json
import sys
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest
from test_agent_lots_compose import RECIPE
from test_agent_lots_publish import shop  # noqa: F401 - fixture
from test_pokeprice_lots import test_db  # noqa: F401 - fixture

import pokeprice.agent_lots_compose as compose_api
from pokeprice import agent_client
from pokeprice.agent_client import AgentClient, AgentRequestError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pokeprice_lots  # noqa: E402

URL = "http://127.0.0.1:3820"


class AppOpener:
    """Sends each ``urllib`` request to the test app and records it."""

    def __init__(self, client):
        self.client, self.seen = client, []

    def open(self, request, timeout):
        parts = urlsplit(request.full_url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        headers = {name.lower(): value for name, value in request.header_items()}
        self.seen.append(
            {
                "method": request.get_method(),
                "path": path,
                "headers": headers,
                "body": json.loads(request.data) if request.data else None,
            }
        )
        response = self.client.request(
            request.get_method(), path, headers=headers, content=request.data
        )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                "refused",
                response.headers,
                io.BytesIO(response.content),
            )
        return io.BytesIO(response.content)


class Refusing:
    """An opener that answers with a fixed error, or never answers."""

    def __init__(self, status=None, body=None, headers=None):
        self.status, self.body, self.headers, self.seen = status, body, headers or {}, []

    def open(self, request, timeout):
        self.seen.append(dict(request.header_items()))
        if self.status is None:
            raise URLError("down")
        message = Message()
        for name, value in self.headers.items():
            message[name] = value
        raise HTTPError(
            request.full_url, self.status, "refused", message, io.BytesIO(json.dumps(self.body).encode())
        )


def bridged(test_client, token):
    client = AgentClient(URL, token)
    client.opener = AppOpener(test_client)
    return client


@pytest.fixture
def api(shop):  # noqa: F811
    test_client, service, grant, app = shop
    return bridged(test_client, grant["token"]), test_client, service, grant


def test_read_routes_and_their_paths(api):
    client, *_ = api
    pool = client.lots_pool(max_per_lot=5)
    assert pool["max_per_lot"] == 5 and pool["scope"] == "duplicates"
    assert client.lots_status()["cap_used"] == 0
    plan = client.lots_plan(RECIPE)
    assert len(plan["plan_id"]) == 64 and plan["lot"]["copies"]
    paths = [(call["method"], call["path"]) for call in client.opener.seen]
    assert paths == [
        ("GET", "/api/agent/v1/lots/pool?max_per_lot=5"),
        ("GET", "/api/agent/v1/lots/status"),
        ("POST", "/api/agent/v1/lots/plan"),
    ]
    assert all("idempotency-key" not in call["headers"] for call in client.opener.seen)


def test_compose_then_publish_and_unpublish_through_the_client(api):
    client, *_ = api
    plan = client.lots_plan(RECIPE)
    draft = client.lots_compose(plan["recipe"], plan["plan_id"])
    assert draft["status"] == "draft"
    check = client.lots_publication(draft["sale_id"])
    assert check["publishable"] and check["version"] == draft["version"]
    trial = client.lots_publish(draft["sale_id"], expected_version=check["version"])
    assert trial["dry_run"] is True
    published = client.lots_publish(
        draft["sale_id"], expected_version=check["version"], dry_run=False
    )
    listing_id = published["published_listing_id"]
    status = client.lots_status()
    assert status["online_drafts_count"] == 1
    with pytest.raises(AgentRequestError) as refused:
        client.lots_cancel(draft["sale_id"], expected_version=published["version"], reason="essai")
    assert (refused.value.status, refused.value.code) == (409, "online_lot")
    removed = client.lots_unpublish(listing_id, expected_version=1, reason="Plus d'actualité")
    assert removed["listing_id"] == listing_id


def test_each_write_gets_a_fresh_key_and_a_retry_reuses_it(api):
    client, *_ = api
    first = client.lots_rotate()
    second = client.lots_rotate()
    keys = [call["headers"]["idempotency-key"] for call in client.opener.seen]
    assert len(set(keys)) == 2 and all(key.startswith("lots-") for key in keys)
    assert first["dry_run"] is True and second["dry_run"] is True

    plan = client.lots_plan(RECIPE)
    created = client.lots_compose(plan["recipe"], plan["plan_id"], key="essai-1")
    again = client.lots_compose(plan["recipe"], plan["plan_id"], key="essai-1")
    assert again["replayed"] is True and again["sale_id"] == created["sale_id"]
    assert client.opener.seen[-1]["headers"]["idempotency-key"] == "essai-1"
    with pytest.raises(AgentRequestError) as conflict:
        client.lots_compose(plan["recipe"], plan["plan_id"], asking_cents=99999, key="essai-1")
    assert (conflict.value.status, conflict.value.code) == (409, "idempotency_conflict")
    assert conflict.value.idempotency_key == "essai-1"


def test_a_failed_write_hands_back_its_generated_key():
    client = AgentClient(URL, "pp_agent_" + "a" * 43)
    client.opener = Refusing()
    with pytest.raises(AgentRequestError) as down:
        client.lots_rotate(dry_run=False)
    assert down.value.code == "unreachable" and down.value.status is None
    assert down.value.idempotency_key == client.opener.seen[0]["Idempotency-key"]


def test_cancel_and_raise_pass_the_expected_version(api):
    client, *_ = api
    plan = client.lots_plan(RECIPE)
    draft = client.lots_compose(plan["recipe"], plan["plan_id"])
    with pytest.raises(AgentRequestError) as stale:
        client.lots_raise(draft["sale_id"], expected_version=draft["version"] + 5, asking_cents=draft["asking_cents"] + 100)
    assert stale.value.status == 409
    raised = client.lots_raise(
        draft["sale_id"], expected_version=draft["version"], asking_cents=draft["asking_cents"] + 100
    )
    assert client.opener.seen[-1]["body"] == {
        "expected_version": draft["version"],
        "asking_cents": draft["asking_cents"] + 100,
    }
    cancelled = client.lots_cancel(draft["sale_id"], expected_version=raised["version"], reason="essai")
    assert cancelled["status"] == "cancelled"


def test_a_missing_permission_is_a_403_with_its_code(api):
    _client, test_client, service, _grant = api
    reader = service.issue("Lecture", "owner", "a", client="Synthetic", permissions=["lots:read"])
    client = bridged(test_client, reader["token"])
    with pytest.raises(AgentRequestError) as refused:
        client.lots_rotate()
    assert refused.value.status == 403 and refused.value.code
    assert str(refused.value).startswith(f"HTTP 403 {refused.value.code} : ")
    assert reader["token"] not in str(refused.value)


def test_the_daily_quota_is_a_429_with_retry_after(api, monkeypatch):
    client, *_ = api
    monkeypatch.setattr(compose_api, "DAILY_DRAFTS", 1)
    plan = client.lots_plan(RECIPE)
    client.lots_compose(plan["recipe"], plan["plan_id"])
    plan = client.lots_plan(RECIPE)
    with pytest.raises(AgentRequestError) as refused:
        client.lots_compose(plan["recipe"], plan["plan_id"])
    assert (refused.value.status, refused.value.code) == (429, "draft_quota")
    assert refused.value.retry_after == "60"


def test_an_unknown_error_body_keeps_a_plain_message():
    client = AgentClient(URL, "pp_agent_" + "a" * 43)
    client.opener = Refusing(409, {"code": "Pas un code !", "detail": "Refusé."})
    with pytest.raises(AgentRequestError) as refused:
        client.lots_status()
    assert str(refused.value) == "HTTP 409 : Refusé." and refused.value.code == ""


def test_identifiers_are_checked_before_any_request():
    client = AgentClient(URL, "pp_agent_" + "a" * 43)
    client.opener = Refusing()
    with pytest.raises(ValueError, match="invalide"):
        client.lots_publication("../copies")
    assert client.opener.seen == []


def cli(monkeypatch, capsys, test_client, token, *argv):
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", token)
    monkeypatch.delenv("POKEPRICE_AGENT_TOKEN_FILE", raising=False)
    monkeypatch.setattr(agent_client, "build_opener", lambda *handlers: AppOpener(test_client))
    code = agent_client.main(["--url", URL, *map(str, argv)])
    out, err = capsys.readouterr()
    return code, (json.loads(out) if code == 0 else None), err


def test_cli_lots_commands(api, monkeypatch, capsys, tmp_path):
    _client, test_client, _service, grant = api
    recipe = tmp_path / "recette.json"
    recipe.write_text(json.dumps(RECIPE))
    run = lambda *argv: cli(monkeypatch, capsys, test_client, grant["token"], *argv)  # noqa: E731
    code, status, _ = run("lots-status")
    assert code == 0 and status["cap_used"] == 0
    code, plan, _ = run("lots-plan", "--recipe-file", recipe)
    assert code == 0
    code, draft, _ = run(
        "lots-compose", "--recipe-file", recipe, "--plan-id", plan["plan_id"], "--key", "cli-1"
    )
    assert code == 0 and draft["status"] == "draft"
    code, _, err = run("lots-compose", "--recipe-file", recipe, "--plan-id", "0" * 64)
    assert code == 1 and err.startswith("HTTP 409 stale_plan : ")
    assert "Clé d’idempotence : lots-" in err
    code, check, _ = run("lots-publication", draft["sale_id"])
    assert code == 0 and check["publishable"]
    code, trial, _ = run("lots-publish", draft["sale_id"], "--expected-version", check["version"])
    assert code == 0 and trial["dry_run"] is True
    code, rotation, _ = run("lots-rotate", "--limit", "0")
    assert code == 0 and rotation["dry_run"] is True


class Recorder:
    """A client stand-in that records the adapter's calls."""

    def __init__(self, **answers):
        self.calls, self.answers = [], answers

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.answers.get(name, {"ok": name})

        return call


def script_args(*argv):
    parser_args = ["--api", "--output", "o.json", *argv]
    seen = {}

    def capture(client, args):
        seen["args"] = args
        return {}

    original = pokeprice_lots.run_api_command
    pokeprice_lots.run_api_command = capture
    try:
        pokeprice_lots.AgentClient, saved = (lambda url, token: None), pokeprice_lots.AgentClient
        try:
            pokeprice_lots.main(parser_args)
        finally:
            pokeprice_lots.AgentClient = saved
    finally:
        pokeprice_lots.run_api_command = original
    return seen["args"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["analyze", "--max-per-lot", "7"], ("lots_pool", (7,), {})),
        (["status"], ("lots_status", (), {})),
        (["rotate"], ("lots_rotate", (), {"dry_run": False, "limit": None, "key": None})),
        (["--key", "r-1", "rotate", "--dry-run", "--limit", "2"], ("lots_rotate", (), {"dry_run": True, "limit": 2, "key": "r-1"})),
    ],
)
def test_the_adapter_routes_each_subcommand(argv, expected, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    args = script_args(*argv)
    recorder = Recorder()
    pokeprice_lots.run_api_command(recorder, args)
    assert recorder.calls == [expected]


def test_the_adapter_sends_the_recipe_and_composes_the_plan(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    plan = {"plan_id": "f" * 64, "recipe": RECIPE, "lot": {}}
    recorder = Recorder(lots_plan=plan, lots_compose={"sale_id": "s1"})
    args = script_args("compose", "--recipe", json.dumps(RECIPE))
    assert pokeprice_lots.run_api_command(recorder, args) == plan
    sent = recorder.calls[0][1][0]
    assert sent["title"] == RECIPE["title"] and sent["bundle_rules"]["diversity"] == "any"
    args = script_args("compose", "--recipe", json.dumps(RECIPE), "--create-draft", "--dry-run")
    assert pokeprice_lots.run_api_command(recorder, args)["draft_action"] == "dry_run_simulated"
    args = script_args("--key", "c-1", "compose", "--recipe", json.dumps(RECIPE), "--create-draft")
    result = pokeprice_lots.run_api_command(recorder, args)
    assert result["created_sale_id"] == "s1"
    assert recorder.calls[-1] == ("lots_compose", (RECIPE, "f" * 64), {"key": "c-1"})


def test_a_prompt_is_interpreted_on_the_workstation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    monkeypatch.setattr(
        pokeprice_lots,
        "prompt_to_recipe",
        lambda prompt: pokeprice_lots.LotCompositionRecipe.model_validate({**RECIPE, "title": prompt}),
    )
    recorder = Recorder(lots_plan={"plan_id": None})
    pokeprice_lots.run_api_command(recorder, script_args("compose", "--prompt", "Lot Kanto"))
    assert recorder.calls[0][1][0]["title"] == "Lot Kanto"


def test_the_adapter_publishes_at_the_checked_version(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    recorder = Recorder(lots_publication={"publishable": True, "version": 4})
    pokeprice_lots.run_api_command(recorder, script_args("publish-to-storefront", "--sale-id", "s1"))
    assert recorder.calls[-1] == ("lots_publish", ("s1",), {"expected_version": 4, "dry_run": False, "key": None})
    refused = Recorder(lots_publication={"publishable": False, "refusal": "Carte à examiner."})
    with pytest.raises(ValueError, match="examiner"):
        pokeprice_lots.run_api_command(refused, script_args("publish-to-storefront", "--sale-id", "s1"))
    assert [name for name, *_ in refused.calls] == ["lots_publication"]


def test_publish_all_skips_hand_made_and_online_drafts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    drafts = [
        {"id": "new", "title": "Nouveau", "tool_made": True, "online_listing_id": None},
        {"id": "online", "title": "En ligne", "tool_made": True, "online_listing_id": "l1"},
        {"id": "hand", "title": None, "tool_made": False, "online_listing_id": None},
    ]
    recorder = Recorder(
        lots_status={"active_drafts": drafts}, lots_publication={"publishable": True, "version": 2}
    )
    report = pokeprice_lots.run_api_command(
        recorder, script_args("publish-to-storefront", "--all", "--dry-run")
    )
    assert [entry["sale_id"] for entry in report["skipped"]] == ["hand", "online"]
    assert recorder.calls[-1] == ("lots_publish", ("new",), {"expected_version": 2, "dry_run": True, "key": None})


@pytest.mark.parametrize(
    "argv",
    [
        ["rotate", "--actor", "moi"],
        ["status", "--max-drafts", "9"],
        ["compose", "--recipe", "{}", "--scope", "all"],
        ["--key", "k", "status"],
        ["--key", "k", "publish-to-storefront", "--all"],
    ],
)
def test_the_adapter_refuses_what_the_server_decides(argv, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "pp_agent_" + "a" * 43)
    recorder = Recorder()
    with pytest.raises(ValueError, match="--"):
        pokeprice_lots.run_api_command(recorder, script_args(*argv))
    assert recorder.calls == []


def test_the_script_api_mode_end_to_end(shop, monkeypatch, tmp_path, capsys):  # noqa: F811
    test_client, _service, grant, _app = shop
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", grant["token"])
    monkeypatch.delenv("POKEPRICE_AGENT_TOKEN_FILE", raising=False)
    monkeypatch.setattr(agent_client, "build_opener", lambda *handlers: AppOpener(test_client))
    output = tmp_path / "compose.json"
    pokeprice_lots.main(
        ["--api", "--output", str(output), "compose", "--recipe", json.dumps(RECIPE), "--create-draft"]
    )
    sale_id = json.loads(output.read_text())["created_sale_id"]
    pokeprice_lots.main(
        ["--api", "--output", str(output), "publish-to-storefront", "--sale-id", sale_id]
    )
    assert json.loads(output.read_text())["published_listing_id"]
    with pytest.raises(SystemExit) as failed:
        pokeprice_lots.main(
            ["--api", "--output", str(output), "publish-to-storefront", "--sale-id", sale_id]
        )
    assert failed.value.code == 1
    assert "Refus de l'API agent" in capsys.readouterr().err


def test_without_api_the_script_still_needs_data(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as missing:
        pokeprice_lots.main(["--output", "o.json", "status"])
    assert missing.value.code == 2 and "--data" in capsys.readouterr().err
    with pytest.raises(SystemExit) as both:
        pokeprice_lots.main(["--api", "--remote", "--output", "o.json", "status"])
    assert both.value.code == 2
