from test_public_storefront import shop  # noqa: F401

from pokeprice.audience import Audience

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Mobile Safari/604.1"


def test_a_visitor_counts_once_a_day_and_leaves_no_trace(tmp_path):
    audience = Audience(tmp_path, ["lilydex.example.org"])
    for _ in range(3):
        audience.record("page", "accueil", "203.0.113.7", BROWSER, today="2026-10-20")
    audience.record("page", "accueil", "203.0.113.8", PHONE,
                    "https://www.forum.example/fil/42", today="2026-10-20")
    audience.record("page", "a-propos", "203.0.113.8", PHONE,
                    "https://lilydex.example.org/", today="2026-10-20")
    audience.record("listing", "L1", "203.0.113.7", BROWSER, today="2026-10-21")
    report = audience.report(7, today="2026-10-21")
    assert report["visitors"] == 3 and report["page_views"] == 5
    assert report["pages"] == {"accueil": 4, "a-propos": 1}
    assert report["listings"] == [{"id": "L1", "count": 1}]
    assert report["referrers"] == [{"domain": "forum.example", "count": 1}]
    assert report["devices"] == {"mobile": 1, "desktop": 2}
    assert [d["day"] for d in report["days"]][-2:] == ["2026-10-20", "2026-10-21"]
    # Past days keep their totals only: no salt, no hash, no address.
    raw = audience.path.read_bytes()
    assert b"203.0.113" not in raw
    with audience.connect() as db:
        assert {r[0] for r in db.execute("SELECT day FROM seen")} == {"2026-10-21"}
        assert {r[0] for r in db.execute("SELECT day FROM salts")} == {"2026-10-21"}


def test_totals_expire_after_25_months(tmp_path):
    audience = Audience(tmp_path)
    audience.record("page", "accueil", "a", BROWSER, today="2024-01-01")
    audience.report(30, today="2026-10-21")
    with audience.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM totals").fetchone()[0] == 0


def test_the_storefront_counts_visitors_but_not_robots_nor_the_team(shop):  # noqa: F811
    admin, visitor, store, cards, single, lot = shop
    visitor.get("/", headers={"user-agent": BROWSER})
    visitor.get("/a-propos", headers={"user-agent": BROWSER})
    visitor.get(f"/api/public/listings/{lot['id']}/photo",
                params={"size": "full"}, headers={"user-agent": BROWSER})
    visitor.get(f"/api/public/listings/{lot['id']}/photo", headers={"user-agent": BROWSER})
    visitor.get("/", headers={"user-agent": "Googlebot/2.1"})
    visitor.get("/", headers={"user-agent": BROWSER, "sec-gpc": "1"})
    admin.get("/", headers={"user-agent": BROWSER})
    # Do Not Track is often on by default; Chrome shows a preloaded page without asking again.
    visitor.get("/", headers={"user-agent": PHONE, "dnt": "1"})
    visitor.get("/", headers={"user-agent": PHONE, "sec-purpose": "prefetch;prerender"})
    report = admin.get("/api/audience", params={"days": 7}).json()
    assert report["visitors"] == 2 and report["pages"] == {"accueil": 3, "a-propos": 1}
    assert report["listings"] == [{"id": lot["id"], "count": 1, "title": "Deux cartes"}]
    assert report["signups"] == 0 and report["requests"] == 0
    assert visitor.get("/api/audience").status_code == 401
