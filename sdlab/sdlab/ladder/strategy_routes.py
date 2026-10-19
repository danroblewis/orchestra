"""The strategy page's read-only endpoints (strategy_view.py), under /api/ladder/strategy.

    GET /api/ladder/strategy/{name}                    the page in one compact response: header, totals, timeline, cells
    GET /api/ladder/strategy/{name}/details?ids=1,2    found flows, parts and repairs of some results (at most 40), with the true models
    GET /api/ladder/strategy/{name}/errors?ids=1,2     (found - true) / range per stock over log time to 100k (at most 24)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from . import api, compact, strategy_view

router = APIRouter(prefix="/api/ladder/strategy")


def _name(name: str) -> str:
    if name not in api.strategy_names():
        raise HTTPException(404, f"no strategy {name!r}")
    return name


@router.get("/{name}")
def overview(request: Request, name: str) -> Response:
    _name(name)
    return compact.respond(("strategy", name), lambda: strategy_view.overview(name), request)   # serialized once per summary version


@router.get("/{name}/details")
def details(name: str, ids: str = "") -> dict:
    return strategy_view.details(_name(name), strategy_view.parse_ids(ids, 40))


@router.get("/{name}/errors")
def errors(name: str, ids: str = "") -> dict:
    _name(name)
    return strategy_view.errors(strategy_view.parse_ids(ids, 24))
