"""blockwise: the matrix method made to scale to models of hundreds of measured stocks
(docs/research/blockwise.md).

1. Sums once (gram.py): every row's regression shares the columns (levels, delayed copies of the
   levels, measured inputs), so their cross products are computed once and each row, its outside
   inflow's pieces included, is fitted from small matrices: a 230-stock week in seconds.
2. Rows (rows.py): the matrix method's row (stepwise by BIC; an outside inflow none, constant or in
   pieces), every column a candidate. A delayed copy of another stock's level (hidden.py) is an
   unmeasured stage in front of the row's stock (a load balancer's queue, pods starting).
3. Structure: the main line's conservation and reading of flows (sdlab/discovery/matrix.py finish),
   or links only (links.py: what one stock does to another takes nothing from it).
4. Candidates (VARIANTS) are judged by behaviour with the measured inputs, per stock (judge.py).
5. Blocks (blocks.py): the stocks split into weakly coupled blocks by the columns the rows chose;
   each block takes its rows from the candidate that behaves best on that block, and the joined
   model is kept if it behaves better as a whole.

A budget (opts "budget", seconds) bounds the whole; the best model so far is always returned.
Below `small` measured stocks the main line itself runs (sdlab/discovery/identify.py).
"""

from __future__ import annotations

import math
import time

import numpy as np

from ...hidden import delayed
from . import boundary
from .earned import main_line as matrix_identify
from ...matrix import finish, injected
from .blocks import blocks_of, pick_rows
from .gram import Design
from .judge import Judge
from .links import read_links
from .ratios import ratio_row, table
from .rows import fit_row, hinge, scan

DEFAULTS = {"small": 15, "budget": 600.0, "blocks": True, "delays": [1.0, 0.5]}

VARIANTS = [
    {"name": "links, stages, changing inflows", "inflow": "pieces", "read": "links", "add_gain_x": 3.0, "copies": True},
    {"name": "links, stages, constant inflows", "inflow": "constant", "read": "links", "add_gain_x": 3.0, "copies": True},
    {"name": "links, changing inflows", "inflow": "pieces", "read": "links", "add_gain_x": 3.0},
    {"name": "links, constant inflows", "inflow": "constant", "read": "links", "add_gain_x": 3.0},
    {"name": "moves, changing inflows", "inflow": "pieces"},
    {"name": "moves, constant inflows", "inflow": "constant"},
    {"name": "links, stages, constant inflows, strict", "inflow": "constant", "read": "links", "add_gain_x": 10.0, "copies": True},
    {"name": "links, constant inflows, strict", "inflow": "constant", "read": "links", "add_gain_x": 10.0},
]


def _arrays(stocks, run, opts):
    ids = [s["id"] for s in stocks]
    t = run["t"]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    inputs = [(k, np.nan_to_num(np.asarray(v, dtype=float))[1: len(t)]) for k, v in (opts.get("inputs") or {}).items() if k not in ids]
    return ids, lv, prev, dy, inputs


class Builder:
    """The columns, the candidates' rows, and any set of rows read into flows."""

    def __init__(self, stocks, run, opts, delays):
        ids, lv, prev, dy, inputs = _arrays(stocks, run, opts)
        self.stocks, self.ids, self.t, self.prev, self.dy = stocks, ids, run["t"], prev, dy
        S = len(ids)
        self.final = {s["id"] for s in stocks if s.get("final")}
        self.group = {s["id"]: s.get("group") for s in stocks}
        self.unit = {s["id"]: s.get("unit") or "" for s in stocks}
        # delayed copies of every non-final stock's level, aligned with the steps (series over t, as
        # hidden.py makes them; a step reads the copy at its start)
        self.extra = []
        cols = [prev]
        for d in delays:
            for i, sid in enumerate(ids):
                if sid in self.final or lv[i].std() == 0:
                    continue
                z = delayed(lv[i], d)
                self.extra.append({"id": f"{sid}~{d:g}", "source": sid, "delay": d, "series": z})
                cols.append(z[None, :-1])
        cols += [v[None, :] for _, v in inputs]
        self.names = ids + [e["id"] for e in self.extra] + [k for k, _ in inputs]
        self.X = np.vstack(cols)
        self.E0, self.I0 = S, S + len(self.extra)
        self.copies = {e["id"]: (e["source"], e["delay"]) for e in self.extra}
        self.design = Design(self.X, dy)
        self.opts = opts
        self.boundary = boundary.Boundary(run)

    def rows(self, v: dict) -> list[dict]:
        ids, S, T, names = self.ids, len(self.ids), self.design.T, self.names
        o = {**self.opts, **v, "add_gain": math.log(T) * v.get("add_gain_x", 1.0)}
        positive = np.zeros(len(names), bool)
        positive[self.E0:self.I0] = True
        out = []
        for s, sid in enumerate(ids):
            allowed = np.ones(len(names), bool)
            for j in range(S):
                a, b = self.group[ids[j]], self.group[sid]
                if j != s and a and b and a != b:
                    allowed[j] = False
            if sid in self.final:
                allowed[s] = False
            if not v.get("copies"):
                allowed[self.E0:self.I0] = False
            else:
                for q, e in enumerate(self.extra):          # no copy of the row's own level, nor across groups
                    a, b = self.group[e["source"]], self.group[sid]
                    if e["source"] == sid or (a and b and a != b):
                        allowed[self.E0 + q] = False
            # inside the announced boundary (boundary.py): an outside inflow (constant or pieces) only
            # where an estimated outside flow is declared; a measured input's column only where a
            # measured one is; a stock of another unit (a link from outside, a drain to outside
            # reading it) only where an estimated one is, and, read as links, any other stock's level
            # only where an estimated inflow is (a link is an inflow from outside)
            bd = self.boundary
            if not bd.inputs_ok(sid):
                allowed[self.I0:] = False
            for j in range(S):
                if j != s and ((not bd.links_ok(sid) and self.unit[ids[j]] != self.unit[sid])
                               or (v.get("read") == "links" and not bd.may(sid, "in", "estimate"))):
                    allowed[j] = False
            for q, e in enumerate(self.extra):
                src = e["source"]
                if not bd.links_ok(sid) and self.unit[src] != self.unit[sid]:
                    allowed[self.E0 + q] = False
            ro = o if bd.pieces_ok(sid) else {**o, "inflow": "none"}
            r = fit_row(self.design, self.X, s, allowed, ro, positive)
            out.append({"id": sid, "cols": r["set"], "beta": r["beta"], "pieces": r["pieces"], "cuts": r["cuts"], "rss": r["rss"], "p": r["p"],
                        "trust_receivers": v.get("trust_receivers", True)})
        return out

    def hinged(self, raw: list[dict]) -> list[dict]:
        """The rows again, each one that two floored rates of its own columns explain clearly better
        (rows.hinge) carrying them; rows with stages stay as they are."""
        out = []
        for s, r in enumerate(raw):
            cols = [j for j in r["cols"] if not (self.E0 <= j < self.I0)]
            h = None
            if len(cols) == len(r["cols"]) and self.ids[s] not in self.final:
                h = hinge(self.X, self.dy[s], s, cols, r["rss"], r["p"])
            out.append({**r, "hinge": h} if h else r)
        return out

    def ratioed(self, raw: list[dict]) -> list[dict]:
        """The rows again, each with ratio columns (ratios.py) where they pay (rows with floored rates
        stay as they are); an outside inflow's pieces are measured again beside them."""
        out, T = [], self.design.T
        for s, r in enumerate(raw):
            if r.get("hinge") or not r["cols"]:
                out.append(r)
                continue
            y = self.dy[s]
            q = ratio_row(self.X, y, s, r["cols"], set(range(self.E0)), r["cuts"], math.log(T) * 3)
            if q is None:
                out.append(r)
                continue
            cols = [c for c in q["cols"] if not isinstance(c, tuple)]
            beta = np.array([b for c, b in zip(q["cols"], q["beta"]) if not isinstance(c, tuple)])
            ratios = [(c[0], c[1], float(b)) for c, b in zip(q["cols"], q["beta"]) if isinstance(c, tuple)]
            res = y - (beta @ self.X[cols] if cols else 0.0) - sum(k * self.X[a] / self.X[m] for a, m, k in ratios)
            c = r["cuts"]
            pieces = [{"a": a, "b": b, "w": b - a, "v": float(res[a:b].mean())} for a, b in zip(c[:-1], c[1:])] if c else []
            out.append({**r, "cols": cols, "beta": beta, "ratios": ratios, "pieces": pieces})
        return out

    def lag1(self, name: str) -> np.ndarray:
        """What a column read during the step before each time (aligned with t): a stage fed by it
        holds that at the time."""
        x = self.X[self.names.index(name)]                         # one value per step (t[0] -> t[1], ...)
        return np.concatenate([x[:1], x])

    def _pieces(self, r):
        t = self.t
        return [{"from": t[p["a"] + 1], "to": t[p["b"]], "value": p["v"]} for p in r["pieces"]]

    def flows(self, raw: list[dict], read: str = "main") -> tuple[list[dict], dict]:
        """(flows, inferred levels of the found unmeasured stages, as arrays aligned with t)."""
        ids, t, X, names, T = self.ids, self.t, self.X, self.names, self.design.T
        series = {e["id"]: e["series"] for e in self.extra}
        if read == "links":
            rows = []
            for r in raw:
                if r.get("hinge"):
                    h = r["hinge"]
                    rows.append({"id": r["id"], "coef": {}, "inflow": [],
                                 "hinge": [(float(h[k][0]), {names[j]: float(b) for j, b in zip(h["cols"], h[k][1:])}) for k in ("up", "down")]})
                else:
                    rows.append({"id": r["id"], "coef": {names[j]: float(b) for j, b in zip(r["cols"], r["beta"])}, "inflow": self._pieces(r),
                                 "ratios": [(names[a], names[m], k, table(X[m])) for a, m, k in r.get("ratios") or []]})
            means = {n: float(X[j].mean()) for j, n in enumerate(names)}
            flows, stages = read_links(rows, ids, means, set(names[self.I0:]), self.copies, self.unit)
            inferred = {h: sum(sc * (series[c] if kind == "copy" else self.lag1(c)) for c, kind, sc in parts) for h, parts in stages.items()}
            return flows, inferred
        lt = math.log(T)
        rows = []
        for r in raw:                                              # fresh copies: conservation changes rows in place
            rows.append({"id": r["id"], "coefL": [{names[j]: float(b) for j, b in zip(r["cols"], r["beta"])}],
                         "X": X[r["cols"]] if r["cols"] else X[:0], "col": [(j, -1) for j in r["cols"]], "set": list(range(len(r["cols"]))),
                         "beta": np.array(r["beta"]), "inflow": self._pieces(r),
                         "cuts": r["cuts"], "rss": r["rss"], "p": r["p"], "trust_receivers": r["trust_receivers"]})
        used = {names[j] for r in raw for j in r["cols"] if self.E0 <= j < self.I0}
        stride = self.opts.get("scan_stride", 1)
        bicf = lambda rss, p: T * math.log(max(rss, 1e-12) / T) + p * lt  # noqa: E731
        ctx = {"stocks": self.stocks, "ids": ids, "t": t, "final": self.final, "unit": self.unit, "prev": self.prev, "dy": self.dy,
               "cfg": np.zeros(T, dtype=int), "L": 1, "labels": [None], "conf": None, "bic": bicf, "log_t": lt, "T": T,
               "at": lambda k: t[k + 1], "extras": [], "names": names, "columns": X, "inputs": names[self.I0:]}
        # every copy is passed (read_flows indexes their levels by position); only the chosen ones make stages
        extra = [{"id": e["id"], "source": e["source"], "delay": e["delay"], "rows": set()} for e in self.extra] if used else []
        out = finish(rows, ctx, {"scan": lambda r, phase: scan(r, 1.0, 5, stride), **({"extra": extra} if extra else {})})
        inferred = {}
        for f in out["flows"]:
            inf = f.get("inferred")
            if inf:
                inferred[inf["id"]] = inf["scale"] * series[inf["copy"]]
        return out["flows"], inferred


def graph(raw: list[dict], b: Builder) -> dict[str, list[str]]:
    """Each stock's row: the other stocks whose levels (or copies) it chose."""
    out = {}
    for r in raw:
        js = []
        for j in r["cols"]:
            n = b.names[j]
            if j < b.E0 and n != r["id"]:
                js.append(n)
            elif b.E0 <= j < b.I0:
                js.append(b.copies[n][0])
        out[r["id"]] = js
    return out


def choose(cands: list[dict]) -> dict:
    """The candidate that behaves best: its error in the data's own units (what the goal's skill
    weighs: the large stocks' misses count most) plus its error with every stock weighed alike (no
    small stock running away unseen). Each is relative to how far the data moved (0 = perfect, 1 =
    no better than assuming nothing changes)."""
    ok = [c for c in cands if math.isfinite(c["norm"]) and math.isfinite(c["error"])]
    return min(ok, key=lambda c: c["error"] + c["norm"]) if ok else cands[0]


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    o = {**DEFAULTS, **{k: opts.pop(k) for k in list(opts) if k in DEFAULTS}}
    began = time.perf_counter()
    if len(stocks) < o["small"]:
        r = matrix_identify(stocks, run, opts)
        r["method"] = "blockwise (the main line: a small model)"
        return r
    bd = boundary.Boundary(run)
    deadline = began + float(o["budget"])
    t = run["t"]
    if len(t) < 21:
        return {"flows": [], "note": "Too few steps."}
    T = len(t) - 1
    stride = max(1, T // 3000)                                     # pieces found on means of `stride` steps
    builder = Builder(stocks, run, {**opts, "scan_stride": stride}, o["delays"])
    ids = builder.ids
    judge = Judge(ids, t, run["levels"], opts.get("injections"), opts.get("inputs"))
    tried, cands = [], []
    for v in opts.pop("variants", None) or VARIANTS:
        if time.perf_counter() > deadline and cands:
            tried.append({"name": v["name"], "error": None, "note": "not run: out of budget"})
            continue
        b0 = time.perf_counter()
        raw = builder.rows(v)
        flows, inferred = builder.flows(raw, v.get("read", "main"))
        flows = _inside(flows, stocks, run, opts, bd)
        per = judge.per_stock(flows, inferred)
        cands.append({"name": v["name"], "read": v.get("read", "main"), "raw": raw, "flows": flows, "inferred": inferred,
                      "per": per, "per_raw": judge.raw, "error": float(judge.raw.sum()), "norm": float(per.sum())})
        tried.append({"name": v["name"], "error": cands[-1]["error"], "norm": cands[-1]["norm"], "seconds": round(time.perf_counter() - b0, 1), "flows": len(flows)})
    # refinements of the two best candidates read as links: floored rates (rows.hinge), ratio
    # columns (ratios.py), and both
    steps = {"floored rates": lambda raw: builder.hinged(raw), "ratios": lambda raw: builder.ratioed(raw),
             "floored rates, ratios": lambda raw: builder.ratioed(builder.hinged(raw))}
    for c in sorted([c for c in cands if c["read"] == "links"], key=lambda c: c["error"] + c["norm"])[:2]:
        for label, step in steps.items():
            if time.perf_counter() > deadline:
                break
            b0 = time.perf_counter()
            raw = step(c["raw"])
            if not any(r.get("hinge") or r.get("ratios") for r in raw):
                continue
            flows, inferred = builder.flows(raw, "links")
            flows = _inside(flows, stocks, run, opts, bd)
            per = judge.per_stock(flows, inferred)
            cands.append({"name": f"{c['name']}, {label}", "read": "links", "raw": raw, "flows": flows, "inferred": inferred,
                          "per": per, "per_raw": judge.raw, "error": float(judge.raw.sum()), "norm": float(per.sum())})
            tried.append({"name": cands[-1]["name"], "error": cands[-1]["error"], "norm": cands[-1]["norm"], "seconds": round(time.perf_counter() - b0, 1),
                          "flows": len(flows), "floored": sum(1 for r in raw if r.get("hinge")), "ratios": sum(1 for r in raw if r.get("ratios"))})
    best = choose(cands)
    result = {"flows": best["flows"], "inferred_levels": best["inferred"], "chosen": best["name"], "tried": tried, "method": "blockwise"}
    if o["blocks"] and len(cands) > 1 and time.perf_counter() < deadline:
        # the join reads its rows as the best candidate reads them, from the candidates read the same way
        same = [c for c in cands if c["read"] == best["read"]]
        bl = blocks_of(ids, graph(best["raw"], builder), builder.dy)
        choice, desc = pick_rows(same, bl, ids)
        result["blocks"] = [sorted(b) for b in bl]
        if len(set(choice.values())) > 1:
            raw = [same[choice[sid]]["raw"][s] for s, sid in enumerate(ids)]
            flows, inferred = builder.flows(raw, best["read"])
            flows = _inside(flows, stocks, run, opts, bd)
            per = judge.per_stock(flows, inferred)
            joined = {"name": f"blocks: {desc}", "flows": flows, "inferred": inferred, "error": float(judge.raw.sum()), "norm": float(per.sum())}
            tried.append({"name": joined["name"], "error": joined["error"], "norm": joined["norm"], "flows": len(flows)})
            if choose([best, joined]) is joined:
                result.update(flows=flows, inferred_levels=inferred, chosen=joined["name"])
    if not result["inferred_levels"]:
        result.pop("inferred_levels")
    if result.get("inferred_levels"):                              # (arrays while judging; lists for the page)
        result["inferred_levels"] = {h: np.asarray(v, dtype=float).tolist() for h, v in result["inferred_levels"].items()}
    result["seconds"] = round(time.perf_counter() - began, 1)
    return result


def _inside(flows: list[dict], stocks: list[dict], run: dict, opts: dict, bd: boundary.Boundary) -> list[dict]:
    """A candidate's flows kept inside a declared boundary before it is judged (boundary.py's guard:
    nothing when it is already inside, the usual case after the rows' own restrictions)."""
    if not bd.declared or not flows:
        return flows
    return boundary.apply({"flows": flows}, stocks, run, opts, final=False)["flows"]


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py,
    docs/research/declared-boundary.md: the guard and moves where one is declared, each outside flow
    priced as a boundary claim where none is)."""
    from .eiv import apply

    return boundary.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
