"""Copied from sdlab/discovery/numopt.py at commit aac65a0 (the pinned shared library); the one
change: the run's measured inputs (opts["inputs"]) reach every model the search runs (the
objective, the probes of what a flow moves, the profiled inflows) and the judge that decides
whether the searched model is kept, as identify() judges its candidates. The shared copy ran and
judged every model with the inputs missing, so a rate reading one saw nothing.

Numerical optimisation of a whole model's numbers on multi-step error, with forward selection of
optional terms (effects, co-flows, hidden stocks) and the optimiser in the loop.

    flows, note = search(stocks, run, base_flows, "fd", opts)

1. The base is the matrix method's flows, with its numbers (the rates are not fitted first: fitted
   to a misread structure, they make the structure that replaces it harder to reach).
2. Rounds of forward selection: every optional term the base allows (terms.py) is screened by one
   Gauss-Newton step on short horizons (its own numbers and its flow's rates, Jacobian by finite
   differences: the same cheap screen for every optimiser); the best `top` are fitted with the
   chosen optimiser (their numbers and their flow's rates, the rest held), and the best fit joins
   the model if its error falls by more than `price` x its net numbers (its own, less those of the
   flows it replaces; a share of the error).
3. Every number is fitted again together.

Outside inflows (`inflows`):
  - "fixed": held as the matrix method found them;
  - "coarse": each becomes coarse pieces (its found values averaged over equal blocks of the run) with
    a free factor per block, fitted with the rest under a price on the factors' roughness and their
    mean log (the output-error experiment found free inflows take over the internal flows' job);
  - "profile": the found pieces of every stock a chosen term touches are re-measured at every
    evaluation as what that stock's one-step change leaves over on average in each piece (so a term
    that changes a stock's balance, such as an effect replacing a link, is judged with the inflow
    that balance implies, not the one the matrix's structure implied).
"""

from __future__ import annotations

import math
import time

import numpy as np

from ...optimisers import minimise
from .outerror import Objective
from ...simulate import Model, levels_array
from ...terms import Config, Term, _rate_k, output_flows

DEFAULTS = {"horizons": (5, 20, 100), "screen_horizons": (5, 20), "starts": 80, "rounds": 3, "top": 5, "price": 0.02,
            "term_budget": 60, "full_budget": 300, "bo_max": 8, "effects": True, "coflows": True, "hidden": False,
            "inflows": "fixed", "inflow_penalty": 1.0, "coarse": None}


class _Fitter:
    def __init__(self, stocks, run, base, method, opts, inputs=None):
        self.ids = [s["id"] for s in stocks]
        self.inputs = {"t": list(run["t"]), "values": inputs} if inputs else None
        self.base, self.method, self.o = base, method, opts
        self.run = run
        self.obj = Objective(self.ids, run["t"], run["levels"], opts["horizons"], opts["starts"], inputs=inputs)
        self.screen = Objective(self.ids, run["t"], run["levels"], opts["screen_horizons"], opts["starts"], inputs=inputs)
        A = levels_array(run["levels"], self.ids)
        tt = np.asarray(run["t"], dtype=float)
        self.amount = {}
        for i, f in enumerate(base):
            if f.get("from") in self.ids and not f.get("inflow"):
                probe = Model([{**f, "to": None}], self.ids, inputs=self.inputs)
                s = self.ids.index(f["from"])
                self.amount[i] = float(np.mean(A[s, :-1] - probe.step(A[:, :-1], tt[1:])[s]))
        self.prev, self.dy, self.t1 = A[:, :-1], np.diff(A, axis=1), tt[1:]
        top = {i: float(A[k].max()) for k, i in enumerate(self.ids)}
        self.data = {"t": run["t"], "levels": run["levels"],
                     "per_scale": lambda i, j: 2 * top.get(j, 1.0) / max(1e-6, self.amount.get(i, 1.0))}
        self.opt_evals = 0
        self.screen_evals = 0
        self.penalty_w = 0.0

    def start(self) -> tuple[Config, np.ndarray, float]:
        """The base as a configuration (with its outside inflows' factors when they are free), and
        its error."""
        terms: tuple[Term, ...] = ()
        if self.o["inflows"] == "coarse":
            terms = tuple(Term("inflow", i) for i, f in enumerate(self.base)
                          if f.get("inflow") or (not f.get("from") and not f.get("driver") and (f.get("rate") or {}).get("form") == "constant"))
        cfg = self.config(terms)
        c = self.cost(cfg, cfg.x0)
        if self.o["inflows"] == "coarse":
            self.penalty_w = math.sqrt(self.o["inflow_penalty"] * c / max(1, sum(s.kind == "inflow" for s in cfg.slots)))
        return cfg, cfg.x0, c

    def config(self, terms, values=None) -> Config:
        return Config(self.base, terms, self.data, values, self.o["coarse"] or int(np.clip(len(self.run["t"]) // 100, 8, 40)))

    def residuals(self, cfg: Config, x_full: np.ndarray, idx: np.ndarray, obj: Objective):
        # free inflows are priced: a block's factor against its neighbour's (roughness) and each
        # inflow's mean log factor (moving away from the level found)
        hosts: dict[int, list[int]] = {}
        for i, s in enumerate(cfg.slots):
            if s.kind == "inflow":
                hosts.setdefault(s.host, []).append(i)
        groups = [np.array(v) for v in hosts.values()]
        profile = self.profiled(cfg) if self.o["inflows"] == "profile" else None

        def res(xs):
            x = x_full.copy()
            x[idx] = xs
            cfg.put(x)
            if profile:
                self.remeasure(cfg, profile)
            r = obj.residuals(cfg.flows, cfg.hidden)
            if groups:
                pen = []
                for g in groups:
                    lf = np.log(np.maximum(1e-6, x[g]))
                    pen.append(np.diff(lf))
                    pen.append([lf.mean() * math.sqrt(len(g))])
                r = np.append(r, self.penalty_w * np.concatenate(pen))
            return r
        return res

    def profiled(self, cfg: Config) -> list[tuple]:
        """The found outside inflows of the stocks cfg's terms touch: (flow, stock row, sign, piece
        of each step, steps per piece)."""
        touched = cfg.touched(cfg.terms, used=False)
        out = []
        for f in cfg.flows:
            if not f.get("inflow"):
                continue
            s = f.get("to") if f.get("to") in self.ids else f.get("from")
            if s not in touched or s not in self.ids:
                continue
            segs = f["inflow"]
            piece = np.full(len(self.t1), len(segs))
            for i in range(len(segs) - 1, -1, -1):                 # the first segment that covers a time
                piece[(self.t1 >= segs[i]["from"]) & (self.t1 <= segs[i]["to"])] = i
            count = np.bincount(piece, minlength=len(segs) + 1)[:-1]
            out.append((f, self.ids.index(s), 1.0 if f.get("to") == s else -1.0, piece, count))
        return out

    def remeasure(self, cfg: Config, profile: list[tuple]) -> None:
        own = [f for f in cfg.flows if not f.get("inflow")]
        ids = self.ids + [h["id"] for h in cfg.hidden]
        prev = self.prev if not cfg.hidden else np.vstack([self.prev, np.zeros((len(cfg.hidden), self.prev.shape[1]))])
        nxt = Model(own, ids, inputs=self.inputs).step(prev, self.t1)[: len(self.ids)]
        res = self.dy - (nxt - self.prev)
        for f, s, sign, piece, count in profile:
            total = np.bincount(piece, weights=res[s], minlength=len(count) + 1)[:-1]
            for g, c, v in zip(f["inflow"], count, total):
                if c:
                    g["value"] = float(max(0.0, sign * v / c))

    def cost(self, cfg, x, obj=None) -> float:
        r = self.residuals(cfg, x, np.arange(len(x)), obj or self.obj)(x[np.arange(len(x))])
        return float(r @ r)

    def fit(self, cfg: Config, x: np.ndarray, idx: np.ndarray, budget: int) -> tuple[np.ndarray, float]:
        if not len(idx) or (self.method == "bo" and len(idx) > self.o["bo_max"]):
            return x, self.cost(cfg, x)
        res = self.residuals(cfg, x, idx, self.obj)
        r = minimise(self.method, res, x[idx], cfg.lo[idx], cfg.hi[idx], budget)
        self.opt_evals += r.evals
        out = x.copy()
        out[idx] = r.x
        return out, r.cost

    def gauss_newton(self, cfg: Config, x: np.ndarray, idx: np.ndarray) -> float:
        """The screen's cost after one damped Gauss-Newton step in the numbers idx."""
        res = self.residuals(cfg, x, idx, self.screen)
        z = x[idx]
        r0 = res(z)
        h = 1e-3 * np.maximum(np.abs(z), 0.1 * (cfg.hi[idx] - cfg.lo[idx]))
        h = np.where(z + h <= cfg.hi[idx], h, -h)
        J = np.empty((len(r0), len(z)))
        for q in range(len(z)):
            e = np.zeros(len(z))
            e[q] = h[q]
            J[:, q] = (res(z + e) - r0) / h[q]
        self.screen_evals += len(z) + 1
        G = J.T @ J
        step = -np.linalg.solve(G + 1e-6 * np.trace(G) / len(z) * np.eye(len(z)) + 1e-12 * np.eye(len(z)), J.T @ r0)
        z1 = np.clip(z + step, cfg.lo[idx], cfg.hi[idx])
        r1 = r0 + J @ (z1 - z)
        return float(r1 @ r1)

    def candidates(self, cfg: Config) -> list[Term]:
        have = {t.name for t in cfg.terms}
        gone = {i for t in cfg.terms for i in t.drop}
        base, ids = self.base, self.ids
        out = []
        for i, f in enumerate(base):
            if i in gone or i not in self.amount:
                continue
            a = f["from"]
            for j in ids:
                if j == a:
                    continue
                if self.o["effects"]:
                    links = tuple(k for k, g in enumerate(base) if k not in gone and g.get("driver") == j and k != i
                                  and ((g.get("from") == a and not g.get("to")) or (f.get("to") and g.get("to") == f["to"] and not g.get("from"))))
                    for drop in ({(), links} if links else {()}):
                        out.append(Term("effect", i, j, drop))
                if self.o["coflows"] and j != f.get("to"):
                    k_f = _rate_k(f)
                    links = [k for k, g in enumerate(base) if k not in gone and k != i and g.get("from") == j and not g.get("to") and g.get("driver") == a]
                    for k in links:
                        out.append(Term("coflow", i, j, (k,), _rate_k(base[k]) / k_f if k_f else 0.0))
                    out.append(Term("coflow", i, j))
            if self.o["hidden"] and f.get("to") in ids and not f.get("driver"):
                out.append(Term("hidden", i))
        return [t for t in out if t.name not in have and not (set(t.drop) & gone)]


_NEUTRAL = {"effect": 1.0, "coflow": 0.0}


def _numbers(f: dict) -> int:
    r = f.get("rate") or {}
    return len(r.get("terms") or []) if r.get("form") == "linear" else 1


def search(stocks: list[dict], run: dict, base: list[dict], method: str, opts: dict | None = None,
           inputs: dict | None = None) -> tuple[list[dict], dict]:
    """inputs: measured inputs, {name: value per step aligned with t}, that the flows may read."""
    o = {**DEFAULTS, **(opts or {})}
    began = time.time()
    F = _Fitter(stocks, run, base, method, o, inputs)
    cfg, x, c_start = F.start()
    trace = [("start", c_start)]
    c = c_start
    added = []
    for _ in range(o["rounds"]):
        cands = F.candidates(cfg)
        if not cands:
            break
        values = cfg.values(x)
        cur_screen = F.cost(cfg, x, F.screen)
        scored = []
        for tm in cands:
            cc = F.config(cfg.terms + (tm,), values)
            idx = cc.index(cc.term_slots(tm))
            scored.append((F.gauss_newton(cc, cc.x0, idx), tm))
        scored.sort(key=lambda s: s[0])
        best = None
        for sc, tm in scored[: o["top"]]:
            if sc >= cur_screen:
                continue
            cc = F.config(cfg.terms + (tm,), values)
            idx = cc.index(cc.term_slots(tm))
            x1, c1 = F.fit(cc, cc.x0, idx, o["term_budget"])
            own = cc.index([tm.name])
            p = len(own) - sum(_numbers(F.base[i]) for i in tm.drop)
            if not (c1 < c * (1 - o["price"] * p) and (best is None or c1 < best[1])):
                continue
            # the fall must come from the term, not from the rates refitted beside it: with the
            # term's own numbers set to doing nothing (and nothing dropped) the fit must be worse
            xn = x1.copy()
            xn[own] = [_NEUTRAL.get(cc.slots[i].kind, cc.slots[i].lo) for i in own]
            if not tm.drop and F.cost(cc, xn) <= c1 * (1 + o["price"] * max(1, p)):
                continue
            best = (cc, c1, x1, tm)
        if best is None:
            break
        cfg, c, x, tm = best
        added.append(tm.name)
        trace.append((tm.name, c))
    x, c = F.fit(cfg, x, np.arange(len(x)), o["full_budget"])
    trace.append(("all", c))
    cfg.put(x)
    note = {"method": method, "terms": added, "trace": [(n, round(v, 5)) for n, v in trace], "evals": F.opt_evals,
            "screen_evals": F.screen_evals, "objective_evals": F.obj.evals + F.screen.evals, "seconds": round(time.time() - began, 2),
            "values": {s.name: round(float(v), 5) for s, v in zip(cfg.slots, x) if s.kind != "rate"}}
    return output_flows(cfg), note


def identify_with(method: str, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """identify() (the matrix method, candidates chosen by behaviour), then search() from its
    model; the searched model is kept only if identify()'s judge prefers it."""
    from ...identify import judge
    from . import boundary
    from .earned import main_line as identify

    opts = dict(opts or {})
    nopts = {**(opts.pop("numopt", None) or {})}
    r = identify(stocks, run, opts)
    if not r.get("flows"):
        return r
    inputs = opts.get("inputs")
    flows, note = search(stocks, run, r["flows"], method, nopts, inputs)
    # (the declared boundary, boundary.py) the search adds effects, co-flows and hidden stocks on the
    # base's flows, never an outside flow, and the base is inside the boundary already (earned.py);
    # the guard still sees the searched model before the judge, so no undeclared outside flow is kept
    if boundary.Boundary(run).declared:
        flows = boundary.apply({"flows": flows}, stocks, run, opts, final=False)["flows"]
    e0, e1 = judge(r["flows"], stocks, run, inputs=inputs), judge(flows, stocks, run, inputs=inputs)
    note["judge"] = (round(e0, 5), round(e1, 5))
    kept = e1 < e0
    if kept:
        r = {**r, "flows": flows}
    # the bench records `chosen`: what was kept, and what the search cost
    r["chosen"] = (f"{r.get('chosen')} | numopt {method} {'kept' if kept else 'rejected'}" + (f" + {', '.join(note['terms'])}" if note["terms"] else "")
                   + f" | evals {note['evals']} screen {note['screen_evals']} {note['seconds']}s")
    r["numopt"] = note
    return r
