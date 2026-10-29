from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, ImageDraw

from pokeprice.public_media import PRESETS, PublicMedia


def source_photo(tmp_path, size=(1200, 1800), *, exif=None, color='white'):
    directory = tmp_path / 'photos'
    directory.mkdir(exist_ok=True)
    source = directory / 'consultation.jpg'
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    # All four edge markers must survive the resizing, not just a centre crop.
    for box, fill in [((0, 0, 99, 99), 'red'), ((size[0]-100, 0, size[0]-1, 99), 'blue'), ((0, size[1]-100, 99, size[1]-1), 'green'), ((size[0]-100, size[1]-100, size[0]-1, size[1]-1), 'black')]:
        draw.rectangle(box, fill=fill)
    image.save(source, 'JPEG', quality=94, **({'exif': exif} if exif else {}))
    return source


def test_describe_does_not_generate_cache_or_disclose_private_names(tmp_path):
    source = source_photo(tmp_path)
    media = PublicMedia(tmp_path)
    metadata = media.describe(source)
    assert (metadata['width'], metadata['height']) == (1200, 1800)
    by_size = {v['size']: v for v in metadata['variants']}
    assert (by_size['thumb']['width'], by_size['thumb']['height']) == (261, 392)
    assert by_size['thumb']['formats'] == ['jpeg']
    assert by_size['view']['width'] == 640
    assert not media.cache.exists()
    assert source.name not in str(metadata)
    assert str(tmp_path) not in str(metadata)


@pytest.mark.parametrize('preset', PRESETS)
def test_real_dimensions_match_metadata_preserve_edges_and_leave_source_unchanged(tmp_path, preset):
    source = source_photo(tmp_path)
    before = source.read_bytes()
    media = PublicMedia(tmp_path)
    variant = next(v for v in media.describe(source)['variants'] if v['size'] == preset)
    path = media.render(source, preset)
    assert path.parent == tmp_path / 'public-media'
    with Image.open(path) as derivative:
        assert derivative.size == (variant['width'], variant['height'])
        assert derivative.format == 'JPEG'
        assert derivative.width <= PRESETS[preset][0]
        assert derivative.height <= PRESETS[preset][1]
        assert abs(derivative.width / derivative.height - 2 / 3) < 0.003
        assert derivative.getpixel((5, 5))[0] > 200
        assert derivative.getpixel((derivative.width-6, 5))[2] > 180
        assert derivative.getpixel((5, derivative.height-6))[1] > 80
        assert max(derivative.getpixel((derivative.width-6, derivative.height-6))) < 35
    assert source.read_bytes() == before
    assert media.render(source, preset) == path


def test_small_clean_jpeg_is_not_upscaled_or_recompressed(tmp_path):
    source = source_photo(tmp_path, (240, 320))
    media = PublicMedia(tmp_path)
    for variant in media.describe(source)['variants']:
        if variant['size'] == 'thumb':
            continue
        assert (variant['width'], variant['height']) == (240, 320)
        assert variant['formats'] == ['jpeg']
        assert media.render(source, variant['size']).read_bytes() == source.read_bytes()


def test_webp_has_correct_format_dimensions_and_no_private_metadata(tmp_path):
    exif = Image.Exif()
    exif[270] = 'Private camera note'
    exif[315] = 'Private author'
    source = source_photo(tmp_path, exif=exif)
    media = PublicMedia(tmp_path)
    if 'webp' not in media.formats:
        pytest.skip('Pillow has no WebP encoder')
    path = media.render(source, 'view', 'webp')
    with Image.open(path) as derivative:
        assert derivative.format == 'WEBP'
        assert derivative.size == (640, 960)
        assert not derivative.getexif()
        assert 'exif' not in derivative.info
    assert b'Private' not in path.read_bytes()
    assert exif[270] in Image.open(source).getexif().values()


def test_jpeg_rotates_from_exif_then_strips_it(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = 'Private author'
    source = source_photo(tmp_path, (1200, 800), exif=exif)
    media = PublicMedia(tmp_path)
    description = media.describe(source)
    assert (description['width'], description['height']) == (800, 1200)
    variant = next(v for v in description['variants'] if v['size'] == 'view')
    path = media.render(source, 'view')
    with Image.open(path) as derivative:
        assert derivative.size == (variant['width'], variant['height']) == (640, 960)
        assert not derivative.getexif()
        # The lower-left green marker rotates to the upper-left.
        assert derivative.getpixel((5, 5))[1] > 80
        assert derivative.getpixel((5, 5))[0] < 80
    assert b'Private' not in path.read_bytes()


def test_replacing_bytes_at_same_source_path_invalidates_the_cache(tmp_path):
    source = source_photo(tmp_path, color='white')
    media = PublicMedia(tmp_path)
    first = media.render(source, 'view')
    first_bytes = first.read_bytes()
    Image.new('RGB', (1200, 1800), 'black').save(source, 'JPEG')
    second = media.render(source, 'view')
    assert second != first
    assert second.read_bytes() != first_bytes
    with Image.open(second) as image:
        assert max(image.getpixel((100, 100))) < 10


def test_concurrent_generation_is_atomic_and_leaves_no_temporary_files(tmp_path):
    source = source_photo(tmp_path)
    media = PublicMedia(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        paths = list(workers.map(lambda _: media.render(source, 'view'), range(16)))
    assert len(set(paths)) == 1
    with Image.open(paths[0]) as image:
        image.load()
        assert image.size == (640, 960)
    assert sorted(media.cache.iterdir()) == [paths[0]]


def test_only_named_sizes_formats_and_consultation_directory_are_accepted(tmp_path):
    source = source_photo(tmp_path)
    media = PublicMedia(tmp_path)
    for size, format in [('full', 'jpeg'), ('thumb', 'jpeg'), ('arbitrary', 'jpeg'), ('view', 'avif'), ('view', '../jpeg')]:
        with pytest.raises(ValueError):
            media.render(source, size, format)
    outside = tmp_path / 'private-original.jpg'
    outside.write_bytes(source.read_bytes())
    with pytest.raises(ValueError):
        media.describe(outside)
    with pytest.raises(ValueError):
        media.render(outside, 'view')
    symlink = tmp_path / 'photos' / 'escape.jpg'
    symlink.symlink_to(outside)
    with pytest.raises(ValueError):
        media.render(symlink, 'view')
    assert not media.cache.exists()


def test_encoder_without_webp_still_offers_jpeg(monkeypatch, tmp_path):
    monkeypatch.setattr('pokeprice.public_media.features.check', lambda _: False)
    source = source_photo(tmp_path)
    media = PublicMedia(tmp_path)
    assert media.formats == ('jpeg',)
    assert all(v['formats'] == ['jpeg'] for v in media.describe(source)['variants'])
    assert media.render(source, 'view').suffix == '.jpg'
    with pytest.raises(ValueError):
        media.render(source, 'view', 'webp')


@pytest.mark.parametrize('size', [(1600, 1000), (1200, 1200), (101, 1203), (3, 1)])
def test_manifest_records_actual_dimensions_for_every_aspect_ratio(tmp_path, size):
    (tmp_path / 'photos').mkdir()
    source = tmp_path / 'photos' / 'source.jpg'
    Image.new('RGB', size, 'white').save(source, 'JPEG')
    media = PublicMedia(tmp_path)
    for variant in media.describe(source)['variants']:
        if variant['size'] == 'thumb':
            continue
        with Image.open(media.render(source, variant['size'])) as actual:
            assert actual.size == (variant['width'], variant['height'])
            assert actual.width <= size[0] and actual.height <= size[1]
