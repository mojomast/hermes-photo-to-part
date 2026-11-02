#!/usr/bin/env python3
"""Check a mesh for watertightness and an expected bounding box."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from photopart.validate import main

if __name__ == "__main__":
    raise SystemExit(main())
