"""
Report generation module: CSV, Excel (.xlsx), and CLI terminal summaries.
"""

from typing import List, Dict, Any
import pandas as pd
from tabulate import tabulate


import re

CONDITION_MULTIPLIERS = {
    "NM": 1.00,
    "EX": 0.85,
    "GD": 0.70,
    "LP": 0.55,
    "PL": 0.40,
    "PO": 0.15,
}


def normalize_report_columns(df):
    """Read old exports without retaining misleading price names in new reports."""
    df = df.copy()
    for old, current in (
        ("Prix_Estime_EUR", "Prix_Reference_EUR"),
        ("Prix_Catalogue_EUR", "Prix_Reference_EUR"),
        ("Prix_Ajuste_EUR", "Prix_Simule_EUR"),
        ("Decote_Etat", "Hypothese_Decote_Etat"),
    ):
        if old in df:
            if current not in df:
                df = df.rename(columns={old: current})
            else:
                df = df.drop(columns=[old])
    return df


def condition_multiplier(condition):
    """Unknown grades remain unknown; combined grades use the conservative value."""
    parts = str(condition or "").strip().upper().split("/")
    if any(part not in CONDITION_MULTIPLIERS for part in parts):
        return None
    return min(CONDITION_MULTIPLIERS[part] for part in parts)


def assess_card_anomalies(row):
    """Return evidence to review, never a counterfeit diagnosis from a sleeve photo."""
    warnings = []
    ext = str(row.get("Extension", "")).lower()
    num = str(row.get("Numero_Officiel", ""))
    is_foil = str(row.get("Is_Foil", "")).lower() == "oui"
    vintage_sets = [
        ("base", 102, 16),
        ("jungle", 64, 16),
        ("fossil", 62, 15),
        ("rocket", 82, 17),
        ("neo genesis", 111, 19),
    ]
    for token, count, end in vintage_sets:
        match = re.fullmatch(r"(\d+)/" + str(count), num)
        if token in ext and match and 1 <= int(match.group(1)) <= end and not is_foil:
            warnings.append(
                {
                    "code": "HOLO_UNCERTAIN",
                    "message": "Incohérence Holo : cette référence est holographique. Vérifier le reflet et la référence sur la carte.",
                }
            )
            break
    hp = row.get("PV_Verifie")
    if pd.isna(hp):
        hp = row.get("PV")
    official_hp = row.get("PV_Officiel")
    if pd.notna(hp) and pd.notna(official_hp):
        try:
            if int(hp) > 0 and int(hp) != int(official_hp):
                warnings.append(
                    {
                        "code": "HP_MISMATCH",
                        "message": f"Incohérence PV : lecture {int(hp)}, référence officielle {int(official_hp)}. Vérification nécessaire.",
                    }
                )
        except (TypeError, ValueError):
            pass
    return warnings


def detect_card_anomaly(row: Dict[str, Any]) -> str:
    return " ".join(w["message"] for w in assess_card_anomalies(row))


def apply_pricing_and_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_report_columns(df)
    if "Prix_Reference_EUR" not in df:
        df["Prix_Reference_EUR"] = float("nan")
    df["Prix_Reference_EUR"] = pd.to_numeric(df["Prix_Reference_EUR"], errors="coerce")
    discounts, coefficients, adjusted, suspects, alerts, revisions = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for _, row in df.iterrows():
        grade = row.get("Etat", "")
        mult = condition_multiplier(grade if pd.notna(grade) else "")
        warnings = assess_card_anomalies(row.to_dict())
        message = " ".join(w["message"] for w in warnings)
        status = str(row.get("Statut_Identification", "confirmed"))
        price = row["Prix_Reference_EUR"]
        available = (
            pd.notna(price)
            and status == "confirmed"
            and mult is not None
            and not warnings
        )
        discounts.append(
            f"Hypothèse : -{round((1 - mult) * 100)}% ({grade})"
            if mult is not None
            else "État à vérifier"
        )
        coefficients.append(mult)
        adjusted.append(round(float(price) * mult, 2) if available else float("nan"))
        suspects.append("Oui" if warnings else "Non")
        alerts.append(message)
        revisions.append(
            "À vérifier"
            if status != "confirmed" or warnings
            else "Prix indisponible"
            if pd.isna(price)
            else "État à confirmer"
            if mult is None
            else "Simulation disponible"
        )
    df["Hypothese_Decote_Etat"] = discounts
    df["Coefficient_Simulation_Etat"] = coefficients
    if "Source_Etat" not in df:
        df["Source_Etat"] = "Inconnue (historique)"
    df["Etat_A_Confirmer"] = "Oui"
    df["Prix_Simule_EUR"] = adjusted
    df["Est_Suspecte"] = suspects
    df["Alerte_Incoherence"] = alerts
    df["Statut_Revision"] = revisions
    return df


def build_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Transforms raw pipeline records into a clean, presentation-ready DataFrame."""
    rows = []
    for r in records:
        price_info = r.get("price_info")
        ocr = r.get("ocr")

        row = {
            "Page": r.get("page_num", 1),
            "Position": r.get("position", 1),
            "Fichier_Image": r.get("image_file", ""),
            "OCR_Name": ocr.name if ocr else "",
            "OCR_Number": ocr.card_number if ocr else "",
            "PV": ocr.hp if (ocr and ocr.hp > 0) else None,
            "Is_Foil": "Oui" if (ocr and ocr.is_holo) else "Non",
            "Identified_Name": price_info.name
            if price_info
            else ((ocr.name if ocr else "") or "À identifier"),
            "Extension": price_info.set_name if price_info else "",
            "Numero_Officiel": price_info.card_number if price_info else "",
            "Rarete": price_info.rarity if price_info else "",
            "Etat": r.get("condition")
            if r.get("condition") is not None
            else (ocr.condition if ocr else ""),
            "Source_Etat": "Paramètre utilisateur"
            if r.get("condition") is not None
            else "IA",
            "Defauts": (ocr.flaws if (ocr and ocr.flaws) else r.get("flaws", "")),
            "Prix_Reference_EUR": price_info.cm_recommended_eur if price_info else None,
            "Tendance_EUR": price_info.cm_trend_eur if price_info else None,
            "Tendance_Holo_EUR": price_info.cm_trend_holo_eur if price_info else None,
            "Moyenne_EUR": price_info.cm_avg_eur if price_info else None,
            "TCGPlayer_USD": price_info.tcg_market_usd if price_info else None,
            "Lien_Cardmarket": (
                f"https://www.cardmarket.com/fr/Pokemon/Products/Singles/{price_info.cardmarket_id}"
                if (price_info and price_info.cardmarket_id)
                else ""
            ),
            "Image_Officielle": (
                f"{price_info.image_url}/high.webp"
                if (price_info and price_info.image_url)
                else ""
            ),
            "Statut_Identification": r.get("match_status")
            or (
                "confirmed"
                if price_info and price_info.match_method == "exact"
                else "review"
                if price_info
                else "failed"
                if ocr and ocr.status == "failed"
                else "unresolved"
            ),
            "Methode_Correspondance": price_info.match_method if price_info else "",
            "Note_Verification": r.get("verification_note", "")
            or (ocr.error if ocr else ""),
            "TCGdex_ID": price_info.card_id if price_info else "",
            "PV_Officiel": price_info.hp if price_info else None,
            "Langue_Carte": price_info.language if price_info else "",
            "Date_Prix": price_info.pricing_updated if price_info else "",
            "Source_Prix_EUR": price_info.price_field if price_info else "",
            "Reference_Verifiee": r.get("verified_number", ""),
            "Nom_Verifie": r.get("verified_name", ""),
            "PV_Verifie": r.get("verified_hp"),
            "Source_Correction": r.get("correction_source", ""),
            "Grille_Lignes": r.get("grid_rows"),
            "Grille_Colonnes": r.get("grid_cols"),
            "Rotation": r.get("rotation", ""),
            "Marge_Decoupe": r.get("inset"),
            "OCR_Brut": ocr.raw_response if ocr else "",
            "Modele_OCR": r.get("model", ""),
            "Moteur_OCR": r.get("backend", ""),
            "Crop_Path": r.get("crop_path", ""),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "Page",
                "Position",
                "Fichier_Image",
                "Identified_Name",
                "Is_Foil",
                "Etat",
                "Prix_Reference_EUR",
            ]
        )
    df = apply_pricing_and_anomalies(df)
    return df


def safe_spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def spreadsheet_dataframe(df):
    # Prefix only risky text. Numbers and missing values keep their native types.
    return df.apply(lambda column: column.map(safe_spreadsheet_text))


def export_csv(df: pd.DataFrame, filepath: str) -> None:
    spreadsheet_dataframe(normalize_report_columns(df)).to_csv(
        filepath, index=False, encoding="utf-8-sig"
    )


def read_report(filepath):
    """Undo only our reversible formula protection when re-importing reports."""
    from pathlib import Path

    df = (
        pd.read_excel(filepath)
        if Path(filepath).suffix.lower() == ".xlsx"
        else pd.read_csv(filepath)
    )

    def unprotect(v):
        if (
            isinstance(v, str)
            and v.startswith("'")
            and v[1:].lstrip().startswith(("=", "+", "-", "@"))
        ):
            return v[1:]
        return v

    return normalize_report_columns(df.apply(lambda column: column.map(unprotect)))


def export_excel(df: pd.DataFrame, filepath: str) -> None:
    from openpyxl.styles import Alignment, Font
    import math

    df = normalize_report_columns(df)
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        # Put actionable prices beside identity; retain all provenance columns.
        leading = [
            c
            for c in (
                "Page",
                "Position",
                "Identified_Name",
                "Statut_Identification",
                "Prix_Reference_EUR",
                "Etat",
                "Source_Etat",
                "Etat_A_Confirmer",
                "Note_Verification",
            )
            if c in df
        ]
        ordered = leading + [c for c in df if c not in leading]
        spreadsheet_dataframe(df[ordered]).to_excel(
            writer, index=False, sheet_name="Cartes Pokemon"
        )
        ws = writer.sheets["Cartes Pokemon"]
        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions
        compact_widths = {
            "Page": 7,
            "Position": 9,
            "Identified_Name": 24,
            "Statut_Identification": 22,
            "Prix_Reference_EUR": 22,
            "Prix_Simule_EUR": 20,
            "Etat": 8,
            "Source_Etat": 24,
            "Etat_A_Confirmer": 22,
            "Note_Verification": 38,
        }
        for cells in ws.columns:
            header = cells[0].value
            width = compact_widths.get(
                header,
                min(max(max(len(str(c.value or "")) for c in cells) + 2, 12), 36),
            )
            ws.column_dimensions[cells[0].column_letter].width = width
            for c in cells:
                c.alignment = Alignment(vertical="top", wrap_text=True)
                c.font = Font(name="Arial", size=10, bold=c.row == 1)
                if (
                    c.row > 1
                    and isinstance(c.value, (float, int))
                    and "EUR" in str(header)
                ):
                    c.number_format = '#,##0.00" €"'
        ws.row_dimensions[1].height = 30
        for cells in ws.columns:
            if cells[0].value in (
                "OCR_Brut",
                "Image_Officielle",
                "Lien_Cardmarket",
                "Crop_Path",
                "Prix_Simule_EUR",
                "Coefficient_Simulation_Etat",
                "Hypothese_Decote_Etat",
            ):
                ws.column_dimensions[cells[0].column_letter].hidden = True
        for row in range(2, ws.max_row + 1):
            lines = max(
                (
                    math.ceil(
                        len(str(c.value or ""))
                        / max(ws.column_dimensions[c.column_letter].width - 2, 1)
                    )
                    for c in ws[row]
                    if not ws.column_dimensions[c.column_letter].hidden
                ),
                default=1,
            )
            ws.row_dimensions[row].height = max(24, lines * 13 + 5)


def print_summary(df: pd.DataFrame) -> None:
    """Prints a styled terminal summary of the collection."""
    if df.empty:
        print("\nAucune carte à afficher.")
        return
    df = apply_pricing_and_anomalies(df)

    total_cards = (df["Position"] > 0).sum() if "Position" in df else len(df)
    valid_prices = df["Prix_Reference_EUR"].fillna(0.0)
    confirmed = (
        df.get("Statut_Identification", pd.Series("confirmed", index=df.index))
        == "confirmed"
    )
    total_val_cat = valid_prices[confirmed].sum()

    review_count = (
        df.get("Statut_Revision", pd.Series("Simulation disponible", index=df.index))
        == "À vérifier"
    ).sum()
    foils_count = (df["Is_Foil"] == "Oui").sum()

    print("\n" + "=" * 70)
    print(" 📊 RÉSUMÉ DE LA COLLECTION POKÉMON")
    print("=" * 70)
    print(f" • Nombre total de cartes scannées     : {total_cards}")
    print(f" • Entrées à vérifier                  : {review_count}")
    print(f" • Cartes brillantes / Reverse         : {foils_count}")
    print(f" • SOMME DES RÉFÉRENCES (identités confirmées) : {total_val_cat:.2f} €")
    print(
        " • Prix de référence TCGdex ; états non vérifiés. Simulation facultative dans le HTML."
    )
    if "Etat" in df.columns and not df["Etat"].isna().all():
        counts = df["Etat"].value_counts().to_dict()
        dist_str = " | ".join(f"{k}: {v}" for k, v in counts.items() if k)
        print(f" • États proposés, à confirmer     : {dist_str}")

    if "Est_Suspecte" in df.columns and (df["Est_Suspecte"] == "Oui").any():
        nb_suspect = (df["Est_Suspecte"] == "Oui").sum()
        print(f" • ⚠️ INCOHÉRENCES À VÉRIFIER   : {nb_suspect} détectée(s)")
    print("=" * 70)

    # Top valuable cards
    price_col = "Prix_Reference_EUR"
    top = df.loc[confirmed].sort_values(by=price_col, ascending=False).head(10)
    top_cols = [
        "Page",
        "Position",
        "Identified_Name",
        "Extension",
        "Numero_Officiel",
        "Rarete",
        "Is_Foil",
        "Etat",
        "Prix_Reference_EUR",
    ]
    top_display = top[[c for c in top_cols if c in top.columns]].copy()
    top_display.rename(
        columns={
            "Page": "P.",
            "Position": "Pos",
            "Identified_Name": "Nom",
            "Numero_Officiel": "Réf",
            "Rarete": "Rareté",
            "Etat": "État à confirmer",
            "Prix_Reference_EUR": "Référence (€)",
            "Prix_Simule_EUR": "Simulation (€)",
        },
        inplace=True,
    )

    print("\n🏆 TOP PRIX DE RÉFÉRENCE (IDENTITÉS CONFIRMÉES) :")
    print(
        tabulate(top_display, headers="keys", tablefmt="rounded_grid", showindex=False)
    )

    # Suspect cards section
    if "Est_Suspecte" in df.columns:
        suspects = df[df["Est_Suspecte"] == "Oui"]
        if not suspects.empty:
            print("\n⚠️ INCOHÉRENCES À VÉRIFIER :")
            s_cols = [
                "Page",
                "Position",
                "Identified_Name",
                "Extension",
                "Numero_Officiel",
                "Etat",
                "Alerte_Incoherence",
            ]
            s_disp = suspects[[c for c in s_cols if c in suspects.columns]].copy()
            s_disp.rename(
                columns={
                    "Page": "P.",
                    "Position": "Pos",
                    "Identified_Name": "Nom",
                    "Numero_Officiel": "Réf",
                    "Etat": "État",
                    "Alerte_Incoherence": "Diagnostic / Incohérence",
                },
                inplace=True,
            )
            print(
                tabulate(
                    s_disp, headers="keys", tablefmt="rounded_grid", showindex=False
                )
            )

    # Cards not NM/EX
    if "Etat" in df.columns:
        worn = df[~df["Etat"].isin(["NM", "EX", "NM/EX", ""]) & df["Etat"].notna()]
        if not worn.empty:
            print("\n⚠️ CARTES AVEC DÉFAUTS OU USURE (Non NM/EX) :")
            worn_cols = [
                "Page",
                "Position",
                "Identified_Name",
                "Extension",
                "Numero_Officiel",
                "Etat",
                "Defauts",
                "Prix_Reference_EUR",
            ]
            worn_display = worn[[c for c in worn_cols if c in worn.columns]].copy()
            worn_display.rename(
                columns={
                    "Page": "P.",
                    "Position": "Pos",
                    "Identified_Name": "Nom",
                    "Numero_Officiel": "Réf",
                    "Etat": "État à confirmer",
                    "Defauts": "Défauts détectés",
                    "Prix_Reference_EUR": "Référence (€)",
                },
                inplace=True,
            )
            print(
                tabulate(
                    worn_display,
                    headers="keys",
                    tablefmt="rounded_grid",
                    showindex=False,
                )
            )
    print("\n")
