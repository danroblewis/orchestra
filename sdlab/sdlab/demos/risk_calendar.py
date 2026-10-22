"""Demo 5, risk calendar (docs/demos/risk-calendar.md; OPERATIONALIZATION.md idea 29), on ladder case
311-k8s-node-pool: the next 30 days of known events (the weekly traffic pattern already in the traffic, a launch, a
planned node maintenance, optionally the case's Mon/Wed/Fri node failures) run through a stored found model and
through the true model (an in-memory copy); each day's worst level of a risk stock against a limit, the days each
one flags, and where they disagree. Nothing here changes a case, a simulation, a strategy or the result store."""

from __future__ import annotations

import functools

import numpy as np
from fastapi import APIRouter, HTTPException

from . import capacity as C

router = APIRouter()

N_DAYS = 30
STEPS = N_DAYS * C.STEPS_PER_DAY
STEPS_PER_HOUR = C.STEPS_PER_DAY // 24
RISKS = {   # the stocks a person might put a limit on, with a default limit (normal weekdays stay under it)
    "queue": {"label": "requests waiting (queue)", "unit": "requests", "limit": 6000},
    "pending": {"label": "pods pending (wanted, not started)", "unit": "pods", "limit": 5},
    "retries": {"label": "requests waiting to retry", "unit": "requests", "limit": 500},
}
RANGE = ("queue", "retries", "pending", "ready", "desired", "cpu")   # stocks checked against the data's range
BEYOND = 1.05                   # a day is "beyond the data" when the found model takes one of them 5% past its highest level there
POD_PER_NODE_MOVED = 3          # a node taken out moves 3 ready pods back to pending (as the case's node failure does)


def events(launch_day: int, launch_boost: float, after_boost: float, maint_day: int, maint_hour: int, maint_hours: int,
           failures: bool) -> tuple[np.ndarray, list[dict], list[dict]]:
    """The traffic series, the injections, and the list of events (for the page)."""
    traffic = np.asarray(C.base_traffic(STEPS), float).copy()
    ev, inj = [], []
    D = C.STEPS_PER_DAY
    if 0 <= launch_day < N_DAYS:
        traffic[launch_day * D:(launch_day + 1) * D] *= 1 + launch_boost
        traffic[(launch_day + 1) * D:] *= 1 + after_boost
        ev.append({"day": launch_day, "kind": "launch", "label": f"launch: traffic +{100 * launch_boost:.0f}% that day, "
                                                                  f"+{100 * after_boost:.0f}% after"})
    if 0 <= maint_day < N_DAYS:
        t0 = maint_day * D + maint_hour * STEPS_PER_HOUR + 1
        t1 = min(STEPS, t0 + maint_hours * STEPS_PER_HOUR)
        inj += [{"t": t0, "stock": "nodes", "amount": -1}, {"t": t0, "stock": "ready", "amount": -POD_PER_NODE_MOVED},
                {"t": t0, "stock": "pending", "amount": POD_PER_NODE_MOVED}, {"t": t1, "stock": "nodes", "amount": 1}]
        ev.append({"day": maint_day, "kind": "maintenance", "label": f"node maintenance {maint_hour:02d}:00–"
                                                                       f"{(maint_hour + maint_hours) % 24:02d}:00 (one node out)"})
    if failures:
        fails = C.case_failures(STEPS)
        inj += fails
        for t in sorted({int(j["t"]) for j in fails if j["stock"] == "nodes" and j["amount"] < 0}):
            ev.append({"day": (t - 1) // D, "kind": "failure", "label": "node failure 10:50 (the case's, back in 2.5 h)"})
    return traffic, inj, sorted(ev, key=lambda e: e["day"])


@functools.lru_cache(maxsize=64)
def _runs(strategy: str, nodes: int, launch_day: int, launch_boost: float, after_boost: float, maint_day: int,
          maint_hour: int, maint_hours: int, failures: bool) -> dict:
    traffic, inj, ev = events(launch_day, launch_boost, after_boost, maint_day, maint_hour, maint_hours, failures)
    keep = tuple(RISKS) + RANGE
    tr = C.run_true(traffic, nodes, inj)
    fo = C.run_found(C.found(strategy)["found"], traffic, nodes, inj)
    return {"truth": {s: tr[s] for s in keep}, "found": {s: fo[s] for s in keep}, "events": ev, "traffic": traffic}


@functools.lru_cache(maxsize=1)
def data_range() -> dict:
    """The highest level of each stock in the data the found models were fitted on (the case's none-long run)."""
    lv = C.setup()["data"]["levels"]
    return {s: float(np.max(lv[s])) for s in RANGE}


def calendar(strategy: str = "milp", stock: str = "queue", limit: float | None = None, nodes: int = 3, launch_day: int = 15,
             launch_boost: float = 0.4, after_boost: float = 0.1, maint_day: int = 22, maint_hour: int = 12, maint_hours: int = 4,
             failures: bool = False) -> dict:
    if stock not in RISKS:
        raise KeyError(stock)
    if nodes not in C.NODE_CHOICES:
        raise KeyError(f"nodes {nodes}")
    limit = float(RISKS[stock]["limit"] if limit is None else limit)
    r = _runs(strategy, nodes, int(launch_day), round(float(launch_boost), 3), round(float(after_boost), 3), int(maint_day),
              int(maint_hour), int(maint_hours), bool(failures))
    D = C.STEPS_PER_DAY
    top = data_range()
    days = []
    for d in range(N_DAYS):
        sl = slice(d * D, (d + 1) * D)
        wt, wf = float(np.max(r["truth"][stock][sl])), float(np.max(r["found"][stock][sl]))
        ht = int(np.sum(r["truth"][stock][sl] >= limit)) / STEPS_PER_HOUR
        hf = int(np.sum(r["found"][stock][sl] >= limit)) / STEPS_PER_HOUR
        days.append({"day": d, "weekday": C.DAYS[d % 7], "truth": round(wt, 2), "found": round(wf, 2),
                     "truth_hours": round(ht, 2), "found_hours": round(hf, 2), "truth_flag": wt >= limit, "found_flag": wf >= limit,
                     "events": [e["kind"] for e in r["events"] if e["day"] == d],
                     "beyond": [s for s in RANGE if float(np.max(r["found"][s][sl])) > BEYOND * top[s]]})
    ft = {x["day"] for x in days if x["truth_flag"]}
    ff = {x["day"] for x in days if x["found_flag"]}
    every = 12                                                        # hourly points for the 30-day chart
    return {"source": C.source(strategy), "stock": stock, "risk": RISKS[stock], "limit": limit, "nodes": nodes, "days": days,
            "events": r["events"], "flagged": {"both": sorted(ft & ff), "found_only": sorted(ff - ft), "truth_only": sorted(ft - ff)},
            "t": list(range(1, STEPS + 1))[::every],
            "series": {"truth": [round(float(x), 2) for x in r["truth"][stock][::every]],
                       "found": [round(float(x), 2) for x in r["found"][stock][::every]]},
            "data_max": {k: round(v, 2) for k, v in top.items()}, "caps": C.caps(strategy),
            "risks": {k: {"label": v["label"], "unit": v["unit"], "limit": v["limit"]} for k, v in RISKS.items()},
            "strategies": list(C.STRATEGIES), "node_choices": list(C.NODE_CHOICES), "steps_per_day": D}


@router.get("/risk-calendar/days")
def days_route(strategy: str = "milp", stock: str = "queue", limit: float | None = None, nodes: int = 3, launch_day: int = 15,
               launch_boost: float = 0.4, after_boost: float = 0.1, maint_day: int = 22, maint_hour: int = 12,
               maint_hours: int = 4, failures: bool = False) -> dict:
    try:
        return calendar(strategy, stock, limit, nodes, max(-1, min(launch_day, N_DAYS - 1)), max(0.0, min(launch_boost, 2.0)),
                        max(0.0, min(after_boost, 1.0)), max(-1, min(maint_day, N_DAYS - 1)), max(0, min(maint_hour, 23)),
                        max(1, min(maint_hours, 12)), failures)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None
