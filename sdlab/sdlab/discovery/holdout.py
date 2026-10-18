"""Judging a way of estimating the model on data it was not fitted on (blocked cross-validation).

The run's steps are cut into contiguous blocks. For each block, the model is fitted on every other
step (identify_one with `steps`), then run forward from moments inside the held-out block and
compared with what was measured there. The held-out block's outside inflows come only from what the
fit knows: the piece in force before the block (or, `fill="mean"`, the time-weighted mean of the
fitted pieces), never from the block's own data.
"""

from __future__ import annotations

import numpy as np

from .matrix import identify_one
from .simulate import behaviour_error


def fill_gaps(flows: list[dict], fill: str = "last") -> list[dict]:
    """Outside inflows whose pieces cover every time: a time between two pieces (a held-out block)
    takes the piece before it ("last") or the pieces' mean ("mean"); before the first piece, the
    first."""
    out = []
    for f in flows:
        segs = sorted(f.get("inflow") or [], key=lambda g: g["from"])
        if not segs:
            out.append(f)
            continue
        if fill == "mean":
            w = [g["to"] - g["from"] + 1 for g in segs]
            mean = sum(g["value"] * k for g, k in zip(segs, w)) / max(1, sum(w))
            gaps = [{"from": a["to"] + 1, "to": b["from"] - 1, "value": mean} for a, b in zip(segs, segs[1:]) if b["from"] > a["to"] + 1]
            segs = [{**g} for g in segs] + gaps
            segs.sort(key=lambda g: g["from"])
        else:
            segs = [{**g, "to": (segs[i + 1]["from"] - 1 if i + 1 < len(segs) else g["to"])} for i, g in enumerate(segs)]
        segs[0] = {**segs[0], "from": -1e18}
        segs[-1] = {**segs[-1], "to": 1e18}
        out.append({**f, "inflow": segs})
    return out


def blocks(T: int, folds: int) -> list[tuple[int, int]]:
    """`folds` contiguous blocks of the steps 0..T-1."""
    edges = np.linspace(0, T, folds + 1).astype(int)
    return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]) if b > a]


def held_out_errors(stocks: list[dict], run: dict, opts: dict, folds: int = 5, horizons=(5, 20, 100), fill: str = "last") -> list[dict]:
    """Per held-out block: {"block": (a, b), "errors": {horizon: error}} (behaviour_error, run on
    the block's own levels; a horizon is used only when it is under half the block)."""
    t = run["t"]
    T = len(t) - 1
    ids = [s["id"] for s in stocks]
    out = []
    for a, b in blocks(T, folds):
        mask = np.ones(T, bool)
        mask[a:b] = False
        r = identify_one(stocks, run, {**opts, "steps": mask})
        flows = fill_gaps(r["flows"], fill)
        tb = t[a:b + 1]
        lb = {i: list(run["levels"][i][a:b + 1]) for i in run["levels"]}
        errs = {h: behaviour_error(flows, ids, tb, lb, horizon=h) if flows else float("inf") for h in horizons if h < (b - a) / 2}
        out.append({"block": (a, b), "errors": errs})
    return out
