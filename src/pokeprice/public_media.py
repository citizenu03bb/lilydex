"""Bounded public consultation derivatives; callers enforce publication visibility.

The source is a consultation photo under ``photos/``. This module neither finds
copies nor reads the collection database. Its cache is disposable derived data.
"""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from PIL import Image, ImageOps, features


# Version includes the resize/encoding contract. Bump when that contract changes.
VERSION = "v1"
PRESETS = {
    "grid2": (560, 784),
    "grid3": (840, 1176),
    "view": (640, 960),
    "view2": (960, 1440),
}
THUMB_BOX = (280, 392)
JPEG_QUALITY = 90
WEBP_QUALITY = 92


def cache_digest(payload, size, format):
    """Stable key shared by rendering and the bounded cache maintenance tool."""
    parameters = f"{VERSION}:{size}:{format}:{JPEG_QUALITY}:{WEBP_QUALITY}".encode()
    return sha256(parameters + b"\0" + payload).hexdigest()


class PublicMedia:
    """Create only named, proportionate variants of an authorized source photo."""

    def __init__(self, root):
        self.root = Path(root)
        self.photos = (self.root / "photos").resolve()
        self.cache = self.root / "public-media"
        self.formats = ("jpeg", "webp") if features.check("webp") else ("jpeg",)
        # Bounded lock storage even when many publications are visited.
        self._locks = tuple(Lock() for _ in range(64))

    def _source(self, source):
        source = Path(source).resolve()
        if source.parent != self.photos:
            raise ValueError("La photo de consultation doit appartenir au dossier photos.")
        return source

    @staticmethod
    def _clean_jpeg(image):
        """A JPEG containing only ordinary JFIF sizing metadata can be copied."""
        return image.format == "JPEG" and not image.getexif() and not (
            set(image.info) - {"jfif", "jfif_version", "jfif_unit", "jfif_density"}
        )

    def describe(self, source):
        """Actual dimensions without generating variants or creating cache files.

        No source name, path, copy identifier, or URL is part of this projection.
        The caller supplies publication URLs and determines permitted formats.
        """
        source = self._source(source)
        with Image.open(source) as image:
            # EXIF orientation can swap the public image's dimensions.
            orientation = image.getexif().get(274)
            width, height = image.size
            raw_size = image.size
            clean_jpeg = self._clean_jpeg(image)
            if orientation in (5, 6, 7, 8):
                width, height = height, width
        variants = []
        for size, box in {"thumb": THUMB_BOX, **PRESETS}.items():
            # Pillow's thumbnail rounding is the output's actual pixel contract.
            fitted = Image.new("1", raw_size if size == "thumb" else (width, height))
            fitted.thumbnail(box, Image.Resampling.LANCZOS)
            formats = (
                ("jpeg",)
                if size == "thumb" or (clean_jpeg and fitted.size == (width, height))
                else self.formats
            )
            variants.append({
                "size": size, "width": fitted.width, "height": fitted.height,
                "formats": list(formats),
            })
        return {"width": width, "height": height, "variants": variants}

    def render(self, source, size, format="jpeg"):
        """Return a cache path after atomically deriving one allowed size/format.

        A cache hit never authorizes serving it. Every caller must check current
        publication and stock availability before calling this method.
        """
        if size not in PRESETS:
            raise ValueError("Taille de consultation inconnue.")
        if format not in self.formats:
            raise ValueError("Format de consultation indisponible.")
        source = self._source(source)
        payload = source.read_bytes()
        digest = cache_digest(payload, size, format)
        target = self.cache / (digest + (".jpg" if format == "jpeg" else ".webp"))
        lock = self._locks[int(digest[:4], 16) % len(self._locks)]
        with lock:
            if target.is_file():
                return target
            self.cache.mkdir(parents=True, exist_ok=True)
            with Image.open(BytesIO(payload)) as opened:
                clean_jpeg = self._clean_jpeg(opened)
                image = ImageOps.exif_transpose(opened).convert("RGB")
                original_size = image.size
                image.thumbnail(PRESETS[size], Image.Resampling.LANCZOS)
                # Conversions retain info, which may contain EXIF/ICC/comments.
                image.info.clear()
                options = (
                    {"quality": JPEG_QUALITY, "optimize": True, "subsampling": 0}
                    if format == "jpeg"
                    else {"quality": WEBP_QUALITY, "method": 6}
                )
                temporary = None
                try:
                    with NamedTemporaryFile(dir=self.cache, suffix=".tmp", delete=False) as stream:
                        temporary = Path(stream.name)
                        if format == "jpeg" and clean_jpeg and image.size == original_size:
                            # Already-small consultation JPEGs lose no detail or
                            # bytes to a pointless second lossy compression.
                            stream.write(payload)
                        else:
                            image.save(stream, "JPEG" if format == "jpeg" else "WEBP", **options)
                    temporary.replace(target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        return target
