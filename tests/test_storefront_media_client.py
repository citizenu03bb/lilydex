import shutil
import subprocess
from pathlib import Path

import pytest


def test_responsive_sources_use_real_dimensions_and_recover_to_jpeg():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise public images")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/storefront_media_runtime.cjs"),
         str(root / "src/pokeprice/web/storefront.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
