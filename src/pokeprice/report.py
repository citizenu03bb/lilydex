"""
Report generation module: CSV, Excel (.xlsx), and CLI terminal summaries.
"""

from typing import List, Dict, Any
import pandas as pd
from tabulate import tabulate


def build_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Transforms raw pipeline records into a clean, presentation-ready DataFrame."""
    rows = []
    for r in records:
        price_info = r.get("price_info")
        ocr = r.get("ocr")
        
        row = {
            "Page": r.get("page_num", 1),
            "Position": r.get("position", 1),
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
    total_val = valid_prices.sum()
    foils_count = (df["Is_Foil"] == "Oui").sum()

    print("\n" + "=" * 70)
    print(" 📊 RÉSUMÉ DE LA COLLECTION POKÉMON")
    print("=" * 70)
    print(f" • Nombre total de cartes scannées : {total_cards}")
    print(f" • Cartes brillantes / Reverse     : {foils_count}")
    print(f" • VALEUR TOTALE ESTIMÉE           : {total_val:.2f} €")
    if "Etat" in df.columns and not df["Etat"].isna().all():
        counts = df["Etat"].value_counts().to_dict()
        dist_str = " | ".join(f"{k}: {v}" for k, v in counts.items() if k)
        print(f" • États de conservation constatés : {dist_str}")
    print("=" * 70)

    # Top valuable cards
    top = df.sort_values(by="Prix_Estime_EUR", ascending=False).head(10)
    top_cols = ["Page", "Position", "Identified_Name", "Extension", "Numero_Officiel", "Rarete", "Is_Foil", "Etat", "Prix_Estime_EUR"]
    top_display = top[[c for c in top_cols if c in top.columns]].copy()
    top_display.columns = ["P.", "Pos", "Nom", "Extension", "Réf", "Rareté", "Foil", "État", "Prix (€)"]

    print("\n🏆 TOP CARTES LES PLUS VALORISÉES :")
    print(tabulate(top_display, headers="keys", tablefmt="rounded_grid", showindex=False))

    # Cards not NM/EX
    if "Etat" in df.columns:
        worn = df[~df["Etat"].isin(["NM", "EX", "NM/EX", ""]) & df["Etat"].notna()]
        if not worn.empty:
            print("\n⚠️ CARTES AVEC DÉFAUTS OU USURE (Non NM/EX) :")
            worn_cols = ["Page", "Position", "Identified_Name", "Extension", "Numero_Officiel", "Etat", "Defauts", "Prix_Estime_EUR"]
            worn_display = worn[[c for c in worn_cols if c in worn.columns]].copy()
            worn_display.columns = ["P.", "Pos", "Nom", "Extension", "Réf", "État", "Défauts constatés", "Prix (€)"]
            print(tabulate(worn_display, headers="keys", tablefmt="rounded_grid", showindex=False))
    print("\n")
