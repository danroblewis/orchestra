"""A hidden stock on a move, fitted by gradient descent (gradfit), and how it is handed on.

A move A -> B at k x A becomes A -> h at k x A and h -> B at k2 x h, with h a stock nobody measures:
its level over the run is what its flows imply (gradfit steps it through the measured data from a
fitted starting level). The fit is tried move by move and kept where the multi-step error falls by
more than a stated share.

simulate.Model (and the grader) step only the stocks they are given, so a hidden stock is handed on
as SD Lab writes one (an `inferred` stock with the two flows) only to callers that step it;
`collapse` turns it back into the move A -> B at the rate it is fed, for those that do not.
"""

from __future__ import annotations

import copy

import numpy as np

from .diffsim import compile_flows, to_flows
from .gradfit import Fit

PREFIX = "hidden:"


def moves(flows: list[dict], ids: list[str]) -> list[int]:
    """Flows that move things between two measured stocks at a rate proportional to the source."""
    return [i for i, f in enumerate(flows) if f.get("from") in ids and f.get("to") in ids and not f.get("driver") and not f.get("byTime")
            and (f.get("rate") or {}).get("form") == "proportional" and f["rate"].get("stock") == f["from"]]


def with_hidden(flows: list[dict], i: int, ids: list[str], data, delay: float = 5.0) -> tuple[list[dict], str, float]:
    """The flows with move i routed through a new hidden stock (delay steps on average), its id, and
    a starting level (what it would hold in a steady state)."""
    f = flows[i]
    h = f"{PREFIX}{f['from']}->{f['to']}"
    k = float(f["rate"]["k"])
    out = copy.deepcopy(flows)
    out[i] = {**f, "to": h}
    out.append({"from": h, "to": f["to"], "ratio": 1, "rate": {"form": "proportional", "stock": h, "k": 1 / delay}, "via": {"hidden": h}})
    level = k * float(data.A[ids.index(f["from"])].mean()) * delay
    return out, h, level


def fit_hidden(flows: list[dict], ids: list[str], times, data, horizons=(5, 20), gain: float = 0.02, log=None) -> dict:
    """Each move tried with a hidden stock on it; returns {"flows", "hidden": [...], "error"}: the
    best, kept only if its multi-step error is at least `gain` (a share) below the model without."""
    spec = compile_flows(flows, ids, times)
    fit = Fit(spec, data)
    p = fit.run(None, horizons, log=log)
    best = {"flows": to_flows(spec, p), "hidden": [], "error": fit.error(p, horizons[-1])}
    base = best["error"]
    for i in moves(flows, ids):
        trial, h, level = with_hidden(flows, i, ids, data)
        spec_h = compile_flows(trial, ids + [h], times)
        spec_h.init["h0"] = np.array([level])
        fit_h = Fit(spec_h, data)
        ph = fit_h.run(None, horizons, log=log)
        err = fit_h.error(ph, horizons[-1])
        if log:
            log(f"  hidden on {flows[i]['from']} -> {flows[i]['to']}: error {err:.5g} (without {base:.5g})")
        if err < best["error"] and err < base * (1 - gain):
            best = {"flows": to_flows(spec_h, ph), "hidden": [{"id": h, "initial": float(np.asarray(ph["h0"])[0])}], "error": err}
    return best


def collapse(flows: list[dict]) -> list[dict]:
    """Hidden stocks removed for a simulator that does not step them: A -> h becomes A -> B, the flow
    out of h is dropped."""
    out = []
    for f in flows:
        if str(f.get("from") or "").startswith(PREFIX):
            continue
        to = f.get("to")
        if str(to or "").startswith(PREFIX):
            nxt = next((g for g in flows if g.get("from") == to), None)
            f = {**f, "to": nxt.get("to") if nxt else None}
        out.append(f)
    return out
