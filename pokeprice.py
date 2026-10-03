#!/usr/bin/env python3
"""
pokeprice CLI launcher script.
"""

import sys
import os

# Add src to python path so it works seamlessly without pip install -e .
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pokeprice.cli import main

if __name__ == "__main__":
    main()
