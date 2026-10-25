"""An outside inflow through a hidden first-order delay stage (k8s 312, docs/research/fixes/312-structures.md).

A stock S can be fed from outside through a stage the data never show: the cluster autoscaler asks for nodes
for the pods it cannot place, and they join a provisioning delay later (DELAY1: a hidden stock H filled at
g, drained into S at H / tau). S's inflow on a step is then a weighted sum of g over the steps before it, not
a function of the levels at the step, and no rate on S's row can stand in for it: the fits upstream write
S's sides as small drifts on unrelated stocks.

Here, for a measured non-counter stock S with an estimated outside inflow side (any, when no boundary is
declared) whose row the answer leaves far from exact (residual rms above GATE x the data's quantum), its
outside sides are refitted as

    S's inflow  = H_t / tau,   H_{t+1} = H_t + max(0, c + w . X_t) - H_t / tau,   H_0 = h0 >= 0
    S's outflow = max(0, c' + w' . X_t)          (only on a side S may have: the engine's floored rate)

X any measured non-counter level or input (links: they may cross units). For a fixed tau and fixed sets of
steps where each floor is open, S's change is linear in (w, h0, w'), so the numbers come from the same
Gauss-Newton on the hinges as floor.py, with the inflow block's columns passed through the stage's filter.
The columns are chosen forward on BIC (a first step tries pairs: a gap binds only with both sides), on a
coarse grid of tau, then tau is refined by golden section and the columns pruned backward. The same search
with no stage (the inflow g itself on the step) is the alternative the stage must beat: the stage is kept
when its BIC beats both that and the answer's own row by PRICE x log n (tau and h0 are two numbers more).

It is written as a found hidden stock `delay_S` with its two flows (outside -> delay_S at the floored rate,
written as an expression, delay_S -> S at 1 / tau x delay_S) and its estimated level in inferred_levels.
Moves on S are left as they are (their amounts are taken out of the row first).
"""

from __future__ import annotations

import math

import numpy as np

from . import steps
from ._vendored.combined import judge as J
from .hidden import _amount
from .repair import _fixed_side, _numbers, _sign

GATE = 100.0
PRICE = 6.0
MAX_TERMS = 4          # columns per block, beyond the constant
GN_ITERS = 15
TAUS = (1.25, 2.0, 3.0, 5.0, 8.0)
TAU_RANGE = (1.01, 40.0)


def _filt(a: float, V: np.ndarray) -> np.ndarray:
    """H_t = a H_{t-1} + v_{t-1}, H_0 = 0, along axis 0 (the stage's level for inflow v)."""
    from scipy.signal import lfilter

    return lfilter([0.0, 1.0], [1.0, -a], V, axis=0)


class _Row:
    def __init__(self, y: np.ndarray, cols: dict[str, np.ndarray], floor: float, thr: float):
        self.y, self.cols, self.floor, self.thr = y, cols, floor, thr
        self.n = len(y)

    def fit(self, cin: list[str], cout: list[str], tau: float | None):
        """(SSE, numbers) of S's row with the inflow block cin (through the stage when tau) and the outflow
        block cout; None when it cannot be fitted."""
        y, n = self.y, self.n
        if not cin:
            return None
        Ai = np.column_stack([self.cols[k] for k in cin])
        Ao = np.column_stack([self.cols[k] for k in cout]) if cout else np.zeros((n, 0))
        if tau is None:
            a, sc, phi = 0.0, 1.0, np.zeros(n)
        else:
            a, sc = 1.0 - 1.0 / tau, 1.0 / tau
            phi = sc * a ** np.arange(n)
        ki, ko = Ai.shape[1], Ao.shape[1]

        def through(V):
            return V if tau is None else sc * _filt(a, V)

        def pred(th):
            g = np.maximum(0.0, Ai @ th[:ki])
            o = through(g) + (th[ki] * phi if tau is not None else 0.0)
            return o - (np.maximum(0.0, Ao @ th[ki + 1:]) if ko else 0.0)
        # start: the outflow block on the steps the stock falls, the inflow block on the stage's inverse
        wo = np.zeros(ko)
        if ko:
            neg = y < -self.thr
            if neg.sum() > ko:
                wo = np.linalg.lstsq(Ao[neg], -y[neg], rcond=None)[0]
        o = y + (np.maximum(0.0, Ao @ wo) if ko else 0.0)
        g = o if tau is None else np.concatenate([tau * (o[1:] - a * o[:-1]), [0.0]])
        act = g > self.thr
        if act.sum() <= ki:
            return None
        wi = np.linalg.lstsq(Ai[act], g[act], rcond=None)[0]
        th = np.concatenate([wi, [0.0], wo])
        best = (float(np.sum((y - pred(th)) ** 2)), th.copy())
        prev = None
        for _ in range(GN_ITERS):
            ai = (Ai @ th[:ki]) > 0
            ao = (Ao @ th[ki + 1:]) > 0 if ko else np.zeros(n, dtype=bool)
            key = np.concatenate([ai, ao])
            if prev is not None and np.array_equal(key, prev):
                break
            prev = key
            D = [through(Ai * ai[:, None])]
            if tau is not None:
                D.append(phi[:, None])
            if ko:
                D.append(-Ao * ao[:, None])
            D = np.column_stack(D)
            try:
                sol = np.linalg.lstsq(D, y, rcond=None)[0]
            except np.linalg.LinAlgError:
                break
            th = np.concatenate([sol[:ki], [sol[ki] if tau is not None else 0.0], sol[ki + (1 if tau is not None else 0):]])
            if th[ki] < 0:                                # the stage starts empty or above: never below 0
                th[ki] = 0.0
            sse = float(np.sum((y - pred(th)) ** 2))
            if sse < best[0]:
                best = (sse, th.copy())
        k = len(cin) + len(cout) + (2 if tau is not None else 0)
        return best[0], k, best[1]

    def bic(self, got) -> float:
        return self.n * math.log(max(got[0], self.floor) / self.n) + got[1] * math.log(self.n)

    def search(self, tau: float | None, out_ok: bool):
        """Forward selection of both blocks' columns on BIC at this tau: (bic, cin, cout, fit)."""
        names = list(self.cols)
        cin: list[str] = []
        cout: list[str] = []
        best = None
        while len(cin) + len(cout) < 2 * MAX_TERMS:
            tries = []
            for blk in ("in", "out") if out_ok else ("in",):
                cur = cin if blk == "in" else cout
                if len([c for c in cur if c != "1"]) >= MAX_TERMS:
                    continue
                rest = [c for c in names if c not in cur]
                adds = [[c] for c in rest]
                if not cur:
                    adds += [[p, q] for j, p in enumerate(rest) for q in rest[j + 1:]]
                for ad in adds:
                    tries.append((cin + ad, cout) if blk == "in" else (cin, cout + ad))
            step = None
            for ci, co in tries:
                got = self.fit(ci, co, tau)
                if got is None:
                    continue
                b = self.bic(got)
                if step is None or b < step[0]:
                    step = (b, ci, co, got)
            if step is None or (best is not None and not step[0] < best[0]):
                break
            best = step
            cin, cout = step[1], step[2]
        return best

    def prune(self, best, tau):
        b, cin, cout, got = best
        changed = True
        while changed:
            changed = False
            for blk, cur in (("in", cin), ("out", cout)):
                for c in list(cur):
                    ci = [x for x in cin if x != c] if blk == "in" else cin
                    co = [x for x in cout if x != c] if blk == "out" else cout
                    g2 = self.fit(ci, co, tau)
                    if g2 is not None and self.bic(g2) <= b:
                        b, cin, cout, got, changed = self.bic(g2), ci, co, g2, True
                        break
                if changed:
                    break
        return b, cin, cout, got


def _clamped(z: np.ndarray, A: np.ndarray, iS: int, w0: np.ndarray, starts: list[float]) -> tuple[float, np.ndarray, float] | None:
    """z ~ max(0, min(A w, w_S S - m)): a floored gap whose goal has a floor (S above max(L, goal) goes, L = m / w_S),
    S the column iS of A; active-set Gauss-Newton from each start m: (SSE, w, m)."""
    n = len(z)
    S = A[:, iS]
    best = None
    for m0 in starts:
        w, m = w0.copy(), float(m0)
        prev = None
        for _ in range(GN_ITERS):
            r1, r2 = A @ w, w[iS] * S - m
            on = np.minimum(r1, r2) > 0
            two = on & (r2 < r1)
            key = np.concatenate([on, two])
            if prev is not None and np.array_equal(key, prev):
                break
            prev = key
            D = np.zeros((n, A.shape[1] + 1))
            one = on & ~two
            D[one, :A.shape[1]] = A[one]
            D[two, iS] = S[two]
            D[two, -1] = -1.0
            try:
                sol = np.linalg.lstsq(D, z, rcond=None)[0]
            except np.linalg.LinAlgError:
                break
            w, m = sol[:-1], float(sol[-1])
        pred = np.maximum(0.0, np.minimum(A @ w, w[iS] * S - m))
        sse = float(np.sum((z - pred) ** 2))
        if best is None or sse < best[0]:
            best = (sse, w.copy(), m)
    return best


def _floor_goal(row: "_Row", S: str, cin: list[str], cout: list[str], tau: float, got) -> tuple | None:
    """The outflow block refitted as a gap whose goal has a floor (_clamped), its columns chosen forward on BIC
    with S always in, the inflow block and the stage held: (bic, cout, w, m, sse) or None."""
    if S not in row.cols:
        return None
    n, th = row.n, got[2]
    ki = len(cin)
    a = 1.0 - 1.0 / tau
    Ai = np.column_stack([row.cols[k] for k in cin])
    o_in = _filt(a, np.maximum(0.0, Ai @ th[:ki])) / tau + th[ki] * a ** np.arange(n) / tau
    z = o_in - row.y                                    # what the outflow carries
    names = [k for k in row.cols]

    def fit(use):
        A = np.column_stack([row.cols[k] for k in use])
        w0 = np.linalg.lstsq(A[z > row.thr], z[z > row.thr], rcond=None)[0] if (z > row.thr).sum() > len(use) else np.zeros(len(use))
        iS = use.index(S)
        if w0[iS] <= 0:
            return None
        goal = row.cols[S] - (A @ w0) / w0[iS]
        starts = [w0[iS] * float(np.quantile(goal, p)) for p in (0.02, 0.05, 0.1, 0.2, 0.35, 0.5)]
        r = _clamped(z, A, iS, w0, starts)
        if r is None or r[1][iS] <= 0:
            return None
        return n * math.log(max(r[0], row.floor) / n) + (len(use) + 1 + ki + 2) * math.log(n), use, r[1], r[2], r[0]
    best = None
    cur = [S]
    while len(cur) <= MAX_TERMS:
        tries = [cur + [c] for c in names if c not in cur]
        if len(cur) == 1:
            tries += [cur + [p, q] for j, p in enumerate(names) for q in names[j + 1:] if S not in (p, q)]
        step = None
        for use in tries:
            r = fit(use)
            if r is not None and (step is None or r[0] < step[0]):
                step = r
        if step is None or (best is not None and not step[0] < best[0]):
            break
        best, cur = step, list(step[1])
    return best


def _golden(f, lo: float, hi: float, iters: int = 30) -> float:
    a, b = math.log(lo), math.log(hi)
    for _ in range(iters):
        c, d = b - 0.618 * (b - a), a + 0.618 * (b - a)
        if f(math.exp(c)) < f(math.exp(d)):
            b = d
        else:
            a = c
    return math.exp(0.5 * (a + b))


def _hinge_text(c: float, terms: list[tuple[str, float]]) -> str:
    body = " + ".join([repr(float(c))] + [f"{float(k)!r} * {_col_text(s)}" for s, k in terms])
    return f"max(0, {body})"


SUB = "sub:"           # a column that is a floored term of the answer's own expressions


def _col_text(name: str) -> str:
    return f"({name[len(SUB):]})" if name.startswith(SUB) else name


def _subterms(flows: list[dict], X: dict, n: int) -> dict[str, np.ndarray]:
    """The floored linear terms `max(0, ...)` the answer's expression rates already carry (a room a capacity
    leaves, room.py; a gap), as columns: what fills a stage may read what the answer already computes (312:
    the autoscaler asks for the pods the room the nodes leave cannot take)."""
    import re

    from . import exprs

    out: dict[str, np.ndarray] = {}
    for f in flows:
        r = f.get("rate") or {}
        if r.get("form") != "expr":
            continue
        for m in re.finditer(r"max\(0, [^()]+\)", str(r.get("expr") or "")):
            text = m.group(0)
            if SUB + text in out:
                continue
            v = exprs.amount(text, X, n)
            if v is not None and np.ptp(v) > 0:
                out[SUB + text] = np.asarray(v, dtype=float)
    return out


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "delay": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    steps.adjust(X, dy, run, opts, n)
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = max(n * q * q / 12.0, 1e-300)
    finals = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = list(result["flows"])
    price = PRICE * math.log(n)
    base_cols = {"1": np.ones(n), **{k: X[k] for k in X if k not in finals and np.ptp(X[k]) > 0}, **_subterms(flows, X, n)}
    notes, inferred = [], {}
    for S in ids:
        if S in finals or np.ptp(L[S]) <= 0:
            continue
        sides = bound.get(S) or {}

        def kinds(side):
            k = sides.get(side) or []
            return [k] if isinstance(k, str) else list(k)
        in_ok = (not declared) or "estimate" in kinds("in")
        on = [f for f in flows if S in (f.get("from"), f.get("to"))]
        outs = [f for f in on if (f.get("from") is None or f.get("to") is None) and not _fixed_side(f, bound, declared)]
        out_ok = ("estimate" in kinds("out")) if declared else any(f.get("from") == S for f in outs)
        if not in_ok:
            continue
        amts = [_amount(f, X, n) for f in on]
        if any(a is None for a in amts):
            continue
        r_cur = dy[S] - sum((_sign(f, S) * a for f, a in zip(on, amts)), np.zeros(n))
        if not float(np.sqrt(np.mean(r_cur * r_cur))) > GATE * q:
            continue
        y = r_cur + sum((_sign(f, S) * a for f, a in zip(on, amts) if any(f is g for g in outs)), np.zeros(n))
        plain_outs = [i for i, f in enumerate(flows) if any(f is g for g in outs) and (f.get("rate") or {}).get("form") in ("constant", "proportional", "linear")]
        k_cur = _numbers(flows, plain_outs) + 2 * (len(outs) - len(plain_outs))
        row = _Row(y, base_cols, floor, max(0.5 * q, 1e-9 * float(np.max(np.abs(y)) or 1.0)))
        bic_cur = n * math.log(max(float(r_cur @ r_cur), floor) / n) + k_cur * math.log(n)
        undelayed = row.search(None, out_ok)
        best = None
        for tau in TAUS:
            got = row.search(tau, out_ok)
            if got is not None and (best is None or got[0] < best[0][0]):
                best = (got, tau)
        note = {"stock": S, "bic_current": round(bic_cur, 1), "bic_no_stage": round(undelayed[0], 1) if undelayed else None, "kept": False}
        if best is None:
            notes.append(note)
            continue
        (b, cin, cout, got), tau = best
        tau = _golden(lambda t: (lambda g: row.bic(g) if g else math.inf)(row.fit(cin, cout, t)), max(TAU_RANGE[0], tau / 2), min(TAU_RANGE[1], tau * 2))
        b, cin, cout, got = row.prune((row.bic(row.fit(cin, cout, tau)), cin, cout, row.fit(cin, cout, tau)), tau)
        note.update({"bic_stage": round(b, 1), "tau": tau, "in": cin, "out": cout})
        if not (b < bic_cur - price and (undelayed is None or b < undelayed[0] - price)):
            notes.append(note)
            continue
        th = got[2]
        ki = len(cin)
        wi, h0, wo = th[:ki], float(th[ki]), th[ki + 1:]
        # the outflow's goal may have a floor (312 none-long: nodes go above max(2, pods / 2); the floor binds on 84
        # of 1999 steps): kept when it beats the plain floored gap by PRICE x log n
        clamp = _floor_goal(row, S, cin, cout, tau, got) if out_ok else None
        if clamp is not None and clamp[0] < b - price:
            note["goal_floor"] = {"bic": round(clamp[0], 1), "out": list(clamp[1]), "floor": clamp[3] / clamp[2][list(clamp[1]).index(S)]}
            cout, wo = list(clamp[1]), clamp[2]
        H = f"delay_{S}"
        c_in = sum(float(w) for c, w in zip(cin, wi) if c == "1")
        t_in = [(c, float(w)) for c, w in zip(cin, wi) if c != "1"]
        new = [{"id": f"delay_{S}_in", "from": None, "to": H, "ratio": 1, "rate": {"form": "expr", "expr": _hinge_text(c_in, t_in)}},
               {"id": f"delay_{S}_stage", "from": H, "to": S, "ratio": 1, "rate": {"form": "proportional", "stock": H, "k": 1.0 / tau}}]
        if cout:
            c_out = float(sum(float(w) for c, w in zip(cout, wo) if c == "1"))
            t_out = [(c, float(w)) for c, w in zip(cout, wo) if c != "1"]
            if "goal_floor" in note:
                body = " + ".join([repr(c_out)] + [f"{w!r} * {_col_text(c)}" for c, w in t_out])
                wS = float(dict(t_out)[S])
                note["goal_floor"]["floor"] = float(note["goal_floor"]["floor"])
                rate = {"form": "expr", "expr": f"max(0, min({body}, {wS!r} * {S} - {float(wS * note['goal_floor']['floor'])!r}))"}
            elif any(c.startswith(SUB) for c, _ in t_out):
                rate = {"form": "expr", "expr": _hinge_text(c_out, t_out)}
            else:
                rate = {"form": "linear", "c": c_out, "terms": [{"stock": c, "k": w} for c, w in t_out]}
            new.append({"id": f"delay_{S}_out", "from": S, "to": None, "ratio": 1, "rate": rate})
        g = np.maximum(0.0, np.column_stack([base_cols[c] for c in cin]) @ wi)
        a = 1.0 - 1.0 / tau
        level = _filt(a, g) + h0 * a ** np.arange(n)
        inferred[H] = [float(v) for v in level] + [float(a * level[-1] + g[-1])]
        flows = [f for f in flows if not any(f is o for o in outs)] + new
        note.update({"kept": True, "start": h0})
        notes.append(note)
    if not notes:
        return result
    out = {**result, "flows": flows, "delay": notes}
    if inferred:
        out["inferred_levels"] = {**(result.get("inferred_levels") or {}), **inferred}
    return out
