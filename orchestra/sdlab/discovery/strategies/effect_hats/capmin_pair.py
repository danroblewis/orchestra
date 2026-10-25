"""The offered MIN series' terms in a base read with it in every row, paired into the one flow it limits
(docs/research/k8s-306-s1.md, "counts, MIN mis-routed"; 2026-10-21).

The base here is the pinned matrix method (sdlab/discovery/identify.py), which knows nothing of capmin.py:
it reads the offered series m = MIN(X, theta Y) in every row, as an outside outflow of X and an outside
inflow of its receiver R, plus small proxies elsewhere. Left to the declared boundary's guard, the
outflow half can be paired with any other stock's outside inflow (306 counts-long: queue -> errors_total,
the MIN lost). capmin.offer already named the limited flow (X and its receiver), so its two halves are
joined here into the move X -> R at the mean of the two coefficients (matrix_v2's rule, f640c89), and m's
terms in any other row are dropped: m may be read only in X's and R's rows (capmin.excluded). Nothing
reads the case: only what offer() found in the data.
"""

from __future__ import annotations

import copy

from .capmin import offered


def _m_term(f: dict, name: str):
    """(k, rest) when f's rate reads the series `name` as a linear term (rest: its other terms), else None."""
    r = f.get("rate") or {}
    if f.get("byTime") or f.get("inflow") or r.get("form") != "linear":
        return None
    terms = r.get("terms") or []
    hit = [t for t in terms if t.get("stock") == name]
    if not hit:
        return None
    return sum(float(t.get("k") or 0) for t in hit), [t for t in terms if t.get("stock") != name], float(r.get("c") or 0)


def _without(f: dict, name: str, rest: list[dict], c: float) -> dict | None:
    if not rest and not c:
        return None
    g = copy.deepcopy(f)
    rate = {"form": "linear", "c": c, "terms": copy.deepcopy(rest)}
    g["rate"], g["rates"] = rate, [rate]
    return g


def pair(flows: list[dict], opts: dict | None) -> list[dict]:
    """flows with each offered series' terms read as one flow out of its source (into its receiver)."""
    for name, (src, to) in offered(opts).items():
        out_k, in_k, kept = [], [], []
        for f in flows:
            got = _m_term(f, name)
            if got is None:
                kept.append(f)
                continue
            k, rest, c = got
            if f.get("from") == src and f.get("to") in (None, to):
                out_k.append(k)                                  # src loses it (to outside, or straight to R)
                if f.get("to") == to and to is not None:
                    in_k.append(k)
            elif f.get("to") == to and to is not None and f.get("from") in (None, src):
                in_k.append(k)
            g = _without(f, name, rest, c)
            if g is not None:
                kept.append(g)
        if not out_k:
            flows = kept if not in_k else flows                  # no outflow half: leave the base as it was
            continue
        a = sum(out_k) if not in_k else 0.5 * (sum(out_k) + sum(in_k))
        if a <= 0:
            continue
        rate = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": a}]}
        flows = kept + [{"from": src, "to": to, "ratio": 1, "rate": rate, "rates": [rate]}]
    return flows
