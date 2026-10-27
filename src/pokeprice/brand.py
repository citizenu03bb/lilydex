"""The site's public name, written once: pages and file names take it from here."""

import re
import unicodedata

SITE_NAME = "Les cartes de Lily"


def site_slug() -> str:
    """The name as it goes into a file name: « Les cartes de Lily » → les-cartes-de-lily."""
    ascii_name = unicodedata.normalize("NFKD", SITE_NAME).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def site_wordmark() -> tuple[str, str]:
    """The logotype's two lines: « Les cartes » in small capitals over « de Lily » in italics.

    The name splits before its last « de » ; a name without one is all italics.
    """
    head, sep, tail = SITE_NAME.rpartition(" de ")
    return (head, "de " + tail) if sep else ("", SITE_NAME)
