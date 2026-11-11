"""Automatic renewal of the lots agent key and the lots agent launcher.

The renewal script runs against a fake `ssh` that runs the remote script
locally, a fake `sudo` that drops the account switch, and a fake
`pokeprice.manage` that keeps its delegations in a JSON file: no server, no
real key, no network.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENEW = ROOT / "deploy" / "lots-key-renew.sh"
LAUNCHER = ROOT / "deploy" / "lots-agent-run.sh"
DAY = 86400

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash requis pour les scripts de déploiement")

FAKE_SSH = """#!/usr/bin/env bash
# fake ssh: drop options and host, run the remote command here.
while [ "$1" = -o ]; do shift 2; done
echo "$1" >>"$FAKE_STATE.hosts"
shift
exec bash -c "$*"
"""

FAKE_SUDO = f"""#!/usr/bin/env bash
# fake sudo: drop -n and -u ACCOUNT, route pokeprice.manage to the fake.
[ "$1" = -n ] && shift
[ "$1" = -u ] && shift 2
for ((i = 1; i <= $#; i++)); do
    if [ "${{!i}}" = pokeprice.manage ]; then
        shift "$i"
        exec {sys.executable} "$FAKE_MANAGE" "$@"
    fi
done
exec "$@"
"""

FAKE_MANAGE = """
import json, os, sys, time
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
assert args[:2] == ["--data", "/srv/pokeprice/inventory"], args
action, rest = args[2], args[3:]
state["calls"].append([action] + rest)

def save():
    json.dump(state, open(state_path, "w"))

def option(name):
    return rest[rest.index(name) + 1]

if action == "agent-list":
    save()
    print(json.dumps(state["grants"], indent=2))
elif action == "agent-create":
    if state.get("fail_create"):
        save()
        sys.exit("Erreur simulée de création.")
    grant_id = "grant-%d" % (len(state["grants"]) + 1)
    token = "pp_agent_secret_%s" % grant_id
    fd = os.open(option("--token-file"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token + "\\n")
    grant = {"id": grant_id, "name": rest[0], "expires_at": int(time.time()) + 7 * 86400,
             "revoked_at": "", "permissions": ["lots:read", "lots:compose", "lots:publish"]}
    state["grants"].append(grant)
    state["tokens"][grant_id] = token
    save()
    print("Attention : les permissions lots portent sur toute la collection.", file=sys.stderr)
    # Same shape as pokeprice-manage agent-create: a lifetime in days, no expires_at.
    print(json.dumps({"id": grant_id, "album_id": "album", "permissions": grant["permissions"],
                      "expires_in_days": 7, "value_ceiling_cents": 1000,
                      "token_file": option("--token-file")}, indent=2))
elif action == "agent-revoke":
    if state.get("fail_revoke"):
        save()
        sys.exit("Erreur simulée de révocation.")
    for grant in state["grants"]:
        if grant["id"] == rest[0]:
            grant["revoked_at"] = "now"
    save()
    print(json.dumps({"id": rest[0], "revoked": True}))
"""


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def world(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "ssh", FAKE_SSH)
    executable(bin_dir / "sudo", FAKE_SUDO)
    (tmp_path / "fake_manage.py").write_text(FAKE_MANAGE)
    drop = tmp_path / "drop"
    drop.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    config = tmp_path / "lots-key.env"
    config.write_text(
        f"POKEPRICE_OCI_HOST=operator@server.invalid\nLOTS_OWNER=admin\nLOTS_ALBUM=album-1\nLOTS_TOKEN_DIR={drop}\n"
    )
    state = tmp_path / "state.json"

    class World:
        root = tmp_path
        token_dir = drop

        def set_state(self, grants=(), **flags):
            state.write_text(json.dumps({"grants": list(grants), "calls": [], "tokens": {}, **flags}))

        def state(self):
            return json.loads(state.read_text())

        def actions(self):
            return [call[0] for call in self.state()["calls"]]

        def run(self):
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": str(tmp_path),
                "TMPDIR": str(scratch),
                "LOTS_KEY_ENV": str(config),
                "FAKE_STATE": str(state),
                "FAKE_MANAGE": str(tmp_path / "fake_manage.py"),
            }
            return subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=60)

        def leftovers(self):
            return sorted(p.name for p in scratch.iterdir())

    world = World()
    world.set_state()
    return world


def grant(grant_id, expires_in, revoked=""):
    return {"id": grant_id, "name": "lots-doublons", "revoked_at": revoked, "expires_at": int(time.time()) + expires_in}


def install_old(world, grant_id="old-1", token="pp_agent_old_token"):
    (world.token_dir / "access-id").write_text(grant_id + "\n")
    (world.token_dir / "token").write_text(token + "\n")


def assert_secret_free(world, result):
    for token in world.state()["tokens"].values():
        assert token not in result.stdout
        assert token not in result.stderr


def test_first_run_creates_the_key_and_drops_the_token_mode_0640(world):
    result = world.run()

    assert result.returncode == 0, result.stderr
    assert world.actions() == ["agent-create"]
    create = world.state()["calls"][0]
    for flag in ("--lots-read", "--lots-compose", "--lots-publish"):
        assert flag in create
    assert create[1] == "lots-doublons"
    assert create[create.index("--owner") + 1] == "admin"
    assert create[create.index("--album") + 1] == "album-1"
    assert create[create.index("--actor") + 1] == "system:lots-key-renew"
    assert "--value-ceiling-eur" not in create
    token = world.token_dir / "token"
    assert token.read_text().strip() == world.state()["tokens"]["grant-1"]
    assert stat.S_IMODE(token.stat().st_mode) == 0o640
    assert (world.token_dir / "access-id").read_text().strip() == "grant-1"
    assert "grant-1" in result.stdout
    assert_secret_free(world, result)
    assert sorted(p.name for p in world.token_dir.iterdir()) == ["access-id", "token"]
    assert world.leftovers() == []


def test_fresh_key_is_left_alone(world):
    install_old(world)
    world.set_state([grant("old-1", 5 * DAY)])

    result = world.run()

    assert result.returncode == 0, result.stderr
    assert world.actions() == ["agent-list"]
    assert "rien à faire" in result.stdout
    assert (world.token_dir / "token").read_text().strip() == "pp_agent_old_token"
    assert world.leftovers() == []


def test_key_near_expiry_is_renewed_then_the_old_one_revoked(world):
    install_old(world)
    world.set_state([grant("old-1", 30 * 3600)])

    result = world.run()

    assert result.returncode == 0, result.stderr
    assert world.actions() == ["agent-list", "agent-create", "agent-revoke"]
    revoke = world.state()["calls"][2]
    assert revoke[1] == "old-1"
    assert revoke[revoke.index("--actor") + 1] == "system:lots-key-renew"
    old = next(g for g in world.state()["grants"] if g["id"] == "old-1")
    assert old["revoked_at"]
    token = world.token_dir / "token"
    assert token.read_text().strip() == world.state()["tokens"]["grant-2"]
    assert stat.S_IMODE(token.stat().st_mode) == 0o640
    assert (world.token_dir / "access-id").read_text().strip() == "grant-2"
    assert "old-1" in result.stdout and "grant-2" in result.stdout
    assert_secret_free(world, result)
    assert world.leftovers() == []


def test_failed_creation_keeps_the_old_key(world):
    install_old(world)
    world.set_state([grant("old-1", 3600)], fail_create=True)

    result = world.run()

    assert result.returncode != 0
    assert world.actions() == ["agent-list", "agent-create"]
    assert (world.token_dir / "token").read_text().strip() == "pp_agent_old_token"
    assert (world.token_dir / "access-id").read_text().strip() == "old-1"
    assert "l'ancien accès reste en place" in result.stderr
    assert sorted(p.name for p in world.token_dir.iterdir()) == ["access-id", "token"]
    assert world.leftovers() == []


def test_failed_revocation_fails_but_keeps_the_new_token(world):
    install_old(world)
    world.set_state([grant("old-1", 3600)], fail_revoke=True)

    result = world.run()

    assert result.returncode != 0
    assert world.actions() == ["agent-list", "agent-create", "agent-revoke"]
    assert (world.token_dir / "token").read_text().strip() == world.state()["tokens"]["grant-2"]
    assert (world.token_dir / "access-id").read_text().strip() == "grant-2"
    assert "old-1" in result.stderr
    assert_secret_free(world, result)


@pytest.mark.parametrize("old", [grant("old-1", 5 * DAY, revoked="x"), None])
def test_revoked_or_unknown_key_is_replaced_without_revoking(world, old):
    install_old(world)
    world.set_state([old] if old else [])

    result = world.run()

    assert result.returncode == 0, result.stderr
    assert world.actions() == ["agent-list", "agent-create"]
    assert (world.token_dir / "access-id").read_text().strip().startswith("grant-")


def test_unreachable_server_changes_nothing(world):
    install_old(world)
    world.set_state([grant("old-1", 3600)])
    executable(world.root / "bin" / "ssh", "#!/usr/bin/env bash\nexit 255\n")

    result = world.run()

    assert result.returncode != 0
    assert (world.token_dir / "token").read_text().strip() == "pp_agent_old_token"
    assert (world.token_dir / "access-id").read_text().strip() == "old-1"


@pytest.fixture
def lots_home(tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    clone = home / "lilydex"
    clone.mkdir()
    drop = tmp_path / "drop"
    drop.mkdir()
    token = drop / "token"
    token.write_text("pp_agent_lots\n")
    token.chmod(0o640)
    config = home / ".config" / "pokeprice"
    config.mkdir(parents=True)
    (config / "agent.env").write_text(f"POKEPRICE_AGENT_URL=https://agent.invalid\nLOTS_TOKEN_DIR={drop}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    executable(bin_dir / "git", f'#!/usr/bin/env bash\necho "git $*" >>{log}\nexit "${{GIT_STATUS:-0}}"\n')
    executable(local_bin / "uv", f'#!/usr/bin/env bash\necho "uv $* in $PWD" >>{log}\nexit "${{UV_STATUS:-0}}"\n')

    def run(**env_overrides):
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(home),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
            **env_overrides,
        }
        (tmp_path / "run").mkdir(exist_ok=True)
        command = [
            "bash",
            str(LAUNCHER),
            "bash",
            "-c",
            'echo "pwd=$PWD"; echo "url=$POKEPRICE_AGENT_URL"; '
            'echo "file=$POKEPRICE_AGENT_TOKEN_FILE"; stat -c %a "$POKEPRICE_AGENT_TOKEN_FILE"; '
            'cat "$POKEPRICE_AGENT_TOKEN_FILE" >/dev/null',
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        return result, log.read_text() if log.exists() else ""

    run.clone = clone
    run.private = tmp_path / "run" / "pokeprice" / "lots.token"
    return run


def test_launcher_pulls_syncs_and_runs_in_the_clone_with_a_private_token(lots_home):
    result, log = lots_home()

    assert result.returncode == 0, result.stderr
    assert log.splitlines() == [
        f"git -C {lots_home.clone} pull --ff-only -q",
        f"uv sync -q in {lots_home.clone}",
    ]
    assert f"pwd={lots_home.clone}" in result.stdout
    assert "url=https://agent.invalid" in result.stdout
    assert f"file={lots_home.private}" in result.stdout
    assert result.stdout.strip().endswith("600")
    assert "pp_agent_lots" not in result.stdout + result.stderr


def test_launcher_continues_offline_on_the_current_copy(lots_home):
    result, log = lots_home(GIT_STATUS="1")

    assert result.returncode == 0, result.stderr
    assert "copie actuelle" in result.stderr
    assert "uv sync -q" in log
    assert f"pwd={lots_home.clone}" in result.stdout


def test_launcher_stops_when_uv_sync_fails(lots_home):
    result, _ = lots_home(UV_STATUS="1")

    assert result.returncode != 0
    assert "pwd=" not in result.stdout


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck absent")
def test_deploy_scripts_pass_shellcheck():
    result = subprocess.run(["shellcheck", str(RENEW), str(LAUNCHER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
