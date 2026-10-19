"""The newest cases view's read-only endpoints (newest.py), under /api/ladder/newest.

    GET /api/ladder/newest?strategies=a,b     every case file newest first, with when/why it was added, what it
                                              tests, the leaders' results, the pass-rate impact and regressions
    GET /api/ladder/newest/ages               {now, added: {file id: when}, regressions totals}: for the leaderboard
    GET /api/ladder/newest/regressions        every regression (a strategy now worse than its previous version)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from . import api, newest

router = APIRouter(prefix="/api/ladder/newest")


@router.get("")
def overview(strategies: str | None = None) -> Response:
    names = [n.strip() for n in strategies.split(",") if n.strip()][:20] if strategies else None
    for n in names or ():
        if n not in api.strategy_names():
            raise HTTPException(404, f"no strategy {n!r}")
    return Response(newest.view_json(names), media_type="application/json")


@router.get("/ages")
def ages() -> dict:
    return newest.ages()


@router.get("/regressions")
def regressions() -> dict:
    r = newest.regressions()
    return r if r is not None else {"items": [], "n": None, "pending": True}
