"""Web Push of the management (decision 0033): disposable keys, no network."""

import base64
import io
import json
import os
import shutil
import stat
import subprocess
from functools import partial
from pathlib import Path

import http_ece
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from pywebpush import WebPushException, webpush
from test_notifications import GUEST, Fake, guest_request, wire
from test_reservations import activate, client_of, shop, signup  # noqa: F401 - shared fixture.

from pokeprice import notifications
from pokeprice.inventory import SCHEMA_VERSION, Store
from pokeprice.manage import send_brief, write_vapid_keys
from pokeprice.notifications import (
    PUSH_TIMEOUT, WebPush, channels_from_env, push_payload, vapid_keys,
)
from pokeprice.webapp import create_app

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://fcm.googleapis.com/fcm/send/telephone-de-test"
STAFF_PASSWORD = "Collection-test-2026!"


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Browser:
    """A phone's side of a subscription: its key pair and auth secret."""

    def __init__(self, endpoint=ENDPOINT):
        self.endpoint = endpoint
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    def json(self):
        point = self.key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64(point), "auth": b64(self.auth)}}

    def decrypt(self, body):
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth,
                                           version="aes128gcm"))


@pytest.fixture
def vapid(monkeypatch):
    """Disposable keys in the environment; no alert thread, no real push service."""
    import pywebpush

    def offline(**kwargs):
        raise AssertionError("a test never reaches a real push service")

    monkeypatch.setattr(pywebpush, "webpush", offline)
    monkeypatch.setattr(notifications.Notifier, "start", lambda self, interval=60: None)
    public, private = vapid_keys()
    monkeypatch.setenv("POKEPRICE_VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("POKEPRICE_VAPID_PRIVATE_KEY", private)
    monkeypatch.setenv("POKEPRICE_VAPID_SUBJECT", "mailto:operateur@example.test")
    return public, private


@pytest.fixture
def pushed(vapid, shop):  # noqa: F811
    """The shop, its app rebuilt with the VAPID keys of this test."""
    _, store, listings = shop
    with TestClient(create_app(store.root)) as admin:
        assert admin.post("/api/login", json={"username": "pat", "password": STAFF_PASSWORD}).status_code == 200
        yield admin, store, listings


def channel(store, sender):
    public, private = vapid_keys()
    return WebPush(store, public, private, "mailto:operateur@example.test", sender=sender)


def rows(store):
    with store.connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM push_subscriptions ORDER BY endpoint")]


def staff_member(admin, store, username, role="reader"):
    assert admin.post("/api/users", json={"username": username, "password": STAFF_PASSWORD,
                                          "role": role}).status_code == 201
    member = TestClient(create_app(store.root))
    member.__enter__()
    assert member.post("/api/login", json={"username": username, "password": STAFF_PASSWORD}).status_code == 200
    return member


# --- Keys -------------------------------------------------------------------


def test_vapid_keys_are_a_p256_pair_written_once_in_a_private_file(tmp_path):
    public, private = vapid_keys()
    point = base64.urlsafe_b64decode(public + "==")
    assert len(point) == 65 and point[0] == 4
    assert len(base64.urlsafe_b64decode(private + "=")) == 32
    output = tmp_path / "vapid.env"
    shown = io.StringIO()
    written = write_vapid_keys(str(output), "mailto:operateur@example.test", stdout=shown)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    lines = output.read_text().splitlines()
    assert [line.split("=", 1)[0] for line in lines] == [
        "POKEPRICE_VAPID_PUBLIC_KEY", "POKEPRICE_VAPID_PRIVATE_KEY", "POKEPRICE_VAPID_SUBJECT"]
    assert lines[0] == f"POKEPRICE_VAPID_PUBLIC_KEY={written}"
    # The private key is in the file only, never in what the terminal shows.
    assert lines[1].split("=", 1)[1] not in shown.getvalue()
    with pytest.raises(FileExistsError):
        write_vapid_keys(str(output))
    assert output.read_text().splitlines() == lines
    with pytest.raises(ValueError):
        write_vapid_keys(None, "operateur@example.test", stdout=io.StringIO())


def test_vapid_keys_command_prints_the_pair_once(monkeypatch, capsys):
    from pokeprice import manage

    monkeypatch.setattr("sys.argv", ["pokeprice-manage", "vapid-keys"])
    manage.main()
    printed = capsys.readouterr().out.splitlines()
    assert [line.split("=", 1)[0] for line in printed] == [
        "POKEPRICE_VAPID_PUBLIC_KEY", "POKEPRICE_VAPID_PRIVATE_KEY"]
    manage.main()
    assert capsys.readouterr().out.splitlines() != printed  # A new pair each time, stored nowhere.


def test_web_push_is_a_channel_only_with_keys_subject_and_store(tmp_path):
    store = Store(tmp_path / "inventory")
    public, private = vapid_keys()
    keys = {"POKEPRICE_VAPID_PUBLIC_KEY": public, "POKEPRICE_VAPID_PRIVATE_KEY": private,
            "POKEPRICE_VAPID_SUBJECT": "mailto:operateur@example.test"}
    assert channels_from_env(keys) == []  # No store, no subscriptions to read.
    assert channels_from_env({**keys, "POKEPRICE_VAPID_SUBJECT": "operateur"}, store) == []
    assert channels_from_env({**keys, "POKEPRICE_VAPID_PRIVATE_KEY": ""}, store) == []
    channels = channels_from_env({**keys, "POKEPRICE_NTFY_URL": "https://ntfy.sh/sujet"}, store)
    assert [c.name for c in channels] == ["ntfy", "webpush"]
    assert channels[1].public_key == public


# --- Schema -------------------------------------------------------------------


def test_schema_25_adds_the_subscriptions_table_after_a_snapshot(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("DROP TABLE push_subscriptions")
        db.execute("PRAGMA user_version=24")
    migrated = Store(store.root)
    with migrated.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 25
        columns = [r[1] for r in db.execute("PRAGMA table_info(push_subscriptions)")]
    # The endpoint, the browser's keys and the account: nothing else.
    assert columns == ["endpoint", "p256dh", "auth", "user_id"]
    assert list((tmp_path / "backups").glob(f"before-schema{SCHEMA_VERSION}-from24-*"))


# --- Subscriptions -----------------------------------------------------------


def test_a_management_account_subscribes_and_unsubscribes_its_phone(pushed, vapid):
    admin, store, _ = pushed
    assert admin.get("/api/push").json() == {"enabled": True, "public_key": vapid[0]}
    phone = Browser().json()
    assert admin.post("/api/push/subscriptions", json=phone).status_code == 201
    assert admin.post("/api/push/subscriptions", json=phone).status_code == 201  # Idempotent.
    [row] = rows(store)
    assert set(row) == {"endpoint", "p256dh", "auth", "user_id"}
    assert row["endpoint"] == ENDPOINT and row["p256dh"] == phone["keys"]["p256dh"]
    check = {"endpoint": ENDPOINT}
    assert admin.post("/api/push/subscriptions/check", json=check).json() == {"subscribed": True}
    assert admin.request("DELETE", "/api/push/subscriptions", json=check).json() == {"removed": True}
    assert rows(store) == []
    assert admin.request("DELETE", "/api/push/subscriptions", json=check).json() == {"removed": False}
    assert admin.post("/api/push/subscriptions/check", json=check).json() == {"subscribed": False}


def test_only_logged_in_management_accounts_reach_the_subscriptions(pushed):
    admin, store, _ = pushed
    phone = Browser().json()
    with TestClient(create_app(store.root)) as anonymous:
        assert anonymous.get("/api/push").status_code == 401
        assert anonymous.post("/api/push/subscriptions", json=phone).status_code == 401
        assert anonymous.request("DELETE", "/api/push/subscriptions",
                                 json={"endpoint": ENDPOINT}).status_code == 401
    signup(store, "sacha+push@example.org")
    activate(admin, "sacha+push@example.org")
    customer = client_of(store, "sacha+push@example.org")
    assert customer.get("/api/push").status_code == 403
    assert customer.post("/api/push/subscriptions", json=phone).status_code == 403
    customer.__exit__(None, None, None)
    assert rows(store) == []
    # A reader is a management account: its own phone, which no one else removes.
    reader = staff_member(admin, store, "lecture")
    assert reader.post("/api/push/subscriptions", json=phone).status_code == 201
    assert admin.request("DELETE", "/api/push/subscriptions",
                         json={"endpoint": ENDPOINT}).json() == {"removed": False}
    assert len(rows(store)) == 1
    reader.__exit__(None, None, None)
    # Another site cannot subscribe a phone through a logged-in browser.
    other = admin.post("/api/push/subscriptions", json=Browser().json(),
                       headers={"Origin": "https://ailleurs.example"})
    assert other.status_code == 403


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",            # Not HTTPS.
    "https://127.0.0.1/push",                          # Not a push service.
    "https://fcm.googleapis.com.evil.example/x",       # A look-alike host.
    "https://user:pw@web.push.apple.com/x",            # Credentials in the URL.
])
def test_a_subscription_goes_to_a_known_push_service_only(pushed, endpoint):
    admin, store, _ = pushed
    response = admin.post("/api/push/subscriptions", json=Browser(endpoint).json())
    assert response.status_code == 422
    for keys in ({"p256dh": "court", "auth": "AAAAAAAAAAAAAAAAAAAAAA"},
                 {**Browser().json()["keys"], "auth": "AAAA"}):
        bad = admin.post("/api/push/subscriptions", json={"endpoint": ENDPOINT, "keys": keys})
        assert bad.status_code == 422
    for endpoint in ("https://web.push.apple.com/QGx", "https://updates.push.services.mozilla.com/wpush/v2/x",
                     "https://wns2-par02p.notify.windows.com/w/?token=x"):
        assert admin.post("/api/push/subscriptions", json=Browser(endpoint).json()).status_code == 201
    assert rows(store) and all(r["endpoint"].startswith("https://") for r in rows(store))


def test_without_keys_the_server_says_so_and_stores_nothing(shop):  # noqa: F811
    admin, store, _ = shop
    assert admin.get("/api/push").json() == {"enabled": False, "public_key": None}
    assert admin.post("/api/push/subscriptions", json=Browser().json()).status_code == 409
    assert rows(store) == []


# --- Sending -----------------------------------------------------------------


class Sender:
    """Stands for pywebpush.webpush: records each call, fails on chosen endpoints."""

    def __init__(self, statuses=None):
        self.calls, self.statuses = [], statuses or {}

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        status = self.statuses.get(kwargs["subscription_info"]["endpoint"])
        if status:
            raise WebPushException(f"Push failed: {status}", response=type("R", (), {"status_code": status})())


def test_a_new_request_reaches_the_staff_phones_without_client_data(pushed):
    admin, store, listings = pushed
    from pokeprice import webapp

    assert admin.post("/api/push/subscriptions", json=Browser().json()).status_code == 201
    reader = staff_member(admin, store, "ancien")
    assert reader.post("/api/push/subscriptions",
                       json=Browser("https://web.push.apple.com/ancien").json()).status_code == 201
    reader.__exit__(None, None, None)
    former = next(u for u in admin.get("/api/users").json() if u["username"] == "ancien")
    assert admin.patch(f"/api/users/{former['id']}", json={"role": "reader", "disabled": True}).status_code == 200
    sender, apps = Sender(), []

    def factory(root):
        app = webapp.create_app(root)
        wire(store, app, [channel(store, sender)])
        apps.append(app)
        return app

    assert guest_request(store, [listings[0]["id"], listings[1]["id"]], factory).status_code == 202
    assert apps[0].state.notifier.run_due() == 1
    [call] = sender.calls  # The disabled account's phone gets nothing.
    assert call["subscription_info"]["endpoint"] == ENDPOINT
    assert call["timeout"] == PUSH_TIMEOUT <= 10 and call["vapid_claims"] == {"sub": "mailto:operateur@example.test"}
    message = json.loads(call["data"])
    assert set(message) == {"title", "body", "url"}
    assert message["title"] == "Nouvelle demande : 2 cartes, 4,70 €"
    assert message["body"] == "Accepter ou refuser"
    assert message["url"].startswith("/gestion?demande=")  # The view concerned, no origin.
    for secret in (GUEST["email"], GUEST["display_name"], "Sacha", "sacha", "Privée", "12 rue", "cartes.example"):
        assert secret not in call["data"]


def test_the_brief_opens_the_management_and_keeps_counts_only(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES('u','pat','x','admin','now')")
    notifications.subscribe(store, "u", ENDPOINT, **Browser().json()["keys"])
    sender, ntfy = Sender(), Fake("ntfy", fail=1)
    sent = send_brief(store, notify=True, channels=[ntfy, channel(store, sender)],
                      origin="https://cartes.example")
    # ntfy down: the phone still gets it, and the other way round.
    assert sent["notified"] == ["webpush"] and sent["errors"] == {"ntfy": "OSError"}
    message = json.loads(sender.calls[0]["data"])
    assert message["url"] == "/gestion" and message["title"] == sent["title"]
    assert "https://" not in message["body"] and message["body"].startswith("Fait :")
    failing = Sender({ENDPOINT: 500})
    again = send_brief(store, notify=True, channels=[channel(store, failing), Fake("ntfy")],
                       origin="https://cartes.example")
    assert again["notified"] == ["ntfy"] and again["errors"] == {"webpush": "OSError"}


def test_gone_subscriptions_are_purged_and_failures_name_no_endpoint(tmp_path, caplog):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES('u','pat','x','admin','now')")
    phones = {name: f"https://fcm.googleapis.com/fcm/send/{name}" for name in ("vivant", "parti", "oublie", "lent")}
    for endpoint in phones.values():
        notifications.subscribe(store, "u", endpoint, **Browser(endpoint).json()["keys"])
    sender = Sender({phones["parti"]: 410, phones["oublie"]: 404, phones["lent"]: 503})
    assert channel(store, sender).send("Titre", "Texte", "https://cartes.example/gestion") == 1
    assert {r["endpoint"] for r in rows(store)} == {phones["vivant"], phones["lent"]}
    # Every phone failing is an error, so the outbox retries; the log names no phone.
    with pytest.raises(OSError) as failure:
        channel(store, Sender({phones["vivant"]: 500, phones["lent"]: 503})).send("T", "B", "")
    assert "fcm.googleapis.com" not in str(failure.value)
    assert "fcm.googleapis.com" not in caplog.text
    assert len(rows(store)) == 2
    # No phone subscribed: nothing to do, nothing failed.
    with store.connect(write=True) as db:
        db.execute("DELETE FROM push_subscriptions")
    assert channel(store, Sender()).send("T", "B", "") == 0


def test_the_real_library_encrypts_for_the_phone_with_a_short_timeout(tmp_path):
    """pywebpush itself, its HTTP session replaced: the phone's key decrypts the payload."""
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES('u','pat','x','admin','now')")
    phone = Browser()
    notifications.subscribe(store, "u", ENDPOINT, **phone.json()["keys"])
    posts = []

    class Session:
        def post(self, url, data=None, headers=None, timeout=None):
            posts.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
            return type("Response", (), {"status_code": 201, "text": "", "headers": {}})()

    push = channel(store, partial(webpush, requests_session=Session()))
    assert push.send("Rien ne t’attend aujourd’hui", "Fait : rien de nouveau.\nhttps://cartes.example/gestion",
                     "https://cartes.example/gestion") == 1
    [post] = posts
    assert post["url"] == ENDPOINT and post["timeout"] == PUSH_TIMEOUT
    assert post["headers"]["content-encoding"] == "aes128gcm" and int(post["headers"]["ttl"]) > 0
    assert post["headers"]["authorization"].startswith("vapid t=")
    assert push.public_key in post["headers"]["authorization"]
    assert phone.decrypt(post["data"]) == {
        "title": "Rien ne t’attend aujourd’hui", "body": "Fait : rien de nouveau.", "url": "/gestion"}
    # A second send builds fresh claims: pywebpush writes into the dict it gets.
    assert push.send("T", "B", "") == 1 and len(posts) == 2


def test_the_payload_stays_short_and_inside_the_management():
    long = "Fait : " + "x" * 400
    message = json.loads(push_payload("Titre", long, "https://cartes.example/gestion?demande=abc"))
    assert len(message["body"]) <= notifications.PUSH_BODY and message["body"].endswith("…")
    assert message["url"] == "/gestion?demande=abc"
    for outside in ("https://ailleurs.example/piege", "https://cartes.example/", "", "javascript:alert(1)"):
        assert json.loads(push_payload("T", "B", outside))["url"] == "/gestion"


# --- Browser code ------------------------------------------------------------


def node_or_skip():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the browser code")
    return node


def test_service_worker_shows_the_push_and_opens_the_management(tmp_path):
    node = node_or_skip()
    with TestClient(create_app(tmp_path / "inventory")) as client:
        served = tmp_path / "sw.js"
        served.write_text(client.get("/gestion/sw.js").text)
    result = subprocess.run([node, str(ROOT / "tests/web_push_runtime.cjs"), str(served)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_switch_asks_permission_only_on_a_gesture(tmp_path):
    node = node_or_skip()
    messages = json.loads((ROOT / "src/pokeprice/web/messages/fr.json").read_text())
    result = subprocess.run(
        [node, str(ROOT / "tests/web_push_toggle_runtime.cjs"), str(ROOT / "src/pokeprice/web/pwa.js")],
        input=json.dumps(messages), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_the_switch_is_in_the_settings(tmp_path):
    with TestClient(create_app(tmp_path / "inventory")) as client:
        page = client.get("/gestion").text
    assert 'id="push-toggle" type="checkbox" role="switch" disabled' in page
    assert "Notifications sur ce téléphone" in page
    # First in the settings, above the backups: it was missed below them.
    assert page.index('id="push-panel"') < page.index('id="backup-status-panel"')
