import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_script", ROOT / "scripts/check.py")
check = importlib.util.module_from_spec(spec)
sys.modules["check_script"] = check
spec.loader.exec_module(check)


def names(steps):
    return [s.name for s in steps]


def test_full_run_mirrors_ci_steps():
    steps = check.build_steps(changed=["a.py"], browser_reason="")
    assert names(steps) == [
        "ruff",
        "mypy",
        "ruff (fichiers modifiés)",
        "documentation",
        "pytest (Python et JavaScript)",
        "recette Firefox",
    ]
    by_name = {s.name: s for s in steps}
    assert by_name["ruff"].cmd[-3:] == ["ruff", "check", "."]
    assert by_name["mypy"].cmd[-1] == "mypy"
    assert by_name["ruff (fichiers modifiés)"].cmd[-1] == "a.py"
    assert by_name["recette Firefox"].skip_reason is None


def test_fast_run_skips_slow_steps():
    steps = check.build_steps(rapide=True, changed=[])
    assert names(steps) == ["ruff (fichiers modifiés)", "documentation"]
    assert steps[0].skip_reason


def test_browser_skipped_when_unavailable_or_disabled():
    steps = check.build_steps(changed=[], browser_reason="dépendances absentes")
    assert steps[-1].skip_reason == "dépendances absentes"
    steps = check.build_steps(changed=[], navigateur=False)
    assert steps[-1].skip_reason == "--sans-navigateur"


def test_browser_skip_reason_without_node_modules(tmp_path):
    assert "dépendances" in check.browser_skip_reason(tmp_path, home=tmp_path) or "npm" in (
        check.browser_skip_reason(tmp_path, home=tmp_path)
    )


def test_exit_status_and_summary(monkeypatch, capsys):
    def fake_run(step):
        status = check.ECHEC if step.name == "mypy" else check.OK
        return check.Result(step.name, status, 0.0)

    monkeypatch.setattr(check, "run_step", fake_run)
    assert check.main(["--base", "master", "--sans-navigateur"]) == 1
    out = capsys.readouterr().out
    assert "Contrôle en échec : mypy" in out

    monkeypatch.setattr(check, "run_step", lambda s: check.Result(s.name, check.OK, 0.0))
    assert check.main(["--rapide"]) == 0
    assert "Contrôle réussi." in capsys.readouterr().out


def test_run_step_reports_failure_and_missing_command(tmp_path):
    ok = check.run_step(check.Step("x", [sys.executable, "-c", "pass"], cwd=tmp_path))
    bad = check.run_step(check.Step("x", [sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path))
    gone = check.run_step(check.Step("x", ["commande-inexistante-xyz"], cwd=tmp_path))
    assert (ok.status, bad.status, gone.status) == (check.OK, check.ECHEC, check.ECHEC)
