"""
Unit tests for pokeprice slicer module.
"""

from PIL import Image
from pokeprice.slicer import normalize_orientation, detect_grid_layout, slice_grid


def test_normalize_orientation_landscape():
    # Landscape image (width > height)
    img = Image.new("RGB", (800, 600), color="red")
    res = normalize_orientation(img, rotation="auto")
    assert res.height > res.width
    assert res.size == (600, 800)


def test_normalize_orientation_portrait():
    # Portrait image (height > width)
    img = Image.new("RGB", (600, 800), color="blue")
    res = normalize_orientation(img, rotation="auto")
    assert res.size == (600, 800)


def test_detect_grid_layout():
    assert detect_grid_layout(None, "3x3") == (3, 3)
    assert detect_grid_layout(None, "2x2") == (2, 2)
    assert detect_grid_layout(None, "single") == (1, 1)

    # Heuristic: portrait 600x800 -> 3x3
    img_3x3 = Image.new("RGB", (600, 800))
    assert detect_grid_layout(img_3x3, "auto") == (3, 3)

    # Heuristic: squarer 900x1000 -> 2x2
    img_2x2 = Image.new("RGB", (900, 1000))
    assert detect_grid_layout(img_2x2, "auto") == (2, 2)


def test_slice_grid_3x3():
    img = Image.new("RGB", (900, 1200), color="white")
    crops = slice_grid(img, rows=3, cols=3, inset_pct=0.0)
    assert len(crops) == 9
    for idx, (pos, crop) in enumerate(crops, 1):
        assert pos == idx
        assert crop.size == (300, 400)


def test_slice_grid_2x2():
    img = Image.new("RGB", (800, 800), color="white")
    crops = slice_grid(img, rows=2, cols=2, inset_pct=0.0)
    assert len(crops) == 4
    for idx, (pos, crop) in enumerate(crops, 1):
        assert pos == idx
        assert crop.size == (400, 400)
