"""combined_r2: combined_misfit's choice (multi-step error picks when even the BIC winner does not
fit the counts to their noise), then combined_lean's leaner pass (inflow change places at a
modified-BIC price, weak flows dropped). The two ideas proposed for combined's round 2, composed
(docs/research/ideas-2026-10-18.md). It carries its own copies of both (misfit.py, lean.py,
prune.py, fitcheck.py) and of combined (_vendored/), per CLAUDE.md invariant 11.

opts: combined_misfit's and combined_lean's options (SDLAB_COMBINED_MISFIT, SDLAB_COMBINED_LEAN).
"""

from __future__ import annotations

import json
import os

from .lean import DEFAULTS as LEAN
from .lean import leaner
from .misfit import identify as misfit


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED_LEAN") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in LEAN}
    cfg = {**LEAN, **own, **env}
    return leaner(misfit(stocks, run, opts), stocks, run, opts, cfg)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
