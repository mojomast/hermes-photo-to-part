"""A stand-in ``hermes_constants`` for unit tests that run outside Hermes.

Real Hermes resolves ``get_hermes_home()`` from the active profile, which is
``HERMES_HOME`` in a single-profile process. This stub does the same and
raises when the variable is unset, so a test never falls back to the real
``~/.hermes``.
"""

from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path


def _get_hermes_home() -> Path:
    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        raise RuntimeError("test stub: HERMES_HOME is not set")
    return Path(raw)


def install() -> object:
    """Install the stub and return whatever was there before."""
    previous = sys.modules.get("hermes_constants")
    module = types.ModuleType("hermes_constants")
    module.get_hermes_home = _get_hermes_home
    module.P2P_TEST_STUB = True
    sys.modules["hermes_constants"] = module
    return previous


def restore(previous: object) -> None:
    if previous is None:
        sys.modules.pop("hermes_constants", None)
    else:
        sys.modules["hermes_constants"] = previous


@contextmanager
def hermes_home_stub():
    previous = install()
    try:
        yield
    finally:
        restore(previous)
