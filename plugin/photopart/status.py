"""Human-readable status lines. Checkers keep stdout for JSON."""

from __future__ import annotations

import sys


def status(message: str) -> None:
    """Print a status line to stderr so stdout stays one JSON object."""
    print(message, file=sys.stderr, flush=True)
