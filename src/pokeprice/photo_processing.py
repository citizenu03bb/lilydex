"""Conservative local preparation; retain the whole frame as separate evidence."""

import io
import math
import statistics

from PIL import Image, ImageFilter


def pixel_values(image):
    # Support Pillow 10 as well as the renamed iterator in current releases.
    return (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def fit_sides(quad, points):
    """Fit the straight sides, excluding rounded corners, then intersect them."""
    centre = [sum(p[c] for p in quad) / 4 for c in range(2)]
    lines = []
    for a, b in zip(quad, quad[1:] + quad[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        selected = [
            p
            for p in points
            if 0.15 < ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length**2 < 0.85
            and abs(cross(a, b, p)) / length < 6
        ]
        if len(selected) < 20:
            return quad
        horizontal = abs(dx) > abs(dy)
        independent, dependent = (0, 1) if horizontal else (1, 0)
        mean_x = statistics.mean(p[independent] for p in selected)
        mean_y = statistics.mean(p[dependent] for p in selected)
        variance = sum((p[independent] - mean_x) ** 2 for p in selected)
        if variance < 1:
            return quad
        slope = (
            sum((p[independent] - mean_x) * (p[dependent] - mean_y) for p in selected)
            / variance
        )
        intercepts = sorted(p[dependent] - slope * p[independent] for p in selected)
        centre_value = centre[dependent] - slope * centre[independent]
        intercept = (
            intercepts[0]
            if centre_value > statistics.median(intercepts)
            else intercepts[-1]
        )
        lines.append((-slope, 1, intercept) if horizontal else (1, -slope, intercept))
    refined = []
    for i in range(4):
        a, b, c = lines[i - 1]
        d, e, f = lines[i]
        determinant = a * e - b * d
        if abs(determinant) < 0.1:
            return quad
        point = ((c * e - b * f) / determinant, (a * f - c * d) / determinant)
        if math.dist(point, quad[i]) > 15:
            return quad
        refined.append(point)
    return refined


def corners(points):
    """Reduce a convex silhouette to four corners; reject non-card shapes."""
    points = sorted(set(points))
    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]

    def area(polygon):
        return (
            abs(
                sum(
                    a[0] * b[1] - a[1] * b[0]
                    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True)
                )
            )
            / 2
        )

    hull_area = area(hull)
    quad = hull.copy()
    while len(quad) > 4:
        index = min(
            range(len(quad)),
            key=lambda i: abs(cross(quad[i - 1], quad[i], quad[(i + 1) % len(quad)])),
        )
        quad.pop(index)
    if len(quad) != 4 or area(quad) < hull_area * 0.85:
        return None
    start = min(range(4), key=lambda i: sum(quad[i]))
    quad = quad[start:] + quad[:start]  # top-left, top-right, bottom-right, bottom-left
    lengths = [math.dist(quad[i], quad[(i + 1) % 4]) for i in range(4)]
    if (
        not 0.58 <= (lengths[0] + lengths[2]) / (lengths[1] + lengths[3]) <= 0.86
        or max(lengths[0], lengths[2]) / min(lengths[0], lengths[2]) > 1.5
        or max(lengths[1], lengths[3]) / min(lengths[1], lengths[3]) > 1.5
    ):
        return None
    return fit_sides(quad, points)


def components_of(mask):
    width, height = mask.size
    foreground = bytearray(1 if p else 0 for p in pixel_values(mask))
    components = []
    for index in range(len(foreground)):
        if not foreground[index]:
            continue
        foreground[index] = 0
        todo, points = [index], []
        left, top, right, bottom = width, height, 0, 0
        while todo:
            point = todo.pop()
            y, x = divmod(point, width)
            points.append((x, y))
            left, top = min(left, x), min(top, y)
            right, bottom = max(right, x), max(bottom, y)
            neighbours = []
            if x:
                neighbours.append(point - 1)
            if x + 1 < width:
                neighbours.append(point + 1)
            if y:
                neighbours.append(point - width)
            if y + 1 < height:
                neighbours.append(point + width)
            for other in neighbours:
                if foreground[other]:
                    foreground[other] = 0
                    todo.append(other)
        components.append((len(points), (left, top, right + 1, bottom + 1), points))
    return sorted(components, reverse=True)


def padded_bounds(image, width, height, bounds, quad, points):
    left, top, right, bottom = bounds
    if min(left, top, width - right, height - bottom) < 4:
        return None
    margin = max(4, round((bottom - top) * 0.035))
    box = (
        max(0, left - margin),
        max(0, top - margin),
        min(width, right + margin),
        min(height, bottom + margin),
    )
    if (box[2] - box[0]) * (box[3] - box[1]) > width * height * 0.94:
        return None
    centre = [sum(p[c] for p in quad) / 4 for c in range(2)]
    # Polygon simplification rounds corners inwards. Enclose the ENTIRE detected
    # silhouette first, then add a margin, rather than cutting a rounded corner.
    scale = 1.0
    for a, b in zip(quad, quad[1:] + quad[:1], strict=True):
        centre_distance = cross(a, b, centre)
        if centre_distance <= 0:
            return None
        scale = max(scale, max(1 - cross(a, b, p) / centre_distance for p in points))
    scale = max(1.07, scale * 1.035)
    if scale > 1.25:
        return None
    padded = [[centre[c] + (p[c] - centre[c]) * scale for c in range(2)] for p in quad]
    if any(not (0 <= x < width and 0 <= y < height) for x, y in padded):
        return None
    return {
        "box": [
            round(box[0] * image.width / width),
            round(box[1] * image.height / height),
            round(box[2] * image.width / width),
            round(box[3] * image.height / height),
        ],
        "quad": [
            [round(x * image.width / width, 2), round(y * image.height / height, 2)]
            for x, y in padded
        ],
    }


def yellow_frame_bounds(image):
    """Detect an unbroken yellow frame, including against a textured grey cloth."""
    small = image.copy()
    small.thumbnail((256, 256))
    small = small.filter(ImageFilter.MedianFilter(3))
    width, height = small.size
    if min(width, height) < 50:
        return None
    mask = Image.new("L", small.size)
    mask.putdata(
        [
            255
            if r > 100 and g > 95 and 0.90 < r / g < 1.40 and b < (r + g) * 0.36
            else 0
            for r, g, b in pixel_values(small)
        ]
    )
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    components = components_of(mask)
    if not components:
        return None
    count, bounds, points = components[0]
    left, top, right, bottom = bounds
    if (
        count < width * height * 0.015
        or (right - left) * (bottom - top) < width * height * 0.20
        or sum(c[0] for c in components[1:]) > count * 0.35
    ):
        return None
    quad = corners(points)
    if quad is None:
        return None
    pixels = mask.load()
    for a, b in zip(quad, quad[1:] + quad[:1], strict=True):
        supported = 0
        for i in range(20):
            t = (i + 0.5) / 20
            x, y = round(a[0] + t * (b[0] - a[0])), round(a[1] + t * (b[1] - a[1]))
            if any(
                pixels[px, py]
                for px in range(max(0, x - 2), min(width, x + 3))
                for py in range(max(0, y - 2), min(height, y + 3))
            ):
                supported += 1
        if supported < 16:
            return None
    return padded_bounds(image, width, height, bounds, quad, points)


def plain_card_bounds(image, max_noise=22):
    """Find one upright card on a plain background, otherwise leave it untouched.

    This deliberately avoids guessing a crop for album pages, busy backgrounds,
    clipped cards or strong perspective. Padding retains the border/reference.
    """
    small = image.copy()
    small.thumbnail((256, 256))
    small = small.filter(ImageFilter.MedianFilter(5))
    width, height = small.size
    if min(width, height) < 50:
        return None
    pixels = list(pixel_values(small))
    rim = [
        pixels[y * width + x]
        for y in range(height)
        for x in range(width)
        if x < 3 or y < 3 or x >= width - 3 or y >= height - 3
    ]
    background = [statistics.median(p[c] for p in rim) for c in range(3)]
    background_chroma = max(background) - min(background)

    def distance(pixel):
        # Chroma separates a shaded saturated border (dark blue card back)
        # from a dark neutral mat even when every channel is close.
        return max(
            *(abs(pixel[c] - background[c]) for c in range(3)),
            abs(max(pixel) - min(pixel) - background_chroma),
        )

    noise = sorted(distance(p) for p in rim)[int(len(rim) * 0.95)]
    if noise > max_noise:
        return None
    mask = Image.new("L", small.size)
    mask.putdata([255 if distance(p) > max(30, noise * 2) else 0 for p in pixels])
    # Close small gaps without relying on the colour of the illustration.
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    components = components_of(mask)
    if not components:
        return None
    count, (left, top, right, bottom), points = components[0]
    box_width, box_height = right - left, bottom - top
    # An artwork rectangle alone is generally landscape, unlike the whole card.
    if (
        not 0.58 <= box_width / box_height <= 0.86
        or count < width * height * 0.20
        or count / (box_width * box_height) < 0.72
        or sum(c[0] for c in components[1:]) > count * 0.12
        or min(left, top, width - right, height - bottom) < 4
    ):
        return None
    quad = corners(points)
    if quad is None:
        return None
    return padded_bounds(image, width, height, (left, top, right, bottom), quad, points)


def card_bounds(image, guide=None):
    found = yellow_frame_bounds(image) or plain_card_bounds(image)
    if found or not guide:
        return found
    # The guide region excludes the surroundings (sofa, cloth) and holds one
    # card placed by hand, so a textured mat such as felt is tolerated there.
    left, top, right, bottom = guide_box(image, guide)
    region = image.crop((left, top, right, bottom))
    inner = yellow_frame_bounds(region) or plain_card_bounds(region, max_noise=32)
    if not inner:
        return None
    return {
        "box": [v + (left, top)[i % 2] for i, v in enumerate(inner["box"])],
        "quad": [[x + left, y + top] for x, y in inner["quad"]],
        "within_guide": True,
    }


def neutral_balance(image):
    """Small channel gains from bright near-neutral pixels, never grey-world art."""
    sample = image.copy()
    sample.thumbnail((200, 200))
    neutrals = [
        p
        for p in pixel_values(sample)
        if min(p) >= 100 and max(p) - min(p) <= max(p) * 0.22
    ]
    if len(neutrals) < sample.width * sample.height * 0.02:
        return image, None
    channels = [statistics.median(p[c] for p in neutrals) for c in range(3)]
    target = sum(channels) / 3
    gains = [max(0.92, min(1.08, target / c)) for c in channels]
    if max(abs(g - 1) for g in gains) < 0.01:
        return image, None
    balanced = Image.merge(
        "RGB",
        [
            channel.point([min(255, round(v * gain)) for v in range(256)])
            for channel, gain in zip(image.split(), gains, strict=True)
        ],
    )
    return balanced, [round(g, 4) for g in gains]


def perspective_coefficients(quad, width, height):
    """Output-to-source homography, as required by Pillow PERSPECTIVE."""
    rows = []
    for (x, y), (sx, sy) in zip(
        [(0, 0), (width, 0), (width, height), (0, height)], quad, strict=True
    ):
        rows.append([x, y, 1, 0, 0, 0, -sx * x, -sx * y, sx])
        rows.append([0, 0, 0, x, y, 1, -sy * x, -sy * y, sy])
    for column in range(8):
        pivot = max(range(column, 8), key=lambda i: abs(rows[i][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        if abs(divisor) < 1e-10:
            raise ValueError("Coins trop ambigus pour redresser la perspective.")
        rows[column] = [v / divisor for v in rows[column]]
        for index in range(8):
            if index != column:
                factor = rows[index][column]
                rows[index] = [
                    v - factor * p
                    for v, p in zip(rows[index], rows[column], strict=True)
                ]
    return tuple(row[-1] for row in rows)


def parse_guide(value):
    """Framing guide as frame fractions: "x,y,width,height", inside the frame."""
    try:
        guide = [float(part) for part in value.split(",")]
    except ValueError:
        guide = []
    if (
        len(guide) != 4
        or not all(math.isfinite(v) for v in guide)
        or min(guide[:2]) < 0
        or min(guide[2:]) < 0.2
        or guide[0] + guide[2] > 1.0001
        or guide[1] + guide[3] > 1.0001
    ):
        raise ValueError("Mire de cadrage invalide. Reprenez la photo.")
    return [round(v, 4) for v in guide]


def guide_box(image, guide):
    # The card is placed by hand inside the guide: keep a margin for misalignment.
    x, y, width, height = guide
    margin = 0.06
    return [
        max(0, round((x - width * margin) * image.width)),
        max(0, round((y - height * margin) * image.height)),
        min(image.width, round((x + width * (1 + margin)) * image.width)),
        min(image.height, round((y + height * (1 + margin)) * image.height)),
    ]


def prepare_photo(data, *, crop=True, balance=True, perspective=True, guide=None):
    # Input is already validated, oriented, resized and stripped of EXIF.
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    bounds = card_bounds(image, guide) if crop else None
    box = bounds["box"] if bounds and crop and not perspective else None
    quad = bounds["quad"] if bounds and perspective else None
    # Detected contours always win; the guide only replaces the whole frame.
    from_guide = bool(crop and guide and not bounds)
    if from_guide:
        box = guide_box(image, guide)
    if quad:
        width = round((math.dist(quad[0], quad[1]) + math.dist(quad[2], quad[3])) / 2)
        height = round(width * 88 / 63)
        image = image.transform(
            (width, height),
            Image.Transform.PERSPECTIVE,
            perspective_coefficients(quad, width, height),
            resample=Image.Resampling.BICUBIC,
        )
        image.thumbnail((1600, 1600))
    elif box:
        image = image.crop(box)
    gains = None
    if balance:
        image, gains = neutral_balance(image)
    details = {
        "algorithm": "conservative-card-v1",
        "crop": crop,
        "balance": balance,
        "perspective": perspective,
        "crop_box": box,
        "perspective_quad": quad,
        "color_gains": gains,
        "guide": guide,
        "crop_source": (
            "guide"
            if from_guide
            else None
            if not (box or quad)
            else "contours-in-guide"
            if bounds.get("within_guide")
            else "contours"
        ),
        "message": (
            "Perspective redressée, avec une marge autour de la carte. "
            if quad
            else "Contours incertains : recadrage sur la mire de cadrage. "
            if from_guide
            else "Carte recadrée avec une marge. "
            if box
            else "Contours incertains : photo entière conservée. "
            if crop
            else "Photo entière. "
        )
        + ("Couleurs légèrement équilibrées." if gains else "Couleurs conservées."),
    }
    if not box and not quad and not gains:
        return data, details
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue(), details
