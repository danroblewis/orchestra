"""NO-TRUTH machinery shared by the evidence checks of notruth.py: the discovery view on a step grid, a
found model compiled for one-step and multi-step prediction, its Kalman innovations, and a refit of its
numbers on part of the run.

**No truth.** Everything here gets only the discovery view (what `identify(stocks, run, opts)` gets:
stocks, t, levels, eras, injections, inputs) and found flows. `check_view` asserts it, as the unified
evaluator's leakage guard does (sdlab/discovery/strategies/unified/frontend.py, copied at 4747340, not
imported: that package is another workflow's). tests/test_notruth.py checks that this module and
notruth.py import nothing that reads the truth, the case, the store or hidden stocks.

**Grid.** Every whole time from the first report to the last; a time without a report (gaps, weekly)
is nan. The nominal path X (every stock of the found model at every grid time) is the measured levels
(linearly interpolated over missing reports) and the found model's own unmeasured stocks stepped with
the measured ones held at X (discovery/observer.py's estimate, here with inputs and injections).

**Innovations.** The model linearised along X (F_k = d step / d x at X[:, k-1], by finite differences in
one vectorised call) is filtered with a Kalman filter whose noise is estimated from the data by moments
of the clamped one-step errors e_k = y_k - f(X_(k-1)): for a right mean model e_k = w_k + v_k - F v_(k-1),
so lag-1 covariance -F R gives each measured stock's report noise R and lag 0 the process noise Q. On
data without report noise R goes to its floor (quantum^2 / 12) and the filter is the clamped one-step
prediction. Weekly means are treated as points (a limit).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np

from ..discovery.observer import unmeasured
from . import sim as _sim

VIEW_KEYS = {"stocks", "t", "levels", "eras", "injections", "inputs"}
FORBIDDEN = {"all_levels", "counters", "clean", "observation", "truth", "case", "seed", "id", "variant", "hidden"}
QUANTA = (1.0, 0.1, 0.01, 1e-3, 1e-4, 1e-5, 1e-6)
BURN = 10                     # innovations dropped at the start (the filter settling)


def check_view(view: dict) -> None:
    """The leakage guard: a check gets the discovery view and nothing else."""
    bad = set(view) & FORBIDDEN
    assert not bad, f"a NO-TRUTH check was given what discovery never sees: {sorted(bad)}"
    extra = set(view) - VIEW_KEYS
    assert not extra, f"a NO-TRUTH check was given keys outside the discovery view: {sorted(extra)}"
    measured = {s["id"] for s in view["stocks"]}
    assert set(view["levels"]) <= measured, "levels of stocks the page does not list (hidden stocks?)"


def check_flows(flows: list[dict]) -> None:
    assert isinstance(flows, list) and all(isinstance(f, dict) for f in flows), "flows must be a list of flow dicts"


def quantum(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    for q in QUANTA:
        if x.size == 0 or np.abs(x / q - np.round(x / q)).max() < 1e-6:
            return q
    return 1e-7


@dataclass
class Grid:
    ids: list[str]                       # measured stocks
    times: np.ndarray                    # every whole time, first report .. last
    y: np.ndarray                        # measured x grid (nan: no report)
    Yi: np.ndarray                       # y interpolated over missing reports
    inputs: dict | None                  # simulate.Model's inputs {"t", "values"} (view t)
    input_grid: dict[str, np.ndarray]    # each input's value at each grid time (the step into it)
    injections: list[dict]
    eras: list[dict]
    q: np.ndarray                        # each stock's quantum
    level: np.ndarray                    # each stock's level scale: mean |y| + q
    seen: np.ndarray = field(default=None)   # grid indices with every measured stock reported


def build_grid(view: dict) -> Grid:
    check_view(view)
    t = [int(round(float(x))) for x in view["t"]]
    ids = [s["id"] for s in view["stocks"] if s["id"] in view["levels"]]
    times = np.arange(t[0], t[-1] + 1)
    pos = np.asarray(t) - t[0]
    y = np.full((len(ids), len(times)), np.nan)
    for i, s in enumerate(ids):
        v = np.array([np.nan if x is None else float(x) for x in view["levels"][s]], dtype=float)
        y[i, pos] = v
    Yi = y.copy()
    for i in range(len(ids)):
        ok = np.isfinite(y[i])
        Yi[i] = np.interp(times, times[ok], y[i, ok]) if ok.any() else 0.0
    inputs, input_grid = None, {}
    if view.get("inputs"):
        inputs = {"t": t, "values": {k: list(v) for k, v in view["inputs"].items()}}
        for k, v in view["inputs"].items():
            arr = np.nan_to_num(np.asarray(v, dtype=float))
            idx = np.clip(np.searchsorted(np.asarray(t, float), times.astype(float), side="right") - 1, 0, len(arr) - 1)
            input_grid[k] = arr[idx]
    q = np.array([quantum(y[i]) for i in range(len(ids))])
    level = np.array([np.nanmean(np.abs(y[i])) if np.isfinite(y[i]).any() else 1.0 for i in range(len(ids))]) + q
    g = Grid(ids, times, y, Yi, inputs, input_grid, list(view.get("injections") or []), list(view.get("eras") or []), q, level)
    g.seen = np.flatnonzero(np.all(np.isfinite(y), axis=0))
    return g


class Compiled:
    """A found model on a grid: its stocks (measured, then its own unmeasured ones), stepping with the
    measured inputs and the announced injections."""

    def __init__(self, flows: list[dict], grid: Grid):
        check_flows(flows)
        self.flows, self.g = flows, grid
        self.hidden = unmeasured(flows, grid.ids)
        self.ids = list(grid.ids) + self.hidden
        self.S, self.D = len(grid.ids), len(self.ids)
        self.model = _sim.found_model(flows, self.ids, inputs=grid.inputs)
        index = {s: i for i, s in enumerate(self.ids)}
        self.pulses = [(int(j["t"]), index[j["stock"]], float(j["amount"])) for j in grid.injections if j.get("stock") in index]

    def advance(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        """One step into times t (one per column of L), the injections at t added first."""
        if self.pulses:
            L = L.copy()
            for tj, i, a in self.pulses:
                hit = t == tj
                if hit.any():
                    L[i, hit] = np.maximum(0.0, L[i, hit] + a)
        return self.model.step(L, t.astype(float))

    def gross(self, L: np.ndarray, t: np.ndarray) -> np.ndarray:
        """What flows through each measured stock in one step into times t from L (sum of |amount| of the
        flows into and out of it; injections added first): counting noise grows with it."""
        if self.pulses:
            L = L.copy()
            for tj, i, a in self.pulses:
                hit = t == tj
                if hit.any():
                    L[i, hit] = np.maximum(0.0, L[i, hit] + a)
        amounts = self.model._amounts(L, t.astype(float))
        G = np.zeros((self.S, L.shape[1]))
        for (src, dst, *_), a in zip(self.model.parts, amounts):
            for c in (src, dst):
                if c is not None and c < self.S:
                    G[c] += np.abs(np.nan_to_num(a))
        return G

    def run(self, L: np.ndarray, t0: np.ndarray, h: int) -> np.ndarray:
        """Levels h steps after states L at times t0 (one per column): stocks x columns x h (every step)."""
        out = np.empty((L.shape[0], L.shape[1], h))
        for s in range(h):
            L = self.advance(L, t0 + s + 1)
            out[:, :, s] = L
        return out

    def nominal(self) -> np.ndarray:
        """X: measured stocks at their (interpolated) reports, own unmeasured ones observed."""
        g = self.g
        N = len(g.times)
        X = np.zeros((self.D, N))
        X[: self.S] = g.Yi
        if self.hidden:
            L = X[:, :1].copy()
            for k in range(1, N):
                L[: self.S, 0] = X[: self.S, k - 1]
                L = self.advance(L, g.times[k: k + 1])
                X[self.S:, k] = L[self.S:, 0]
        return X

    def one_step(self, X: np.ndarray) -> np.ndarray:
        """Predictions for grid 1..N-1 from X at 0..N-2 (D x N-1)."""
        return self.advance(X[:, :-1], self.g.times[1:])

    def jacobians(self, X: np.ndarray) -> np.ndarray:
        """F_k = d step / d x at X[:, k-1], k = 1..N-1 (N-1 x D x D), one-sided upwards differences."""
        D, N = X.shape
        B = X[:, :-1]
        h = 1e-6 * np.maximum(1.0, np.abs(B))
        L = np.repeat(B[:, :, None], D + 1, axis=2)              # D x (N-1) x (D+1)
        for j in range(D):
            L[j, :, j + 1] += h[j]
        t = np.repeat(self.g.times[1:, None], D + 1, axis=1)
        out = self.advance(L.reshape(D, -1), t.reshape(-1)).reshape(D, N - 1, D + 1)
        J = (out[:, :, 1:] - out[:, :, :1]) / h.T[None, :, :]     # [i, k, j]
        return np.transpose(J, (1, 0, 2))


@dataclass
class Innovations:
    z: np.ndarray            # standardized innovations, measured x grid (nan where none)
    e: np.ndarray            # raw innovations
    sd: np.ndarray           # their predicted sd
    R: np.ndarray            # estimated report noise variance, measured x grid
    Q: np.ndarray            # estimated process noise variance, measured x grid
    clamped: np.ndarray      # clamped one-step errors (measured x grid)
    how: str
    M: np.ndarray            # filtered levels of every stock of the model (D x grid): data up to each time only


def _moments(e: np.ndarray, F: np.ndarray, Y: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Report noise R and process noise Q per measured stock and grid time, from the clamped one-step
    errors: R_k = r0 + r1 y_k^2 (absolute and relative report error), Q_k = q0 + q1 |y_(k-1)| (counting
    noise grows with what flows), by non-negative least squares on the lag-1 and lag-0 products."""
    from scipy.optimize import nnls
    S, N = Y.shape
    R, Q = np.zeros((S, N)), np.zeros((S, N))
    for i in range(S):
        x = e[i]
        floor = q[i] ** 2 / 12
        ok = np.flatnonzero(np.isfinite(x[2:]) & np.isfinite(x[1:-1])) + 2       # pairs (k, k-1), k >= 2
        if ok.size < 10:
            v = float(np.nanmean(x ** 2)) if np.isfinite(x).any() else 1.0
            R[i], Q[i] = floor, max(v, floor)
            continue
        f = float(np.nanmedian(F[:, i, i])) if F.size else 1.0
        y2 = Y[i] ** 2
        sc2 = max(float(np.mean(y2[ok])), 1e-300)
        prod = x[ok] * x[ok - 1]
        A = np.column_stack([np.ones(ok.size), y2[ok - 1] / sc2])          # -E[e_k e_(k-1)] = f R_(k-1)
        r, _ = nnls(A * max(f, 0.05), -prod) if f > 0.05 else (np.zeros(2), 0)
        Rk = np.maximum(r[0] + r[1] * y2 / sc2, floor)
        sq = x[ok] ** 2 - Rk[ok] - f * f * Rk[ok - 1]
        ya = np.abs(Y[i, ok - 1])
        sca = max(float(np.mean(ya)), 1e-300)
        qq, _ = nnls(np.column_stack([np.ones(ok.size), ya / sca]), sq)
        Qk = qq[0] + qq[1] * np.abs(np.concatenate([Y[i, :1], Y[i, :-1]])) / sca
        tot = float(np.mean(x[ok] ** 2))
        R[i] = np.minimum(Rk, tot)
        Q[i] = np.maximum(Qk, max(1e-6 * tot, 1e-12))
    return R, Q


def innovations(c: Compiled, X: np.ndarray | None = None, fit_noise: bool = True) -> Innovations:
    """The Kalman innovations of the found model (module docstring)."""
    g = c.g
    X = c.nominal() if X is None else X
    P1 = c.one_step(X)
    S, D, N = c.S, c.D, X.shape[1]
    clamped = np.full((S, N), np.nan)
    clamped[:, 1:] = g.y[:, 1:] - P1[:S]
    F = c.jacobians(X)
    F = np.where(np.isfinite(F), F, 0.0)
    R0, Q0 = _moments(clamped, F, g.Yi, g.q)
    from . import notruth_kf as kfm
    lev = g.Yi.copy()
    lev[:, 1:] = P1[:S]
    noise = kfm.Noise(g.y, lev, clamped, g.q, D, 1e-6 * float(np.max(g.level) ** 2))
    th0 = noise.start(R0, Q0)
    P0 = np.diag(np.concatenate([R0[:, 0], (np.max(g.level) ** 2) * np.ones(D - S)]))
    th, ll, ok = kfm.fit(F, P1, X, g.y, noise, th0, P0) if fit_noise else (th0, float("nan"), False)
    R, Qm = noise.RQ(th)
    ll, e, sd, M = kfm.kf(F, P1, X, g.y, R, Qm, P0, kfm.BURN)
    Qm = Qm[:S]
    if not np.isfinite(ll) or not np.isfinite(e[:, -1][np.isfinite(g.y[:, -1])]).all():
        M = X.copy()
        e = clamped.copy()
        sd = np.sqrt(Qm + 2 * R)
        how = "clamped (the filter diverged)"
    else:
        how = ("kalman, noise by maximum likelihood" + ("" if ok else " (not converged)")) if fit_noise else "kalman, noise by moments"
    e[:, : BURN + 1] = np.nan
    z = e / sd
    return Innovations(z, e, sd, R, Qm, clamped, how, np.maximum(M, 0.0))


# ---- the found structure's numbers ----

RATE_KEYS = {"constant": ("value",), "proportional": ("k",), "gap": ("goal", "time"), "linear": ("c",)}


@dataclass
class Leaf:
    path: tuple              # where the number sits in the flows
    value: float
    span: tuple | None       # (from, to) times when the number applies (a piece), or None (all run)
    name: str                # readable: "flow 2 (a -> b) k" etc.


def _flow_name(f: dict, i: int) -> str:
    return f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}" + (f" [{f['id']}]" if f.get("id") else f" [#{i}]")


def _rate_leaves(r: dict, base: tuple, span, fname: str) -> list[Leaf]:
    out = []
    form = (r or {}).get("form")
    for k in RATE_KEYS.get(form, ()):
        if isinstance(r.get(k), (int, float)):
            out.append(Leaf(base + (k,), float(r[k]), span, f"{fname} {k}"))
    if form == "linear":
        for m, term in enumerate(r.get("terms") or []):
            if isinstance(term.get("k"), (int, float)):
                out.append(Leaf(base + ("terms", m, "k"), float(term["k"]), span, f"{fname} k[{term.get('stock')}]"))
    return out


def leaves(flows: list[dict]) -> list[Leaf]:
    """Every number of the found structure that a refit can move: rate numbers (per piece) and outside
    inflow piece values. Effect tables, ratios and co-flow numbers are held (a limit)."""
    out = []
    for i, f in enumerate(flows):
        name = _flow_name(f, i)
        if f.get("inflow"):
            for j, s in enumerate(f["inflow"]):
                out.append(Leaf((i, "inflow", j, "value"), float(s["value"]), (s["from"], s["to"]), f"{name} inflow piece {s['from']}-{s['to']}"))
        elif f.get("byTime"):
            for j, s in enumerate(f["byTime"]):
                out += _rate_leaves(s.get("rate") or {}, (i, "byTime", j, "rate"), (s["from"], s["to"]), f"{name} piece {s['from']}-{s['to']}")
        else:
            out += _rate_leaves(f.get("rate") or {}, (i, "rate"), None, name)
    return out


def set_leaves(flows: list[dict], lv: list[Leaf], values) -> list[dict]:
    out = copy.deepcopy(flows)
    for leaf, v in zip(lv, values):
        node = out
        for p in leaf.path[:-1]:
            node = node[p]
        node[leaf.path[-1]] = float(v)
    return out


def active(leaf: Leaf, t_lo: float, t_hi: float, min_steps: int = 10) -> bool:
    if leaf.span is None:
        return True
    a, b = max(leaf.span[0], t_lo), min(leaf.span[1], t_hi)
    return b - a + 1 >= min_steps


@dataclass
class Fit:
    values: np.ndarray       # every leaf's value (held ones at their found value)
    se: np.ndarray           # standard errors (nan for held ones)
    fitted: np.ndarray       # bool per leaf
    n: int
    ok: bool
    note: str = ""
    corr: np.ndarray | None = None     # correlation of the fitted numbers' errors (nan for held ones)


def refit(flows: list[dict], grid: Grid, X: np.ndarray, rows: np.ndarray, weights: np.ndarray, lv: list[Leaf] | None = None) -> Fit:
    """Refit the found structure's numbers on the one-step errors into grid indices `rows` (each > 0,
    from the path X: measured stocks at their reports; the model's own unmeasured stocks start from X at
    the first row and are re-observed with each trial's numbers, measured ones held at X),
    each measured stock's errors divided by `weights` times their counting scale (_count_scale). SE: the
    larger of the model-based one and the Newey-West HC3 sandwich (_sandwich), so neither one step that
    decides a number alone (no residual left to see its noise) nor misspecified noise makes it too small."""
    from scipy.optimize import least_squares
    lv = leaves(flows) if lv is None else lv
    v0 = np.array([leaf.value for leaf in lv], dtype=float)
    rows = np.asarray(rows, dtype=int)
    rows = rows[rows > 0]
    if rows.size == 0 or not lv:
        return Fit(v0, np.full(len(lv), np.nan), np.zeros(len(lv), bool), int(rows.size), False, "nothing to fit")
    t_lo, t_hi = grid.times[rows.min()], grid.times[rows.max()]
    act = np.array([active(leaf, t_lo, t_hi) for leaf in lv])
    if not act.any():
        return Fit(v0, np.full(len(lv), np.nan), act, int(rows.size), False, "no number applies here")
    idx = np.flatnonzero(act)
    S = grid.y.shape[0]
    Y = grid.y[:, rows]
    ok = np.isfinite(Y)
    w = np.where(weights > 0, weights, 1.0)[:, None] * _count_scale(Compiled(flows, grid), X, rows)

    span = np.arange(rows.min(), rows.max() + 1)

    def resid(p):
        vals = v0.copy()
        vals[idx] = p
        c = Compiled(set_leaves(flows, lv, vals), grid)
        A = X[: c.D]
        if c.hidden:                    # its own unmeasured stocks re-observed with these numbers over the rows
            A = A.copy()
            L = A[:, span[0] - 1: span[0]].copy()
            for k in span:
                L[:S, 0] = A[:S, k - 1]
                L = c.advance(L, grid.times[k: k + 1])
                A[S:, k] = L[S:, 0]
        P = c.advance(A[:, rows - 1], grid.times[rows])[:S]
        r = (Y - P) / w
        return np.where(ok, np.nan_to_num(r, nan=0.0, posinf=1e6, neginf=-1e6), 0.0).ravel()

    lo = np.array([1e-9 if lv[i].path[-1] == "time" else -np.inf for i in idx])
    p0 = np.clip(v0[idx], lo, np.inf)
    try:
        sol = least_squares(resid, p0, bounds=(lo, np.full(len(idx), np.inf)), x_scale="jac", max_nfev=200)
    except Exception as err:                                    # noqa: BLE001
        return Fit(v0, np.full(len(lv), np.nan), act, int(rows.size), False, f"refit failed: {err}")
    vals = v0.copy()
    vals[idx] = sol.x
    r = sol.fun
    n_obs = int(ok.sum())
    J = sol.jac
    se = np.full(len(lv), np.nan)
    corr = np.full((len(lv), len(lv)), np.nan)
    try:
        cov = _sandwich(J, r, S, n_obs, len(idx))
        # model-based: the stocks' errors at one step share a covariance (a move's counting draw leaves one
        # stock and enters another; each stock has its own variance), the same at every step
        R2 = r.reshape(S, -1)
        Jt = J.reshape(S, R2.shape[1], -1)
        Sig = (R2 @ R2.T) / max(1, R2.shape[1]) * (n_obs / max(1, n_obs - len(idx)))
        bread = np.linalg.pinv(J.T @ J)
        meat = np.einsum("itp,ij,jtq->pq", Jt, Sig, Jt)
        model_based = bread @ meat @ bread
        d = np.sqrt(np.maximum(np.maximum(np.diag(cov), np.diag(model_based)), 0.0))
        se[idx] = d
        with np.errstate(invalid="ignore", divide="ignore"):
            corr[np.ix_(idx, idx)] = cov / np.outer(d, d)
    except np.linalg.LinAlgError:
        pass
    return Fit(vals, se, act, n_obs, bool(sol.success or sol.status > 0), corr=corr)


def _count_scale(c: Compiled, X: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Each one-step error's relative sd under counting noise (variance half constant, half growing with
    the gross flow through the stock that step), normalised to a typical step's: a pulse or an injection
    step is noisier, and weighs less."""
    G = c.gross(X[: c.D, rows - 1], c.g.times[rows])
    m = np.median(G, axis=1, keepdims=True)
    f = np.where(m > 0, G / np.where(m > 0, m, 1.0), 1.0)
    return np.sqrt(0.5 + 0.5 * f)


def _sandwich(J: np.ndarray, r: np.ndarray, S: int, n_obs: int, p: int, lags: int = 5) -> np.ndarray:
    """Newey-West sandwich covariance of least-squares numbers with HC3 residuals (each divided by 1 - its
    leverage): robust to errors whose variance changes from step to step (counting noise grows with what
    flows, e.g. at a pulse or an injection), to a few steps that decide a number almost alone, and to
    serial correlation (5 lags); residuals stacked stock by stock over the same times."""
    T = r.size // S
    bread = np.linalg.pinv(J.T @ J)
    lev = np.einsum("ij,jk,ik->i", J, bread, J)                  # leverage of each error
    ra = r / np.maximum(1.0 - lev, 0.05)                          # HC3: a step that decides a number alone
    g = (J.reshape(S, T, -1) * ra.reshape(S, T)[:, :, None]).sum(axis=0)       # score per time
    meat = g.T @ g
    for h in range(1, lags + 1):
        c = g[h:].T @ g[:-h]
        meat += (1 - h / (lags + 1)) * (c + c.T)
    return bread @ meat @ bread


def robust_sd(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size < 3:
        return float("nan")
    s = 1.4826 * float(np.median(np.abs(x - np.median(x))))
    return s if s > 0 else float(np.std(x))


def finite(x):
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None
