"""A move that can never move anything is no flow (port-matrix_v2, 2026-10-22; docs/research/fixes/port-matrix_v2.md).

The engine floors every rate at 0. A move between two stocks whose rate is a constant or linear form with no positive
number (c <= 0 and every term's k <= 0), reading only levels and inputs that are never negative on the run, is 0 for
every state the run reaches and every state beyond it with those readers nonnegative: the model is the same without
it (algebraically, on the nonnegative states). The matrix's answer leaves such moves on a stock whose flows a later
pass rewrote (310 none-short: `desired -> pending = -21.97 desired` beside the controller), and the scorer counts them
as spurious flows. They are removed; a declared outside side is never touched (fill_declared keeps it by design).
Fix ledger type 17 (spurious flows must earn their place), in its simplest exact case. Self-contained.
"""

from __future__ import annotations

import numpy as np


def _never_positive(rate: dict, nonneg: set) -> bool:
    form = (rate or {}).get("form")
    if form == "proportional":
        return float(rate.get("k") or 0.0) <= 0.0 and rate.get("stock") in nonneg
    if form == "constant":
        return float(rate.get("value", rate.get("c", 0.0)) or 0.0) <= 0.0
    if form == "linear":
        return (float(rate.get("c") or 0.0) <= 0.0
                and all(float(t.get("k") or 0.0) <= 0.0 and t.get("stock") in nonneg for t in rate.get("terms") or []))
    return False


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The answer without its moves that are 0 on every nonnegative state."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    nonneg = set()
    for s in stocks:
        v = np.asarray(run["levels"].get(s["id"], []), dtype=float)
        if len(v) and np.isfinite(v).all() and float(v.min()) >= 0.0:
            nonneg.add(s["id"])
    for name, v in ((opts or {}).get("inputs") or {}).items():
        u = np.asarray(v, dtype=float)
        if len(u) and np.isfinite(u).all() and float(u.min()) >= 0.0:
            nonneg.add(name)
    keep, gone = [], []
    for f in result["flows"]:
        a, b = f.get("from"), f.get("to")
        plain = not (f.get("effects") or f.get("uses") or f.get("byTime") or f.get("inflow"))
        if a is not None and b is not None and plain and _never_positive(f.get("rate"), nonneg):
            gone.append(f"{a} -> {b}")
            continue
        keep.append(f)
    if not gone:
        return result
    out = dict(result)
    out["flows"] = keep
    out["dead_moves"] = gone
    return out
