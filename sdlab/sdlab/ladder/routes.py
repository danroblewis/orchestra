"""The ladder's read-only endpoints (the read API in api.py, under /api/ladder).

    GET /api/ladder/cases                                     every case (metadata, variants, truth model)
    GET /api/ladder/cases/{case}                              one case
    GET /api/ladder/strategies                                every strategy (name, hash, available, reason)
    GET /api/ladder/results?case=&variant=&strategy=          latest result per (case, variant, strategy)
    GET /api/ladder/results/{case}/{variant}/{strategy}       the latest one, with the found flows
    GET /api/ladder/results/{case}/{variant}/{strategy}/history   every result for it, newest first
    GET /api/ladder/cases/{case}/data/{variant}?fresh=        the case's data in a variant (levels, every stock's levels, eras)
    GET /api/ladder/result/{id}                               one stored result by id, with the found flows
    GET /api/ladder/strategies/{strategy}/timeline            the strategy's totals after each version
    GET /api/ladder/board?strategy=&variant=                  every case with one strategy's latest results (default: the best strategy; variant all)
    GET /api/ladder/progress?recent=                          the current or last run (recent: only running + the n latest done)
    GET /api/ladder/summary?strategies=a,b                    the matrix (cells, per-tag and per-strategy totals)

Nothing takes a path from the client: a case, variant or strategy must be one the listings name
(404 otherwise).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import api
from . import cases as casemod

router = APIRouter(prefix="/api/ladder")


def _case(case_id: str) -> dict:
    if not casemod.known(case_id):
        raise HTTPException(404, f"no case {case_id!r}")
    return casemod.load(case_id)


def _variant(c: dict | None, name: str) -> str:
    known = [v["name"] for v in c["variants"]] if c else list(dict.fromkeys(v["name"] for i in casemod.case_ids() for v in casemod.load(i)["variants"]))
    if name not in known:
        raise HTTPException(404, f"no variant {name!r}")
    return name


def _strategy(name: str) -> str:
    if name not in api.strategy_names():
        raise HTTPException(404, f"no strategy {name!r}")
    return name


@router.get("/cases")
def cases() -> list[dict]:
    return api.cases()


@router.get("/cases/{case_id}")
def case(case_id: str) -> dict:
    _case(case_id)
    return api.case(case_id)


@router.get("/strategies")
def strategies() -> list[dict]:
    return api.strategies()


@router.get("/results")
def results(case: str | None = None, variant: str | None = None, strategy: str | None = None) -> list[dict]:
    c = _case(case) if case else None
    if variant:
        _variant(c, variant)
    if strategy:
        _strategy(strategy)
    return api.results(case, variant, strategy)


@router.get("/results/{case_id}/{variant}/{strategy}")
def result(case_id: str, variant: str, strategy: str) -> dict:
    _variant(_case(case_id), variant)
    _strategy(strategy)
    r = api.result(case_id, variant, strategy)
    if r is None:
        raise HTTPException(404, "not run yet")
    return r


@router.get("/results/{case_id}/{variant}/{strategy}/history")
def history(case_id: str, variant: str, strategy: str) -> list[dict]:
    _variant(_case(case_id), variant)
    _strategy(strategy)
    return api.history(case_id, variant, strategy)


@router.get("/cases/{case_id}/data/{variant}")
def case_data(case_id: str, variant: str, fresh: bool = False) -> dict:
    _variant(_case(case_id), variant)
    return api.case_data(case_id, variant, fresh)


@router.get("/result/{result_id}")
def result_by_id(result_id: int) -> dict:
    r = api.result_by_id(result_id)
    if r is None:
        raise HTTPException(404, "no such result")
    return r


@router.get("/strategies/{strategy}/timeline")
def timeline(strategy: str) -> list[dict]:
    return api.timeline(_strategy(strategy))


@router.get("/board")
def board(strategy: str | None = None, variant: str | None = None) -> dict:
    name = _strategy(strategy) if strategy else api.best_strategy()
    if name is None:
        raise HTTPException(404, "no strategy is available")
    if variant and variant != "all":
        _variant(None, variant)
    return api.board(name, None if not variant or variant == "all" else variant)


@router.get("/progress")
def progress(recent: int | None = None) -> dict:
    return api.progress(None if recent is None else max(0, min(recent, 1000)))


@router.get("/summary")
def summary(strategies: str | None = None) -> dict:
    names = [_strategy(n.strip()) for n in strategies.split(",") if n.strip()] if strategies else None
    return api.summary(names)
