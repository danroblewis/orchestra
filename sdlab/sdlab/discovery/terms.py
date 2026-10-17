"""A found model with optional terms, as a vector of numbers an optimiser can move.

The base is a list of flows (the matrix method's result). A term adds structure to it:

  - effect:  a flow's rate multiplied by a table curve of another stock's level (five points at the
             stock's observed quantiles; the middle one fixed at 1, so the flow's own number keeps
             the scale);
  - coflow:  a flow uses up `per` of another stock for each unit it moves (and shares what that stock
             holds with its other takers);
  - hidden:  a move A -> B waits in a stock nobody measures, which drains 1/delay a step;
  - inflow:  an outside inflow as coarse pieces (its found values averaged over equal blocks of the
             run), each block's value times a free factor.

A term may drop base flows it replaces (a co-flow replaces the link "the used stock drains faster
when the flow's driver is high"; an effect replaces links its stock drives into the flow's ends).
Every number has a name that survives adding terms (so a fit carries over), a starting value, a box
(lo, hi) every optimiser respects, and a kind (rate, effect, coflow, hidden, inflow).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Term:
    kind: str                       # "effect", "coflow", "hidden", "inflow"
    flow: int                       # index of the base flow it acts on
    stock: str | None = None        # the stock an effect reads or a co-flow uses
    drop: tuple[int, ...] = ()      # base flows it replaces
    start: float | None = None      # a co-flow's starting `per`

    @property
    def name(self) -> str:
        return f"{self.kind}:{self.flow}:{self.stock or ''}" + (f"-{'.'.join(map(str, self.drop))}" if self.drop else "")


@dataclass
class Slot:
    name: str
    kind: str
    host: int | None                # base flow it belongs to
    lo: float
    hi: float
    places: list = field(default_factory=list)      # (dict or list, key) places that hold it
    transform: str = ""             # "invdelay": the place holds 1 / exp(value)

    def put(self, v: float) -> None:
        w = 1.0 / math.exp(v) if self.transform == "invdelay" else v
        for d, k in self.places:
            d[k] = float(w)


def _rate_k(f: dict) -> float:
    r = f.get("rate") or {}
    if r.get("form") == "proportional":
        return float(r.get("k") or 0)
    if r.get("form") == "linear":
        return float((r.get("terms") or [{}])[0].get("k") or 0)
    return 0.0


def flow_label(f: dict) -> str:
    return f"{f.get('from')}>{f.get('to')}" + (f" by {f['driver']}" if f.get("driver") else "")


class Config:
    """Base flows plus terms, materialised once; `put(x)` writes numbers in place."""

    def __init__(self, base: list[dict], terms: tuple[Term, ...], data: dict, values: dict[str, float] | None = None, coarse: int = 8):
        self.base, self.terms, self.data = base, terms, data
        flows = copy.deepcopy(base)
        self.slots: list[Slot] = []
        self.hidden: list[dict] = []
        dropped = {i for tm in terms for i in tm.drop}
        rate_slots: dict[str, Slot] = {}
        for i, f in enumerate(flows):
            if i in dropped or f.get("inflow") or f.get("_hidden_out"):
                continue
            seen = set()
            for r in ([g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]):
                if id(r) in seen:
                    continue
                seen.add(id(r))
                vals = [(r, "k")] if r.get("form") == "proportional" else [(x, "k") for x in r.get("terms") or []] if r.get("form") == "linear" else []
                for q, (d, key) in enumerate(vals):
                    v = float(d.get(key) or 0.0)
                    name = f"rate:{i}:{q}:{round(v, 6)}"          # eras that share a number share the slot
                    s = rate_slots.get(name) or Slot(name, "rate", i, 0.0, max(3 * abs(v), 1e-3))
                    s.places.append((d, key))
                    rate_slots[name] = s
        self.slots.extend(rate_slots.values())
        self._starts: dict[str, float] = {s.name: float(s.places[0][0][s.places[0][1]]) for s in self.slots}
        for tm in terms:
            getattr(self, "_" + tm.kind)(flows, tm, coarse)
        self.flows = [f for i, f in enumerate(flows) if i not in dropped]
        values = values or {}
        self.x0 = np.array([float(np.clip(values.get(s.name, self._starts[s.name]), s.lo, s.hi)) for s in self.slots])
        self.lo = np.array([s.lo for s in self.slots])
        self.hi = np.array([s.hi for s in self.slots])

    # -- terms --
    def _effect(self, flows, tm: Term, coarse) -> None:
        x = np.asarray(self.data["levels"][tm.stock], dtype=float)
        knots = np.unique(np.quantile(x, [0, 0.25, 0.5, 0.75, 1.0]))
        if len(knots) < 2:
            knots = np.array([x.min(), x.min() + 1])
        anchor = len(knots) // 2
        # flat, or (replacing links the stock drives into the flow's ends) the curve that gives the
        # flow, at its source's mean level, what it carried plus what the links carried
        y = np.ones(len(knots))
        host = self.base[tm.flow]
        k = _rate_k(host)
        links = [_rate_k(self.base[i]) for i in tm.drop]
        if links and k > 0 and host.get("from") in self.data["levels"]:
            base = k * float(np.mean(self.data["levels"][host["from"]]))
            kl = float(np.mean(links))
            y = np.clip((base + kl * knots) / max(1e-9, base + kl * knots[anchor]), 0.0, 5.0)
        pts = [[float(a), float(v)] for a, v in zip(knots, y)]
        flows[tm.flow].setdefault("effects", []).append({"stock": tm.stock, "shape": "table", "points": pts})
        for q, p in enumerate(pts):
            if q != anchor:
                name = f"{tm.name}:{q}"
                self.slots.append(Slot(name, "effect", tm.flow, 0.0, 5.0, [(p, 1)]))
                self._starts[name] = float(p[1])

    def _coflow(self, flows, tm: Term, coarse) -> None:
        u = {"stock": tm.stock, "per": float(tm.start or 0.0)}
        flows[tm.flow].setdefault("uses", []).append(u)
        hi = max(3 * (tm.start or 0.0), self.data["per_scale"](tm.flow, tm.stock))
        self.slots.append(Slot(tm.name, "coflow", tm.flow, 0.0, hi, [(u, "per")]))
        self._starts[tm.name] = float(tm.start or 0.0)

    def _hidden(self, flows, tm: Term, coarse) -> None:
        f = flows[tm.flow]
        hid = f"hidden {f['from']}>{f['to']}"
        out = {"from": hid, "to": f["to"], "rate": {"form": "proportional", "stock": hid, "k": 0.2}, "_hidden_out": True}
        f["to"] = hid
        flows.append(out)
        self.hidden.append({"id": hid, "into": f, "out": out, "delay": 5.0})
        hi = math.log(max(2.0, min(200.0, len(self.data["t"]) / 8)))
        self.slots.append(Slot(tm.name, "hidden", tm.flow, 0.0, hi, [(out["rate"], "k")], "invdelay"))
        self._starts[tm.name] = math.log(5.0)

    def _inflow(self, flows, tm: Term, coarse) -> None:
        """The found pieces averaged over `coarse` equal blocks of the run (so they no longer replay
        the data's every change), each block's value times a free factor."""
        f = flows[tm.flow]
        t = self.data["t"]
        t0, t1 = float(t[0]), float(t[-1])
        edges = np.linspace(t0, t1 + 1, coarse + 1)
        segs = f.get("inflow") or [{"from": t0, "to": t1, "value": float(f["rate"].get("value") or 0)}]
        new = []
        for b in range(coarse):
            a, z = edges[b], edges[b + 1] - 1e-9
            w = v = 0.0
            for g in segs:
                lo, hi = max(a, g["from"]), min(z, g["to"])
                if lo <= hi:
                    w += hi - lo + 1
                    v += (hi - lo + 1) * float(g["value"])
            base = v / w if w else 0.0
            new.append({"from": a, "to": z, "value": base, "_base": base, "_block": b})
        f["inflow"] = new
        f["rate"] = {"form": "constant", "value": float(np.mean([g["value"] for g in new]))}
        for b, g in enumerate(new):
            name = f"{tm.name}:{b}"
            self.slots.append(_ScaleSlot(name, "inflow", tm.flow, 0.1, 10.0, [g]))
            self._starts[name] = 1.0

    # -- numbers --
    def put(self, x: np.ndarray) -> None:
        for s, v in zip(self.slots, x):
            s.put(v)
        for h in self.hidden:
            h["delay"] = 1.0 / max(1e-9, h["out"]["rate"]["k"])

    def values(self, x: np.ndarray) -> dict[str, float]:
        return {s.name: float(v) for s, v in zip(self.slots, x)}

    def index(self, names) -> np.ndarray:
        names = set(names)
        return np.array([i for i, s in enumerate(self.slots) if s.name in names or any(s.name.startswith(n + ":") for n in names)], dtype=int)

    def host_slots(self, flow: int) -> list[str]:
        return [s.name for s in self.slots if s.kind == "rate" and s.host == flow]

    def touched(self, terms, used: bool = True) -> set:
        """The stocks whose balance terms change: their flow's ends, the ends of the flows they
        replace, and (with `used`) a co-flow's stock, unless it replaces a link out of it one for
        one."""
        b = self.base
        out = set()
        for tm in terms:
            out |= {b[tm.flow].get("from"), b[tm.flow].get("to")}
            out |= {b[i].get(k) for i in tm.drop for k in ("from", "to") if not (tm.kind == "coflow" and b[i].get(k) == tm.stock)}
            if tm.kind == "coflow" and used:
                out.add(tm.stock)
        out.discard(None)
        return out

    def term_slots(self, tm: Term) -> list[str]:
        """What a fit of a term moves: its own numbers, the rates of every flow in or out of a
        stock it touches, and those stocks' outside inflow factors (if any)."""
        b = self.base
        touched = self.touched([tm])
        near = lambda i: b[i].get("from") in touched or b[i].get("to") in touched  # noqa: E731
        return [tm.name] + [s.name for s in self.slots if s.kind in ("rate", "inflow") and s.host is not None and near(s.host)]


class _ScaleSlot(Slot):
    """An inflow block's factor: each of its segments' found value times the factor."""

    def __init__(self, name, kind, host, lo, hi, segs):
        super().__init__(name, kind, host, lo, hi)
        self.segs = segs

    def put(self, v: float) -> None:
        for g in self.segs:
            g["value"] = g["_base"] * float(v)


def output_flows(cfg: Config) -> list[dict]:
    """The model as SD Lab flows a grader can run on the measured stocks: a hidden stock cannot be
    started from a level nobody measured, so the move it delays is given back as a direct move that
    names the delay (`via`)."""
    out = []
    for f in cfg.flows:
        if f.get("_hidden_out"):
            continue
        g = {k: v for k, v in f.items() if not k.startswith("_")}
        if g.get("inflow"):
            g["inflow"] = [{k: v for k, v in s.items() if not k.startswith("_")} for s in g["inflow"]]
        h = next((h for h in cfg.hidden if h["into"] is f), None)
        if h:
            g["to"] = h["out"]["to"]
            g["via"] = {"hidden": True, "delay": round(h["delay"], 2)}
        out.append(g)
    return out
