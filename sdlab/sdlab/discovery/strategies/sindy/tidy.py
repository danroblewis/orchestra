# sindy's copy of engine_forms/tidy.py at 2bca23f (rule 11: copied, never imported; port-sindy, 2026-10-22).
"""Negligible terms dropped (k8s-307, docs/research/fixes/307-engine_forms.md, 2026-10-21).

On noise-free levels every extra column lowers the residual a little, so a fit can keep a term with a
coefficient near the float floor (307 none: cpu's inflow 1.25 inflight + 20 ready - 1.1e-7 x the
offered MIN series; cpu's drain 0.5 cpu + 9.5e-8 traffic). Such a term carries nothing: its largest
contribution over the record is a tiny share of the flow's largest amount. It is dropped here, with
no refit (what it carried is below any tolerance), and a linear rate left with one term and no constant
is written as a proportional one. General: it reads only the rate, the measured levels and the inputs.
"""

from __future__ import annotations

import copy

import numpy as np

REL = 1e-4          # a term whose largest |k x series| is below REL x the flow's largest amount carries nothing


def _series(name, levels: dict, inputs: dict, n: int):
    v = levels.get(name) if name in levels else inputs.get(name)
    if v is None:
        return None
    a = np.asarray(v, dtype=float)[:n]
    return a if a.shape == (n,) and np.all(np.isfinite(a)) else None


def _rate(rate: dict, levels: dict, inputs: dict, n: int, dropped: list) -> dict:
    if not isinstance(rate, dict) or rate.get("form") != "linear":
        return rate
    terms = list(rate.get("terms") or [])
    c = float(rate.get("c") or 0.0)
    cols = [_series(t.get("stock"), levels, inputs, n) for t in terms]
    if not terms or any(x is None for x in cols):
        return rate
    parts = [float(t.get("k") or 0.0) * x for t, x in zip(terms, cols)]
    big = float(np.max(np.abs(c + sum(parts))))
    if not big > 0:
        return rate
    keep = [t for t, p in zip(terms, parts) if float(np.max(np.abs(p))) >= REL * big]
    dropped += [t.get("stock") for t, p in zip(terms, parts) if float(np.max(np.abs(p))) < REL * big]
    if abs(c) < REL * big and c:
        dropped.append("constant")
        c = 0.0
    if not keep or len(keep) == len(terms) and c == float(rate.get("c") or 0.0):
        return rate
    if len(keep) == 1 and c == 0.0:
        return {"form": "proportional", "stock": keep[0].get("stock"), "k": keep[0].get("k")}
    return {**rate, "c": c, "terms": keep}


def apply(result: dict, run: dict, opts: dict | None) -> dict:
    """The result with every linear rate's negligible terms dropped (what was dropped under "tidy")."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels = run.get("levels") or {}
    inputs = (opts or {}).get("inputs") or {}
    n = len(run.get("t") or [])
    out, log = copy.deepcopy(result), []
    for f in out["flows"]:
        dropped: list = []
        if f.get("rate"):
            f["rate"] = _rate(f["rate"], levels, inputs, n, dropped)
        for g in f.get("byTime") or []:
            if g.get("rate"):
                g["rate"] = _rate(g["rate"], levels, inputs, n, dropped)
        if f.get("rates"):
            f["rates"] = [_rate(r, levels, inputs, n, dropped) for r in f["rates"]]
        if dropped:
            log.append(f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}: {', '.join(map(str, dropped))}")
    if log:
        out["tidy"] = log
    return out
