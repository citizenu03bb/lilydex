"""The shared viewer controller and its private integration run without a service."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_shared_photo_zoom_and_private_wrapper():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the shared photo zoom")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/photo_zoom_runtime.cjs"),
         str(root / "src/pokeprice/web/photo-zoom.js"),
         str(root / "src/pokeprice/web/media.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
