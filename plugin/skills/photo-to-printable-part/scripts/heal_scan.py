#!/usr/bin/env python3
"""Heal a scan mesh into a new STL. This does not rebuild CAD faces."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from photopart.launcher import ensure_plugin_python

ensure_plugin_python()

from photopart.heal import main

if __name__ == "__main__":
    raise SystemExit(main())
