"""Ground-truth examples: a system dynamics model that IS the system.

An example made this way has a `truth.model.json`: an ordinary SD Lab model with every stock (the
ones the example shows, and `"measured": false` ones it does not) and every flow with its equation,
plus a few things a simulation of the real world needs:

    "steps", "long_steps", "seed"     how long a run is (default, and for the long-run tests)
    "noise": {"counts": true}         flows move whole things, drawn around their rate (Poisson):
                                      the counting noise a real system has; or {"relative": 0.1}
    "injections": [{"t": 100, "stock": "s", "amount": 1500}]
                                      announced interventions: at the start of step t, the amount
                                      is added to the stock from outside (taken away if negative,
                                      never below 0); a run can also be given injections to make
    "uses": [{"stock": "s", "per": 0.1}]   (on a flow) a co-flow: each unit the flow moves also uses up
                                      `per` of stock s; the flow cannot move more than s allows
    "schedule": {"every": 365, "changes": [{"t": 1, "label": "...", "set": {flow id: {rate}},
                                            "announce": true}]}
                                      on step t (of each period of `every` steps) a flow's equation
                                      changes. Only changes marked "announce" are eras the data
                                      reports (a change to the system: a price, a team); the rest
                                      (demand rising, night falling) happen without being announced,
                                      as the world's changes do

Added on 2026-10-18 (approved; additive: a model that uses none of them gives the same numbers as
before, tests/test_engine_additive.py proves it on every case, example and bench model):

    "dt": 0.25                        a sub-step: each recorded step is 1/dt sub-steps (1/dt a whole
                                      number); every rate moves rate x dt per sub-step and counting
                                      noise is drawn per sub-step (Poisson(rate x dt)), so a recorded
                                      step's amount has the same variance for the same rate. Schedule
                                      changes and injections happen at the start of a recorded step;
                                      levels and counters are recorded once per step (counters sum
                                      their sub-steps)
    "inputs": {"pump": {"values": [3, 3, 5, ...], "repeat": false,
                        "terms": [{"fn": "step", "height": 2, "start": 100}, ...]}}
                                      measured inputs: outside drivers given as data. A rate reads one
                                      by its name as it reads a stock's level ({"form": "proportional",
                                      "stock": "pump", "k": 0.5}, effects too). Its value in sub-step j
                                      of step t is values[t - 1] (held over the step; after the end
                                      the last value, or the series again with "repeat") plus the
                                      terms at time t + j x dt: constant {value}, step {height, start},
                                      pulse {height, start, width = 1}, ramp {slope, start, end?},
                                      pulse_train {height, first, width, every, last?}, sin {amplitude,
                                      period, phase = 0}. A run reports each input's mean over each
                                      step ("inputs"), which a page may give discovery
    "max": 500                        (on a stock) a ceiling: the flows into the stock share the room
                                      left (max - level), as its outflows share what it holds; an
                                      injection never fills it past max
    "exact": true                     (on a flow) no counting or relative noise (an information flow,
                                      e.g. the hidden stock a SMOOTH compiles to)
    "delay": {"id", "stage", "of", "time"}  (on a flow) one stage of a compiled DELAYn (the case
                                      format's delay3()): the answer key reports the chain of hidden
                                      stocks as one hidden path with its total delay

The data is made by stepping that model with SD Lab's own equations (sdlab.runner.desired_rate and
multiplier), one step per time unit, each flow computed from the levels at the start of the step:
the same convention discovery fits. So the truth is exactly a model SD Lab can hold, and a
discovery that recovers it has found the system. `truth()` derives the answer key in the shared
format (moves, flows to or from outside, links, hidden stocks) from the model itself.
"""

from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from pathlib import Path

from .runner import desired_rate, multiplier  # noqa: F401  (the equations; run() uses a compiled copy, _compile)


class Truth:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.model = json.loads(self.path.read_text())
        m = self.model
        self.seed = int(m.get("seed", 20261016))
        self.steps = int(m["steps"])
        self.long_steps = int(m.get("long_steps", self.steps * 10))
        self.measured_ids = [s["id"] for s in m["stocks"] if s.get("measured", True)]
        self.stock_ids = [s["id"] for s in m["stocks"]]

    # ---- the schedule ----
    def eras(self, steps: int) -> list[dict]:
        sch = self.model.get("schedule") or {}
        every, changes = int(sch.get("every") or 0), sorted(sch.get("changes") or [], key=lambda c: c["t"])
        out = []
        periods = max(1, math.ceil(steps / every)) if every else 1
        for p in range(periods):
            for c in changes:
                t = int(c["t"]) + p * every
                if t > steps:
                    continue
                out.append({"t": t, "label": c.get("label") or "change", "set": c.get("set") or {}, "announce": bool(c.get("announce"))})
        out.sort(key=lambda e: e["t"])
        return out

    # ---- a run ----
    def run(self, seed: int | None = None, steps: int | None = None, injections: list[dict] | None = None) -> dict:
        seed = self.seed if seed is None else seed
        steps = self.steps if steps is None else steps
        rng = random.Random(seed)
        flows = deepcopy(self.model["flows"])
        byid = {f["id"]: f for f in flows}
        noise = self.model.get("noise") or {}
        level = {s["id"]: float(s.get("initial") or 0) for s in self.model["stocks"]}
        # added features (each absent from a model that does not use it): sub-steps, measured inputs,
        # ceilings, flows without noise
        dt, n_sub = substeps(self.model)
        inputs = self.model.get("inputs") or {}
        cap = {s["id"]: float(s["max"]) for s in self.model["stocks"] if s.get("max") is not None}
        exact = {f["id"] for f in flows if f.get("exact")}
        eras = self.eras(steps)
        changes: dict[int, list[dict]] = {}
        for e in eras:
            changes.setdefault(e["t"], []).append(e)
        # co-flows: for each stock, the flows that use it up and how much per unit moved
        users: dict[str, list] = {}
        for f in flows:
            for u in f.get("uses") or []:
                if float(u.get("per") or 0) > 0:
                    users.setdefault(u["stock"], []).append((f, float(u["per"])))
        # injections (announced interventions): at the start of step t, `amount` of a stock is added
        # (or taken away; a stock never goes below 0) from outside the system, before that step's
        # flows: an impulse whose spread through the system shows how stocks are connected
        injected: dict[int, list[dict]] = {}
        for j in list(self.model.get("injections") or []) + list(injections or []):
            if int(j["t"]) <= steps and j.get("stock") in level:
                injected.setdefault(int(j["t"]), []).append(j)
        # added 2026-10-18 for speed on large models (sd-k8s-platform: ~500 stocks, ~1100 flows); the
        # same arithmetic in the same order, so every number is bit-identical (tests/test_engine_additive.py):
        # each stock's takers (its outflows, then the co-flows using it) and each ceiling's inflows are
        # found once, not every sub-step, and each flow's rate x effects is a precompiled function
        takers = []
        for s in self.stock_ids:
            take = {f["id"]: float(f.get("ratio") or 1) for f in flows if f.get("from") == s}
            for f, per in users.get(s, []):
                take[f["id"]] = take.get(f["id"], 0.0) + per
            if take:
                takers.append((s, list(take.items())))
        into = [(s, c, [f["id"] for f in flows if f.get("to") == s]) for s, c in cap.items()]
        speed = {f["id"]: _compile(f) for f in flows}
        applied = []
        levels = {s: [] for s in self.stock_ids}
        counters = {f["id"]: [] for f in flows}
        seen = {k: [] for k in inputs}
        for t in range(1, steps + 1):
            for e in changes.get(t, []):
                for fid, rate in e["set"].items():
                    byid[fid]["rate"] = rate
                    speed[fid] = _compile(byid[fid])
            for j in injected.get(t, []):
                before = level[j["stock"]]
                level[j["stock"]] = max(0.0, before + float(j["amount"]))
                if j["stock"] in cap:
                    level[j["stock"]] = min(cap[j["stock"]], level[j["stock"]])
                applied.append({"t": t, "stock": j["stock"], "amount": level[j["stock"]] - before})
            total = {f["id"]: 0 for f in flows}
            mean = {k: 0.0 for k in inputs}
            for sub in range(n_sub):
                view = level
                if inputs:                                   # a rate reads an input as it reads a level
                    now = {k: input_value(spec, t + sub * dt, t) for k, spec in inputs.items()}
                    view = {**level, **now}
                    for k, v in now.items():
                        mean[k] += v / n_sub
                amount = {}
                for f in flows:
                    q = speed[f["id"]](view)                  # desired_rate(f["rate"], view, f) * multiplier(f, view)
                    if n_sub > 1:
                        q = q * dt
                    if noise.get("counts") and f["id"] not in exact:
                        q = poisson(rng, q)
                    elif noise.get("relative") and f["id"] not in exact:
                        q = max(0.0, q * (1 + rng.gauss(0, float(noise["relative"]))))
                    amount[f["id"]] = q
                # nothing leaves a stock that is not there: outflows share what it holds (with the flows
                # that use it up as they move, co-flows: each unit they move takes `per` of it)
                for s, take in takers:
                    want = sum(amount[fid] * w for fid, w in take)
                    if want > level[s] > -1 and want > 0:     # (want > 0: a stock a rounding error left at -1e-16 with nothing to give used to divide by zero)
                        k = max(0.0, level[s]) / want
                        for fid, _ in take:
                            amount[fid] = math.floor(amount[fid] * k) if noise.get("counts") and fid not in exact else amount[fid] * k
                # nothing enters a full stock: inflows share the room left under its ceiling
                for s, c, ins in into:
                    want = sum(amount[fid] for fid in ins)
                    room = max(0.0, c - level[s])
                    if want > room:
                        k = room / want
                        for fid in ins:
                            amount[fid] = math.floor(amount[fid] * k) if noise.get("counts") and fid not in exact else amount[fid] * k
                for f in flows:
                    q = amount[f["id"]]
                    if f.get("from"):
                        level[f["from"]] -= q * float(f.get("ratio") or 1)
                    if f.get("to"):
                        level[f["to"]] += q
                    for u in f.get("uses") or []:
                        if float(u.get("per") or 0) > 0:
                            level[u["stock"]] -= q * float(u["per"])
                    if n_sub == 1:
                        counters[f["id"]].append(q if not noise.get("counts") or f["id"] in exact else int(q))
                    else:
                        total[f["id"]] += q if not noise.get("counts") or f["id"] in exact else int(q)
            if n_sub > 1:
                for fid, q in total.items():
                    counters[fid].append(q)
            for k, v in mean.items():
                seen[k].append(v)
            for s in self.stock_ids:
                levels[s].append(round(level[s], 4) if not noise.get("counts") else int(round(level[s])))
        out = {"levels": levels, "counters": counters, "eras": [{"t": e["t"], "label": e["label"]} for e in eras if e["announce"]]}
        if applied:
            out["injections"] = applied
        if inputs:
            out["inputs"] = seen
        return out

    def measured(self, seed: int | None = None, steps: int | None = None, injections: list[dict] | None = None) -> dict:
        """What SD Lab sees: the measured stocks, the eras, every flow's amount per step (a model may
        name a flow to have it measured), and the injections made (announced, like eras)."""
        steps = self.steps if steps is None else steps
        r = self.run(seed, steps, injections)
        eras, seen = [{"start": 1, "label": "Start"}], {1}
        for e in r["eras"]:
            if e["t"] in seen:
                continue
            seen.add(e["t"])
            eras.append({"start": e["t"], "label": e["label"]})
        out = {"t": list(range(1, steps + 1)), "levels": {s: r["levels"][s] for s in self.measured_ids},
               "eras": eras, "counters": r["counters"]}
        if r.get("injections"):
            out["injections"] = r["injections"]
        if r.get("inputs"):
            out["inputs"] = r["inputs"]
        return out

    # ---- the answer key ----
    def truth(self) -> dict:
        M = set(self.measured_ids)
        stocks = {s["id"]: s for s in self.model["stocks"]}
        moves, outside, links, hidden, coflows, effects = [], [], [], [], [], []
        reads = lambda f: [x for x in [(f.get("rate") or {}).get("stock"), *((t.get("stock") for t in (f.get("rate") or {}).get("terms") or []))] if x]  # noqa: E731
        for f in self.model["flows"]:
            a, b = f.get("from"), f.get("to")
            entry = {"flow": f["id"], "what": f.get("name", f["id"]), "rate": f.get("rate")}
            if a in M and b in M:
                moves.append({"from": a, "to": b, **entry})
            elif a in M and not b:
                outside.append({"from": a, **entry})
            elif b in M and not a:
                outside.append({"to": b, **entry})
            # a co-flow: a measured stock the flow uses up as it moves
            for u in f.get("uses") or []:
                if u.get("stock") in M:
                    coflows.append({"stock": u["stock"], "per": u.get("per"), "from": a if a in M else None, "to": b if b in M else None, **entry})
            # an effect: a measured stock whose level speeds the flow up or slows it down
            for e in f.get("effects") or []:
                if e.get("stock") in M:
                    effects.append({"stock": e["stock"], "shape": e.get("shape") or "linear", "from": a if a in M else None, "to": b if b in M else None, **entry})
            # a flow into a measured stock whose equation reads another measured stock: a link
            if b in M and not a:
                for d in reads(f):
                    if d in M and d != b:
                        links.append({"driver": d, "into": b, "flow": f["id"], "what": f.get("name", f["id"])})
        # hidden stocks: a measured stock -> unmeasured stock(s) -> a measured stock
        for h in (s for s in self.stock_ids if s not in M):
            ins = [f for f in self.model["flows"] if f.get("to") == h and f.get("from") in M]
            outs = [f for f in self.model["flows"] if f.get("from") == h and f.get("to") in M]
            for i in ins:
                for o in outs:
                    rate = o.get("rate") or {}
                    delay = round(1 / float(rate["k"]), 3) if rate.get("form") == "proportional" and rate.get("k") else None
                    hidden.append({"from": i["from"], "to": o["to"], "via": h, "via_name": stocks[h].get("name", h),
                                   "shape": "exp", "delay": delay, "what": f"{i.get('name', i['id'])}, then {o.get('name', o['id'])}"})
        # a compiled DELAYn (n > 1; a DELAY1 is one hidden stock, found above): its chain of hidden
        # stocks between two measured stocks is one hidden path, with the delay's total time
        chains: dict[str, list[dict]] = {}
        for f in self.model["flows"]:
            if isinstance(f.get("delay"), dict) and f["delay"].get("of", 1) > 1:
                chains.setdefault(f["delay"]["id"], []).append(f)
        for gid, fs in chains.items():
            fs = sorted(fs, key=lambda f: f["delay"]["stage"])
            a, b = fs[0].get("from"), fs[-1].get("to")
            if a in M and b in M:
                via = [f["to"] for f in fs[:-1]]
                hidden.append({"from": a, "to": b, "via": via, "via_name": ", ".join(stocks[h].get("name", h) for h in via), "shape": "erlang",
                               "order": fs[0]["delay"]["of"], "delay": float(fs[0]["delay"]["time"]), "what": fs[0].get("name", gid)})
        return {"moves": moves, "outside": outside, "links": links, "hidden": hidden, "echoes": [], **({"coflows": coflows} if coflows else {}), **({"effects": effects} if effects else {})}


def _compile(flow: dict):
    """A flow's desired_rate(rate, level, flow) x multiplier(flow, level) (sdlab/runner.py) as one
    function of the levels, with the same arithmetic in the same order (so bit-identical), and the
    work that does not depend on the levels (parsing numbers, sorting a table's points) done once."""
    rate = flow.get("rate")
    effects = [_compile_effect(e) for e in flow.get("effects") or []]
    form = rate.get("form") if rate else None
    if form == "constant":
        v = max(0.0, float(rate.get("value") or 0))
        base = lambda level: v  # noqa: E731
    elif form == "proportional":
        k, st = float(rate.get("k") or 0), rate.get("stock")
        base = lambda level: max(0.0, k * level.get(st, 0))  # noqa: E731
    elif form == "gap":
        t, goal, st = max(1e-9, float(rate.get("time") or 1)), float(rate.get("goal") or 0), rate.get("stock")
        base = lambda level: max(0.0, (goal - level.get(st, 0)) / t)  # noqa: E731
    elif form == "linear":
        c = float(rate.get("c") or 0)
        terms = [(float(x.get("k") or 0), x.get("stock")) for x in rate.get("terms") or []]
        base = lambda level: max(0.0, c + sum(k * level.get(st, 0) for k, st in terms))  # noqa: E731
    elif form == "available":
        src = rate.get("stock") or flow.get("from")
        r = float(flow.get("ratio") or 1) or 1
        base = (lambda level: level.get(src, 0) / r) if src else (lambda level: 0.0)
    else:
        base = lambda level: 0.0  # noqa: E731
    if not effects:
        return lambda level: base(level) * 1.0

    def rate_x_effects(level):
        m = 1.0
        for e in effects:
            m *= e(level)
        return base(level) * m
    return rate_x_effects


def _compile_effect(e: dict):
    """runner.effect_value(e, level) as a function of the levels (the same arithmetic)."""
    st = e.get("stock")
    if e.get("shape") == "table" and e.get("points"):
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        pairs = list(zip(pts, pts[1:]))

        def tab(level):
            x = level.get(st, 0)
            if x <= pts[0][0]:
                return max(0.0, pts[0][1])
            for (x0, y0), (x1, y1) in pairs:
                if x <= x1:
                    return max(0.0, y0 + (y1 - y0) * (x - x0) / max(1e-9, x1 - x0))
            return max(0.0, pts[-1][1])
        return tab
    normal = max(1e-9, float(e.get("normal") or 1))
    lo = float(e["min"]) if e.get("min") is not None else 0.0
    hi = float(e["max"]) if e.get("max") is not None else 1.0
    return lambda level: min(hi, max(lo, level.get(st, 0) / normal))


def substeps(model: dict) -> tuple[float, int]:
    """The model's sub-step dt and the number of sub-steps in a recorded step (1/dt, a whole number)."""
    if model.get("dt") is None:
        return 1.0, 1
    dt = float(model["dt"])
    n = round(1 / dt) if dt > 0 else 0
    if not 0 < dt <= 1 or abs(n * dt - 1) > 1e-9:
        raise ValueError(f"dt must be 1/n for a whole number n (got {model['dt']!r})")
    return 1.0 / n, n


def input_value(spec, tau: float, t: int) -> float:
    """A measured input's value at time tau in step t (tau = t + j x dt in sub-step j): its series'
    value for step t (held over the step) plus its terms at tau."""
    if isinstance(spec, list):
        spec = {"values": spec}
    v = 0.0
    vals = spec.get("values")
    if vals:
        i = t - 1
        v = float(vals[i % len(vals)] if spec.get("repeat") else vals[min(max(i, 0), len(vals) - 1)])
    for term in spec.get("terms") or []:
        v += _term_value(term, tau)
    return v


def _term_value(term: dict, tau: float) -> float:
    fn = term.get("fn")
    num = lambda k, d=0.0: float(term[k]) if term.get(k) is not None else d  # noqa: E731
    if fn == "constant":
        return num("value")
    if fn == "step":
        return num("height") if tau >= num("start") else 0.0
    if fn == "pulse":
        return num("height") if num("start") <= tau < num("start") + num("width", 1.0) else 0.0
    if fn == "ramp":
        start, end = num("start"), num("end", math.inf)
        return num("slope") * (min(tau, end) - start) if tau > start else 0.0
    if fn == "pulse_train":
        first, last, every = num("first"), num("last", math.inf), max(1e-9, num("every", 1.0))
        return num("height") if first <= tau <= last and (tau - first) % every < num("width", 1.0) else 0.0
    if fn == "sin":
        return num("amplitude") * math.sin(2 * math.pi * (tau - num("phase")) / max(1e-9, num("period", 1.0)))
    raise ValueError(f"unknown input term {fn!r} (constant, step, pulse, ramp, pulse_train, sin)")


def poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 50:                                            # normal approximation for large means
        return max(0, int(round(rng.gauss(mean, math.sqrt(mean)))))
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


# ---- the example's programs: each example's machines/*.py are two lines calling these ----

def history_main(truth: Truth) -> None:
    """history.py: one line per step, {"t", "levels", "flows"?, "era"?}; the measured stocks the model
    asks for (all when stdin is empty), and the flows it names that the truth has."""
    import sys
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    job = json.loads(stdin) if stdin.strip() else {}
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else truth.seed
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else truth.steps
    m = truth.measured(seed, steps)
    stocks = [s["id"] for s in job.get("stocks") or [] if s["id"] in m["levels"]] or list(m["levels"])
    flows = [f["id"] for f in job.get("flows") or [] if f.get("id") in m["counters"]]
    eras = {e["start"]: e["label"] for e in m["eras"] if e["start"] > 1}
    for i, t in enumerate(m["t"]):
        row = {"t": t, "levels": {s: m["levels"][s][i] for s in stocks}}
        if flows:
            row["flows"] = {f: m["counters"][f][i] for f in flows}
        if t in eras:
            row["era"] = eras[t]
        print(json.dumps(row))


def write_truth(truth: Truth, out: Path) -> dict:
    """truth.py: the answer key, written next to the model."""
    t = {"note": "Derived from truth.model.json, the system dynamics model that generates this example's data.",
         "seed": truth.seed, "steps": truth.steps, "measured": truth.measured_ids,
         "hidden_stocks": [s for s in truth.stock_ids if s not in truth.measured_ids],
         "schedule": truth.model.get("schedule"), "sd_structure": truth.truth()}
    out.write_text(json.dumps(t, indent=1) + "\n")
    return t
