"""milp: structure and numbers found together by one mixed-integer program (docs/research/milp.md).

Every candidate flow the boundary allows (moves between measured stocks, declared outside flows,
capacity-limited flows MIN(a x source, b x another stock or input)) gets a binary "in the model" and
numbers bounded by big-M; a capacity-limited flow also gets a per-step regime binary (which side is the
lesser). HiGHS minimises the misfit of the one-step changes plus a BIC price per number: best-subset
selection (Bertsimas, King and Mazumder 2016; Bertsimas and Gurnee 2023 for SINDy-style discovery) and
piecewise-affine identification (Roll, Bemporad and Ljung 2004) in one program. The chosen structure's
numbers are then refitted by least squares on every step, the noise scales re-estimated from what it
leaves, and the program solved again until the structure no longer changes.

Self-contained: it imports nothing from other strategies or the shared library (highspy, numpy, scipy).
"""

from __future__ import annotations

import time

import numpy as np

from . import candidates, counter, program
from .persist import persistent
from .refit import Structure, drop_tiny, keeps, prune
from .steps import Steps

__all__ = ["identify"]

EXACT = 10.0          # a structure leaving every stock's mean misfit within this many floors explains the data exactly
NEAR = 10             # after the first solve, each solve searches within this many switches of its start (local branching)
SHAPED = False                   # counts: the local search weighs steps by each structure's own moved amounts
STEP_ROUNDS = 5                  # drain and inflow steps found in turn at most this many times
STEP_SPACING = 100               # a start with more than one step per this many steps per inflow is not searched
STEP_FACTORS = (2.0, 1.0)        # change-point prices (x log T x noise variance) the inflow steps are first sought at
SCREEN = 6            # MIN flows offered beyond those on the flows found: the best by the screen
SAMPLE = 150          # steps the program reads (evenly spaced over the run when it is longer)
PASSES = 4            # program solves at most (each re-estimates the noise scales and offers MINs on the flows found)
TIME_LIMIT = 60.0     # seconds of HiGHS per solve
GAP = 1e-4            # relative MIP gap HiGHS stops at
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))
FLOOR = 1e-6          # a stock's noise scale is at least this fraction of its typical level and change


def _floor(st: Steps) -> np.ndarray:
    lv = np.mean(np.abs(st.L), axis=1)
    ch = np.sqrt(np.mean(st.dy ** 2, axis=1))
    return FLOOR * (lv + ch) + 1e-12


def _first_scale(st: Steps) -> np.ndarray:
    """Each stock's scatter left by a plain linear fit of its change on every level and input (an upper
    bound on the noise, to price the first solve)."""
    X = np.column_stack([np.ones(st.T)] + [st.L[i] for i in range(len(st.ids))] + [st.inputs[k] for k in sorted(st.inputs)])
    out = []
    for s in range(len(st.ids)):
        beta = np.linalg.lstsq(X, st.dy[s], rcond=None)[0]
        out.append(float(np.mean(np.abs(st.dy[s] - X @ beta))))
    return np.maximum(np.array(out), _floor(st))


def _scales(st: Steps, base: np.ndarray, gross: np.ndarray | None) -> np.ndarray:
    """Per stock and step: the stock's scale, and for counts a Poisson-like one growing as the square
    root of the amount moved through the stock in the step."""
    sc = np.repeat(base[:, None], st.T, axis=1)
    if st.counts and gross is not None:
        g = np.maximum(gross, 1.0)
        sc = sc * np.sqrt(g / np.mean(g, axis=1, keepdims=True))
    return np.maximum(sc, _floor(st)[:, None])


def _claims(s: Structure, bd) -> float:
    """CLAIM_PRICE log T per outside flow where no boundary is declared."""
    if not bd.claim():
        return 0.0
    n = len({(p[1], p[2]) for p in s.parts if p[1] is None or p[2] is None})
    return program.CLAIM_PRICE * np.log(max(s.st.T, 2)) * n


def _screen(st: Steps, s: Structure, mins: list, scale: np.ndarray) -> list:
    """The MIN flows most worth offering (column generation's pricing step, by least squares): each
    flow's best threshold column, scored by how much of what the structure s leaves unexplained
    (stocks x steps, per noise scale) it would explain alone; the SCREEN best."""
    e = (st.dy - s.change()) / scale
    pos = {x: i for i, x in enumerate(st.ids)}
    scored = []
    for mf in mins:
        x, y = st.series(mf.src), st.series(mf.cap)
        best = (0.0, None, 0.0)
        for th in candidates.thresholds(st, mf):
            f = np.minimum(x, th * y)
            num, den = 0.0, 0.0
            for end, sign in ((mf.src, -1.0), (mf.dst, 1.0)):
                if end in pos:
                    g = sign * f / scale[pos[end]]
                    num += float(g @ e[pos[end]])
                    den += float(g @ g)
            if den > 0 and num > 0 and num * num / den > best[0]:
                best = (num * num / den, float(th), num / den)
        scored.append((best, mf))
    scored.sort(key=lambda z: -z[0][0])
    return [(mf, th, a) for (sc, th, a), mf in scored[:SCREEN] if sc > 0]


def _start(chosen: list, screened: list) -> list:
    """The next solve's start: this one's columns, with the screen's best MIN flow (at its threshold and
    least-squares number) in place of a plain move it would limit."""
    if not screened:
        return chosen
    mf, th, a = screened[0]
    out = [(c, v) for c, v in chosen if not (c.src == mf.src and c.dst == mf.dst and c.what == ("term", mf.src))]
    col = program.Column(mf.src, mf.dst, None, 1.0, 2, None, None, ("min", mf.cap, th))
    return out + [(col, min(1.0, max(0.0, a)))]


def _as_drains(s: Structure, bd) -> Structure:
    """A gap term reading an inflow's own stock (c - k x level) written as that stock's drain where the
    boundary allows one: the same levels, and the simpler reading (the program may pick either when it
    stops at its time limit)."""
    parts = []
    for p in s.parts:
        if p[0] == "neg" and p[1] is None and p[3] == p[2] and bd.kinds(p[2], "out", p[2] in s.st.final):
            p = ("term", p[2], None, p[2])
        parts.append(p)
    s.parts = parts
    return s


def _one_per_side(s: Structure, bd, scale: np.ndarray, floor: np.ndarray, price) -> Structure:
    """(k8s-310) A declared outside side holds one flow: where the answer has a MIN flow on it beside the
    side's plain flow (or two MINs), the side is given each of them alone, refitted, and BIC keeps the best.
    The program may choose both (a MIN's columns and a term's are separate), and the scorer counts the
    second as an invented boundary."""
    if not bd.declared:
        return s
    for _ in range(len(s.parts)):
        sides: dict = {}
        for i, p in enumerate(s.parts):
            if p[0] in ("term", "neg", "min") and (p[1] is None) != (p[2] is None):
                sides.setdefault((p[1], p[2]), []).append(i)
        clash = next(((k, ix) for k, ix in sides.items() if sum(s.parts[i][0] == "min" for i in ix) + any(s.parts[i][0] != "min" for i in ix) > 1), None)
        if clash is None:
            return s
        _, ix = clash
        mins = [i for i in ix if s.parts[i][0] == "min"]
        plain = [i for i in ix if s.parts[i][0] != "min"]
        options = ([plain] if plain else []) + [[m] for m in mins]
        tried = []
        for keep in options:
            x = s
            for i in sorted(set(ix) - set(keep), reverse=True):
                x = x.without(i)
            x.refit(scale)
            tried.append((x.bic(scale, floor, price(x)), len(tried), x))
        s = min(tried)[2]
    return s


def _declared(st: Steps, bd, forced: list, have: Structure | None) -> Structure:
    """have (or nothing) with every declared outside flow it lacks added in its plainest form: an
    inflow at a constant (measured: k x each input), an outflow proportional to its stock."""
    s = have if have is not None else Structure(st, [])
    present = {(p[1], p[2]) for p in s.parts}
    for src, dst in forced:
        if (src, dst) in present:
            continue
        if src is None:
            readers = [None] if "estimate" in bd.kinds(dst, "in", dst in st.final) or not st.inputs else sorted(st.inputs)
            for r in readers:
                s.parts.append(("term", None, dst, r))
                s.theta, s.lo, s.hi = np.append(s.theta, 0.0), np.append(s.lo, 0.0), np.append(s.hi, np.inf)
        else:
            s.parts.append(("term", src, None, src))
            s.theta, s.lo, s.hi = np.append(s.theta, 0.1), np.append(s.lo, 0.0), np.append(s.hi, 1.0)
    return s


def _changes(e: np.ndarray, penalty: float, gap: int) -> list[int]:
    """Optimal partitioning of e into stretches of constant mean (least squares plus penalty per
    change, stretches at least gap long, dynamic programming): the steps where a new stretch starts."""
    T = len(e)
    c1, c2 = np.concatenate([[0.0], np.cumsum(e)]), np.concatenate([[0.0], np.cumsum(e * e)])
    F = np.full(T + 1, np.inf)
    F[0] = -penalty
    back = np.zeros(T + 1, dtype=int)
    for b in range(gap, T + 1):
        a = np.arange(0, b - gap + 1)
        a = a[(a == 0) | (a >= gap)]
        n = b - a
        cost = c2[b] - c2[a] - (c1[b] - c1[a]) ** 2 / n
        tot = F[a] + cost + penalty
        i = int(np.argmin(tot))
        F[b], back[b] = tot[i], a[i]
    out, b = [], T
    while b > 0:
        out.append(int(back[b]))
        b = back[b]
    return sorted(k for k in out if k > 0)


def _with_steps(s: Structure, scale: np.ndarray, factor: float, into: list) -> Structure:
    """Each estimated inflow constant given the steps that what the rest of s leaves of its stock's
    change asks for (optimal partitioning at factor x log T x the noise variance per change, the noise
    from step-to-step differences), refitted, and again from the refitted rest (STEP_ROUNDS times: a
    drain fitted without the steps is biased and hides them, so the drain and the steps are found in
    turn). A starting point for the local search; several factors are tried and BIC chooses."""
    st = s.st
    targets = sorted(into)
    for dst in targets:                          # the steps are of a constant: give the inflow one
        if not any(q[0] == "term" and q[1] is None and q[2] == dst and q[3] is None for q in s.parts):
            s.parts.append(("term", None, dst, None))
            s.theta, s.lo, s.hi = np.append(s.theta, 0.0), np.append(s.lo, 0.0), np.append(s.hi, np.inf)
    for _ in range(STEP_ROUNDS):
        rest = s
        for i in reversed([i for i, q in enumerate(s.parts) if q[0] == "piece"]):
            rest = rest.without(i)
        base = rest.change()
        new = rest
        for dst in targets:
            j = st.ids.index(dst)
            e = st.dy[j] - base[j]
            var = (np.median(np.abs(np.diff(e))) / 0.6745) ** 2 / 2.0
            if var <= 0:
                var = max(float(np.var(e)) * 1e-6, 1e-18)
            for k in _changes(e, factor * np.log(max(st.T, 2)) * var, candidates.PIECE_MIN):
                new = new.with_piece(dst, k)
        new.refit(scale)
        if sorted(map(str, new.parts)) == sorted(map(str, s.parts)):
            s = new
            break
        s = new
    return s


def _sample(T: int) -> np.ndarray:
    return np.arange(T) if T <= SAMPLE else np.unique(np.linspace(0, T - 1, SAMPLE).round().astype(int))


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _rate(parts: dict) -> dict:
    """{reader: number} (None: the constant) as a rate."""
    c = parts.get(None, 0.0)
    reads = [(r, v) for r, v in parts.items() if r is not None and v != 0]
    if not reads:
        return {"form": "constant", "value": _num(c)}
    if len(reads) == 1 and c == 0:
        return {"form": "proportional", "stock": reads[0][0], "k": _num(reads[0][1])}
    return {"form": "linear", "c": _num(c), "terms": [{"stock": r, "k": _num(v)} for r, v in reads]}


def _flows(s: Structure) -> list[dict]:
    """The structure in SD Lab's flow format. A flow whose rate changes (announced eras, or an inflow's
    pieces at unannounced change points) gets one segment per stretch, byTime."""
    base: dict[tuple, dict] = {}
    deltas: dict[tuple, list] = {}               # (src, dst) -> [(first step it applies, last step + 1 or None, reader, value)]
    st = s.st
    era_steps = [int(np.argmax(st.era == e)) if np.any(st.era == e) else st.T for e in range(len(st.era_starts))]
    out = []
    for p, v in s.numbers():
        if p[0] in ("term", "neg"):
            d = base.setdefault((p[1], p[2]), {})
            d[p[3]] = d.get(p[3], 0.0) + (-v[0] if p[0] == "neg" else v[0])
        elif p[0] == "era":
            base.setdefault((p[1], p[2]), {})
            e = p[4]
            end = era_steps[e + 1] if e + 1 < len(era_steps) else None
            deltas.setdefault((p[1], p[2]), []).append((era_steps[e], end, p[3], v[0]))
        elif p[0] == "piece":
            base.setdefault((p[1], p[2]), {})
            deltas.setdefault((p[1], p[2]), []).append((int(p[4]), None, p[3], v[0]))
    for key, parts in base.items():
        f = {"from": key[0], "to": key[1], "ratio": 1, "rate": _rate(parts)}
        if key in deltas:
            cuts = sorted({0} | {a for a, _, _, _ in deltas[key]} | {e for _, e, _, _ in deltas[key] if e is not None})
            cuts = [c for c in cuts if c < st.T]
            segs = []
            for n, k0 in enumerate(cuts):
                pe = dict(parts)
                for a, e, r, dv in deltas[key]:
                    if a <= k0 and (e is None or k0 < e):
                        pe[r] = pe.get(r, 0.0) + dv
                k1 = cuts[n + 1] if n + 1 < len(cuts) else st.T
                t0 = float(st.t[0]) if k0 == 0 else float(st.t[k0 + 1])
                segs.append({"from": t0, "to": float(st.t[k1]) if k1 < st.T else float(st.t[-1]), "rate": _rate(pe)})
            f["byTime"] = segs
            f["rates"] = [g["rate"] for g in segs]
            f["rate"] = segs[0]["rate"]
        out.append(f)
    for p, v in s.numbers():
        a, b = (v + [0.0])[:2]
        if p[0] == "min" and a > 0 and b > 0:
            out.append({"from": p[1], "to": p[2], "ratio": 1,
                        "rate": {"form": "expr", "expr": f"min({_num(a):g} * {p[1]}, {_num(b):g} * {p[3]})"}})
    for n, f in enumerate(out):                  # an id per flow (the engine compiles expression rates by it)
        f["id"] = f"milp:{f['from'] or 'outside'}->{f['to'] or 'outside'}:{n}"
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None, known: dict | None = None) -> dict:
    """known: {stock: {"amount": change per step}} for stocks a controller rule explains (quantized.py):
    their rows are fitted to what the rule leaves (nothing) and no flow into or out of them is offered."""
    began = time.perf_counter()
    opts = dict(opts or {})
    st = Steps(stocks, run, opts)
    if st.T < 3 or not st.ids:
        return {"flows": [], "milp": {"note": "too few steps"}}
    bd = candidates.Boundary(run)
    known = {s: k for s, k in (known or {}).items() if s in st.ids}
    if known:
        bd.skip = frozenset(known)
        for s, k in known.items():
            st.dy[st.ids.index(s)] -= np.asarray(k["amount"], dtype=float)[:st.T]
    terms, mins = candidates.build(st, bd)
    terms = [x for x in terms if x.src not in bd.skip and x.dst not in bd.skip]
    mins = [m for m in mins if m.src not in bd.skip and m.dst not in bd.skip]
    forced = candidates.declared_sides(st, bd)
    K = _sample(st.T)
    scale = _scales(st, _first_scale(st), None)
    solves, seen, tried, zoom, start = [], set(), [], None, None
    offer: list = []                       # MIN flows offered: on the flows the last solve chose (none at first)
    for _ in range(PASSES):
        cols = candidates.columns(st, terms, offer, bd.claim(), zoom)
        sol = program.solve(st.ids, st.dy, cols, K, scale[:, K], st.T, bd.claim(), TIME_LIMIT, GAP, start,
                            NEAR if start else None, forced)
        solves.append(sol["report"])
        if not sol["report"]["found"]:
            break
        s = _declared(st, bd, forced, drop_tiny(Structure(st, sol["chosen"])))
        s.refit(scale)
        if DEBUG:
            print("pass", sol["report"], "\n  chosen", [(p, [round(x, 5) for x in v]) for p, v in s.numbers()], "\n  bic", s.bic(scale, _floor(st)))
        price = lambda x: x.bic(scale, _floor(st), _claims(x, bd))  # noqa: E731
        if tried and price(s) >= min(price(x) for x in tried):
            tried.append(s)
            break                          # no better than a structure already found: the search has converged
        tried.append(s)
        if np.all(np.mean(np.abs(st.dy - s.change()), axis=1) <= EXACT * _floor(st)):
            break                          # every change explained to the data's rounding: nothing left to find
        pairs = {(p[1], p[2]) for p in s.parts if p[1] is not None and (p[0] == "min" or p[3] == p[1])}
        nxt = [m for m in mins if (m.src, m.dst) in pairs]
        screened = _screen(st, s, mins, scale)
        nxt += [m for m, _, _ in screened if m not in nxt]
        if (s.key(), len(nxt)) in seen:
            break
        seen.add((s.key(), len(nxt)))
        offer, zoom, start = nxt, s.thetas(), _start(sol["chosen"], screened)
        e = np.abs(st.dy - s.change())
        unit = _scales(st, np.ones(len(st.ids)), s.gross())
        scale = _scales(st, np.maximum(np.mean(e / unit, axis=1), _floor(st)), s.gross())
    best = None
    if tried:                               # the solves' structures compared on every step at the last noise scales
        for x in tried:
            x.refit(scale)
        best = min(tried, key=lambda x: x.bic(scale, _floor(st), _claims(x, bd)))
        st.level_rows = counter.level_rows(best)          # counters whose changes show measurement error: their rows in level space
        if st.level_rows:
            for x in tried:
                x.refit(scale)
            best = min(tried, key=lambda x: x.bic(scale, _floor(st), _claims(x, bd)))
        best = _as_drains(best, bd)
        best.refit(scale)
        shape = (lambda x: _scales(st, np.ones(len(st.ids)), x.gross())) if st.counts and SHAPED else None
        search = lambda x: prune(x, scale, _floor(st), lambda y: _claims(y, bd), lambda src: candidates.targets(st, bd, src),  # noqa: E731
                                 forced, candidates.piece_places(st), shape)
        ends = [search(best)]
        into = [j for j in st.ids if "estimate" in bd.kinds(j, "in", j in st.final)]
        if into:
            if DEBUG:
                for f in STEP_FACTORS:
                    w = _with_steps(best.without(len(best.parts)), scale, f, into)
                    print("  steps", f, round(w.bic(scale, _floor(st)), 1), len(w.parts), [(p, [round(y, 4) for y in v]) for p, v in w.numbers()][:4])
            for f in STEP_FACTORS:
                w = _with_steps(best.without(len(best.parts)), scale, f, into)
                cap = max(2, st.T // STEP_SPACING) * len(into)
                pieces = [(abs(v[0]), i) for i, (p, v) in enumerate(w.numbers()) if p[0] == "piece"]
                for _, i in sorted(sorted(pieces)[:max(0, len(pieces) - cap)], key=lambda z: -z[1]):
                    w = w.without(i)             # more steps than that chases noise: keep the largest
                w.refit(scale)
                ends.append(search(w))
        own = (lambda x: shape(x)) if shape else (lambda x: scale)
        if DEBUG:
            for x in ends:
                print("  end", round(x.bic(own(x), _floor(st), _claims(x, bd)), 1), [(p, [round(y, 4) for y in v]) for p, v in x.numbers()][:8])
        best = min(ends, key=lambda x: x.bic(own(x), _floor(st), _claims(x, bd)))
        best.refit(own(best))
        best = persistent(best, own(best))         # a MIN whose regime flips at random is its demand alone (persist.py)
        best = _one_per_side(best, bd, own(best), _floor(st), lambda x: _claims(x, bd))
        if DEBUG:
            print("  pruned", [(p, [round(x, 5) for x in v]) for p, v in best.numbers()], best.bic(scale, _floor(st)))
    note = None
    if best is None or not keeps(best, forced):          # no solve gave an answer: the declared flows, fitted
        note = "no solve returned a model: the declared outside flows, fitted by least squares"
        best = _declared(st, bd, forced, best)
        best.refit(scale)
    flows = _flows(best) if best is not None else []
    rep = {"solves": solves, "seconds": round(time.perf_counter() - began, 3),
           "solve_seconds": round(sum(r["seconds"] for r in solves), 3),
           "gap": solves[-1]["gap"] if solves else None,
           "gap_closed": bool(solves) and all(r["status"] == "Optimal" for r in solves),
           "candidates": {"terms": len(terms), "min_flows": len(mins), "columns": len(cols)}, "sample": int(len(K)), "counts": st.counts, "note": note,
           "level_rows": [st.ids[i] for i in sorted(st.level_rows)]}
    return {"flows": fixed_inputs(flows, run, (opts.get("inputs") or {}).keys()), "milp": rep}


def fixed_inputs(flows: list[dict], run: dict, inputs) -> list[dict]:
    """(2026-10-21, the user) A declared "input" inflow IS the measured series: the inflow into such a stock
    that reads a measured input is set at exactly 1 x it (no constant, never rescaled); on a side that
    declares only inputs, the stock's other outside inflows are dropped. The other numbers are not refitted
    (this strategy's search reads the side as "measured")."""
    if not run.get("boundary_declared"):
        return flows
    inputs = set(inputs or ())
    flows = [dict(f) for f in flows]

    def reads(f: dict) -> list:
        r = f.get("rate") or {}
        t = [r.get("stock")] if r.get("form") == "proportional" else [x.get("stock") for x in r.get("terms") or []]
        return [x for x in t if x in inputs]

    for s, e in sorted((run.get("boundary") or {}).items()):
        kinds = list(e.get("in") or [])
        into = [i for i, f in enumerate(flows) if f.get("from") is None and f.get("to") == s and not f.get("byTime")]
        fed = [i for i in into if reads(flows[i])]
        if "input" not in kinds or not fed:
            continue
        name = reads(flows[fed[0]])[0]
        rate = {"form": "proportional", "stock": name, "k": 1.0}
        flows[fed[0]] = {**{k: v for k, v in flows[fed[0]].items() if k in ("from", "to", "name", "id")},
                         "ratio": 1, "rate": rate, "rates": [rate], "input": name}
        drop = [i for i in into if i != fed[0]] if all(k == "input" for k in kinds) else []
        flows = [f for i, f in enumerate(flows) if i not in drop]
    return flows


# Output error (oefit.py, a copy of combined2's; 2026-10-21, k8s-307, docs/research/k8s-307-c1.md): where the
# levels carry measurement error, the program's answer (its MINs written as expressions) is refitted and its
# structure revised on the output error and judged on a Kalman likelihood.
_identify_program = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:  # noqa: F811
    from . import quantized

    known, notes = quantized.find(stocks, run, opts)          # whole-unit controllers (k8s-308): their rules, from the data
    result = _identify_program(stocks, run, opts, known)
    return _after_program(result, stocks, run, opts, known, notes)


def _after_program(result: dict, stocks: list[dict], run: dict, opts: dict | None, known: dict, notes) -> dict:
    """The passes after the program, in order (split out so a stored program answer can be re-run through them)."""
    from . import delay, effects, hidden, hinge, oefit, pairs, polish, quantized, room

    if known:
        result = {**result, "flows": quantized.put(result.get("flows") or [], known)}
    flows, revised = pairs.refine(result.get("flows") or [], stocks, run, opts, skip=known)   # a pair's flows on every step (k8s-312)
    flows, rooms = room.refine(flows, stocks, run, opts, skip=known)   # room-limited moves (k8s-311)
    if rooms:                                                  # the gaps the room's misfit bent, floored; the room polished on them
        flows, _ = hinge.refine(flows, stocks, run, opts, skip=known)
        flows, more = room.refine(flows, stocks, run, opts, skip=known)
        rooms = {"rooms": rooms["rooms"] + (more.get("rooms") or [])}
    if revised:                                                # (k8s-312) every plain flow and MIN refitted on every row before the
        flows, _ = polish.refine(flows, stocks, run, opts, skip=known)   # effect search reads what they leave
    flows, eff = effects.refine(flows, stocks, run, opts, skip=known)  # table-effect flows (k8s-310)
    if rooms:                                                  # a counted move the bent room hid (k8s-311)
        flows, cm = room.counted(flows, stocks, run, opts, skip=known)
        rooms.update(cm)
    flows, gaps = hinge.refine(flows, stocks, run, opts, skip=known)   # floored gap flows (k8s-309)
    if revised and gaps.get("used"):                           # (k8s-312) the revised pairs refitted on the gaps' flows (fitted beside
        flows, more = pairs.refine(flows, stocks, run, opts, skip=known)  # the program's misfit, a MIN's number bends)
        if more:
            revised = {"pairs": revised["pairs"] + more["pairs"]}
    if gaps.get("used"):                                       # the gaps may uncover an effect flow their misfit hid
        if revised:
            flows, _ = polish.refine(flows, stocks, run, opts, skip=known)
        flows, more = effects.refine(flows, stocks, run, opts, skip=known)
        if more:
            eff = {"effects": (eff.get("effects") or []) + more["effects"]}
            flows, gaps = hinge.refine(flows, stocks, run, opts, skip=known)
    if not rooms:                                              # (k8s-312) a room the missing effect and gap flows hid: their misfit
        flows, rooms = room.refine(flows, stocks, run, opts, skip=known)   # on the two rows kept the room's share low
        if rooms:
            flows, gaps = hinge.refine(flows, stocks, run, opts, skip=known)
            flows, more = room.refine(flows, stocks, run, opts, skip=known)
            rooms["rooms"] += more.get("rooms") or []
            flows, cm = room.counted(flows, stocks, run, opts, skip=known)
            rooms.update(cm)
            flows, gaps = hinge.refine(flows, stocks, run, opts, skip=known)
    if rooms:                                                  # the room polished on the flows as they now are
        flows, more = room.refine(flows, stocks, run, opts, skip=known)
        rooms["rooms"] += more.get("rooms") or []
    result = {**result, "flows": flows, "gaps": gaps, **({"effects": eff} if eff else {}), **({"room": rooms} if rooms else {}),
              **({"pairs": revised} if revised else {})}
    result = oefit.refit(result, stocks, run, opts or {})
    if known:                                                  # the output-error refit does not run the rules' forms
        result = {**result, "flows": quantized.put(result.get("flows") or [], known)}
    flows, hid = hidden.refine(result.get("flows") or [], stocks, run, opts, skip=known)   # hidden integrators (k8s-310)
    if hid:
        result = {**result, "flows": flows, "hidden": hid}
    flows, dl = delay.refine(result.get("flows") or [], stocks, run, opts, skip=known)   # a hidden delay on an inflow (k8s-312)
    if dl:
        result = {**result, "flows": flows, "delay": dl}
    return {**result, "quantized": notes} if notes else result
