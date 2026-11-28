"""The Gemini model name, in one place (decision 0054).

Card reading (identity, finish, language, stamp, condition), the album OCR, the
lots prompt and the chat all default to the same model. One variable changes it
everywhere; the chat and the lots prompt keep their own variable, which wins
over this one. Read at call time, after any ``.env`` is loaded, so each reading
records the model that produced it.
"""

import os

DEFAULT_MODEL = "gemini-3.8-flash"
MODEL_VARIABLE = "POKEPRICE_GEMINI_MODEL"


def gemini_model(environ=None):
    """The model for Gemini calls: ``POKEPRICE_GEMINI_MODEL``, else the default."""
    environ = os.environ if environ is None else environ
    return (environ.get(MODEL_VARIABLE) or "").strip() or DEFAULT_MODEL
