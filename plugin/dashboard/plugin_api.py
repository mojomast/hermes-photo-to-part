"""Part studio routes mounted at /api/plugins/photo-to-part/.

The desktop pane calls these with ctx.rest. Handlers return JSON. They do not
read credentials, open a socket of their own, or serve files outside the
project that wrote the progress record.
"""

from __future__ import annotations

from fastapi import APIRouter

from photopart.pane import get_run, health, list_runs, read_media

router = APIRouter()


@router.get("/health")
def route_health():
    return health()


@router.get("/runs")
def route_runs():
    return list_runs()


@router.get("/runs/{run_id}")
def route_run(run_id: str):
    return get_run(run_id)


@router.get("/media")
def route_media(run: str, path: str):
    return read_media(run, path)
