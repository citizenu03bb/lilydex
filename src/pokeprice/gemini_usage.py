"""The tokens of each Gemini call, collected by whoever asked for them.

The binder import (decision 0047) counts what its readings cost: the card
reading, the finish reading and the condition assessment each report the
usage of their response here. Outside a ``metering()`` block, nothing is kept.
"""

import contextvars
from contextlib import contextmanager

_meter: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "pokeprice_gemini_meter", default=None
)


def usage_of(response):
    """Input and output tokens of a google-genai response; thinking counts as output."""
    metadata = getattr(response, "usage_metadata", None)

    def count(name):
        value = getattr(metadata, name, None)
        return value if isinstance(value, int) and value >= 0 else 0

    return {
        "input_tokens": count("prompt_token_count"),
        "output_tokens": count("candidates_token_count") + count("thoughts_token_count"),
    }


def record(model, response):
    """Called after each Gemini response, by the reader that made the call."""
    meter = _meter.get()
    if meter is not None:
        meter.append({"model": "gemini:" + model, **usage_of(response)})


@contextmanager
def metering():
    """Collect the usage of every Gemini call made inside the block."""
    calls: list = []
    token = _meter.set(calls)
    try:
        yield calls
    finally:
        _meter.reset(token)
