"""Read-only endpoints for the mathematical analysis of cases (analysis.py) and the sweeps' phase
diagrams (sweep.py), under /api/ladder:

    GET /api/ladder/analysis/{case}/{variant}       what the data can deliver: label, p, design, bound, parts
    GET /api/ladder/sweeps                          every sweep: axis, values, draws, variants
    GET /api/ladder/sweeps/{base}/{variant}         its phase diagram as data (?strategies=a,b)
    GET /api/ladder/sweeps/{base}/{variant}.svg     the same as a chart

A case, variant, sweep or strategy must be one the listings name (404 otherwise).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..discovery.api import jsonable
from . import analysis, catalog, sweep
from . import cases as casemod

router = APIRouter(prefix="/api/ladder")


def _sweep(base: str, variant: str) -> dict:
    for s in sweep.sweeps():
        if s["base"] == base:
            if variant not in s["variants"]:
                raise HTTPException(404, f"no variant {variant!r}")
            return s
    raise HTTPException(404, f"no sweep {base!r}")


def _strategies(strategies: str | None) -> list[str] | None:
    if not strategies:
        return None
    names = [n.strip() for n in strategies.split(",") if n.strip()]
    known = set(catalog.names())
    for n in names:
        if n not in known:
            raise HTTPException(404, f"no strategy {n!r}")
    return names


@router.get("/analysis/{case_id}/{variant}")
def case_analysis(case_id: str, variant: str) -> dict:
    if not casemod.known(case_id):
        raise HTTPException(404, f"no case {case_id!r}")
    c = casemod.load(case_id)
    if variant not in [v["name"] for v in c["variants"]]:
        raise HTTPException(404, f"no variant {variant!r}")
    return jsonable(analysis.get(case_id, variant))


@router.get("/sweeps")
def sweeps() -> list[dict]:
    return jsonable(sweep.sweeps())


@router.get("/sweeps/{base}/{variant}.svg")
def sweep_svg(base: str, variant: str, strategies: str | None = None) -> Response:
    _sweep(base, variant)
    return Response(sweep.svg(base, variant, _strategies(strategies)), media_type="image/svg+xml")


@router.get("/sweeps/{base}/{variant}")
def sweep_phase(base: str, variant: str, strategies: str | None = None) -> dict:
    _sweep(base, variant)
    return jsonable(sweep.phase(base, variant, _strategies(strategies)))
