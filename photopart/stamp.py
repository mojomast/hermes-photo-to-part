"""Sidecar that records which bytes photo_part_validate actually checked."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_HISTORY_CAP = 20


def mesh_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sidecar_path(mesh: Path) -> Path:
    """`<file>.validate.json` beside the mesh."""
    return Path(str(mesh) + ".validate.json")


def read_sidecar(mesh: Path) -> dict | None:
    path = sidecar_path(mesh)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def stamp_status(mesh: Path) -> dict:
    """Compare the file on disk with the last validation sidecar."""
    digest = mesh_hash(mesh)
    side = sidecar_path(mesh)
    prior = read_sidecar(mesh)
    if prior is None:
        stale = None
    else:
        stale = prior.get("sha256") != digest
    return {
        "sha256": digest,
        "stale_validation": stale,
        "validation_sidecar": str(side.resolve()) if side.is_file() else str(side),
        "validation_ok": None if prior is None else prior.get("ok"),
    }


def write_sidecar(mesh: Path, report: dict) -> dict:
    """Write the sidecar for the current bytes and return the stamp fields.

    `stale_validation` is about the sidecar that was already on disk. The
    previous record is appended to `history` (newest last, capped) instead of
    being dropped. The top-level `sha256` and `ok` stay the latest check.
    """
    status = stamp_status(mesh)
    destination = sidecar_path(mesh)
    status["validation_sidecar"] = str(destination.resolve())
    prior = read_sidecar(mesh)
    history = _history_of(prior)
    validated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = dict(report)
    payload["file"] = str(mesh.resolve())
    payload["sha256"] = status["sha256"]
    payload["stale_validation"] = status["stale_validation"]
    payload["validation_sidecar"] = status["validation_sidecar"]
    payload["validated_at"] = validated_at
    payload["history"] = history
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status["history"] = history
    status["validated_at"] = validated_at
    return status


def _history_of(prior: dict | None) -> list[dict]:
    if not prior:
        return []
    history = []
    previous = prior.get("history")
    if isinstance(previous, list):
        history.extend(item for item in previous if isinstance(item, dict) and "history" not in item)
    if prior.get("sha256"):
        history.append(
            {
                "sha256": prior.get("sha256"),
                "ok": prior.get("ok"),
                "failures": list(prior.get("failures") or []),
                "validated_at": prior.get("validated_at"),
                "file": prior.get("file"),
                "answers": dict(prior.get("answers") or {}),
            }
        )
    return history[-_HISTORY_CAP:]
