import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


def test_documentation_has_no_dead_link_date_or_private_pattern(monkeypatch):
    monkeypatch.setenv("POKEPRICE_PRIVATE_PATTERNS", "/nonexistent")
    errors, _ = check_docs.controler()
    assert errors == []


def test_living_pages_exist():
    for name in check_docs.PAGES_VIVANTES:
        assert (ROOT / name).is_file(), name


def test_dates_are_found_outside_measurement_lines_and_code():
    text = "\n".join([
        "Depuis le 16 octobre 2026, le serveur fait foi.",
        "Conditions de mesure : 31 cartes, octobre 2026.",
        "Mis à jour le 18 octobre 2026.",
        "Archive `daily-2026-10-17.zip`.",
        "```",
        "restore oci-daily-2026-10-17.zip",
        "```",
        "Mesuré le 2026-10-18.",
    ])
    errors = check_docs.dates_interdites(text)
    assert [e.split(":")[0] for e in errors] == ["1", "8"]


def test_links_to_ignored_folders_are_dead(tmp_path):
    page = check_docs.ROOT / "docs" / "page.md"
    errors = check_docs.liens_morts(page, "[preuve](../outputs/x.json) [ok](APP.md)")
    assert len(errors) == 1 and "ignoré par git" in errors[0]


def test_anchors_follow_github_slugs():
    assert check_docs.ancre("La langue : Tesseract face au contrôle de cohérence") == (
        "la-langue--tesseract-face-au-contrôle-de-cohérence"
    )
    page = check_docs.ROOT / "docs" / "JOURNAL.md"
    errors = check_docs.liens_morts(page, "[a](GLOSSAIRE.md#les-prix) [b](GLOSSAIRE.md#absente)")
    assert len(errors) == 1 and "ancre absente" in errors[0]


def test_private_patterns_are_reported(tmp_path, monkeypatch):
    patterns = tmp_path / "motifs.txt"
    patterns.write_text("# commentaire\nlilydex\\.duckdns\n")
    monkeypatch.setenv("POKEPRICE_PRIVATE_PATTERNS", str(patterns))
    assert [p.pattern for p in check_docs.motifs_prives()] == ["lilydex\\.duckdns"]


def test_command_reference_is_up_to_date():
    spec = importlib.util.spec_from_file_location("gen_commandes", ROOT / "scripts/gen_commandes.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (ROOT / "docs/COMMANDES.md").read_text(encoding="utf-8") == gen.generer(), (
        "Référence des commandes périmée : lancer python scripts/gen_commandes.py"
    )
