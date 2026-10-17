"""Random ground-truth SD models, built from motifs, for a benchmark discovery cannot be tuned to.

    uv run python tests/bench/generator.py dev 7               the path to dev model 7 (built once, then cached)
    uv run python tests/bench/generator.py dev 0-19 --show     their motifs, sizes and how many draws each took
    uv run python tests/bench/generator.py dev 0-9 --features coflow,eras    models that have these motifs

A model is a spine (an outside inflow through a run of stocks and out) with motifs added to it, each
a family of structure the 31 hand-made examples also have: chains, branches, merges, rework loops, a
reinforcing loop with a balancing limit, goal-seeking (gap) flows, hidden stocks (delays of order
1-3), links between units, co-flows, effects (linear and table, several curve shapes), floors that
bind, caps (a stock that runs empty), outside inflows with unannounced changes (steps, spikes,
seasons) and announced eras. Sizes are 3-15 measured stocks.

Parameters are drawn, then the model is checked as the examples are (tests/test_sd_examples.py):
valid, bounded and never negative over fifty times its default length, still exercising its model
late in that run, every flow still moving, every measured stock away from zero, and a motif that
promises a floor or a cap actually binding. A model that fails is drawn again (the same motif plan
first, then a new plan). Everything is deterministic from (VERSION, pool, index, required features):
the model's id says which, and the model carries its motif list in "generated".

Pools (the playbook's I2): "dev" for development, any index; "sealed" (SEALED_SIZE fixed indices,
other seeds) is scored only when a change is adopted. The sealed pool alone has the held-out family
(HELD_OUT_FAMILIES) and the held-out motif combinations (HELD_OUT_COMBOS): a dev model never has
them, half the sealed models are built around one.

The truth is handed unchanged to the ground-truth engine (sdlab/sdtruth.py), as tests/synth.py does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

from sdlab.sdtruth import Truth

VERSION = 1
MAIN = "items"
STRUCTURE = ("branch", "merge", "rework", "reinforcing", "goal_gap", "hidden_delay", "link", "coflow",
             "effect_linear", "effect_table", "floor", "cap", "eras")
INPUTS = ("inflow_steps", "inflow_spikes", "inflow_season")
HELD_OUT_FAMILIES = ("effect_peaked",)
HELD_OUT_COMBOS = (frozenset({"hidden_delay", "coflow"}), frozenset({"reinforcing", "eras"}))
FAMILIES = ("chain", *STRUCTURE, *HELD_OUT_FAMILIES, *INPUTS)
POOLS = ("dev", "sealed")
SEALED_SIZE = 300
PLANS, DRAWS = 6, 25                      # motif plans per model, parameter draws per plan
SOURCE = Path(__file__).resolve()


def held_out(families) -> list[str]:
    """What in this motif set the development pool may never contain."""
    fams = set(families)
    return [f for f in HELD_OUT_FAMILIES if f in fams] + ["+".join(sorted(c)) for c in HELD_OUT_COMBOS if c <= fams]


def model_id(pool: str, index: int, require=()) -> str:
    return f"gen{VERSION}-{pool}-{index:05d}" + (f"-{'+'.join(sorted(require))}" if require else "")


# ---- the plan: which motifs, how big ----

def plan(pool: str, index: int, require=(), attempt: int = 0) -> dict:
    if pool not in POOLS:
        raise ValueError(f"pool is one of {POOLS}")
    if pool == "dev" and held_out(require):
        raise ValueError(f"held out of the development pool: {', '.join(held_out(require))}")
    if pool == "sealed" and not 0 <= index < SEALED_SIZE:
        raise ValueError(f"the sealed pool has {SEALED_SIZE} models")
    rng = random.Random(f"sdlab-generator/{VERSION}/{pool}/{'+'.join(sorted(require))}/{index}/plan{attempt}")
    candidates = STRUCTURE + (HELD_OUT_FAMILIES if pool == "sealed" else ())
    while True:
        size = rng.randint(3, 15)
        fams = set(rng.sample(candidates, rng.randint(1, min(5, 1 + size // 2))))
        fams |= set(rng.sample(INPUTS, rng.choice((1, 1, 2))))
        fams |= set(require)
        if pool == "sealed" and index % 2 == 0 and not require:    # half the sealed pool is built around a held-out item
            items = [{f} for f in HELD_OUT_FAMILIES] + [set(c) for c in HELD_OUT_COMBOS]
            fams |= items[(index // 2) % len(items)]
        if pool == "dev" and held_out(fams):
            continue
        return {"size": size, "families": sorted(fams), "spine": rng.randint(2, 4)}


# ---- building a model ----

def U(rng, a, b):
    return rng.uniform(a, b)


def const(v):
    return {"form": "constant", "value": round(max(0.0, v), 3)}


def prop(s, k):
    return {"form": "proportional", "stock": s, "k": round(k, 5)}


def linear(c, terms):
    return {"form": "linear", "c": round(c, 4), "terms": [{"stock": s, "k": round(k, 6)} for s, k in terms]}


def gap(s, goal, t):
    return {"form": "gap", "stock": s, "goal": round(goal, 2), "time": round(t, 2)}


class Build:
    """A model under construction. Ids are placeholders (@s3@, @f7@) renamed at the end; `later` holds
    the parameters that depend on typical levels, set after a first run without them."""

    def __init__(self, rng: random.Random, period: int):
        self.rng, self.P = rng, period
        self.stocks: dict[str, dict] = {}
        self.flows: list[dict] = []
        self.sched: list[tuple] = []       # (t, flow id, rate, announced)
        self.later: list = []              # fn(levels, amounts)
        self.refit: list = []              # the same, set again once the others are in (flow amounts)
        self.binds: list[tuple] = []       # ("floor", flow id) / ("empty", stock id)
        self.inputs: list[str] = []        # outside constant inflows: they get the unannounced changes
        self.demands: list[str] = []       # constant outflows whose demand changes unannounced
        self.motifs: set[str] = set()
        self.details: dict = {}
        self.spine: list[str] = []
        self.end: dict | None = None

    # parts
    def stock(self, unit=MAIN, measured=True, level=50.0) -> str:
        sid = f"@s{len(self.stocks)}@"
        self.stocks[sid] = {"id": sid, "unit": unit, "initial": level, **({} if measured else {"measured": False})}
        return sid

    def flow(self, a, b, rate, **more) -> dict:
        f = {"id": f"@f{len(self.flows)}@", "from": a, "to": b, "rate": rate, "machine": "environment", **more}
        self.flows.append(f)
        return f

    def source(self, to, value) -> dict:
        f = self.flow(None, to, const(value))
        self.inputs.append(f["id"])
        return f

    def drain(self, a, k) -> dict:
        return self.flow(a, None, prop(a, k))

    def measured(self, unit=MAIN) -> list[str]:
        return [s for s, d in self.stocks.items() if d.get("measured", True) and (unit is None or d["unit"] == unit)]

    def n_measured(self) -> int:
        return len(self.measured(None))

    def moves(self) -> list[dict]:
        m = set(self.measured())
        return [f for f in self.flows if f["from"] in m and f["to"] in m and f["rate"]["form"] == "proportional"]

    def pick(self, items):
        return self.rng.choice(list(items))


def spine(b: Build, length: int) -> None:
    r = b.rng
    s = b.stock()
    b.source(s, U(r, 5, 40))
    b.spine = [s]
    for _ in range(length - 1):
        n = b.stock()
        b.flow(s, n, prop(s, U(r, 0.05, 0.4)))
        s = n
        b.spine.append(n)
    b.end = b.drain(s, U(r, 0.05, 0.4))
    for x in b.spine:
        if r.random() < 0.25:
            b.drain(x, U(r, 0.01, 0.05))


def lengthen(b: Build) -> None:
    """One more stock at the end of the spine (padding to the planned size)."""
    n = b.stock()
    b.end["to"] = n
    b.end = b.drain(n, U(b.rng, 0.05, 0.4))
    b.spine.append(n)


def m_branch(b):
    r = b.rng
    a = b.pick(b.measured())
    n = b.stock()
    b.flow(a, n, prop(a, U(r, 0.03, 0.2)))
    b.drain(n, U(r, 0.05, 0.3))
    b.motifs.add("branch")


def m_merge(b):
    r = b.rng
    a = b.pick(b.measured())
    n = b.stock()
    b.source(n, U(r, 3, 20))
    b.flow(n, a, prop(n, U(r, 0.05, 0.3)))
    b.motifs.add("merge")


def m_rework(b):
    if not b.moves():
        m_branch(b)
    f = b.pick(b.moves())
    b.flow(f["to"], f["from"], prop(f["to"], U(b.rng, 0.02, 0.12)))
    b.motifs.add("rework")


def m_reinforcing(b):
    """Growth in proportion to itself, limited by its own level: a falling table on births, or
    crowding (a linear effect) on deaths. Births may change with the season, unannounced."""
    r = b.rng
    K = U(r, 200, 2000)
    g = b.stock("members", level=K * 0.6)
    rate = U(r, 0.03, 0.12)
    if r.random() < 0.5:
        births = b.flow(None, g, prop(g, rate), effects=[{"stock": g, "shape": "table", "points": [[0, 1], [round(K / 2), round(U(r, 0.55, 0.8), 3)], [round(K), 0]]}])
        b.drain(g, rate * U(r, 0.2, 0.6))
        b.details["reinforcing"] = "limit on births (table)"
    else:
        births = b.flow(None, g, prop(g, rate))
        d = rate * U(r, 0.6, 0.9)
        b.drain(g, d)["effects"] = [{"stock": g, "shape": "linear", "normal": round(K * d / rate, 1), "max": 10}]
        b.details["reinforcing"] = "crowding on deaths (linear effect)"
    if r.random() < 0.5:
        m, a, phase = r.randint(4, 8), U(r, 0.2, 0.5), U(r, 0, 2 * math.pi)
        for j in range(m):
            b.sched.append((1 + j * b.P // m, births["id"], prop(g, rate * (1 + a * math.sin(2 * math.pi * j / m + phase))), False))
    b.motifs.add("reinforcing")


def m_goal_gap(b):
    r = b.rng
    if r.random() < 0.5:
        # replenishment: an existing stock topped up towards a goal (nothing while it is above it)
        a = b.pick(b.measured())
        f = b.flow(None, a, gap(a, 0, U(r, 2, 12)))
        mult = U(r, 1.0, 1.5)
        b.later.append(lambda lv, amt: f["rate"].update(goal=round(lv[a] * mult, 2)))
        b.details["goal_gap"] = "replenish towards a goal"
    else:
        # a supply line: orders fall as stock on hand and on order rise; demand drains what is on hand
        p, w = b.stock(), b.stock()
        D, k, ka = U(r, 5, 30), U(r, 0.1, 0.4), U(r, 0.1, 0.4)
        kb, target = U(r, 0.02, ka), D * U(r, 3, 10)
        b.flow(None, p, linear(D + ka * target + kb * D / k, [(w, -ka), (p, -kb)]))
        b.flow(p, w, prop(p, k))
        b.demands.append(b.flow(w, None, const(D))["id"])
        b.details["goal_gap"] = "supply line"
    b.motifs.add("goal_gap")


def m_hidden(b):
    r = b.rng
    order, delay = r.randint(1, 3), U(r, 3, 20)
    moves = b.moves()
    hs = [b.stock(measured=False) for _ in range(order)]
    if moves and r.random() < 0.7:
        f = b.pick(moves)
        z = f["to"]
        f["to"] = hs[0]
    else:
        a = b.pick(b.measured())
        z = b.stock()
        b.drain(z, U(r, 0.05, 0.3))
        b.flow(a, hs[0], prop(a, U(r, 0.03, 0.2)))
    for h, nxt in zip(hs, hs[1:] + [z]):
        b.flow(h, nxt, prop(h, order / delay))
    b.details["hidden_delay"] = {"order": order, "delay": round(delay, 2)}
    b.motifs.add("hidden_delay")


def driver(b, unit, inflow=(5, 30), out=(0.05, 0.3)) -> str:
    """A stock of another unit for a link or an effect: an existing one, or a new one with its own
    outside inflow (which gets unannounced changes) and drain."""
    others = [s for s in b.measured(None) if b.stocks[s]["unit"] != MAIN]
    if others and b.rng.random() < 0.5:
        return b.pick(others)
    d = b.stock(unit)
    b.source(d, U(b.rng, *inflow))
    b.drain(d, U(b.rng, *out))
    return d


def m_link(b):
    r = b.rng
    d = driver(b, "signals")
    z = b.pick(b.measured())
    f = b.flow(None, z, linear(U(r, 0, 3), [(d, 0)]))
    gain = U(r, 2, 15)
    b.later.append(lambda lv, amt: f["rate"]["terms"][0].update(k=round(gain / max(1.0, lv[d]), 6)))
    b.motifs.add("link")


def m_coflow(b):
    r = b.rng
    res = b.stock("credits")
    if r.random() < 0.5:
        grant = b.source(res, U(r, 5, 40))
        supply, frac = grant["rate"]["value"], U(r, 0.4, 1.1)
    else:
        goal, t = U(r, 100, 800), U(r, 3, 15)
        b.flow(None, res, gap(res, goal, t))
        supply, frac = goal / t, U(r, 0.3, 0.9)
    b.drain(res, U(r, 0.01, 0.05))
    m = set(b.measured())
    f = b.pick([f for f in b.flows if f["from"] in m and f["rate"]["form"] == "proportional" and not f.get("uses")])
    b.refit.append(lambda lv, amt: f.update(uses=[{"stock": res, "per": round(frac * supply / max(0.1, amt[f["id"]]), 5)}]))
    b.motifs.add("coflow")


def table(shape: str, m: float, r: random.Random) -> list:
    xs = [0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3]
    if shape == "rising":                                     # saturating
        lo, sharp = U(r, 0.1, 0.5), U(r, 1.5, 4)
        ys = [lo + (1 - lo) * (1 - math.exp(-sharp * x)) / (1 - math.exp(-sharp * 3)) for x in xs]
    elif shape == "falling":
        lo, p = U(r, 0.1, 0.5), U(r, 0.7, 2)
        ys = [1 - (1 - lo) * min(1.0, x / 2) ** p for x in xs]
    elif shape == "s-curve":
        lo, hi, w = U(r, 0.1, 0.4), U(r, 1, 1.6), U(r, 0.15, 0.35)
        ys = [lo + (hi - lo) / (1 + math.exp(-(x - 1) / w)) for x in xs]
    else:                                                     # peaked (held out of development)
        lo, w = U(r, 0.1, 0.5), U(r, 0.35, 0.7)
        ys = [lo + (1 - lo) * math.exp(-(((x - 1) / w) ** 2)) for x in xs]
    return [[round(x * m, 2), round(y, 4)] for x, y in zip(xs, ys)]


def m_effect(b, family: str):
    r = b.rng
    m = set(b.measured(None))
    flows = [f for f in b.flows if (f["from"] in m or f["to"] in m) and f["rate"]["form"] == "proportional" and not f.get("effects")]
    f = b.pick(flows)
    e = driver(b, "staff", inflow=(2, 10), out=(0.02, 0.1)) if r.random() < 0.6 else b.pick(b.measured(None))
    shape = "peaked" if family == "effect_peaked" else r.choice(("rising", "falling", "s-curve"))
    norm, top, low = U(r, 0.8, 1.5), r.choice((1, 1.5, 2, 3)), r.choice((None, 0.2))
    seed = r.random()

    def put(lv, amt):
        level = max(1.0, lv[e])
        if family == "effect_linear":
            eff = {"stock": e, "shape": "linear", "normal": round(level * norm, 2), "max": top, **({"min": low} if low is not None else {})}
        else:
            eff = {"stock": e, "shape": "table", "points": table(shape, level, random.Random(seed))}
        f["effects"] = [eff]
    b.later.append(put)
    b.details.setdefault("effects", []).append("linear" if family == "effect_linear" else shape)
    b.motifs.add(family)


def m_floor(b):
    """A flow whose equation goes below zero part of the time (the engine floors it at 0)."""
    r = b.rng
    a = b.pick(b.measured())
    k, th = U(r, 0.1, 0.5), U(r, 0.6, 1.1)
    if r.random() < 0.5:
        # an overflow: drains only what is above a threshold
        others = [s for s in b.measured() if s != a]
        f = b.flow(a, b.pick(others) if others and r.random() < 0.3 else None, linear(0, [(a, 0)]))
        b.later.append(lambda lv, amt: f.update(rate=linear(-k * th * lv[a], [(a, k)])))
        b.details["floor"] = "overflow"
    else:
        # an inflow that stops when another stock is high
        d = b.pick([s for s in b.measured(None) if s != a] or [a])
        f = b.flow(None, a, linear(0, [(d, 0)]))
        gain, th = U(r, 2, 15), U(r, 0.9, 1.4)
        b.later.append(lambda lv, amt: f.update(rate=linear(gain * th, [(d, -gain / max(1.0, lv[d]))])))
        b.details["floor"] = "inflow that stops"
    b.binds.append(("floor", f["id"]))
    b.motifs.add("floor")


def m_cap(b):
    """A stock drained by a steady demand close to what reaches it on average (and a little in
    proportion to what it holds): it runs empty whenever its supply dips."""
    r = b.rng
    a = b.pick(b.measured())
    c = b.stock()
    feed = b.flow(a, c, prop(a, U(r, 0.05, 0.3)))
    out = b.flow(c, None, const(0))
    b.drain(c, U(r, 0.01, 0.06))
    share = U(r, 0.85, 1.05)
    b.refit.append(lambda lv, amt: out.update(rate=const(amt[feed["id"]] * share)))
    b.binds.append(("empty", c))
    b.motifs.add("cap")


def m_eras(b):
    """Announced changes to internal flows' rates."""
    r = b.rng
    m = set(b.measured())
    cands = [f for f in b.flows if f["from"] in m and f["rate"]["form"] == "proportional" and not any(s[1] == f["id"] for s in b.sched)]
    if not cands:
        return
    picked = r.sample(cands, min(len(cands), r.choice((1, 1, 2))))
    times = spaced(r, b.P, r.randint(1, 3), max(10, b.P // 8))
    for f in picked:
        b.sched.append((1, f["id"], dict(f["rate"]), True))
    for t in times:
        f = r.choice(picked)
        b.sched.append((t, f["id"], {**f["rate"], "k": round(f["rate"]["k"] * U(r, 0.4, 2.2), 5)}, True))
    b.details["eras"] = len(times)
    b.motifs.add("eras")


def spaced(r: random.Random, P: int, n: int, gap: int) -> list[int]:
    """n step times in a period of P, each level holding at least `gap` steps (a level held for a
    step or two is a spike, which is its own family)."""
    n = max(1, min(n, P // gap - 1))
    while True:
        ts = sorted(r.sample(range(1 + gap, P + 2 - gap), n))
        if all(b - a >= gap for a, b in zip(ts, ts[1:])):
            return ts


def inputs(b, kinds: list[str]) -> None:
    """Unannounced changes to every outside constant inflow (each drawn kind used at least once when
    there are enough inflows); demands change in steps."""
    r = b.rng
    flows = {f["id"]: f for f in b.flows}
    ids = list(b.inputs)
    r.shuffle(ids)
    P = b.P
    for i, fid in enumerate(ids + b.demands):
        kind = kinds[i % len(kinds)] if i < len(ids) else "inflow_steps"
        v = flows[fid]["rate"]["value"]
        if kind != "inflow_season":
            b.sched.append((1, fid, const(v), False))
        if kind == "inflow_steps":
            for t in spaced(r, P, r.randint(2, 5), max(10, P // 8)):
                b.sched.append((t, fid, const(v * U(r, 0.4, 1.8)), False))
        elif kind == "inflow_spikes":
            n = r.randint(1, 3)
            slot = (P - 4) // n
            for j in range(n):
                t, d = 2 + j * slot + r.randrange(max(1, slot - 4)), r.randint(1, 3)
                b.sched.append((t, fid, const(v * U(r, 3, 8)), False))
                b.sched.append((t + d, fid, const(v), False))
        else:
            m, a, phase = r.randint(6, 12), U(r, 0.3, 0.7), U(r, 0, 2 * math.pi)
            for j in range(m):
                b.sched.append((1 + j * P // m, fid, const(v * (1 + a * math.sin(2 * math.pi * j / m + phase))), False))
        if i < len(ids):
            b.motifs.add(kind)


MOTIFS = {"branch": m_branch, "merge": m_merge, "rework": m_rework, "reinforcing": m_reinforcing, "goal_gap": m_goal_gap,
          "hidden_delay": m_hidden, "link": m_link, "coflow": m_coflow, "floor": m_floor, "cap": m_cap,
          "effect_linear": lambda b: m_effect(b, "effect_linear"), "effect_table": lambda b: m_effect(b, "effect_table"),
          "effect_peaked": lambda b: m_effect(b, "effect_peaked")}


def schedule(b: Build) -> dict:
    entries: dict[tuple, dict] = {}
    for t, fid, rate, announce in sorted(b.sched, key=lambda s: (s[0], not s[3])):
        e = entries.setdefault((t, announce), {"t": t, "label": "", "set": {}, **({"announce": True} if announce else {})})
        e["set"][fid] = rate
    eras = 1
    for e in entries.values():
        if e.get("announce") and e["t"] > 1:
            eras += 1
        e["label"] = (f"Era {eras}" if e["t"] > 1 else "Era 1") if e.get("announce") else "change"
    return {"every": b.P, "changes": list(entries.values())}


def truth(model: dict) -> Truth:
    """The ground-truth engine on a model dict (it reads a file)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "truth.model.json"
        p.write_text(json.dumps(model))
        return Truth(p)


def means(model: dict, steps: int) -> tuple[dict, dict, dict] | None:
    """A run without noise: mean levels and flow amounts over its second half, and the last levels."""
    r = truth({**model, "noise": {}}).run(steps=steps)
    half = steps // 2
    lv = {s: statistics.fmean(v[half:]) for s, v in r["levels"].items()}
    amt = {f: statistics.fmean(v[half:]) for f, v in r["counters"].items()}
    last = {s: v[-1] for s, v in r["levels"].items()}
    if not all(math.isfinite(x) and 0 <= x < 1e7 for x in [*lv.values(), *last.values()]):
        return None
    return lv, amt, last


def build(rng: random.Random, p: dict) -> tuple[dict, list] | None:
    """One draw of parameters for a motif plan: a model (placeholder ids) and its binding promises."""
    period = rng.randint(90, 300)
    steps = rng.randint(400, 1000)
    b = Build(rng, period)
    spine(b, p["spine"])
    structure = [f for f in p["families"] if f in MOTIFS or f == "eras"]
    rng.shuffle(structure)
    for f in structure:
        if f != "eras":
            MOTIFS[f](b)
    while b.n_measured() < p["size"]:
        lengthen(b)
    if b.n_measured() > 15:
        return None
    if "eras" in structure:
        m_eras(b)
    inputs(b, [f for f in p["families"] if f in INPUTS])
    if len(b.spine) >= 3:                                     # three measured stocks in a row, at least
        b.motifs.add("chain")
    model = {"id": "generated", "name": "", "time_unit": "step", "seed": rng.randrange(1, 2**31), "steps": steps,
             "long_steps": steps * 5, "noise": {"counts": True}, "stocks": list(b.stocks.values()), "flows": b.flows,
             "machines": [], "schedule": schedule(b)}
    first = means(model, 6 * period)
    if first is None:
        return None
    for fn in b.later + b.refit:
        fn(*first[:2])
    if b.refit:
        second = means(model, 6 * period)
        if second is None:
            return None
        for fn in b.refit:
            fn(*second[:2])
    settled = means(model, 3 * period)
    if settled is None:
        return None
    for s in model["stocks"]:
        s["initial"] = int(round(settled[2][s["id"]] * U(rng, 0.8, 1.2)))
    model["generated"] = {"motifs": sorted(b.motifs), "details": b.details}
    return model, b.binds


def finish(model: dict, binds: list, rng: random.Random, mid: str, extra: dict) -> tuple[dict, list]:
    """Neutral ids and names (shuffled, so the order of the stocks says nothing), positions, metadata."""
    stocks = model["stocks"]
    order = list(range(len(stocks)))
    rng.shuffle(order)
    rename = {stocks[i]["id"]: f"s{n + 1}" for n, i in enumerate(order)}
    fl = list(range(len(model["flows"])))
    rng.shuffle(fl)
    rename.update({model["flows"][i]["id"]: f"f{n + 1}" for n, i in enumerate(fl)})
    text = json.dumps(model)
    for old, new in rename.items():
        text = text.replace(f'"{old}"', f'"{new}"')
    out = json.loads(text)
    out["stocks"] = sorted(out["stocks"], key=lambda s: int(s["id"][1:]))
    out["flows"] = sorted(out["flows"], key=lambda f: int(f["id"][1:]))
    for i, s in enumerate(out["stocks"]):
        s.update(name=f"Stock {s['id'][1:]}", x=80 + 240 * (i % 5), y=80 + 160 * (i // 5))
    for f in out["flows"]:
        f["name"] = f"Flow {f['id'][1:]}"
    out["id"], out["name"] = mid, f"Generated {mid}"
    out["generated"] = {"version": VERSION, "id": mid, **out["generated"], **extra}
    return out, [(k, rename[x]) for k, x in binds]


# ---- the checks every example passes (tests/test_sd_examples.py), and the motifs' promises ----

def check(model: dict, binds=()) -> list[str]:
    from sdlab.server import validate

    problems = []
    t = truth(model)
    if validate({**model, "stocks": [{k: v for k, v in s.items() if k != "measured"} for s in model["stocks"]]}):
        return ["not a valid model"]
    if not 3 <= len(t.measured_ids) <= 15:
        return [f"{len(t.measured_ids)} measured stocks"]
    final = {s["id"] for s in model["stocks"] if s.get("final")}
    for mult in (5, 50):                                   # a cheap look first
        n = t.steps * mult
        r = t.run(steps=n)
        for s, v in r["levels"].items():
            if not all(math.isfinite(x) and x >= 0 for x in v):
                return [f"{s} not finite or negative"]
            first = max(v[: t.steps])
            if s not in final and max(v) > 5 * first + 50:
                return [f"{s} grew from at most {first} to {max(v)} over {mult}x"]
    for s, v in r["levels"].items():                      # keeps exercising the model
        if s in final:
            continue
        w = len(v) // 10
        early, late = v[w: 2 * w], v[-w:]
        spread = lambda a: statistics.pstdev([b - x for x, b in zip(a, a[1:])])  # noqa: E731
        if spread(early) == 0:
            continue
        if spread(late) < 0.8 * spread(early) or statistics.pstdev(late) < 0.5 * statistics.pstdev(early):
            problems.append(f"{s} stops moving")
    w = len(next(iter(r["counters"].values()))) // 10
    for f, v in r["counters"].items():                    # every flow still moves
        if sum(v[: t.steps]) <= 0 or sum(1 for x in v[-w:] if x) < 0.03 * w:
            problems.append(f"{f} idle")
    for s in t.measured_ids:                              # every measured stock away from zero
        v = r["levels"][s][: t.steps]
        if statistics.fmean(v) < 3 or statistics.pstdev(v) == 0:
            problems.append(f"{s} near zero or flat")
    flows = {f["id"]: f for f in model["flows"]}
    for kind, x in binds:
        if kind == "floor":
            rate = flows[x]["rate"]
            below = sum(1 for i in range(1, len(r["levels"][t.stock_ids[0]]))
                        if rate["c"] + sum(term["k"] * r["levels"][term["stock"]][i - 1] for term in rate["terms"]) < 0)
            share = below / (len(r["levels"][t.stock_ids[0]]) - 1)
            if not 0.05 <= share <= 0.95:
                problems.append(f"floor {x} binds {share:.0%} of the time")
        elif kind == "empty":
            # empty: less left than one step's demand (the demand then takes what there is)
            demand = sum(f["rate"]["value"] for f in model["flows"] if f["from"] == x and f["rate"]["form"] == "constant")
            share = sum(1 for v in r["levels"][x] if v < demand) / len(r["levels"][x])
            if not 0.02 <= share <= 0.7:
                problems.append(f"cap {x} empty {share:.0%} of the time")
    return problems


def generate(pool: str, index: int, require=()) -> dict:
    """The model (pool, index): a motif plan, then parameter draws until one passes the checks; a
    new plan after DRAWS failures."""
    mid = model_id(pool, index, require)
    began, draws = time.time(), 0
    for a in range(PLANS):
        p = plan(pool, index, require, a)
        for d in range(DRAWS):
            rng = random.Random(f"sdlab-generator/{VERSION}/{mid}/plan{a}/draw{d}")
            draws += 1
            built = build(rng, p)
            if built is None:
                continue
            model, binds = finish(*built, rng, mid, {"pool": pool, "index": index, "require": sorted(require)})
            missing = [f for f in p["families"] if f not in INPUTS and f not in model["generated"]["motifs"]]
            if not missing and not check(model, binds):
                model["generated"].update(draws=draws, plan=a, seconds=round(time.time() - began, 2))
                return model
    raise RuntimeError(f"{mid}: no model passed the checks in {draws} draws")


# ---- the cache ----

def cache_dir() -> Path:
    d = Path(os.environ.get("SDLAB_BENCH_CACHE") or Path.home() / ".cache" / "sdlab" / "bench") / "generated"
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_key() -> str:
    """Generator version and source, and the engine: what decides a model and its data."""
    h = hashlib.sha256(f"generator {VERSION}\n".encode() + SOURCE.read_bytes())
    for p in ("sdtruth.py", "runner.py"):
        h.update((Path(__file__).resolve().parents[2] / "sdlab" / p).read_bytes())
    return h.hexdigest()[:12]


def model_path(pool: str, index: int, require=()) -> Path:
    return cache_dir() / "models" / f"{model_id(pool, index, require)}-{source_key()}.json"


def get(pool: str, index: int, require=()) -> dict:
    """The model, from the cache or built now (and cached)."""
    path = model_path(pool, index, require)
    if path.exists():
        return json.loads(path.read_text())
    model = generate(pool, index, require)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(model, indent=1))
    tmp.replace(path)
    return model


def dataset(model: dict, steps: int, seed: int) -> dict:
    """A run of the model, as datasets.py's: t, the measured levels, announced eras, every level."""
    path = cache_dir() / "data" / f"{model['id']}-{source_key()}-s{seed}-n{steps}.json"
    if path.exists():
        d = json.loads(path.read_text())
    else:
        t = truth(model)
        m = t.measured(seed, steps)
        d = {"t": m["t"], "eras": m["eras"], "measured": t.measured_ids, "all_levels": t.run(seed, steps)["levels"]}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, separators=(",", ":")))
        tmp.replace(path)
    return {**d, "levels": {s: d["all_levels"][s] for s in d["measured"]}}


def indices(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pool", choices=["dev"])           # the sealed pool is built by the bench, at adoption only
    ap.add_argument("indices")
    ap.add_argument("--features", default="")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    require = tuple(f for f in a.features.split(",") if f)
    for i in indices(a.indices):
        m = get(a.pool, i, require)
        if a.show:
            g = m["generated"]
            measured = sum(1 for s in m["stocks"] if s.get("measured", True))
            print(f"{m['id']}: {measured} measured, {len(m['stocks']) - measured} hidden, {len(m['flows'])} flows, "
                  f"{m['steps']} steps; {', '.join(g['motifs'])} ({g['draws']} draws)")
        else:
            print(model_path(a.pool, i, require))


if __name__ == "__main__":
    sys.exit(main())
