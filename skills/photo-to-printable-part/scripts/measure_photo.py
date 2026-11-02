#!/usr/bin/env python3
"""Pixel-to-millimetre scale from a coin, a ruler, or a known rectangle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from photopart.launcher import ensure_plugin_python

ensure_plugin_python()

from photopart.measure import main

if __name__ == "__main__":
    raise SystemExit(main())
