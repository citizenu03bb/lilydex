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


def test_storefront_logout_failure_keeps_the_visitor_signed_in():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the storefront logout")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            node,
            str(root / "tests/storefront_logout_runtime.cjs"),
            str(root / "src/pokeprice/web/storefront.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_storefront_viewer_walks_the_list_and_a_lot_photos():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the storefront viewer")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            node,
            str(root / "tests/storefront_viewer_runtime.cjs"),
            str(root / "src/pokeprice/web/storefront.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_storefront_filters_survive_urls_pages_races_and_mobile_editing():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the storefront filters")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/storefront_filters_runtime.cjs"),
         str(root / "src/pokeprice/web/storefront.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


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


def test_sales_status_filter_hides_cancelled_lots_by_default():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_sales_filter_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )



def test_intake_reading_keeps_entry_preselects_exact_edition_and_proposes_notes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_intake_runtime.cjs"),
            str(root / "src/pokeprice/web/app.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_theme_picker_and_viewer_quick_exam_preserve_drafts_and_csp():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_components_runtime.cjs"),
            str(root / "src/pokeprice/web/components.js"),
            str(root / "src/pokeprice/web/gallery.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_storefront_submissions_ignore_repeated_activation_and_allow_retry():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root / 'tests/storefront_submission_runtime.cjs'),
                    str(root / 'src/pokeprice/web/storefront.js')], check=True,
                   capture_output=True, text=True)
