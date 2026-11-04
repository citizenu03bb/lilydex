"""Storefront reservation requests: nothing is blocked until the seller accepts.

Accepting creates a lot through the existing sale workflow and reserves it in
the same transaction as the request's answer: a cancellation or another answer
to the same request either comes first and wins, or waits and is refused.
"""

import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from .inventory import Conflict, now
from .notifications import euros

EXPIRY = timedelta(days=7)
OPEN_LIMIT = 10  # Open requests per client, against abuse.
GUEST_LIMIT = 3  # Open requests per address, when sent without signing in.
LINK_EXPIRY = timedelta(days=7)

# La Poste 2026-01-01 (France métropolitaine)
TARIFF_DATE = "2026-01-01"
CARD_WEIGHT_GRAMS = 2
DEFAULT_PACKING_GRAMS = 10
DEFAULT_REGISTERED_THRESHOLD_CENTS = 5000  # 50.00 € : envoi sécurisé recommandé avec signature dès ce seuil

# Grilles tarifaires publiques au 2026-01-01
# Lettre verte suivie jusqu'à 100 g, puis Colissimo domicile standard
TRACKED_TARIFFS = (
    (20, 202, "lettre_suivie"),
    (100, 360, "lettre_suivie"),
    (250, 549, "colissimo"),
    (500, 759, "colissimo"),
    (750, 929, "colissimo"),
    (1000, 959, "colissimo"),
    (2000, 1119, "colissimo"),
    (5000, 1739, "colissimo"),
)

# Lettre recommandée R2 (remise contre signature, indemnisation forfaitaire 153 €)
# jusqu'à 250 g, puis Colissimo avec recommandation R2 (tarif Colissimo base + 5,00 €)
REGISTERED_TARIFFS = (
    (20, 729, "lettre_recommandee_r2"),
    (50, 807, "lettre_recommandee_r2"),
    (100, 897, "lettre_recommandee_r2"),
    (250, 1073, "lettre_recommandee_r2"),
    (500, 1259, "colissimo_recommande_r2"),
    (750, 1429, "colissimo_recommande_r2"),
    (1000, 1459, "colissimo_recommande_r2"),
    (2000, 1619, "colissimo_recommande_r2"),
    (5000, 2239, "colissimo_recommande_r2"),
)

# La Poste's names for the services, the same in both languages.
SHIPPING_SERVICES = {
    "lettre_suivie": "Lettre verte suivie",
    "colissimo": "Colissimo",
    "lettre_recommandee_r2": "Lettre recommandée R2",
    "colissimo_recommande_r2": "Colissimo recommandé R2",
}


def packing_grams(env=None):
    source = os.environ if env is None else env
    try:
        value = int(source.get("POKEPRICE_PACKING_GRAMS", ""))
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    return DEFAULT_PACKING_GRAMS


def registered_threshold_cents(env=None):
    source = os.environ if env is None else env
    try:
        value = float(source.get("POKEPRICE_REGISTERED_THRESHOLD_EUR", ""))
        if value >= 0:
            return int(round(value * 100))
    except (TypeError, ValueError):
        pass
    return DEFAULT_REGISTERED_THRESHOLD_CENTS


def response_delay_hours(notifier=None, env=None):
    source = os.environ if env is None else env
    try:
        value = int(source.get("POKEPRICE_RESPONSE_DELAY_HOURS", ""))
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    if notifier and getattr(notifier, "enabled", False):
        return 48
    return 120


def shipping_quote(card_count, total_cents=0, delivery="shipping", registered=None, packing=None, threshold_cents=None):
    """Calcule le tarif postal selon le nombre de cartes et la valeur du panier."""
    if delivery == "hand":
        return {
            "delivery": "hand",
            "registered": False,
            "cards": card_count,
            "weight_grams": 0,
            "shipping_cents": 0,
            "service": "hand",
            "tariff_date": TARIFF_DATE,
        }
    p_grams = packing if packing is not None else packing_grams()
    thresh = threshold_cents if threshold_cents is not None else registered_threshold_cents()
    weight = p_grams + max(0, card_count) * CARD_WEIGHT_GRAMS
    # Recommandé obligatoire dès que le montant atteint le seuil (Option B), ou si demandé
    is_registered = bool(registered or (total_cents >= thresh))
    table = REGISTERED_TARIFFS if is_registered else TRACKED_TARIFFS
    cost, service = table[-1][1], table[-1][2]
    for max_w, price, srv in table:
        if weight <= max_w:
            cost, service = price, srv
            break
    return {
        "delivery": "shipping",
        "registered": is_registered,
        "cards": card_count,
        "weight_grams": weight,
        "shipping_cents": cost,
        "service": service,
        "tariff_date": TARIFF_DATE,
    }


def shipping_cents(card_count, total_cents=0, delivery="shipping", registered=None, packing=None):
    return shipping_quote(card_count, total_cents, delivery, registered, packing)["shipping_cents"]


def extract_delivery_mode(message):
    """Extrait le mode de livraison et le choix recommandé du message de réservation."""
    lines = (message or "").split("\n")
    delivery = "shipping"
    registered = False
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == "[delivery:hand]":
            delivery = "hand"
        elif stripped == "[delivery:registered]":
            delivery = "shipping"
            registered = True
        elif stripped == "[delivery:shipping]":
            delivery = "shipping"
        else:
            clean_lines.append(line)
    return delivery, registered, "\n".join(clean_lines).strip()


def format_delivery_message(message, delivery, registered):
    prefix = ""
    if delivery == "hand":
        prefix = "[delivery:hand]\n"
    elif registered:
        prefix = "[delivery:registered]\n"
    return (prefix + (message or "").strip()).strip()


def reply_message(request, payment, client_name=""):
    """Message de réponse complet prérempli pour Lily, prêt à être copié vers l'acheteur."""
    greeting = f"Bonjour {client_name}," if client_name else "Bonjour,"
    lines = [greeting, "", "Votre demande de réservation a bien été acceptée :"]
    accepted_items = [i for i in request.get("items", []) if i.get("outcome") == "accepted"]
    if not accepted_items:
        accepted_items = request.get("items", [])
    for item in accepted_items:
        lines.append(f"- {item['label']} ({euros(item['price_cents'])})")
    lines.append("")
    total_cards = sum(i["price_cents"] for i in accepted_items) or request.get("total_cents", 0)
    shipping_amt = payment.get("shipping_cents", 0)
    total_cents = payment.get("total_cents", total_cards + shipping_amt)
    delivery = request.get("delivery", "shipping")
    registered = request.get("registered", False)

    if delivery == "hand":
        lines.append(f"Montant des cartes : {euros(total_cards)}")
        lines.append("Livraison : remise en main propre (sans frais de port).")
        lines.append(f"Total à régler : {euros(total_cents)}")
    elif registered:
        lines.append(f"Montant des cartes : {euros(total_cards)}")
        lines.append(f"Frais d’envoi : {euros(shipping_amt)} (envoi recommandé avec remise contre signature R2).")
        lines.append(f"Total à régler : {euros(total_cents)}")
    else:
        lines.append(f"Montant des cartes : {euros(total_cards)}")
        lines.append(f"Frais d’envoi : {euros(shipping_amt)} (lettre verte suivie / colissimo).")
        lines.append(f"Total à régler : {euros(total_cents)}")

    lines.append(f"Référence à indiquer dans le libellé : {payment.get('reference', '')}.")
    lines.append("")
    lines.append("Moyens de paiement disponibles :")
    has_method = False
    if payment.get("wero"):
        lines.append(f"- Wero : {payment['wero']}")
        has_method = True
    if payment.get("iban"):
        iban_spaced = re.sub(r"(.{4})", r"\1 ", payment["iban"]).strip()
        lines.append(f"- Virement bancaire : IBAN {iban_spaced} (titulaire {payment.get('holder', '')})")
        has_method = True
    if payment.get("paypal"):
        lines.append(f"- PayPal (biens et services) : {payment['paypal']}")
        has_method = True
    if not has_method:
        lines.append("- À convenir ensemble par retour d’e-mail.")

    lines.append("")
    lines.append("Les cartes vous sont réservées pendant 7 jours en attente du règlement.")
    if delivery == "hand":
        lines.append("Nous pouvons convenir d'un rendez-vous pour la remise en main propre.")
    else:
        lines.append("Votre commande sera soigneusement protégée et expédiée dès réception du paiement.")
    lines.append("")
    lines.append("Bien cordialement,")
    lines.append("Lily — Les cartes de Lily")
    return "\n".join(lines)


def shipping_config(notifier=None, env=None):
    """Configuration tarifaire complète pour le client web et les pages publiques."""
    p_grams = packing_grams(env)
    thresh = registered_threshold_cents(env)
    delay_h = response_delay_hours(notifier, env)
    return {
        "tariff_date": TARIFF_DATE,
        "card_weight_grams": CARD_WEIGHT_GRAMS,
        "packing_grams": p_grams,
        "registered_threshold_cents": thresh,
        "response_delay_hours": delay_h,
        "tracked_tariffs": [
            {"max_grams": w, "shipping_cents": c, "service": s} for w, c, s in TRACKED_TARIFFS
        ],
        "registered_tariffs": [
            {"max_grams": w, "shipping_cents": c, "service": s} for w, c, s in REGISTERED_TARIFFS
        ],
    }
# Schema 20: one-time links the seller sends from their own mailbox, so that a
# client chooses a password; only the token's hash is kept.
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS password_links(token_hash TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id), created_by TEXT NOT NULL,
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
PRAGMA user_version=20;
COMMIT;
"""
# Schema 21: the seller's settings, such as how a reserved lot is paid.
SETTINGS_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
PRAGMA user_version=21;
COMMIT;
"""
PAYMENT_FIELDS = ("wero", "iban", "holder", "paypal")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")
SALE_STATUS = {
    "draft": "Acceptée",
    "reserved": "Réservée",
    "sold": "Vendue",
    "shipped": "Expédiée",
    "completed": "Terminée",
    "cancelled": "Annulée",
    "returned": "Retournée",
}
REQUEST_STATUS = {
    "sent": "Envoyée",
    "accepted": "Acceptée",
    "partially_accepted": "Acceptée en partie",
    "refused": "Refusée",
    "expired": "Expirée",
    "cancelled": "Annulée",
}


def valid_email(value):
    value = (value or "").strip()
    if len(value) > 254 or not EMAIL.match(value):
        raise ValueError("Adresse e-mail invalide.")
    return value


def valid_iban(value):
    """An IBAN without spaces, checked by its two control digits (ISO 13616)."""
    iban = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        raise ValueError("IBAN invalide.")
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    if int(digits) % 97 != 1:
        raise ValueError("IBAN invalide : sa clé de contrôle ne correspond pas.")
    return iban


def payment_values(values):
    """Check the payment settings: each method is optional, none is guessed."""
    clean = {key: (values.get(key) or "").strip() for key in PAYMENT_FIELDS}
    wero = clean["wero"]
    if wero and "@" in wero:
        clean["wero"] = valid_email(wero)
    elif wero:
        phone = re.sub(r"[\s.\-]", "", wero)
        if not re.fullmatch(r"(\+\d{9,15}|0\d{9})", phone):
            raise ValueError("Wero : indiquez le numéro de téléphone ou l’e-mail enregistré dans Wero.")
        clean["wero"] = phone
    if clean["iban"]:
        clean["iban"] = valid_iban(clean["iban"])
        if not clean["holder"]:
            raise ValueError("Indiquez le titulaire du compte : le client en a besoin pour le virement.")
    elif clean["holder"]:
        raise ValueError("Le titulaire accompagne un IBAN.")
    paypal = clean["paypal"]
    if paypal and "@" in paypal:
        clean["paypal"] = valid_email(paypal)
    elif paypal:
        name = re.fullmatch(r"(?:https?://)?(?:www\.)?paypal\.me/([A-Za-z0-9]{1,20})/?", paypal)
        if not name:
            raise ValueError("PayPal : indiquez une adresse e-mail ou un lien paypal.me.")
        clean["paypal"] = "https://paypal.me/" + name[1]
    return clean


def sale_reference(sale_id):
    """The short reference a client copies into the payment's wording."""
    return "LILY-" + sale_id.replace("-", "")[:8].upper()


class Reservations:
    def __init__(self, store, storefront, notifier=None):
        self.store, self.storefront, self.notifier = store, storefront, notifier

    # -- Accounts ---------------------------------------------------------

    def signup(self, email, display_name, password_hash):
        """Create a pending client; an existing address is silently left alone."""
        email = valid_email(email)
        with self.store.connect(write=True) as db:
            # Before the first admin exists, a sign-up could only get in the way of setup.
            if not db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
                raise Conflict("La boutique n’est pas encore ouverte aux inscriptions.")
            known = db.execute(
                "SELECT 1 FROM users WHERE email=? OR username=?", (email, email)
            ).fetchone()
            if known:
                return False
            timestamp = now()
            db.execute(
                "INSERT INTO users(id,username,password_hash,role,created_at,email,"
                "display_name,status,consent_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    email,
                    password_hash,
                    "client",
                    timestamp,
                    email,
                    display_name.strip(),
                    "pending",
                    timestamp,
                ),
            )
            return True

    def clients(self):
        with self.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,email,display_name,status,disabled,created_at,consent_at "
                    "FROM users WHERE role='client' "
                    "ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC"
                )
            ]

    def set_client(self, client_id, status, disabled):
        with self.store.connect(write=True) as db:
            row = db.execute(
                "SELECT id FROM users WHERE id=? AND role='client'", (client_id,)
            ).fetchone()
            if not row:
                raise KeyError("Client introuvable.")
            db.execute(
                "UPDATE users SET status=?,disabled=? WHERE id=?",
                (status, int(disabled), client_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (client_id,))
        return {"ok": True}

    def password_link(self, client_id, actor):
        """A new one-time link replaces the previous ones; the token is shown once."""
        token = secrets.token_urlsafe(32)
        timestamp = datetime.now(timezone.utc)
        with self.store.connect(write=True) as db:
            row = db.execute(
                "SELECT status,disabled FROM users WHERE id=? AND role='client'", (client_id,)
            ).fetchone()
            if not row:
                raise KeyError("Client introuvable.")
            if row["status"] == "refused" or row["disabled"]:
                raise Conflict("Ce compte est refusé ou désactivé : validez-le d’abord.")
            db.execute("DELETE FROM password_links WHERE user_id=?", (client_id,))
            expires_at = (timestamp + LINK_EXPIRY).isoformat()
            db.execute(
                "INSERT INTO password_links VALUES(?,?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), client_id, actor,
                 timestamp.isoformat(), expires_at),
            )
        return {"token": token, "expires_at": expires_at}

    def use_link(self, db, token, password_hash):
        """Set the password a link was made for; the link proves the address."""
        row = db.execute(
            "SELECT u.id,u.username,u.role FROM password_links l JOIN users u ON u.id=l.user_id "
            "WHERE l.token_hash=? AND l.expires_at>? AND u.role='client' "
            "AND u.status!='refused' AND u.disabled=0",
            (hashlib.sha256(token.encode()).hexdigest(), now()),
        ).fetchone()
        if not row:
            raise ValueError("Ce lien n’est plus valable : demandez-en un autre au vendeur.")
        db.execute(
            "UPDATE users SET password_hash=?,status='active' WHERE id=?", (password_hash, row["id"])
        )
        db.execute("DELETE FROM password_links WHERE user_id=?", (row["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        return dict(row)

    # -- Requests ---------------------------------------------------------

    def expire(self, db):
        db.execute(
            "UPDATE requests SET status='expired',updated_at=?,version=version+1 "
            "WHERE status='sent' AND expires_at<?",
            (now(), now()),
        )

    def describe(self, db, row, *, staff=False):
        request = dict(row)
        sale = (
            db.execute(
                "SELECT status,paid,amount_cents,shipping_charged_cents FROM sales WHERE id=?",
                (request["sale_id"],),
            ).fetchone()
            if request["sale_id"]
            else None
        )
        request["status_label"] = (
            SALE_STATUS[sale[0]] if sale else REQUEST_STATUS[request["status"]]
        )
        request["sale_status"] = sale[0] if sale else None
        items = []
        for item in db.execute(
            "SELECT i.listing_id,i.price_cents,i.outcome,l.title FROM request_items i "
            "JOIN listings l ON l.id=i.listing_id WHERE i.request_id=? ORDER BY i.rowid",
            (request["id"],),
        ):
            cards = self.storefront.cards(db, item["listing_id"])
            entry = {
                "listing_id": item["listing_id"],
                "price_cents": item["price_cents"],
                "outcome": item["outcome"],
                # Several copies share a name: the edition tells them apart.
                "label": item["title"]
                or (
                    " · ".join(filter(None, [cards[0]["name"], cards[0]["set_name"], cards[0]["number"]]))
                    if len(cards) == 1
                    else f"Lot de {len(cards)} cartes"
                ),
                "available": bool(self.storefront.rows(db, item["listing_id"])),
                "card_count": max(1, len(cards)),
            }
            if staff:
                entry["copies"] = [
                    {"id": c["id"], "name": c["name"], "number": c["number"],
                     "set_name": c["set_name"], "stock_state": c["stock_state"]}
                    for c in cards
                ]
            items.append(entry)
        request["items"] = items
        request["total_cents"] = sum(i["price_cents"] for i in items)
        delivery, registered, clean_message = extract_delivery_mode(request.get("message"))
        request["message"] = clean_message
        request["delivery"] = delivery
        request["registered"] = registered
        total_card_count = sum(i.get("card_count", 1) for i in items)
        if sale:
            request["shipping_cents"] = sale["shipping_charged_cents"]
            card_subtotal = sale["amount_cents"] if sale["status"] in ("reserved", "sold", "completed") else request["total_cents"]
            request["total_with_shipping_cents"] = card_subtotal + sale["shipping_charged_cents"]
            quote = shipping_quote(total_card_count, card_subtotal, delivery=delivery, registered=registered)
            request["registered"] = quote["registered"]
        else:
            quote = shipping_quote(total_card_count, request["total_cents"], delivery=delivery, registered=registered)
            request["shipping_cents"] = quote["shipping_cents"]
            request["total_with_shipping_cents"] = request["total_cents"] + quote["shipping_cents"]
            request["registered"] = quote["registered"]
        if sale:
            request["reference"] = sale_reference(request["sale_id"])
        if not staff:
            request.pop("client_id")
        # The seller's payment details reach a client only while their lot awaits
        # payment; the team copies the same text into its e-mail.
        if sale and sale["status"] == "reserved" and not sale["paid"]:
            request["payment"] = {
                "total_cents": sale["amount_cents"] + sale["shipping_charged_cents"],
                "shipping_cents": sale["shipping_charged_cents"],
                "reference": request["reference"],
                **self.payment(db),
            }
            if staff:
                client_row = db.execute("SELECT email,display_name FROM users WHERE id=?", (row["client_id"],)).fetchone()
                client_name = (client_row["display_name"] or client_row["email"]) if client_row else ""
                request["reply_text"] = reply_message(request, request["payment"], client_name)
        return request

    def payment(self, db=None):
        """The seller's payment methods; an empty value means the method is not offered."""
        if db is None:
            with self.store.connect() as db:
                return self.payment(db)
        row = db.execute("SELECT value_json FROM settings WHERE key='payment'").fetchone()
        stored = json.loads(row[0]) if row else {}
        return {key: stored.get(key, "") for key in PAYMENT_FIELDS}

    def set_payment(self, values, actor):
        clean = payment_values(values)
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT INTO settings(key,value_json,updated_by,updated_at) VALUES('payment',?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,"
                "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                (json.dumps(clean), actor, now()),
            )
        return clean

    def payment_methods(self, names=None):
        """The methods offered, named without any identifier, for the public pages."""
        payment = self.payment()
        names = names or {"wero": "Wero", "iban": "virement bancaire", "paypal": "PayPal (biens et services)"}
        return [label for key, label in names.items() if payment[key]]

    def mine(self, client_id):
        with self.store.connect(write=True) as db:
            self.expire(db)
            return [
                self.describe(db, r)
                for r in db.execute(
                    "SELECT * FROM requests WHERE client_id=? ORDER BY created_at DESC",
                    (client_id,),
                ).fetchall()
            ]

    def create(self, client_id, listing_ids, message, delivery="shipping", registered=None):
        formatted_message = format_delivery_message(message, delivery, registered)
        prices = self.prices(listing_ids)
        with self.store.connect(write=True) as db:
            request = self.insert(db, client_id, prices(db), formatted_message, OPEN_LIMIT)
        self.notified()
        return request

    def guest(self, email, display_name, listing_ids, message, unusable_hash, delivery="shipping", registered=None):
        """A request without signing in: the address is checked when the seller replies.

        An unknown address gets a pending account without a usable password; a
        known one gets the request, unless its account is closed to requests.
        Either way the answer is the same: it never tells who has an account.
        """
        email = valid_email(email)
        formatted_message = format_delivery_message(message, delivery, registered)
        prices = self.prices(listing_ids)
        with self.store.connect(write=True) as db:
            if not db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
                raise Conflict("La boutique n’est pas encore ouverte aux réservations.")
            chosen = prices(db)
            row = db.execute(
                "SELECT id,role,status,disabled FROM users WHERE email=? OR username=?", (email, email)
            ).fetchone()
            if row and (row["role"] != "client" or row["status"] == "refused" or row["disabled"]):
                return
            if row:
                client_id = row["id"]
            else:
                client_id, timestamp = str(uuid.uuid4()), now()
                db.execute(
                    "INSERT INTO users(id,username,password_hash,role,created_at,email,"
                    "display_name,status,consent_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (client_id, email, unusable_hash, "client", timestamp, email,
                     display_name.strip(), "pending", timestamp),
                )
            self.insert(db, client_id, chosen, formatted_message, GUEST_LIMIT)
        self.notified()

    def notified(self):
        """After the commit: the alert thread sends at once, never this request."""
        if self.notifier:
            self.notifier.wake()

    def prices(self, listing_ids):
        """Check the choice now; read each card's price inside the request's transaction."""
        if not listing_ids or len(listing_ids) != len(set(listing_ids)):
            raise ValueError("Choisissez des cartes distinctes.")

        def read(db):
            self.expire(db)
            prices = {}
            for listing_id in listing_ids:
                rows = self.storefront.rows(db, listing_id)
                if not rows:
                    raise Conflict("Une carte n’est plus disponible : actualisez la vitrine.")
                prices[listing_id] = rows[0]["price_cents"]
            return prices

        return read

    def insert(self, db, client_id, prices, message, limit):
        open_count = db.execute(
            "SELECT COUNT(*) FROM requests WHERE client_id=? AND status='sent'",
            (client_id,),
        ).fetchone()[0]
        if open_count >= limit:
            raise Conflict("Trop de demandes en attente : attendez une réponse du vendeur.")
        timestamp = datetime.now(timezone.utc)
        request = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "status": "sent",
            "message": message.strip(),
            "created_at": timestamp.isoformat(),
            "updated_at": timestamp.isoformat(),
            "expires_at": (timestamp + EXPIRY).isoformat(),
        }
        db.execute(
            "INSERT INTO requests(" + ",".join(request) + ") VALUES("
            + ",".join("?" for _ in request) + ")",
            list(request.values()),
        )
        db.executemany(
            "INSERT INTO request_items(request_id,listing_id,price_cents) VALUES(?,?,?)",
            [(request["id"], l, p) for l, p in prices.items()],
        )
        if self.notifier:
            self.notifier.enqueue(db, request["id"], timestamp)
        return self.describe(db, db.execute("SELECT * FROM requests WHERE id=?", (request["id"],)).fetchone())

    def cancel(self, client_id, request_id, version):
        with self.store.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=? AND client_id=?", (request_id, client_id)
            ).fetchone()
            if not row:
                raise KeyError("Demande introuvable.")
            if row["version"] != version:
                raise Conflict("La demande a changé. Actualisez la page.")
            if row["status"] != "sent":
                raise Conflict("Seule une demande en attente peut être annulée.")
            db.execute(
                "UPDATE requests SET status='cancelled',updated_at=?,version=version+1 WHERE id=?",
                (now(), request_id),
            )
            return self.describe(db, db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone())

    def all(self):
        with self.store.connect(write=True) as db:
            self.expire(db)
            result = []
            for row in db.execute(
                "SELECT r.*,u.email,u.display_name,u.status AS client_status FROM requests r JOIN users u ON u.id=r.client_id "
                "ORDER BY CASE r.status WHEN 'sent' THEN 0 ELSE 1 END, r.created_at DESC"
            ).fetchall():
                request = self.describe(db, row, staff=True)
                result.append(request)
            return result

    def refuse(self, request_id, version, actor, reason):
        if not reason.strip():
            raise ValueError("Précisez le motif.")
        with self.store.connect(write=True) as db:
            self.expire(db)
            row = self.pending(db, request_id, version)
            db.execute(
                "UPDATE requests SET status='refused',decision=?,updated_at=?,version=version+1 WHERE id=?",
                (reason.strip(), now(), request_id),
            )
            db.execute("UPDATE request_items SET outcome='refused' WHERE request_id=?", (request_id,))
            self.log(db, row, actor, "refused", reason)
        return {"ok": True}

    def pending(self, db, request_id, version):
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise KeyError("Demande introuvable.")
        if row["version"] != version:
            raise Conflict("La demande a changé. Rechargez-la.")
        if row["status"] != "sent":
            raise Conflict("Cette demande a déjà reçu une réponse ou a expiré.")
        return row

    def log(self, db, row, actor, decision, reason):
        for (listing_id,) in db.execute(
            "SELECT listing_id FROM request_items WHERE request_id=?", (row["id"],)
        ).fetchall():
            for card in self.storefront.cards(db, listing_id):
                db.execute(
                    "INSERT INTO events(copy_id,actor,kind,reason,before_json,after_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (card["id"], actor, "storefront-request", reason, "{}",
                     json.dumps({"request_id": row["id"], "decision": decision}), now()),
                )

    def accept(self, request_id, version, listing_ids, actor):
        """Accept all or part of a request: the chosen cards become a reserved lot."""
        with self.store.connect(write=True) as db:
            self.expire(db)
            row = self.pending(db, request_id, version)
            client = db.execute(
                "SELECT email,display_name FROM users WHERE id=?", (row["client_id"],)
            ).fetchone()
            items = {
                r["listing_id"]: r["price_cents"]
                for r in db.execute(
                    "SELECT listing_id,price_cents FROM request_items WHERE request_id=?", (request_id,)
                )
            }
            chosen = [l for l in listing_ids if l in items]
            if not chosen or len(chosen) != len(set(listing_ids)):
                raise ValueError("Choisissez des cartes de cette demande.")
            unavailable = [l for l in chosen if not self.storefront.rows(db, l)]
            if unavailable:
                raise Conflict("Une carte choisie n’est plus disponible : retirez-la de l’acceptation.")
            copy_ids = [c["id"] for l in chosen for c in self.storefront.cards(db, l)]
            delivery, registered, clean_msg = extract_delivery_mode(row["message"])
            accepted_amount = sum(items[l] for l in chosen)
            accepted_card_count = len(copy_ids)
            ship_cents = shipping_cents(accepted_card_count, accepted_amount, delivery=delivery, registered=registered)
            title = f"Vitrine · {client['display_name'] or client['email']}"
            sale_id = self.store.create_sale(
                {
                    "title": title[:256],
                    "channel": "Vitrine",
                    "notes": f"Demande {request_id} de {client['email']}."
                    + (f"\nMessage : {clean_msg}" if clean_msg else ""),
                    "amount_cents": accepted_amount,
                    "asking_cents": accepted_amount,
                    "shipping_charged_cents": ship_cents,
                },
                copy_ids,
                actor,
                _db=db,
            )
            sale_version = db.execute("SELECT version FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
            try:
                self.store.update_sale(
                    sale_id, {"status": "reserved", "shipping_charged_cents": ship_cents}, sale_version, actor,
                    "Demande de la vitrine acceptée", _db=db,
                )
            except Conflict:
                # The rollback drops the draft too: the request stays open, nothing is left.
                raise Conflict("Un exemplaire vient d’être réservé ailleurs : rechargez la demande.") from None
            status = "accepted" if set(chosen) == set(items) else "partially_accepted"
            db.execute(
                "UPDATE requests SET status=?,sale_id=?,updated_at=?,version=version+1 WHERE id=?",
                (status, sale_id, now(), request_id),
            )
            for listing_id in items:
                db.execute(
                    "UPDATE request_items SET outcome=? WHERE request_id=? AND listing_id=?",
                    ("accepted" if listing_id in chosen else "refused", request_id, listing_id),
                )
            self.log(db, row, actor, status, "Demande de la vitrine acceptée")
            # Accepting means the seller writes to the client: that is the account's validation.
            db.execute(
                "UPDATE users SET status='active' WHERE id=? AND status='pending'", (row["client_id"],)
            )
        return {"ok": True, "sale_id": sale_id, "status": status}
