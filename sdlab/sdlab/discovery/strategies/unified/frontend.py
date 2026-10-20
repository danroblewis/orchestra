"""The front end: any model's flows (the truth laid out by time, a stored found model, a search
candidate) read into one structure with numbered slots (docs/research/unified-design.md, section 2).

A rate segment is put in one normal form, `c + sum_j k_j z_j` over readers z (stocks, measured inputs,
the constant 1): constant -> c; proportional -> k on its stock; gap (goal - x) / time -> c = goal/time
and k = -1/time; linear -> c (a c of exactly 0 is no term) and its k's. A flow's segments (byTime, else
inflow pieces, else one rate) give each coefficient a schedule over time; runs of the schedule with the
same value share one slot, a coefficient whose segment lacks the term is a fixed 0. Effects (table:
knot positions are structure, the multipliers slots; linear: normal, min, max slots), co-flow `per`
(a slot), ratio (structure), two_way (an unfloored rate), signed stocks, ceilings, sub-steps and
hidden-stock starts (slots) are kept. Anything else (an expression rate, a switch, an auxiliary) raises
NotExpressible: class C of the objective test, never a silent skip.

Only the discovery view and the flows come in: nothing here imports the ladder (CLAUDE.md rule 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

VIEW_KEYS = {"stocks", "t", "levels", "eras", "injections", "inputs"}
FORBIDDEN = {"all_levels", "counters", "clean", "observation", "truth", "case", "seed"}
QUANTA = (1.0, 0.1, 0.01, 1e-3, 1e-4, 1e-5, 1e-6)


class NotExpressible(ValueError):
    """The model uses something the class cannot hold yet (class C)."""


def check_view(view: dict) -> None:
    """The leakage guard (section 7.2, check 4): the evaluator gets the discovery view and nothing else."""
    bad = set(view) & FORBIDDEN
    assert not bad, f"the evaluator was given what discovery never sees: {sorted(bad)}"
    extra = set(view) - VIEW_KEYS
    assert not extra, f"the evaluator was given keys outside the discovery view: {sorted(extra)}"


def quantum(levels: np.ndarray) -> float:
    """The coarsest power of ten every level is written in (1 for counts, 1e-4 for the engine's
    noise-free levels); 1e-7 when none fits. Copied from strategies/combined/judge.py (c74fe15)."""
    x = levels[np.isfinite(levels)]
    for q in QUANTA:
        if x.size == 0 or np.abs(x / q - np.round(x / q)).max() < 1e-6:
            return q
    return 1e-7


@dataclass
class Grid:
    """The view on the engine's step grid: every whole time from the first report to the last."""
    ids: list[str]                 # measured stocks, in the view's order
    times: np.ndarray              # grid times (first = the first report, not stepped into)
    y: np.ndarray                  # reports, grid x measured (nan: no report)
    q: np.ndarray                  # each measured stock's quantum
    scale: np.ndarray              # each measured stock's level scale (mean |level| + q)
    inputs: dict[str, np.ndarray]  # measured inputs on the grid (value at or before each time)
    injections: list[tuple[int, str, float]]
    announced: set[int]            # announced era starts (cut places that are given)

    @property
    def n_reports(self) -> int:
        return int(np.isfinite(self.y[1:]).sum())


def grid_of(view: dict) -> Grid:
    check_view(view)
    t = np.asarray(view["t"], dtype=float)
    ids = [s["id"] for s in view["stocks"]]
    t0, t1 = int(round(t[0])), int(round(t[-1]))
    times = np.arange(t0, t1 + 1, dtype=float)
    pos = {int(round(v)): i for i, v in enumerate(t)}
    y = np.full((len(times), len(ids)), np.nan)
    for gi, tt in enumerate(times):
        i = pos.get(int(tt))
        if i is not None:
            for j, s in enumerate(ids):
                v = view["levels"][s][i]
                y[gi, j] = np.nan if v is None else float(v)
    q = np.array([quantum(y[:, j]) for j in range(len(ids))])
    scale = np.array([float(np.nanmean(np.abs(y[:, j]))) if np.isfinite(y[:, j]).any() else 0.0 for j in range(len(ids))]) + q
    ins = {}
    for k, vals in (view.get("inputs") or {}).items():
        v = np.asarray([np.nan if x is None else float(x) for x in vals])
        idx = np.clip(np.searchsorted(t, times, side="right") - 1, 0, len(t) - 1)
        ins[k] = np.nan_to_num(v[idx])
    inj = [(int(round(float(j["t"]))), j["stock"], float(j["amount"])) for j in view.get("injections") or []]
    eras = view.get("eras") or []
    announced = {int(round(float(e["start"]))) for e in eras[1:]} if len(eras) > 1 else set()
    return Grid(ids, times, y, q, scale, ins, inj, announced)


@dataclass
class Slot:
    value: float                    # the number as written
    kind: str                       # coef, effect, per, start
    flow: int | None                # the flow it belongs to (None: a hidden start)
    stocks: tuple                   # the stocks whose one-step mean it moves (for N_j)
    steps: np.ndarray | None = None  # grid steps where it acts (None: all)
    path: tuple = ()                # where to write it back: (flow, ...) into the flows


@dataclass
class Structure:
    ids: list[str]                  # every stock: measured first, then hidden
    n_measured: int
    inputs: list[str]
    flows: list[dict]               # the flows as given (for writing numbers back)
    slots: list[Slot] = field(default_factory=list)
    # terms: one per (flow, reader); tidx[k, term] is the slot active at grid step k (P: a fixed 0)
    term_flow: list[int] = field(default_factory=list)
    term_reader: list[int] = field(default_factory=list)   # index into z = [x, u, 1]
    tidx: np.ndarray | None = None
    gap_flows: dict = field(default_factory=dict)          # flow -> written as a gap (for writing back)
    effects: list[tuple] = field(default_factory=list)     # (flow, reader, "table", xs, slots) | (flow, reader, "linear", normal, min, max)
    uses: list[tuple] = field(default_factory=list)        # (flow, stock, slot)
    V: np.ndarray | None = None                            # stoichiometry without co-flows, stocks x flows
    two_way: np.ndarray | None = None
    signed: np.ndarray | None = None
    ceilings: list[tuple] = field(default_factory=list)   # (stock, cap)
    n_sub: int = 1
    starts: list[tuple] = field(default_factory=list)     # (hidden stock, slot)
    struct: dict = field(default_factory=dict)            # what the structure code counts

    @property
    def P(self) -> int:
        return len(self.slots)

    def theta0(self) -> np.ndarray:
        return np.array([s.value for s in self.slots], dtype=float)


def _normal(rate: dict | None) -> dict:
    """{reader or None: coefficient} for one rate segment."""
    r = rate or {}
    form = r.get("form")
    if form == "constant":
        return {None: float(r.get("value") or 0)}
    if form == "proportional":
        return {r.get("stock"): float(r.get("k") or 0)}
    if form == "gap":
        T = float(r.get("time") or 1) or 1.0
        return {None: float(r.get("goal") or 0) / T, r.get("stock"): -1.0 / T}
    if form == "linear":
        out = {None: float(r["c"])} if float(r.get("c") or 0) != 0 else {}
        for term in r.get("terms") or []:
            out[term.get("stock")] = out.get(term.get("stock"), 0.0) + float(term.get("k") or 0)
        return out or {None: 0.0}
    if form is None and not r:
        return {None: 0.0}
    raise NotExpressible(f"rate form {form!r}")


def _segments(f: dict) -> list[tuple[float, dict, tuple]]:
    """(from, normal form, write-back path) per segment, ordered by from."""
    if f.get("byTime"):
        segs = [(float(g["from"]), _normal(g.get("rate")), ("byTime", i, "rate")) for i, g in enumerate(f["byTime"])]
    elif f.get("inflow"):
        segs = [(float(g["from"]), {None: float(g.get("value") or 0)}, ("inflow", i, "value")) for i, g in enumerate(f["inflow"])]
    else:
        segs = [(-math.inf, _normal(f.get("rate")), ("rate",))]
    return sorted(segs, key=lambda s: s[0])


def _key(v: float) -> float:
    return float(f"{v:.12g}")


def build(view: dict, flows: list[dict], *, dt: float = 1.0, ceilings: dict | None = None, signed: set | None = None,
          hidden_starts: dict | None = None, grid: Grid | None = None) -> Structure:
    """The structure of `flows` on the view's grid. hidden_starts: {hidden stock: a start level to
    begin the fit from} (default 0)."""
    g = grid or grid_of(view)
    measured = list(g.ids)
    inputs = list(g.inputs)
    known = set(measured) | set(inputs)
    hidden: list[str] = []

    def stock(s):
        if s is None:
            return None
        if s not in known and s not in hidden:
            hidden.append(s)
        return s

    for f in flows:
        if f.get("form") == "expr" or (f.get("rate") or {}).get("form") == "expr":
            raise NotExpressible("an expression rate")
        stock(f.get("from"))
        stock(f.get("to"))
        for u in f.get("uses") or []:
            stock(u.get("stock"))
        for _, nf, _ in _segments(f):
            for r in nf:
                if r is not None:
                    stock(r)
        for e in f.get("effects") or []:
            stock(e.get("stock"))
    hidden = [h for h in hidden if h not in inputs]
    ids = measured + hidden
    S, U = len(ids), len(inputs)
    zi = {s: i for i, s in enumerate(ids)}
    zi.update({k: S + j for j, k in enumerate(inputs)})
    ONE = S + U
    st = Structure(ids=ids, n_measured=len(measured), inputs=inputs, flows=flows)
    F = len(flows)
    V = np.zeros((S, F))
    for fi, f in enumerate(flows):
        if f.get("from") is not None:
            V[zi[f["from"]], fi] -= float(f.get("ratio") or 1)
        if f.get("to") is not None:
            V[zi[f["to"]], fi] += 1.0
    st.V = V
    st.two_way = np.array([bool(f.get("two_way")) for f in flows])
    sg = set(signed or set())
    for f in flows:
        s = f.get("signed")
        if s is True:
            sg |= {x for x in (f.get("from"), f.get("to")) if x}
        elif isinstance(s, (list, tuple)):
            sg |= set(s)
    st.signed = np.array([s in sg for s in ids])
    st.ceilings = [(zi[s], float(c)) for s, c in (ceilings or {}).items() if s in zi and zi[s] < S and c is not None]
    st.n_sub = max(1, round(1 / float(dt))) if dt and float(dt) < 1 else 1

    times = g.times
    Tg = len(times)
    t_cols: list[np.ndarray] = []
    n_sched, n_cuts_ann, sched_cuts = 0, 0, []
    terms_per_flow = []
    for fi, f in enumerate(flows):
        segs = _segments(f)
        froms = np.array([s[0] for s in segs])
        seg_at = np.clip(np.searchsorted(froms, times, side="right") - 1, 0, len(segs) - 1)   # latest from <= t
        readers = []
        for _, nf, _ in segs:
            for r in nf:
                if r not in readers:
                    readers.append(r)
        touched = tuple(x for x in (f.get("from"), f.get("to")) if x is not None) + tuple(u.get("stock") for u in f.get("uses") or [])
        nterms = 0
        for r in readers:
            vals = [nf.get(r) for _, nf, _ in segs]                        # None: a fixed 0 in that segment
            slot_of: dict = {}
            seg_slot = []
            for si, v in enumerate(vals):
                if v is None:
                    seg_slot.append(-1)
                    continue
                k = _key(v)
                if k not in slot_of:
                    slot_of[k] = len(st.slots)
                    path = segs[si][2]
                    st.slots.append(Slot(v, "coef", fi, touched, None, (fi, path, r)))
                seg_slot.append(slot_of[k])
            col = np.array([seg_slot[s] for s in seg_at])
            col = np.where(col < 0, -1, col)
            # where each slot acts (for N_j) and the schedule's cuts (for the structure code)
            for sl in set(slot_of.values()):
                st.slots[sl].steps = np.flatnonzero(col == sl)
            ch = np.flatnonzero(col[2:] != col[1:-1]) + 2 if Tg > 2 else np.array([], int)   # cuts inside the run
            if len(ch):
                n_sched += 1
                ann = sum(int(times[c]) in g.announced for c in ch)
                n_cuts_ann += ann
                sched_cuts.append(len(ch) - ann)
            t_cols.append(col)
            st.term_flow.append(fi)
            st.term_reader.append(ONE if r is None else zi[r])
            nterms += 1
        if f.get("byTime") is None and not f.get("inflow") and (f.get("rate") or {}).get("form") == "gap":
            st.gap_flows[fi] = True
        terms_per_flow.append(nterms)
        for ei, e in enumerate(f.get("effects") or []):
            rd = zi.get(e.get("stock"))
            if rd is None:
                raise NotExpressible(f"an effect of {e.get('stock')!r}")
            if e.get("shape") == "table" and e.get("points"):
                pts = sorted((float(a), float(b)) for a, b in e["points"])
                xs = np.array([a for a, _ in pts])
                sl = []
                for pi, (_, b) in enumerate(pts):
                    sl.append(len(st.slots))
                    st.slots.append(Slot(b, "effect", fi, touched, None, (fi, ("effects", ei, "points"), pi)))
                st.effects.append((fi, rd, "table", xs, sl))
            else:
                parts = []
                for k, dflt in (("normal", 1.0), ("min", 0.0), ("max", 1.0)):
                    if e.get(k) is not None:
                        parts.append(len(st.slots))
                        st.slots.append(Slot(float(e[k]), "effect", fi, touched, None, (fi, ("effects", ei, k), None)))
                    else:
                        parts.append(("fixed", dflt))
                st.effects.append((fi, rd, "linear", *parts))
        for ui, u in enumerate(f.get("uses") or []):
            if float(u.get("per") or 0) <= 0 or u.get("stock") not in zi:
                continue
            st.uses.append((fi, zi[u["stock"]], len(st.slots)))
            st.slots.append(Slot(float(u["per"]), "per", fi, touched, None, (fi, ("uses", ui, "per"), None)))
    st.tidx = (np.stack(t_cols, axis=1) if t_cols else np.zeros((Tg, 0), int))
    hs = hidden_starts or {}
    for h in hidden:
        st.starts.append((zi[h], len(st.slots)))
        st.slots.append(Slot(float(hs.get(h, 0.0)), "start", None, (h,), None, ("start", h)))
    P = len(st.slots)
    st.tidx = np.where(st.tidx < 0, P, st.tidx).astype(np.int32)
    st.struct = {
        "S": S, "U": U, "T": Tg - 1, "F": F, "H": len(hidden), "terms": terms_per_flow,
        "readers": [sum(1 for t, fl in zip(st.term_reader, st.term_flow) if fl == fi and t != ONE) for fi in range(F)],
        "effects": [(e[0], len(e[4]) if e[2] == "table" else 2) for e in st.effects],
        "uses": len(st.uses), "two_way": int(st.two_way.sum()), "n_coef": len(st.term_flow),
        "scheduled": n_sched, "unannounced_cuts": sched_cuts, "announced_cuts": n_cuts_ann,
    }
    return st


def write_back(st: Structure, theta: np.ndarray) -> list[dict]:
    """The flows with the fitted numbers written into them (gap rates written back as gaps), for the
    scorer to re-grade."""
    import copy
    out = copy.deepcopy(st.flows)
    coef: dict = {}
    for sl, v in zip(st.slots, theta):
        if sl.kind == "coef":
            fi, path, r = sl.path
            coef.setdefault((fi, path), {})[r] = float(v)
    for (fi, path), nf in coef.items():
        f = out[fi]
        tgt = f
        for p in path[:-1]:
            tgt = tgt[p]
        last = path[-1]
        if last == "value":                                    # an inflow piece
            tgt["value"] = nf.get(None, 0.0)
            continue
        old = tgt.get(last) or {}
        readers = [r for r in nf if r is not None]
        if old.get("form") == "gap" and len(readers) == 1 and nf[readers[0]] != 0:
            k = nf[readers[0]]
            tgt[last] = {**old, "time": -1.0 / k, "goal": nf.get(None, 0.0) * (-1.0 / k)}
        elif not readers:
            tgt[last] = {"form": "constant", "value": nf.get(None, 0.0)}
        elif len(readers) == 1 and None not in nf:
            tgt[last] = {"form": "proportional", "stock": readers[0], "k": nf[readers[0]]}
        else:
            tgt[last] = {"form": "linear", "c": nf.get(None, 0.0), "terms": [{"stock": r, "k": nf[r]} for r in readers]}
        if last == "rate" and len(path) == 1:
            f.pop("rates", None)
    for sl, v in zip(st.slots, theta):
        if sl.kind == "effect":
            fi, (_, ei, key), pi = sl.path
            e = out[fi]["effects"][ei]
            if key == "points":
                pts = sorted([list(map(float, p)) for p in e["points"]])
                pts[pi][1] = float(v)
                e["points"] = pts
            else:
                e[key] = float(v)
        elif sl.kind == "per":
            fi, (_, ui, _), _ = sl.path
            out[fi]["uses"][ui]["per"] = float(v)
    return out
