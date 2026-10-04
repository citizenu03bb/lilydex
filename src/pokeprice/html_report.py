"""
HTML Interactive Report Generator for pokeprice.
Generates a standalone, responsive, modern web report comparing real album crops
with official TCGdex HD card illustrations side-by-side.
"""

import base64
import glob
import io
import json
import os
import re
from pathlib import Path
from typing import Optional

import pandas as pd
from PIL import Image

from pokeprice.slicer import normalize_orientation, slice_grid


def encode_image_base64(img: Image.Image, max_size: tuple = (400, 560), quality: int = 80) -> str:
    """Resizes and encodes a PIL Image to a compact base64 JPEG data URI."""
    thumb = img.copy()
    thumb.thumbnail(max_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def detect_counterfeit_risk(row: pd.Series) -> Optional[str]:
    """Detects logical contradictions indicating a likely vintage counterfeit or proxy."""
    name = str(row.get("Identified_Name", "")).lower()
    ext = str(row.get("Extension", "")).lower()
    num = str(row.get("Numero_Officiel", ""))
    is_foil = str(row.get("Is_Foil", "")).lower() == "oui"
    
    # 1. Base Set 1999 Holo-only cards (1/102 to 16/102) printed in flat non-holo
    if "base" in ext and not is_foil:
        match = re.search(r"^(\d+)/102", num)
        if match:
            card_num = int(match.group(1))
            if 1 <= card_num <= 16:
                return (
                    f"Incohérence Holo : Dans le Set de Base officiel (1999), {row.get('Identified_Name')} "
                    f"({num}) n'a été imprimé qu'en version brillante holographique étoilée. "
                    f"Un exemplaire mat non-brillant est très probablement une fausse carte d'époque (proxy / contrefaçon de cour d'école)."
                )

    # 2. Jungle (1/64 to 16/64) or Fossil (1/62 to 15/62) holo numbers with non-holo
    # (Note: Jungle/Fossil have non-holo versions with different numbers e.g. 17-64, handled by matcher)
    
    return None


def generate_html_report(
    df: pd.DataFrame,
    album_dir: str,
    output_html_path: str,
    title: str = "Catalogue & Valorisation Album Pokémon"
) -> str:
    """
    Slices album pages on the fly, links official TCGdex visuals, and builds a standalone HTML report.
    """
    patterns = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG"]
    image_files = []
    for pat in patterns:
        image_files.extend(glob.glob(os.path.join(album_dir, pat)))
    image_files = sorted(list(set(image_files)))

    # Filter out album cover if 29 files (28 album pages + 1 cover)
    # The first file is typically the cover if there are 29 images
    if len(image_files) == 29:
        cover_file = image_files[0]
        album_pages = image_files[1:]
    else:
        album_pages = image_files

    # Pre-slice and cache crops for each page
    page_crops_map = {}
    print(f"📦 Génération des aperçus visuels pour l'album ({len(album_pages)} pages)...")
    for p_idx, page_path in enumerate(album_pages, 1):
        try:
            p_img = Image.open(page_path)
            oriented = normalize_orientation(p_img)
            crops = slice_grid(oriented, rows=2, cols=2)
            page_crops_map[p_idx] = {pos: crop for pos, crop in crops}
        except Exception as e:
            print(f"  Erreur découpe page {p_idx}: {e}")

    # Build card objects for JSON injection into the HTML
    cards_data = []
    for idx, row in df.iterrows():
        page = int(row.get("Page", 1))
        pos = int(row.get("Position", 1))
        
        # Real crop thumbnail
        real_crop_b64 = ""
        if page in page_crops_map and pos in page_crops_map[page]:
            real_crop_b64 = encode_image_base64(page_crops_map[page][pos])

        counterfeit_warning = detect_counterfeit_risk(row)
        
        card_obj = {
            "id": idx,
            "page": page,
            "pos": pos,
            "ocr_name": str(row.get("OCR_Name", "")),
            "ocr_number": str(row.get("OCR_Number", "")),
            "pv": int(row.get("PV")) if pd.notna(row.get("PV")) and row.get("PV") > 0 else 0,
            "is_foil": str(row.get("Is_Foil", "")) == "Oui",
            "name": str(row.get("Identified_Name", "Inconnue")),
            "set_name": str(row.get("Extension", "")),
            "number": str(row.get("Numero_Officiel", "")),
            "rarity": str(row.get("Rarete", "")),
            "condition": str(row.get("Etat", "NM/EX")),
            "flaws": str(row.get("Defauts", "")),
            "price_eur": float(row.get("Prix_Estime_EUR", 0.0) or 0.0),
            "trend_eur": float(row.get("Tendance_EUR", 0.0) or 0.0),
            "cardmarket_url": str(row.get("Lien_Cardmarket", "")),
            "official_img": str(row.get("Image_Officielle", "")),
            "real_crop_img": real_crop_b64,
            "counterfeit_warning": counterfeit_warning
        }
        cards_data.append(card_obj)

    # Compute stats
    total_val = sum(c["price_eur"] for c in cards_data)
    total_cards = len(cards_data)
    total_foils = sum(1 for c in cards_data if c["is_foil"])
    
    condition_counts = {}
    for c in cards_data:
        cond = c["condition"] or "Non spécifié"
        condition_counts[cond] = condition_counts.get(cond, 0) + 1

    total_suspect = sum(1 for c in cards_data if c["counterfeit_warning"])

    html_content = _build_html_template(
        title=title,
        cards=cards_data,
        total_val=total_val,
        total_cards=total_cards,
        total_foils=total_foils,
        condition_counts=condition_counts,
        total_suspect=total_suspect
    )

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✨ Rapport interactif généré avec succès : {output_html_path}")
    return output_html_path


def _build_html_template(
    title: str,
    cards: list,
    total_val: float,
    total_cards: int,
    total_foils: int,
    condition_counts: dict,
    total_suspect: int
) -> str:
    cards_json = json.dumps(cards, ensure_ascii=False)
    
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

    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 80px;
    }}

    /* Container */
    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px 20px;
    }}

    /* Header & Hero Stats */
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

    /* Stats Grid */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 6px;
    }}

    .stat-val {{
      font-size: 1.75rem;
      font-weight: 800;
      color: #ffffff;
    }}

    .stat-val.highlight {{
      color: #38bdf8;
      text-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
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

    /* Single Card Item */
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
      border: 2px solid var(--purple);
      box-shadow: 0 0 15px rgba(168, 85, 247, 0.2);
    }}

    /* Card Header */
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

    /* Card Details & Badges */
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

    /* Price Section */
    .price-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 6px;
      padding-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
    }}

    .price-tag {{
      font-size: 1.35rem;
      font-weight: 800;
      color: #4ade80;
    }}

    .cm-link {{
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 6px;
      background: rgba(56, 189, 248, 0.1);
      transition: var(--transition);
    }}

    .cm-link:hover {{
      background: rgba(56, 189, 248, 0.2);
    }}

    /* Defect Box */
    .flaw-box {{
      font-size: 0.75rem;
      background: rgba(239, 68, 68, 0.1);
      border-left: 3px solid var(--red);
      color: #fca5a5;
      padding: 6px 10px;
      border-radius: 4px;
      margin-top: 4px;
    }}

    /* Warning Banner for Counterfeit / Proxy */
    .counterfeit-banner {{
      font-size: 0.75rem;
      background: rgba(168, 85, 247, 0.15);
      border: 1px solid rgba(168, 85, 247, 0.4);
      color: #e9d5ff;
      padding: 8px 10px;
      border-radius: 6px;
      line-height: 1.35;
    }}

    /* Native Dialog Modal for Zoom */
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
          <h1>
            <span>🎴 {title}</span>
            <span class="badge-live">IA Gemini 3.8 Flash + TCGdex</span>
          </h1>
          <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 4px;">
            Validation visuelle côte-à-côte (Photo réelle du classeur vs Visuel officiel HD Cardmarket)
          </p>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Valeur totale estimée</div>
          <div class="stat-val highlight">{total_val:.2f} €</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Cartes scannées</div>
          <div class="stat-val">{total_cards}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Cartes brillantes / Foil</div>
          <div class="stat-val">{total_foils}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Cartes suspectes / Fausse potentielle</div>
          <div class="stat-val" style="color: {'#c084fc' if total_suspect > 0 else '#94a3b8'};">{total_suspect}</div>
        </div>
      </div>
    </header>

    <!-- Toolbar Filters -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" class="search-input" placeholder="Rechercher un Pokémon, une extension...">
      </div>

      <div class="pill-filters">
        <button class="filter-btn active" data-filter="all">Toutes ({total_cards})</button>
        <button class="filter-btn" data-filter="valuable">⭐ > 10 €</button>
        <button class="filter-btn" data-filter="foil">✨ Brillantes ({total_foils})</button>
        <button class="filter-btn" data-filter="worn">⚠️ Abîmées (PO/PL)</button>
        <button class="filter-btn" data-filter="nm-ex">🛡️ NM / EX</button>
        {f'<button class="filter-btn" data-filter="suspect">🚨 Suspectes ({total_suspect})</button>' if total_suspect > 0 else ''}
      </div>

      <select id="sortSelect" class="sort-select">
        <option value="price-desc">Prix : Plus cher d'abord</option>
        <option value="price-asc">Prix : Moins cher d'abord</option>
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
      <div id="modalDetails" style="font-size: 0.9rem; color: #cbd5e1; line-height: 1.6;"></div>
    </div>
  </dialog>

  <script>
    const CARDS = {cards_json};
    let currentFilter = 'all';
    let currentSort = 'price-desc';
    let searchQuery = '';

    const gridEl = document.getElementById('cardsGrid');
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const zoomDialog = document.getElementById('zoomDialog');
    const modalCloseBtn = document.getElementById('modalCloseBtn');

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

        if (currentFilter === 'valuable') return c.price_eur >= 10.0;
        if (currentFilter === 'foil') return c.is_foil;
        if (currentFilter === 'worn') return ['PL', 'PO'].includes(c.condition.toUpperCase());
        if (currentFilter === 'nm-ex') return ['NM', 'EX', 'NM/EX'].includes(c.condition.toUpperCase());
        if (currentFilter === 'suspect') return !!c.counterfeit_warning;
        return true;
      }});

      filtered.sort((a, b) => {{
        if (currentSort === 'price-desc') return b.price_eur - a.price_eur;
        if (currentSort === 'price-asc') return a.price_eur - b.price_eur;
        if (currentSort === 'page-pos') return (a.page * 10 + a.pos) - (b.page * 10 + b.pos);
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

      gridEl.innerHTML = filtered.map(c => {{
        const condClass = getConditionClass(c.condition);
        const hasWarning = !!c.counterfeit_warning;
        const officialFallback = c.official_img || 'https://assets.tcgdex.net/univ/back/high.webp';

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
                <img class="card-img" src="${{officialFallback}}" alt="${{c.name}} officielle" loading="lazy" onerror="this.src='https://assets.tcgdex.net/univ/back/high.webp'">
              </div>
            </div>

            <div class="badges-row">
              <span class="badge ${{condClass}}">${{c.condition || 'EX'}}</span>
              ${{c.is_foil ? '<span class="badge badge-foil">✨ Foil / Reverse</span>' : ''}}
              ${{c.pv > 0 ? `<span class="badge badge-pv">${{c.pv}} PV</span>` : ''}}
              <span class="badge" style="background: rgba(148, 163, 184, 0.1); color: #cbd5e1;">${{c.rarity || 'Commune'}}</span>
            </div>

            ${{c.flaws && c.flaws.toLowerCase() !== 'none visible' && c.flaws.toLowerCase() !== 'none' ? `
              <div class="flaw-box">
                <strong>Défauts :</strong> ${{c.flaws}}
              </div>
            ` : ''}}

            ${{hasWarning ? `
              <div class="counterfeit-banner">
                <strong>⚠️ Alerte collectionneur :</strong><br>${{c.counterfeit_warning}}
              </div>
            ` : ''}}

            <div class="price-row">
              <div class="price-tag">${{c.price_eur > 0 ? c.price_eur.toFixed(2) + ' €' : 'N/A'}}</div>
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

    function openZoom(cardId) {{
      const card = CARDS.find(c => c.id === cardId);
      if (!card) return;

      document.getElementById('modalTitle').textContent = `${{card.name}} (${{card.set_name}} #${{card.number}})`;
      document.getElementById('modalRealImg').src = card.real_crop_img;
      document.getElementById('modalOfficialImg').src = card.official_img || 'https://assets.tcgdex.net/univ/back/high.webp';

      document.getElementById('modalDetails').innerHTML = `
        <p><strong>Emplacement dans le classeur :</strong> Page ${{card.page}}, Position ${{card.pos}}</p>
        <p><strong>Points de Vie (PV) :</strong> ${{card.pv || 'N/A'}} | <strong>Finition :</strong> ${{card.is_foil ? 'Brillante (Holo/Reverse)' : 'Non-brillante'}}</p>
        <p><strong>État physique évalué :</strong> ${{card.condition}} ${{card.flaws ? '— <em>' + card.flaws + '</em>' : ''}}</p>
        <p><strong>Cote Cardmarket recommandée :</strong> <span style="color: #4ade80; font-weight: 800; font-size: 1.1rem;">${{card.price_eur.toFixed(2)}} €</span></p>
        ${{card.counterfeit_warning ? `<p style="color: #fca5a5; margin-top: 8px;"><strong>⚠️ Remarque contrefaçon :</strong> ${{card.counterfeit_warning}}</p>` : ''}}
      `;

      zoomDialog.showModal();
    }}

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
    renderCards();
  </script>
</body>
</html>"""
