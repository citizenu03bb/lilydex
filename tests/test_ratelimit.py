"""Bounded, /64-aware rate limiters (unit and through the application).

Only documentation addresses appear here: 2001:db8::/32 and 203.0.113.0/24.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from pokeprice import ratelimit
from pokeprice.ratelimit import SlidingWindow, client_key
from pokeprice.webapp import create_app

OWNER = {"username": "owner", "password": "Collection-test-2026!"}
WRONG = {"username": "nobody", "password": "Collection-wrong-2026!"}
SIGNUP_PASSWORD = "Client-test-2026!"


class Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


# SlidingWindow


def test_the_limit_is_allowed_then_refused_without_recording():
    clock = Clock(1.0)
    window = SlidingWindow(3, 10, clock=clock)
    assert [window.hit("a") for _ in range(5)] == [True] * 3 + [False] * 2
    clock.value = 10.9  # Refused hits at 1.0 recorded nothing that lasts longer.
    assert window.hit("a") is False
    clock.value = 11.0  # now - window == first stamp: expired, as `now - t < window`.
    assert window.hit("a") is True


def test_a_key_is_allowed_again_after_the_window():
    clock = Clock(0.5)
    window = SlidingWindow(2, 60, clock=clock)
    assert window.hit("a") and window.hit("a") and not window.hit("a")
    clock.value += 60
    assert window.hit("a") and window.hit("a") and not window.hit("a")


def test_the_number_of_keys_is_capped_and_the_oldest_go_first():
    clock = Clock()
    window = SlidingWindow(5, 60, max_keys=1000, clock=clock)
    for i in range(5000):
        clock.value = i * 0.001
        assert window.hit(i)
    assert len(window) == 1000
    assert 3999 not in window._buckets and 4000 in window._buckets and 4999 in window._buckets
    assert next(iter(window._buckets)) == 4000


def test_a_refused_hit_does_not_refresh_the_eviction_order():
    window = SlidingWindow(1, 60, max_keys=2, clock=Clock())
    assert window.hit("old") and window.hit("new")
    assert window.hit("old") is False
    assert window.hit("third")
    assert list(window._buckets) == ["new", "third"]


def test_expired_keys_are_removed_on_access():
    clock = Clock()
    window = SlidingWindow(5, 60, clock=clock)
    window.hit("a")
    clock.value = 100
    window.hit("b")
    assert "a" in window._buckets  # Only touched keys expire eagerly.
    window.hit("a")
    assert len(window._buckets["a"].stamps) == 1
    assert all(bucket.stamps for bucket in window._buckets.values())


def test_simultaneous_hits_never_exceed_the_limit():
    window = SlidingWindow(100, 60)
    successes = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        successes.append(sum(window.hit("shared") for _ in range(200)))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(successes) == 100


def test_forgive_removes_only_the_matching_tag_in_order():
    clock = Clock()
    window = SlidingWindow(5, 60, tagged=True, clock=clock)
    for tag in ("admin", "me", "admin", "me"):
        clock.value += 1
        window.hit("here", tag)
    window.hit("there", "me")
    window.forgive("here", "me")
    bucket = window._buckets["here"]
    assert list(bucket.stamps) == [1.0, 3.0] and list(bucket.tags or ()) == ["admin", "admin"]
    assert list(window._buckets["there"].tags or ()) == ["me"]
    window.forgive("here", "admin")
    assert "here" not in window._buckets
    window.forgive("absent", "me")  # Unknown keys are ignored.
    assert len(window) == 1


def test_only_tagged_limiters_store_tags():
    tagged = SlidingWindow(5, 60, tagged=True)
    plain = SlidingWindow(5, 60)
    tagged.hit("k", "user")
    plain.hit("k", "user")
    assert list(tagged._buckets["k"].tags or ()) == ["user"]
    assert plain._buckets["k"].tags is None
    assert all(isinstance(s, float) for s in plain._buckets["k"].stamps)
    plain.forgive("k", "user")  # Nothing to forgive without tags.
    assert len(plain) == 1


def test_the_default_clock_is_resolved_at_call_time(monkeypatch):
    window = SlidingWindow(1, 60)
    monkeypatch.setattr(ratelimit, "_now", lambda: 5.0)
    assert window.hit("k") and not window.hit("k")
    monkeypatch.setattr(ratelimit, "_now", lambda: 65.0)
    assert window.hit("k")


def test_the_default_cap_is_read_at_construction(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 3)
    assert SlidingWindow(1, 60).max_keys == 3
    assert SlidingWindow(1, 60, max_keys=7).max_keys == 7


# client_key


def test_ipv4_is_unchanged():
    assert client_key("203.0.113.7") == "203.0.113.7"


def test_ipv6_is_keyed_on_its_64():
    assert client_key("2001:db8:1:2::1") == client_key("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:3::1") != client_key("2001:db8:1:2::1")


def test_compressed_and_expanded_forms_agree():
    assert client_key("2001:0db8:0001:0002:0000:0000:0000:0001") == client_key("2001:db8:1:2::1")
    assert client_key("2001:DB8:1:2::1") == client_key("2001:db8:1:2::1")


def test_mapped_ipv4_is_keyed_as_ipv4():
    assert client_key("::ffff:203.0.113.7") == "203.0.113.7"
    assert client_key("::ffff:203.0.113.7") != "::/64"
    assert client_key("::ffff:203.0.113.7") != client_key("::ffff:203.0.113.8")


def test_brackets_and_zones_are_stripped():
    assert client_key("[2001:db8:1:2::1]") == "2001:db8:1:2::/64"
    assert client_key("fe80::1%eth0") == client_key("fe80::2") == "fe80::/64"


def test_non_addresses_are_namespaced():
    assert client_key(None) == client_key("") == client_key("  ") == "local"
    assert client_key("testclient") == "raw:testclient"
    assert client_key("x" * 500) == "raw:" + "x" * 64


def test_a_prefix_string_cannot_pose_as_a_real_key():
    forged = client_key("2001:db8:1:2::/64")
    assert forged == "raw:2001:db8:1:2::/64"
    assert forged != client_key("2001:db8:1:2::1")


# Through the application


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "inventory")
    with TestClient(application) as owner:
        assert owner.post("/api/setup", json=OWNER).status_code == 200
        yield application


def from_address(app, host, **options):
    # Lifespan already ran in the fixture: no context manager here.
    return TestClient(app, client=(host, 50000), **options)


def test_login_failures_rotating_inside_a_64_are_throttled(app):
    statuses = [
        from_address(app, f"2001:db8:1:2::{i}").post("/api/login", json=WRONG).status_code
        for i in range(1, 6)
    ]
    assert statuses == [401] * 5
    refused = from_address(app, "2001:db8:1:2::99").post("/api/login", json=WRONG)
    assert refused.status_code == 429
    assert refused.json()["detail"] == "Trop de tentatives. Réessayez dans cinq minutes."
    assert from_address(app, "2001:db8:1:3::1").post("/api/login", json=WRONG).status_code == 401
    assert from_address(app, "203.0.113.7").post("/api/login", json=WRONG).status_code == 401


def test_login_failures_expire_after_five_minutes(app, monkeypatch):
    clock = Clock(1000.0)
    monkeypatch.setattr(ratelimit, "_now", clock)
    client = from_address(app, "203.0.113.7")
    assert [client.post("/api/login", json=WRONG).status_code for _ in range(6)] == [401] * 5 + [429]
    clock.value += 300
    assert client.post("/api/login", json=WRONG).status_code == 401


def test_a_successful_login_forgives_only_its_own_typos(app):
    typo = {"username": "owner", "password": "Collection-typo-2026!"}
    client = from_address(app, "2001:db8:1:2::1")
    other = from_address(app, "2001:db8:1:2::2")
    statuses = [client.post("/api/login", json=typo).status_code for _ in range(2)]
    statuses += [other.post("/api/login", json=WRONG).status_code for _ in range(2)]
    statuses.append(client.post("/api/login", json=OWNER).status_code)
    # Owner's typos and its success are gone; the two guesses at "nobody" stay.
    statuses += [other.post("/api/login", json=WRONG).status_code for _ in range(4)]
    assert statuses == [401] * 4 + [200] + [401] * 3 + [429]


def signup_body(i):
    return {"email": f"x{i}@example.org", "display_name": "X", "password": SIGNUP_PASSWORD, "consent": True}


def test_signups_rotating_inside_a_64_are_limited(app):
    statuses = [
        from_address(app, f"2001:db8:1:2::{i}").post("/api/public/signup", json=signup_body(i)).status_code
        for i in range(1, 7)
    ]
    assert statuses == [202] * 5 + [429]
    assert from_address(app, "2001:db8:1:3::1").post("/api/public/signup", json=signup_body(9)).status_code == 202


def guest_body(i):
    # An unknown listing: refused after the quota is counted, without a reservation.
    return {
        "email": f"x{i}@example.org", "display_name": "X", "listing_ids": ["inconnue"],
        "expected_prices": {"inconnue": 100}, "consent": True,
    }


def test_guest_requests_rotating_inside_a_64_are_limited(app):
    statuses = [
        from_address(app, f"2001:db8:1:2::{i}").post("/api/public/requests", json=guest_body(i)).status_code
        for i in range(1, 7)
    ]
    assert statuses == [409] * 5 + [429]
    refused = from_address(app, "2001:db8:1:2::99").post("/api/public/requests", json=guest_body(7))
    assert refused.json()["detail"] == "Trop de demandes depuis cette adresse. Réessayez plus tard."
    assert from_address(app, "2001:db8:1:3::1").post("/api/public/requests", json=guest_body(8)).status_code == 409


def test_public_reads_rotating_inside_a_64_are_limited(app):
    clients = [from_address(app, f"2001:db8:1:2::{i}") for i in range(1, 6)]
    statuses = [clients[i % 5].get("/api/public/listings/absent").status_code for i in range(300)]
    assert set(statuses) == {404}
    refused = from_address(app, "2001:db8:1:2::99").get("/api/public/listings/absent")
    assert refused.status_code == 429 and refused.headers["Retry-After"] == "60"
    assert refused.json()["detail"] == "Trop de requêtes. Réessayez dans une minute."
    assert from_address(app, "2001:db8:1:3::1").get("/api/public/listings/absent").status_code == 404


def test_invalid_bodies_do_not_consume_the_quota(app):
    client = from_address(app, "203.0.113.7")
    for _ in range(6):
        assert client.post("/api/public/signup", json={"email": "x"}).status_code == 422
        assert client.post("/api/public/requests", json={"email": "x"}).status_code == 422
        assert client.post("/api/login", json={"username": "owner"}).status_code == 422
    assert client.post("/api/public/signup", json=signup_body(1)).status_code == 202
    assert client.post("/api/public/requests", json=guest_body(1)).status_code == 409
    assert client.post("/api/login", json=OWNER).status_code == 200


def test_signup_refusal_keeps_its_message_and_code(app):
    client = from_address(app, "203.0.113.7")
    for i in range(5):
        assert client.post("/api/public/signup", json=signup_body(i)).status_code == 202
    refused = client.post("/api/public/signup", json=signup_body(5))
    assert refused.status_code == 429
    assert refused.json()["detail"] == "Trop d’inscriptions depuis cette adresse. Réessayez plus tard."
    assert refused.json()["code"] == "too_many_signups"


def test_many_addresses_stay_under_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 8)
    app = create_app(tmp_path / "inventory")
    with TestClient(app):
        for i in range(50):
            assert from_address(app, f"2001:db8:{i:x}::1").get("/api/public/listings/absent").status_code == 404
        limiters = app.state.rate_limits
        assert len(limiters["public"]) == 8
        assert all(limiter.max_keys == 8 for limiter in limiters.values())


# Behind the reverse proxy: uvicorn rewrites the client, the app never reads headers.


def proxied(app, peer, forwarded):
    middleware = pytest.importorskip("uvicorn.middleware.proxy_headers")
    wrapped = middleware.ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
    return TestClient(wrapped, client=(peer, 50000), headers={"X-Forwarded-For": forwarded})


def test_the_trusted_proxy_address_is_keyed_on_its_64(app):
    statuses = [
        proxied(app, "127.0.0.1", f"2001:db8:1:2::{i}").post("/api/login", json=WRONG).status_code
        for i in range(1, 7)
    ]
    assert statuses == [401] * 5 + [429]
    assert "2001:db8:1:2::/64" in app.state.rate_limits["login"]._buckets
    # Multi-hop: the right-most untrusted address is the client.
    hops = "2001:db8:9:9::1, 2001:db8:1:2::9"
    assert proxied(app, "127.0.0.1", hops).post("/api/login", json=WRONG).status_code == 429


def test_a_forged_header_from_an_untrusted_peer_is_ignored(app):
    for i in range(1, 6):
        assert proxied(app, "127.0.0.1", f"2001:db8:1:2::{i}").post("/api/login", json=WRONG).status_code == 401
    # Claims the throttled /64: ignored, so the peer itself is counted.
    forged = proxied(app, "203.0.113.9", "2001:db8:1:2::77")
    assert forged.post("/api/login", json=WRONG).status_code == 401
    assert "203.0.113.9" in app.state.rate_limits["login"]._buckets
