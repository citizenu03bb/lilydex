"""Optional dependencies: say which extra to install when one is missing.

The base install serves the server (web app, assistant, timers). The album
scanner and the import of its reports need the ``cli`` extra.
"""

import importlib
from types import ModuleType


class MissingExtra(ImportError):
    """A package from an optional extra is not installed."""


def missing_extra(package: str, extra: str) -> MissingExtra:
    return MissingExtra(
        f"Le paquet « {package} » n'est pas installé : il fait partie de l'extra « {extra} ». "
        f"Installez-le avec `uv sync --extra {extra}` (ou `pip install 'pokeprice[{extra}]'`)."
    )


def require(package: str, extra: str) -> ModuleType:
    """Import an optional package, or say which extra provides it."""

    try:
        return importlib.import_module(package)
    except ImportError as error:
        raise missing_extra(package, extra) from error
