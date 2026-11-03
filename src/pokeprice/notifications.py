"""Seller alerts for storefront requests: a push (ntfy) and an e-mail (SMTP).

Each channel is off unless its environment variables are set. An alert says
how many cards, the total and the link to the request in /gestion: never the
client's name, address or message. Alerts wait in the database (table
``notifications``), so a restart loses nothing; a background thread sends
them with retries and never holds an HTTP response.
"""

import logging
import os
import smtplib
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

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


def channels_from_env(env=None):
    """The configured channels; a missing variable switches its channel off."""
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
