"""archetypes: the classic SD structures (growth, logistic crowding, Lotka-Volterra competition and
predation, linear and Bass/SIR-type moves, constant inflows, links) fitted by their free run and
chosen by AICc, for short and noisy series (docs/research/archetypes.md).

The matrix method and everything built on it refuse a series of fewer than 20 steps. A short series
still says a lot when the candidate structures are few and classic: each candidate's numbers and
starting levels are fitted to the measured levels its free run reaches (output error: the error is
in the measurements), under three error models (constant, square-root and proportional to the
level), and the small-sample Akaike criterion picks the structure (search.py).

- Fewer than 20 steps: the search's model is the answer.
- 20 steps or more: combined runs first (unchanged, through its identify()); the search runs on a
  series of at most `max_steps` steps and `max_stocks` stocks, and its model replaces combined's only
  when it forecasts the run's last part better from the earlier part (`holdout`: both refitted
  on the first part, the search with combined's own structure too) and its free run fits the whole
  run at least as well as combined's model's free run.

opts (also SDLAB_ARCHETYPES, JSON): "seconds" (the search's cap, default 60), "powers" (error models,
default [0, 0.5, 1]), "base" ("combined"), "alone" (the search's model whatever the length),
"max_steps" (120), "max_stocks" (3).
"""

from __future__ import annotations

import json
import math
import os
import time

import numpy as np

from .fit import Data
from .hidden import search_hidden
from .holdout import cut_run, error, forecast, persistence
from .search import conserved, search
from .write import flows as to_flows
from .boundary import CLAIM_PRICE, Boundary, side_rule   # (boundary: docs/research/declared-boundary.md)

DEFAULTS = {"seconds": 60.0, "powers": [0.0, 0.5, 1.0], "base": "combined", "alone": False, "max_steps": 120, "max_stocks": 3,
            "moves": True, "hidden": True, "price": True}
SHORT = 20          # below this many steps the matrix method (and every strategy built on it) returns nothing


def injections(opts: dict, ids: list[str], t: list) -> np.ndarray:
    out = np.zeros((len(t), len(ids)))
    pos = {float(x): k for k, x in enumerate(t)}
    for j in opts.get("injections") or []:
        k = pos.get(float(j["t"]))
        if k is not None and j.get("stock") in ids:
            out[k, ids.index(j["stock"])] += float(j["amount"])
    return out


def pulses(Y: np.ndarray, drop: float = 0.2) -> list[int]:
    """The stocks whose level rises to a peak inside the run and then falls by at least `drop` of it
    (on a 3-sample running mean): what a source that runs out leaves (an epidemic's later stage). Only
    these are offered a hidden source; a level that rises and settles is explained by measured flows."""
    out = []
    for i, y in enumerate(Y):
        if len(y) < 5:
            continue
        s = np.convolve(y, np.ones(3) / 3, mode="valid")
        k = int(np.argmax(s))
        if 0 < k < len(s) - 1 and s[-1] <= (1 - drop) * s[k] and s[k] > s[0]:
            out.append(i)
    return out


def discover(stocks: list[dict], run: dict, opts: dict, cfg: dict) -> dict | None:
    ids = [s["id"] for s in stocks]
    t = list(run["t"])
    Y = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    if Y.shape[1] < 4:
        return None
    inj = injections(opts, ids, t)
    # (boundary: docs/research/declared-boundary.md): terms with an outside end only on declared sides; with none declared, each outside term is a
    # boundary claim priced CLAIM_PRICE x log T on top of AICc
    rule = side_rule(Boundary(run), ids, 0)
    allow = None if rule is None else (lambda x: rule(x.src, x.dst, x.mono))
    claim = 0.0 if Boundary(run).declared else CLAIM_PRICE * math.log(max(2, Y.shape[1] - 1))
    began = time.perf_counter()
    per = float(cfg["seconds"]) / max(1, len(cfg["powers"]))
    best, tried = None, []
    m = len(ids)
    hidden = bool(cfg["hidden"]) and 2 <= m <= cfg["max_stocks"]
    per = per / (1 + (m if hidden else 0))
    for p in cfg["powers"]:
        D = Data(Y, inj, power=float(p), allow=allow, claim=claim)
        fits = [("measured", search(D, per, moves=bool(cfg["moves"]), price=bool(cfg["price"])), None)]
        if hidden:
            for i in ([] if conserved(Y) else pulses(Y)):
                h = search_hidden(Y, inj, float(p), i, per, moves=bool(cfg["moves"]), price=bool(cfg["price"]), allow=allow, claim=claim)
                if h is not None:
                    fits.append((f"hidden source of {ids[i]}", h, i))
        for name, f, i in fits:
            names = ids + [f"{ids[i]}~h{k + 1}" for k in range(f.x0.shape[0] - m)] if i is not None else ids
            tried.append({"power": p, "seed": name, "family": f.family, "aicc": round(f.aicc, 3) if math.isfinite(f.aicc) else None,
                          "score": round(f.score, 3) if math.isfinite(f.score) else None, "terms": [x.name(names) for x in f.terms]})
            if best is None or f.score < best[0].score:
                best = (f, p, names)
    f, p, names = best
    Z = np.vstack([Y, f.X[m:]]) if f.X.shape[0] > m else Y
    out = to_flows(f.terms, f.theta, names, Z)
    r = {"flows": out, "archetypes": {"power": p, "family": f.family, "aicc": f.aicc, "score": f.score, "terms": [x.name(names) for x in f.terms],
                                      "theta": [float(v) for v in f.theta], "x0": [float(v) for v in f.x0], "tried": tried,
                                      "seconds": round(time.perf_counter() - began, 2)}}
    if len(names) > m:
        r["inferred_levels"] = {names[k]: [float(v) for v in f.X[k]] for k in range(m, len(names))}
    return r


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_ARCHETYPES") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS}
    cfg = {**DEFAULTS, **own, **env}
    T = len(run["t"]) - 1
    if cfg["alone"] or T < SHORT:
        r = discover(stocks, run, opts, cfg)
        return {**(r or {"flows": []}), "method": "archetypes"}
    from ._vendored.combined import identify as combined
    base = combined(stocks, run, opts)
    if len(stocks) > cfg["max_stocks"] or T > cfg["max_steps"] or (opts.get("eras") and len(opts["eras"]) > 1):
        return base
    mine = discover(stocks, run, opts, cfg)
    if not mine or not mine.get("flows"):
        return base
    info = {**mine["archetypes"], **choose(stocks, run, opts, cfg, combined)}
    if info["chosen"] == "archetypes":
        return {**mine, "archetypes": info, "method": "archetypes"}
    return {**base, "archetypes": info}


def choose(stocks: list[dict], run: dict, opts: dict, cfg: dict, base_identify) -> dict:
    """The holdout comparison (holdout.py): which model forecasts the run's last part better when
    both are refitted on the part before it."""
    ids = [s["id"] for s in stocks]
    N = len(run["t"])
    n = min(N - 3, int(round(0.75 * N)))
    if n < 5:
        return {"chosen": "base", "holdout": "too short to hold out"}
    r, o = cut_run(run, opts, n)
    mine = discover(stocks, r, o, {**cfg, "seconds": float(cfg["seconds"]) / 2})
    e_mine = error(forecast(mine, ids, run, opts, n), ids, run, n)
    e_keep = error(persistence(ids, run, n), ids, run, n)
    if n - 1 >= SHORT:
        e_base = error(forecast(base_identify(stocks, r, o), ids, run, opts, n), ids, run, n)
        chosen = "archetypes" if e_mine < e_base else "base"
    else:
        e_base = None
        chosen = "archetypes" if e_mine < e_keep else "base"
    rd = lambda x: None if x is None or not math.isfinite(x) else round(x, 4)  # noqa: E731
    return {"chosen": chosen, "holdout": {"from": n, "archetypes": rd(e_mine), "base": rd(e_base), "persistence": rd(e_keep)}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    from . import boundary

    # the declared boundary (boundary.py, docs/research/declared-boundary.md): the guard and the moves where one
    # is declared, each outside flow priced as a boundary claim where none is
    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)
