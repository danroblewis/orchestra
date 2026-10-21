"""combined_misfit: combined's candidates and judge, with one change: when even the model the judge
picks does not fit the measured changes to their noise, the pick is made by multi-step error
instead (docs/research/combined_misfit.md).

combined picks by the one-step likelihood plus a BIC price. That is the efficient choice when one
candidate is right: on the ladder's tests the winner's standardized residuals are what its counting
noise says they should be. On realistic models no candidate is right, and the one-step likelihood
then rewards what is wrong in a way that does not show one step ahead (inflows absorbed by
self-reinforcing terms, a hidden stock replaced by links): those models run away over 20 steps.
Selecting by simulation (multi-step) error is the system-identification answer for misspecified
model classes (Piroddi and Spinelli 2003; Farina and Piroddi 2011; Ribeiro and Aguirre 2018).

The switch: with counts, the BIC winner's residuals are tested (fitcheck.py: dispersion and
Ljung-Box whiteness, each as a z-score). If either is above `z` (5), the candidate with the lowest
multi-step error on the data (combined's behaviour measure: runs from many moments over 5, 20 and
100 steps) among those combined's runaway guard keeps is chosen; ties go to the lower BIC. Otherwise
combined's choice stands. Noise-free data are never switched (their residuals are rounding).

opts (also SDLAB_COMBINED_MISFIT, JSON): combined's options, plus "z" (default 5) and "switch"
(default on).
"""

from __future__ import annotations

import json
import os

from ._vendored import combined as C
from ._vendored.combined import judge as J
from .fitcheck import goodness

DEFAULTS = {"z": 5.0, "switch": True}


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED_MISFIT") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in C.DEFAULTS or k in DEFAULTS or k == "specialists"}
    cfg = {**C.DEFAULTS, **DEFAULTS, **own, **env}
    names = list(cfg.get("specialists") or C.SPECIALISTS)
    cands = C.candidates(stocks, run, opts, names, cfg)
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    best = C.choose(cands, data, run, cfg)
    if best is None:
        return {"flows": [], "combined": {"chosen": None, "candidates": C._summary(cands, cfg)}}
    how = {"bic_choice": best["name"]}
    if cfg["switch"] and data.counts:
        r = best["result"]
        starts = {h: v[0] for h, v in (r.get("inferred_levels") or {}).items() if v}
        try:
            fit = goodness(r["flows"], data, starts)
        except Exception as e:                           # noqa: BLE001
            fit = {"error": f"{type(e).__name__}: {e}"[:200]}
        how["fit"] = fit
        z = float(cfg["z"])
        if any(v is not None and v > z for k, v in fit.items() if k in ("dispersion", "whiteness")):
            pool = [c for c in cands if "score" in c and not c["score"].get("ran_away")
                    and c["score"].get("behaviour") is not None and c["score"]["behaviour"] < float("inf")]
            if pool:
                best = min(pool, key=lambda c: (round(c["score"]["behaviour"], 9), c["score"]["bic"]))
                how["switched"] = True
    out = dict(best["result"])
    out["combined"] = {"chosen": best["name"], "misfit": how, "candidates": C._summary(cands, cfg)}
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    from . import boundary

    # the declared boundary (boundary.py, docs/research/declared-boundary.md): the guard and the moves where one
    # is declared, each outside flow priced as a boundary claim where none is
    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)
