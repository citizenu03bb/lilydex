"""The chat's cost alert, V1.1 (decision 0039): fake model and fake channel, no service."""

import json
import logging
import time
from datetime import datetime, timezone

from test_assistant import ask, env, login, sse  # noqa: F401 - env is a fixture

from pokeprice.assistant import (
    PRICING,
    CostAlert,
    Journal,
    load_pricing,
    month_cost,
    month_of,
    month_shift,
    price_of,
)
from pokeprice.assistant_model import FakeModel

PRICES = {"models": {
    "gemini:flash": {"input": 1.00, "output": 4.00,
                     "changes": [{"from": "2027-01", "input": 2.00, "output": 8.00}]},
}}


class Channel:
    name = "webpush"

    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, title, body, link):
        if self.fail:
            raise OSError("service de push injoignable")
        self.sent.append((title, body, link))


class Clock:
    def __init__(self, moment):
        self.now = moment

    def __call__(self):
        return self.now


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def alert(journal, channel, clock, **kwargs):
    return CostAlert(journal, [channel], "https://exemple.test", threshold_eur=30,
                     eur_per_usd=1.0, pricing=PRICES, spawn=lambda job: job(), clock=clock,
                     **kwargs)


def spend(journal, month, dollars, model="gemini:flash"):
    """``dollars`` of input tokens at 1 $ the million."""
    journal.count_month(month, model, int(dollars * 1_000_000), 0)


def test_the_price_list_is_the_benchs_and_knows_the_default_model():
    pricing = load_pricing()
    assert PRICING.name == "assistant_pricing.json"
    assert price_of(pricing, "gemini:gemini-3.8-flash", "2026-11") == {"input": 0.75, "output": 3.75}
    assert price_of(pricing, "gemini:gemini-3.8-flash", "2027-01") == {"input": 1.50, "output": 7.50}


def test_cost_uses_the_price_in_force_for_the_month():
    rows = [{"model": "gemini:flash", "input_tokens": 1_000_000, "output_tokens": 500_000}]
    assert month_cost(rows, PRICES, "2026-12", 0.9) == {
        "month": "2026-12", "usd": 3.0, "eur": 2.7, "unpriced_models": []}
    assert month_cost(rows, PRICES, "2027-01", 1.0)["usd"] == 6.0


def test_no_alert_below_then_one_at_the_threshold(tmp_path):
    journal, channel = Journal(tmp_path), Channel()
    clock = Clock(at("2026-11-10T12:00:00"))
    watch = alert(journal, channel, clock)
    spend(journal, "2026-11", 29.5)
    assert watch.check("2026-11")["eur"] == 29.5
    assert channel.sent == []
    spend(journal, "2026-11", 0.5)
    watch.check("2026-11")
    assert len(channel.sent) == 1
    title, body, link = channel.sent[0]
    assert title == "Chat : coût estimé 30,00 € ce mois-ci"
    assert "seuil 30,00 €" in body and link == "https://exemple.test/gestion"
    assert journal.alert_state("2026-11")["sent_at"] == clock.now


def test_a_single_alert_a_month_even_after_a_restart(tmp_path):
    channel = Channel()
    clock = Clock(at("2026-11-10T12:00:00"))
    journal = Journal(tmp_path)
    spend(journal, "2026-11", 31)
    alert(journal, channel, clock).check("2026-11")
    spend(journal, "2026-11", 40)
    alert(journal, channel, clock).check("2026-11")
    # A new process: the sent alert is in assistant.sqlite3, not in memory.
    clock.now += 86400
    alert(Journal(tmp_path), channel, clock).check("2026-11")
    assert len(channel.sent) == 1


def test_a_new_month_starts_from_zero_and_can_alert_again(tmp_path):
    journal, channel = Journal(tmp_path), Channel()
    clock = Clock(at("2026-11-30T23:00:00"))
    watch = alert(journal, channel, clock)
    spend(journal, "2026-11", 35)
    watch.check("2026-11")
    clock.now = at("2026-12-01T00:30:00")
    spend(journal, "2026-12", 5)
    assert watch.check()["eur"] == 5.0  # The month comes from the clock.
    assert len(channel.sent) == 1
    spend(journal, "2026-12", 25)
    watch.check()
    assert len(channel.sent) == 2
    assert [m["questions"] for m in journal.month_tokens("2026-12")] == [2]


def test_a_failed_send_is_tried_again_after_its_lease(tmp_path):
    journal, broken = Journal(tmp_path), Channel(fail=True)
    clock = Clock(at("2026-11-10T12:00:00"))
    spend(journal, "2026-11", 31)
    alert(journal, broken, clock).check("2026-11")
    state = journal.alert_state("2026-11")
    assert state["sent_at"] is None and state["error"] == "OSError"
    working = Channel()
    alert(journal, working, clock).check("2026-11")
    assert working.sent == []  # Within the lease: no burst of retries.
    clock.now += 601
    alert(journal, working, clock).check("2026-11")
    assert len(working.sent) == 1


def test_a_model_without_a_price_never_breaks_and_warns_once(tmp_path, caplog):
    journal, channel = Journal(tmp_path), Channel()
    watch = alert(journal, channel, Clock(at("2026-11-10T12:00:00")))
    spend(journal, "2026-11", 1000, model="mistral:inconnu")
    spend(journal, "2026-11", 2)
    with caplog.at_level(logging.WARNING, logger="pokeprice.assistant"):
        cost = watch.check("2026-11")
        watch.check("2026-11")
    assert cost == {"month": "2026-11", "usd": 2.0, "eur": 2.0, "unpriced_models": ["mistral:inconnu"]}
    assert [r.getMessage() for r in caplog.records].count(
        "assistant cost: no price for model=mistral:inconnu in assistant_pricing.json, "
        "its tokens are not counted") == 1
    assert channel.sent == []


def test_the_threshold_at_zero_switches_the_alert_off(tmp_path):
    journal, channel = Journal(tmp_path), Channel()
    watch = CostAlert(journal, [channel], threshold_eur=0, pricing=PRICES, spawn=lambda job: job())
    spend(journal, month_of(time.time()), 500)
    watch.check()
    assert channel.sent == [] and not watch.enabled


def test_the_months_tokens_outlive_the_thirty_days_purge(tmp_path):
    journal = Journal(tmp_path)
    old = at("2026-10-31T10:00:00")
    question, _ = journal.start("u", None, "gemini:flash", daily_limit=10, per_minute=10, at=old)
    journal.finish(question, input_tokens=5000, output_tokens=100, duration_ms=1, tool_rounds=0,
                   outcome="ok")
    journal.count_month("2026-10", "gemini:flash", 5000, 100)
    journal.purge(at=at("2026-12-01T00:00:00"))
    assert journal.month_tokens("2026-10") == [
        {"model": "gemini:flash", "questions": 1, "input_tokens": 5000, "output_tokens": 100}]
    # Thirteen months at most: counts only, but nothing kept forever.
    journal.count_month("2027-11", "gemini:flash", 1, 1)
    assert journal.month_tokens("2026-10") == []
    assert month_shift("2027-01", -12) == "2026-01" and month_shift("2026-12", 1) == "2027-01"


class PricedModel(FakeModel):
    provider = "gemini"


def test_each_question_adds_its_tokens_and_the_alert_goes_out(env):  # noqa: F811
    costly = {"text": "Coûteux.", "input_tokens": 20_000_000, "output_tokens": 1_000_000}
    model = PricedModel([costly, costly], model="gemini-3.8-flash")
    app = env["make"](assistant_model=model)
    channel = Channel()
    watch = app.state.assistant.cost_alert
    assert watch.threshold == 30 and watch.rate == 0.95
    assert watch.pricing == load_pricing()
    # A fixed price: the test does not change with the announced 2027 price.
    watch.pricing = {"models": {"gemini:gemini-3.8-flash": {"input": 0.75, "output": 3.75}}}
    watch.channels, watch.spawn = [channel], (lambda job: job())
    events = sse(ask(login(app, "owner"), "Combien de cartes ?"))
    assert events[-1][0] == "done"
    month = month_of(time.time())
    assert app.state.assistant.journal.month_tokens(month) == [
        {"model": "gemini:gemini-3.8-flash", "questions": 1, "input_tokens": 20_000_000,
         "output_tokens": 1_000_000}]
    # 20 × 0.75 + 1 × 3.75 = 18.75 $, 17.81 € : below 30 € ; twice, 35.62 €.
    assert channel.sent == []
    events = sse(ask(login(app, "owner"), "Et maintenant ?"))
    assert events[-1][0] == "done"
    assert len(channel.sent) == 1 and "35,62 €" in channel.sent[0][0]
    assert json.dumps(channel.sent).count("Combien") == 0  # Never a question's text.


def test_the_threshold_and_rate_come_from_the_environment(env):  # noqa: F811
    env["monkeypatch"].setenv("POKEPRICE_ASSISTANT_COST_ALERT_EUR", "12,5")
    env["monkeypatch"].setenv("POKEPRICE_ASSISTANT_EUR_PER_USD", "0.9")
    watch = env["make"](assistant_model=FakeModel()).state.assistant.cost_alert
    assert (watch.threshold, watch.rate) == (12.5, 0.9)
