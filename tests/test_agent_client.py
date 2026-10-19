import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import test_agent_control
from fastapi.testclient import TestClient
from test_agent_control import PASSWORD

from pokeprice.agent_client import AgentClient, load_token
from pokeprice.inventory import Store
from pokeprice.manage import main as manage


@pytest.fixture
def shop(tmp_path):
    yield from test_agent_control.shop.__wrapped__(tmp_path)


@pytest.fixture
def live_server(shop):
    uvicorn = pytest.importorskip("uvicorn")
    client, _service, _grant, _cards, _other, _user = shop
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(client.app, log_level="error", access_log=False, lifespan="off")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", shop
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def test_real_cli_http_workflow_and_management_review(live_server, tmp_path):
    url, (client, service, grant, _cards, _, _) = live_server
    token_file = tmp_path / "agent.token"
    token_file.write_text(grant["token"] + "\n")
    token_file.chmod(0o600)
    env = os.environ.copy()
    env.pop("POKEPRICE_AGENT_TOKEN", None)
    env.pop("POKEPRICE_AGENT_TOKEN_FILE", None)

    def cli(*args, success=True):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pokeprice.agent_client",
                "--url",
                url,
                "--token-file",
                str(token_file),
                *args,
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert grant["token"] not in result.stdout + result.stderr
        assert (result.returncode == 0) == success, result.stderr
        return json.loads(result.stdout) if success else result.stderr

    capabilities = cli("capabilities")
    assert capabilities["album_id"] == "a"
    request_file = tmp_path / "request.json"
    report = cli(
        "prepare-lot",
        "--language",
        "fr",
        "--request-output",
        str(request_file),
        "--title",
        "Lot préparé en CLI",
    )
    assert len(report["selected"]) == 3 and request_file.stat().st_mode & 0o077 == 0
    receipt = cli(
        "create-draft", "--request-file", str(request_file), "--key", "cli-lot-1"
    )
    assert (
        cli("create-draft", "--request-file", str(request_file), "--key", "cli-lot-1")
        == receipt
    )
    draft = cli("draft", receipt["id"])
    assert draft["amount_cents"] is None and not draft["stale"]
    target = tmp_path / "annonce.zip"
    cli("package", receipt["id"], "--output", str(target))
    with zipfile.ZipFile(target) as archive:
        assert "Lot préparé en CLI" in archive.read("description.txt").decode()
        assert "état à vérifier" in archive.read("description.txt").decode()
    assert target.stat().st_mode & 0o077 == 0
    with TestClient(client.app) as human:
        human.post("/api/login", json={"username": "owner", "password": PASSWORD})
        sales = human.get("/api/sales").json()
        assert len(sales) == 1 and sales[0]["id"] == receipt["id"]
        assert sales[0]["agent_preparation"]["origin"] == "agent"
        assert {c["stock_state"] for c in sales[0]["items"]} == {"available"}
        assert human.get("/api/public/listings").json()["items"] == []
    service.revoke(grant["id"])
    assert "401" in cli("copies", success=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "file:///tmp/test",
        "https://user:password@example.org",
        "https://example.org/?token=bad",
        "https://example.org/elsewhere",
    ],
)
def test_client_rejects_unsafe_or_ambiguous_backend_urls(url):
    with pytest.raises(ValueError):
        AgentClient(url, "pp_agent_" + "a" * 43)


def test_client_never_follows_a_redirect_with_credentials(live_server):
    url, (_, _, grant, _, _, _) = live_server
    calls = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(302)
            self.send_header("Location", url + "/api/agent/v1/copies")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        agent = AgentClient(
            "http://127.0.0.1:" + str(server.server_port), grant["token"]
        )
        with pytest.raises(ValueError, match="302"):
            agent.request("/capabilities")
        assert calls == ["/api/agent/v1/capabilities"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_token_file_is_private_and_not_ambiguous(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("pp_agent_" + "a" * 43)
    token.chmod(0o644)
    monkeypatch.delenv("POKEPRICE_AGENT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="privé"):
        load_token(token)
    token.chmod(0o600)
    assert load_token(token).startswith("pp_agent_")
    monkeypatch.setenv("POKEPRICE_AGENT_TOKEN", "another")
    with pytest.raises(ValueError, match="pas les deux"):
        load_token(token)


def test_manage_issue_list_revoke_and_offline_schema(
    shop, tmp_path, monkeypatch, capsys
):
    _, service, _, _, _, _ = shop
    token = tmp_path / "new.token"

    def run(*args):
        monkeypatch.setattr(
            sys, "argv", ["pokeprice-manage", "--data", str(service.store.root), *args]
        )
        manage()
        return capsys.readouterr().out

    output = run(
        "agent-create",
        "Local client",
        "--owner",
        "owner",
        "--album",
        "a",
        "--client",
        "Synthetic local client; no external photos",
        "--drafts",
        "--token-file",
        str(token),
    )
    issued = json.loads(output)
    secret = token.read_text().strip()
    assert secret not in output and token.stat().st_mode & 0o077 == 0
    listed = run("agent-list")
    assert secret not in listed and "token_hash" not in listed
    assert any(g["id"] == issued["id"] for g in json.loads(listed))
    assert json.loads(run("agent-revoke", issued["id"]))["revoked"]
    with pytest.raises(FileExistsError):
        run(
            "agent-create",
            "Again",
            "--owner",
            "owner",
            "--album",
            "a",
            "--client",
            "local",
            "--token-file",
            str(token),
        )

    def no_database(*args, **kwargs):
        raise AssertionError("Schema export must not open a database")

    monkeypatch.setattr(Store, "__init__", no_database)
    exported = json.loads(run("agent-schema"))
    assert all(path.startswith("/api/agent/v1/") for path in exported["paths"])
