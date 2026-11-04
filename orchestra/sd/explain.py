"""What discovery tried for every series it considered, kept in its record (``discovery["explain"]``,
by series key), so a page can show why a series is a stock or was left out without re-running
anything. It changes nothing discovery decides; it only says what was read and tried:

- **kind**: what the series was taken for (a counter, a gauge, an indicator of 0 and 1), whether
  its source's definition said so or its name and samples did, and the samples' behaviour (never
  falls, resets, value range, whole numbers, the interval it is written on, and how much of each
  reading carries over to the next: ``reads_as``, a held quantity or readings around a mean, as a
  per-interval count or a rate is);
- **read**: the exact query it was read with (its source's query, the store's selector and the
  query a view of it opens with, what a split summed over), the window and step, and what came
  back (points, span, range, a ``SPARK``-point sparkline);
- **roles**: each role it was tried in: a level to **balance** (the counters offered as its moves,
  those kept apart and why, the balance found and its R²); a level to **drive** (``sd.netflow``:
  every form tried with its inputs, R², and why it lost; the series of its own name never
  offered); a **move** (a counter: the levels whose balances it was offered to, those it is in, its
  flow); an **input** (a gauge offered to flows' rates and to other levels' net flows, and how it
  fared there);
- **verdict**: the sentence the record's ``left_out`` gives, or why it is a stock."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise

from .live import usual_interval

SPARK = 60                  # points in a series' sparkline
CARRIES = 0.7               # lag-one autocorrelation at which each reading carries the last: a held quantity
NEW_EACH = 0.3              # ... below which each reading is new: readings around a mean (a per-interval count, a rate)
MOST = 25                   # series named in a list, at most (the count says the rest)


def _r(v: float | None, digits: int = 4) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return float(f"{v:.{digits}g}")


def _autocorr(v: list[float]) -> float | None:
    if len(v) < 4:
        return None
    m = sum(v) / len(v)
    d = [x - m for x in v]
    var = sum(x * x for x in d)
    return sum(a * b for a, b in pairwise(d)) / var if var > 0 else None


def spark(points: list[tuple[float, float]], start: float, end: float, n: int = SPARK) -> list[float | None]:
    """The points' mean in each of ``n`` equal stretches of [start, end]; None where none fell."""
    width = (end - start) / n if end > start else 1.0
    sums, counts = [0.0] * n, [0] * n
    for t, v in points:
        if start <= t <= end:
            i = min(n - 1, int((t - start) / width))
            sums[i] += v
            counts[i] += 1
    return [_r(s / c) if c else None for s, c in zip(sums, counts, strict=True)]


def kind(s, declared: bool, prov: dict | None, start: float, end: float) -> dict:
    """What the series was taken for, on what word, and how its samples behave."""
    pts = [(t, v) for t, v in s.points if start <= t <= end] or list(s.points)
    vals = [v for _, v in pts]
    falls = sum(1 for a, b in pairwise(vals) if b < a)
    resets = sum(1 for a, b in pairwise(vals) if b < a and a > 0 and b <= 0.5 * a)
    ac = _autocorr(vals)
    ev = {"points": len(vals), "never_falls": falls == 0, "falls": falls, "resets": resets,
          "min": _r(min(vals)) if vals else None, "max": _r(max(vals)) if vals else None,
          "whole": bool(vals) and all(float(v).is_integer() for v in vals), "distinct": len(set(vals)),
          "interval_s": _r(usual_interval(pts)), "autocorr": _r(ac, 3)}
    as_ = "counter" if s.counter else "indicator" if vals and set(vals) <= {0.0, 1.0} else "gauge"
    if declared or prov:
        said = (prov or {}).get("kind")
        why = f"its source's definition reads it as a {said or ('counter' if s.counter else 'level')}"
    elif s.counter:
        why = "its name ends in _total and it never falls but for a reset"
    else:
        why = "not named a counter (_total), or it falls: a level"
    out = {"as": as_, "why": why, "evidence": ev}
    if as_ == "gauge" and ac is not None and ev["distinct"] > 2:
        if ac < NEW_EACH and (ev["min"] or 0) >= 0:
            out["reads_as"] = "rate"
            out["reads_why"] = (f"each reading is new, not carried from the last (lag-one autocorrelation {ac:.2f}): readings "
                                "around a mean, as a per-interval count or a rate is, not a quantity held")
        elif ac >= CARRIES:
            out["reads_as"] = "held"
            out["reads_why"] = f"each reading carries most of the last (lag-one autocorrelation {ac:.2f}), as a quantity held does"
    return out


def read(s, prov: dict | None, start: float, end: float, step: float) -> dict:
    """The query it was read with and what came back."""
    p = prov or {}
    pts = [(t, v) for t, v in s.points if start <= t <= end]
    vals = [v for _, v in pts]
    q = {"source": p.get("source") or "own", "query": p.get("query") or s.key,
         **{k: p[k] for k in ("selector", "store_query", "summed", "candidate", "view", "family", "named_as", "named_by") if p.get(k)},
         "window": [start, end], "step": step}
    if s.members:
        q["instances"] = len(s.members)
    return {**q, "points": len(pts), "first": pts[0][0] if pts else None, "last": pts[-1][0] if pts else None,
            "span_s": round(pts[-1][0] - pts[0][0], 3) if len(pts) > 1 else 0.0,
            "min": _r(min(vals)) if vals else None, "max": _r(max(vals)) if vals else None, "spark": spark(pts, start, end)}


def _few(keys) -> dict:
    keys = sorted(keys)
    return {"n": len(keys), "keys": keys[:MOST]}


def stock_verdict(st) -> str:
    """Why a stock is one, in a sentence."""
    ev = st.evidence or {}
    if ev.get("net_flow"):
        nf = ev["net_flow"]
        return (f"a stock: no counters balance it, and its net flow is fitted as {nf['form']} at R² {nf['r2']:.2f} over "
                f"{nf['stretches']} stretches, beating a constant drift and every refutation")
    if ev.get("by_construction"):
        return "a stock by construction: a count and its own turnover, as its instrument declared them"
    if ev.get("balance") and ev.get("balance_r2") is not None:
        terms = " ".join(f"{'+' if b['sign'] > 0 else '−'} {b['series']}" for b in ev["balance"])
        return (f"a stock: its changes are balanced by {terms} at R² {ev['balance_r2']:.2f} (at least {ev.get('min_r2', 0.9)} is "
                f"needed), exact in {round(100 * (ev.get('exact_steps') or 0))}% of steps")
    return "a stock: " + str(ev.get("note") or "found by its balance")


def record(series, *, left_out: dict, stocks, sid_of: dict, kinds: dict | None, provenance: dict, start: float, end: float,
           step: float, balances: dict, net: dict, input_of: dict, offered: dict, flow_of: dict, min_r2: float) -> dict:
    """Every considered series' record, by key (see the module). ``balances``: each level's balance
    attempt; ``net``: each level's net-flow trace (``sd.netflow``); ``input_of``: a gauge's input
    name; ``offered``: a path id (stock id or ``input:<name>``) -> the flows whose rate it was offered
    to, and whether chosen; ``flow_of``: a counter's flow id."""
    by_sid = {st.id: st for st in stocks}
    in_balance: dict[str, list[str]] = defaultdict(list)
    for st in stocks:
        for b in (st.evidence or {}).get("balance") or []:
            in_balance[b["series"]].append(st.id)
    offered_to_balance: dict[str, list[str]] = defaultdict(list)
    for lv, b in balances.items():
        for c in b.get("counters_all", []):
            offered_to_balance[c].append(lv)
    to_levels: dict[str, list[dict]] = defaultdict(list)
    for lv, tr in net.items():
        best: dict[str, dict] = {}
        for f in tr.get("forms") or []:
            for k in f.get("inputs") or []:
                if k not in best or (f.get("r2") or -1) > (best[k].get("r2") or -1):
                    best[k] = f
        for k, f in best.items():
            to_levels[k].append({"level": lv, "form": f["form"], "r2": f.get("r2"), "outcome": f["outcome"]})
    out = {}
    for s in series:
        key, prov = s.key, provenance.get(s.key)
        sid = sid_of.get(key)
        rec: dict = {"kind": kind(s, key in (kinds or {}), prov, start, end), "read": read(s, prov, start, end, step), "roles": {}}
        roles = rec["roles"]
        if s.counter:
            roles["move"] = {"offered_to": _few(offered_to_balance.get(key, [])), "in_balances": in_balance.get(key, []),
                             **({"flow": flow_of[key]} if key in flow_of else {})}
        else:
            if key in balances:
                b = {k: v for k, v in balances[key].items() if k != "counters_all"}
                roles["balance"] = {**b, "min_r2": min_r2}
            if key in net:
                tr = dict(net[key])
                tr["forms"] = [{"form": "c", "inputs": [], "own": False, "r2": 0.0, "outcome": "reference",
                                "why": "a constant drift: the form every other must beat"}, *(tr.get("forms") or [])]
                roles["driven"] = tr
            name = input_of.get(key)
            p = f"input:{name}" if name else (sid if sid else None)
            roles["input"] = {"name": name, "to_flows": offered.get(p, []) if p else [], "to_levels": to_levels.get(key, [])}
        if sid and sid in by_sid:
            rec["stock"] = sid
            rec["verdict"] = stock_verdict(by_sid[sid])
            rec["kept"] = True
        else:
            rec["verdict"] = left_out.get(key, "considered; not left out, and no stock is bound to it")
            rec["kept"] = False
        out[key] = rec
    return out
