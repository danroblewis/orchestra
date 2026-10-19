"""Time and runs endpoints (timing.py, runs.py), under /api/ladder. Nothing here reads the store in a
request: each answer is made in a background thread and served from memory ({pending: true} until the
first one is made, at most REFRESH seconds old after that).

    GET /api/ladder/timing                 {strategies: {name: {sets, score, trend}}, sets}: time per cell (discovery
                                           seconds, median, p95, n) per set over each strategy's latest results
    GET /api/ladder/timing/{name}          {stats, versions}: one strategy, and its time per cell per version
    GET /api/ladder/runs                   the runs panel (runs.panel): the watcher's batch, pace, backlog, ETA, recent runs
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException

from . import api, runs, store, timing

router = APIRouter(prefix="/api/ladder")
REFRESH = 20.0
_made: dict = {}                      # (store, key) -> (when, value)
_busy: set = set()
_lock = threading.Lock()


def _all() -> dict:
    t = timing.table()
    sets = timing.case_sets()
    names = sorted({k[2] for k in t.latest})
    return {"sets": list(timing.SETS), "strategies": {n: timing.stats(t, n, sets) for n in names}}


def _one(name: str) -> dict:
    t = timing.table()
    sets = timing.case_sets()
    return {"strategy": name, "sets": list(timing.SETS), "stats": timing.stats(t, name, sets), "versions": timing.versions(t, name, sets)}


def served(key: tuple, make) -> dict:
    """The last value made for key, made again in the background once it is REFRESH seconds old."""
    k = (str(store.path()), *key)
    got = _made.get(k)
    with _lock:
        start = (got is None or time.time() - got[0] >= REFRESH) and k not in _busy
        if start:
            _busy.add(k)
    if start:
        def go():
            try:
                _made[k] = (time.time(), make())
            finally:
                with _lock:
                    _busy.discard(k)
        threading.Thread(target=go, daemon=True).start()
    if len(_made) > 256:
        _made.clear()
    return got[1] if got else {"pending": True}


@router.get("/timing")
def timing_all() -> dict:
    return served(("timing",), _all)


@router.get("/timing/{name}")
def timing_one(name: str) -> dict:
    if name not in api.strategy_names():
        raise HTTPException(404, f"no strategy {name!r}")
    return served(("timing", name), lambda: _one(name))


@router.get("/runs")
def runs_panel() -> dict:
    return runs.panel()
