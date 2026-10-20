import json
from types import SimpleNamespace

import pytest
from PIL import Image

from pokeprice import cli
from pokeprice.energy_gate import MARGIN, EnergyGate, basic_energy, gated_note
from pokeprice.report import read_report
from conftest import card
from test_cli import known, scan_args, stub_setup


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ENERGY", (True, "")),
        ("Énergie", (True, "")),
        ("Énergie Psy", (True, "Psy")),
        ("Fighting Energy", (True, "Combat")),
        ("Énergie Obscurité", (True, "Obscurité")),
        ("Double Énergie Incolore", (False, "")),
        ("Énergie Sup", (False, "")),
        ("Récupération d'Énergie", (False, "")),
        ("Lainergie", (False, "")),
    ],
)
def test_basic_energy_names(name, expected):
    assert basic_energy(name) == expected


def unit(*values):
    torch = pytest.importorskip("torch")
    return torch.nn.functional.normalize(torch.tensor(values, dtype=torch.float), dim=-1)


def gate_for(query, refs, basic, types, count=20):
    # The bank repeats each reference so that it reaches the minimum size.
    vectors = unit(*refs).repeat(count, 1)
    return EnergyGate(
        lambda images: unit(query), vectors, basic * count, types * count
    )


def test_gate_needs_a_clear_margin_over_every_other_card():
    image = Image.new("RGB", (10, 10))
    energy, special = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    clear = gate_for([1.0, 0.1, 0.0], [energy, special], [True, False], ["Psy", ""])
    evidence = clear.check(image)
    assert evidence["gap"] >= MARGIN and evidence["type_proposal"] == "Psy"
    assert "Psy" in gated_note(evidence) and "sans lecture Gemini" in gated_note(evidence)
    close = gate_for([1.0, 0.9, 0.0], [energy, special], [True, False], ["Psy", ""])
    assert close.check(image) is None


def test_gate_stays_off_without_enough_references():
    gate = gate_for([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0]], [True, False], ["", ""], count=5)
    assert not gate.ready and gate.check(Image.new("RGB", (4, 4))) is None


def test_scan_skips_gemini_for_gated_pockets(tmp_path, monkeypatch, client_factory):
    args = scan_args(tmp_path, energy_gate=str(tmp_path / "inventory"))
    (tmp_path / "inventory").mkdir()
    (tmp_path / "inventory" / "collection.sqlite3").touch()
    calls = []

    def extract(image):
        calls.append(image)
        return known()

    evidence = {"gap": 0.2, "type_proposal": "Feu", "margin": MARGIN}
    checked = []

    def check(crop):
        checked.append(crop)
        return evidence if len(checked) == 1 else None

    gate = SimpleNamespace(ready=True, check=check)
    monkeypatch.setattr("pokeprice.energy_gate.from_store", lambda store: gate)
    monkeypatch.setattr("pokeprice.inventory.Store", lambda path: None)
    provider = SimpleNamespace(model="mock", extract_card=extract)
    stub_setup(monkeypatch, provider, client_factory([card("set-1", "Pikachu", 1, 100, 50)]))
    cli.cmd_scan(args)
    df = read_report(args.output)
    assert len(calls) == 3  # 2x2 grid: the first pocket was gated
    gated = df[df.Position == 1].iloc[0]
    assert gated.OCR_Name == "Énergie de base"
    assert gated.Statut_Identification == "unresolved"
    assert "Feu" in gated.Note_Verification
    checkpoint = json.loads((tmp_path / "result.checkpoint.json").read_text())
    assert checkpoint["settings"]["energy_gate"]["margin"] == MARGIN
