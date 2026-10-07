import json
import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from pokeprice.library import build_library, consolidate, load_manifest
from pokeprice.report import read_report

NODE = (
    "node"
)


def inputs(tmp_path):
    image_dir = tmp_path / "photos"
    image_dir.mkdir()
    Image.new("RGB", (200, 200)).save(image_dir / "page.png")
    base = {
        "Page": 1,
        "Fichier_Image": "page.png",
        "Etat": "EX",
        "Prix_Reference_EUR": 1.0,
        "Statut_Identification": "confirmed",
        "Langue_Carte": "fr",
        "TCGdex_ID": "dp4-91",
        "Extension": "Duels au Sommets",
        "Numero_Officiel": "91/106",
        "Identified_Name": "Zarbi L",
        "OCR_Name": "Zarbi [L] NIV.18",
        "Grille_Lignes": 2,
        "Grille_Colonnes": 2,
        "Rotation": "0",
    }
    a = pd.DataFrame(
        [
            {**base, "Position": 1},
            {**base, "Position": 2},
            {
                **base,
                "Position": 3,
                "Identified_Name": "Évoli",
                "OCR_Name": "Evoli NIV.10",
                "TCGdex_ID": "pl2-59",
                "Numero_Officiel": "59/111",
                "Extension": "Rivaux Émergeants",
            },
            {
                **base,
                "Position": 4,
                "Statut_Identification": "unresolved",
                "Identified_Name": "À identifier",
                "OCR_Name": "Énergie",
                "TCGdex_ID": None,
            },
        ]
    )
    b = pd.DataFrame(
        [
            {**base, "Position": 1},
            {**base, "Position": 2, "Langue_Carte": "en", "Identified_Name": "Unown L"},
            {
                **base,
                "Position": 3,
                "TCGdex_ID": "dp5-89",
                "Identified_Name": "Fossile Dôme",
                "OCR_Name": "Fossile Dôme",
                "Numero_Officiel": "89/100",
            },
        ]
    )
    a.to_csv(tmp_path / "a.csv", index=False)
    b.to_csv(tmp_path / "b.csv", index=False)
    manifest = {
        "albums": [
            {"id": "a", "name": "Album A", "report": "a.csv", "photos": "photos"},
            {"id": "b", "name": "Album B", "report": "b.csv", "photos": "photos"},
        ]
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_counts_preserve_pockets_across_albums_and_languages(tmp_path):
    manifest = inputs(tmp_path)
    df, data = consolidate(load_manifest(manifest), tmp_path, include_images=False)
    assert len(df) == 7 and df.Exemplaire_ID.nunique() == 7
    french = [
        g
        for g in data["groups"]
        if g["name"] == "Zarbi L" and g["language"] == "fr" and g["confirmed"]
    ][0]
    assert french["quantity"] == 3
    assert {(c["album_id"], c["position"]) for c in french["copies"]} == {
        ("a", 1),
        ("a", 2),
        ("b", 1),
    }
    english = [g for g in data["groups"] if g["language"] == "en"][0]
    assert english["quantity"] == 1
    assert len([g for g in data["groups"] if not g["confirmed"]]) == 1


def test_library_search_updates_global_counts_and_album_filter(tmp_path):
    manifest = inputs(tmp_path)
    stats = build_library(manifest, tmp_path / "library")
    assert stats == {"copies": 7, "editions": 4, "unresolved": 1, "albums": 2}
    html = (tmp_path / "library.html").read_text()
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    actions = [
        {"field": "search", "value": "Zarbi L"},
        {"field": "album", "value": "b"},
        {"field": "album", "value": ""},
        {"field": "search", "value": "evoli"},
        {"field": "search", "value": "59/111"},
        {"field": "search", "value": "nothing matches"},
    ]
    result = subprocess.run(
        [NODE, str(Path(__file__).with_name("library_runtime.cjs"))],
        input=json.dumps({"script": script, "actions": actions}),
        text=True,
        capture_output=True,
        check=True,
    )
    states = json.loads(result.stdout)
    assert states[0]["summary"].startswith("7 exemplaires")
    # OCR aliases find the English-language printing as well, without merging it.
    assert states[1]["summary"].startswith("4 exemplaires · 2 éditions")
    assert states[2]["summary"].startswith("2 exemplaires · 2 éditions")
    assert states[4]["summary"].startswith("1 exemplaire · 1 édition")
    assert states[5]["summary"] == states[4]["summary"]
    assert states[6]["summary"].startswith("0 exemplaires")
    assert len(read_report(tmp_path / "library.csv")) == 7
    assert (
        "image"
        not in json.loads((tmp_path / "library.json").read_text())["groups"][0][
            "copies"
        ][0]
    )


def test_duplicate_reports_rejected_and_source_not_overwritten(tmp_path):
    manifest = inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["albums"][1]["report"] = "a.csv"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="dupliqué"):
        load_manifest(manifest)
    payload["albums"][1]["report"] = "b.csv"
    manifest.write_text(json.dumps(payload))
    before = (tmp_path / "a.csv").read_bytes()
    with pytest.raises(ValueError, match="distinct"):
        build_library(manifest, tmp_path / "a")
    assert (tmp_path / "a.csv").read_bytes() == before


def test_manual_editions_and_unresolved_pockets_are_not_merged(tmp_path):
    manifest = inputs(tmp_path)
    frame = pd.read_csv(tmp_path / "a.csv")
    frame["TCGdex_ID"] = None
    frame.loc[:1, "Nom_Verifie"] = "メガニウム LV.54"
    frame.loc[1, "Extension"] = "Different Japanese printing"
    frame.loc[2:, "Statut_Identification"] = "unresolved"
    frame.to_csv(tmp_path / "a.csv", index=False)
    _, data = consolidate(load_manifest(manifest)[:1], tmp_path, include_images=False)
    assert len(data["groups"]) == 4


def test_library_embedded_payload_escapes_script_injection(tmp_path):
    manifest = inputs(tmp_path)
    frame = pd.read_csv(tmp_path / "a.csv")
    frame.loc[0, "Identified_Name"] = "</script><script>alert(1)</script>"
    frame.to_csv(tmp_path / "a.csv", index=False)
    build_library(manifest, tmp_path / "library")
    html = (tmp_path / "library.html").read_text()
    assert "</script><script>alert" not in html
    assert "\\u003c/script\\u003e" in html


def test_single_zarbi_letter_does_not_match_extension_name(tmp_path):
    manifest = inputs(tmp_path)
    frame = pd.read_csv(tmp_path / "b.csv")
    frame.loc[2, ["Identified_Name", "OCR_Name", "TCGdex_ID", "Numero_Officiel"]] = [
        "Zarbi G",
        "Zarbi [G] NIV.17",
        "dp4-57",
        "57/106",
    ]
    frame.to_csv(tmp_path / "b.csv", index=False)
    build_library(manifest, tmp_path / "library")
    script = re.search(
        r"<script>(.*?)</script>", (tmp_path / "library.html").read_text(), re.S
    ).group(1)
    result = subprocess.run(
        [NODE, str(Path(__file__).with_name("library_runtime.cjs"))],
        input=json.dumps(
            {"script": script, "actions": [{"field": "search", "value": "Zarbi L"}]}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    state = json.loads(result.stdout)[1]
    assert state["summary"].startswith("4 exemplaires · 2 éditions")
    assert "Zarbi G" not in state["results"]
