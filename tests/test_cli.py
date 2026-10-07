import json
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image
from pokeprice import cli
from pokeprice.ocr import CardOCRResult
from pokeprice.report import read_report
from conftest import card


def scan_args(tmp_path, **extras):
    folder = tmp_path / "album"
    folder.mkdir(exist_ok=True)
    Image.new("RGB", (400, 600)).save(folder / "page.png")
    return SimpleNamespace(
        path=str(folder),
        output=str(tmp_path / "result.csv"),
        backend="ollama",
        model="mock",
        grid="2x2",
        rotate="0",
        inset=0.0,
        condition=None,
        save_crops=None,
        exclude=[],
        limit=0,
        retries=0,
        resume=False,
        **extras,
    )


def stub_setup(monkeypatch, provider, client):
    monkeypatch.setattr(cli, "get_ocr_provider", lambda **kw: provider)
    monkeypatch.setattr(cli, "TCGdexClient", lambda **kw: client)
    monkeypatch.setattr(
        "pokeprice.html_report.generate_html_report", lambda *a, **k: None
    )


def known():
    return CardOCRResult("Pikachu", 50, "1/100", False, "{}", "NM", occupied=True)


def empty():
    return CardOCRResult("", 0, "", False, "{}", occupied=False, status="empty")


def test_failure_preserves_results_and_resume_retries_only_failed(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    responses = iter([known(), RuntimeError("temporary error"), empty(), empty()])
    calls = []

    def extract(image):
        result = next(responses)
        calls.append(result)
        if isinstance(result, Exception):
            raise result
        return result

    provider = SimpleNamespace(model="mock", extract_card=extract)
    client = client_factory([card("set-1", "Pikachu", 1, 100, 50)])
    stub_setup(monkeypatch, provider, client)
    assert cli.cmd_scan(args) == 1
    df = read_report(args.output)
    assert list(df.Position) == [1, 2]
    assert df.loc[0, "Prix_Simule_EUR"] == 10
    assert df.loc[1, "Statut_Identification"] == "failed"
    checkpoint = json.loads((tmp_path / "result.checkpoint.json").read_text())
    assert len(checkpoint["completed"]) == 4
    args.resume = True
    provider.extract_card = lambda im: known()
    assert cli.cmd_scan(args) == 0
    df = read_report(args.output)
    assert list(df.Position) == [1, 2]
    assert list(df.Statut_Identification) == ["confirmed", "confirmed"]


def test_unidentified_occupied_pocket_preserved_and_override_applied(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    args.condition = "PO"
    responses = iter(
        [
            known(),
            CardOCRResult("", 0, "", False, "{}", occupied=True, status="unidentified"),
            empty(),
            empty(),
        ]
    )
    provider = SimpleNamespace(model="mock", extract_card=lambda im: next(responses))
    stub_setup(
        monkeypatch, provider, client_factory([card("set-1", "Pikachu", 1, 100, 50)])
    )
    assert cli.cmd_scan(args) == 0
    df = read_report(args.output)
    assert len(df) == 2
    assert df.loc[0, "Etat"] == "PO" and df.loc[0, "Prix_Simule_EUR"] == 1.5
    assert df.loc[1, "Statut_Identification"] == "unresolved"
    assert pd.isna(df.loc[1, "Prix_Simule_EUR"])
    assert (df.Grille_Lignes == 2).all() and (df.Rotation == 0).all()


def test_keyboard_interrupt_exports_completed_results(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    count = 0

    def extract(im):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt
        return known()

    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=extract),
        client_factory([card("set-1", "Pikachu", 1, 100, 50)]),
    )
    assert cli.cmd_scan(args) == 1
    assert len(read_report(args.output)) == 1
    assert (tmp_path / "result.xlsx").exists()


def test_bounded_retry_can_recover(tmp_path, monkeypatch, client_factory):
    args = scan_args(tmp_path)
    args.retries = 1
    responses = iter([RuntimeError("transient"), known(), empty(), empty(), empty()])

    def extract(im):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=extract),
        client_factory([card("set-1", "Pikachu", 1, 100, 50)]),
    )
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    assert cli.cmd_scan(args) == 0
    assert len(read_report(args.output)) == 1


def test_output_suffix_cannot_overwrite_csv_with_excel(tmp_path):
    with pytest.raises(ValueError):
        cli.output_paths(str(tmp_path / "unsafe"))


def test_resume_rejects_changed_settings(tmp_path, monkeypatch, client_factory):
    args = scan_args(tmp_path)
    provider = SimpleNamespace(model="mock", extract_card=lambda im: empty())
    stub_setup(monkeypatch, provider, client_factory([]))
    cli.cmd_scan(args)
    args.resume = True
    args.inset = 0.1
    with pytest.raises(ValueError, match="paramètres"):
        cli.cmd_scan(args)


def test_page_layout_failure_preserved(tmp_path, monkeypatch, client_factory):
    args = scan_args(tmp_path)
    args.grid = "auto"

    def detect(im):
        raise RuntimeError("unavailable layout")

    provider = SimpleNamespace(model="mock", detect_layout=detect)
    stub_setup(monkeypatch, provider, client_factory([]))
    assert cli.cmd_scan(args) == 1
    df = read_report(args.output)
    assert len(df) == 1 and df.loc[0, "Position"] == 0
    assert df.loc[0, "Statut_Identification"] == "failed"


def test_user_correction_used_without_replacing_ocr(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    file = tmp_path / "corrections.json"
    file.write_text(
        json.dumps(
            [
                {
                    "image_file": "page.png",
                    "position": 1,
                    "card_number": "58/127",
                    "source": "user",
                }
            ]
        )
    )
    args.corrections = str(file)
    responses = iter(
        [
            CardOCRResult(
                "Octillery NIV.40", 90, "73/147", False, "{}", "EX", occupied=True
            ),
            empty(),
            empty(),
            empty(),
        ]
    )
    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=lambda im: next(responses)),
        client_factory([card("pl1-58", "Octillery", 58, 127, 90)]),
    )
    assert cli.cmd_scan(args) == 0
    df = read_report(args.output)
    assert df.loc[0, "OCR_Number"] == "73/147"
    assert df.loc[0, "Numero_Officiel"] == df.loc[0, "Reference_Verifiee"] == "58/127"
    assert df.loc[0, "Statut_Identification"] == "confirmed"
    assert df.loc[0, "Prix_Simule_EUR"] == 8.5


def test_resume_keeps_page_and_position_order(tmp_path, monkeypatch, client_factory):
    args = scan_args(tmp_path)
    responses = iter([RuntimeError("temporary"), known(), empty(), empty()])

    def extract(image):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    provider = SimpleNamespace(model="mock", extract_card=extract)
    stub_setup(
        monkeypatch, provider, client_factory([card("set-1", "Pikachu", 1, 100, 50)])
    )
    assert cli.cmd_scan(args) == 1
    args.resume = True
    provider.extract_card = lambda image: known()
    assert cli.cmd_scan(args) == 0
    assert list(read_report(args.output).Position) == [1, 2]


def test_verified_name_and_edition_preserve_original_ocr(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    file = tmp_path / "corrections.json"
    file.write_text(
        json.dumps(
            [
                {
                    "image_file": "page.png",
                    "position": 1,
                    "card_name": "Zarbi K",
                    "card_number": "58/64",
                    "card_id": "neo3-58",
                }
            ]
        )
    )
    args.corrections = str(file)
    responses = iter(
        [
            CardOCRResult("Zarbi [K]", 40, "58/105", False, "{}", "EX", occupied=True),
            empty(),
            empty(),
            empty(),
        ]
    )
    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=lambda im: next(responses)),
        client_factory([card("neo3-58", "Zarbi K", 58, 64, 40)]),
    )
    assert cli.cmd_scan(args) == 0
    df = read_report(args.output)
    assert df.loc[0, "OCR_Name"] == "Zarbi [K]"
    assert df.loc[0, "OCR_Number"] == "58/105"
    assert df.loc[0, "Nom_Verifie"] == "Zarbi K"
    assert df.loc[0, "TCGdex_ID"] == "neo3-58"
    assert df.loc[0, "Statut_Identification"] == "confirmed"


def test_verified_edition_rejects_conflicting_fraction(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    file = tmp_path / "corrections.json"
    file.write_text(
        json.dumps(
            [
                {
                    "image_file": "page.png",
                    "position": 1,
                    "card_name": "Pikachu",
                    "card_number": "2/100",
                    "card_id": "set-1",
                }
            ]
        )
    )
    args.corrections = str(file)
    responses = iter([known(), empty(), empty(), empty()])
    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=lambda im: next(responses)),
        client_factory([card("set-1", "Pikachu", 1, 100, 50)]),
    )
    assert cli.cmd_scan(args) == 1
    assert read_report(args.output).loc[0, "Statut_Identification"] == "failed"


def test_verified_hp_preserves_ocr_and_removes_false_anomaly(
    tmp_path, monkeypatch, client_factory
):
    args = scan_args(tmp_path)
    file = tmp_path / "corrections.json"
    file.write_text(
        json.dumps(
            [
                {
                    "image_file": "page.png",
                    "position": 1,
                    "card_name": "Axoloto",
                    "card_number": "88/123",
                    "card_hp": 50,
                }
            ]
        )
    )
    args.corrections = str(file)
    responses = iter(
        [
            CardOCRResult("Axoloto", 60, "88/123", False, "{}", "EX", occupied=True),
            empty(),
            empty(),
            empty(),
        ]
    )
    stub_setup(
        monkeypatch,
        SimpleNamespace(model="mock", extract_card=lambda im: next(responses)),
        client_factory([card("hgss1-88", "Axoloto", 88, 123, 50)]),
    )
    assert cli.cmd_scan(args) == 0
    df = read_report(args.output)
    assert df.loc[0, "PV"] == 60 and df.loc[0, "PV_Verifie"] == 50
    assert df.loc[0, "Statut_Identification"] == "confirmed"
    assert df.loc[0, "Statut_Revision"] == "Simulation disponible"
