"""Symbolic effects accepted only when inflow pieces cannot have faked them (experiment
symbolic-addition-judge, docs/research/symbolic-addition-judge.md).

The main line's model is the base. The effect search of strategy "symbolic" (effects.py: curves of a
stock's level screened on what the rows leave unexplained, fitted as virtual stocks, translated into
SD Lab effects) proposes additions; every variant is fitted with them, and a candidate is accepted
only if addition.addition_test says that, with an outside inflow neither model tailored (by default
a coarse inflow re-measured under each model's own dynamics frozen, into the stocks the base feeds),
it predicts better over 5/20/100 steps than the base by more than the judge's own noise, AND that it
also does better with its own pieces than the base with the base's (it must not need its pieces to
look good, nor look good only once pieces are taken away). Measured: the base's own pieces
("anchor") count a true effect twice and refuse every one; refit alone lets a candidate of another
variant (constant inflows) win once everyone's inflow is coarse, with disastrous long runs.

opts (or SDLAB_ANCHOR_OPTS, JSON, for the bench's ablations):
  inflow     "refit" (default): a coarse inflow re-measured for each model, dynamics frozen, into the
             stocks the base feeds; "anchor": the base's own pieces for both; "remeasure": the base's
             piece times with values re-measured under each model's dynamics; "own": each its own
             (plain symbolic's judge, with the noise margin)
  also       inflows under which the addition must also gain (more than nothing): default ["own"]
  mode       "set" (default): the screen's effects together; "each": one at a time, greedily, each
             judged against the model with the ones already accepted
  search     "all" (default): every variant with the effects; "same": the base's variant only
  pick       "test" (default): every candidate tested, the largest gain that passes; "judge": the
             main judge picks one candidate, which is tested
  z, floor   the margin: the gain must exceed z bootstrap spreads (default 2) and floor (default 0.02)
  refit_len  the shortest piece of the refitted inflow (default: a fiftieth of the run, at least 20)
  pieces     also require the addition's pieces to vary no more than the base's (default False)
"""

from __future__ import annotations

import json
import os

from ..addition import addition_test
from ..effects import only_rows, screen, translate, virtual
from ..identify import VARIANTS, judge
from ..identify import identify as matrix_identify
from ..matrix import identify_one, known_flows

DEFAULTS = {"inflow": "refit", "mode": "set", "search": "all", "pick": "test", "z": 2.0, "floor": 0.02, "pieces": False, "also": ["own"], "refit_len": None}


def _label(cols: list[dict]) -> str:
    return " + ".join(f"{c['base'] or 1} x {c['curve'].name}({c['stock']})" for c in cols)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**DEFAULTS, **json.loads(os.environ.get("SDLAB_ANCHOR_OPTS") or "{}"), **(opts or {})}
    keep = opts.pop("candidates", False)                  # the bench grades every candidate
    ids = [s["id"] for s in stocks]
    extra = known_flows(opts["known"], ids, run["t"]) if opts.get("known") else []
    fit_opts = {k: v for k, v in opts.items() if k not in DEFAULTS}
    base = matrix_identify(stocks, run, {**fit_opts, "candidates": keep})
    cols = screen(stocks, run, fit_opts)
    base["effects_tried"] = [f"{c['base'] or 1} x {c['curve'].name}({c['stock']}) {c['score']:.0f}" for c in cols]
    base["additions"] = []
    if not cols or not base["flows"]:
        return base
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    if opts["search"] == "all":
        variants = [v for v in VARIANTS if has_eras or not v.get("split_eras")]
    else:
        variants = [v for v in VARIANTS if v["name"] == base["chosen"]]

    def fit(group: list[dict]) -> list[tuple[str, list[dict], float]]:
        """Every candidate with these effects: (name, flows, main judge's error)."""
        vstocks, vrun, meta = virtual(stocks, run, group)
        out = []
        for plain in (True, False):
            rows = only_rows(meta, ids, plain=plain)
            for v in variants:
                r = identify_one(vstocks, vrun, {**fit_opts, **v, "only_rows": rows})
                flows = translate(r["flows"], meta, stocks)
                name = f"effects {_label(group)}{'' if plain else ' (curved level only)'}, {v['name']}"
                e = judge(flows + extra if flows else [], stocks, run)
                out.append((name, flows, e))
                base["tried"].append({"name": name, "error": e})
                if keep:
                    base.setdefault("candidates", []).append({"name": name, "error": e, "flows": flows})
        return out

    current, chosen, accepted = base["flows"], base["chosen"], []
    groups = [cols] if opts["mode"] == "set" else [[c] for c in cols]
    for g in groups:
        cands = [c for c in fit(accepted + g) if c[1]]
        if not cands:
            continue
        if opts["pick"] == "judge":                       # the main judge picks one; the test decides
            cands = [min(cands, key=lambda c: c[2])]
        tests = []
        for name, flows, _ in cands:                      # else each is tested; the largest gain that passes
            test = addition_test(current, flows, stocks, run, inflow=opts["inflow"], z=opts["z"], floor=opts["floor"],
                                 pieces=opts["pieces"], extra=extra, refit_len=opts["refit_len"])
            for other in opts["also"] if test["accept"] else []:
                gain = addition_test(current, flows, stocks, run, inflow=other, extra=extra, refit_len=opts["refit_len"])["gain"]
                test[f"gain {other}"] = gain
                test["accept"] = test["accept"] and gain > 0
            tests.append((test, name, flows))
        test, name, flows = max(tests, key=lambda x: (x[0]["accept"], x[0]["gain"]))
        base["additions"].append({"effects": _label(g), "candidate": name, **test})
        if test["accept"]:
            current, chosen, accepted = flows, name, accepted + g
    if not accepted:
        return base
    return {**base, "flows": current, "chosen": chosen}
