"""
Image orientation normalization and grid slicing for Pokemon card binder albums.
"""

from typing import List, Tuple
from PIL import Image, ImageOps


def normalize_orientation(image: Image.Image, rotation: str = "auto") -> Image.Image:
    """
    Normalizes image orientation:
    - Applies EXIF transpose if present.
    - If rotation is 'auto', rotates landscape images 90 deg clockwise (portrait).
    - If rotation is a specific angle ('90', '180', '270', '0'), applies it.
    """
    # 1. Respect EXIF orientation tag if present
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    if rotation == "auto":
        # Binder albums are almost universally portrait (height > width).
        # A landscape shot usually means the user held phone horizontally.
        if image.width > image.height:
            # Rotate 90 deg clockwise (which is 270 in PIL counter-clockwise)
            return image.rotate(270, expand=True)
        return image
    elif rotation in ("90", "cw"):
        return image.rotate(270, expand=True)
    elif rotation in ("180",):
        return image.rotate(180, expand=True)
    elif rotation in ("270", "ccw"):
        return image.rotate(90, expand=True)
    elif rotation in ("0", "none"):
        return image
    return image


def detect_grid_layout(
    image: Image.Image, requested_layout: str = "auto"
) -> Tuple[int, int]:
    """
    Determines grid layout (rows, cols).
    Supports: 'auto', '3x3', '2x2', 'single', or custom 'RxC'.
    """
    if requested_layout in ("3x3", "9"):
        return 3, 3
    if requested_layout in ("2x2", "4"):
        return 2, 2
    if requested_layout in ("single", "1x1", "1"):
        return 1, 1
    if "x" in requested_layout:
        try:
            parts = requested_layout.split("x")
            rows, cols = int(parts[0]), int(parts[1])
            if rows <= 0 or cols <= 0:
                raise ValueError("Grid dimensions must be positive.")
            return rows, cols
        except ValueError:
            raise ValueError("Invalid grid layout.")

    # Auto-detection heuristic based on aspect ratio
    # 3x3 pages are typical standard A4 / Letter format (ratio ~ 0.70 - 0.77)
    # 2x2 mini-binder pages are often squarer (ratio ~ 0.80 - 1.05)
    aspect = image.width / float(image.height)
    if aspect > 0.85:
        # Tends towards 2x2
        return 2, 2
    return 3, 3


def slice_grid(
    image: Image.Image, rows: int, cols: int, inset_pct: float = 0.02
) -> List[Tuple[int, Image.Image]]:
    """
    Slices the image into a grid of cells.

    Args:
        image: PIL Image (already oriented portrait/upright)
        rows: Number of rows (e.g. 3 or 2)
        cols: Number of columns (e.g. 3 or 2)
        inset_pct: Percentage to crop inwards on each cell to avoid plastic sleeve seams.

    Returns:
        List of (cell_index_1_based, cropped_cell_image) in row-major order.
    """
    if rows <= 0 or cols <= 0 or not 0 <= inset_pct < 0.5:
        raise ValueError(
            "Positive grid dimensions and inset between 0 and 0.5 are required."
        )
    w, h = image.size
    cell_w = w / float(cols)
    cell_h = h / float(rows)

    crops = []
    idx = 1

    for r in range(rows):
        for c in range(cols):
            x1 = c * cell_w
            y1 = r * cell_h
            x2 = (c + 1) * cell_w
            y2 = (r + 1) * cell_h

            # Apply slight inset margin
            inset_x = (x2 - x1) * inset_pct
            inset_y = (y2 - y1) * inset_pct

            box = (
                int(x1 + inset_x),
                int(y1 + inset_y),
                int(x2 - inset_x),
                int(y2 - inset_y),
            )

            cropped = image.crop(box)
            crops.append((idx, cropped))
            idx += 1

    return crops
