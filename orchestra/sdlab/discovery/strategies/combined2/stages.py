"""The three specialists that are combined plus one stage, run as that stage on combined2's own base
instead of on their own copies of combined (so the base runs once):

- kalman (kalman_lna, as at 6a93270): levels that are reports, not the stocks. Before the base, on
  up to SMALL stocks, uneven reports or announced injections, the filter's superset is fitted; when
  the levels carry a measurement error, gross errors or uneven reports, the filter's model is the
  answer (the base's one-step judge assumes exact levels and cannot rank it). After the base, a
  reporting delay or a stock counted at a scale may still send the data to the filter.
- structures (as at 7e0a2bf): products of stocks, goal gaps over several stocks, a hidden Erlang
  chain. The search's model replaces the base's when combined's judge prefers it (BIC) and it
  behaves as well over many steps with no more numbers, or clearly better with more.
- archetypes (as at 3c3e009): classic structures fitted by their free run. Below 20 steps (where
  the matrix method and everything on it return nothing) it is the answer; otherwise, on up to 3
  stocks and 120 steps, its model replaces the base's when it forecasts the run's last quarter
  better from the first three. The base is refitted on the first part by its structure (refit.py:
  least squares of the one-step changes), not rediscovered as archetypes does, so the base's
  discovery runs once.

Each function's code is the specialist's own identify() (vendored in _vendored/), with the base a
callable or a result passed in.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ._vendored.archetypes import SHORT, discover as arch_discover
from ._vendored.archetypes.holdout import cut_run, error, forecast, persistence
from ._vendored.combined import judge as J
from ._vendored.combined.deadline import Overrun, deadline, outer_left
from ._vendored.combined.refit import refit
from ._vendored.kalman_lna import _levels, noisy, scale_pattern
from ._vendored.kalman_lna import CHECK, SMALL
from ._vendored.kalman_lna.run import BUDGET, FAILURES, Session
from ._vendored.structures import CLEARLY
from ._vendored.structures.discover import discover as struct_discover

ARCH = {"seconds": 60.0, "powers": [0.0, 0.5, 1.0], "base": "combined", "alone": False, "max_steps": 120, "max_stocks": 3,
        "moves": True, "hidden": True, "price": True}


# ---- kalman_lna -------------------------------------------------------------------------------

class Kalman:
    """kalman_lna's identify() split in two: before() may answer alone; after(base) may replace it."""

    def __init__(self, stocks: list[dict], run: dict, opts: dict):
        self.stocks, self.run, self.opts = stocks, run, opts
        t, Y = _levels(stocks, run)
        self.uneven = len(t) > 1 and (bool(np.any(np.diff(t) != 1)) or not np.isfinite(Y).all())
        self.ses = Session(stocks, run, opts)
        self.info: dict = {}
        self.prepared = False

    def _allow(self, share: float, most: float) -> None:
        left = outer_left()
        self.ses.allow(min(most, share * left) if left else most)

    def _kalman(self, why: str) -> dict | None:
        self._allow(0.6, BUDGET)
        try:
            got = self.ses.finish()
        except FAILURES as e:
            self.ses.trace.append(f"failed: {type(e).__name__}: {e}")
            return None
        return {**got, "kalman": {"reading": why, **self.info}}

    def before(self) -> dict | None:
        """The filter's model when the reports need it, else None (the base runs)."""
        ses = self.ses
        if self.uneven or len(self.stocks) <= SMALL or self.opts.get("injections"):
            self._allow(0.6 if self.uneven else 0.25, BUDGET if self.uneven else CHECK)
            try:
                self.prepared = ses.prepare()
                if self.prepared and not self.uneven:
                    self.info["evidence"] = ses.evidence()
            except FAILURES as e:
                ses.trace.append(f"failed: {type(e).__name__}: {e}")
                self.prepared = False
        gross = int(ses.gross.sum()) if self.prepared else 0
        if self.prepared and (self.uneven or noisy(self.info["evidence"]) or gross):
            return self._kalman("uneven" if self.uneven else "meas" if noisy(self.info["evidence"]) else "outliers")
        return None

    def after(self, r: dict) -> dict:
        """The base's answer, or the filter's when it reads a reporting delay or a scale."""
        if self.prepared and not self.uneven:
            scaled = scale_pattern(r.get("flows") or [])
            if self.ses.lag or scaled:
                got = self._kalman("lag" if self.ses.lag else "scale")
                if got is not None and (got.get("lag") or got.get("scales")):
                    return got
        return {**r, "kalman": {"reading": None, **{k: v for k, v in self.info.items() if k != "trace"}}}


# ---- structures -------------------------------------------------------------------------------

def structures(base: dict, stocks: list[dict], run: dict, opts: dict, seconds: float = 90.0, slack: float = 0.02) -> dict:
    """structures' identify() with the base given: the search's model when the judge prefers it."""
    left = outer_left()
    cap = float(seconds) if left is None else min(float(seconds), 0.6 * left - 10)
    began = time.perf_counter()
    mine, why = None, None
    if opts.get("eras") and len(opts["eras"]) > 1:
        why = "announced eras (the search fits one set of numbers)"
    elif cap < 1:
        why = "no time left"
    else:
        try:
            with deadline(cap + 1.0):
                mine = struct_discover(stocks, run, opts, seconds=cap, chains=True, products=True, base_flows=base.get("flows"))
            why = None if mine else "no model in time"
        except Overrun:
            why = "no model in time"
        except Exception as e:                           # noqa: BLE001
            why = f"{type(e).__name__}: {e}"[:300]
    info = {"search_seconds": round(time.perf_counter() - began, 2), "why": why}
    if mine and mine.get("flows"):
        try:
            info.update(_compare(mine, base, stocks, run, opts, slack))
        except Exception as e:                           # noqa: BLE001
            info["judge_error"] = f"{type(e).__name__}: {e}"[:300]
        info["terms"] = mine.get("terms")
    if info.get("chosen") == "structures":
        out = {k: v for k, v in mine.items() if k in ("flows", "inferred_levels")}
        out["method"] = "structures"
        out["structures"] = info
        return out
    return {**base, "structures": info}


def _compare(mine: dict, base: dict, stocks: list[dict], run: dict, opts: dict, slack: float) -> dict:
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    starts_m = {h: v[0] for h, v in (mine.get("inferred_levels") or {}).items() if v}
    starts_b = {h: v[0] for h, v in (base.get("inferred_levels") or {}).items() if v}
    sm = J.score(mine["flows"], data, 1.0, 0.0, starts_m)
    sb = J.score(base.get("flows") or [], data, 1.0, 0.0, starts_b)
    out = {"bic": {"structures": round(sm["bic"], 3), "base": round(sb["bic"], 3)}, "numbers": {"structures": sm["k"], "base": sb["k"]}}
    if not sm["bic"] < sb["bic"]:
        return out
    bm = J.behaviour(mine["flows"], data, run, starts_m)
    bb = J.behaviour(base.get("flows") or [], data, run, starts_b) if base.get("flows") else float("inf")
    out["behaviour"] = {"structures": round(bm, 6), "base": round(bb, 6)}
    if (sm["k"] <= sb["k"] and bm <= bb * (1 + slack) + 1e-9) or bm <= CLEARLY * bb:
        out["chosen"] = "structures"
    return out


# ---- archetypes -------------------------------------------------------------------------------

def short(stocks: list[dict], run: dict, opts: dict) -> bool:
    return len(run["t"]) - 1 < SHORT


def archetypes_alone(stocks: list[dict], run: dict, opts: dict) -> dict:
    r = arch_discover(stocks, run, opts, dict(ARCH))
    return {**(r or {"flows": []}), "method": "archetypes"}


def archetypes(base: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    """archetypes' identify() with the base given (20 steps or more)."""
    cfg = dict(ARCH)
    T = len(run["t"]) - 1
    if len(stocks) > cfg["max_stocks"] or T > cfg["max_steps"] or (opts.get("eras") and len(opts["eras"]) > 1):
        return base
    mine = arch_discover(stocks, run, opts, cfg)
    if not mine or not mine.get("flows"):
        return base
    info = {**mine["archetypes"], **_choose(base, stocks, run, opts, cfg)}
    if info["chosen"] == "archetypes":
        return {**mine, "archetypes": info, "method": "archetypes"}
    return {**base, "archetypes": {k: info[k] for k in ("chosen", "holdout") if k in info}}


def _base_on(base: dict, stocks: list[dict], r: dict, o: dict) -> dict | None:
    """The base's structure with its numbers refitted on the first part of the run."""
    flows = base.get("flows") or []
    if not flows:
        return None
    data = J.Data(stocks, r, o.get("injections"), o.get("inputs"))
    try:
        got = refit(flows, data, J.weights(flows, data))
    except Exception:                                    # noqa: BLE001
        got = None
    return {"flows": got or flows, **({"inferred_levels": base["inferred_levels"]} if base.get("inferred_levels") else {})}


def _choose(base: dict, stocks: list[dict], run: dict, opts: dict, cfg: dict) -> dict:
    ids = [s["id"] for s in stocks]
    N = len(run["t"])
    n = min(N - 3, int(round(0.75 * N)))
    if n < 5:
        return {"chosen": "base", "holdout": "too short to hold out"}
    r, o = cut_run(run, opts, n)
    mine = arch_discover(stocks, r, o, {**cfg, "seconds": float(cfg["seconds"]) / 2})
    e_mine = error(forecast(mine, ids, run, opts, n), ids, run, n)
    e_keep = error(persistence(ids, run, n), ids, run, n)
    if n - 1 >= SHORT:
        e_base = error(forecast(_base_on(base, stocks, r, o), ids, run, opts, n), ids, run, n)
        chosen = "archetypes" if e_mine < e_base else "base"
    else:
        e_base = None
        chosen = "archetypes" if e_mine < e_keep else "base"
    rd = lambda x: None if x is None or not math.isfinite(x) else round(x, 4)  # noqa: E731
    return {"chosen": chosen, "holdout": {"from": n, "archetypes": rd(e_mine), "base": rd(e_base), "persistence": rd(e_keep)}}
