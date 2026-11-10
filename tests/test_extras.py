"""The server runs without the scanner dependencies (extra « cli »)."""

import subprocess
import sys

BLOCK = "import sys\nfor name in ('pandas', 'openpyxl', 'tabulate'):\n    sys.modules[name] = None\n"


def run(code):
    return subprocess.run(
        [sys.executable, "-c", BLOCK + code], capture_output=True, text=True, timeout=120
    )


def test_server_entry_points_import_without_the_scanner_dependencies():
    done = run(
        "import pokeprice.manage, pokeprice.webapp, pokeprice.assistant, pokeprice.assistant_tools\n"
        "import pokeprice.agent_api, pokeprice.daily_backup, pokeprice.pricing, pokeprice.notifications\n"
        "import pokeprice.library, pokeprice.marketplace_export, pokeprice.todo\n"
        "assert 'pokeprice.report' not in sys.modules and 'pokeprice.html_report' not in sys.modules\n"
    )
    assert done.returncode == 0, done.stderr


def test_the_scanner_names_the_extra_to_install():
    done = run("import pokeprice.cli\n")
    assert done.returncode != 0
    assert "MissingExtra" in done.stderr and "uv sync --extra cli" in done.stderr


def test_import_command_names_the_extra_instead_of_a_traceback(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "album.csv").write_text("Page\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"albums": [{"id": "a", "name": "A", "report": "album.csv", "photos": "photos"}]}',
        encoding="utf-8",
    )
    done = run(
        "from pokeprice.manage import main\n"
        f"sys.argv = ['pokeprice-manage', '--data', {str(tmp_path / 'inventory')!r}, 'import', {str(manifest)!r}]\n"
        "main()\n"
    )
    assert done.returncode == 1
    assert "Traceback" not in done.stderr and "extra « cli »" in done.stderr
