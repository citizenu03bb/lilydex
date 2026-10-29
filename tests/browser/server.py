"""Serve the real storefront against disposable synthetic data on loopback only."""

from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw
import uvicorn

from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection
from pokeprice.listings import Listings
from pokeprice.webapp import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_library import inputs

BASE = "http://127.0.0.1:8796"


def no_service(*args, **kwargs):
    raise AssertionError("Browser fixtures must never call an external service")


def build_fixture(root):
    store = Store(root / "inventory")
    import_collection(store, inputs(root))

    def photo(size, color, caption=False):
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, size[0] - 9, size[1] - 9), outline="#ac4c3c", width=16)
        if caption:
            draw.rectangle((40, 220, 1024, 1320), fill="#f5e3bc", outline="#343d32", width=12)
            draw.text((45, 120), "SYNTHETIQUE - bords visibles", fill="#343d32", font_size=44)
        data = BytesIO()
        image.save(data, "JPEG", quality=94)
        return store.save_photo(data.getvalue())

    portrait = photo((1064, 1573), "#e9efde", caption=True)
    landscape = photo((1600, 1000), "#f5e3bc")
    square = photo((1200, 1200), "#d8e4ed")
    cards = [c for c in store.listing(limit=100)["items"]
             if c["identification_status"] == "confirmed"]
    with store.connect(write=True) as db:
        for index, card in enumerate(cards):
            db.execute(
                "UPDATE copies SET name=?,condition=?,condition_confirmed=?,photo=? WHERE id=?",
                (f"Carte synthetique {index}", "NM" if index == 0 else "EX",
                 int(index in (0, 2, 3)),
                 landscape if index == 1 else square if index == 3 else portrait, card["id"]),
            )
        db.execute("UPDATE copies SET back_photo=? WHERE id=?", (square, cards[0]["id"]))
        db.execute("UPDATE copies SET condition='NM/EX' WHERE id=?", (cards[3]["id"],))
        db.execute("UPDATE copies SET language='ja' WHERE id=?", (cards[1]["id"],))

    listings = Listings(store)
    single = listings.publish([cards[0]["id"]], "fixture", price_cents=120)
    lot = listings.publish([cards[1]["id"], cards[2]["id"]], "fixture", price_cents=200,
                           lot=True, title="Lot synthetique <test> & public")
    square_listing = listings.publish([cards[3]["id"]], "fixture", price_cents=150)

    # No local operator identity, credentials or real service is used by this app.
    os.environ["POKEPRICE_CONTACT_EMAIL"] = ""
    os.environ["POKEPRICE_CONTROLLER_NAME"] = ""
    app = create_app(
        store.root, auto_checks=False, public_origin=BASE, agent_enabled=False,
        intake_reader=no_service, intake_lookup=no_service, condition_reader=no_service,
        variant_reader=no_service, edition_reader=no_service, edition_get_json=no_service,
        edition_fetch=no_service, price_fetch=no_service, variant_fetch=no_service,
        market_fetch=no_service,
    )

    @app.get("/__test__/fixture")
    def fixture():
        return {"synthetic_only": True, "single": single["id"], "lot": lot["id"],
                "square": square_listing["id"], "source_dimensions": [1064, 1573]}

    return app


if __name__ == "__main__":
    # There is deliberately no --data option or existing-server fallback.
    with tempfile.TemporaryDirectory(prefix="lilydex-browser-") as directory:
        uvicorn.run(build_fixture(Path(directory)), host="127.0.0.1", port=8796,
                    log_level="warning")
