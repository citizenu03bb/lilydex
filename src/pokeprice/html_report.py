"""
HTML Interactive Report Generator for pokeprice.
Generates a responsive web report with embedded album crops and remote official images
with opt-in condition simulations and explicit unresolved-card review.
"""

import base64
import glob
import io
import json
import os
import math
from html import escape as html_escape
from urllib.parse import urlsplit
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd
from PIL import Image

from pokeprice.slicer import normalize_orientation, slice_grid
from pokeprice.report import (
    CONDITION_MULTIPLIERS,
    condition_multiplier,
    apply_pricing_and_anomalies,
)


def encode_image_base64(
    img: Image.Image, max_size: tuple = (400, 560), quality: int = 80
) -> str:
    """Resizes and encodes a PIL Image to a compact base64 JPEG data URI."""
    thumb = img.convert("RGB")
    thumb.thumbnail(max_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def text_value(value, default=""):
    return str(value) if pd.notna(value) else default


def number_value(value):
    try:
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def safe_url(value):
    url = text_value(value).strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def build_report_cards(df, album_dir, *, grid=None, rotation="auto", inset=0.02):
    """Embed the same per-page crop geometry used by the scanner."""
    df = apply_pricing_and_anomalies(df)
    files = sorted(
        p
        for p in Path(album_dir).iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    )
    by_name = {p.name: p for p in files}
    cache = {}
    cards = []
    for index, (_, row) in enumerate(df.iterrows()):
        page = int(row.get("Page", 1))
        pos = int(row.get("Position", 1))
        filename = text_value(row.get("Fichier_Image"))
        # An explicit filename never falls back to a different page photograph.
        path = (
            by_name.get(filename)
            if filename
            else (files[page - 1] if 0 < page <= len(files) else None)
        )
        crop = None
        if path and pos > 0:
            same_page = (
                df[df["Fichier_Image"] == filename]
                if filename and "Fichier_Image" in df
                else df[df["Page"] == page]
            )
            row_count = number_value(row.get("Grille_Lignes"))
            col_count = number_value(row.get("Grille_Colonnes"))
            if row_count and col_count:
                rows, cols = int(row_count), int(col_count)
            elif grid:
                rows, cols = grid
            else:
                # Compatibility for legacy reports; new scans always persist geometry.
                max_pos = int(same_page["Position"].max())
                if max_pos > 9:
                    raise ValueError(
                        "Grille inconnue : préciser la géométrie des pages à 12 cartes."
                    )
                rows, cols = (3, 3) if max_pos > 4 else (2, 2)
            rot = text_value(row.get("Rotation"), rotation) or rotation
            margin = number_value(row.get("Marge_Decoupe"))
            margin = margin if margin is not None else inset
            key = (str(path), rows, cols, rot, margin)
            if key not in cache:
                with Image.open(path) as image:
                    oriented = normalize_orientation(image, rot)
                    cache[key] = dict(slice_grid(oriented, rows, cols, margin))
            crop = cache[key].get(pos)
        grade = text_value(row.get("Etat"))
        mult = condition_multiplier(grade)
        status = text_value(row.get("Statut_Identification"), "confirmed")
        note = text_value(row.get("Note_Verification"))
        anomaly = text_value(row.get("Alerte_Incoherence"))
        cards.append(
            {
                "id": index,
                "page": page,
                "pos": pos,
                "image_file": filename,
                "ocr_name": text_value(row.get("OCR_Name")),
                "ocr_number": text_value(row.get("OCR_Number")),
                "pv": int(
                    number_value(row.get("PV_Verifie"))
                    if number_value(row.get("PV_Verifie")) is not None
                    else (number_value(row.get("PV")) or 0)
                ),
                "is_foil": text_value(row.get("Is_Foil")).lower() == "oui",
                "name": text_value(row.get("Identified_Name"), "À identifier"),
                "set_name": text_value(row.get("Extension")),
                "number": text_value(row.get("Numero_Officiel")),
                "rarity": text_value(row.get("Rarete")),
                "condition": grade,
                "condition_source": text_value(
                    row.get("Source_Etat"), "Inconnue (historique)"
                ),
                "price_date": text_value(row.get("Date_Prix")),
                "price_source": text_value(row.get("Source_Prix_EUR")),
                "decote_pct": int(round((1 - mult) * 100))
                if mult is not None
                else None,
                "flaws": text_value(row.get("Defauts")),
                "reference_price_eur": number_value(row.get("Prix_Reference_EUR")),
                "simulated_price_eur": number_value(row.get("Prix_Simule_EUR")),
                "trend_eur": number_value(row.get("Tendance_EUR")),
                "cardmarket_url": safe_url(row.get("Lien_Cardmarket")),
                "official_img": safe_url(row.get("Image_Officielle")),
                "real_crop_img": encode_image_base64(crop) if crop else "",
                "is_suspect": bool(anomaly),
                "counterfeit_warning": anomaly,
                "needs_review": text_value(row.get("Statut_Revision")) == "À vérifier",
                "price_missing": status == "confirmed"
                and number_value(row.get("Prix_Reference_EUR")) is None,
                "match_status": status,
                "verification_note": note,
            }
        )
    return cards


def generate_html_report(
    df,
    album_dir,
    output_html_path,
    title="Références de prix Album Pokémon",
    *,
    grid=None,
    rotation="auto",
    inset=0.02,
):
    cards = build_report_cards(df, album_dir, grid=grid, rotation=rotation, inset=inset)
    catalogue = sum(
        c["reference_price_eur"] or 0 for c in cards if c["match_status"] == "confirmed"
    )
    adjusted = sum(c["simulated_price_eur"] or 0 for c in cards)
    review_count = sum(c["needs_review"] for c in cards)
    html = _build_html_template(
        title,
        cards,
        catalogue,
        adjusted,
        sum(c["pos"] > 0 for c in cards),
        sum(c["is_foil"] for c in cards),
        review_count,
    )
    Path(output_html_path).write_text(html, encoding="utf-8")
    print(f"Rapport HTML : {output_html_path}")
    return str(output_html_path)


def _build_html_template(
    title: str,
    cards: list,
    total_val_cat: float,
    total_val_adjusted: float,
    total_cards: int,
    total_foils: int,
    total_suspect: int,
) -> str:
    cards_json = (
        json.dumps(cards, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    title = html_escape(title)
    coefficient_labels = " · ".join(
        f"{grade} × {mult:.2f}" for grade, mult in CONDITION_MULTIPLIERS.items()
    )
    simulated_count = sum(c["simulated_price_eur"] is not None for c in cards)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --surface: #1e293b;
      --surface-card: #243247;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.2);
      --green: #22c55e;
      --yellow: #eab308;
      --orange: #f97316;
      --red: #ef4444;
      --purple: #a855f7;
      --radius: 12px;
      --transition: 0.2s ease-in-out;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    [hidden] {{ display: none !important; }}
    .simulation-controls {{ margin-top: 18px; line-height: 1.6; }}
    .simulation-controls label {{ display: flex; align-items: center; gap: 10px; cursor: pointer; }}
    .simulation-controls input {{ accent-color: var(--accent); width: 18px; height: 18px; }}
    #simulationPanel {{ margin-top: 12px; border: 1px dashed var(--accent); }}
    .price-meta {{ font-size: 0.75rem; color: var(--text-muted); margin-top: 6px; overflow-wrap: anywhere; }}
    .simulation-price {{ margin-top: 10px; color: var(--text-muted); font-size: 0.85rem; }}

    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 80px;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px 20px;
    }}

    header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 28px 32px;
      margin-bottom: 24px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }}

    .header-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 24px;
    }}

    h1 {{
      font-size: 1.85rem;
      font-weight: 800;
      letter-spacing: -0.025em;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .badge-live {{
      font-size: 0.75rem;
      background: rgba(34, 197, 94, 0.2);
      color: #4ade80;
      border: 1px solid rgba(34, 197, 94, 0.4);
      padding: 4px 10px;
      border-radius: 999px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .alert-banner-top {{
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #fca5a5;
      font-size: 0.9rem;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}

    .stat-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 20px;
      backdrop-filter: blur(8px);
    }}

    .stat-label {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 6px;
    }}

    .stat-val {{
      font-size: 1.7rem;
      font-weight: 800;
      color: #ffffff;
    }}

    .stat-val.highlight {{
      color: #4ade80;
      text-shadow: 0 0 15px rgba(74, 222, 128, 0.3);
    }}

    .stat-sub {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 4px;
    }}

    /* Filter Toolbar */
    .toolbar {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      margin-bottom: 28px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 14px;
      position: sticky;
      top: 16px;
      z-index: 100;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
    }}

    .search-box {{
      flex: 1 1 240px;
      position: relative;
    }}

    .search-input {{
      width: 100%;
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px 10px 38px;
      color: #ffffff;
      font-size: 0.95rem;
      outline: none;
      transition: var(--transition);
    }}

    .search-input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }}

    .search-icon {{
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      pointer-events: none;
    }}

    .pill-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .filter-btn {{
      background: #0f172a;
      border: 1px solid var(--border);
      color: var(--text-muted);
      padding: 8px 14px;
      border-radius: 999px;
      font-size: 0.825rem;
      font-weight: 600;
      cursor: pointer;
      transition: var(--transition);
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .filter-btn:hover {{
      color: #ffffff;
      border-color: #64748b;
    }}

    .filter-btn.active {{
      background: var(--accent);
      color: #0f172a;
      border-color: var(--accent);
      box-shadow: 0 2px 10px var(--accent-glow);
    }}

    .filter-btn.btn-suspect.active {{
      background: var(--red);
      color: #ffffff;
      border-color: var(--red);
      box-shadow: 0 2px 10px rgba(239, 68, 68, 0.4);
    }}

    .sort-select {{
      background: #0f172a;
      border: 1px solid var(--border);
      color: #ffffff;
      padding: 9px 14px;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      outline: none;
      cursor: pointer;
    }}

    /* Card Grid */
    .card-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 20px;
    }}

    .card-item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: transform var(--transition), border-color var(--transition), box-shadow var(--transition);
    }}

    .card-item:hover {{
      transform: translateY(-3px);
      border-color: #64748b;
      box-shadow: 0 12px 24px -10px rgba(0, 0, 0, 0.5);
    }}

    .card-item.suspect-card {{
      border: 2px solid var(--red);
      box-shadow: 0 0 15px rgba(239, 68, 68, 0.25);
    }}

    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
    }}

    .card-title {{
      font-size: 1.15rem;
      font-weight: 700;
      color: #ffffff;
      line-height: 1.25;
    }}

    .card-sub {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    .pos-badge {{
      font-size: 0.75rem;
      font-weight: 700;
      background: rgba(148, 163, 184, 0.15);
      color: #cbd5e1;
      padding: 3px 8px;
      border-radius: 6px;
      white-space: nowrap;
    }}

    /* Side-by-Side Visual Comparison Container */
    .comparison-container {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      background: #0f172a;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }}

    .image-box {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      position: relative;
    }}

    .image-tag {{
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 2px 6px;
      border-radius: 4px;
    }}

    .tag-real {{
      background: rgba(56, 189, 248, 0.2);
      color: #38bdf8;
    }}

    .tag-official {{
      background: rgba(168, 85, 247, 0.2);
      color: #c084fc;
    }}

    .card-img {{
      width: 100%;
      aspect-ratio: 2.5 / 3.5;
      object-fit: cover;
      border-radius: 6px;
      border: 1px solid #334155;
      background: #1e293b;
      cursor: zoom-in;
      transition: transform var(--transition);
    }}

    .card-img:hover {{
      transform: scale(1.02);
    }}

    /* Badges */
    .badges-row {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 4px;
    }}

    .badge {{
      font-size: 0.75rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}

    .badge-nm {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); }}
    .badge-ex {{ background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }}
    .badge-gd {{ background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); }}
    .badge-lp {{ background: rgba(249, 115, 22, 0.2); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.4); }}
    .badge-pl {{ background: rgba(249, 115, 22, 0.25); color: #f97316; border: 1px solid rgba(249, 115, 22, 0.5); }}
    .badge-po {{ background: rgba(239, 68, 68, 0.25); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.5); }}

    .badge-foil {{
      background: linear-gradient(135deg, rgba(234, 179, 8, 0.3) 0%, rgba(249, 115, 22, 0.3) 100%);
      color: #fde047;
      border: 1px solid rgba(234, 179, 8, 0.5);
    }}

    .badge-pv {{
      background: rgba(239, 68, 68, 0.15);
      color: #fca5a5;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }}

    .badge-suspect {{
      background: rgba(239, 68, 68, 0.2);
      color: #fca5a5;
      border: 1px solid rgba(239, 68, 68, 0.5);
      font-weight: 800;
    }}

    /* Price Section */
    .price-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      margin-top: 6px;
      padding-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
    }}

    .price-block {{
      display: flex;
      flex-direction: column;
    }}

    .price-tag-reference {{
      font-size: 1.4rem;
      font-weight: 800;
      color: #4ade80;
      line-height: 1.1;
    }}

    .price-tag-reference.zero-suspect {{
      color: #ef4444;
      text-decoration: line-through;
    }}

    .price-caption {{
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    .cm-link {{
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 5px 11px;
      border-radius: 6px;
      background: rgba(56, 189, 248, 0.1);
      transition: var(--transition);
    }}

    .cm-link:hover {{
      background: rgba(56, 189, 248, 0.2);
    }}

    .flaw-box {{
      font-size: 0.75rem;
      background: rgba(249, 115, 22, 0.1);
      border-left: 3px solid var(--orange);
      color: #fed7aa;
      padding: 6px 10px;
      border-radius: 4px;
      margin-top: 2px;
    }}

    .counterfeit-banner {{
      font-size: 0.78rem;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fca5a5;
      padding: 8px 10px;
      border-radius: 6px;
      line-height: 1.35;
    }}

    /* Dialog */
    dialog {{
      margin: auto;
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      max-width: 900px;
      width: 90vw;
      color: #ffffff;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
    }}

    dialog::backdrop {{
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(6px);
    }}

    .dialog-content {{
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}

    .dialog-images {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}

    .dialog-images img {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid #334155;
    }}

    .btn-close {{
      align-self: flex-end;
      background: #334155;
      color: #ffffff;
      border: none;
      padding: 8px 16px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
    }}

    .btn-close:hover {{
      background: #475569;
    }}
  </style>
</head>
<body>

  <div class="container">
    <header>
      <div class="header-top">
        <div>
          <h1>🎴 {title}</h1>
        </div>
      </div>

      {
        f'''<div class="alert-banner-top">
        <span style="font-size: 1.4rem;">⚠️</span>
        <div>
          <strong>Alerte de collection : {total_suspect} carte(s) à vérifier</strong><br>
          La somme des références inclut uniquement les identités confirmées avec un prix disponible. Les états restent à confirmer ; les entrées à vérifier sont exclues de la simulation.
        </div>
      </div>'''
        if total_suspect > 0
        else ""
    }

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Somme des références de prix</div>
          <div class="stat-val highlight">{total_val_cat:.2f} €</div>
          <div class="stat-sub">Identités confirmées · Références TCGdex · Prix de vente à vérifier</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Cartes scannées</div>
          <div class="stat-val">{total_cards}</div>
          <div class="stat-sub">{total_foils} brillantes ({
        int(round(total_foils / total_cards * 100)) if total_cards else 0
    }%)</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">À vérifier</div>
          <div class="stat-val" style="color: {
        "#ef4444" if total_suspect > 0 else "#94a3b8"
    };">{total_suspect}</div>
          <div class="stat-sub">{
        "⚠️ À vérifier en priorité"
        if total_suspect > 0
        else "Références disponibles · États à confirmer"
    }</div>
        </div>
      </div>
      <div class="simulation-controls">
        <label for="simulationToggle">
          <input type="checkbox" id="simulationToggle" aria-controls="simulationPanel">
          Afficher une simulation selon l’état
        </label>
        <div id="simulationPanel" class="stat-card" hidden>
          <div class="stat-label">Total simulé</div>
          <div class="stat-val">{total_val_adjusted:.2f} €</div>
          <p class="stat-sub">Hypothèse indicative, sans calibration sur des ventes comparables. Le prix de référence n’est pas une cote NM garantie.</p>
          <p class="stat-sub">Coefficients appliqués : {
        coefficient_labels
    }. NM/EX utilise EX.</p>
          <p class="stat-sub">{simulated_count} entrée(s) incluses ; {
        len(cards) - simulated_count
    } exclue(s) : identité non confirmée, prix ou état inconnu, ou incohérence. Les états inclus restent à confirmer.</p>
        </div>
      </div>
    </header>

    <!-- Toolbar Filters -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" class="search-input" placeholder="Rechercher un Pokémon, une extension, un numéro...">
      </div>

      <div class="pill-filters">
        <button class="filter-btn active" data-filter="all">Toutes ({
        len(cards)
    })</button>
        <button class="filter-btn" data-filter="valuable">⭐ Référence > 10 €</button>
        <button class="filter-btn" data-filter="foil">✨ Brillantes ({
        total_foils
    })</button>
        <button class="filter-btn" data-filter="worn">⚠️ Abîmées (PO/PL)</button>
        <button class="filter-btn" data-filter="nm-ex">🛡️ NM / EX</button>
        {
        f'<button class="filter-btn btn-suspect" data-filter="suspect">⚠️ À vérifier ({total_suspect})</button>'
        if total_suspect > 0
        else ""
    }
        <button class="filter-btn" data-filter="missing-price">Prix indisponibles</button>
      </div>

      <select id="sortSelect" class="sort-select">
        <option value="price-desc">Prix de référence : Décroissant</option>
        <option value="price-asc">Prix de référence : Croissant</option>
        <option value="simulation-desc" data-simulation-option hidden disabled>Simulation : Décroissant</option>
        <option value="simulation-asc" data-simulation-option hidden disabled>Simulation : Croissant</option>
        <option value="page-pos">Ordre du classeur (Page/Pos)</option>
        <option value="name">Nom alphabétique (A-Z)</option>
      </select>
    </div>

    <!-- Cards Grid -->
    <main id="cardsGrid" class="card-grid">
      <!-- Injected via JavaScript -->
    </main>
  </div>

  <!-- Zoom Lightbox Dialog -->
  <dialog id="zoomDialog">
    <div class="dialog-content">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <h2 id="modalTitle" style="font-size: 1.4rem;">Détail de la carte</h2>
        <button id="modalCloseBtn" class="btn-close">Fermer ✕</button>
      </div>
      <div class="dialog-images">
        <div>
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 8px;">📸 Photo réelle du classeur</div>
          <img id="modalRealImg" src="" alt="Photo réelle">
        </div>
        <div>
          <div style="font-weight: 700; color: #c084fc; margin-bottom: 8px;">🖼️ Visuel officiel HD (TCGdex)</div>
          <img id="modalOfficialImg" src="" alt="Visuel officiel">
        </div>
      </div>
      <div id="modalDetails" style="font-size: 0.95rem; color: #cbd5e1; line-height: 1.6;"></div>
    </div>
  </dialog>

  <script>
    const CARDS = {cards_json};
    let currentFilter = 'all';
    let currentSort = 'price-desc';
    let searchQuery = '';
    let simulationEnabled = false;
    let activeCardId = null;

    const gridEl = document.getElementById('cardsGrid');
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const zoomDialog = document.getElementById('zoomDialog');
    const modalCloseBtn = document.getElementById('modalCloseBtn');
    const simulationToggle = document.getElementById('simulationToggle');
    const simulationPanel = document.getElementById('simulationPanel');
    const simulationOptions = document.querySelectorAll('[data-simulation-option]');

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }})[char]);
    }}
    function formatPrice(value) {{
      return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) + ' €' : 'Indisponible';
    }}

    function referencePrice(card) {{
      return card.match_status === 'confirmed' ? card.reference_price_eur : null;
    }}
    function conditionLabel(card) {{
      return card.condition_source === 'IA' ? 'État estimé par IA — à confirmer' : 'État fourni ou historique — à confirmer';
    }}
    function priceProvenance(card) {{
      return 'Source : TCGdex / Cardmarket' + (card.price_source ? ' · ' + card.price_source : ' · champ non renseigné') +
        ' · Date : ' + (card.price_date || 'non renseignée');
    }}

    function getConditionClass(cond) {{
      const c = (cond || '').toUpperCase();
      if (c === 'NM') return 'badge-nm';
      if (c === 'EX' || c === 'NM/EX') return 'badge-ex';
      if (c === 'GD') return 'badge-gd';
      if (c === 'LP') return 'badge-lp';
      if (c === 'PL') return 'badge-pl';
      if (c === 'PO') return 'badge-po';
      return 'badge-ex';
    }}

    function renderCards() {{
      let filtered = CARDS.filter(c => {{
        if (searchQuery) {{
          const q = searchQuery.toLowerCase();
          const matchName = c.name.toLowerCase().includes(q) || c.ocr_name.toLowerCase().includes(q);
          const matchSet = c.set_name.toLowerCase().includes(q);
          const matchNum = c.number.includes(q) || c.ocr_number.includes(q);
          if (!matchName && !matchSet && !matchNum) return false;
        }}

        if (currentFilter === 'valuable') return c.match_status === 'confirmed' && c.reference_price_eur > 10.0;
        if (currentFilter === 'foil') return c.is_foil;
        if (currentFilter === 'worn') return ['PL', 'PO'].includes(c.condition.toUpperCase());
        if (currentFilter === 'nm-ex') return ['NM', 'EX', 'NM/EX'].includes(c.condition.toUpperCase());
        if (currentFilter === 'suspect') return c.needs_review;
        if (currentFilter === 'missing-price') return c.price_missing;
        return true;
      }});

      filtered.sort((a, b) => {{
        if (currentSort === 'price-desc') return (referencePrice(b) ?? -Infinity) - (referencePrice(a) ?? -Infinity);
        if (currentSort === 'price-asc') return (referencePrice(a) ?? Infinity) - (referencePrice(b) ?? Infinity);
        if (simulationEnabled && currentSort === 'simulation-desc') return (b.simulated_price_eur ?? -Infinity) - (a.simulated_price_eur ?? -Infinity);
        if (simulationEnabled && currentSort === 'simulation-asc') return (a.simulated_price_eur ?? Infinity) - (b.simulated_price_eur ?? Infinity);
        if (currentSort === 'page-pos') return a.page - b.page || a.pos - b.pos;
        if (currentSort === 'name') return a.name.localeCompare(b.name);
        return 0;
      }});

      if (filtered.length === 0) {{
        gridEl.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; color: var(--text-muted);">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">🔍</div>
          <div style="font-size: 1.2rem; font-weight: 600;">Aucune carte ne correspond à ces critères</div>
        </div>`;
        return;
      }}

      gridEl.innerHTML = filtered.map(raw => {{
        const c = {{ ...raw }};
        for (const key of Object.keys(c)) if (typeof c[key] === 'string') c[key] = escapeHtml(c[key]);
        const condClass = getConditionClass(c.condition);
        const hasWarning = c.needs_review;
        const officialFallback = c.official_img;

        return `
          <div class="card-item ${{hasWarning ? 'suspect-card' : ''}}">
            <div class="card-header">
              <div>
                <div class="card-title">${{c.name}}</div>
                <div class="card-sub">${{c.set_name}} • ${{c.number || 'Réf inconnue'}}</div>
              </div>
              <span class="pos-badge">P.${{c.page}} #${{c.pos}}</span>
            </div>

            <div class="comparison-container" onclick="openZoom(${{c.id}})">
              <div class="image-box">
                <span class="image-tag tag-real">📸 Réelle</span>
                <img class="card-img" src="${{c.real_crop_img}}" alt="${{c.name}} réelle" loading="lazy">
              </div>
              <div class="image-box">
                <span class="image-tag tag-official">🖼️ Officielle</span>
                <img class="card-img" src="${{officialFallback}}" alt="Visuel officiel indisponible" loading="lazy">
              </div>
            </div>

            <div class="badges-row">
              <span class="badge ${{condClass}}">${{c.condition || 'État inconnu'}} · à confirmer</span>
              ${{c.is_foil ? '<span class="badge badge-foil">✨ Foil / Reverse</span>' : ''}}
              ${{c.pv > 0 ? `<span class="badge badge-pv">${{c.pv}} PV</span>` : ''}}
              ${{c.match_status === 'confirmed' ? '<span class="badge">✓ Identité confirmée</span>' : ''}}
              ${{c.price_missing ? '<span class="badge">Prix indisponible</span>' : ''}}
              ${{hasWarning ? '<span class="badge badge-suspect">⚠️ À vérifier</span>' : ''}}
              <span class="badge" style="background: rgba(148, 163, 184, 0.1); color: #cbd5e1;">${{c.rarity || 'Commune'}}</span>
            </div>

            <div class="price-meta">${{conditionLabel(c)}}</div>
            ${{c.flaws && c.flaws.toLowerCase() !== 'none visible' && c.flaws.toLowerCase() !== 'none' ? `
              <div class="flaw-box">
                <strong>Défauts :</strong> ${{c.flaws}}
              </div>
            ` : ''}}

            ${{hasWarning && c.counterfeit_warning ? `
              <div class="counterfeit-banner">
                <strong>⚠️ Alerte collectionneur :</strong><br>${{c.counterfeit_warning}}
              </div>
            ` : ''}}

            ${{c.verification_note ? `<div class="flaw-box"><strong>Vérification :</strong> ${{c.verification_note}}</div>` : ''}}
            <div class="price-row">
              <div class="price-block">
                <div class="price-tag-reference">${{formatPrice(c.reference_price_eur)}}</div>
                <div class="price-caption">${{c.match_status === 'confirmed' ? 'Prix de référence TCGdex' : 'Référence proposée — à vérifier'}}</div>
                <div class="price-meta">${{priceProvenance(c)}}</div>
                ${{simulationEnabled ? `<div class="simulation-price"><strong>Montant simulé :</strong> ${{formatPrice(c.simulated_price_eur)}}<br>${{c.decote_pct !== null ? 'Hypothèse : −' + c.decote_pct + '% · état à confirmer' : 'État inconnu : simulation indisponible'}}</div>` : ''}}
              </div>
              ${{c.cardmarket_url ? `
                <a class="cm-link" href="${{c.cardmarket_url}}" target="_blank" rel="noopener">
                  Cardmarket ↗
                </a>
              ` : ''}}
            </div>
          </div>
        `;
      }}).join('');
    }}

    function renderModal(cardId) {{
      const card = CARDS.find(c => c.id === cardId);
      if (!card) return;

      document.getElementById('modalTitle').textContent = `${{card.name}} (${{card.set_name}} #${{card.number}})`;
      document.getElementById('modalRealImg').src = card.real_crop_img;
      document.getElementById('modalOfficialImg').src = card.official_img;

      const safe = {{ ...card }};
      for (const key of Object.keys(safe)) if (typeof safe[key] === 'string') safe[key] = escapeHtml(safe[key]);
      document.getElementById('modalDetails').innerHTML = `
        <p><strong>Emplacement classeur :</strong> Page ${{safe.page}}, Position ${{safe.pos}} (fichier : <code>${{safe.image_file}}</code>)</p>
        <p><strong>Points de Vie (PV) :</strong> ${{safe.pv || 'N/A'}} | <strong>Finition :</strong> ${{safe.is_foil ? 'Brillante (Holo/Reverse)' : 'Non-brillante'}}</p>
        <p><strong>${{conditionLabel(safe)}} :</strong> <span style="font-weight:700;">${{safe.condition || 'État inconnu'}}</span> ${{safe.flaws ? '— <em>' + safe.flaws + '</em>' : ''}}</p>
        <p><strong>${{safe.match_status === 'confirmed' ? 'Prix de référence TCGdex' : 'Référence proposée — à vérifier'}} :</strong> ${{formatPrice(card.reference_price_eur)}}<br><span class="price-meta">${{priceProvenance(safe)}}</span></p>
        ${{simulationEnabled ? `<p><strong>Montant simulé :</strong> ${{formatPrice(card.simulated_price_eur)}} · ${{safe.decote_pct !== null ? 'hypothèse de décote : −' + safe.decote_pct + '%' : 'état inconnu'}}. État à confirmer.</p>` : ''}}
        ${{safe.counterfeit_warning ? `<div style="background: rgba(239, 68, 68, 0.2); border: 1px solid rgba(239, 68, 68, 0.5); padding: 10px; border-radius: 8px; margin-top: 10px; color: #fca5a5;"><strong>⚠️ Vérification nécessaire :</strong><br>${{safe.counterfeit_warning}}</div>` : ''}}
      `;

    }}

    function openZoom(cardId) {{
      activeCardId = cardId;
      renderModal(cardId);
      zoomDialog.showModal();
    }}

    simulationToggle.addEventListener('change', () => {{
      simulationEnabled = simulationToggle.checked;
      simulationPanel.hidden = !simulationEnabled;
      simulationOptions.forEach(option => {{
        option.hidden = !simulationEnabled;
        option.disabled = !simulationEnabled;
      }});
      if (!simulationEnabled && currentSort.startsWith('simulation-')) {{
        currentSort = 'price-desc';
        sortSelect.value = currentSort;
      }}
      renderCards();
      if (zoomDialog.open && activeCardId !== null) renderModal(activeCardId);
    }});

    modalCloseBtn.addEventListener('click', () => zoomDialog.close());
    zoomDialog.addEventListener('click', (e) => {{
      if (e.target === zoomDialog) zoomDialog.close();
    }});

    searchInput.addEventListener('input', (e) => {{
      searchQuery = e.target.value.trim();
      renderCards();
    }});

    sortSelect.addEventListener('change', (e) => {{
      currentSort = e.target.value;
      renderCards();
    }});

    filterBtns.forEach(btn => {{
      btn.addEventListener('click', () => {{
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        renderCards();
      }});
    }});

    // Initial render
    simulationToggle.checked = false;
    renderCards();
  </script>
</body>
</html>"""
