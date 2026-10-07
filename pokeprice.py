#!/usr/bin/env python3
"""
pokeprice CLI launcher script.
"""

import sys
from pathlib import Path

source = Path(__file__).resolve().parent / "src"

if __name__ == "__main__":
    sys.path.insert(0, str(source))
    from pokeprice.cli import main
    main()
else:
    # Importing from the checkout should load the package, not this CLI module.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        __name__, source / "pokeprice" / "__init__.py",
        submodule_search_locations=[str(source / "pokeprice")],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[__name__] = package
    spec.loader.exec_module(package)
