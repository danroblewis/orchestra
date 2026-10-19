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


def _walk(h: str, flows: list[dict], measured: set, used: set) -> tuple[list, list]:
    """From an unmeasured stock h: the further unmeasured stages h -> h2 -> ... -> hn (each a single flow
    into the next stock, which nothing else feeds) and hn's flows into measured stocks:
    ([(index, flow)] of the stages, [(index, flow)] into measured stocks)."""
    stages, cur, seen = [], h, {h}
    while True:
        out_m = [(i, f) for i, f in enumerate(flows) if f.get("from") == cur and f.get("to") in measured]
        out_u = [(i, f) for i, f in enumerate(flows) if f.get("from") == cur and f.get("to") and f.get("to") not in measured and i not in used]
        if out_m or len(out_u) != 1:
            return (stages, out_m) if out_m else ([], [])
        i, f = out_u[0]
        nxt = f["to"]
        if nxt in seen or sum(1 for g in flows if g.get("to") == nxt) != 1:
            return [], []
        stages.append((i, f))
        seen.add(nxt)
        cur = nxt


def _hidden_chains(flows: list[dict], measured: set) -> tuple[dict, set]:
    """A -> unmeasured H (-> H2 ... -> Hn) -> measured B, A measured or outside (None):
    {(A, B): {"in": [flows], "out": [flows], "via": H, "stages": [flows between H and Hn]}}, and the
    indexes of the flows they take. A path fed from outside (a supply line, a delayed input) is one
    too (the user, 2026-10-19: hidden stocks fed from outside are scored)."""
    chains, used = {}, set()
    # a compiled DELAYn (n > 1, the case format's delay3(): flows marked "delay"): A -> H1 -> ... -> Hn ->
    # measured B is one hidden path whose delay is the DELAY's time ("time")
    groups: dict = {}
    for i, f in enumerate(flows):
        if isinstance(f.get("delay"), dict) and f["delay"].get("of", 1) > 1:
            groups.setdefault(f["delay"]["id"], []).append((f["delay"]["stage"], i, f))
    for g in groups.values():
        g.sort(key=lambda x: x[0])
        a, b = g[0][2].get("from"), g[-1][2].get("to")
        if (a in measured or a is None) and b in measured:
            c = chains.setdefault((a, b), {"in": [], "out": [], "via": g[0][2]["to"], "stages": [], "time": float(g[0][2]["delay"]["time"])})
            c["in"].append(g[0][2])
            used.update(i for _, i, _ in g)
    inner = {x for f in flows for x in (f.get("from"), f.get("to")) if x and x not in measured}
    for h in sorted(inner):
        ins = [(i, f) for i, f in enumerate(flows) if f.get("to") == h and (f.get("from") in measured or not f.get("from")) and i not in used]
        if not ins:
            continue
        stages, outs = _walk(h, flows, measured, used)
        for i, f in ins:
            for o, g in outs:
                c = chains.setdefault((f.get("from") or None, g["to"]), {"in": [], "out": [], "via": h, "stages": [x for _, x in stages]})
                if f not in c["in"]:
                    c["in"].append(f)
                if g not in c["out"]:
                    c["out"].append(g)
                used.update((i, o))
                used.update(x for x, _ in stages)
    return chains, used


def _delay(c: dict, window: tuple[int, int]) -> float:
    """A hidden path's delay: the DELAY's time, else the mean time through its stages (sum of 1 / each
    stage's rate on its own stock; one stage: 1 / its outflow's rate)."""
    if "time" in c:
        return c["time"]
    total, cur = 0.0, c["via"]
    for f in c.get("stages") or []:
        k = (form_over(f, *window) or (0, {}))[1].get(cur, 0.0)
        if k <= 0:
            return math.inf
        total += 1 / k
        cur = f["to"]
    k_out = sum((form_over(g, *window) or (0, {}))[1].get(cur, 0.0) for g in c["out"])
    return total + 1 / k_out if k_out > 0 else math.inf


def _inflow_parts(out: dict, notes: list, flows: list[dict], b: str, measured: set, inputs, window: tuple[int, int]) -> None:
    """The numbers of what feeds a hidden path from outside into b: ("via", None, b, reader), and its
    effects ("viaeffect", None, b, stock)."""
    for f in flows:
        lf = form_over(f, *window)
        if lf is None:
            notes.append(f"outside -> (hidden) -> {b}: inflow form {(f.get('rate') or {}).get('form')} is not linear, not scored")
            continue
        c, ks = lf
        if c:
            out[("via", None, b, ONE)] = out.get(("via", None, b, ONE), 0.0) + c
        for j, k in ks.items():
            if j not in measured and j not in inputs:
                notes.append(f"outside -> (hidden) -> {b} reads unmeasured {j}, not scored")
                continue
            out[("via", None, b, j)] = out.get(("via", None, b, j), 0.0) + k
        for e in f.get("effects") or []:
            if e.get("stock") in measured or e.get("stock") in inputs:
                out[("viaeffect", None, b, e["stock"])] = e


def parts(flows: list[dict], measured: set, window: tuple[int, int], inputs: set | frozenset = frozenset()) -> tuple[dict, list[str]]:
    """{key: value} for the flows over a window, and notes on what could not be read. Keys are tuples:
    ("flow", from, to, reader), ("uses", from, to, stock), ("effect", from, to, stock),
    ("hidden", from, to); from / to None for outside. A hidden path fed from outside is ("hidden", None,
    to) = {"delay"} with the numbers of its inflow as ("via", None, to, reader) (and its effects as
    ("viaeffect", None, to, stock)). A reader may be a measured input (inputs: their names), read as a
    stock is."""
    out: dict[tuple, object] = {}
    notes: list[str] = []
    chains, used = _hidden_chains(flows, measured)
    for (a, b), c in chains.items():
        if a is None:                                     # fed from outside: its delay, and the numbers of what feeds it
            out[("hidden", None, b)] = {"delay": _delay(c, window)}
            _inflow_parts(out, notes, c["in"], b, measured, inputs, window)
            continue
        k_in = sum((form_over(f, *window) or (0, {}))[1].get(a, 0.0) for f in c["in"])
        out[("hidden", a, b)] = {"k_in": k_in, "delay": _delay(c, window)}
    for i, f in enumerate(flows):
        if f.get("via"):                                  # a found hidden stock, as one flow from A (or outside) to B
            delay = float(f["via"].get("delay") or math.inf)
            if not f.get("from"):
                out[("hidden", None, f.get("to"))] = {"delay": delay}
                _inflow_parts(out, notes, [f], f.get("to"), measured, inputs, window)
                continue
            lf = form_over(f, *window) or (0, {})
            out[("hidden", f.get("from"), f.get("to"))] = {"k_in": lf[1].get(f.get("from"), 0.0), "delay": delay}
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
    if key[0] in ("uses", "effect", "hidden", "via", "viaeffect"):
        return {"uses": "co-flow", "effect": "effect", "hidden": "hidden", "via": "hidden inflow", "viaeffect": "hidden inflow effect"}[key[0]]
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
        return f"{end(key[1])} -> (hidden) -> {key[2]}"
    if key[0] == "via":
        return f"outside -> (hidden) -> {key[2]} [{'const' if key[3] == ONE else key[3]}]"
    if key[0] == "viaeffect":
        return f"effect {key[3]} on outside -> (hidden) -> {key[2]}"
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
