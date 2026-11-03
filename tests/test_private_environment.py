"""A test never reads the developer's ~/.env, so it never alerts the real seller."""

import os
from pathlib import Path

from pokeprice.cli import load_env
from pokeprice.notifications import channels_from_env


def test_the_real_home_env_stays_out_of_the_tests():
    assert not (Path.home() / ".env").exists()
    load_env()
    # A bare membership test: a failure must not print the environment.
    leaked = [n for n in ("POKEPRICE_NTFY_URL", "GEMINI_API_KEY") if n in os.environ]
    assert not leaked, f"variables lues depuis un .env réel : {leaked}"
    assert channels_from_env() == []
