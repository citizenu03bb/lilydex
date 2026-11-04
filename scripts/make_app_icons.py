"""Les icônes de l'application installable, tirées de la mascotte.

    uv run python scripts/make_app_icons.py

Écrit icon-192.png, icon-512.png et icon-maskable-512.png dans
src/pokeprice/web/. Les fichiers produits sont versionnés : relancez le script
seulement quand la mascotte change.
"""

from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parents[1] / "src/pokeprice/web"
# Fond --accent-soft du thème Herbier (themes.css) : la robe rouge y ressort.
BACKGROUND = (0xE3, 0xF0, 0xEA, 255)


def icon(size: int, figure: float) -> Image.Image:
    """Un carré plein, la mascotte centrée sur `figure` de sa hauteur."""
    mascot = Image.open(WEB / "mascotte.png").convert("RGBA")
    mascot = mascot.crop(mascot.getbbox())
    height = round(size * figure)
    width = round(mascot.width * height / mascot.height)
    mascot = mascot.resize((width, height), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), BACKGROUND)
    canvas.alpha_composite(mascot, ((size - width) // 2, (size - height) // 2))
    return canvas.convert("RGB")


def main() -> None:
    icon(192, 0.9).save(WEB / "icon-192.png", optimize=True)
    icon(512, 0.9).save(WEB / "icon-512.png", optimize=True)
    # Maskable : le système découpe un cercle ou un carré arrondi ; tout ce qui
    # compte tient dans le cercle central de 80 % (zone sûre du W3C).
    icon(512, 0.72).save(WEB / "icon-maskable-512.png", optimize=True)


if __name__ == "__main__":
    main()
