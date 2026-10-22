"""Demo 11, canary guard (docs/demos/canary.md; idea 32 of OPERATIONALIZATION.md).

Two copies of the 310 scenario's service run side by side: the baseline (the true model as it is) and the canary (an
in-memory copy with one rate a little worse: more errors, more timeouts, or slower completions, by 0%, 5%, 15% or
30%). Each runs on its own seed (with counted noise: the ladder's counts, flows move whole requests). The found
model's structure is kept and its numbers are refitted on each copy (attribution.refit: one-step weighted least
squares with block-bootstrap intervals); a number that differs between the two by more than Z standard errors (and
by more than 1% of its value) is a reason to stop. The bootstrap within one run is too narrow (it misses how a
number's refit varies from run to run through the model's misfit), so each number's z is first divided by its spread
over A/A pairs: identical copies on their own seeds (`calibration`). A table over sizes and seeds counts the decisions against the
truth: right stops, false stops (a 0% canary stopped), and missed regressions.

Nothing here changes a case, a simulation, a strategy or the result store. Cache: ~/.cache/sdlab/demos/canary/
(regenerate: `uv run python -m sdlab.demos.canary`)."""

from __future__ import annotations

import functools
import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import attribution as A
from . import demos as D
from . import engine as E

SCEN = A.SCEN
CACHE = Path.home() / ".cache" / "sdlab" / "demos" / "canary"
REGRESSIONS = {
    "errors": {"label": "more failed requests (the error rate goes up)", "flow": "errors", "sign": 1},
    "timeouts": {"label": "more timeouts (the timeout rate goes up)", "flow": "timeouts", "sign": 1},
    "slower": {"label": "slower responses (the completion rate goes down)", "flow": "completed", "sign": -1},
}
SIZES = (0.0, 0.05, 0.15, 0.30)
SEEDS = tuple(range(1, 11))
CAL_SEEDS = tuple(range(101, 113))         # the A/A calibration's own seeds (never the test seeds)
STEPS = (300, 1000)
SHOW = ("errors_total", "retries", "responses_total", "queue")


def _canary_truth(truth: dict, regression: str, size: float) -> tuple[dict, dict]:
    rg = REGRESSIONS[regression]
    tf = next(f for f in truth["flows"] if f["id"] == rg["flow"])
    factor = 1.0 + rg["sign"] * float(size)
    return ({rg["flow"]: E.scale_true_rate(tf["rate"], factor)} if size else {}), tf


def _copy(regression: str, size: float, seed: int, steps: int, counts: bool, which: str) -> dict:
    """One copy's run and refit (cached: a baseline is shared by every size)."""
    on = which == "canary" and bool(size)
    return _copy_cached(regression if on else "", float(size) if on else 0.0, int(seed), int(steps), bool(counts), which)


@functools.lru_cache(maxsize=256)
def _copy_cached(regression: str, size: float, seed: int, steps: int, counts: bool, which: str) -> dict:
    b = D._base(SCEN)
    edits = _canary_truth(b["truth"], regression, size)[0] if which == "canary" and size else {}
    s = (1000 if which == "baseline" else 2000) + seed
    r = A.run(b["truth"], counts=counts, seed=s, edits=edits or None, steps=steps)
    flows0, meas = b["result"]["found"], b["measured"]
    lv = A.carried(flows0, meas, r)
    fit = A.refit(flows0, meas, r["t"], lv, r["inputs"], (1, len(r["t"])), boot=200, block=max(10, steps // 20), seed=s)
    return {"run": r, "fit": fit, "seed": s}


def _zs(base: dict, can: dict) -> list:
    """Each number's difference (canary - baseline) in bootstrap standard errors; None where a copy cannot tell it."""
    out = []
    for x, y in zip(base["fit"]["nums"], can["fit"]["nums"]):
        se, d = math.hypot(x["se"], y["se"]), y["value"] - x["value"]
        ok = x["identified"] and y["identified"]
        out.append((d / se if se > 0 else (0.0 if d == 0 else math.inf)) if ok else None)
    return out


def calibration(steps: int, counts: bool) -> dict:
    """A/A calibration: pairs of identical copies on their own seeds (CAL_SEEDS, never the test seeds). The bootstrap
    within one run misses how much a number's refit varies from run to run (here mostly through the model's misfit on
    memory), so each number's z is divided by its root-mean-square z over the A/A pairs (at least 1). Cached."""
    b = D._base(SCEN)
    path = CACHE / f"cal-{steps}-{'counts' if counts else 'none'}-r{b['result'].get('id')}.json"
    if path.exists():
        return json.loads(path.read_text())
    zs = [_zs(_copy("", 0.0, s, steps, counts, "baseline"), _copy("", 0.0, s, steps, counts, "canary")) for s in CAL_SEEDS]
    keys = [n["key"] for n in _copy("", 0.0, CAL_SEEDS[0], steps, counts, "baseline")["fit"]["nums"]]
    factor = {}
    for j, k in enumerate(keys):
        got = [z[j] for z in zs if z[j] is not None and math.isfinite(z[j])]
        factor[k] = max(1.0, math.sqrt(sum(v * v for v in got) / len(got))) if got else 1.0
    out = {"steps": steps, "counts": counts, "pairs": len(zs), "seeds": list(CAL_SEEDS), "factor": factor}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def compare(regression: str, size: float, seed: int, steps: int, counts: bool) -> dict:
    """The two copies' refitted numbers side by side and the decision."""
    if regression not in REGRESSIONS:
        raise KeyError(regression)
    b = D._base(SCEN)
    base = _copy(regression, 0.0, seed, steps, counts, "baseline")
    can = _copy(regression, size, seed, steps, counts, "canary")
    edits, tf = _canary_truth(b["truth"], regression, size)
    ends = f"{tf.get('from') or 'outside'} → {tf.get('to') or 'outside'}"
    cal = calibration(steps, counts)
    rows = []
    for x, y, zr in zip(base["fit"]["nums"], can["fit"]["nums"], _zs(base, can)):
        d = y["value"] - x["value"]
        big = abs(d) > A.REL * max(abs(x["value"]), 1e-12)
        f = cal["factor"].get(x["key"], 1.0)
        zr = None if zr is None else (zr if math.isfinite(zr) else 1e9)
        z = None if zr is None else zr / f
        rows.append({"key": x["key"], "ends": x["ends"], "label": x["label"], "identified": zr is not None,
                     "baseline": {k: x[k] for k in ("value", "se", "lo", "hi")}, "canary": {k: y[k] for k in ("value", "se", "lo", "hi")},
                     "diff": d, "relative": d / x["value"] if x["value"] else None, "z": z, "z_raw": zr, "factor": f,
                     "flag": bool(z is not None and abs(z) > A.Z and big), "flag_raw": bool(zr is not None and abs(zr) > A.Z and big),
                     "is_changed_flow": x["ends"] == ends})
    flagged = [r for r in rows if r["flag"]]
    worse = size > 0
    stop = bool(flagged)
    verdict = ("right stop" if stop and worse else "false stop" if stop else "missed" if worse else "right go")
    return {"regression": {"key": regression, **REGRESSIONS[regression], "ends": ends, "before": tf.get("rate"),
                           "canary": edits.get(REGRESSIONS[regression]["flow"])},
            "size": size, "seed": seed, "seeds": {"baseline": base["seed"], "canary": can["seed"]}, "steps": steps, "counts": counts,
            "rows": rows, "stop": stop, "verdict": verdict, "flagged": [f"{r['ends']} {r['label']}" for r in flagged],
            "right_number": any(r["is_changed_flow"] for r in flagged), "z": A.Z, "rel": A.REL,
            "stop_raw": any(r["flag_raw"] for r in rows), "calibration": {"pairs": cal["pairs"], "seeds": cal["seeds"]}}


def run_view(regression: str, size: float, seed: int, steps: int, counts: bool) -> dict:
    """compare() plus both copies' levels of a few stocks, and the source, for the page."""
    c = compare(regression, size, seed, steps, counts)
    b = D._base(SCEN)
    base = _copy(regression, 0.0, seed, steps, counts, "baseline")["run"]
    can = _copy(regression, size, seed, steps, counts, "canary")["run"]
    every = max(1, steps // 500)
    c["t"] = base["t"][::every]
    c["stocks"] = {s: {"baseline": A._r(base["levels"][s][::every]), "canary": A._r(can["levels"][s][::every]), "unit": b["units"].get(s)}
                   for s in SHOW}
    c["source"] = D._source(b)
    return c


def _table_file(regression: str, steps: int, counts: bool) -> Path:
    b = D._base(SCEN)
    return CACHE / f"table-{regression}-{steps}-{'counts' if counts else 'none'}-r{b['result'].get('id')}.json"


def table(regression: str, steps: int = 1000, counts: bool = True, compute: bool = True) -> dict:
    """Decisions over sizes and seeds (noise-free: one seed, since every seed is the same run). Cached in a file."""
    if regression not in REGRESSIONS:
        raise KeyError(regression)
    path = _table_file(regression, steps, counts)
    if path.exists():
        return json.loads(path.read_text())
    if not compute:
        return {"regression": regression, "steps": steps, "counts": counts, "cells": None}
    seeds = SEEDS if counts else SEEDS[:1]
    cells = []
    for size in SIZES:
        for s in seeds:
            c = compare(regression, size, s, steps, counts)
            top = max((r for r in c["rows"] if r["z"] is not None), key=lambda r: abs(r["z"]))
            cells.append({"size": size, "seed": s, "stop": c["stop"], "stop_raw": c["stop_raw"], "verdict": c["verdict"], "right_number": c["right_number"],
                          "flagged": c["flagged"], "largest": {"ends": top["ends"], "label": top["label"], "z": top["z"]}})
    summary = {}
    for size in SIZES:
        cs = [x for x in cells if x["size"] == size]
        summary[str(size)] = {"runs": len(cs), "stops": sum(x["stop"] for x in cs), "stops_raw": sum(x["stop_raw"] for x in cs),
                              "right_number": sum(x["stop"] and x["right_number"] for x in cs)}
    out = {"regression": regression, "steps": steps, "counts": counts, "sizes": list(SIZES), "seeds": list(seeds), "cells": cells,
           "summary": summary, "source": D._source(D._base(SCEN)), "z": A.Z, "rel": A.REL}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# ---- routes (under /api/demos) ----

router = APIRouter()


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/canary/options")
def options_route() -> dict:
    return {"regressions": {k: v["label"] for k, v in REGRESSIONS.items()}, "sizes": list(SIZES), "seeds": list(SEEDS), "steps": list(STEPS)}


@router.get("/canary/run")
def run_route(regression: str, size: float = 0.15, seed: int = 1, steps: int = 1000, counts: bool = True) -> dict:
    if size not in SIZES or steps not in STEPS:
        raise HTTPException(400, f"size one of {SIZES}, steps one of {STEPS}")
    return _guard(run_view, regression, size, max(1, min(seed, 99)), steps, counts)


@router.get("/canary/table")
def table_route(regression: str, steps: int = 1000, counts: bool = True) -> dict:
    if steps not in STEPS:
        raise HTTPException(400, f"steps one of {STEPS}")
    return _guard(table, regression, steps, counts)


if __name__ == "__main__":                      # precompute the tables: uv run python -m sdlab.demos.canary
    rid = D._base(SCEN)["result"].get("id")
    for old in list(CACHE.glob(f"cal-*-r{rid}.json")) + list(CACHE.glob(f"table-*-r{rid}.json")):
        old.unlink()
    for rg in REGRESSIONS:
        for st in STEPS:
            for cn in (True, False):
                got = table(rg, st, cn)
                print(rg, st, cn, got["summary"])
