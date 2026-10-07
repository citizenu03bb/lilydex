import base64
import io
import json
import re
from html.parser import HTMLParser

import pandas as pd
import pytest
from PIL import Image
from pokeprice.html_report import generate_html_report


def data(html):
    return json.loads(re.search(r"const CARDS = (.*);\n", html).group(1))


def rows(rows=3, cols=3, **extras):
    return pd.DataFrame(
        [
            {
                "Page": 1,
                "Position": p,
                "Fichier_Image": "page.png",
                "OCR_Name": f"Card {p}",
                "Identified_Name": f"Card {p}",
                "Etat": "EX",
                "Prix_Estime_EUR": 10.0,
                "Statut_Identification": "confirmed",
                "Grille_Lignes": rows,
                "Grille_Colonnes": cols,
                "Rotation": "0",
                "Marge_Decoupe": 0.0,
                **extras,
            }
            for p in range(1, rows * cols + 1)
        ]
    )


@pytest.mark.parametrize("geometry", [(3, 3), (4, 3), (3, 4), (1, 1)])
def test_all_scan_crops_in_report(tmp_path, geometry):
    nr, nc = geometry
    Image.new("RGB", (nc * 100, nr * 100)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    generate_html_report(rows(nr, nc), str(tmp_path), str(output))
    cards = data(output.read_text())
    assert len(cards) == nr * nc
    for c in cards:
        decoded = Image.open(
            io.BytesIO(base64.b64decode(c["real_crop_img"].split(",")[1]))
        )
        assert decoded.size == (100, 100)


def test_rotation_and_inset_reused(tmp_path):
    Image.new("RGB", (400, 600)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    generate_html_report(
        rows(1, 1, Rotation="90", Marge_Decoupe=0.1), str(tmp_path), str(output)
    )
    crop = Image.open(
        io.BytesIO(
            base64.b64decode(data(output.read_text())[0]["real_crop_img"].split(",")[1])
        )
    )
    # Rotation gives 600x400, inset gives 480x320, thumbnail gives 400x267.
    assert crop.size == (400, 267)


def test_missing_filename_does_not_show_another_card(tmp_path):
    Image.new("RGB", (200, 300)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    generate_html_report(
        rows(1, 1, Fichier_Image="missing.png"), str(tmp_path), str(output)
    )
    assert data(output.read_text())[0]["real_crop_img"] == ""


def test_injection_is_text_and_urls_are_validated(tmp_path):
    Image.new("RGB", (200, 300)).save(tmp_path / "page.png")
    payload = "</script><script>alert(1)</script><img src=x onerror=alert(2)>"
    output = tmp_path / "report.html"
    generate_html_report(
        rows(
            1,
            1,
            Identified_Name=payload,
            Defauts=payload,
            Note_Verification=payload,
            Date_Prix=payload,
            Source_Prix_EUR=payload,
            Lien_Cardmarket="javascript:alert(1)",
            Image_Officielle="data:text/html,bad",
        ),
        str(tmp_path),
        str(output),
        title=payload,
    )
    html = output.read_text()

    class Scripts(HTMLParser):
        count = 0

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.count += 1

    parser = Scripts()
    parser.feed(html)
    assert parser.count == 1
    c = data(html)[0]
    assert c["name"] == payload
    assert c["cardmarket_url"] == c["official_img"] == ""
    states = run_interactions(
        html, [{"type": "zoom", "id": 0}, {"type": "toggle", "value": True}]
    )
    for state in states:
        assert "<script>alert(1)</script>" not in state["grid"] + state["modal"]
        assert "&lt;script&gt;" in state["grid"]


def test_missing_prices_and_unresolved_totals(tmp_path):
    Image.new("RGB", (200, 300)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    df = rows(1, 1, Prix_Estime_EUR=None, Statut_Identification="unresolved")
    generate_html_report(df, str(tmp_path), str(output))
    html = output.read_text()
    c = data(html)[0]
    assert c["reference_price_eur"] is None and c["simulated_price_eur"] is None
    assert c["needs_review"]
    assert ": NaN" not in html


def run_interactions(html, actions):
    """Execute the generated JavaScript; use actual markup for initial DOM attributes."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise report interactions")

    class Markup(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = {}
            self.filters = []
            self.options = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.elements[attrs["id"]] = attrs
            if "filter-btn" in attrs.get("class", "").split():
                self.filters.append(attrs)
            if "data-simulation-option" in attrs:
                self.options.append(attrs)

    markup = Markup()
    markup.feed(html)
    assert "checked" not in markup.elements["simulationToggle"]
    payload = {
        "script": re.search(r"<script>(.*?)</script>", html, re.S).group(1),
        "elements": markup.elements,
        "filters": markup.filters,
        "options": markup.options,
        "actions": actions,
    }
    completed = subprocess.run(
        [node, str(Path(__file__).with_name("html_runtime.cjs"))],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_simulation_opt_in_and_modal_follow_toggle(tmp_path):
    Image.new("RGB", (200, 300)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    generate_html_report(
        rows(
            1,
            1,
            Etat="PO",
            Source_Etat="IA",
            Date_Prix="2026-10-04",
            Source_Prix_EUR="trend",
        ),
        str(tmp_path),
        str(output),
    )
    html = output.read_text()
    assert (
        "Écart avec le catalogue" not in html and "Estimation après décote" not in html
    )
    assert "Somme des références de prix" in html and "Total simulé" in html
    states = run_interactions(
        html,
        [
            {"type": "zoom", "id": 0},
            {"type": "toggle", "value": True},
            {"type": "sort", "value": "simulation-desc"},
            {"type": "toggle", "value": False},
        ],
    )
    assert states[0]["panelHidden"] and all(
        o["hidden"] and o["disabled"] for o in states[0]["options"]
    )
    assert "10.00 €" in states[0]["grid"] and "Montant simulé" not in states[0]["grid"]
    assert "État estimé par IA — à confirmer" in states[0]["grid"]
    assert "2026-10-04" in states[0]["grid"] and "trend" in states[0]["grid"]
    assert "Montant simulé" not in states[1]["modal"]
    assert (
        not states[2]["panelHidden"]
        and "1.50 €" in states[2]["grid"]
        and "1.50 €" in states[2]["modal"]
    )
    assert all(not o["hidden"] and not o["disabled"] for o in states[2]["options"])
    assert states[4]["panelHidden"] and states[4]["sort"] == "price-desc"
    assert (
        "Montant simulé" not in states[4]["grid"]
        and "Montant simulé" not in states[4]["modal"]
    )


def test_reference_sort_filter_and_simulated_sort_are_distinct(tmp_path):
    Image.new("RGB", (200, 300)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    df = rows(1, 3, Source_Etat="IA")
    df["Identified_Name"] = [
        "Large reference",
        "Small reference",
        "Unconfirmed proposal",
    ]
    df["Prix_Estime_EUR"] = [100, 20, 1000]
    df["Etat"] = ["PO", "NM", "NM"]
    df["Statut_Identification"] = ["confirmed", "confirmed", "review"]
    generate_html_report(df, str(tmp_path), str(output))
    states = run_interactions(
        output.read_text(),
        [
            {"type": "toggle", "value": True},
            {"type": "sort", "value": "simulation-desc"},
            {"type": "filter", "value": "valuable"},
            {"type": "filter", "value": "suspect"},
            {"type": "search", "value": "no matching name"},
        ],
    )
    assert (
        states[0]["grid"].index("Large reference")
        < states[0]["grid"].index("Small reference")
        < states[0]["grid"].index("Unconfirmed proposal")
    )
    assert states[2]["grid"].index("Small reference") < states[2]["grid"].index(
        "Large reference"
    )
    assert (
        "Large reference" in states[3]["grid"]
        and "Unconfirmed proposal" not in states[3]["grid"]
    )
    assert (
        "Unconfirmed proposal" in states[4]["grid"]
        and "Large reference" not in states[4]["grid"]
    )
    assert "Aucune carte" in states[5]["grid"]


def test_verified_identity_without_price_is_not_unverified(tmp_path):
    Image.new("RGB", (100, 100)).save(tmp_path / "page.png")
    output = tmp_path / "report.html"
    generate_html_report(
        rows(
            1,
            1,
            Prix_Estime_EUR=None,
            Note_Verification="Référence corrigée par le propriétaire : 91/106",
        ),
        str(tmp_path),
        str(output),
    )
    html = output.read_text()
    card = data(html)[0]
    assert card["match_status"] == "confirmed"
    assert card["price_missing"] and not card["needs_review"]
    state = run_interactions(html, [])[0]
    assert (
        "Identité confirmée" in state["grid"] and "Prix indisponible" in state["grid"]
    )
    assert "⚠️ À vérifier" not in state["grid"]
