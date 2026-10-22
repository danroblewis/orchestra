"""Room-limited moves: a move that fills its receiver only up to a ceiling another level sets (k8s-311, 2026-10-22).

A move S -> D often carries what S offers until D is full, where "full" is a ceiling proportional to another
measured level Y: pods start onto nodes while the nodes have room (4 pods a node), stock is shelved while the
shelves have space, patients are admitted while beds are free. Its rate is

    MIN(a x S, MAX(0, b x Y - D))

the source's demand, or the room left in the receiver under the ceiling b x Y. The program's MIN flows read
one capacity level (MIN(a x S, b x Y)), not a room (b x Y less the receiver's own level), so where the room
binds the program's answer bends the move to a small steady rate and leaves the rest of both rows' changes
to the flows around them.

The mechanism, the same for every pair of stocks:
- every move S -> D between measured stocks of one unit (neither a counter: nothing leaves a counter, and a
  counter only records) and not a controller's stock (quantized.py), against every ceiling reader Y: a
  measured level that is not a counter, not S and not D, or a measured input (a ceiling may be in any unit);
- for a given (a, b) the move's amount is one fixed column; the plain flows on the rows of S and D (those
  whose ends are both among them) are refitted with it by least squares, the others held at their amounts,
  and the answer's own S -> D flows are the ones it replaces (the comparison has them in, refitted); an
  outside flow on those rows also reads, in both, the levels of its stock's unit and a constant (a gap
  between like quantities the program left out; hinge.py floors it afterwards);
- (a, b) start on a grid (a log-spaced; b over the run's D / Y, from its median to past its top) and are
  polished by bounded least squares on the profiled residual;
- a candidate is kept when BIC over the two rows beats the answer by more than MARGIN (for the CHECK best by
  that gain whose share falls short, the comparison is redone with the outside flows floored as the engine
  runs them and (a, b) polished with them: _floored), the room binds
  (the room arm is the smaller) on at least EVENTS steps where the move carries something and the demand
  arm on at least EVENTS steps (else it is a plain move or a plain capacity, which the program has), and
  it explains at least SHARE of one row's misfit; the best is taken and the search runs again (at most
  MAX_FLOWS).
Written as an expression, "min(a * S, max(0, b * Y - D))"; the other flows' numbers stay the program's (the
floored refit, hinge.py, and the effect search after it refit them around the new flow).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from .hinge import _Fit, _amount, _env, _plain, _rate, _resolution
from .steps import Steps

MARGIN = 10.0        # BIC units a room-limited move must win by
EVENTS = 5           # each arm is the smaller on at least this many steps where the move carries something
SHARE = 0.5          # and it explains at least this share of one touched row's misfit
A_GRID = np.geomspace(0.02, 1.0, 12)
E_GRID = (1.0, 0.5, 0.25, 0.1, 0.05)   # a constant ceiling's weight on the receiver's level (k8s-316)
B_GRID = 16
FLOOR = 1e-5         # a row's misfit is at least this share of its typical change (and the levels' rounding)
MAX_FLOWS = 2
SUBSET = 3           # an inflow on a room's rows is re-read from at most this many readers (k8s-316)
SETTLE = 3           # rounds of re-reading those inflows and polishing the room with them
CHECK = 3            # the best candidates by the least-squares gain that are checked (floored, where their share falls short)
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _numbers(f: dict) -> int:
    """The numbers in a flow's rate (an expression's numeric literals; a linear rate's terms)."""
    r = f.get("rate") or {}
    if r.get("form") == "expr":
        import re
        return max(1, len(re.findall(r"(?<![A-Za-z_])\d+\.?\d*(?:e[-+]?\d+)?", str(r.get("expr")))))
    d = _plain(f)
    return len(d) if d else 1


def amount(S: np.ndarray, D: np.ndarray, Y: np.ndarray, a: float, b: float, e: float = 1.0, floor: bool = True) -> np.ndarray:
    r = b * Y - e * D
    return np.minimum(a * S, np.maximum(0.0, r) if floor else r)


def _amt(S, D, Y, p) -> np.ndarray:
    """The move's amount for the numbers p: (a, b) with the receiver's own level at weight 1, or (a, b, e)."""
    return amount(S, D, Y, p[0], p[1], p[2] if len(p) > 2 else 1.0)


def _free_e(y) -> bool:
    """(k8s-316) A constant ceiling (y None: a pool of b) carries the receiver's level at its own weight e (the room
    is b - e x D: a pool of connections less those held, some of them released and reused within the step); a level
    ceiling keeps weight 1 (room in the receiver's own units)."""
    return y is None


class _Rows:
    """The rows of S and D: what the fixed flows leave of their changes, the free plain flows' columns (their
    numbers refitted), and the columns of the S -> D flows the candidate replaces."""

    def __init__(self, st: Steps, flows: list[dict], amounts: list, src: str, dst: str, scale, floor, extend: bool = True):
        pos = {s: i for i, s in enumerate(st.ids)}
        self.ok = False
        rows = [pos[src], pos[dst]]
        n = st.T
        w = 1.0 / scale[rows]
        target = st.dy[rows].copy()
        free, dropped = [], []
        self.free_at = []                                    # the index in flows of each free flow
        self.drop = [i for i, f in enumerate(flows) if (f.get("from"), f.get("to")) == (src, dst)]
        self.drop_plain = []                                 # the plain ones among them (refitted as columns)
        held = np.zeros((2, n))                              # (k8s-312) replaced moves that are not plain (the program's MIN on
        held_numbers = 0                                     # the pair): in the answer's side at their amounts, charged their numbers
        for i, f in enumerate(flows):
            e = [x for x in (f.get("from"), f.get("to")) if x in pos]
            if not {pos[x] for x in e} & set(rows):
                continue
            d = _plain(f)
            if i in self.drop:
                if d is None:
                    if amounts[i] is None or f.get("room_fit") or f.get("effects"):
                        return                               # not a rate this comparison can run: leave it
                    held[0] -= amounts[i]
                    held[1] += amounts[i]
                    held_numbers += _numbers(f)
                    continue
                dropped.append((src, dst, d))
                self.drop_plain.append(i)
                continue
            if d is not None and all(pos[x] in rows for x in e):
                if extend and None in (f.get("from"), f.get("to")):     # an outside side reads, in this comparison, its own unit's levels too
                    s = f.get("from") or f.get("to")         # (a gap the program could not floor: hinge.py floors it after)
                    d = dict(d) | {x: 0.0 for x in st.ids if x not in st.final and st.units.get(x) == st.units.get(s)} | {None: 0.0}
                free.append((f.get("from"), f.get("to"), d))
                self.free_at.append(i)
                continue
            if amounts[i] is None:
                return
            for j, r in enumerate(rows):
                if st.ids[r] == f.get("from"):
                    target[j] += amounts[i]
                if st.ids[r] == f.get("to"):
                    target[j] -= amounts[i]

        def columns(fl):
            out = []
            for a, b, d in fl:
                for r in d:
                    c = np.zeros((2, n))
                    for j, row in enumerate(rows):
                        if st.ids[row] == a:
                            c[j] -= st.series(r)
                        if st.ids[row] == b:
                            c[j] += st.series(r)
                    out.append((c * w[:, None]).ravel())
            return out

        self.free, self.dropped, self.rows = free, dropped, rows
        self.fixed = np.zeros_like(st.dy)                    # the held flows' net amounts on every stock (for _floored)
        self.fixed[rows] = st.dy[rows] - target
        self.held = np.zeros_like(st.dy)                     # the replaced non-plain moves' net amounts (the answer's side only)
        self.held[rows] = held
        self.held_numbers = held_numbers
        B = columns(free)
        D = columns(dropped)
        self.y = (target * w[:, None]).ravel()
        self.Q = np.linalg.qr(np.column_stack(B))[0] if B else np.zeros((2 * n, 0))
        QD = np.linalg.qr(np.column_stack(B + D))[0] if B + D else np.zeros((2 * n, 0))
        self.r0 = self.y - self.Q @ (self.Q.T @ self.y)
        yD = ((target - held) * w[:, None]).ravel()
        eD = yD - QD @ (QD.T @ yD)
        self.p0 = len(B)
        self.base = self.bic(eD, len(B) + len(D) + held_numbers, n, floor[rows])
        self.rss0 = np.sum(eD.reshape(2, n) ** 2, axis=1)
        self.w, self.n, self.floor = w, n, floor[rows]
        self.ok = True

    @staticmethod
    def bic(resid, p, n, floor) -> float:
        e = resid.reshape(2, n)
        rss = np.maximum(np.sum(e * e, axis=1), n * floor ** 2)
        return float(np.sum(n * np.log(rss / n)) + p * np.log(2 * n))

    def resid(self, amt: np.ndarray) -> np.ndarray:
        c = (np.array([-1.0, 1.0])[:, None] * amt[None, :] * self.w[:, None]).ravel()
        cp = c - self.Q @ (self.Q.T @ c)
        return self.r0 - cp


def _fit(rw: _Rows, S, D, Y, start=None, free_e: bool = False) -> tuple:
    """(a, b) (or (a, b, e) with free_e) by least squares on the profiled residual: from a grid (or a start), polished."""
    if start is None:
        r = D / Y
        pick = None
        if free_e:                                           # the ceiling b / e in the receiver's units, past its top
            lo = max(float(np.quantile(r, 0.5)), 1e-9)
            cs = np.geomspace(lo, max(float(np.max(r)), lo) * 10.0, B_GRID)
            grid = [(a, c * e, e) for a in A_GRID for e in E_GRID for c in cs]
        else:
            bs = np.unique(np.quantile(r, 0.5) + (np.max(r) * 1.25 - np.quantile(r, 0.5)) * np.linspace(0, 1, B_GRID))
            grid = [(a, b) for a in A_GRID for b in bs]
        for p in grid:
            e = rw.resid(_amt(S, D, Y, p))
            v = float(e @ e)
            if pick is None or v < pick[0]:
                pick = (v, p)
        start = pick[1]
    f = lambda p: rw.resid(_amt(S, D, Y, p))  # noqa: E731
    box = ([1e-9] * len(start), [np.inf] * len(start))
    fit = least_squares(f, [max(float(v), 2e-9) for v in start], bounds=box, method="trf", x_scale="jac", max_nfev=200)
    # then robustly: a flow still missing on a few steps (a rare effect flow, found after this one) must not bend the
    # numbers the other steps set; the scale is the least-squares residual's median absolute deviation
    e = f(fit.x)
    mad = 1.4826 * float(np.median(np.abs(e - np.median(e))))
    if mad > 0:
        rob = least_squares(f, fit.x, bounds=box, method="trf", x_scale="jac", max_nfev=200, loss="soft_l1", f_scale=mad)
        fit = rob
    return tuple(float(v) for v in fit.x)


def _lower(st: Steps, free) -> np.ndarray:
    pos = set(st.ids)                                        # a move's number on its own source is not negative (hinge._Fit)
    return np.array([0.0 if (x in pos and y in pos and r == x) else -np.inf for x, y, rd in free for r in rd])


def _start(free) -> np.ndarray:
    return np.concatenate([[float(d.get(r, 0.0)) for r in d] for _, _, d in free]) if free else np.zeros(0)


def _joint(st: Steps, rw: _Rows, free: list, S, D, Y, pm: tuple, scale, floor):
    """The room-limited move pm = (a, b[, e]) and the free flows (linear in their readers, floored as the engine runs
    them) fitted jointly on the two rows: (BIC, pm, the free flows' numbers, rss)."""
    fit = _Fit(st, rw.rows, rw.fixed, scale, floor)
    th = _start(free)
    free = [(x, y, list(d)) for x, y, d in free]
    lo = _lower(st, free)
    sgn = np.zeros((len(st.ids), 1))
    sgn[rw.rows[0]], sgn[rw.rows[1]] = -1.0, 1.0

    k = len(pm)

    def resid(p):
        net = fit.predict(free, p[k:]) + sgn * _amt(S, D, Y, p[:k])[None, :]
        return ((st.dy - net)[rw.rows] / scale[rw.rows, None]).ravel()

    th = np.where(np.isfinite(th), th, 0.0)
    p0 = np.concatenate([[max(v, 2e-9) if np.isfinite(v) else (0.1 if j == 0 else 1.0) for j, v in enumerate(pm)],
                         np.maximum(th, lo + 1e-12 * np.isfinite(lo))])
    r = least_squares(resid, p0, bounds=(np.r_[[1e-9] * k, lo], np.full(len(p0), np.inf)), method="trf", x_scale="jac",
                      max_nfev=400, ftol=1e-12, xtol=1e-12, gtol=1e-12)
    e = resid(r.x).reshape(2, st.T)
    rss = np.maximum(np.sum(e * e, axis=1), st.T * floor[rw.rows] ** 2)
    return float(np.sum(st.T * np.log(rss / st.T)) + len(r.x) * np.log(2 * st.T)), tuple(float(v) for v in r.x[:k]), r.x[k:], rss


def _floored(st: Steps, rw: _Rows, S, D, Y, pm: tuple, scale, floor):
    """The comparison redone with the outside flows floored as the engine runs them (hinge._Fit): the answer's
    flows (the replaced S -> D move in) against the room-limited move, (a, b) polished jointly with the free
    flows. A gap between like quantities that the least squares above cannot floor leaves most of a row's
    misfit to both, which hides how much of the rest the room explains. (gain, share, pm, base BIC)."""
    fit = _Fit(st, rw.rows, rw.fixed + rw.held, scale, floor)
    base_free = [(x, y, list(d)) for x, y, d in rw.free + rw.dropped]
    lo = _lower(st, base_free)
    th0 = fit.fit(base_free, np.maximum(_start(rw.free + rw.dropped), lo + 1e-12 * np.isfinite(lo)))
    e0 = fit.resid(base_free, th0).reshape(2, st.T)
    rss0 = np.maximum(np.sum(e0 * e0, axis=1), st.T * floor[rw.rows] ** 2)
    b0 = float(np.sum(st.T * np.log(rss0 / st.T)) + (len(th0) + rw.held_numbers) * np.log(2 * st.T))
    b1, pm, _, rss1 = _joint(st, rw, rw.free, S, D, Y, pm, scale, floor)
    return b0 - b1, float(np.max(1.0 - rss1 / rss0)), pm, b0


def _with_counted(st: Steps, flows: list[dict], src: str, dst: str) -> list[dict] | None:
    """(k8s-312) flows with each counter's effect flow (effects.py: into a final counter C, reading R of C's unit; fed from
    outside, or a move R -> C) placed as the move it counts between the pair's two stocks (R one of them, the other its
    receiver X), with the counter fed from outside by the same amount, as counted() places it; a plain or MIN flow the
    program wrote on R -> X (a stand-in for those kills) goes. None when there is none to place. The kills a counted
    move carries off ready onto pending stay in both rows' misfit while the counter's flow alone carries them, and keep
    the room's share below SHARE."""
    out, placed, gone = [dict(f) for f in flows], False, set()
    for k, f0 in enumerate(flows):
        fit = f0.get("effect_fit") or {}
        c, R = f0.get("to"), fit.get("reader")
        if c not in st.final or fit.get("counter") or f0.get("counts") or f0.get("from") not in (None, R):
            continue
        if R not in (src, dst) or st.units.get(R) != st.units.get(c):
            continue
        X = dst if R == src else src
        if st.units.get(X) != st.units.get(R) or any((g.get("from"), g.get("to")) == (R, X) and g.get("effects") for g in flows):
            continue
        mid = f"milp:effect:{R}->{X}"
        out[k] = {kk: v for kk, v in f0.items() if kk != "effect_fit"} | {"from": None, "counts": mid}
        out.append({"from": R, "to": X, "ratio": 1, "id": mid, "rate": dict(f0["rate"]), "effects": [dict(e) for e in f0["effects"]],
                    "effect_fit": {**fit, "counter": c}})
        gone |= {i for i, g in enumerate(flows) if (g.get("from"), g.get("to")) == (R, X) and not g.get("effects") and not g.get("room_fit")
                 and (_plain(g) is not None or str((g.get("rate") or {}).get("expr") or "").startswith("min("))}
        gone |= {i for i, g in enumerate(flows) if i != k and (g.get("from"), g.get("to")) == (None, c) and _plain(g) is not None}
        placed = True
    return [f for i, f in enumerate(out) if i not in gone] if placed else None


def _polish(st: Steps, flows: list[dict], env: dict, scale, floor) -> tuple[list[dict], list]:
    """Each room-limited move this module wrote refitted, jointly with the plain flows on its two rows (floored as
    the engine runs them, each with its own readers; another flow on the same pair among them), on the flows as
    they now are: its numbers were fitted beside misfits (a gap not yet floored, a missing effect flow) that a
    later step removed. Written back where the rows' misfit is no worse."""
    done = []
    for f0 in [f for f in flows if f.get("room_fit")]:
        k = next(i for i, f in enumerate(flows) if f is f0)
        fit = f0["room_fit"]
        src, dst, y = f0["from"], f0["to"], fit["ceiling"]
        rest = flows[:k] + flows[k + 1:]
        rw = _Rows(st, rest, [_amount(f, st, env) for f in rest], src, dst, scale, floor, extend=False)
        if not rw.ok:
            continue
        S, D, Y = st.series(src), st.series(dst), st.series(y)
        pm = _pm(fit)
        free = rw.free + rw.dropped
        at = rw.free_at + rw.drop_plain
        cur = np.concatenate([[d[r] for r in d] for _, _, d in free]) if free else np.zeros(0)
        fitc = _Fit(st, rw.rows, rw.fixed, scale, floor)
        sgn = np.zeros((len(st.ids), 1))
        sgn[rw.rows[0]], sgn[rw.rows[1]] = -1.0, 1.0
        e = ((st.dy - fitc.predict([(x, z, list(d)) for x, z, d in free], cur) - sgn * _amt(S, D, Y, pm)[None, :])[rw.rows]
             / scale[rw.rows, None])
        rss0 = np.sum(e * e)
        _, pm, th, rss = _joint(st, rw, free, S, D, Y, pm, scale, floor)
        if not np.sum(rss) <= rss0 * (1 + 1e-9):
            continue
        new, n = {}, 0
        for i, (x, z, d) in zip(at, free):
            new[i] = _rate({r: float(v) for r, v in zip(d, th[n:n + len(d)])})
            n += len(d)
        out = []
        for i, f in enumerate(rest):
            if i in new:
                if new[i].get("form") == "constant" and not new[i].get("value") and f.get("from") is not None and f.get("to") is not None:
                    continue                                     # a move refitted to nothing goes
                f = {**f, "rate": new[i]}
            out.append(f)
        flows = out[:k] + [{**f0, "rate": {"form": "expr", "expr": _expr(st, src, dst, y, pm)}, "room_fit": _record(y, pm)}] + out[k:]
        done.append({"flow": f"{src}->{dst}", **{n: _num(v) for n, v in zip("abe", pm)}, "with": len(free)})
    return flows, done


def _count(f: dict) -> int:
    """The numbers a flow carries, over all its time segments (an inflow's pieces each pay theirs)."""
    rates = [g.get("rate") or {} for g in f.get("byTime") or []] or [f.get("rate") or {}]
    n = 0
    for r in rates:
        if r.get("form") == "linear":
            n += len(r.get("terms") or []) + (1 if r.get("c") else 0)
        else:
            n += _numbers({"rate": r})
    return max(1, n)


def _reread(st: Steps, flows: list[dict], env: dict, scale, floor) -> tuple[list[dict], list]:
    """(k8s-316) Each outside inflow on a room move's two rows read again by best subset, with the room move and every
    other flow at their amounts. The program had no room to offer, so the inflow into the room's source took the room's
    misfit (readers that only stand in for it, pieces in time); fitted around that, the room's numbers bend in turn.
    The inflow's readers are the program's own offer for an estimated side (the constant, the inputs, every other
    measured level, its own level as a gap); every subset of 1 to SUBSET of them is fitted by least squares on the
    row (each subset's exact best, never a greedy path), judged by BIC against the inflow as it stands (its pieces
    each pay their numbers). Kept when better."""
    pos = {x: i for i, x in enumerate(st.ids)}
    rooms = [f for f in flows if f.get("room_fit")]
    rows = {f["from"] for f in rooms} | {f["to"] for f in rooms}
    done = []
    for k, f0 in enumerate(flows):
        j = f0.get("to")
        if f0.get("from") is not None or j not in rows or j not in pos or f0.get("effects") or f0.get("input") or f0.get("counts"):
            continue
        r = pos[j]
        target, ok = st.dy[r].copy(), True
        for i, f in enumerate(flows):
            if i == k or j not in (f.get("from"), f.get("to")):
                continue
            amt = _amount(f, st, env)
            if amt is None:
                ok = False
                break
            target += amt if f.get("from") == j else -amt
        cur = _amount(f0, st, env)
        if not ok or cur is None:
            continue
        T, w = st.T, 1.0 / scale[r]
        fl = st.T * floor[r] ** 2

        def bic(rss, p):
            return float(T * np.log(max(rss, fl) / T) + p * np.log(T))
        b0 = bic(float(np.sum(((target - cur) * w) ** 2)), _count(f0))
        names = [None] + sorted(st.inputs) + [x for x in st.ids if x != j] + [j]
        X = np.column_stack([st.series(x) for x in names]) * w
        y = target * w
        best = None
        from itertools import combinations
        for m in range(1, SUBSET + 1):
            for idx in combinations(range(len(names)), m):
                A = X[:, idx]
                th, *_ = np.linalg.lstsq(A, y, rcond=None)
                if any(names[q] != j and v < 0 for q, v in zip(idx, th)) or any(names[q] == j and v > 0 for q, v in zip(idx, th)):
                    continue                                 # links read with a positive number, the own level as a gap
                amt = np.maximum(0.0, (A @ th) / w)
                rss = float(np.sum(((target - amt) * w) ** 2))
                b = bic(rss, m)
                if best is None or b < best[0]:
                    best = (b, {names[q]: float(v) for q, v in zip(idx, th)})
        if best is None or not best[0] < b0:
            continue
        rate = _rate(best[1])
        flows[k] = {kk: v for kk, v in f0.items() if kk not in ("byTime", "rates")} | {"rate": rate, "rates": [rate]}
        done.append({"flow": f"outside->{j}", "readers": [x or "1" for x in best[1]], "gain": round(b0 - best[0], 1)})
    return flows, done


def _settle(st: Steps, flows: list[dict], env: dict, scale, floor) -> tuple[list[dict], list]:
    """(k8s-316) The room moves and the inflows on their rows settled together: the inflows re-read (_reread), then the
    rooms polished with them (_polish), until the inflows' readers stop changing (at most SETTLE rounds)."""
    notes = []
    for _ in range(SETTLE):
        flows, rr = _reread(st, flows, env, scale, floor)
        flows, pol = _polish(st, flows, env, scale, floor)
        if rr:
            notes.append({"reread": rr})
        if pol:
            notes.append({"polished": pol})
        if not rr:
            break
    return flows, notes


def _pm(fit: dict) -> tuple:
    return (fit["a"], fit["b"], fit["e"]) if "e" in fit else (fit["a"], fit["b"])


def _record(y, pm: tuple) -> dict:
    return {"ceiling": y, "a": pm[0], "b": pm[1], **({"e": pm[2]} if len(pm) > 2 else {})}


def _expr(st: Steps, src, dst, y, pm: tuple) -> str:
    """The move as the engine runs it. (k8s-316) The room's floor at 0 is written only where the run shows it: where
    the fitted room never falls below 0 on the run, the floor is a branch the data never saw (a floor that never
    bound is "fits", not the truth's equation), so the room is written plain."""
    a, b = _num(pm[0]), _num(pm[1])
    e = _num(pm[2]) if len(pm) > 2 else 1.0
    room = (b * st.series(y) - e * st.series(dst))
    lim = (f"{b!r} * {y}" if y is not None else f"{b!r}") + (f" - {dst}" if len(pm) < 3 else f" - {e!r} * {dst}")
    if np.min(room) < 0:
        lim = f"max(0, {lim})"
    return f"min({a!r} * {src}, {lim})"


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or not st.ids:
        return flows, {}
    env = _env(st)
    flows = [dict(f) for f in flows or []]
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    skip = set(skip)
    unit = lambda x: st.units.get(x)  # noqa: E731
    pairs = [(a, b) for a in st.ids for b in st.ids
             if a != b and a not in st.final and b not in st.final and not ({a, b} & skip) and unit(a) and st.same_unit(a, b)]
    ceilings = [y for y in st.ids if y not in st.final] + sorted(st.inputs) + [None]   # None: a constant ceiling (k8s-316)
    notes = []
    flows, settled = _settle(st, flows, env, scale, floor)
    notes += settled
    for _ in range(MAX_FLOWS):
        amounts = [_amount(f, st, env) for f in flows]
        have = {(f.get("from"), f.get("to")) for f in flows if f.get("room_fit")}
        best, tops = None, []
        for src, dst in pairs:
            if (src, dst) in have:
                continue
            rw = _Rows(st, flows, amounts, src, dst, scale, floor)
            if not rw.ok:
                continue
            S, D = st.series(src), st.series(dst)
            for y in ceilings:
                if y in (src, dst):
                    continue
                Y = st.series(y)
                if not np.all(Y > 0):
                    continue
                pm = _fit(rw, S, D, Y, free_e=_free_e(y))
                e1 = rw.resid(_amt(S, D, Y, pm))
                gain = rw.base - rw.bic(e1, rw.p0 + len(pm), rw.n, rw.floor)
                rss1 = np.sum(e1.reshape(2, rw.n) ** 2, axis=1)
                tops.append((gain, float(np.max(1.0 - rss1 / np.maximum(rw.rss0, 1e-300))), src, dst, y, pm))
        tops.sort(key=lambda z: -z[0])
        seen, uniq = set(), []                                 # (k8s-312) the best ceiling of each pair: one pair's many ceilings
        for z in tops:                                         # must not fill the CHECK list
            if (z[2], z[3]) not in seen:
                seen.add((z[2], z[3]))
                uniq.append(z)
        tops = uniq
        if DEBUG:
            for z in tops[:6]:
                print("  room cand", [round(v, 4) if isinstance(v, float) else v for v in z])
        for gain, share, src, dst, y, pm in tops[:CHECK]:
            if gain <= MARGIN:
                break
            rw = _Rows(st, flows, amounts, src, dst, scale, floor)
            S, D, Y = st.series(src), st.series(dst), st.series(y)
            base = flows
            if share < SHARE:                                  # the floored comparison (the gaps the least squares bent)
                gain, share, pm, b0 = _floored(st, rw, S, D, Y, pm, scale, floor)
                if DEBUG:
                    print("  room floored", src, dst, y, round(gain, 1), round(share, 3), [round(v, 4) for v in pm])
                alt = _with_counted(st, flows, src, dst) if share < SHARE else None
                if alt is not None:                            # (k8s-312) judged with a counter's kills placed as their move
                    rw2 = _Rows(st, alt, [_amount(f, st, env) for f in alt], src, dst, scale, floor)
                    if rw2.ok:
                        g2, s2, pm2, b02 = _floored(st, rw2, S, D, Y, pm, scale, floor)
                        if DEBUG:
                            print("  room with counted move", src, dst, y, round(g2, 1), round(s2, 3), [round(v, 4) for v in pm2], "move alone", round(b0 - b02, 1))
                        if s2 >= SHARE and g2 + (b0 - b02) > MARGIN:     # the placement and the room judged together
                            gain, share, pm, rw, base = g2 + (b0 - b02), s2, pm2, rw2, alt
            amt = _amt(S, D, Y, pm)
            moves = amt > 1e-9 * (np.abs(amt).max() + 1e-300)
            room = np.maximum(0.0, pm[1] * Y - (pm[2] if len(pm) > 2 else 1.0) * D) < pm[0] * S
            if int(np.sum(moves & room)) < EVENTS or int(np.sum(moves & ~room)) < EVENTS:
                continue
            if share >= SHARE and gain > MARGIN and (best is None or gain > best[0]):
                best = (gain, src, dst, y, pm, rw.drop, base)
        if best is None:
            break
        gain, src, dst, y, pm, drop, base = best
        new = {"from": src, "to": dst, "ratio": 1, "id": f"milp:room:{src}->{dst}", "rate": {"form": "expr", "expr": _expr(st, src, dst, y, pm)},
               "room_fit": _record(y, pm)}
        flows = [f for i, f in enumerate(base) if i not in drop] + [new]
        notes.append({"flow": f"{src}->{dst}", "ceiling": y, **{n: _num(v) for n, v in zip("abe", pm)}, "gain": round(gain, 1), "replaced": len(drop)})
        flows, settled = _settle(st, flows, _env(st), scale, floor)
        notes += settled
        if DEBUG:
            print("room", notes[-1])
    return flows, {"rooms": notes} if notes else {}


def _rows_bic(st: Steps, flows: list[dict], env: dict, rows: list[int], scale, floor) -> float | None:
    net = np.zeros((len(rows), st.T))
    for f in flows:
        if not {f.get("from"), f.get("to")} & {st.ids[r] for r in rows}:
            continue
        a = _amount(f, st, env)
        if a is None:
            return None
        for j, r in enumerate(rows):
            if st.ids[r] == f.get("from"):
                net[j] -= a
            if st.ids[r] == f.get("to"):
                net[j] += a
    e = (st.dy[rows] - net) / scale[rows, None]
    rss = np.maximum(np.sum(e * e, axis=1), st.T * floor[rows] ** 2)
    return float(np.sum(st.T * np.log(rss / st.T)))


def counted(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    """A counter's effect inflow (effects.py) placed as the move it counts, judged with the room-limited moves
    re-polished (k8s-311). effects.py tries the counted move with the other flows' numbers as they stand; a
    room-limited move on the same rows was fitted while the counted flow was missing and bent to absorb it
    (its ceiling binds on the same steps), so there the counted move looks worse than the counter's inflow
    alone. Here, for an effect inflow into a final counter C reading a stock R of C's unit, each move R -> X
    (X a measured stock of that unit, not a counter) carrying the same amount is tried (replacing a plain
    R -> X move, which may have been added to absorb it): the room-limited
    moves are polished with it in and with it out, and it is kept when the BIC of the rows of R and X falls
    by more than MARGIN (the move adds no numbers: it is the counter's)."""
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or not any(f.get("room_fit") for f in flows or []):
        return flows, {}
    env = _env(st)
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    skip = set(skip)
    pos = {s: i for i, s in enumerate(st.ids)}
    notes = []
    for f0 in [f for f in flows if f.get("effect_fit") and f.get("from") is None and f.get("to") in st.final]:
        c, R = f0["to"], (f0.get("effect_fit") or {}).get("reader")
        if f0.get("effect_fit", {}).get("counter") or any(g.get("counts") == f0.get("id") for g in flows):
            continue
        if R not in pos or R in st.final or R in skip or st.units.get(R) != st.units.get(c):
            continue
        best = None
        for X in st.ids:
            if X in (R, c) or X in st.final or X in skip or st.units.get(X) != st.units.get(R):
                continue
            if any((g.get("from"), g.get("to")) == (R, X) and _plain(g) is None for g in flows):
                continue                                       # a plain move on the pair is the one the counted move replaces
            rows = [pos[R], pos[X]]
            base = _polish(st, flows, env, scale, floor)[0]
            b0 = _rows_bic(st, base, env, rows, scale, floor)
            mid = f"milp:effect:{R}->{X}"
            move = {"from": R, "to": X, "ratio": 1, "id": mid, "rate": dict(f0["rate"]), "effects": [dict(e) for e in f0["effects"]],
                    "effect_fit": {**f0["effect_fit"], "counter": c}}
            inflow = {k: v for k, v in f0.items() if k != "effect_fit"} | {"counts": mid}
            trial = [inflow if g is f0 else g for g in flows if (g.get("from"), g.get("to")) != (R, X)] + [move]
            trial = _polish(st, trial, env, scale, floor)[0]
            b1 = _rows_bic(st, trial, env, rows, scale, floor)
            if b0 is None or b1 is None:
                continue
            if DEBUG:
                print("  counted move", R, "->", X, round(b0 - b1, 1))
            if b0 - b1 > MARGIN and (best is None or b0 - b1 > best[0]):
                best = (b0 - b1, X, trial)
        if best is not None:
            flows = best[2]
            notes.append({"flow": f"{R}->{best[1]}", "counted_by": c, "gain": round(best[0], 1)})
    return flows, {"counted": notes} if notes else {}
