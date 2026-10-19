"""combined_lean: combined's model, made leaner afterwards (docs/research/combined_lean.md).

combined picks among its specialists' models by the one-step likelihood plus a BIC price, and
returns the winner as its specialist wrote it. The strict tier fails most of combined's passes for
extra parts: an inflow cut at one or two places the data barely earn (short noisy runs), or a weak
flow next to the right ones. This strategy keeps combined's choice and then (prune.py):

1. re-segments each pieced outside inflow on its own change places by dynamic programming, at
   `cp` x log T per change (1.5: the modified BIC of Zhang and Siegmund 2007; combined charges
   log T: a place and a value);
2. drops flows by backward elimination while the score with that price falls (`fp` x 0.5 log T per
   number, 1 = BIC), each removal refitted (combined's refit), and keeps the drops only if the
   model's multi-step error on the data stays within 1.1x;
3. keeps the result only if its score is lower than combined's model's under the same prices.

The pass runs only where a price on complexity means something: where the model fits the data to
their noise. With counts that the model does not fit (fitcheck.py, a copy of combined_misfit's: dispersion or
Ljung-Box whiteness above z = 5, as on every realistic model), the pieces stand in for dynamics no
candidate has, and taking them out moved the refitted drains and cost skill (on the stored
realistic results); there the model is returned unchanged. Models with unmeasured stocks are
returned unchanged too (their numbers are not refitted here).

opts (also SDLAB_COMBINED_LEAN, JSON): combined's options, plus "cp" (1.5), "fp" (1.0), "slack"
(1.1), "flows" (the flow pass, on), "gate" (skip models that do not fit counts, z; 5, 0 = off) and
"lean" (the whole pass, on).
"""

from __future__ import annotations

import json
import os

from ._vendored import combined as C
from ._vendored.combined import judge as J
from .fitcheck import goodness
from .prune import lean

DEFAULTS = {"cp": 1.5, "fp": 1.0, "slack": 1.1, "flows": True, "gate": 5.0, "lean": True}


def leaner(result: dict, stocks: list[dict], run: dict, opts: dict, cfg: dict) -> dict:
    """result with its flows made leaner (and a "lean" report)."""
    if not cfg["lean"] or not result.get("flows"):
        return result
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    if cfg["gate"]:
        starts = {h: v[0] for h, v in (result.get("inferred_levels") or {}).items() if v}
        try:
            fit = goodness(result["flows"], data, starts)
        except Exception as e:                           # noqa: BLE001
            fit = {"error": f"{type(e).__name__}: {e}"[:200]}
        if "error" in fit or any(v is not None and v > float(cfg["gate"]) for v in fit.values()):
            return {**result, "lean": {"skipped": "does not fit the counts", "fit": fit}}
    try:
        flows, report = lean(result["flows"], data, run, cp=float(cfg["cp"]), fp=float(cfg["fp"]), slack=float(cfg["slack"]),
                             flows_pass=bool(cfg["flows"]), merge=False)
    except Exception as e:                               # noqa: BLE001
        return {**result, "lean": {"error": f"{type(e).__name__}: {e}"[:300]}}
    return {**result, "flows": flows, "lean": report}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED_LEAN") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS}
    cfg = {**DEFAULTS, **own, **env}
    return leaner(C.identify(stocks, run, opts), stocks, run, opts, cfg)
