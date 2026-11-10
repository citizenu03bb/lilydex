"""The management scripts load as the page loads them (safety net for splitting app.js).

A split of `app.js` into parts must keep three lists in step: the script tags
of `index.html`, the service worker's shell (`APP_SHELL`) and the names the
`/assets/{name}` route accepts. Each part must run in strict mode, and the
parts, run one after the other in one context, must load without error.
"""

import re
import shutil
import subprocess
import typing
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from web_scripts import WEB, app_parts, app_source, management_scripts

from pokeprice.webapp import APP_SHELL, create_app

ROOT = Path(__file__).resolve().parents[1]
LEADING_COMMENTS = re.compile(r"\A(?:\s+|/\*.*?\*/|//[^\n]*)*", re.S)


def asset_names(app):
    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/assets/{name}")
    return set(typing.get_args(typing.get_type_hints(route.endpoint)["name"]))


def test_index_lists_the_app_parts_first_part_named_app_js():
    parts = app_parts()
    assert parts and parts[0] == "app.js"
    scripts = management_scripts()
    # The parts load one after the other, with no other script between them.
    first = scripts.index(parts[0])
    assert scripts[first:first + len(parts)] == parts


def test_each_management_script_runs_in_strict_mode():
    for name in management_scripts():
        source = (WEB / name).read_text()
        body = source[LEADING_COMMENTS.match(source).end():]
        assert body.startswith('"use strict";'), name


def test_script_tags_shell_and_asset_whitelist_agree(tmp_path):
    scripts = management_scripts()
    assert len(scripts) == len(set(scripts))
    shell = [path.removeprefix("/assets/") for path in APP_SHELL if path.endswith(".js")]
    # The worker caches every script of the page, and nothing else.
    assert shell == scripts
    allowed = asset_names(create_app(tmp_path / "inventory"))
    assert {path.removeprefix("/assets/") for path in APP_SHELL if path.startswith("/assets/")} <= allowed
    assert set(scripts) <= allowed
    for name in allowed:
        assert (WEB / name).is_file(), name


def test_management_scripts_load_in_order_against_a_stub_dom():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to load the management scripts")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_load_runtime.cjs"), *(str(WEB / name) for name in management_scripts())],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"loaded {len(management_scripts())} scripts" in result.stdout


def test_load_check_fails_on_scripts_out_of_order():
    # The net must catch a part loaded before the one it needs at load time.
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to load the management scripts")
    scripts = management_scripts()
    result = subprocess.run(
        [node, str(ROOT / "tests/web_load_runtime.cjs"), str(WEB / "workflows.js"),
         *(str(WEB / name) for name in scripts if name != "workflows.js")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_app_source_joins_the_parts_beside_the_other_web_files(tmp_path):
    joined = Path(app_source(tmp_path))
    assert joined.read_text() == "\n".join((WEB / name).read_text() for name in app_parts())
    assert (joined.parent / "components.js").read_text() == (WEB / "components.js").read_text()
    assert (joined.parent / "messages" / "fr.json").is_file()
