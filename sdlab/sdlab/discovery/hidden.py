"""Unmeasured stocks between two measured ones, as delayed copies of a level.

A stock H nobody measures, fed from A at k x A and drained into B at d x H, is

    H(t) = (1 - d) H(t-1) + k A(t-1),     B gains d x H(t-1) a step.

With the copy of A delayed by d, z(t) = (1 - d) z(t-1) + d A(t-1), H = (k / d) z, so B's row gains
k x z(t-1): a column the matrix can choose like any level. The copy starts at A's first level (as if
H had been settled), and the found H's level is then (k / d) x z, its own estimate, never the truth.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

DELAYS = (0.5, 0.3, 0.17, 0.1, 0.06, 0.03)


def delayed(x: np.ndarray, d: float) -> np.ndarray:
    """z aligned with x: z[0] = x[0], z[t] = (1 - d) z[t-1] + d x[t-1]."""
    x = np.asarray(x, dtype=float)
    z = np.empty_like(x)
    z[0] = x[0]
    if len(x) > 1:
        z[1:] = lfilter([d], [1.0, -(1.0 - d)], x[:-1], zi=[(1.0 - d) * x[0]])[0]
    return z


def copies(stocks: list[dict], run: dict, delays=DELAYS) -> list[dict]:
    """The candidate columns: every non-final stock's level delayed by each d, offered to the rows of
    the other stocks of its unit (and group) only."""
    out = []
    for a in stocks:
        if a.get("final"):
            continue
        x = np.nan_to_num(np.asarray(run["levels"].get(a["id"], [0] * len(run["t"])), dtype=float))
        rows = {b["id"] for b in stocks if b["id"] != a["id"] and (b.get("unit") or "") == (a.get("unit") or "")
                and (not a.get("group") or not b.get("group") or a.get("group") == b.get("group"))}
        if not rows:
            continue
        for d in delays:
            out.append({"id": f"{a['id']}~{d:g}", "source": a["id"], "delay": d, "series": delayed(x, d), "rows": rows})
    return out


def inferred_levels(flows: list[dict], extra: list[dict]) -> dict[str, list[float]]:
    """Each found unmeasured stock's estimated level over the run: scale x its copy."""
    series = {e["id"]: e["series"] for e in extra}
    out = {}
    for f in flows:
        inf = f.get("inferred")
        if inf:
            out[inf["id"]] = (inf["scale"] * series[inf["copy"]]).tolist()
    return out
