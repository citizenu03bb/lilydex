import io

import pytest
from PIL import Image, ImageDraw

from pokeprice.photo_processing import (
    neutral_balance,
    parse_guide,
    perspective_coefficients,
    prepare_photo,
)


def image_bytes(image):
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=95)
    return stream.getvalue()


def card_scene(quad=None):
    image = Image.new("RGB", (420, 540), (30, 32, 30))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        quad or [(100, 70), (310, 70), (310, 365), (100, 365)], fill=(235, 224, 197)
    )
    # Distinct marker near the reference and at each corner, retained by padding.
    for point in quad or [(103, 73), (307, 73), (307, 362), (103, 362)]:
        x, y = point
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill="red")
    draw.text((115, 340), "077/203", fill="black")
    return image_bytes(image)


def test_crop_retains_reference_and_can_return_exact_initial_frame():
    original = card_scene()
    prepared, report = prepare_photo(original, perspective=False, balance=False)
    assert report["crop_box"]
    left, top, right, bottom = report["crop_box"]
    assert left < 100 and top < 70 and right > 310 and bottom > 365
    assert Image.open(io.BytesIO(prepared)).height < 540
    unchanged, report = prepare_photo(
        original, crop=False, perspective=False, balance=False
    )
    assert unchanged == original and not report["color_gains"]


def test_projective_map_preserves_all_four_corners():
    quad = [(95, 80), (290, 105), (322, 390), (72, 405)]
    a, b, c, d, e, f, g, h = perspective_coefficients(quad, 220, 308)
    for (x, y), (sx, sy) in zip(
        [(0, 0), (220, 0), (220, 308), (0, 308)], quad, strict=True
    ):
        denominator = g * x + h * y + 1
        assert abs((a * x + b * y + c) / denominator - sx) < 1e-7
        assert abs((d * x + e * y + f) / denominator - sy) < 1e-7
    original = card_scene(quad)
    prepared, report = prepare_photo(original, balance=False)
    assert report["perspective_quad"]
    image = Image.open(io.BytesIO(prepared))
    assert abs(image.width / image.height - 63 / 88) < 0.01
    assert image.getpixel((image.width // 2, image.height // 2))[0] > 200


def test_ambiguous_multiple_or_clipped_cards_are_not_cropped():
    for kind in ["uniform", "multiple", "clipped", "landscape-art"]:
        image = Image.new("RGB", (420, 540), "black")
        draw = ImageDraw.Draw(image)
        if kind == "multiple":
            draw.rectangle((20, 30, 185, 262), fill="white")
            draw.rectangle((220, 280, 385, 512), fill="white")
        elif kind == "clipped":
            draw.rectangle((0, 50, 230, 372), fill="white")
        elif kind == "landscape-art":
            draw.rectangle((70, 140, 350, 320), fill="green")
        original = image_bytes(image)
        result, report = prepare_photo(original, balance=False)
        assert result == original
        assert not report["crop_box"] and not report["perspective_quad"]


def test_balance_is_bounded_and_does_not_neutralize_blue_card_backs():
    yellow = Image.new("RGB", (200, 200), (235, 224, 197))
    corrected, gains = neutral_balance(yellow)
    assert gains and all(0.92 <= g <= 1.08 for g in gains)
    assert max(corrected.getpixel((50, 50))) - min(corrected.getpixel((50, 50))) < 38
    blue = Image.new("RGB", (200, 200), (30, 65, 180))
    unmodified, gains = neutral_balance(blue)
    assert gains is None and unmodified.tobytes() == blue.tobytes()


def test_yellow_frame_on_textured_background_and_missing_side():
    scene = Image.new("RGB", (420, 540), (200, 200, 200))
    draw = ImageDraw.Draw(scene)
    for y in range(0, 540, 9):
        draw.rectangle((0, y, 420, y + 4), fill=(80, 80, 80))
    draw.rectangle((100, 70, 310, 365), fill=(230, 205, 40))
    draw.rectangle((108, 78, 302, 357), fill=(120, 85, 160))
    original = image_bytes(scene)
    _, report = prepare_photo(original, balance=False)
    assert report["perspective_quad"]
    # Three yellow sides cannot establish the missing edge safely.
    for y in range(354, 366):
        draw.line(
            (100, y, 310, y), fill=(80, 80, 80) if y % 9 <= 4 else (200, 200, 200)
        )
    original = image_bytes(scene)
    result, report = prepare_photo(original, balance=False)
    assert result == original and not report["perspective_quad"]


def test_guide_crops_only_when_contours_are_uncertain():
    guide = parse_guide("0.25,0.2,0.5,0.6")
    uniform = image_bytes(Image.new("RGB", (400, 500), "black"))
    prepared, report = prepare_photo(uniform, balance=False, guide=guide)
    assert report["crop_source"] == "guide" and report["guide"] == guide
    # A 6 % margin around the guide absorbs a card placed slightly off-centre.
    assert report["crop_box"] == [88, 82, 312, 418]
    assert Image.open(io.BytesIO(prepared)).size == (224, 336)
    _, report = prepare_photo(card_scene(), balance=False, guide=guide)
    assert report["perspective_quad"] and report["crop_source"] == "contours"
    unchanged, report = prepare_photo(
        uniform, crop=False, balance=False, perspective=False, guide=guide
    )
    assert unchanged == uniform and report["crop_source"] is None


def test_guide_must_lie_inside_the_frame():
    assert parse_guide("0.1,0.1,0.8,0.8") == [0.1, 0.1, 0.8, 0.8]
    for value in [
        "",
        "0.1,0.1,0.8",
        "0.5,0.1,0.8,0.8",
        "-0.1,0,0.5,0.5",
        "0,0,0.1,0.5",
        "nan,0,0.5,0.5",
        "a,b,c,d",
    ]:
        with pytest.raises(ValueError):
            parse_guide(value)


def test_card_back_on_felt_is_found_inside_the_guide():
    # Felt-like noise, a red cloth along the edge and a blue card back.
    scene = Image.new("RGB", (400, 800), (55, 52, 52))
    draw = ImageDraw.Draw(scene)
    for i in range(0, 400 * 800, 7):
        x, y = i % 400, i // 400
        draw.point((x, y), fill=(80, 76, 76) if (x * 7 + y * 13) % 5 else (30, 28, 28))
    draw.rectangle((0, 680, 400, 800), fill=(170, 30, 25))
    draw.rectangle((95, 230, 300, 516), fill=(40, 95, 180))
    draw.rectangle((110, 250, 285, 496), fill=(120, 160, 220))
    # Shaded border on the far side of the light: close to the mat per channel.
    draw.polygon([(300, 380), (300, 516), (230, 516)], fill=(20, 47, 94))
    original = image_bytes(scene)
    _, report = prepare_photo(original, balance=False)
    assert report["crop_source"] is None
    prepared, report = prepare_photo(
        original, balance=False, guide=parse_guide("0.1,0.2206,0.8,0.5587")
    )
    assert report["crop_source"] == "contours-in-guide"
    quad = report["perspective_quad"]
    left, top = quad[0]
    assert 80 < left < 95 and 215 < top < 230
    # The shaded corner must not pull the right side inwards (skew).
    assert abs(quad[1][0] - quad[2][0]) < 6
    image = Image.open(io.BytesIO(prepared))
    assert abs(image.width / image.height - 63 / 88) < 0.01
