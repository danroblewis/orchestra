"""The matrix method, then its numbers refined by multi-step (output) error (sdlab/discovery/refine.py).

The candidates are identify()'s (sdlab/discovery/identify.py). The best `top` of them by the judge
have their flows' rates moved so the model, run forward from many moments, stays close to the
measured data over 5, 20 and 100 steps; the outside inflows stay as found (see refine.py for why).
The model kept is the one, refined or not, that the judge (the same one identify() uses) likes best.
"""

from __future__ import annotations

from ..identify import VARIANTS, judge
from ..matrix import identify_one
from ..refine import refine


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    ropts = {"profile": False, **(opts.pop("refine", None) or {})}
    top = opts.pop("top", 1)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    tried = []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v})
        tried.append((judge(r["flows"], stocks, run), v["name"], r))
    tried.sort(key=lambda x: x[0])
    if not tried:
        return {"flows": []}
    best = tried[0]
    ids = [s["id"] for s in stocks]
    notes = []
    for e, name, r in tried[:top]:
        if not r.get("flows"):
            continue
        flows, note = refine(r["flows"], ids, run["t"], run["levels"], ropts)
        if not note.get("refined"):
            continue
        e2 = judge(flows, stocks, run)
        notes.append({"name": name, "judge": (e, e2)})
        if e2 < best[0]:
            best = (e2, name + ", refined", {**r, "flows": flows})
    out = best[2]
    out["chosen"] = best[1]
    out["tried"] = [{"name": n, "error": e} for e, n, _ in tried]
    out["refine"] = notes
    return out
