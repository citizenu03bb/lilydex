"""Disposable Codex client with only the explicit evaluation MCP tools."""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from agent_review_fixture import private_write


def run_client(private_root, workspace, token_file, url, prompt, schema, timeout=360):
    root = Path(__file__).resolve().parents[1]
    binary = Path(shutil.which("codex")).resolve()
    auth_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    auth = auth_home / "auth.json"
    if not auth.is_file():
        raise ValueError("Session Codex fichier absente ; aucun fournisseur de repli.")
    home = private_root / "client-home"
    home.mkdir(mode=0o700)
    codex_home = home / ".codex"
    codex_home.mkdir(mode=0o700)
    private_write(codex_home / "auth.json", auth.read_bytes())
    config = """approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
project_doc_max_bytes = 0
[features]
shell_tool = false
apps = false
[mcp_servers.pokeprice]
command = "/usr/bin/python3"
args = ["/tools/bridge.py"]
required = true
tool_timeout_sec = 40
[mcp_servers.pokeprice.env]
EVAL_TASK = "review"
EVAL_MAX_TOOL_CALLS = "24"
POKEPRICE_AGENT_TOKEN_FILE = "/access.token"
"""
    config += "POKEPRICE_AGENT_URL = " + json.dumps(url) + "\n"
    for name in ("capabilities", "copies", "copy", "photo"):
        config += f'\n[mcp_servers.pokeprice.tools.{name}]\napproval_mode = "approve"\noutput_token_limit = 25000\n'
    private_write(codex_home / "config.toml", config.encode())
    private_write(workspace / "schema.json", json.dumps(schema).encode())
    private_write(workspace / "prompt.txt", prompt.encode())
    command = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
    ]
    for source, target, writable in (
        ("/usr", "/usr", False),
        ("/lib", "/lib", False),
        ("/lib64", "/lib64", False),
        ("/etc/ssl", "/etc/ssl", False),
        ("/etc/resolv.conf", "/etc/resolv.conf", False),
        ("/etc/hosts", "/etc/hosts", False),
        (binary.parent.parent, binary.parent.parent, False),
        (home, "/home/evaluator", True),
        (workspace, "/work", True),
        (token_file, "/access.token", False),
        (root / "scripts/agent_eval_tools.py", "/tools/bridge.py", False),
        (root / "src/pokeprice/agent_client.py", "/tools/client.py", False),
    ):
        command += ["--bind" if writable else "--ro-bind", str(source), str(target)]
    command += [
        "--symlink",
        "usr/bin",
        "/bin",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--clearenv",
    ]
    for key, value in {
        "HOME": "/home/evaluator",
        "CODEX_HOME": "/home/evaluator/.codex",
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
    }.items():
        command += ["--setenv", key, value]
    command += ["--chdir", "/work", "--"]
    paths = [str(root), str(private_root / "album"), "/home/pat/.ssh"]
    preflight = subprocess.run(
        command
        + [
            "/usr/bin/python3",
            "-c",
            "from pathlib import Path; import json; print(json.dumps({p:Path(p).exists() for p in "
            + repr(paths)
            + "}))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    isolation = json.loads(preflight.stdout)
    if any(isolation.values()):
        raise ValueError("Le client peut voir des fichiers qui doivent être isolés.")
    # Session files live only in the temporary home. Read only the selected model
    # metadata afterwards, then delete this home with the surrounding context.
    command += [
        str(binary),
        "exec",
        "--skip-git-repo-check",
        "--json",
        "--output-schema",
        "/work/schema.json",
        "--output-last-message",
        "/work/answer.json",
        "-",
    ]
    started = time.monotonic()
    with (
        open(
            workspace / "events.jsonl",
            "x",
            opener=lambda p, flags: os.open(p, flags, 0o600),
        ) as stdout,
        open(
            workspace / "stderr.txt",
            "x",
            opener=lambda p, flags: os.open(p, flags, 0o600),
        ) as stderr,
    ):
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        try:
            process.communicate(prompt, timeout=timeout)
            status = "completed" if process.returncode == 0 else "client_error"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            status = "timeout"
    models = set()
    for session in (codex_home / "sessions").rglob("*.jsonl"):
        for line in session.read_text().splitlines():
            event = json.loads(line)
            if event.get("type") == "turn_context" and event["payload"].get("model"):
                models.add(event["payload"]["model"])
    return {
        "status": status,
        "exit_code": process.returncode,
        "seconds": round(time.monotonic() - started, 2),
        "model_ids": sorted(models),
        "model_selection": "native CLI default, no user model alias copied",
        "isolation": {
            "repository_mounted": isolation[paths[0]],
            "database_mounted": isolation[paths[1]],
            "ssh_mounted": isolation[paths[2]],
        },
    }
