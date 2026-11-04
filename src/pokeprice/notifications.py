"""Seller alerts for storefront requests: ntfy, an e-mail (SMTP) and Web Push.

Each channel is off unless its environment variables are set. An alert says
how many cards, the total and the link to the request in /gestion: never the
client's name, address or message. Alerts wait in the database (table
``notifications``), so a restart loses nothing; a background thread sends
them with retries and never holds an HTTP response.
"""

import base64
import json
import logging
import os
import re
import smtplib
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit

log = logging.getLogger("pokeprice.notifications")

# Schema 22: the outbox. Only ids, kinds and dates: no personal data.
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL, kind TEXT NOT NULL, channel TEXT NOT NULL,
 due_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 sent_at TEXT, given_up_at TEXT, error TEXT NOT NULL DEFAULT '',
 UNIQUE(request_id, kind, channel));
CREATE INDEX IF NOT EXISTS notifications_due ON notifications(due_at)
 WHERE sent_at IS NULL AND given_up_at IS NULL;
PRAGMA user_version=22;
COMMIT;
"""
# A new request at once, then reminders while it is still waiting.
KINDS = {"new": timedelta(0), "reminder-2": timedelta(days=2), "reminder-5": timedelta(days=5)}
RETRIES = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30),
           timedelta(hours=2), timedelta(hours=6))
LEASE = timedelta(minutes=5)  # A row being sent is not taken by another process.
KEEP = timedelta(days=30)
TIMEOUT = 15


def euros(cents):
    return f"{cents / 100:.2f} €".replace(".", ",")


def alert_text(kind, cards, total_cents, link):
    """Title and body of an alert; nothing in it identifies the client."""
    plural = "s" if cards > 1 else ""
    if kind == "new":
        title = f"Nouvelle demande : {cards} carte{plural}, {euros(total_cents)}"
    else:
        days = kind.split("-")[1]
        title = f"Rappel J+{days} : demande en attente ({cards} carte{plural}, {euros(total_cents)})"
    body = f"{title}.\nAccepter ou refuser : {link}"
    return title, body


class Ntfy:
    """Push without an account: the topic's URL is the secret."""

    name = "ntfy"

    def __init__(self, url, token="", opener=None):
        self.url, self.token = url, token
        self.opener = opener or urllib.request.urlopen

    def send(self, title, body, link):
        headers = {"Title": title.encode("utf-8"), "Click": link, "Tags": "cards",
                   "Actions": f"view, Ouvrir la demande, {link}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.url, data=body.encode(), headers=headers, method="POST")
        with self.opener(request, timeout=TIMEOUT) as response:
            if not 200 <= response.status < 300:
                raise OSError(f"ntfy HTTP {response.status}")


class Mail:
    name = "email"

    def __init__(self, host, port, sender, recipient, user="", password="", security="starttls",
                 smtp=None):
        self.host, self.port, self.sender, self.recipient = host, port, sender, recipient
        self.user, self.password, self.security = user, password, security
        self.smtp = smtp or (smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP)

    def send(self, title, body, link):
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = title, self.sender, self.recipient
        message.set_content(body)
        with self.smtp(self.host, self.port, timeout=TIMEOUT) as server:
            if self.security == "starttls":
                server.starttls()
            if self.user:
                server.login(self.user, self.password)
            server.send_message(message)


# Schema 25: Web Push subscriptions of management accounts, decision 0033.
# The push service's endpoint, the browser's two keys and the account: nothing else.
PUSH_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS push_subscriptions(endpoint TEXT PRIMARY KEY,
 p256dh TEXT NOT NULL, auth TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id));
CREATE INDEX IF NOT EXISTS push_subscriptions_user ON push_subscriptions(user_id);
PRAGMA user_version=25;
COMMIT;
"""
# The browsers' push services. The server only ever posts to these hosts, so a
# subscription can never turn it into a client for an arbitrary address.
PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com",
              "notify.windows.com")
PUSH_TIMEOUT = 10
PUSH_TTL = 12 * 3600  # A phone that is off still gets the morning brief at noon.
PUSH_BODY = 180
STAFF = ("admin", "editor", "reader")
B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64url_bytes(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def vapid_keys():
    """A new VAPID pair (P-256), base64url: the public point and the private scalar."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return b64url(public), b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def push_host_allowed(host):
    host = (host or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in PUSH_HOSTS)


def check_subscription(endpoint, p256dh, auth):
    """A browser subscription, or ValueError: HTTPS on a known push service, sane keys."""
    parts = urlsplit(endpoint or "")
    if (parts.scheme != "https" or len(endpoint) > 1024 or parts.username or parts.password
            or not push_host_allowed(parts.hostname)):
        raise ValueError("Service de notification inconnu.")
    try:
        point, secret = b64url_bytes(p256dh), b64url_bytes(auth)
    except (ValueError, TypeError):
        point = secret = b""
    if not (B64URL.match(p256dh or "") and B64URL.match(auth or "")
            and len(point) == 65 and point[0] == 4 and len(secret) == 16):
        raise ValueError("Clés de notification invalides.")


def subscribe(store, user_id, endpoint, p256dh, auth):
    check_subscription(endpoint, p256dh, auth)
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO push_subscriptions(endpoint,p256dh,auth,user_id) VALUES(?,?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth,"
            "user_id=excluded.user_id",
            (endpoint, p256dh, auth, user_id),
        )


def unsubscribe(store, user_id, endpoint):
    """Only the account's own subscription; True when one was removed."""
    with store.connect(write=True) as db:
        return db.execute(
            "DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?", (endpoint, user_id)
        ).rowcount > 0


def subscribed(store, user_id, endpoint):
    with store.connect() as db:
        return bool(db.execute(
            "SELECT 1 FROM push_subscriptions WHERE endpoint=? AND user_id=?", (endpoint, user_id)
        ).fetchone())


def push_payload(title, body, link):
    """What the phone shows: the short title and text already sent, and a /gestion path.

    Links are taken out of the text (the tap opens the page); the path keeps
    only /gestion and its query, so the push service never sees the origin.
    """
    text = re.sub(r"\s*:?\s*https?://\S+", "", body or "")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and line.rstrip(".") != title.rstrip(".")]
    text = "\n".join(lines)
    if len(text) > PUSH_BODY:
        text = text[: PUSH_BODY - 1].rstrip() + "…"
    parts = urlsplit(link or "")
    path = parts.path or "/gestion"
    url = path + (f"?{parts.query}" if parts.query else "")
    if path != "/gestion" and not path.startswith("/gestion/"):
        url = "/gestion"
    return json.dumps({"title": title, "body": text, "url": url}, ensure_ascii=False)


class WebPush:
    """Web Push to the management accounts' phones, signed with the VAPID key.

    A subscription the push service calls gone (404, 410) is deleted. The send
    counts as done when at least one phone, or none at all, was reached; it
    only fails, and is retried, when every subscription failed.
    """

    name = "webpush"

    def __init__(self, store, public_key, private_key, subject, sender=None, timeout=PUSH_TIMEOUT):
        self.store, self.public_key, self.subject = store, public_key, subject
        self.private_key, self.sender, self.timeout = private_key, sender, timeout
        self.vapid = None

    def subscriptions(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT p.endpoint,p.p256dh,p.auth FROM push_subscriptions p "
                "JOIN users u ON u.id=p.user_id WHERE u.role IN (?,?,?) AND u.disabled=0 "
                "AND u.status='active'", STAFF,
            ).fetchall()]

    def send(self, title, body, link):
        rows = self.subscriptions()
        if not rows:
            return 0
        sender = self.sender
        if sender is None:
            from pywebpush import webpush as sender
        if self.vapid is None:
            from py_vapid import Vapid

            self.vapid = Vapid.from_string(self.private_key)
        data = push_payload(title, body, link)
        sent, failures, gone = 0, [], []
        for row in rows:
            try:
                sender(
                    subscription_info={"endpoint": row["endpoint"],
                                       "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                    data=data, vapid_private_key=self.vapid,
                    # A fresh dict: pywebpush writes "aud" and "exp" into it.
                    vapid_claims={"sub": self.subject},
                    timeout=self.timeout, ttl=PUSH_TTL,
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001 - one phone never stops the others.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    gone.append(row["endpoint"])
                else:
                    # Never the endpoint: it is the phone's address at the push service.
                    failures.append(f"{type(exc).__name__}{f' {status}' if status else ''}")
        if gone:
            with self.store.connect(write=True) as db:
                db.executemany("DELETE FROM push_subscriptions WHERE endpoint=?",
                               [(endpoint,) for endpoint in gone])
            log.info("%s abonnement(s) Web Push expiré(s) supprimé(s).", len(gone))
        if failures and not sent:
            raise OSError("Web Push : " + ", ".join(sorted(set(failures))))
        if failures:
            log.warning("Web Push : %s téléphone(s) non joint(s) sur %s.", len(failures), len(rows))
        return sent


def webpush_from_env(env, store):
    public = env.get("POKEPRICE_VAPID_PUBLIC_KEY", "").strip()
    private = env.get("POKEPRICE_VAPID_PRIVATE_KEY", "").strip()
    subject = env.get("POKEPRICE_VAPID_SUBJECT", "").strip()
    if not (store is not None and public and private
            and (subject.startswith("mailto:") or subject.startswith("https://"))):
        return None
    return WebPush(store, public, private, subject)


def channels_from_env(env=None, store=None):
    """The configured channels; a missing variable switches its channel off.

    Web Push also needs the store, where the subscriptions are.
    """
    env = os.environ if env is None else env
    channels = []
    url = env.get("POKEPRICE_NTFY_URL", "").strip()
    if url.startswith("https://") or url.startswith("http://localhost"):
        channels.append(Ntfy(url, env.get("POKEPRICE_NTFY_TOKEN", "").strip()))
    host = env.get("POKEPRICE_SMTP_HOST", "").strip()
    sender = env.get("POKEPRICE_SMTP_FROM", "").strip()
    recipient = (env.get("POKEPRICE_NOTIFY_EMAIL", "") or env.get("POKEPRICE_CONTACT_EMAIL", "")).strip()
    if host and sender and recipient:
        security = env.get("POKEPRICE_SMTP_SECURITY", "starttls").strip().lower()
        if security not in ("starttls", "ssl", "none"):
            security = "starttls"
        default_port = {"ssl": 465, "starttls": 587, "none": 25}[security]
        channels.append(Mail(
            host, int(env.get("POKEPRICE_SMTP_PORT", "") or default_port), sender, recipient,
            env.get("POKEPRICE_SMTP_USER", "").strip(), env.get("POKEPRICE_SMTP_PASSWORD", ""),
            security,
        ))
    if push := webpush_from_env(env, store):
        channels.append(push)
    return channels


def iso(moment):
    return moment.isoformat()


class Notifier:
    """The outbox: enqueue inside the request's transaction, send from a thread."""

    def __init__(self, store, channels, origin="", clock=None):
        self.store, self.channels, self.origin = store, list(channels), origin.rstrip("/")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.wakeup = threading.Event()
        self.thread = None
        self.stopping = False
        self.autostart = True

    @property
    def enabled(self):
        return bool(self.channels)

    def link(self, request_id):
        return f"{self.origin}/gestion?demande={request_id}"

    def enqueue(self, db, request_id, created_at=None):
        """Called inside the transaction that creates the request."""
        start = created_at or self.clock()
        for kind, delay in KINDS.items():
            for channel in self.channels:
                db.execute(
                    "INSERT OR IGNORE INTO notifications(id,request_id,kind,channel,due_at) "
                    "VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), request_id, kind, channel.name, iso(start + delay)),
                )

    def wake(self):
        self.wakeup.set()

    def claim(self):
        """Take the due rows: each one is leased so that one process sends it."""
        moment = self.clock()
        with self.store.connect(write=True) as db:
            db.execute(
                "DELETE FROM notifications WHERE (sent_at IS NOT NULL OR given_up_at IS NOT NULL) "
                "AND due_at<?", (iso(moment - KEEP),),
            )
            rows = [dict(r) for r in db.execute(
                "SELECT n.*,r.status,r.expires_at FROM notifications n "
                "LEFT JOIN requests r ON r.id=n.request_id "
                "WHERE n.sent_at IS NULL AND n.given_up_at IS NULL AND n.due_at<=? "
                "ORDER BY n.due_at LIMIT 20", (iso(moment),),
            ).fetchall()]
            due = []
            for row in rows:
                # A reminder only makes sense while the request still waits.
                if row["status"] != "sent" or (row["expires_at"] or "") < iso(moment):
                    db.execute("UPDATE notifications SET given_up_at=?,error='sans objet' WHERE id=?",
                               (iso(moment), row["id"]))
                    continue
                count, total = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(price_cents),0) FROM request_items WHERE request_id=?",
                    (row["request_id"],),
                ).fetchone()
                db.execute("UPDATE notifications SET due_at=?,attempts=attempts+1 WHERE id=?",
                           (iso(moment + LEASE), row["id"]))
                due.append({**row, "attempts": row["attempts"] + 1, "cards": count, "total": total})
            return due

    def run_due(self):
        """Send what is due; return how many alerts went out."""
        channels = {c.name: c for c in self.channels}
        sent = 0
        for row in self.claim():
            channel = channels.get(row["channel"])
            moment = self.clock()
            if channel is None:  # Switched off since: nothing to send.
                result = ("given_up_at", iso(moment), "canal désactivé")
            else:
                link = self.link(row["request_id"])
                title, body = alert_text(row["kind"], row["cards"], row["total"], link)
                try:
                    channel.send(title, body, link)
                    result = ("sent_at", iso(moment), "")
                    sent += 1
                except Exception as exc:  # noqa: BLE001 - any failure is retried.
                    # The error's class only: a message could echo an address.
                    error = type(exc).__name__
                    log.warning("Alerte %s non envoyée (essai %s) : %s",
                                row["channel"], row["attempts"], error)
                    if row["attempts"] > len(RETRIES):
                        result = ("given_up_at", iso(moment), error)
                    else:
                        with self.store.connect(write=True) as db:
                            db.execute(
                                "UPDATE notifications SET due_at=?,error=? WHERE id=?",
                                (iso(moment + RETRIES[row["attempts"] - 1]), error, row["id"]),
                            )
                        continue
            with self.store.connect(write=True) as db:
                db.execute(f"UPDATE notifications SET {result[0]}=?,error=? WHERE id=?",
                           (result[1], result[2], row["id"]))
        return sent

    def start(self, interval=60):
        if not (self.enabled and self.autostart) or self.thread:
            return
        self.stopping = False

        def loop():
            while not self.stopping:
                try:
                    self.run_due()
                except Exception:  # noqa: BLE001 - the loop must survive a bad turn.
                    log.exception("File des alertes interrompue ; reprise au prochain tour.")
                self.wakeup.wait(interval)
                self.wakeup.clear()

        self.thread = threading.Thread(target=loop, name="pokeprice-alerts", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping = True
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
