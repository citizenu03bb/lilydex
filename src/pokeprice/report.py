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


def detect_card_anomaly(row: Dict[str, Any]) -> str:
    """
    Detects logical contradictions indicating a likely counterfeit card or metadata anomaly.
    Returns explanation string or empty string if no anomaly.
    """
    ext = str(row.get("Extension", "")).lower()
    num = str(row.get("Numero_Officiel", "") or row.get("OCR_Number", "")).strip()
    is_foil = str(row.get("Is_Foil", "")).lower() == "oui"
    pv = row.get("PV")
    name = str(row.get("Identified_Name", "") or row.get("OCR_Name", ""))

    # 1. Base Set 1999 (1/102 to 16/102) Holo-only printed flat non-holo
    if "base" in ext:
        match = re.search(r"^(\d+)/102", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 16 and not is_foil:
                return (
                    f"Incohérence Holo : Dans le Set de Base officiel (1999), {name} ({num}) "
                    f"n'a été imprimé qu'en version brillante holographique. "
                    f"Un exemplaire mat non-brillant est une contrefaçon / proxy d'époque."
                )

    # 2. Jungle 2000 (1/64 to 16/64) Holo-only printed flat non-holo
    if "jungle" in ext:
        match = re.search(r"^(\d+)/64", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 16 and not is_foil:
                return (
                    f"Incohérence Holo : Dans le set Jungle officiel (2000), les cartes 1 à 16 ({name} {num}) "
                    f"sont obligatoirement brillantes (Holo). Les versions non-brillantes portent les numéros 17 à 32."
                )

    # 3. Fossile 2000 (1/62 to 15/62) Holo-only printed flat non-holo
    if "fossil" in ext or "fossile" in ext:
        match = re.search(r"^(\d+)/62", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 15 and not is_foil:
                return (
                    f"Incohérence Holo : Dans le set Fossile (2000), les cartes 1 à 15 ({name} {num}) "
                    f"sont obligatoirement brillantes (Holo). Les versions non-brillantes portent les numéros 16 à 30."
                )

    # 4. Team Rocket 2000 (1/82 to 17/82) Holo-only printed flat non-holo
    if "rocket" in ext:
        match = re.search(r"^(\d+)/82", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 17 and not is_foil:
                return (
                    f"Incohérence Holo : Dans le set Team Rocket (2000), les cartes 1 à 17 ({name} {num}) "
                    f"sont obligatoirement Holo (les versions non-holo portent les numéros 18 à 30)."
                )

    # 5. Neo Genesis 2001 (1/111 to 19/111) Holo-only printed flat non-holo
    if "neo genesis" in ext:
        match = re.search(r"^(\d+)/111", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 19 and not is_foil:
                return (
                    f"Incohérence Holo : Dans le set Neo Genesis (2001), les cartes 1 à 19 ({name} {num}) "
                    f"sont obligatoirement Holo."
                )

    # 6. Impossible HP for Vintage / DP era
    if pv is not None and pd.notna(pv):
        try:
            pv_int = int(pv)
            vintage_or_dp = any(k in ext for k in [
                "base", "jungle", "fossile", "fossil", "rocket", "neo", "aquapolis",
                "expedition", "diamant", "perle", "platine", "dp", "ex"
            ])
            if vintage_or_dp and pv_int > 160:
                return (
                    f"Incohérence PV : {pv_int} PV est anormalement élevé pour cette série ancienne "
                    f"(PV max officiel ~150-160, typique des contrefaçons fantaisistes)."
                )
        except (ValueError, TypeError):
            pass

    return ""


def apply_pricing_and_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes condition discounts, adjusted prices, and flags counterfeit risks.
    """
    # Ensure base price column exists
    if "Prix_Estime_EUR" not in df.columns:
        df["Prix_Estime_EUR"] = 0.0
    df["Prix_Estime_EUR"] = df["Prix_Estime_EUR"].fillna(0.0)

    # Prix catalogue
    df["Prix_Catalogue_EUR"] = df["Prix_Estime_EUR"]

    decote_list = []
    prix_ajuste_list = []
    suspect_list = []
    alerte_list = []

    for idx, row in df.iterrows():
        cond = str(row.get("Etat", "NM/EX")).strip().upper()
        # Fallback multi-char condition
        if "/" in cond:
            cond = cond.split("/")[0]
        mult = CONDITION_MULTIPLIERS.get(cond, 0.85)
        decote_pct = int(round((1.0 - mult) * 100))
        decote_str = f"-{decote_pct}% ({cond})" if decote_pct > 0 else f"0% ({cond})"
        decote_list.append(decote_str)

        anomaly = detect_card_anomaly(row.to_dict())
        cat_price = float(row.get("Prix_Catalogue_EUR", 0.0) or 0.0)

        if anomaly:
            suspect_list.append("Oui")
            alerte_list.append(anomaly)
            # If suspected fake vintage holo, set real adjusted price to 0 €
            if "incohérence holo" in anomaly.lower() or "contrefaçon" in anomaly.lower():
                prix_ajuste_list.append(0.0)
            else:
                prix_ajuste_list.append(round(cat_price * mult, 2))
        else:
            suspect_list.append("Non")
            alerte_list.append("")
            prix_ajuste_list.append(round(cat_price * mult, 2))

    df["Decote_Etat"] = decote_list
    df["Prix_Ajuste_EUR"] = prix_ajuste_list
    df["Est_Suspecte"] = suspect_list
    df["Alerte_Incoherence"] = alerte_list

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
            "Identified_Name": price_info.name if price_info else "Non trouvée",
            "Extension": price_info.set_name if price_info else "",
            "Numero_Officiel": price_info.card_number if price_info else "",
            "Rarete": price_info.rarity if price_info else "",
            "Etat": (ocr.condition if (ocr and ocr.condition) else r.get("condition", "NM/EX")),
            "Defauts": (ocr.flaws if (ocr and ocr.flaws) else r.get("flaws", "")),
            "Prix_Estime_EUR": price_info.cm_recommended_eur if price_info else 0.0,
            "Tendance_EUR": price_info.cm_trend_eur if price_info else 0.0,
            "Tendance_Holo_EUR": price_info.cm_trend_holo_eur if price_info else None,
            "Moyenne_EUR": price_info.cm_avg_eur if price_info else 0.0,
            "TCGPlayer_USD": price_info.tcg_market_usd if price_info else None,
            "Lien_Cardmarket": (
                f"https://www.cardmarket.com/fr/Pokemon/Products/Singles/{price_info.cardmarket_id}"
                if (price_info and price_info.cardmarket_id)
                else ""
            ),
            "Image_Officielle": (f"{price_info.image_url}/high.webp" if (price_info and price_info.image_url) else "")
        }
        rows.append(row)
        
    df = pd.DataFrame(rows)
    df = apply_pricing_and_anomalies(df)
    return df


def export_csv(df: pd.DataFrame, filepath: str) -> None:
    """Exports data to CSV format."""
    df.to_csv(filepath, index=False, encoding="utf-8-sig")


def export_excel(df: pd.DataFrame, filepath: str) -> None:
    """Exports data to formatted Excel (.xlsx) with auto-column widths."""
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cartes Pokemon")
        worksheet = writer.sheets["Cartes Pokemon"]
        
        # Format column widths
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 10)


def print_summary(df: pd.DataFrame) -> None:
    """Prints a styled terminal summary of the collection."""
    if df.empty:
        print("\nAucune carte à afficher.")
        return

    total_cards = len(df)
    valid_prices = df["Prix_Estime_EUR"].fillna(0.0)
    total_val_cat = valid_prices.sum()
    
    if "Prix_Ajuste_EUR" in df.columns:
        total_val_ajust = df["Prix_Ajuste_EUR"].fillna(0.0).sum()
        decote_globale_pct = ((1.0 - (total_val_ajust / total_val_cat)) * 100) if total_val_cat > 0 else 0
    else:
        total_val_ajust = total_val_cat
        decote_globale_pct = 0.0

    foils_count = (df["Is_Foil"] == "Oui").sum()

    print("\n" + "=" * 70)
    print(" 📊 RÉSUMÉ DE LA COLLECTION POKÉMON")
    print("=" * 70)
    print(f" • Nombre total de cartes scannées     : {total_cards}")
    print(f" • Cartes brillantes / Reverse         : {foils_count}")
    print(f" • VALEUR CATALOGUE (Référence NM)     : {total_val_cat:.2f} €")
    print(f" • VALEUR RÉELLE AJUSTÉE (État réel)   : {total_val_ajust:.2f} €  (-{decote_globale_pct:.1f}% décote globale)")
    if "Etat" in df.columns and not df["Etat"].isna().all():
        counts = df["Etat"].value_counts().to_dict()
        dist_str = " | ".join(f"{k}: {v}" for k, v in counts.items() if k)
        print(f" • États de conservation constatés     : {dist_str}")
    
    if "Est_Suspecte" in df.columns and (df["Est_Suspecte"] == "Oui").any():
        nb_suspect = (df["Est_Suspecte"] == "Oui").sum()
        print(f" • ⚠️ CARTES SUSPECTES / CONTREFAÇONS   : {nb_suspect} détectée(s)")
    print("=" * 70)

    # Top valuable cards
    price_col = "Prix_Ajuste_EUR" if "Prix_Ajuste_EUR" in df.columns else "Prix_Estime_EUR"
    top = df.sort_values(by=price_col, ascending=False).head(10)
    top_cols = ["Page", "Position", "Identified_Name", "Extension", "Numero_Officiel", "Rarete", "Is_Foil", "Etat", "Prix_Catalogue_EUR", "Prix_Ajuste_EUR"]
    top_display = top[[c for c in top_cols if c in top.columns]].copy()
    top_display.rename(columns={
        "Page": "P.", "Position": "Pos", "Identified_Name": "Nom", "Numero_Officiel": "Réf",
        "Rarete": "Rareté", "Etat": "État", "Prix_Catalogue_EUR": "Cat. (€)", "Prix_Ajuste_EUR": "Ajusté (€)"
    }, inplace=True)

    print("\n🏆 TOP CARTES LES PLUS VALORISÉES (VALEUR RÉELLE AJUSTÉE) :")
    print(tabulate(top_display, headers="keys", tablefmt="rounded_grid", showindex=False))

    # Suspect cards section
    if "Est_Suspecte" in df.columns:
        suspects = df[df["Est_Suspecte"] == "Oui"]
        if not suspects.empty:
            print("\n⚠️ CARTES SUSPECTES OU INCOHÉRENCES DÉTECTÉES :")
            s_cols = ["Page", "Position", "Identified_Name", "Extension", "Numero_Officiel", "Etat", "Alerte_Incoherence"]
            s_disp = suspects[[c for c in s_cols if c in suspects.columns]].copy()
            s_disp.rename(columns={"Page": "P.", "Position": "Pos", "Identified_Name": "Nom", "Numero_Officiel": "Réf", "Etat": "État", "Alerte_Incoherence": "Diagnostic / Incohérence"}, inplace=True)
            print(tabulate(s_disp, headers="keys", tablefmt="rounded_grid", showindex=False))

    # Cards not NM/EX
    if "Etat" in df.columns:
        worn = df[~df["Etat"].isin(["NM", "EX", "NM/EX", ""]) & df["Etat"].notna()]
        if not worn.empty:
            print("\n⚠️ CARTES AVEC DÉFAUTS OU USURE (Non NM/EX) :")
            worn_cols = ["Page", "Position", "Identified_Name", "Extension", "Numero_Officiel", "Etat", "Defauts", "Prix_Catalogue_EUR", "Prix_Ajuste_EUR"]
            worn_display = worn[[c for c in worn_cols if c in worn.columns]].copy()
            worn_display.rename(columns={"Page": "P.", "Position": "Pos", "Identified_Name": "Nom", "Numero_Officiel": "Réf", "Etat": "État", "Defauts": "Défauts constatés", "Prix_Catalogue_EUR": "Cat. (€)", "Prix_Ajuste_EUR": "Ajusté (€)"}, inplace=True)
            print(tabulate(worn_display, headers="keys", tablefmt="rounded_grid", showindex=False))
    print("\n")
