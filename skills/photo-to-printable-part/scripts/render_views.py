#!/usr/bin/env python3
"""Render front, side, top, and iso views, with an optional reference photo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from photopart.render import main

if __name__ == "__main__":
    raise SystemExit(main())
