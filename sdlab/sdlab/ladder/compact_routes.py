"""The ladder pages' small endpoints (compact.py, leaderboard.py), under /api/ladder.

    GET /api/ladder/version                                   {version}: changes whenever the summary does (pages poll this)
    GET /api/ladder/leaderboard?variant=&level=&kind=&set=&age=   the leaderboard's rows for one filter (leaderboard.py)
    GET /api/ladder/matrix?case=                              the matrix view's cells (one case's with case), compact
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from . import cases as casemod
from . import compact, leaderboard

router = APIRouter(prefix="/api/ladder")


@router.get("/version")
def version() -> dict:
    return {"version": leaderboard.summary_now()[1]}


@router.get("/leaderboard")
def board_rows(request: Request, variant: str = "all", level: int = 0, kind: str = "all", set: str = "all", age: str = "") -> Response:   # noqa: A002
    if kind not in ("all", "draws", "fixed") or set not in ("all", "tests", "realistic", "physics", "real") or len(variant) > 64 or len(age) > 8:
        raise HTTPException(422, "variant, level, kind (all, draws, fixed), set (all, tests, realistic, physics), age (o<h>, n<h>)")
    return compact.respond(("leaderboard", variant, level, kind, set, age), lambda: leaderboard.view(variant, level, kind, set, age), request)


@router.get("/matrix")
def matrix(request: Request, case: str | None = None) -> Response:
    if case and not casemod.known(case):
        raise HTTPException(404, f"no case {case!r}")
    return compact.respond(("matrix", case), lambda: compact.matrix(case or None), request)
