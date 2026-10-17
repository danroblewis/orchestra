"""Live runs: real items in stocks, real programs as machines.

A stock is a store of items, not a queue. A flow says what it takes. Each input names a
stock, an optional `where` that relates it to inputs taken before it, and an `order`:
"any" (the default, an arbitrary item) or "oldest" (a FIFO queue). The runner finds a
matching set and takes it, so programs never query anything. It then runs the machine's
program once:

    argv:   the program, the flow's args, then the machine's args (its parameters)
    stdin:  {"flow": <id>, "inputs": {<name>: {"_id": ..., ...fields}}}
    stdout: one JSON object per line, {"to": <stock id or null>, "item": {...}}

"to" may name the flow's `to` or any stock in its `outputs`; null means the item leaves
the model. If the program fails, the items it was given go back where they came from.

Time moves in ticks; one tick is one of the model's time units. On each tick:
- Environment flows fire as often as their rate equation asks. Fractions carry over to
  the next tick.
- Each machine spends its capacity on its flows in turn, and each firing costs the flow's
  `work`.

Every put, take and tick is appended to a JSON-lines log. That log is how a run survives
a restart, and it is where the measured stock levels and flow rates come from."""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .programs import Programs

PROGRAM_RE = re.compile(r"^[a-z0-9_-]+/[a-z0-9_-]+$")


def desired_rate(rate: dict | None, level: dict[str, float], flow: dict | None = None) -> float:
    """Same equation forms as the simulator (static/sim.js), per tick."""
    if not rate:
        return 0.0
    form = rate.get("form")
    if form == "constant":
        return max(0.0, float(rate.get("value") or 0))
    if form == "proportional":
        return max(0.0, float(rate.get("k") or 0) * level.get(rate.get("stock"), 0))
    if form == "gap":
        t = max(1e-9, float(rate.get("time") or 1))
        return max(0.0, (float(rate.get("goal") or 0) - level.get(rate.get("stock"), 0)) / t)
    if form == "linear":
        return max(0.0, float(rate.get("c") or 0) + sum(float(t.get("k") or 0) * level.get(t.get("stock"), 0) for t in rate.get("terms") or []))
    if form == "available":
        src = rate.get("stock") or (flow or {}).get("from")
        r = float((flow or {}).get("ratio") or 1) or 1
        return level.get(src, 0) / r if src else 0.0
    return 0.0


# What makes two configurations "the same system": machines, who runs what, programs and their
# arguments, capacities, work per item, and what each flow takes and fills. Equations, names,
# positions and goals are beliefs and labels, not the system, so changing them does not start an era.
def config_key(model: dict) -> str:
    machines = sorted((m.get("id"), m.get("program"), tuple(m.get("args") or []), m.get("capacity"), m.get("capacity_stock"), m.get("prompt"))
                      for m in model.get("machines", []))
    flows = sorted((f.get("id"), f.get("from"), f.get("to"), tuple(f.get("outputs") or []), json.dumps(f.get("take"), sort_keys=True),
                    f.get("machine"), f.get("work"), tuple(f.get("args") or []), f.get("program"), f.get("ratio"),
                    json.dumps(f.get("effects"), sort_keys=True), json.dumps(f.get("uses"), sort_keys=True), bool(f.get("rule")))
                   for f in model.get("flows", []))
    stocks = sorted(s.get("id") for s in model.get("stocks", []))
    return json.dumps([machines, flows, stocks], default=str)


def describe_change(old: dict | None, new: dict) -> str:
    """One line, in the person's terms, on what differs between two configurations."""
    if old is None:
        return "Start"
    out: list[str] = []
    om = {m["id"]: m for m in old.get("machines", [])}
    nm = {m["id"]: m for m in new.get("machines", [])}

    def name(d: dict, i: str | None) -> str:
        return (d.get(i) or {}).get("name", i or "")

    def who(fl: dict) -> str:
        if fl.get("machine") == "environment":
            return "environment"
        return name(nm, fl.get("machine")) if fl.get("machine") else "no machine"

    for i in nm.keys() - om.keys():
        out.append(f"new machine {name(nm, i)}")
    for i in om.keys() - nm.keys():
        out.append(f"removed {name(om, i)}")
    for i in nm.keys() & om.keys():
        if om[i].get("capacity") != nm[i].get("capacity"):
            out.append(f"{name(nm, i)} capacity {om[i].get('capacity')} \u2192 {nm[i].get('capacity')}")
        for k, label in (("program", "program"), ("args", "parameters")):
            if om[i].get(k) != nm[i].get(k):
                out.append(f"{name(nm, i)} {label} changed")
    of = {f["id"]: f for f in old.get("flows", [])}
    for f in new.get("flows", []):
        g = of.get(f["id"])
        fname = f.get("name", f["id"])
        if g is None:
            out.append(f"new flow {fname}")
        elif g.get("machine") != f.get("machine"):
            out.append(f"{fname} now run by {who(f)}")
        elif g.get("work") != f.get("work"):
            out.append(f"{fname} work {g.get('work')} \u2192 {f.get('work')}")
        elif config_key({"flows": [g]}) != config_key({"flows": [f]}):
            out.append(f"{fname} changed")
    for i in of.keys() - {f["id"] for f in new.get("flows", [])}:
        out.append(f"removed flow {of[i].get('name', i)}")
    return "; ".join(out) or "configuration changed"


def effect_value(e: dict, level: dict[str, float]) -> float:
    """Same as effectValue in static/sim.js: a speed multiplier from a stock's level."""
    x = level.get(e.get("stock"), 0)
    if e.get("shape") == "table" and e.get("points"):
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        if x <= pts[0][0]:
            return max(0.0, pts[0][1])
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return max(0.0, y0 + (y1 - y0) * (x - x0) / max(1e-9, x1 - x0))
        return max(0.0, pts[-1][1])
    normal = max(1e-9, float(e.get("normal") or 1))
    lo = float(e["min"]) if e.get("min") is not None else 0.0
    hi = float(e["max"]) if e.get("max") is not None else 1.0
    return min(hi, max(lo, x / normal))


def multiplier(flow: dict, level: dict[str, float]) -> float:
    m = 1.0
    for e in flow.get("effects") or []:
        m *= effect_value(e, level)
    return m


def machine_capacity(m: dict, level: dict[str, float]) -> float:
    c = max(0.0, float(m.get("capacity") or 0))
    return c * max(0.0, level.get(m["capacity_stock"], 0)) if m.get("capacity_stock") else c


def take_spec(flow: dict) -> list[dict]:
    """A flow's inputs; with none declared, one arbitrary item from its `from` stock."""
    if flow.get("take"):
        return flow["take"]
    return [{"as": "item", "from": flow["from"]}] if flow.get("from") else []


def program_path(examples: Path, program: str) -> Path | None:
    """Programs are named, never given as paths or shell text: `<example>/<name>` resolves to
    sdlab/examples/<example>/machines/<name>.py. A model can be edited by anyone who can open
    the page, so it must not be able to run arbitrary commands."""
    if not isinstance(program, str) or not PROGRAM_RE.match(program):
        return None
    ex, name = program.split("/")
    p = examples / ex / "machines" / f"{name}.py"
    return p if p.is_file() else None


def available_programs(examples: Path) -> list[str]:
    return sorted(f"{p.parent.parent.name}/{p.stem}" for p in examples.glob("*/machines/*.py"))


class LiveRun:
    def __init__(self, model_id: str, model_path: Path, run_dir: Path, examples: Path):
        self.model_id, self.model_path, self.examples = model_id, model_path, examples
        self.run_dir = run_dir
        self.log_path = run_dir / "log.jsonl"
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.seconds_per_tick = 1.0
        self.programs = Programs()
        self.rng = random.Random()
        self._reset_memory()
        self._replay()

    # ---------- state ----------
    def _reset_memory(self) -> None:
        self.items: dict[str, dict[str, dict]] = {}      # stock -> id -> {"_id", "_t", ...fields}
        self.t = 0
        self.next_id = 1
        self.series: dict[str, Any] = {"t": [], "levels": {}, "rates": {}, "load": {}, "moved": []}
        self._acct: dict[str, dict] = {}                 # this tick: per flow, items taken from and made into each stock
        self.carry: dict[str, float] = {}                # environment firings owed from fractions
        self.observed: dict[str, float] = {}             # levels of stocks measured by sensors
        self.rotation: dict[str, int] = {}               # machine -> index of the flow it tries first
        self.eras: list[dict] = []                       # [{n, start, key, label, model, equations: [{t, rates}]}]
        self.recent: list[dict] = []                     # last firings, newest last, with their stdin and stdout
        self.seq = 0
        self.errors: list[dict] = []

    def model(self) -> dict:
        return json.loads(self.model_path.read_text())

    def _log(self, rec: dict) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def _replay(self) -> None:
        if not self.log_path.exists():
            return
        for line in self.log_path.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            op = r.get("op")
            if op == "put":
                self.items.setdefault(r["stock"], {})[r["item"]["_id"]] = r["item"]
                self.next_id = max(self.next_id, int(r["item"]["_id"].lstrip("i") or 0) + 1)
            elif op == "take":
                self.items.get(r["stock"], {}).pop(r["id"], None)
            elif op == "tick":
                self._record(r)
                if r.get("observed"):
                    self.observed.update(r["observed"])
            elif op == "era":
                self.eras.append({k: r[k] for k in ("n", "start", "key", "label", "model", "base") if k in r} | {"equations": [{"t": r["start"], "rates": r["rates"]}]})
            elif op == "equations" and self.eras:
                self.eras[-1]["equations"].append({"t": r["t"], "rates": r["rates"]})

    def _record(self, r: dict) -> None:
        self.t = r["t"]
        s = self.series
        s["t"].append(r["t"])
        s["moved"].append(r.get("moved", {}))
        for key in ("levels", "rates", "load"):
            for k, v in r.get(key, {}).items():
                col = s[key].setdefault(k, [0] * (len(s["t"]) - 1))
                col.append(v)
            for k, col in s[key].items():                 # anything missing this tick reads 0
                if len(col) < len(s["t"]):
                    col.append(0)

    def level(self, stock: str) -> float:
        if stock in self.observed:
            return self.observed[stock]
        return len(self.items.get(stock, {}))

    # ---------- sensors ----------
    # A model can measure stocks instead of holding items: each entry of `sensors` names a program
    # that prints one JSON object of {stock id: level}. Measured stocks are read every tick; they
    # hold no items, so flows cannot take from them. `history` names a program that prints past
    # levels, one {"t": step, "levels": {...}} per line, which "import" turns into the run's record.
    @staticmethod
    def measure_input(model: dict, t: int | None = None) -> str:
        """What a sensor or history program is told: the model's stocks and flows with their
        queries (a stock's or flow's `query`, e.g. PromQL), so one generic program can measure any
        model; a sensor is also told the step it is measuring (`t`)."""
        return json.dumps({
            **({"t": t} if t is not None else {}),
            "model": {k: model.get(k) for k in ("id", "name", "time_unit", "step_seconds", "era_query")},
            "stocks": [{k: s.get(k) for k in ("id", "name", "unit", "query")} for s in model.get("stocks", [])],
            "flows": [{k: f.get(k) for k in ("id", "name", "from", "to", "ratio", "outputs", "query")} for f in model.get("flows", []) if not f.get("hidden")],
        })

    def _flows_to_moves(self, model: dict, amounts: dict) -> dict:
        """Measured flow amounts for one step, as the per-stock accounting discovery subtracts."""
        moved, flows = {}, {f["id"]: f for f in model.get("flows", [])}
        for fid, amt in (amounts or {}).items():
            f = flows.get(fid)
            if not f or amt is None:
                continue
            amt = float(amt)
            ratio = float(f.get("ratio") or 1)
            moved[fid] = {"took": {f["from"]: amt * ratio} if f.get("from") else {}, "made": {f["to"]: amt} if f.get("to") else {}}
        return moved

    def sense(self, model: dict, t: int) -> list[tuple[dict, dict]]:
        """Run every sensor for step t: [(sensor, what it printed)]. Failures are noted as errors."""
        out = []
        for sensor in model.get("sensors") or []:
            path = program_path(self.examples, sensor.get("program", ""))
            if path is None:
                self.errors = (self.errors + [{"t": t, "flow": None, "error": f"no sensor program {sensor.get('program')!r}"}])[-20:]
                continue
            try:
                p = self.programs.run(path, [*map(str, sensor.get("args") or [])], self.measure_input(model, t), 60)
                values = json.loads(p.stdout or "{}") if p.returncode == 0 else None
                if values is None:
                    raise ValueError((p.stderr or "no output").strip()[-300:])
                if p.stderr.strip():                               # it read something, but says what it could not
                    self.errors = (self.errors + [{"t": t, "flow": None, "error": f"sensor {sensor.get('program')}: {p.stderr.strip()}"[-300:]}])[-20:]
                out.append((sensor, values))
            except (ValueError, subprocess.TimeoutExpired, OSError) as e:
                self.errors = (self.errors + [{"t": t, "flow": None, "error": f"sensor {sensor.get('program')}: {e}"[-300:]}])[-20:]
        return out

    def apply_readings(self, model: dict, readings: list[tuple[dict, dict]]) -> None:
        for _, values in readings:
            # either {stock: level} or {"levels": {...}, "flows": {flow: amount this step}}
            levels = values.get("levels", values) if isinstance(values.get("levels"), dict) else values
            for sid, v in levels.items():
                if v is not None and not isinstance(v, (dict, str)) and sid not in ("time", "era"):
                    self.observed[sid] = float(v)
            if values.get("era"):                                 # a change the sensor knows about (a staffing change)
                self._note_change(model, self.t, str(values["era"]))
            if isinstance(values.get("flows"), dict):
                for fid, a in self._flows_to_moves(model, values["flows"]).items():
                    self._acct[fid] = a
                self._sensed_rates = {k: float(v) for k, v in values["flows"].items() if v is not None}

    def import_history(self) -> int:
        model = self.model()
        h = model.get("history") or {}
        path = program_path(self.examples, h.get("program", ""))
        if path is None:
            raise ValueError("this model has no history program")
        p = subprocess.run([sys.executable, str(path), *map(str, h.get("args") or [])], input=self.measure_input(model),
                           capture_output=True, text=True, timeout=1800, cwd=path.parent)
        if p.returncode != 0:
            raise ValueError((p.stderr or "history program failed").strip()[-300:])
        self.reset()
        with self.lock:
            stocks = [s["id"] for s in model.get("stocks", [])]
            self._note_era(model, 1)
            n = 0
            for line in p.stdout.splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("era"):                              # a change the history knows about (a deploy, a scale-up)
                    self._note_change(model, int(r["t"]), str(r["era"]))
                levels = {sid: round(float(r.get("levels", {}).get(sid) or 0), 4) for sid in stocks}
                self.observed.update(levels)
                rates = {k: round(float(v), 4) for k, v in (r.get("flows") or {}).items() if v is not None}
                rec = {"op": "tick", "t": int(r["t"]), "levels": levels, "rates": rates, "load": {}}   # measured: the accounting is the rates
                if r.get("time") is not None:
                    rec["time"] = r["time"]
                self._log(rec)
                self._record(rec)
                n += 1
            return n

    def _note_change(self, model: dict, t: int, label: str) -> None:
        """An era that the record itself announces (the configuration in the model is unchanged)."""
        rates = {f["id"]: f.get("rate") for f in model.get("flows", [])}
        era = {"n": len(self.eras) + 1, "start": t, "key": config_key(model) + f"#{len(self.eras) + 1}", "base": config_key(model), "label": label, "model": model}
        self._log({"op": "era", **era, "rates": rates})
        self.eras.append({**era, "equations": [{"t": t, "rates": rates}]})

    def put(self, stock: str | None, data: dict) -> str | None:
        if stock is None:
            return None
        item = {k: v for k, v in data.items() if k not in ("_id", "_t")}
        item["_id"] = f"i{self.next_id}"
        item["_t"] = self.t
        self.next_id += 1
        self.items.setdefault(stock, {})[item["_id"]] = item
        self._log({"op": "put", "stock": stock, "item": item})
        return item["_id"]

    def _take(self, stock: str, item_id: str) -> dict:
        item = self.items[stock].pop(item_id)
        self._log({"op": "take", "stock": stock, "id": item_id})
        return item

    def _give_back(self, stock: str, item: dict) -> None:
        self.items.setdefault(stock, {})[item["_id"]] = item
        self._log({"op": "put", "stock": stock, "item": item})

    # ---------- matching ----------
    def match(self, spec: list[dict]) -> dict[str, tuple[str, dict]] | None:
        """Bind every input to a distinct item that satisfies its `where`, or return None."""
        bound: dict[str, tuple[str, dict]] = {}
        used: set[str] = set()

        def ok(inp: dict, item: dict) -> bool:
            for field, want in (inp.get("where") or {}).items():
                if isinstance(want, str) and "." in want and want.split(".", 1)[0] in bound:
                    name, ref = want.split(".", 1)
                    want = bound[name][1].get(ref)
                if item.get(field) != want:
                    return False
            return True

        def candidates(inp: dict) -> list[dict]:
            pool = [it for it in self.items.get(inp["from"], {}).values() if it["_id"] not in used]
            order = inp.get("order", "any")
            if order == "oldest":
                return pool                                # dicts keep insertion order
            if order == "newest":
                return pool[::-1]
            self.rng.shuffle(pool)
            return pool

        def go(k: int) -> bool:
            if k == len(spec):
                return True
            inp = spec[k]
            for item in candidates(inp):
                if ok(inp, item):
                    bound[inp["as"]] = (inp["from"], item)
                    used.add(item["_id"])
                    if go(k + 1):
                        return True
                    used.discard(item["_id"])
                    del bound[inp["as"]]
            return False

        return bound if go(0) else None

    # ---------- firing ----------
    def fire(self, model: dict, flow: dict, program: str, args: list[str], machine: dict | None = None) -> bool:
        spec = take_spec(flow)
        # a co-flow uses whole items of another stock as its fractions add up; without them, no run
        uses_due = []
        for u in flow.get("uses") or []:
            key = f"use:{flow['id']}:{u.get('stock')}"
            owed = self.carry.get(key, 0.0) + float(u.get("per") or 0)
            n = int(owed + 1e-9)
            if n > self.level(u.get("stock")):
                return False
            uses_due.append((u.get("stock"), n, key, owed - n))
        bound = self.match(spec) if spec else {}
        if bound is None:
            return False
        used: list[tuple[str, dict]] = []
        for stock, n, key, rest in uses_due:
            for item_id in list(self.items.get(stock, {}))[:n]:
                used.append((stock, self._take(stock, item_id)))
        used_carry = [(key, rest) for _, _, key, rest in uses_due]
        taken = {name: (stock, self._take(stock, item["_id"])) for name, (stock, item) in bound.items()}
        path = program_path(self.examples, program)
        started = time.time()
        outs: list[tuple[str | None, dict]] = []
        err = None
        argv = [*map(str, flow.get("args") or []), *map(str, args)]
        # what the program is given: the items it took, where it may write, and a glance at the
        # stocks around it (an AI agent uses this as its context; a plain program can ignore it)
        allowed = [x for x in [flow.get("to"), *(flow.get("outputs") or [])]]
        near = {x for x in [flow.get("from"), *allowed, *(u.get("stock") for u in flow.get("uses") or []),
                            *(e.get("stock") for e in flow.get("effects") or []), (machine or {}).get("capacity_stock")] if x}
        context = {sid: {"name": next((st.get("name", sid) for st in model.get("stocks", []) if st["id"] == sid), sid), "level": self.level(sid),
                         "sample": [{k: v for k, v in it.items() if not k.startswith("_")} for it in list(self.items.get(sid, {}).values())[-3:]]} for sid in sorted(near)}
        payload = {"flow": flow["id"], "flow_name": flow.get("name", flow["id"]), "inputs": {name: item for name, (_, item) in taken.items()},
                   "to": allowed, "context": context}
        if machine and machine.get("prompt"):
            payload["prompt"] = machine["prompt"]
        stdin = json.dumps(payload)
        stdout = stderr = ""
        if path is None:
            err = f"no program {program!r}"
        else:
            try:
                timeout = float((machine or {}).get("timeout") or (180 if (machine or {}).get("kind") == "agent" else 20))
                p = self.programs.run(path, argv, stdin, timeout)
                stdout, stderr = p.stdout, p.stderr
                if p.returncode != 0:
                    err = (p.stderr.strip() or f"exit {p.returncode}")[-300:]
                else:
                    allowed = {flow.get("to"), *(flow.get("outputs") or [])}
                    for line in p.stdout.splitlines():
                        if not line.strip():
                            continue
                        rec = json.loads(line)
                        to = rec.get("to", flow.get("to"))
                        if to not in allowed:
                            raise ValueError(f"output to {to!r}, but this flow can only fill {sorted(x or 'outside' for x in allowed)}")
                        outs.append((to, rec.get("item") or {}))
            except (ValueError, subprocess.TimeoutExpired, OSError) as e:
                err = str(e)[-300:]
        # every firing is kept with exactly what the program saw and said, so the page can show it
        self.seq += 1
        rec = {"n": self.seq, "t": self.t, "flow": flow["id"], "program": program, "argv": argv,
               "in": [i["_id"] for _, i in taken.values()], "out": len(outs), "ok": err is None,
               "ms": round((time.time() - started) * 1000),
               "stdin": stdin[:4000], "stdout": stdout[:4000], "stderr": (stderr or err or "")[:2000]}
        self.recent = (self.recent + [rec])[-60:]
        if err:
            for stock, item in [*taken.values(), *used]:                # nothing is used up by a run that failed
                self._give_back(stock, item)
            self.errors = (self.errors + [{"t": self.t, "flow": flow["id"], "error": err}])[-20:]
            return False
        for to, item in outs:
            self.put(to, item)
        for key, rest in used_carry:
            self.carry[key] = rest
        # exact accounting: how many items this flow took from and made into each stock
        acct = self._acct.setdefault(flow["id"], {"took": {}, "made": {}})
        for stock, _ in used:
            acct["took"][stock] = acct["took"].get(stock, 0) + 1
        for stock, _ in taken.values():
            acct["took"][stock] = acct["took"].get(stock, 0) + 1
        for to, _ in outs:
            if to is not None:
                acct["made"][to] = acct["made"].get(to, 0) + 1
        return True

    def _note_era(self, model: dict, t: int) -> None:
        """A new era when the system's configuration differs from the current era's; a new
        equations record when the beliefs about the flows changed within the era."""
        rates = {f["id"]: f.get("rate") for f in model.get("flows", [])}
        key = config_key(model)
        if not self.eras or self.eras[-1].get("base", self.eras[-1]["key"]) != key:   # an announced era keeps its configuration
            prev = self.eras[-1]["model"] if self.eras else None
            era = {"n": len(self.eras) + 1, "start": t, "key": key, "label": describe_change(prev, model), "model": model}
            self._log({"op": "era", **era, "rates": rates})
            self.eras.append({**era, "equations": [{"t": t, "rates": rates}]})
        elif self.eras[-1]["equations"][-1]["rates"] != rates:
            self._log({"op": "equations", "t": t, "rates": rates})
            self.eras[-1]["equations"].append({"t": t, "rates": rates})

    def _allowance(self, f: dict, level: dict[str, float]) -> int:
        """Whole firings a rule-following flow may make this tick (fractions carry over)."""
        key = "rule:" + f["id"]
        if key + ":t" not in self.carry or self.carry[key + ":t"] != self.t:
            want = desired_rate(f.get("rate"), level, f) + self.carry.get(key, 0.0)
            self.carry[key + ":n"] = float(int(want))
            self.carry[key] = want - int(want)
            self.carry[key + ":t"] = self.t
        return int(self.carry[key + ":n"])

    def tick(self, force: bool = True) -> bool:
        """One step. A measured model whose sensors report the time of their sample (a metrics
        store, say) steps only when there is a new sample, unless forced (the Step button): a
        live run cannot go faster than the system it measures. Returns whether it stepped."""
        with self.lock:
            model = self.model()
            readings = None
            if model.get("sensors"):
                readings = self.sense(model, self.t + 1)
                # no sensor could read anything (the recording ended, the source is down): there is
                # nothing new to record, so no step is taken; recording the last levels again would
                # fill the run with a stretch where nothing happens
                if not readings and not force:
                    # three failed reads in a row and the run stops, saying why: a source that keeps
                    # failing (a recording that ended, a server that is down) is not a quiet system
                    self._failed_reads = getattr(self, "_failed_reads", 0) + 1
                    if self._failed_reads >= 3:
                        why = (self.errors[-1]["error"] if self.errors else "no sensor could read anything")
                        self.stopped_because = {"t": self.t, "reason": why}
                    return False
                self._failed_reads = 0
                stamps = tuple(v.get("time") for _, v in readings)
                if not force and readings and None not in stamps and stamps == getattr(self, "_last_stamp", None):
                    return False
                self._last_stamp = stamps
            self._note_era(model, self.t + 1)
            if self.t == 0:                                  # a run starts from each stock's starting value
                for st in model.get("stocks", []):
                    n = int(float(st.get("initial") or 0))
                    if n > 0 and not model.get("sensors") and self.level(st["id"]) == 0:   # measured models start from what is measured
                        for _ in range(n):
                            self.put(st["id"], {"initial": True})
            self.t += 1
            self._acct = {}
            if readings is not None:
                self.apply_readings(model, readings)
            fires: dict[str, int] = {f["id"]: 0 for f in model.get("flows", [])}
            level = {s["id"]: self.level(s["id"]) for s in model.get("stocks", [])}

            # environment flows: as often as their equation asks
            for f in model.get("flows", []):
                if f.get("machine") != "environment" or not f.get("program"):
                    continue
                want = desired_rate(f.get("rate"), level, f) * multiplier(f, level) + self.carry.get(f["id"], 0.0)
                n = int(want)
                self.carry[f["id"]] = want - n
                for _ in range(n):
                    if self.fire(model, f, f["program"], [], None):
                        fires[f["id"]] += 1

            # machines: share time fairly. The flow that has had the least of the machine's time
            # this tick goes next, until nothing can fire or the time is used up. A firing may run
            # past the end of the tick; the overrun (or any unused time) carries to the next one.
            load: dict[str, float] = {}
            for m in model.get("machines", []):
                mine = [f for f in model.get("flows", []) if f.get("machine") == m["id"]]
                cap = machine_capacity(m, level)
                budget = cap + self.carry.get("machine:" + m["id"], 0.0)
                spent, used, stuck = 0.0, {f["id"]: 0.0 for f in mine}, set()
                start = self.rotation.get(m["id"], 0)
                order = {f["id"]: (k - start) % max(1, len(mine)) for k, f in enumerate(mine)}
                while mine and len(stuck) < len(mine) and spent < budget - 1e-9:
                    f = min((x for x in mine if x["id"] not in stuck), key=lambda x: (used[x["id"]], order[x["id"]]))
                    # a flow whose equation is a rule the machine follows ("keep 10 bags on the
                    # shelf") fires no more often than the equation allows this tick
                    if f.get("rule") and fires[f["id"]] >= self._allowance(f, level):
                        stuck.add(f["id"])
                        continue
                    eff = multiplier(f, {s["id"]: self.level(s["id"]) for s in model.get("stocks", [])})
                    if eff <= 0.02:                               # its effect has brought it to a stop
                        stuck.add(f["id"])
                        continue
                    work = max(0.0, float(f.get("work") or 0)) / eff
                    if self.fire(model, f, m.get("program") or "", m.get("args") or [], m):
                        fires[f["id"]] += 1
                        spent += work
                        used[f["id"]] += work if work else 1e-6
                        if not work and fires[f["id"]] > 1000:
                            stuck.add(f["id"])
                    else:
                        stuck.add(f["id"])
                self.rotation[m["id"]] = start + 1
                # unused time is not banked beyond one tick; an overrun is owed
                self.carry["machine:" + m["id"]] = max(-cap, min(0.0, budget - spent)) if len(stuck) == len(mine) else budget - spent
                load[m["id"]] = spent / cap if cap else 0.0

            if getattr(self, "_sensed_rates", None):
                fires.update(self._sensed_rates)
                self._sensed_rates = {}
            rec = {"op": "tick", "t": self.t, "levels": {s["id"]: self.level(s["id"]) for s in model.get("stocks", [])},
                   "rates": fires, "load": load, "moved": self._acct}
            if self.observed:
                rec["observed"] = dict(self.observed)
            self._log(rec)
            self._record(rec)
            return True

    # ---------- control ----------
    def start(self, seconds_per_tick: float | None = None) -> None:
        if seconds_per_tick is not None:                     # 0: as fast as the programs go
            self.seconds_per_tick = max(0.0, float(seconds_per_tick))
        if self.thread and self.thread.is_alive():
            return
        self.stopped_because, self._failed_reads = None, 0
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while not self.stop_flag.is_set():
            began, stepped = time.time(), True
            try:
                stepped = self.tick(force=False)
            except Exception as e:                           # a bad model must not kill the server
                with self.lock:
                    self.errors = (self.errors + [{"t": self.t, "flow": None, "error": repr(e)[-300:]}])[-20:]
            # a short pause at full speed, so the page and other runs get a turn; a longer one when the
            # measured system had nothing new yet (asking again at once would only load it)
            if getattr(self, "stopped_because", None):          # the source failed: stop, do not record
                self.stop_flag.set()
                break
            self.stop_flag.wait(max(0.002 if stepped else 0.5, self.seconds_per_tick - (time.time() - began)))

    def stop(self) -> None:
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=30)

    def reset(self) -> None:
        self.stop()
        with self.lock:
            if self.log_path.exists():
                self.log_path.unlink()
            self._reset_memory()
            self.stopped_because, self._failed_reads = None, 0

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and not self.stop_flag.is_set())

    def _observed_model(self) -> bool:
        """A model measured by sensors: its flows' accounting is just their amounts (the rates)."""
        try:
            m = self.model()
            return bool(m.get("sensors") or m.get("history"))
        except (OSError, ValueError):
            return False

    def hidden_flows(self) -> set[str]:
        """Flows marked hidden stand for the parts of the real world nobody has modelled yet: they
        run, but nothing about them reaches the page (which only sees what was measured)."""
        try:
            return {f["id"] for f in self.model().get("flows", []) if f.get("hidden")}
        except (OSError, ValueError):
            return set()

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            s, hide = self.series, self.hidden_flows()
            k = next((i for i, t in enumerate(s["t"]) if t > since), len(s["t"]))
            def strip(m):
                return {**m, "flows": [f for f in m.get("flows", []) if not f.get("hidden")]}
            return {"running": self.running, "t": self.t, "seconds_per_tick": self.seconds_per_tick,
                    "series": {"t": s["t"][k:],
                               **{key: {n: col[k:] for n, col in s[key].items() if n not in hide} for key in ("levels", "rates", "load")},
                               **({} if self._observed_model() else {"moved": [{f: a for f, a in m.items() if f not in hide} for m in s["moved"][k:]]})},
                    "recent": [{k: v for k, v in r.items() if k not in ("stdin", "stdout", "stderr")} for r in self.recent[-40:] if r["flow"] not in hide],
                    "eras": [{**{k: e[k] for k in ("n", "start", "label", "equations")}, **({"model": strip(e["model"])} if since == 0 else {})} for e in self.eras],
                    "length": len(s["t"]),
                    "stopped": getattr(self, "stopped_because", None),
                    "errors": [e for e in self.errors[-8:] if e.get("flow") not in hide]}

    def firing(self, n: int) -> dict | None:
        with self.lock:
            rec = next((r for r in self.recent if r["n"] == n), None)
            return None if rec and rec["flow"] in self.hidden_flows() else rec

    def stock_items(self, stock: str, limit: int = 100) -> dict:
        with self.lock:
            items = list(self.items.get(stock, {}).values())
            return {"count": len(items), "items": items[-limit:][::-1]}
