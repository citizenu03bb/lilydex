from basket_helpers import accepted_prices
import json
import re
from test_library import inputs
from pokeprice.inventory import SCHEMA_VERSION, Store
from pokeprice.inventory_import import import_collection
from pokeprice.reservations import (
    CARD_WEIGHT_GRAMS,
    DEFAULT_PACKING_GRAMS,
    DEFAULT_REGISTERED_THRESHOLD_CENTS,
    REGISTERED_TARIFFS,
    TRACKED_TARIFFS,
    packing_grams,
    registered_threshold_cents,
    reply_message,
    response_delay_hours,
    shipping_cents,
    shipping_config,
    shipping_quote,
)
from pokeprice.webapp import create_app, password_hash
from starlette.testclient import TestClient


def test_packing_and_threshold_env_and_defaults():
    assert packing_grams({}) == DEFAULT_PACKING_GRAMS
    assert packing_grams({"POKEPRICE_PACKING_GRAMS": "15"}) == 15
    assert packing_grams({"POKEPRICE_PACKING_GRAMS": "invalid"}) == DEFAULT_PACKING_GRAMS

    assert registered_threshold_cents({}) == DEFAULT_REGISTERED_THRESHOLD_CENTS
    assert registered_threshold_cents({"POKEPRICE_REGISTERED_THRESHOLD_EUR": "60"}) == 6000
    assert registered_threshold_cents({"POKEPRICE_REGISTERED_THRESHOLD_EUR": "abc"}) == DEFAULT_REGISTERED_THRESHOLD_CENTS

    class FakeNotifier:
        enabled = True

    assert response_delay_hours(FakeNotifier()) == 48
    assert response_delay_hours(None) == 120
    assert response_delay_hours(None, {"POKEPRICE_RESPONSE_DELAY_HOURS": "24"}) == 24


def test_shipping_quote_hand_delivery():
    quote = shipping_quote(card_count=10, total_cents=10000, delivery="hand")
    assert quote["delivery"] == "hand"
    assert quote["shipping_cents"] == 0
    assert quote["registered"] is False
    assert quote["service"] == "hand"
    assert shipping_cents(10, 10000, delivery="hand") == 0


def test_shipping_quote_tracked_under_50_euros():
    # 1 card: 10g + 2g = 12g <= 20g -> 2.02 € (202 cents)
    quote1 = shipping_quote(card_count=1, total_cents=1200, delivery="shipping")
    assert quote1["shipping_cents"] == 202
    assert quote1["registered"] is False
    assert quote1["service"] == "lettre_suivie"

    # 10 cards: 10g + 20g = 30g <= 100g -> 3.60 € (360 cents)
    quote10 = shipping_quote(card_count=10, total_cents=3500, delivery="shipping")
    assert quote10["shipping_cents"] == 360
    assert quote10["registered"] is False


def test_shipping_quote_option_b_automatic_registered_at_or_above_50_euros():
    # Exactly 50.00 € (5000 cents): must be registered R2
    # 1 card: 12g <= 20g -> 7.29 € (729 cents)
    quote_exact = shipping_quote(card_count=1, total_cents=5000, delivery="shipping")
    assert quote_exact["shipping_cents"] == 729
    assert quote_exact["registered"] is True
    assert quote_exact["service"] == "lettre_recommandee_r2"

    # Above 50 €: 10 cards: 30g <= 50g -> 8.07 € (807 cents)
    quote_above = shipping_quote(card_count=10, total_cents=7500, delivery="shipping")
    assert quote_above["shipping_cents"] == 807
    assert quote_above["registered"] is True
    assert quote_above["service"] == "lettre_recommandee_r2"


def test_shipping_quote_explicit_registered_request():
    # Under 50 €, but buyer or seller requested registered
    quote = shipping_quote(card_count=1, total_cents=2000, delivery="shipping", registered=True)
    assert quote["shipping_cents"] == 729
    assert quote["registered"] is True


def test_reply_message_formatting():
    request = {
        "items": [
            {"label": "Pikachu · Set de Base · 58/102", "price_cents": 1500, "outcome": "accepted"},
            {"label": "Dracaufeu · Set de Base · 4/102", "price_cents": 6000, "outcome": "accepted"},
        ],
        "delivery": "shipping",
        "registered": True,
    }
    payment = {
        "reference": "LILY-12345678",
        "shipping_cents": 729,
        "total_cents": 8229,
        "wero": "0612345678",
        "iban": "FR7630006000011234567890189",
        "holder": "Vendeur Test",
        "paypal": "https://paypal.me/vendeurtest",
    }
    text = reply_message(request, payment, client_name="Sacha")
    assert text.startswith("Bonjour Sacha,")
    assert "Pikachu · Set de Base · 58/102 (15,00 €)" in text
    assert "Dracaufeu · Set de Base · 4/102 (60,00 €)" in text
    assert "Montant des cartes : 75,00 €" in text
    assert "Frais d’envoi : 7,29 € (envoi recommandé avec remise contre signature R2)." in text
    assert "Total à régler : 82,29 €" in text
    assert "LILY-12345678" in text
    assert "Wero : 0612345678" in text
    assert "FR76 3000 6000 0112 3456 7890 189" in text
    assert "https://paypal.me/vendeurtest" in text
    assert "7 jours" in text


def setup_shop(tmp_path):
    store = Store(tmp_path / "inventory")
    import_collection(store, inputs(tmp_path))
    admin = TestClient(create_app(store.root))
    assert admin.post("/api/setup", json={"username": "pat", "password": "Collection-test-2026!"}).status_code == 200
    cards = [c for c in admin.get("/api/copies", params={"limit": 100}).json()["items"] if c["identification_status"] == "confirmed"]
    listings = [
        admin.put(f"/api/copies/{cards[0]['id']}/listing", json={"price_eur": "65.00"}).json(),
        admin.put(f"/api/copies/{cards[1]['id']}/listing", json={"price_eur": "1.20"}).json(),
    ]
    return admin, store, listings[0]["id"], listings[1]["id"]


def test_public_shipping_endpoint(tmp_path):
    client, _, _, _ = setup_shop(tmp_path)
    res = client.get("/api/public/shipping")
    assert res.status_code == 200
    data = res.json()
    assert data["card_weight_grams"] == CARD_WEIGHT_GRAMS
    assert data["packing_grams"] == DEFAULT_PACKING_GRAMS
    assert data["registered_threshold_cents"] == DEFAULT_REGISTERED_THRESHOLD_CENTS
    assert len(data["tracked_tariffs"]) == len(TRACKED_TARIFFS)
    assert len(data["registered_tariffs"]) == len(REGISTERED_TARIFFS)


def test_public_conditions_pages_and_sitemap(tmp_path):
    client, _, _, _ = setup_shop(tmp_path)
    res_fr = client.get("/conditions")
    assert res_fr.status_code == 200
    assert '<html lang="fr"' in res_fr.text
    assert "Conditions de vente" in res_fr.text
    assert "Lettre verte suivie" in res_fr.text
    assert "Lettre recommandée R2" in res_fr.text
    assert "14 jours" in res_fr.text

    res_en = client.get("/en/conditions")
    assert res_en.status_code == 200
    assert '<html lang="en-GB"' in res_en.text
    assert "Terms of sale" in res_en.text

    # Sitemap
    res_sitemap = client.get("/sitemap.xml")
    if res_sitemap.status_code == 200:
        assert "conditions" in res_sitemap.text


def test_client_request_with_hand_delivery_and_postal_shipping(tmp_path):
    client, store, dracaufeu_id, pikachu_id = setup_shop(tmp_path)

    # Configure payment
    client.put(
        "/api/settings/payment",
        json={"wero": "0612345678", "iban": "FR7630006000011234567890189", "holder": "Lily Vendeuse", "paypal": "paypal.me/lily"},
    ).raise_for_status()

    # Signup a client
    client.post("/api/public/signup", json={
        "email": "buyer@example.org",
        "display_name": "Acheteur Test",
        "password": "BuyerPassword123!",
        "consent": True,
    }).raise_for_status()

    # Activate client
    users = client.get("/api/clients").json()
    buyer = next(u for u in users if u["email"] == "buyer@example.org")
    client.patch(f"/api/clients/{buyer['id']}", json={"status": "active", "disabled": False}).raise_for_status()

    # Login as client
    client_buyer = TestClient(create_app(store.root))
    client_buyer.post("/api/login", json={"username": "buyer@example.org", "password": "BuyerPassword123!"}).raise_for_status()

    # Case 1: hand delivery
    req_hand = client_buyer.post(
        "/api/me/requests",
        json={"listing_ids": [pikachu_id], "expected_prices": accepted_prices(store, [pikachu_id]), "message": "Je suis du coin", "delivery": "hand"},
    ).json()
    assert req_hand["delivery"] == "hand"
    assert req_hand["shipping_cents"] == 0
    assert req_hand["total_with_shipping_cents"] == req_hand["total_cents"]
    assert req_hand["message"] == "Je suis du coin"
    with store.connect() as db:
        stored = db.execute(
            "SELECT delivery,registered,message FROM requests WHERE id=?", (req_hand["id"],)
        ).fetchone()
    assert tuple(stored) == ("hand", 0, "Je suis du coin")

    # Case 2: shipping for Dracaufeu (>= 50 € -> 65 € -> automatic registered R2)
    req_drac = client_buyer.post(
        "/api/me/requests",
        json={"listing_ids": [dracaufeu_id], "expected_prices": accepted_prices(store, [dracaufeu_id]), "message": "Envoi soigné svp", "delivery": "shipping"},
    ).json()
    assert req_drac["delivery"] == "shipping"
    assert req_drac["registered"] is True
    assert req_drac["shipping_cents"] == 729
    assert req_drac["total_with_shipping_cents"] == 6500 + 729

    # Staff accepts req_drac
    admin_req = client.get("/api/requests").json()
    drac_req = next(r for r in admin_req if r["id"] == req_drac["id"])
    assert drac_req["delivery"] == "shipping"
    assert drac_req["registered"] is True

    accept_res = client.post(
        f"/api/requests/{drac_req['id']}/accept",
        json={"expected_version": drac_req["version"], "listing_ids": [dracaufeu_id]},
    )
    assert accept_res.status_code == 200

    # Staff checks requests list
    accepted_admin = next(r for r in client.get("/api/requests").json() if r["id"] == drac_req["id"])
    assert accepted_admin["status_label"] == "Réservée"
    assert accepted_admin["payment"]["shipping_cents"] == 729
    assert accepted_admin["payment"]["total_cents"] == 6500 + 729
    assert "reply_text" in accepted_admin
    assert "Bonjour Acheteur Test," in accepted_admin["reply_text"]
    assert "Frais d’envoi : 7,29 € (envoi recommandé avec remise contre signature R2)." in accepted_admin["reply_text"]
    assert "LILY-" in accepted_admin["reply_text"]

    # Client checks their request
    accepted_client = next(r for r in client_buyer.get("/api/me/requests").json() if r["id"] == drac_req["id"])
    assert accepted_client["status_label"] == "Réservée"
    assert accepted_client["payment"]["shipping_cents"] == 729
    assert accepted_client["payment"]["total_cents"] == 6500 + 729
    assert "reply_text" not in accepted_client["payment"]
    assert "reply_text" not in accepted_client


def test_conditions_pages_show_the_rates_the_basket_uses(tmp_path, monkeypatch):
    monkeypatch.setenv("POKEPRICE_REGISTERED_THRESHOLD_EUR", "60")
    client, _, _, _ = setup_shop(tmp_path)
    fr = client.get("/conditions").text
    en = client.get("/en/conditions").text
    assert "{{" not in fr and "{{" not in en
    assert "60,00 €" in fr and "60.00 €" in en
    assert "<td>1 000 g</td><td>9,59 €</td><td>Colissimo</td>" in fr
    assert "<td>1,000 g</td><td>9.59 €</td><td>Colissimo</td>" in en
    assert fr.count("<tr><td>") == len(TRACKED_TARIFFS) + len(REGISTERED_TARIFFS)


def test_schema_24_moves_the_delivery_prefix_out_of_old_messages(tmp_path):
    client, store, dracaufeu_id, pikachu_id = setup_shop(tmp_path)
    for listing_id in (pikachu_id, dracaufeu_id, pikachu_id):
        client.post(
            "/api/public/requests",
            json={"email": f"{listing_id[:8]}@example.org", "display_name": "Ancien", "listing_ids": [listing_id], "expected_prices": accepted_prices(store, [listing_id]),
                  "message": "", "consent": True},
        ).raise_for_status()
    old_messages = ["[delivery:hand]\nJe passe samedi", "[delivery:registered]\nMerci", "[delivery:shipping]"]
    with store.connect(write=True) as db:
        ids = [r[0] for r in db.execute("SELECT id FROM requests ORDER BY rowid")]
        db.execute("ALTER TABLE requests DROP COLUMN delivery")
        db.execute("ALTER TABLE requests DROP COLUMN registered")
        for request_id, message in zip(ids, old_messages):
            db.execute("UPDATE requests SET message=? WHERE id=?", (message, request_id))
        db.execute("PRAGMA user_version=23")
    migrated = Store(store.root)
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rows = [tuple(db.execute("SELECT delivery,registered,message FROM requests WHERE id=?", (i,)).fetchone())
                for i in ids]
    assert rows == [("hand", 0, "Je passe samedi"), ("shipping", 1, "Merci"), ("shipping", 0, "")]
    assert list((tmp_path / "backups").glob(f"before-schema{SCHEMA_VERSION}-from23-*"))
    hand = next(r for r in client.get("/api/requests").json() if r["id"] == ids[0])
    assert hand["delivery"] == "hand" and hand["shipping_cents"] == 0 and hand["message"] == "Je passe samedi"
