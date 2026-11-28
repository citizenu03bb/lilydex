"""One Gemini model name, changeable by one variable (decision 0054)."""

from pokeprice import assistant_model, lots_prompt
from pokeprice.gemini_model import DEFAULT_MODEL, MODEL_VARIABLE, gemini_model
from pokeprice.verification import GeminiFinishReader


def test_default_and_override():
    assert gemini_model({}) == DEFAULT_MODEL == "gemini-3.8-flash"
    assert gemini_model({MODEL_VARIABLE: "  "}) == DEFAULT_MODEL
    assert gemini_model({MODEL_VARIABLE: " gemini-4-hydrogen "}) == "gemini-4-hydrogen"


def test_read_at_call_time(monkeypatch):
    monkeypatch.delenv(MODEL_VARIABLE, raising=False)
    reader = GeminiFinishReader()
    assert reader.model == DEFAULT_MODEL
    monkeypatch.setenv(MODEL_VARIABLE, "modele-de-test")
    assert reader.model == "modele-de-test"


def test_chat_variable_wins_over_the_common_one():
    key = {assistant_model.KEY_VARIABLE: "cle-de-test"}
    assert assistant_model.from_env(key).model == DEFAULT_MODEL
    common = {**key, MODEL_VARIABLE: "commun"}
    assert assistant_model.from_env(common).model == "commun"
    own = {**common, assistant_model.MODEL_VARIABLE: "chat"}
    assert assistant_model.from_env(own).model == "chat"


def test_lots_variable_wins_over_the_common_one(monkeypatch):
    monkeypatch.delenv(lots_prompt.GEMINI_MODEL_ENV, raising=False)
    monkeypatch.setenv(MODEL_VARIABLE, "commun")
    assert lots_prompt.gemini_model() == "commun"
    monkeypatch.setenv(lots_prompt.GEMINI_MODEL_ENV, "lots")
    assert lots_prompt.gemini_model() == "lots"
