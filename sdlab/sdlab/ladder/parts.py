"""Equations as numbers: a flow's rate as c + sum k_j x level_j (linear_form), averaged over a window
of steps (form_over: byTime segments, outside inflow pieces), cut into parts keyed by ends and
reader (parts; see score.py), the windows where the truth's equations hold still, and a model's
flows as one linear system of the measured stocks (linear_system)."""

from __future__ import annotations

import math

import numpy as np

from ..skill import truth_by_time

ONE = "1"                                         # the reader of a constant


def linear_form(rate: dict | None) -> tuple[float, dict[str, float]] | None:
    """A rate as c + sum k_j level_j (before the floor at 0); None for a form that is not linear."""
    r = rate or {}
    form = r.get("form")
    if form == "constant":
        return float(r.get("value") or 0), {}
    if form == "proportional":
        return 0.0, {r.get("stock"): float(r.get("k") or 0)}
    if form == "gap":
        t = max(1e-9, float(r.get("time") or 1))
        return float(r.get("goal") or 0) / t, {r.get("stock"): -1 / t}
    if form == "linear":
        terms: dict[str, float] = {}
        for x in r.get("terms") or []:
            terms[x.get("stock")] = terms.get(x.get("stock"), 0.0) + float(x.get("k") or 0)
        return float(r.get("c") or 0), terms
    return None


def _seg_index(segs: list[dict], t: int) -> int:
    for i, g in enumerate(segs):
        if g["from"] <= t <= g["to"]:
            return i
    return len(segs) - 1


def form_over(flow: dict, a: int, b: int) -> tuple[float, dict[str, float]] | None:
    """The flow's linear form averaged over the steps a..b (byTime segments, outside inflow pieces)."""
    segs = flow.get("inflow") or flow.get("byTime")
    if not segs:
        return linear_form(flow.get("rate"))
    count: dict[int, int] = {}
    for t in range(a, b + 1):
        i = _seg_index(segs, t)
        count[i] = count.get(i, 0) + 1
    forms = [((max(0.0, float(segs[i]["value"])), {}) if flow.get("inflow") else linear_form(segs[i]["rate"]), n) for i, n in count.items()]
    if any(lf is None for lf, _ in forms):
        return None
    if len(forms) == 1:
        return forms[0][0]
    total = sum(n for _, n in forms)
    c, ks = 0.0, {}
    for (c1, k1), n in forms:
        c += c1 * n / total
        for j, k in k1.items():
            ks[j] = ks.get(j, 0.0) + k * n / total
    return c, ks


def windows(truth_model: dict, t: list[int]) -> list[tuple[int, int]]:
    """The spans of the run where every true flow's equation holds still, over the steps the data
    sees (the first level is measured after step t[0], so the steps from t[1] on)."""
    flows, _ = truth_by_time(truth_model, t)
    first = t[1] if len(t) > 1 else t[0]
    starts = sorted({max(first, g["from"]) for f in flows for g in f["byTime"]} | {first})
    return [(s, (starts[i + 1] - 1) if i + 1 < len(starts) else t[-1]) for i, s in enumerate(starts)]


def _hidden_chains(flows: list[dict], measured: set) -> tuple[dict, set]:
    """Measured A -> unmeasured H -> measured B: {(A, B): {"in": [flows], "out": [flows], "via": H}},
    and the indexes of the flows they take."""
    chains, used = {}, set()
    # a compiled DELAYn (n > 1, the case format's delay3(): flows marked "delay"): measured A -> H1 ->
    # ... -> Hn -> measured B is one hidden path whose delay is the DELAY's time ("time")
    groups: dict = {}
    for i, f in enumerate(flows):
        if isinstance(f.get("delay"), dict) and f["delay"].get("of", 1) > 1:
            groups.setdefault(f["delay"]["id"], []).append((f["delay"]["stage"], i, f))
    for g in groups.values():
        g.sort(key=lambda x: x[0])
        a, b = g[0][2].get("from"), g[-1][2].get("to")
        if a in measured and b in measured:
            c = chains.setdefault((a, b), {"in": [], "out": [], "via": g[0][2]["to"], "time": float(g[0][2]["delay"]["time"])})
            c["in"].append(g[0][2])
            used.update(i for _, i, _ in g)
    inner = {x for f in flows for x in (f.get("from"), f.get("to")) if x and x not in measured}
    for h in inner:
        ins = [(i, f) for i, f in enumerate(flows) if f.get("to") == h and f.get("from") in measured]
        outs = [(i, f) for i, f in enumerate(flows) if f.get("from") == h and f.get("to") in measured]
        for i, f in ins:
            if i in used:                                 # (the first stage of a compiled delay)
                continue
            for o, g in outs:
                c = chains.setdefault((f["from"], g["to"]), {"in": [], "out": [], "via": h})
                c["in"].append(f)
                c["out"].append(g)
                used.update((i, o))
    return chains, used


def parts(flows: list[dict], measured: set, window: tuple[int, int], inputs: set | frozenset = frozenset()) -> tuple[dict, list[str]]:
    """{key: value} for the flows over a window, and notes on what could not be read. Keys are tuples:
    ("flow", from, to, reader), ("uses", from, to, stock), ("effect", from, to, stock),
    ("hidden", from, to); from / to None for outside. A reader may be a measured input (inputs: their
    names), read as a stock is."""
    out: dict[tuple, object] = {}
    notes: list[str] = []
    chains, used = _hidden_chains(flows, measured)
    for (a, b), c in chains.items():
        k_in = sum((form_over(f, *window) or (0, {}))[1].get(a, 0.0) for f in c["in"])
        k_out = sum((form_over(g, *window) or (0, {}))[1].get(c["via"], 0.0) for g in c["out"])
        out[("hidden", a, b)] = {"k_in": k_in, "delay": c["time"] if "time" in c else 1 / k_out if k_out > 0 else math.inf}
    for i, f in enumerate(flows):
        if f.get("via"):                                  # a found hidden stock, as one flow from A to B
            lf = form_over(f, *window) or (0, {})
            out[("hidden", f.get("from"), f.get("to"))] = {"k_in": lf[1].get(f.get("from"), 0.0), "delay": float(f["via"].get("delay") or math.inf)}
            continue
        if i in used:
            continue
        a = f.get("from") if f.get("from") in measured else None
        b = f.get("to") if f.get("to") in measured else None
        if (f.get("from") and a is None) or (f.get("to") and b is None) or (a is None and b is None):
            notes.append(f"{f.get('id') or f.get('from')}->{f.get('to')}: touches an unmeasured stock, not scored")
            continue
        lf = form_over(f, *window)
        if lf is None:
            notes.append(f"{f.get('id') or a}->{b}: rate form {(f.get('rate') or {}).get('form')} is not linear, not scored")
            continue
        c, ks = lf
        if c:
            out[("flow", a, b, ONE)] = out.get(("flow", a, b, ONE), 0.0) + c
        for j, k in ks.items():
            if j not in measured and j not in inputs:
                notes.append(f"{a}->{b} reads unmeasured {j}, not scored")
                continue
            out[("flow", a, b, j)] = out.get(("flow", a, b, j), 0.0) + k
        for u in f.get("uses") or []:
            if u.get("stock") in measured:
                out[("uses", a, b, u["stock"])] = out.get(("uses", a, b, u["stock"]), 0.0) + float(u.get("per") or 0)
        for e in f.get("effects") or []:
            if e.get("stock") in measured:
                out[("effect", a, b, e["stock"])] = e
    return out, notes


def kind(key: tuple) -> str:
    if key[0] in ("uses", "effect", "hidden"):
        return {"uses": "co-flow", "effect": "effect", "hidden": "hidden"}[key[0]]
    _, a, b, r = key
    if a and b:
        return "move"
    if b:
        return "outside inflow" if r == ONE else "link"
    return "outside outflow"


def label(key: tuple) -> str:
    end = lambda x: x or "outside"  # noqa: E731
    if key[0] == "flow":
        return f"{end(key[1])} -> {end(key[2])} [{'const' if key[3] == ONE else key[3]}]"
    if key[0] == "hidden":
        return f"{key[1]} -> (hidden) -> {key[2]}"
    return f"{key[0]} {key[3]} on {end(key[1])} -> {end(key[2])}"



def linear_system(flows: list[dict], ids: list[str], window: tuple[int, int]) -> tuple[np.ndarray, np.ndarray] | None:
    """Every measured stock's change as B @ levels + u over a window (None if a flow is not linear,
    has effects, or touches an unmeasured stock)."""
    idx = {s: i for i, s in enumerate(ids)}
    B, u = np.zeros((len(ids), len(ids))), np.zeros(len(ids))
    for f in flows:
        if f.get("effects") or f.get("via"):
            return None
        a, b = f.get("from"), f.get("to")
        if (a and a not in idx) or (b and b not in idx):
            return None
        lf = form_over(f, *window)
        if lf is None or any(j not in idx for j in lf[1]):
            return None
        c, ks = lf
        ratio = float(f.get("ratio") or 1)
        for stock, sign in ((a, -ratio), (b, 1.0)):
            if stock:
                u[idx[stock]] += sign * c
                for j, k in ks.items():
                    B[idx[stock], idx[j]] += sign * k
        for x in f.get("uses") or []:
            if x.get("stock") in idx:
                per = float(x.get("per") or 0)
                u[idx[x["stock"]]] -= per * c
                for j, k in ks.items():
                    B[idx[x["stock"]], idx[j]] -= per * k
    return B, u
