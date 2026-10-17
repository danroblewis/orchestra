"""Symbolic search for effects: the matrix method, plus candidate models in which a flow's rate is
multiplied by a curve of a stock's level (effects.py: a grammar of curves screened on what the rows
leave unexplained, offered to the matrix as virtual stocks, translated back into SD Lab effects).
Every candidate, with effects or without, is judged by behaviour on the data as identify() does."""

from __future__ import annotations

import json
import os

from ..effects import only_rows, screen, translate, virtual
from ..identify import VARIANTS, judge
from ..identify import identify as matrix_identify
from ..matrix import identify_one
from ..onestep import bic


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**json.loads(os.environ.get("SDLAB_SYMBOLIC_OPTS") or "{}"), **(opts or {})}   # ablations from the bench
    select = opts.get("select") or os.environ.get("SDLAB_SYMBOLIC_SELECT", "judge")
    ids = [s["id"] for s in stocks]
    keep = opts.pop("candidates", False)                  # the bench grades every candidate
    base = matrix_identify(stocks, run, {**opts, "candidates": keep})
    base_e = min((x["error"] for x in base.get("tried") or []), default=float("inf"))
    base_b = bic(base["flows"], ids, run["t"], run["levels"])
    cols = screen(stocks, run, opts)
    base["effects_tried"] = [f"{c['base'] or 1} x {c['curve'].name}({c['stock']}) {c['score']:.0f}" for c in cols]
    base["bic"] = base_b
    if not cols:
        return base
    vstocks, vrun, meta = virtual(stocks, run, cols)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    # a virtual stock may join only the rows where the screen saw it, and its base stock's row; the
    # curved stock's plain level in those rows is either left to the search or kept out (both tried)
    plains = {"both": (True, False), True: (True,), False: (False,)}[opts.get("plain", "both")]
    cands = []
    for plain in plains:
        rows = only_rows(meta, ids, plain=plain) if opts.get("restrict", True) else {}
        for v in VARIANTS:
            if v.get("split_eras") and not has_eras:
                continue
            r = identify_one(vstocks, vrun, {**opts, **v, "only_rows": rows})
            flows = translate(r["flows"], meta, stocks)
            e = judge(flows, stocks, run)
            b = bic(flows, ids, run["t"], run["levels"])
            name = f"effects{'' if plain else ' (curved level only)'}, {v['name']}"
            base["tried"].append({"name": name, "error": e, "bic": b})
            cands.append((r, e, b, name, flows))
            if keep:
                base.setdefault("candidates", []).append({"name": name, "error": e, "flows": flows})
    best = min(cands, key=lambda c: c[1])
    if select in ("never", "always"):          # for studying the choice
        take = select == "always"
    elif select == "judge":
        take = best[1] < opts.get("margin", 1.0) * base_e
    elif select == "bic":
        best = min(cands, key=lambda c: c[2])
        take = best[2] < base_b
    else:                                   # both: fewer numbers for the fit, and runs as well
        best = min(cands, key=lambda c: c[2])
        take = best[2] < base_b and best[1] < 1.25 * base_e
    if not take:
        return base
    r, e, b, name, flows = best
    out = {**r, "flows": flows, "chosen": name, "tried": base["tried"], "effects_tried": base["effects_tried"], "bic": b, "base_bic": base_b}
    if keep:
        out["candidates"] = base.get("candidates") or []
    return out
