"""Ground-truth examples: a system dynamics model that IS the system.

An example made this way has a `truth.model.json`: an ordinary SD Lab model with every stock (the
ones the example shows, and `"measured": false` ones it does not) and every flow with its equation,
plus a few things a simulation of the real world needs:

    "steps", "long_steps", "seed"     how long a run is (default, and for the long-run tests)
    "noise": {"counts": true}         flows move whole things, drawn around their rate (Poisson):
                                      the counting noise a real system has; or {"relative": 0.1}
    "schedule": {"every": 365, "changes": [{"t": 1, "label": "...", "set": {flow id: {rate}},
                                            "announce": true}]}
                                      on step t (of each period of `every` steps) a flow's equation
                                      changes. Only changes marked "announce" are eras the data
                                      reports (a change to the system: a price, a team); the rest
                                      (demand rising, night falling) happen without being announced,
                                      as the world's changes do

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

from .runner import desired_rate, multiplier


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
    def run(self, seed: int | None = None, steps: int | None = None) -> dict:
        seed = self.seed if seed is None else seed
        steps = self.steps if steps is None else steps
        rng = random.Random(seed)
        flows = deepcopy(self.model["flows"])
        byid = {f["id"]: f for f in flows}
        noise = self.model.get("noise") or {}
        level = {s["id"]: float(s.get("initial") or 0) for s in self.model["stocks"]}
        eras = self.eras(steps)
        changes: dict[int, list[dict]] = {}
        for e in eras:
            changes.setdefault(e["t"], []).append(e)
        levels = {s: [] for s in self.stock_ids}
        counters = {f["id"]: [] for f in flows}
        for t in range(1, steps + 1):
            for e in changes.get(t, []):
                for fid, rate in e["set"].items():
                    byid[fid]["rate"] = rate
            amount = {}
            for f in flows:
                q = desired_rate(f.get("rate"), level, f) * multiplier(f, level)
                if noise.get("counts"):
                    q = poisson(rng, q)
                elif noise.get("relative"):
                    q = max(0.0, q * (1 + rng.gauss(0, float(noise["relative"]))))
                amount[f["id"]] = q
            # nothing leaves a stock that is not there: outflows share what it holds
            for s in self.stock_ids:
                outs = [f for f in flows if f.get("from") == s]
                want = sum(amount[f["id"]] * float(f.get("ratio") or 1) for f in outs)
                if want > level[s] > -1:
                    k = max(0.0, level[s]) / want
                    for f in outs:
                        amount[f["id"]] = math.floor(amount[f["id"]] * k) if noise.get("counts") else amount[f["id"]] * k
            for f in flows:
                q = amount[f["id"]]
                if f.get("from"):
                    level[f["from"]] -= q * float(f.get("ratio") or 1)
                if f.get("to"):
                    level[f["to"]] += q
                counters[f["id"]].append(q if not noise.get("counts") else int(q))
            for s in self.stock_ids:
                levels[s].append(round(level[s], 4) if not noise.get("counts") else int(round(level[s])))
        return {"levels": levels, "counters": counters, "eras": [{"t": e["t"], "label": e["label"]} for e in eras if e["announce"]]}

    def measured(self, seed: int | None = None, steps: int | None = None) -> dict:
        """What SD Lab sees: the measured stocks, the eras, and every flow's amount per step (a
        model may name a flow to have it measured)."""
        steps = self.steps if steps is None else steps
        r = self.run(seed, steps)
        eras, seen = [{"start": 1, "label": "Start"}], {1}
        for e in r["eras"]:
            if e["t"] in seen:
                continue
            seen.add(e["t"])
            eras.append({"start": e["t"], "label": e["label"]})
        return {"t": list(range(1, steps + 1)), "levels": {s: r["levels"][s] for s in self.measured_ids},
                "eras": eras, "counters": r["counters"]}

    # ---- the answer key ----
    def truth(self) -> dict:
        M = set(self.measured_ids)
        stocks = {s["id"]: s for s in self.model["stocks"]}
        moves, outside, links, hidden = [], [], [], []
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
        return {"moves": moves, "outside": outside, "links": links, "hidden": hidden, "echoes": []}


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
