import shutil
import subprocess
from pathlib import Path

import pytest


def test_registration_client_handles_empty_and_invalid_responses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the web API client")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_api_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_filter_urls_survive_reload_and_reject_invalid_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_navigation_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_clear_selection_updates_cards_and_lot_without_waiting_for_server():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_selection_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_capture_preserves_disabled_fields_and_retries_lost_save_response():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_capture_runtime.cjs"),
            str(root / "src/pokeprice/web/workflows.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_summary_refresh_keeps_the_album_of_a_capture_series():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_summary_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_bulk_price_refresh_skips_unconfirmed_and_continues_after_failures():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_price_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_valuation_totals_show_coverage_and_keep_missing_prices_unknown():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_valuation_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_gallery_keys_find_the_card_below_and_the_page_of_a_position():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_gallery_runtime.cjs"),
            str(root / "src/pokeprice/web/gallery.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
