"""The declared boundary (docs/research/declared-boundary.md): outside flows only where the case says the
system meets its environment.

Copied from matrix/boundary.py at 723f72c (HIDDEN_PRICE 0) for latent_eras (strategies are isolated:
CLAUDE.md invariant 11); this copy changes only here. Its own addition: GUARD_FITS, which bounds the
guard's refits on large models (a flow outside the boundary past the budget is just dropped).

A case may announce its boundary (Sterman's model-boundary chart): run["boundary"] = {stock: {"in":
[kinds], "out": [kinds]}} with run["boundary_declared"] = True, each kind "measured" (driven by a
measured input series) or "estimate" (exists; its form and rate are to be estimated). A stock not
listed has no outside flow. Nothing else about the truth is announced. Outside flows are a modelling
decision, not something discovery may invent, so:

- declared: an outside flow is allowed only on a declared stock and side, and of a declared kind (a
  "measured" side is fed by a flow that reads a measured input; an "estimate" side by an estimated
  form: a constant, pieces, a drain, a link). Everything else must be a flow between stocks, and
  unexplained wiggle is noise. A flow outside the boundary is never kept: it is dropped, or made a move
  between two stocks, whichever prices best (`guard`).
- not declared (real data, some probes): an outside flow is allowed but is a boundary claim, priced at
  CLAIM_PRICE x log T on top of its numbers (`price_claims`), and listed (`claims`).
- either way, an outflow from A and an inflow into B whose unexplained changes are anti-correlated
  (what one loses the other gains) are tried as the move A -> B (`pair_moves`), kept when it prices
  better.

The price of a structure is BIC on the one-step changes: -2 log L (Gaussian, one variance per stock)
plus log T per number, plus CLAIM_PRICE x log T per boundary claim. A hidden stock is inside the
boundary and pays only for its numbers (HIDDEN_PRICE = 0; the user, 2026-10-20). Numbers are refitted for every
structure compared (`Fit`), by least squares on the one-step changes, so a structure is never judged
with numbers fitted for another.

The module is self-contained (it imports only the shared simulator): strategies are isolated, so
another strategy copies this file into its own package (the "for copiers" section of the doc).
"""

from __future__ import annotations

import copy
import math

import numpy as np

from ...simulate import Model

CLAIM_PRICE = 2.0      # an outside flow with no declared boundary pays this many log T beyond its numbers
HIDDEN_PRICE = 0.0     # a hidden stock is part of the system inside the boundary (the user, 2026-10-20): it pays only for its numbers, no surcharge
ANTI_Z = 3.0           # two stocks' unexplained changes anti-correlated beyond this z: the move is tried
ITERATIONS = 4         # Gauss-Newton steps of a refit (one is exact for linear rates without clipping)
MIN_STEPS = 20         # fewer usable steps: no refit (a flow outside the boundary is then just dropped)
MAX_FITS = 120         # the optional passes (moves, claims) stop after this many refits (deterministic)
GUARD_FITS = 200       # (this copy) the guard's refits per call: past them a flow outside the boundary is dropped




class Boundary:
    """The announced boundary, or none (every side open, each outside flow a claim)."""

    KINDS = ("measured", "estimate")

    def __init__(self, run: dict):
        self.declared = bool(run.get("boundary_declared"))
        raw = run.get("boundary") or {}
        self.sides = {s: {side: set(e.get(side) or []) for side in ("in", "out")} for s, e in raw.items()}

    def kinds(self, stock: str, side: str) -> set:
        if not self.declared:
            return set(self.KINDS)
        return self.sides.get(stock, {}).get(side, set())

    def may(self, stock: str, side: str, kind: str | None = None) -> bool:
        k = self.kinds(stock, side)
        return bool(k) if kind is None else kind in k

    # what a row regression (one stock's change on the levels, inputs and an outside inflow) may hold
    def pieces_ok(self, stock: str) -> bool:
        """A constant or changing outside term (positive: an inflow, negative: an outflow)."""
        return self.may(stock, "in", "estimate") or self.may(stock, "out", "estimate")

    def inputs_ok(self, stock: str) -> bool:
        """A measured input's column (positive: an inflow reading it, negative: an outflow)."""
        return self.may(stock, "in", "measured") or self.may(stock, "out", "measured")

    def links_ok(self, stock: str) -> bool:
        """A column of a stock of another unit (a link from outside, or a drain to outside, reading it)."""
        return self.may(stock, "in", "estimate") or self.may(stock, "out", "estimate")

    def must_tie(self, stock: str) -> bool:
        """Its drain must be all moves: no estimated outflow to outside is declared."""
        return self.declared and not self.may(stock, "out", "estimate")

    def summary(self) -> dict:
        return {"declared": self.declared,
                "sides": {s: {k: sorted(v) for k, v in e.items() if v} for s, e in self.sides.items()}}




def _rate_stocks(f: dict) -> set:
    out = set()
    for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
        out.add(r.get("stock"))
        out |= {x.get("stock") for x in r.get("terms") or []}
    return out - {None}


def kind_of(f: dict, inputs: set) -> str:
    """"measured" for an outside flow that reads a measured input, else "estimate"."""
    return "measured" if f.get("input") or _rate_stocks(f) & inputs else "estimate"


def ends(flows: list[dict], ids: list[str]) -> list[list[tuple[str, str]]]:
    """Per flow, the measured stocks and sides its outside end reaches, as the scorer reads them
    (sdlab/ladder/parts.outside_ends): a flow from outside into a measured stock, or into an unmeasured
    one whose flows lead on to a measured one; the same for flows to outside; [] for a flow between
    stocks."""
    measured = set(ids)
    down: dict = {}
    up: dict = {}
    for f in flows:
        if f.get("from") and f.get("to"):
            down.setdefault(f["from"], set()).add(f["to"])
            up.setdefault(f["to"], set()).add(f["from"])

    def reach(start: str, edges: dict) -> set:
        seen, todo, hit = set(), [start], set()
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            if x in measured:
                hit.add(x)
                continue
            todo += list(edges.get(x) or ())
        return hit

    out = []
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if not a and b:
            out.append(sorted((s, "in") for s in reach(b, down)))
        elif a and not b:
            out.append(sorted((s, "out") for s in reach(a, up)))
        else:
            out.append([])
    return out


def violations(flows: list[dict], ids: list[str], b: Boundary, inputs: set) -> list[int]:
    """The flows outside a declared boundary: an outside end on a stock and side it does not have, or
    of a kind it does not have."""
    if not b.declared:
        return []
    return [i for i, (f, e) in enumerate(zip(flows, ends(flows, ids)))
            if any(not b.may(s, side, kind_of(f, inputs)) for s, side in e)]


def claims(flows: list[dict], ids: list[str], b: Boundary, inputs: set) -> list[dict]:
    """With no boundary declared, every outside flow is a boundary claim: [{stock, side, kind, flow}]."""
    if b.declared:
        return []
    out = []
    for f, e in zip(flows, ends(flows, ids)):
        for s, side in e:
            out.append({"stock": s, "side": side, "kind": kind_of(f, inputs),
                        "flow": f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"})
    return out


def _n_claims(flows: list[dict], ids: list[str], b: Boundary) -> int:
    return 0 if b.declared else sum(1 for e in ends(flows, ids) if e)


def _n_hidden(flows: list[dict], ids: list[str]) -> int:
    return len({x for f in flows for x in (f.get("from"), f.get("to")) if x and x not in ids})




def slots(flows: list[dict]) -> list[tuple[dict, str]]:
    """The numbers of a structure, as (dict, key): a proportional rate's k, a linear rate's constant
    (when not 0) and its terms' k, a constant's value, an outside inflow's piece values; per era where a
    rate follows the eras (eras that share a rate dict share the number)."""
    out, seen = [], set()
    for f in flows:
        if f.get("inflow"):
            out += [(g, "value") for g in f["inflow"] if g.get("value") is not None]
            continue
        for r in ([g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]):
            if id(r) in seen:
                continue
            seen.add(id(r))
            form = r.get("form")
            if form == "proportional" and r.get("k") is not None:
                out.append((r, "k"))
            elif form == "constant" and r.get("value") is not None:
                out.append((r, "value"))
            elif form == "gap":
                out += [(r, k) for k in ("goal", "time") if r.get(k) is not None]
            elif form == "linear":
                if r.get("c"):
                    out.append((r, "c"))
                out += [(x, "k") for x in r.get("terms") or [] if x.get("k") is not None]
    return out


def _quantum(a: np.ndarray) -> float:
    a = np.abs(a[np.isfinite(a)])
    for e in range(0, 9):
        q = 10.0 ** -e
        if np.all(np.abs(a / q - np.round(a / q)) < 1e-6):
            return q
    return 0.0


class Data:
    """The one-step changes a structure is fitted to: levels at each step's start (plus announced
    injections), the change over the step, the step's time (its end, as the matrix reads it), the
    measured inputs; only steps where every stock is measured at both ends."""

    def __init__(self, stocks: list[dict], run: dict, opts: dict):
        self.ids = [s["id"] for s in stocks]
        self.inputs = dict(opts.get("inputs") or {})
        t = np.asarray(run["t"], dtype=float)
        A = np.array([np.asarray(run["levels"].get(i, [np.nan] * len(t)), dtype=float) for i in self.ids])
        J = np.zeros((len(self.ids), len(t) - 1))
        for j in opts.get("injections") or []:
            if j.get("stock") in self.ids:
                J[self.ids.index(j["stock"]), np.nonzero(t[1:] == float(j["t"]))[0]] += float(j["amount"])
        L = A[:, :-1] + J
        dy = A[:, 1:] - L
        ok = np.all(np.isfinite(L), axis=0) & np.all(np.isfinite(dy), axis=0)
        self.L, self.dy, self.tt = L[:, ok], dy[:, ok], t[1:][ok]
        self.T = int(ok.sum())
        self.usable = self.T >= MIN_STEPS and len(self.ids) > 0
        self.log_t = math.log(max(self.T, 2))
        self.model_inputs = {"t": list(run["t"]), "values": self.inputs} if self.inputs else None
        q = _quantum(A)
        self.floor = self.T * q * q / 6                     # below this a stock's rss says nothing (rounding)
        self.fits = 0                                       # structures refitted so far (the passes' budget)

    def change(self, flows: list[dict]) -> np.ndarray:
        return Model(flows, self.ids, inputs=self.model_inputs).change(self.L, self.tt)

    def carried(self, f: dict) -> np.ndarray:
        """What one flow carries in each step (what leaves its source, or arrives in its receiver)."""
        if f.get("from") in self.ids:
            return -Model([{**f, "to": None}], self.ids, inputs=self.model_inputs).change(self.L, self.tt)[self.ids.index(f["from"])]
        if f.get("to") in self.ids:
            return Model([f], self.ids, inputs=self.model_inputs).change(self.L, self.tt)[self.ids.index(f["to"])]
        return np.zeros(self.T)


class Fit:
    """A structure with its numbers refitted by (per-stock weighted) least squares on the one-step
    changes; nll is -2 log L with one variance per stock (over every stock), p the count of numbers.

    free: the stocks whose flows' numbers are refitted (None: every flow's); the other numbers stay as
    given. Two structures compared with the same free stocks are compared fairly, and refitting only
    what a change touches keeps a large model's comparisons cheap. Each number's slope comes from the
    one flow that holds it, on the rows of the stocks that flow touches (what one flow's clipping does
    to another's is left out of the slope, not out of the residuals), so the normal equations are
    built stock by stock."""

    def __init__(self, flows: list[dict], data: Data, free: set | None = None):
        self.flows = copy.deepcopy(flows)
        self.p = 0
        self.ok = data.usable and not _n_hidden(flows, data.ids)
        if not self.ok:
            self.nll = float("inf")
            return
        data.fits += 1
        places, owner, seen = [], [], set()
        for fi, f in enumerate(self.flows):
            for d, k in slots([f]):
                if (id(d), k) not in seen:
                    seen.add((id(d), k))
                    places.append((d, k))
                    owner.append(fi)
        self.p = len(places)
        mine = [j for j in range(len(places)) if free is None or {self.flows[owner[j]].get("from"), self.flows[owner[j]].get("to")} & free]

        def put(th):
            for j, v in zip(mine, th):
                d, k = places[j]
                d[k] = float(v)

        def resid(th):
            put(th)
            return data.dy - data.change(self.flows)

        th = np.array([float(places[j][0][places[j][1]]) for j in mine])
        e = resid(th)
        tiny = 1e-9 * max(1.0, float(np.abs(data.dy).max(initial=0)))
        w = 1.0 / np.maximum(e.std(axis=1), tiny)
        obj = lambda r: float(((r * w[:, None]) ** 2).sum())  # noqa: E731
        cur = obj(e)
        for it in range(ITERATIONS if len(th) else 0):
            put(th)
            alone = {fi: data.change([self.flows[fi]]) for fi in {owner[j] for j in mine}}
            per_stock: dict = {}
            for q, j in enumerate(mine):
                d, k = places[j]
                h = 1e-4 * max(1e-3, abs(th[q]))
                d[k] = float(th[q] + h)
                dj = (data.change([self.flows[owner[j]]]) - alone[owner[j]]) / h
                d[k] = float(th[q])
                for srow in np.nonzero(np.any(dj != 0, axis=1))[0]:
                    per_stock.setdefault(int(srow), []).append((q, dj[srow]))
            G = np.zeros((len(th), len(th)))
            g = np.zeros(len(th))
            for srow, cols in per_stock.items():
                ix = [q for q, _ in cols]
                M = np.array([v for _, v in cols])
                G[np.ix_(ix, ix)] += w[srow] ** 2 * (M @ M.T)
                g[ix] += w[srow] ** 2 * (M @ e[srow])
            G[np.diag_indices_from(G)] += 1e-12 * (np.abs(np.diag(G)) + 1)
            try:
                step = np.linalg.solve(G, g)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(G, g, rcond=None)[0]
            for scale in (1.0, 0.5, 0.25):
                tn = th + scale * step
                en = resid(tn)
                if np.all(np.isfinite(en)) and obj(en) < cur:
                    th, e, cur = tn, en, obj(en)
                    break
            else:
                break
            if it == 1:                                     # re-weight once by the stocks' own spreads
                w = 1.0 / np.maximum(e.std(axis=1), tiny)
                cur = obj(e)
        put(th)
        self.resid = e
        rss = np.maximum((e ** 2).sum(axis=1), max(data.floor, 1e-12))
        self.nll = float(data.T * np.log(rss / data.T).sum())
        # a negative rate where only a positive one means anything (a term of a linear rate may be negative)
        self.negative = any(float(d[k]) < -1e-9 for d, k in places if "form" in d and k in ("k", "value", "time"))


def _key(f: dict) -> str:
    r = f.get("rate") or {}
    return f"{f.get('from')}>{f.get('to')}>{r.get('form')}>{sorted(_rate_stocks(f))}>{bool(f.get('inflow'))}>{bool(f.get('byTime'))}"


def touched(old: list[dict], new: list[dict], ids: list[str]) -> set:
    """The measured stocks at the ends of the flows one structure has and the other has not."""
    a, b = [_key(f) for f in old], [_key(f) for f in new]
    out = set()
    for f, k in [(f, k) for f, k in zip(old, a) if a.count(k) != b.count(k)] + [(f, k) for f, k in zip(new, b) if a.count(k) != b.count(k)]:
        out |= {x for x in (f.get("from"), f.get("to")) if x in ids}
    return out


def price(fit: Fit, data: Data, b: Boundary) -> float:
    """BIC with the boundary's prices: log T per number, CLAIM_PRICE log T per boundary claim (no
    boundary declared), HIDDEN_PRICE log T per hidden stock."""
    if not fit.ok or fit.negative:
        return float("inf")
    extra = CLAIM_PRICE * _n_claims(fit.flows, data.ids, b) + HIDDEN_PRICE * _n_hidden(fit.flows, data.ids)
    return fit.nll + (fit.p + extra) * data.log_t


def _set_rate(f: dict, rate: dict) -> None:
    f["rate"] = rate
    f["rates"] = [rate]


def _joined(flows: list[dict]) -> list[dict]:
    """Flows (copied) with two proportional moves between the same stocks on the same level joined (k
    added)."""
    out: list[dict] = []
    for f in copy.deepcopy(flows):
        r = f.get("rate") or {}
        if f.get("from") and f.get("to") and not f.get("byTime") and not f.get("inflow") and r.get("form") == "proportional":
            g = next((g for g in out if g.get("from") == f["from"] and g.get("to") == f["to"] and not g.get("byTime")
                      and (g.get("rate") or {}).get("form") == "proportional" and g["rate"].get("stock") == r.get("stock")
                      and float(g.get("ratio") or 1) == float(f.get("ratio") or 1)), None)
            if g is not None:
                _set_rate(g, {**g["rate"], "k": float(g["rate"]["k"]) + float(r["k"])})
                continue
        out.append(f)
    return out


def _same_unit(stocks: list[dict], a: str, b: str) -> bool:
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    return unit.get(a) == unit.get(b)


def alternatives(flows: list[dict], i: int, stocks: list[dict], b: Boundary, data: Data) -> list[tuple[str, list[dict]]]:
    """What flow i may become instead of an outside flow, as (what was done, flows): dropped; an
    outflow from A made a move into another stock B of A's unit (with or without B's estimated outside
    inflows, which the move may replace); an inflow into B replaced by the move from a stock A of B's
    unit that has an outside outflow, or by a move from the stock a link reads; an estimated inflow on a
    side declared measured replaced by an inflow reading each measured input. Final stocks never send."""
    f = flows[i]
    final = {s["id"] for s in stocks if s.get("final")}
    rest = [g for j, g in enumerate(flows) if j != i]
    name = f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
    out = [(f"dropped {name}", rest)]
    A, B = f.get("from"), f.get("to")
    if A in data.ids and B is None and not f.get("inflow"):
        for R in data.ids:
            if R == A or not _same_unit(stocks, A, R):
                continue
            moved = copy.deepcopy(flows)
            moved[i]["to"] = R
            out.append((f"{name} made the move {A} -> {R}", _joined(moved)))
            for j, g in enumerate(flows):
                if g.get("from") is None and g.get("to") == R and kind_of(g, set(data.inputs)) == "estimate":
                    both = [h for k, h in enumerate(moved) if k != j]
                    out.append((f"{name} and outside -> {R} made the move {A} -> {R}", _joined(both)))
        r = f.get("rate") or {}
        terms = ([{"stock": r.get("stock"), "k": r.get("k")}] if r.get("form") == "proportional"
                 else r.get("terms") if r.get("form") == "linear" and not r.get("c") else None)
        if b.declared and not b.may(A, "out", "estimate") and b.may(A, "in", "estimate") and not f.get("byTime") and terms:
            # an outflow from A where only an inflow is declared: A's estimated inflow falls as what the
            # outflow read rises (a gap inflow, c - k X), the inflow's pieces taken at their mean (only
            # then: with no boundary declared, a stock's inflow and outflow are two claims, not a net one)
            for j, g in enumerate(flows):
                if g.get("from") is not None or g.get("to") != A or g.get("byTime") or kind_of(g, set(data.inputs)) != "estimate":
                    continue
                q = g.get("rate") or {}
                if g.get("inflow"):
                    w = [max(1.0, float(p["to"]) - float(p["from"]) + 1) for p in g["inflow"]]
                    c = sum(float(p["value"]) * x for p, x in zip(g["inflow"], w)) / sum(w)
                elif q.get("form") == "constant":
                    c = float(q.get("value") or 0)
                else:
                    continue
                rate = {"form": "linear", "c": c, "terms": [{"stock": x["stock"], "k": -abs(float(x.get("k") or 0))} for x in terms]}
                gap = {"from": None, "to": A, "ratio": 1, "rate": rate, "rates": [rate]}
                out.append((f"{name} and outside -> {A} made one inflow falling as {', '.join(x['stock'] for x in terms)} rises",
                            [h for k, h in enumerate(flows) if k not in (i, j)] + [gap]))
    if B in data.ids and A is None:
        for j, g in enumerate(flows):
            S = g.get("from")
            if j == i or S not in data.ids or S in final or g.get("to") is not None or g.get("inflow") or not _same_unit(stocks, S, B):
                continue
            moved = copy.deepcopy(flows)
            moved[j]["to"] = B
            out.append((f"{name} and {S} -> outside made the move {S} -> {B}", _joined([h for k, h in enumerate(moved) if k != i])))
        r = f.get("rate") or {}
        if not f.get("byTime") and not f.get("inflow") and r.get("form") == "linear" and len(r.get("terms") or []) == 1:
            S = r["terms"][0].get("stock")
            if S in data.ids and S != B and S not in final and _same_unit(stocks, S, B):
                g = copy.deepcopy(f)
                g["from"] = S
                _set_rate(g, {"form": "proportional", "stock": S, "k": abs(float(r["terms"][0].get("k") or 0))})
                g.pop("driver", None)
                out.append((f"{name} (a link on {S}) made the move {S} -> {B}", _joined(rest + [g])))
        if b.may(B, "in", "measured") and kind_of(f, set(data.inputs)) == "estimate":
            for name_in, series in data.inputs.items():
                if name_in in data.ids:
                    continue
                v = np.asarray(series, dtype=float)
                scale = float(np.nanmean(np.abs(v))) or 1.0
                per = float(np.mean(data.carried(f))) if data.usable else 0.0
                rate = {"form": "linear", "c": 0, "terms": [{"stock": name_in, "k": max(1e-6, per / scale)}]}
                g = {"from": None, "to": B, "ratio": 1, "rate": rate, "rates": [rate], "input": name_in}
                out.append((f"{name} made an inflow reading {name_in}", rest + [g]))
    return out




def guard(flows: list[dict], stocks: list[dict], b: Boundary, data: Data, log: list[str]) -> list[dict]:
    """No flow outside a declared boundary survives: each, largest first, becomes its best-priced
    alternative (refitted); without enough data to refit, or (this copy) once GUARD_FITS refits are
    spent, it is dropped (bounded on the largest models)."""
    inputs = set(data.inputs)
    for _ in range(3 * len(flows) + 3):
        bad = violations(flows, data.ids, b, inputs)
        if not bad:
            return flows
        if not data.usable or data.fits >= GUARD_FITS:
            log += [f"dropped {flows[i].get('from') or 'outside'} -> {flows[i].get('to') or 'outside'} (no refit)" for i in bad]
            return [f for j, f in enumerate(flows) if j not in bad]
        i = max(bad, key=lambda j: float(np.abs(data.carried(flows[j])).mean()) if not _n_hidden([flows[j]], data.ids) else 0.0)
        best = None
        alts = alternatives(flows, i, stocks, b, data)
        free = set().union(*(touched(flows, cand, data.ids) for _, cand in alts))
        for what, cand in alts[:max(1, GUARD_FITS - data.fits)]:
            fit = Fit(cand, data, free)
            # an alternative that keeps more violations than it removes is worse than none
            pr = price(fit, data, b) if fit.ok else float("inf")
            pr += 1e6 * len(violations(fit.flows, data.ids, b, inputs))
            if best is None or pr < best[0]:
                best = (pr, what, fit.flows if fit.ok else cand)
        log.append(best[1])
        flows = best[2]
    return [f for j, f in enumerate(flows) if j not in violations(flows, data.ids, b, inputs)]


def _unexplained(flows: list[dict], data: Data, without: int) -> np.ndarray:
    """Each stock's change less what every flow but one explains (stocks x steps)."""
    return data.dy - data.change([f for j, f in enumerate(flows) if j != without])


def pair_moves(flows: list[dict], stocks: list[dict], b: Boundary, data: Data, log: list[str]) -> list[dict]:
    """An outflow from A and an inflow into B (both outside flows, estimated) whose unexplained changes
    are anti-correlated beyond ANTI_Z are tried as the move A -> B, replacing both, and kept when it
    prices better; repeated while one is kept."""
    if not data.usable or _n_hidden(flows, data.ids):
        return flows
    inputs = set(data.inputs)
    final = {s["id"] for s in stocks if s.get("final")}
    for _ in range(len(flows)):
        base: dict = {}
        best = None
        left: dict = {}

        def unexplained(k: int) -> np.ndarray:
            if k not in left:
                left[k] = _unexplained(flows, data, k)
            return left[k]

        for i, f in enumerate(flows):
            A = f.get("from")
            if A not in data.ids or A in final or f.get("to") is not None or f.get("inflow") or kind_of(f, inputs) != "estimate":
                continue
            eA = unexplained(i)[data.ids.index(A)]
            for j, g in enumerate(flows):
                B = g.get("to")
                if B not in data.ids or B == A or g.get("from") is not None or kind_of(g, inputs) != "estimate" or not _same_unit(stocks, A, B):
                    continue
                eB = unexplained(j)[data.ids.index(B)]
                if eA.std() == 0 or eB.std() == 0:
                    continue
                z = float(np.corrcoef(eA, eB)[0, 1]) * math.sqrt(data.T)
                if z > -ANTI_Z:
                    continue
                if data.fits >= MAX_FITS:
                    break
                moved = copy.deepcopy(flows)
                moved[i]["to"] = B
                cand = _joined([h for k, h in enumerate(moved) if k != j])
                free = frozenset(touched(flows, cand, data.ids))
                if free not in base:
                    base[free] = price(Fit(flows, data, set(free)), data, b)
                if not math.isfinite(base[free]):
                    continue
                fit = Fit(cand, data, set(free))
                gain = base[free] - (price(fit, data, b) + 1e6 * len(violations(fit.flows, data.ids, b, inputs)))
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, f"{A} -> outside and outside -> {B} made the move {A} -> {B} (z {z:.1f})", fit.flows)
        if best is None:
            return flows
        log.append(best[1])
        flows = best[2]
    return flows


def price_claims(flows: list[dict], stocks: list[dict], b: Boundary, data: Data, log: list[str]) -> list[dict]:
    """No boundary declared: each outside flow is a claim at CLAIM_PRICE log T; one at a time, the
    claim whose best alternative (dropped, made a move) lowers the price most is replaced, while one
    does."""
    if b.declared or not data.usable or _n_hidden(flows, data.ids):
        return flows
    for _ in range(len(flows)):
        base: dict = {}
        best = None
        for i, e in enumerate(ends(flows, data.ids)):
            if not e:
                continue
            for what, cand in alternatives(flows, i, stocks, b, data):
                if data.fits >= MAX_FITS:
                    break
                free = frozenset(touched(flows, cand, data.ids))
                if free not in base:
                    base[free] = price(Fit(flows, data, set(free)), data, b)
                if not math.isfinite(base[free]):
                    continue
                fit = Fit(cand, data, set(free))
                gain = base[free] - price(fit, data, b)
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, what + " (claim not earned)", fit.flows)
        if best is None:
            return flows
        log.append(best[1])
        flows = best[2]
    return flows


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, final: bool = True) -> dict:
    """The hook: a result's flows kept inside the boundary. Declared: the guard, then the moves the
    unexplained changes ask for. Not declared (final only): moves, then each claim priced; the claims
    left are listed in result["boundary_claims"]. What was done is under result["boundary"]."""
    if not isinstance(result, dict) or result.get("flows") is None:
        return result
    b = Boundary(run)
    opts = opts or {}
    data = Data(stocks, run, opts)
    log: list[str] = []
    flows = result["flows"]
    if b.declared:
        flows = guard(flows, stocks, b, data, log)
        if final:
            flows = pair_moves(flows, stocks, b, data, log)
    elif final:
        flows = pair_moves(flows, stocks, b, data, log)
        flows = price_claims(flows, stocks, b, data, log)
    out = {**result, "flows": flows}
    if final:
        out["boundary"] = {**b.summary(), "changed": log}
        out["boundary_claims"] = claims(flows, data.ids, b, set(data.inputs))
    elif log:
        out["boundary_guard"] = log
    return out
