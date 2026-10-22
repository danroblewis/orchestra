"""A flow that moves next to nothing is no flow (z3robust's own, port-z3robust 2026-10-22).

The passes copied from milp insert flows and then refit them jointly with the others; a refit can shrink an
inserted flow to almost nothing beside a plain flow on the same pair that took its place (k8s-310 none-short:
a room limit on pending -> ready polished from 0.49 to 9.4e-5 x pending beside the plain 0.5 x pending move).
Such a flow costs complexity and is scored as a spurious flow. Here every move between measured stocks whose amount, over the whole
record, never reaches SHARE of the largest one-step change of the measured stocks it touches is dropped (the
fix ledger's types 1 and 17: a term too small to matter, a flow that does not earn its place). Outside flows
(a declared side stays in the model even at 0), flows on a hidden stock and flows whose amount cannot be
evaluated are left alone. The rest is not refitted: by the
rule, what is dropped is below the rows' resolution of interest.
"""

from __future__ import annotations

import numpy as np

from .hinge import _amount, _env
from .steps import Steps

SHARE = 1e-3          # of the largest one-step change of the flow's measured stocks


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None) -> tuple[list[dict], dict]:
    st = Steps(stocks, run, opts or {})
    env = _env(st)
    index = {s: i for i, s in enumerate(st.ids)}
    keep, dropped = [], []
    for f in flows:
        ends = [f.get("from"), f.get("to")]
        if any(x is None or x not in index for x in ends):             # moves between measured stocks only (an outside
            keep.append(f)                                              # side may be declared: kept even at 0)
            continue
        amt = _amount(f, st, env)
        if amt is None:
            keep.append(f)
            continue
        top = max(float(np.abs(st.dy[index[x]]).max(initial=0.0)) for x in ends)
        if top > 0 and float(np.abs(amt).max(initial=0.0)) < SHARE * top:
            dropped.append(f"{f.get('from') or 'outside'}->{f.get('to') or 'outside'}")
            continue
        keep.append(f)
    return keep, ({"dropped": dropped} if dropped else {})
