# Vendored for combined2 from sdlab/discovery/strategies/coflow_hats/inputs.py at commit 9d891b0 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Measured inputs (opts "inputs": {name: value per step aligned with t}) as this strategy reads them.

The matrix reads an input during a step (t[k] to t[k + 1]) as its value at t[k + 1], and so does the
simulator (the value of the step at or before the time). Every fit here takes the inputs as columns
beside the levels, and every model is stepped with them, so a flow k x input moves what the input
says (never 0) and its effect is in the model once.
"""

from __future__ import annotations

import numpy as np


def model_inputs(inputs: dict | None, ids: list[str], t: list) -> dict | None:
    """The inputs as the simulator takes them ({"t", "values"}); None without any."""
    vals = {k: list(v) for k, v in (inputs or {}).items() if k not in ids}
    return {"t": list(t), "values": vals} if vals else None


def rows(inputs: dict | None, ids: list[str], T: int) -> tuple[list[str], np.ndarray]:
    """The inputs' names and their values during each of the T steps (names x T); an input of
    another length is left out."""
    names, out = [], []
    for k, v in (inputs or {}).items():
        a = np.nan_to_num(np.asarray(v, dtype=float))[1 : T + 1]
        if k not in ids and len(a) == T:
            names.append(k)
            out.append(a)
    return names, np.array(out) if out else np.zeros((0, T))
