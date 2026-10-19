"""The chosen model made leaner: inflow change places and flows the data do not earn under a price
stronger than BIC's are taken out (docs/research/combined_lean.md).

Two passes, each refitting the numbers that remain (combined's refit: least squares of the one-step
changes, weighted by the model's own one-step variance with counts) and kept only when the whole
model's stricter score improves and its multi-step behaviour on the data does not get worse:

1. **Change places** (`resegment`): every outside inflow written as pieces is re-segmented on the
   change places it already has. The stock's residual with the flow's own inflow added back is
   split by dynamic programming over subsets of those places, each segment at its weighted mean,
   at a cost per change of `cp` x log T in negative log-likelihood (combined prices a change at
   log T: one place and one value; the modified BIC of Zhang and Siegmund (2007) charges about
   1.5 log T per change point, which is the default). A place the data only weakly earn goes.
2. **Flows** (`drop_flows`): backward elimination. A flow goes when taking it out (and refitting
   the rest) costs less likelihood than `fp` x 0.5 log T per number it wrote (BIC is fp = 1).

The score both passes compare is the judge's (combined/judge.py) with those prices:

    NLL + 0.5 log T x numbers + (cp - 1) log T x change places + (fp - 1) 0.5 log T x numbers
"""

from __future__ import annotations

import copy
import math
import time

import numpy as np

from ...simulate import _Segments
from ..combined import judge as J
from ..combined.params import numbers
from ..combined.refit import refit


def _sorted(segs: list[dict]) -> list[dict]:
    return sorted(segs, key=lambda g: float(g["from"]))


def change_places(flows: list[dict]) -> int:
    n = 0
    for f in flows or []:
        segs = f.get("inflow")
        if segs:
            vals = [round(float(g["value"]), 9) for g in _sorted(segs)]
            n += sum(1 for a, b in zip(vals, vals[1:]) if a != b)
    return n


def strict_score(flows: list[dict], data: J.Data, cp: float, fp: float) -> tuple[float, float]:
    """(score, nll) with the stronger prices (module docstring)."""
    nll = J.nll(flows, data)
    logT = math.log(max(2, data.T))
    k = numbers(flows, set(data.ids))
    return nll + 0.5 * fp * logT * k + (cp - 1.0) * logT * change_places(flows), nll


def _variance(flows: list[dict], data: J.Data) -> np.ndarray:
    """Per stock and step, the model's one-step variance (counts) or the stock's residual variance."""
    mu, cov = J.one_step(flows, data)
    eps = data.q ** 2 / 6.0
    if cov is not None:
        return np.einsum("tii->it", cov) + eps
    r = data.dy - mu
    v = np.maximum((r ** 2).mean(axis=1), eps)
    return np.repeat(v[:, None], data.T, axis=1)


def _segment(r: np.ndarray, w: np.ndarray, bounds: list[int], cost: float) -> list[int]:
    """The subset of the candidate boundaries (indices where a new segment starts, 0 first) that
    minimises sum over segments of 0.5 x weighted SSE about the weighted mean + cost per change."""
    m = len(bounds)
    ends = bounds[1:] + [len(r)]
    cw = np.concatenate([[0.0], np.cumsum(w)])
    cwr = np.concatenate([[0.0], np.cumsum(w * r)])
    cwr2 = np.concatenate([[0.0], np.cumsum(w * r * r)])

    def sse(a: int, b: int) -> float:                # positions a..b-1
        W = cw[b] - cw[a]
        if W <= 0:
            return 0.0
        s = cwr[b] - cwr[a]
        return float(cwr2[b] - cwr2[a] - s * s / W)
    best = [math.inf] * (m + 1)                       # best[j]: cost of positions before bounds[j] (j = m: all)
    prev = [-1] * (m + 1)
    best[0] = 0.0
    for j in range(1, m + 1):
        b = ends[j - 1]
        for i in range(j):
            c = best[i] + 0.5 * sse(bounds[i], b) + (cost if i > 0 else 0.0)
            if c < best[j]:
                best[j], prev[j] = c, i
    keep, j = [], m
    while j > 0:
        i = prev[j]
        keep.append(bounds[i])
        j = i
    return sorted(keep)


def resegment(flows: list[dict], data: J.Data, cp: float) -> list[dict] | None:
    """The flows with every pieced outside inflow re-segmented on its own change places (None when
    nothing changed)."""
    if not any(f.get("inflow") and len(f["inflow"]) > 1 for f in flows):
        return None
    var = _variance(flows, data)
    mu, _ = J.one_step(flows, data)
    logT = math.log(max(2, data.T))
    out = copy.deepcopy(flows)
    changed = False
    t = data.tt
    for f in out:
        segs = f.get("inflow")
        if not segs or len(segs) < 2 or f.get("to") not in data.ids or f.get("from"):
            continue
        s = data.ids.index(f["to"])
        segs = _sorted(segs)
        which = _Segments(segs)(t)
        own = np.array([float(segs[k]["value"]) for k in which])
        r = data.dy[s] - mu[s] + own                     # what the flow's inflow has to explain
        w = 1.0 / var[s]
        starts = [int(np.searchsorted(t, float(g["from"]), side="left")) for g in segs]
        bounds = sorted(set([0] + [b for b in starts if 0 < b < len(t)]))
        if len(bounds) < 2:
            continue
        keep = _segment(r, w, bounds, cp * logT)
        if len(keep) == len(bounds):
            continue
        changed = True
        edges = keep + [len(t)]
        new = []
        for a, b in zip(edges, edges[1:]):
            W = w[a:b].sum()
            v = float((w[a:b] * r[a:b]).sum() / W) if W > 0 else float(r[a:b].mean())
            new.append({"from": float(segs[0]["from"]) if a == 0 else float(t[a]), "to": float(t[b - 1]) if b < len(t) else float(segs[-1]["to"]),
                        "value": v})
        f["inflow"] = new
        if len(new) == 1:
            f["rate"] = {"form": "constant", "value": new[0]["value"]}
            f.pop("inflow")
        else:
            wts = np.array([max(1.0, g["to"] - g["from"] + 1) for g in new])
            f["rate"] = {"form": "constant", "value": float((wts * np.array([g["value"] for g in new])).sum() / wts.sum())}
    return out if changed else None


def _refitted(flows: list[dict], data: J.Data) -> list[dict]:
    try:
        g = refit(flows, data, J.weights(flows, data))
    except Exception:                                    # noqa: BLE001
        g = None
    if g is None:
        return flows
    return g if J.nll(g, data) < J.nll(flows, data) else flows


def drop_flows(flows: list[dict], data: J.Data, cp: float, fp: float, most: int = 40, seconds: float = 30.0) -> list[dict]:
    """Backward elimination of flows under the stricter score (each removal refitted), for at most
    `seconds` (what has been dropped by then is kept)."""
    began = time.perf_counter()
    cur = flows
    cur_s = strict_score(cur, data, cp, fp)[0]
    for _ in range(most):
        best = None
        for i in range(len(cur)):
            if time.perf_counter() - began > seconds:
                return cur
            trial = _refitted([f for j, f in enumerate(cur) if j != i], data)
            s = strict_score(trial, data, cp, fp)[0]
            if s < cur_s - 1e-9 and (best is None or s < best[0]):
                best = (s, trial)
        if best is None:
            break
        cur_s, cur = best
    return cur


def merge_inflows(flows: list[dict]) -> list[dict] | None:
    """Outside inflows into the same stock written as a plain constant and a linear rate (c + k x)
    merged into one linear flow c + k x, the way an SD model writes it (None when there are none).
    Pieced inflows, effects, co-flows, eras and floors-at-zero that could bind (a negative number)
    are left alone."""
    groups: dict = {}
    for i, f in enumerate(flows):
        r = f.get("rate") or {}
        plain = not f.get("from") and f.get("to") and not any(f.get(k) for k in ("inflow", "byTime", "effects", "uses", "via"))
        plain = plain and float(f.get("ratio") or 1) == 1 and r.get("form") in ("constant", "linear")
        if plain and r.get("form") == "constant" and float(r.get("value") or 0) <= 0:
            plain = False
        if plain and r.get("form") == "linear" and (float(r.get("c") or 0) < 0 or any(float(t.get("k") or 0) < 0 for t in r.get("terms") or [])):
            plain = False
        if plain:
            groups.setdefault(f["to"], []).append(i)
    merged, drop = [], set()
    for to, idx in groups.items():
        forms = [flows[i]["rate"]["form"] for i in idx]
        if len(idx) < 2 or "constant" not in forms or "linear" not in forms:
            continue
        c, terms = 0.0, {}
        for i in idx:
            r = flows[i]["rate"]
            if r["form"] == "constant":
                c += float(r.get("value") or 0)
            else:
                c += float(r.get("c") or 0)
                for t in r.get("terms") or []:
                    terms[t["stock"]] = terms.get(t["stock"], 0.0) + float(t.get("k") or 0)
        g = {k: v for k, v in flows[idx[0]].items() if k not in ("rate", "driver", "id", "name")}
        g["rate"] = {"form": "linear", "c": c, "terms": [{"stock": s, "k": k} for s, k in terms.items()]}
        merged.append(g)
        drop |= set(idx)
    if not merged:
        return None
    return [f for i, f in enumerate(flows) if i not in drop] + merged


def lean(flows: list[dict], data: J.Data, run: dict, cp: float = 1.5, fp: float = 1.0, slack: float = 1.1,
         flows_pass: bool = True, merge: bool = False) -> tuple[list[dict], dict]:
    """(the leaner flows, a report). Unchanged when the model reads an unmeasured stock (its numbers
    are not refitted here) or when no change is kept.

    Change places are judged by the stricter score alone: the in-data multi-step check replays the
    model's own pieces, so it always prefers more of them. Dropped flows must also keep the model's
    multi-step error on the data within `slack` of what it was."""
    report: dict = {"cp": cp, "fp": fp}
    if not flows or J.unmeasured(J.expand_via(flows), data):
        report["skipped"] = "unmeasured stocks" if flows else "no flows"
        return flows, report
    s0, _ = strict_score(flows, data, cp, fp)
    report["before"] = {"score": s0, "numbers": numbers(flows, set(data.ids)), "changes": change_places(flows), "flows": len(flows)}
    cur = flows
    seg = resegment(cur, data, cp)
    if seg is not None:
        seg = _refitted(seg, data)
        s = strict_score(seg, data, cp, fp)[0]
        report["resegment"] = {"score": s, "changes": change_places(seg), "kept": s < s0}
        if s < s0:
            cur, s0 = seg, s
    if flows_pass:
        b0 = J.behaviour(cur, data, run)
        dropped = drop_flows(cur, data, cp, fp)
        if dropped is not cur:
            s1 = strict_score(dropped, data, cp, fp)[0]
            b1 = J.behaviour(dropped, data, run)
            ok = s1 < s0 and b1 <= slack * b0 + 1e-3
            report["drop"] = {"score": s1, "behaviour": [b0, b1], "flows": len(dropped), "kept": ok}
            if ok:
                cur, s0 = dropped, s1
    if merge:
        m = merge_inflows(cur)
        if m is not None:
            nll_m, nll_c = J.nll(m, data), J.nll(cur, data)
            report["merge"] = {"kept": nll_m <= nll_c + 1e-6 * max(1.0, abs(nll_c))}
            if report["merge"]["kept"]:
                cur = m
    report["after"] = {"numbers": numbers(cur, set(data.ids)), "changes": change_places(cur), "flows": len(cur)}
    report["changed"] = cur is not flows
    return cur, report
