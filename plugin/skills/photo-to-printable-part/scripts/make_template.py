#!/usr/bin/env python3
"""Write the sample plate-clip. Run from any working directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from photopart.launcher import ensure_plugin_python

ensure_plugin_python()

from photopart.geometry import main

if __name__ == "__main__":
    raise SystemExit(main())
