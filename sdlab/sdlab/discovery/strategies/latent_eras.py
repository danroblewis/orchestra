"""Unannounced eras found as recurring regimes in the rows' coefficients (discovery/regimes.py), then
fitted as announced eras are: the main line's candidates, plus its "numbers per era" candidates run
again with the regimes merged into the eras; the judge picks among them all.

Options (opts): "era_levels" ("allowed": any level may take a number per configuration; default
"chosen", as the main line), "coefficient_regimes" (False: a regime that changes only the constant
is kept too), "max_regimes", "min_spells", "max_processes", "share", "judge_margin" (a candidate with
regimes must beat the main line's judge error by this share: regimes add numbers, and a tie is
not evidence), "coef_within_pieces" (the coefficient test with the row's inflow pieces taken out).
"""

from __future__ import annotations

from ..identify import VARIANTS, identify as main_line, judge
from ..matrix import identify_one, known_flows
from ..regimes import eras_with, find

DEFAULTS = {"era_levels": "allowed"}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**DEFAULTS, **(opts or {})}
    base_opts = {k: v for k, v in opts.items() if k not in ("era_levels",)}
    base = main_line(stocks, run, dict(base_opts))
    base_err = min(x["error"] for x in base["tried"])
    if not base.get("matrix"):
        return base
    processes = find(stocks, run, base["matrix"], opts)
    base["regimes"] = [{"rows": p["rows"], "K": p["K"], "switches": int((p["z"][1:] != p["z"][:-1]).sum()), "gain": round(p["gain"], 1), "coef_gain": round(p["coef_gain"], 1)} for p in processes]
    if not processes:
        return base
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    best, best_err, tried = base, base_err, list(base["tried"])
    # each process of regimes on its own, and all of them together
    sets = [[p] for p in processes] + ([processes] if len(processes) > 1 and opts.get("combine", True) else [])
    for ps in sets:
        eras = eras_with(ps, opts.get("eras"), run["t"])
        tag = "+".join(",".join(p["rows"]) for p in ps)
        for v in VARIANTS:
            if not v.get("split_eras"):
                continue
            r = identify_one(stocks, run, {**opts, **v, "eras": eras})
            e = judge(r["flows"] + extra if r["flows"] else [], stocks, run)
            name = v["name"].replace("numbers per era", f"numbers per era and regime ({tag})")
            tried.append({"name": name, "error": e})
            if e < best_err and e < base_err * (1 - opts.get("judge_margin", 0.1)):
                best, best_err = {**r, "chosen": name, "regimes": base["regimes"]}, e
    best["tried"] = tried
    return best
