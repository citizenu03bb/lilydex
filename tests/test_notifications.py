"""Seller alerts: simulated channels only, no network and no key."""

from basket_helpers import accepted_prices
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from test_reservations import shop  # noqa: F401 - the shared fixture.

from pokeprice import notifications
from pokeprice.notifications import Mail, Notifier, Ntfy, alert_text, channels_from_env

GUEST = {"email": "sacha+alerte@example.org", "display_name": "Sacha Secret",
         "message": "Mon adresse : 12 rue Privée", "consent": True}


class Fake:
    def __init__(self, name="ntfy", fail=0):
        self.name, self.fail, self.sent = name, fail, []

    def send(self, title, body, link):
        if self.fail:
            self.fail -= 1
            raise OSError("réseau coupé pour sacha+alerte@example.org")
        self.sent.append((title, body, link))


class Clock:
    def __init__(self):
        self.moment = datetime.now(timezone.utc) + timedelta(seconds=5)

    def __call__(self):
        return self.moment


def wire(store, app, channels, clock=None):
    """Swap the app's notifier for one with simulated channels."""
    notifier = app.state.notifier
    notifier.channels = channels
    notifier.autostart = False  # The tests run the queue themselves.
    notifier.origin = "https://cartes.example"
    if clock:
        notifier.clock = clock
    return notifier


def guest_request(store, listing_ids, app_factory):
    with TestClient(app_factory(store.root)) as visitor:
        return visitor.post("/api/public/requests", json={**GUEST, "listing_ids": listing_ids, "expected_prices": accepted_prices(store, listing_ids)})


def test_channels_are_off_unless_configured():
    assert channels_from_env({}) == []
    assert channels_from_env({"POKEPRICE_NTFY_URL": "pas une url"}) == []
    # SMTP needs a host, a sender and a recipient.
    assert channels_from_env({"POKEPRICE_SMTP_HOST": "smtp.example"}) == []
    channels = channels_from_env({
        "POKEPRICE_NTFY_URL": "https://ntfy.sh/sujet-secret",
        "POKEPRICE_SMTP_HOST": "smtp.example", "POKEPRICE_SMTP_FROM": "site@example.org",
        "POKEPRICE_CONTACT_EMAIL": "vendeur@example.org", "POKEPRICE_SMTP_SECURITY": "ssl",
    })
    assert [c.name for c in channels] == ["ntfy", "email"]
    assert channels[1].port == 465 and channels[1].recipient == "vendeur@example.org"


def test_alert_text_has_count_total_and_link_only():
    title, body = alert_text("new", 3, 550, "https://cartes.example/gestion?demande=abc")
    assert title == "Nouvelle demande : 3 cartes, 5,50 €"
    assert body.endswith("https://cartes.example/gestion?demande=abc")
    assert alert_text("reminder-2", 1, 120, "x")[0].startswith("Rappel J+2")


def test_new_request_alerts_without_client_data(shop, monkeypatch):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    push, mail, apps = Fake(), Fake("email"), []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [push, mail])
        apps.append(app)
        return app

    response = guest_request(store, [listings[0]["id"], listings[1]["id"]], factory)
    assert response.status_code == 202
    assert apps[0].state.notifier.run_due() == 2
    for title, body, link in push.sent + mail.sent:
        assert title == "Nouvelle demande : 2 cartes, 4,70 €"
        assert link.startswith("https://cartes.example/gestion?demande=")
        for secret in ("sacha", "Sacha", "Privée", "example.org"):
            assert secret not in title + body
    # Sent once only.
    assert apps[0].state.notifier.run_due() == 0


def test_reminders_at_day_two_and_five_while_waiting(shop):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    push, clock, apps = Fake(), Clock(), []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [push], clock)
        apps.append(app)
        return app

    guest_request(store, [listings[0]["id"]], factory)
    notifier = apps[0].state.notifier
    assert notifier.run_due() == 1
    clock.moment += timedelta(days=2, minutes=1)
    assert notifier.run_due() == 1 and push.sent[-1][0].startswith("Rappel J+2")
    clock.moment += timedelta(days=3)
    assert notifier.run_due() == 1 and push.sent[-1][0].startswith("Rappel J+5")
    assert len(push.sent) == 3


def test_no_reminder_once_answered(shop):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    push, clock, apps = Fake(), Clock(), []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [push], clock)
        apps.append(app)
        return app

    guest_request(store, [listings[0]["id"]], factory)
    notifier = apps[0].state.notifier
    notifier.run_due()
    request = admin.get("/api/requests").json()[0]
    assert admin.post(f"/api/requests/{request['id']}/refuse",
                      json={"expected_version": request["version"], "reason": "Non"}).status_code == 200
    clock.moment += timedelta(days=6)
    assert notifier.run_due() == 0 and len(push.sent) == 1


def test_failures_are_retried_then_given_up_without_logging_data(shop, caplog):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    push, clock, apps = Fake(fail=1), Clock(), []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [push], clock)
        apps.append(app)
        return app

    guest_request(store, [listings[0]["id"]], factory)
    notifier = apps[0].state.notifier
    assert notifier.run_due() == 0
    assert "sacha" not in caplog.text and "OSError" in caplog.text
    assert notifier.run_due() == 0  # Not due yet: the retry waits a minute.
    clock.moment += timedelta(minutes=2)
    assert notifier.run_due() == 1

    broken = Fake(fail=100)
    notifier.channels = [broken]
    with store.connect(write=True) as db:
        db.execute("UPDATE notifications SET sent_at=NULL")
    for _ in range(len(notifications.RETRIES) + 2):
        clock.moment += timedelta(hours=7)
        notifier.run_due()
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM notifications WHERE given_up_at IS NULL "
                          "AND sent_at IS NULL AND kind='new'").fetchone()[0] == 0


def test_disabled_channel_queues_nothing(shop):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    apps = []

    def factory(root):
        app = webapp.create_app(root)
        apps.append(app)
        return app

    assert guest_request(store, [listings[0]["id"]], factory).status_code == 202
    assert not apps[0].state.notifier.enabled
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_ntfy_and_smtp_requests_are_built_without_network():
    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        seen["url"], seen["headers"], seen["data"] = request.full_url, dict(request.headers), request.data
        return Response()

    Ntfy("https://ntfy.example/sujet", "jeton", opener).send("Titre é", "Corps", "https://x/gestion")
    assert seen["url"] == "https://ntfy.example/sujet" and seen["data"] == b"Corps"
    assert seen["headers"]["Click"] == "https://x/gestion"
    assert seen["headers"]["Authorization"] == "Bearer jeton"

    calls = []

    class SMTP:
        def __init__(self, host, port, timeout):
            calls.append(("open", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"]))

    Mail("smtp.example", 587, "site@example.org", "vendeur@example.org", "u", "p", smtp=SMTP).send(
        "Titre", "Corps", "lien")
    assert calls == [("open", "smtp.example", 587), "starttls", ("login", "u"),
                     ("send", "vendeur@example.org", "Titre")]


def test_http_answer_does_not_wait_for_sending(shop):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    class Slow(Fake):
        def send(self, *args):
            raise AssertionError("never sent in the request")

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [Slow()])
        return app

    # The request answers; sending is left to the thread (not started here).
    assert guest_request(store, [listings[0]["id"]], factory).status_code == 202


@pytest.fixture(autouse=True)
def no_alert_environment(monkeypatch):
    for name in ("POKEPRICE_NTFY_URL", "POKEPRICE_SMTP_HOST"):
        monkeypatch.delenv(name, raising=False)


def test_a_public_request_queues_alerts_without_client_data(shop):  # noqa: F811
    admin, store, listings = shop
    from pokeprice import webapp

    apps = []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [Fake(), Fake("email")])
        apps.append(app)
        return app

    assert guest_request(store, [listings[0]["id"]], factory).status_code == 202
    assert apps[0].state.notifier.enabled
    with store.connect() as db:
        rows = db.execute(
            "SELECT * FROM notifications ORDER BY channel, kind").fetchall()
        columns = rows[0].keys()
    # Three kinds on two channels, none sent yet, and only ids, kinds and dates.
    assert [(r["channel"], r["kind"]) for r in rows] == [
        (channel, kind) for channel in ("email", "ntfy")
        for kind in ("new", "reminder-2", "reminder-5")]
    assert all(r["sent_at"] is None and r["attempts"] == 0 for r in rows)
    assert set(columns) == {"id", "request_id", "kind", "channel", "due_at", "attempts",
                            "sent_at", "given_up_at", "error"}
    dump = " ".join(str(value) for r in rows for value in tuple(r))
    for secret in ("sacha", "Sacha", "Privée", "example.org"):
        assert secret not in dump
