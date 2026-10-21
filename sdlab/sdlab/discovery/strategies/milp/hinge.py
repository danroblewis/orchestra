"""Gap flows: outside flows whose rate is a linear gap the engine floors at 0 (k8s-309, 2026-10-21).

The engine floors every rate at 0: a flow's amount is max(0, w . levels), not w . levels. A rate that is
a gap between like quantities ("create what is missing": desired - pending - ready; "delete the
surplus": ready - desired) is negative on many steps, where it moves nothing. The program fits the
unfloored w . levels to the one-step changes, so where the gap goes negative it must explain a zero
amount by a negative one: the gap's numbers come out shrunk (0.34 desired - 0.34 ready - 0.33 pending
for 1, -1, -1), or the flow is lost to a constant or a drain on its own stock, and the numbers of the
moves on the same stocks are bent to make up the difference.

The mechanism, the same for every stock:
- each measured stock S that is not a counter and not a whole-unit controller (quantized.py), on each
  side where it may have an outside flow (declared "estimate", or any side where no boundary is
  declared and the answer has one), gets a candidate outside flow max(0, w . x) that reads S's own
  unit: the measured stocks in S's unit (a gap compares like with like), plus whatever S's present
  flow on that side reads;
- every candidate and every plain move touching a candidate stock (and plain outside flows on those
  stocks) are refitted together on the one-step changes of the stocks they touch, with the floor
  (least squares; the gap's numbers start from a least-squares fit on the steps where the flow
  acts), then each gap's readers are pruned backwards by BIC;
- the gaps are kept only when BIC over the rows they touch improves on the answer's flows by more than
  MARGIN; each gap is then tried back as the answer's own flow and reverted where that is no worse.
A gap is written as a plain linear rate: the engine's floor makes it max(0, w . x).
"""

from __future__ import annotations


import numpy as np
from scipy.optimize import least_squares

from .steps import Steps

MARGIN = 10.0        # BIC units a set of gap flows must win by
MAX_READS = 4        # a gap reads at most this many levels (and the constant)
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))
EVENTS = 5          # a free flow acts, and a new gap's floor binds, on at least this many steps
FLOOR = 1e-5        # a row's misfit is at least this share of its typical change (the answer's numbers are written to 6 digits),
                    # and at least the levels' rounding (_resolution)


def _segments(f: dict, st: Steps) -> list[tuple[np.ndarray, dict]]:
    if not f.get("byTime"):
        return [(np.ones(st.T, bool), f.get("rate") or {})]
    tk = st.t[1:st.T + 1]
    out = []
    for n, g in enumerate(f["byTime"]):
        lo = float(g["from"])
        hi = float(f["byTime"][n + 1]["from"]) if n + 1 < len(f["byTime"]) else np.inf
        out.append(((tk > lo) & (tk <= hi) if n else (tk <= hi), g.get("rate") or {}))
    return out


def _env(st: Steps) -> dict:
    env = {s: st.L[i] for i, s in enumerate(st.ids)}
    env.update(st.inputs)
    env.update(min=np.minimum, max=np.maximum, ceil=np.ceil, floor=np.floor, abs=np.abs, exp=np.exp, log=np.log)
    return env


def _value(rate: dict, st: Steps, env: dict) -> np.ndarray | None:
    form = rate.get("form")
    if form == "constant":
        return np.full(st.T, float(rate.get("value", 0.0)))
    if form == "proportional":
        x = env.get(rate.get("stock"))
        return None if x is None else float(rate["k"]) * np.asarray(x, float)
    if form == "linear":
        v = np.full(st.T, float(rate.get("c", 0.0)))
        for term in rate.get("terms") or []:
            x = env.get(term.get("stock"))
            if x is None:
                return None
            v = v + float(term["k"]) * np.asarray(x, float)
        return v
    if form == "expr":
        try:
            v = eval(rate["expr"], {"__builtins__": {}}, env)          # noqa: S307  (the strategy's own expressions)
        except Exception:                                              # noqa: BLE001
            return None
        return np.broadcast_to(np.asarray(v, float), (st.T,)).copy()
    return None


def _amount(f: dict, st: Steps, env: dict) -> np.ndarray | None:
    out = np.zeros(st.T)
    for mask, rate in _segments(f, st):
        v = _value(rate, st, env)
        if v is None:
            return None
        out[mask] = v[mask]
    return np.maximum(out, 0.0)


def _plain(f: dict) -> dict | None:
    """{reader: k} (None: the constant) of a flow with one linear rate, else None."""
    if f.get("byTime"):
        return None
    r = f.get("rate") or {}
    if r.get("form") == "constant":
        return {None: float(r.get("value", 0.0))}
    if r.get("form") == "proportional":
        return {r["stock"]: float(r["k"])}
    if r.get("form") == "linear":
        d = {None: float(r.get("c", 0.0))} if r.get("c") else {}
        d.update({t["stock"]: float(t["k"]) for t in r.get("terms") or []})
        return d
    return None


def _reads(f: dict) -> set:
    out = set()
    for _, rate in ([(None, f.get("rate") or {})] + [(None, g.get("rate") or {}) for g in f.get("byTime") or []]):
        if rate.get("form") == "proportional":
            out.add(rate.get("stock"))
        for t in rate.get("terms") or []:
            out.add(t.get("stock"))
    return out - {None}


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _rate(d: dict) -> dict:
    c = d.get(None, 0.0)
    reads = [(r, v) for r, v in d.items() if r is not None and v != 0]
    if not reads:
        return {"form": "constant", "value": _num(max(c, 0.0))}
    if len(reads) == 1 and c == 0:
        return {"form": "proportional", "stock": reads[0][0], "k": _num(reads[0][1])}
    return {"form": "linear", "c": _num(c), "terms": [{"stock": r, "k": _num(v)} for r, v in reads]}


class _Fit:
    """Free flows (linear in their readers, floored) fitted with the fixed rest on the rows they touch."""

    def __init__(self, st: Steps, rows: list[int], fixed: np.ndarray, scale: np.ndarray, floor: np.ndarray):
        self.st, self.rows, self.fixed, self.scale, self.floor = st, rows, fixed, scale, floor

    def predict(self, free: list[tuple], theta: np.ndarray) -> np.ndarray:
        st, out, n = self.st, self.fixed.copy(), 0
        pos = {s: i for i, s in enumerate(st.ids)}
        for src, dst, readers in free:
            v = np.zeros(st.T)
            for r in readers:
                v = v + theta[n] * st.series(r)
                n += 1
            a = np.maximum(v, 0.0)
            if src in pos:
                out[pos[src]] -= a
            if dst in pos:
                out[pos[dst]] += a
        return out

    def resid(self, free, theta):
        e = (self.st.dy - self.predict(free, theta))[self.rows]
        return (e / self.scale[self.rows, None]).ravel()

    def fit(self, free: list[tuple], theta0: np.ndarray) -> np.ndarray:
        if len(theta0) == 0:
            return theta0
        r = least_squares(lambda th: self.resid(free, th), theta0, method="trf", max_nfev=400, x_scale="jac",
                          ftol=1e-15, xtol=1e-15, gtol=1e-15)
        return r.x

    def bic(self, free, theta) -> float:
        e = self.resid(free, theta).reshape(len(self.rows), self.st.T)
        n = self.st.T
        rss = np.maximum(np.sum(e * e, axis=1), n * self.floor[self.rows] ** 2)
        return float(np.sum(n * np.log(rss / n)) + len(theta) * np.log(n * len(self.rows)))


def _resolution(x: np.ndarray) -> float:
    """The step the levels are written in (1e-4 for levels with four decimals; 0 at full precision): a
    one-step change carries that rounding, sd resolution / sqrt(6), and no fit explains it."""
    for k in range(10):
        if np.all(np.abs(x * 10.0 ** k - np.round(x * 10.0 ** k)) < 1e-6):
            return 10.0 ** -k
    return 0.0


def _hinge_start(target: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Least squares of the flow's amount on its readers over the steps where it acts, then on those where
    the fit is positive or the flow acts (a few rounds of the active set)."""
    act = target > 1e-9 * (np.abs(target).max() + 1e-300)
    w = np.zeros(X.shape[1])
    for _ in range(6):
        if act.sum() < X.shape[1]:
            break
        w = np.linalg.lstsq(X[act], target[act], rcond=None)[0]
        nxt = (X @ w > 0) | (target > 1e-9 * (np.abs(target).max() + 1e-300))
        if np.array_equal(nxt, act):
            break
        act = nxt
    return w


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 10 or not st.ids:
        return flows, {}
    env = _env(st)
    declared = bool(run.get("boundary_declared"))
    bd = run.get("boundary") or {}
    pos = {s: i for i, s in enumerate(st.ids)}
    flows = list(flows or [])
    amounts = [_amount(f, st, env) for f in flows]
    # candidate sides: (stock, side) with an estimated outside flow allowed
    cands = []
    for s in st.ids:
        if s in st.final or s in skip:
            continue
        for side in ("in", "out"):
            ends = (None, s) if side == "in" else (s, None)
            have = [i for i, f in enumerate(flows) if (f.get("from"), f.get("to")) == ends]
            kinds = (bd.get(s) or {}).get(side) or []
            ok = ("estimate" in kinds) if declared else bool(have)
            if not ok or len(have) > 1 or any(amounts[i] is None for i in have):
                continue
            cands.append((s, side, have[0] if have else None))
    if not cands:
        return flows, {}
    # gap candidates: readers in the stock's own unit, plus what its present flow reads, plus the constant
    gaps = []
    for s, side, i in cands:
        same = [x for x in st.ids if x not in st.final and st.units.get(x) and st.units.get(x) == st.units.get(s)]
        extra = sorted(_reads(flows[i])) if i is not None else []
        readers = [None] + list(dict.fromkeys(same + [x for x in extra if x in pos or x in st.inputs]))
        if len(readers) - 1 > MAX_READS:
            continue
        gaps.append((s, side, readers))
    cands = [c for c in cands if any(g[:2] == c[:2] for g in gaps)]
    if not gaps:
        return flows, {}
    cstocks = {s for s, _, _ in cands}
    # plain moves on candidate stocks are refitted with the gaps
    replaced = {i for _, _, i in cands if i is not None}
    moves = [i for i, f in enumerate(flows) if i not in replaced and (f.get("from") in cstocks or f.get("to") in cstocks)
             and f.get("from") in pos and f.get("to") in pos and _plain(f) is not None]
    have_mv = {(flows[i]["from"], flows[i]["to"]) for i in moves}
    extra_mv = [(a, b) for a in st.ids for b in st.ids
                if a != b and (a in cstocks or b in cstocks) and (a, b) not in have_mv and st.units.get(a)
                and st.same_unit(a, b) and not ({a, b} & (st.final | set(skip)))]
    touched = {e for ab in extra_mv for e in ab}
    for i in list(replaced) + moves:
        for e in (flows[i].get("from"), flows[i].get("to")):
            if e in pos:
                touched.add(e)
    touched |= cstocks
    rows = sorted(pos[s] for s in touched)
    if any(amounts[i] is None for i, f in enumerate(flows) if i not in replaced and i not in moves
           and (f.get("from") in touched or f.get("to") in touched)):
        return flows, {"note": "a flow on the touched stocks cannot be evaluated"}
    fixed = np.zeros_like(st.dy)
    for i, f in enumerate(flows):
        if i in replaced or i in moves or amounts[i] is None:
            continue
        if f.get("from") in pos:
            fixed[pos[f["from"]]] -= amounts[i]
        if f.get("to") in pos:
            fixed[pos[f["to"]]] += amounts[i]
    scale = np.sqrt(np.mean((st.dy) ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)          # whole-number data (counts): their scatter is the noise
    fit = _Fit(st, rows, fixed, scale, floor)

    def plain_free(i):
        d = _plain(flows[i])
        return (flows[i].get("from"), flows[i].get("to"), list(d.keys())), np.array(list(d.values()), float)

    # the answer as it stands, its plain flows refitted with the floor
    old_free, old_th = [], []
    for i in list(replaced) + moves:
        d = _plain(flows[i])
        if d is not None:
            fr, th = plain_free(i)
            old_free.append(fr)
            old_th.append(th)
    old_fixed = fixed.copy()
    for i in replaced:
        if _plain(flows[i]) is None:
            f = flows[i]
            if f.get("from") in pos:
                old_fixed[pos[f["from"]]] -= amounts[i]
            if f.get("to") in pos:
                old_fixed[pos[f["to"]]] += amounts[i]
    old = _Fit(st, rows, old_fixed, scale, floor)
    th0 = np.concatenate(old_th) if old_th else np.zeros(0)
    old_bic = old.bic(old_free, th0)

    # the free flows, by key: ("mv", src, dst) a move between measured stocks (the answer's; and, absent at
    # first, each move of one unit touching a candidate stock that the answer lacks: the gaps' fit may need a
    # move the program's unfloored fit could not see), (stock, side) a gap; each with its readers ([]: absent)
    ends, rd, cur, orig, optional = {}, {}, {}, {}, set()
    for i in moves:
        d = _plain(flows[i])
        key = ("mv", flows[i]["from"], flows[i]["to"])
        ends[key], rd[key], cur[key] = (flows[i]["from"], flows[i]["to"]), list(d), dict(d)
    for a, b in extra_mv:
        key = ("mv", a, b)
        ends[key], rd[key], cur[key] = (a, b), [], {a: 0.0}
        optional.add(key)
    for s, side, readers in gaps:
        key = (s, side)
        ends[key], rd[key] = ((None, s) if side == "in" else (s, None)), list(readers)
    for s, side, i in cands:
        d = _plain(flows[i]) if i is not None else None
        if d is not None and set(d) <= set(rd[(s, side)]):
            orig[(s, side)] = [x for x in rd[(s, side)] if x in d]
            cur[(s, side)] = dict(d)
    keys = list(rd)

    def amount(coef: dict) -> np.ndarray:
        return np.maximum(sum(k * st.series(x) for x, k in coef.items()) if coef else np.zeros(st.T), 0.0)

    def build(rd: dict, cur: dict) -> tuple[list, np.ndarray]:
        """The free flows for reader sets rd, started from the numbers cur (a gap with none yet: least
        squares on the steps where it acts, against what the rest leaves)."""
        free, th = [], []
        for key in keys:
            r = rd[key]
            if not r:
                continue
            free.append((*ends[key], r))
            if key in cur:
                th.append(np.array([cur[key].get(x, 0.0) for x in r], float))
                continue
            s, side = key
            net = np.zeros(st.T)
            for k2 in keys:
                if k2 == key or k2 not in cur or not rd[k2]:
                    continue
                a = amount({x: v for x, v in cur[k2].items() if x in rd[k2]})
                src, dst = ends[k2]
                net += (a if dst == s else 0.0) - (a if src == s else 0.0)
            want = st.dy[pos[s]] - fixed[pos[s]] - net
            X = np.column_stack([st.series(x) for x in r])
            th.append(_hinge_start(want if side == "in" else -want, X))
        return free, np.concatenate(th) if th else np.zeros(0)

    def unpack(rd: dict, th: np.ndarray) -> dict:
        n, c = 0, {}
        for key in keys:
            c[key] = {x: float(v) for x, v in zip(rd[key], th[n:n + len(rd[key])])}
            n += len(rd[key])
        return c

    def invalid(rd2: dict, t2: np.ndarray) -> list:
        """The free flows that move something on fewer than EVENTS steps, and the gaps (not the answer's own
        rate) whose floor binds (the unfloored rate below 0; for an outflow, while its stock holds something)
        on fewer than EVENTS steps: a floor that never
        acts is a plain linear rate, and the answer's own reading of it is kept."""
        n, bad = 0, []
        for key in keys:
            r = rd2[key]
            if not r:
                continue
            v = sum(k * st.series(x) for k, x in zip(t2[n:n + len(r)], r))
            n += len(r)
            tol = 1e-9 * (np.abs(v).max() + 1e-300)
            binds = v < -tol
            if key[0] != "mv" and key[1] == "out":         # an empty stock moves nothing out anyway: not the floor's doing
                binds &= st.L[pos[key[0]]] > 0
            if int(np.sum(v > tol)) < EVENTS or (key[0] != "mv" and r != orig.get(key) and int(np.sum(binds)) < EVENTS):
                bad.append(key)
        return bad

    def trial(rd2: dict, start: dict):
        """Fitted, with each invalid gap put back to the answer's own readers (inf if that cannot mend it)."""
        for _ in range(len(keys) + 1):
            f2, t2 = build(rd2, start)
            t2 = fit.fit(f2, t2)
            bad = invalid(rd2, t2)
            if not bad:
                return fit.bic(f2, t2), rd2, t2
            mend = [k for k in bad if k in orig and rd2[k] != orig[k]]
            if not mend:
                return np.inf, rd2, t2
            start = {**unpack(rd2, t2), **{k: dict(cur[k]) for k in mend}}
            rd2 = {**rd2, **{k: orig[k] for k in mend}}
        return np.inf, rd2, t2

    starts = [trial(rd, cur), trial({k: orig.get(k, v) for k, v in rd.items()}, cur)]
    if DEBUG:
        for z in starts:
            print("hinge start", z[0], {k: v for k, v in z[1].items() if k[0] != "mv"}, np.round(z[2], 4))
    best, rd, th = min(starts, key=lambda z: z[0])
    for _ in range(4 * MAX_READS + 8):                    # stepwise by BIC: a reader or an optional move out, or a move in
        c = unpack(rd, th)
        step = None
        for key in keys:
            if key[0] == "mv":
                tries = ([[]] if rd[key] else [[key[1]]]) if key in optional else []
            else:
                tries = [[x for x in rd[key] if x != r] for r in rd[key]] if len(rd[key]) > 1 else []
                if key in orig and orig[key] != rd[key]:  # or the answer's own readers, refitted with the floor
                    tries.append(orig[key])
            for new in tries:
                start = {**c, key: (dict(cur[key]) if new == orig.get(key) else c[key] or {x: 0.01 for x in new})}
                got = trial({**rd, key: new}, start)
                if got[0] < best and (step is None or got[0] < step[0]):
                    step = got
        if step is None:
            break
        best, rd, th = step
    note = {"old_bic": round(old_bic, 1), "gap_bic": round(best, 1),
            "gaps": {f"{k[0]}:{k[1]}": [x or "1" for x in v] for k, v in rd.items() if k[0] != "mv"},
            "moves_added": [f"{k[1]}->{k[2]}" for k in sorted(optional) if rd[k]]}
    same = all(rd[k] == orig.get(k) for k in keys if k[0] != "mv") and not any(rd[k] for k in optional)
    if same or not best < old_bic - MARGIN:           # no new gap and no new move: the answer stands as it is
        note["used"] = False
        return flows, note
    c = unpack(rd, th)
    out = [dict(f) for i, f in enumerate(flows) if i not in replaced and i not in moves]
    for key in keys:
        d = {r: v for r, v in c[key].items() if abs(v) > 1e-9}
        if not d:
            continue
        src, dst = ends[key]
        tag = f"{src}->{dst}" if key[0] == "mv" else f"{key[0]}:{key[1]}"
        out.append({"from": src, "to": dst, "ratio": 1, "id": f"milp:gap:{tag}", "rate": _rate(d)})
    note["used"] = True
    return out, note
