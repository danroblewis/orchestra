"""The matrix method with an honest price on whether a stock's outside inflow changes at all.

The experiment (docs/DISCOVERY-EXPERIMENTS.md, "change_price") tried the textbook price of a change
(2 x log n x the noise variance, the long-run variance when the residual is autocorrelated, every
change paying on its own) in each phase of the row fit. In the passes it spirals on frequent real
changes (sd-pipeline's intake), so the passes keep the matrix's price (0.5, then 1) and the honest
price is used where it does not feed back: before any piece can bias a row's levels, a stock gets
pieces only if, beside its levels alone, an outside inflow beats none or a change survives the
textbook price (the gate). SDLAB_CHANGE_PRICE (JSON, phase -> [mult, variance, each, min length],
or extra opts) overrides the configuration for ablations.
"""

from __future__ import annotations

import json
import os

from ..identify import identify as _identify
from ..pricing import scan

# per phase of the row fit: (mult, how the noise variance is estimated, every change pays on its own)
CONFIG = {
    "fine": (0.5, "diff", False),
    "pass": (1, "diff", False),
    "level": (1, "diff", False),
    "conserve": (1, "diff", False),
    "gate": (2, "long", False),
}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_CHANGE_PRICE") or "{}")
    cfg = {**CONFIG, **{k: tuple(v) if v else None for k, v in env.items() if k in CONFIG}}
    extra = {k: v for k, v in env.items() if k not in CONFIG}
    min_piece = extra.get("min_piece", opts.get("min_piece", 5))

    def scan_phase(r, phase):
        mult, how, each, *m = cfg[phase]
        return scan(r, m[0] if m else min_piece, mult, how, each)

    gate = None
    if cfg["gate"]:
        def gate(r):
            mult, how, each, *m = cfg["gate"]
            return scan(r, m[0] if m else min_piece, mult, how, each)

    return _identify(stocks, run, {**opts, "scan": scan_phase, "gate": gate, **extra})
