#!/usr/bin/env python3
"""Contrôle unique avant un commit : les mêmes vérifications que la CI, en local.

Lance, dans l'ordre : ruff et mypy (comme `.github/workflows/tests.yml`),
ruff sur les seuls fichiers Python modifiés par rapport à `master`, la
documentation (`check_docs.py`), la suite pytest (qui exécute aussi les tests
JavaScript des scripts) et, si Node, les dépendances de `tests/browser` et
Firefox sont installés, la recette Playwright dans Firefox. Une étape qui ne
peut pas tourner ici est signalée « ignorée » et ne fait pas échouer le
contrôle. Code de sortie : 0 si aucune étape n'échoue, 1 sinon.

Usage : python scripts/check.py [--rapide] [--sans-navigateur] [--base RÉVISION]
  --rapide           lint des fichiers modifiés et documentation
                     seulement (quelques secondes).
  --sans-navigateur  n'essaie pas la recette Playwright.
  --base RÉVISION    révision de comparaison des fichiers modifiés (master).
"""

from __future__ import annotations

import argparse
import glob
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = ROOT / "tests" / "browser"
UV = ["uv", "run", "--extra", "web", "--extra", "dev"]

OK, ECHEC, IGNOREE = "ok", "échec", "ignorée"


@dataclass
class Step:
    name: str
    cmd: list[str] | None
    cwd: Path = ROOT
    skip_reason: str | None = None


@dataclass
class Result:
    name: str
    status: str
    seconds: float
    detail: str = ""


def changed_python_files(base: str, root: Path = ROOT) -> list[str]:
    """Fichiers Python modifiés (commités, indexés ou non) depuis `base`, encore présents."""

    def git(*args: str) -> list[str]:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        return out.stdout.splitlines() if out.returncode == 0 else []

    names = set(git("diff", "--name-only", "--diff-filter=d", f"{base}...HEAD"))
    names |= set(git("diff", "--name-only", "--diff-filter=d", "HEAD"))
    names |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(n for n in names if n.endswith(".py") and (root / n).is_file())


def browser_skip_reason(browser_dir: Path = BROWSER_DIR, home: Path | None = None) -> str | None:
    """Pourquoi la recette Playwright ne peut pas tourner ici, ou None."""
    if shutil.which("npm") is None:
        return "npm absent"
    if not (browser_dir / "node_modules").is_dir():
        return "dépendances absentes (cd tests/browser && npm ci)"
    cache = (home or Path.home()) / ".cache" / "ms-playwright"
    if not glob.glob(str(cache / "firefox-*")):
        return "Firefox de Playwright absent (npx playwright install firefox)"
    return None


def build_steps(
    base: str = "master",
    rapide: bool = False,
    navigateur: bool = True,
    changed: list[str] | None = None,
    browser_reason: str | None = None,
) -> list[Step]:
    changed = changed_python_files(base) if changed is None else changed
    steps = []
    if changed:
        steps.append(Step("ruff (fichiers modifiés)", [*UV, "ruff", "check", "--force-exclude", *changed]))
    else:
        steps.append(Step("ruff (fichiers modifiés)", None, skip_reason="aucun fichier Python modifié"))
    steps.append(Step("documentation", [sys.executable, "scripts/check_docs.py"]))
    if rapide:
        return steps
    steps[:0] = [
        Step("ruff", [*UV, "ruff", "check", "."]),
        Step("mypy", [*UV, "mypy"]),
    ]
    steps.append(Step("pytest (Python et JavaScript)", [*UV, "pytest", "-q"]))
    if not navigateur:
        steps.append(Step("recette Firefox", None, skip_reason="--sans-navigateur"))
    else:
        reason = browser_skip_reason() if browser_reason is None else browser_reason
        steps.append(
            Step(
                "recette Firefox",
                ["npm", "test", "--", "--project=firefox"],
                cwd=BROWSER_DIR,
                skip_reason=reason or None,
            )
        )
    return steps


def run_step(step: Step) -> Result:
    if step.skip_reason is not None or step.cmd is None:
        return Result(step.name, IGNOREE, 0.0, step.skip_reason or "")
    print(f"\n==> {step.name} : {' '.join(step.cmd)}", flush=True)
    start = time.monotonic()
    try:
        code = subprocess.run(step.cmd, cwd=step.cwd, check=False).returncode
    except FileNotFoundError as exc:
        return Result(step.name, ECHEC, time.monotonic() - start, f"commande introuvable : {exc.filename}")
    status = OK if code == 0 else ECHEC
    return Result(step.name, status, time.monotonic() - start, "" if code == 0 else f"code {code}")


def summary(results: list[Result]) -> str:
    lines = ["", "Résumé"]
    for r in results:
        extra = f" ({r.detail})" if r.detail else ""
        lines.append(f"  {r.status:8} {r.name}{extra}" + (f"  {r.seconds:.0f} s" if r.status != IGNOREE else ""))
    failed = [r.name for r in results if r.status == ECHEC]
    lines.append("Contrôle en échec : " + ", ".join(failed) if failed else "Contrôle réussi.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rapide", action="store_true")
    parser.add_argument("--sans-navigateur", action="store_true")
    parser.add_argument("--base", default="master")
    args = parser.parse_args(argv)
    steps = build_steps(args.base, args.rapide, not args.sans_navigateur)
    results = [run_step(s) for s in steps]
    print(summary(results))
    return 1 if any(r.status == ECHEC for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
