# A copy, one per strategy that uses it (sdlab/CLAUDE.md invariant 11: no strategy imports another).
# tests/test_oe_copies.py checks that the copies are identical. docs/research/k8s-306-r3-five.md.
"""State space: where the levels carry measurement error, the found model refined on a Kalman likelihood.

A one-step fit regresses each stock's change on the levels before it. With measurement error in the
levels the regressors are noisy, so the numbers are biased, a kink (a MIN) is lost in the noise, and
the structure is chosen on the biased fit (docs/research/k8s-306-s1.md, round 2). On the ladder the
measured levels are a counting run with measurement error laid on it, so both noises are in the data:
an extended Kalman filter carries counting noise in every flow (variance = its amount, as Poisson
counts) and measurement error of variance a + b x level^2 in every measured level, and gives the
likelihood of the levels with no noisy regressor (docs/research/k8s-306-r3-five.md: on 306 meas it prices
the true structure far below every strategy's one-step answer).

1. Gate: some measured stock's one-step residuals under the found model are negatively correlated
   from one step to the next beyond chance (p < ALPHA over the stocks): what white measurement error
   leaves (counting noise leaves them white; a structure that misses something leaves them smooth).
   Elsewhere the answer is returned unchanged.
2. Noise, first: each stock's a and b from the lag-1 covariance of its one-step residuals (white
   measurement error gives E[e_t e_{t-1}] = -var at the level), without negative parts. It is not
   fitted on the found model: fitted on a wrong model, a stock's measurement variance takes in what
   the model misses (a counter's missing inflow) and the search no longer sees it.
3. Greedy search on the first SEARCH_T steps, priced by Bayes (-2 log-likelihood plus log n per number,
   n the measured values):
   - drop a flow;
   - a flow's constant becomes a share of its source (a declared flow too: it stays, its form changes);
   - add a move X -> R in proportion to X (X not final; R measured, or outside where the boundary
     allows an outflow of X);
   - send a flow elsewhere (another receiver), or take it from the stock its rate reads (joined to
     the flow already there between the same stocks), or move its source, or pass it through another
     stock (X -> R becomes X -> R' and R' -> R in proportion to R');
   - limit a flow: a term k x X of a flow out of X becomes MIN(k x X, b x Y), Y another measured stock
     that is not final, or an input (306's capacity: the cap is fitted with the rest, never offered
     from the noisy levels). Each side must bind on at least REGIME of the steps: a MIN that does not
     switch is a link in disguise, not a limit.
   Every candidate is screened with a few iterations of the fit (all its numbers free) on the first
   SCREEN_T steps; the best few are fitted fully; the best one is made if it lowers the price. Repeat
   while one does (at most ROUNDS).
4. The measurement noise is then fitted (with the numbers, on the whole run) on the model the search
   reached, and the search runs again.
5. The numbers are fitted on the whole run (L-BFGS-B, finite differences; a fit that ends above its
   start keeps the start).
Steps 3-5 run from two starts of the same fit: the found structure, and the found structure with each
flow whose rate is one term on another stock taken from that stock (a flow drains what it reads); the
lower final price is kept. This is a multi-start of one search, labelled as such, not a choice between
two strategies' answers. The refined model replaces the answer if its price on the whole run is below
the found model's own (its numbers kept).

The engine's rules are kept: injections at the start of a step, rates floored at 0, a stock's outflows
share what it holds (a share of the source is bounded at 1 a step: the engine clips more, so more is
not identified; shares that saturate are written scaled to sum to 1), the input read at the step's
own time.

The declared boundary is kept: a declared outside flow is never dropped or moved, an outside inflow is
never added, an "input" inflow keeps its fixed gain (1 x the input), and an outflow to outside is
added only on a side the boundary declares (and below the count it declares).

Forms it can run: proportional, linear (a constant and terms on stocks or inputs), constant, and an
expression of such terms and MIN(a x X, b x Y). A model with anything else (pieces, eras, effects,
co-flows, two-way flows, hidden stocks, a stock nobody measures) is returned unchanged.
"""

from __future__ import annotations

import copy
import math
import re

import numpy as np
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm

ALPHA = 1e-3      # the white-noise test's level (one-sided, over the stocks)
ROUNDS = 8        # greedy rounds at most
SCREEN = 6        # iterations of a candidate's screening fit
SCREEN_T = 400    # steps a candidate is screened on (the first ones)
SEARCH_T = 600    # steps the structure is searched on (the first ones); the numbers are fitted on all
FINALISTS = 3     # candidates fitted fully per round
FULL = 40         # iterations of a full fit
SHARE = (0.3,)    # the starting cap: b so the MIN binds on this share of the steps
REGIME = 0.05     # each side of a MIN binds on at least this share of the steps (else it is a link, not a limit)


class Unsupported(Exception):
    pass


# --- the model, flat ----------------------------------------------------------------------------
# A model is a list of flows {src, dst, comps}; src/dst a stock index or -1 (outside); comps a list
# of ("c", p) | ("t", v, p) | ("m", vx, pa, vy, pb), v a variable (stock index, or n + input index),
# p an index into the numbers. The numbers carry `fixed` (held) beside them.

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _parse_expr(expr: str) -> list[tuple]:
    out = []
    for part in [p.strip() for p in re.split(r"\s\+\s", expr)]:
        m = re.fullmatch(rf"min\(\s*({_NUM})\s*\*\s*(\w+)\s*,\s*({_NUM})\s*\*\s*(\w+)\s*\)", part)
        if m:
            out.append(("m", m.group(2), float(m.group(1)), m.group(4), float(m.group(3))))
            continue
        m = re.fullmatch(rf"({_NUM})\s*\*\s*(\w+)", part)
        if m:
            out.append(("t", m.group(2), float(m.group(1))))
            continue
        if re.fullmatch(_NUM, part):
            out.append(("c", float(part)))
            continue
        raise Unsupported(f"expression part {part!r}")
    return out


def _rate_parts(rate: dict) -> list[tuple]:
    form = rate.get("form")
    if form == "proportional":
        return [("t", rate["stock"], float(rate.get("k") or 0.0))]
    if form == "linear":
        out = [("c", float(rate.get("c") or 0.0))] if rate.get("c") else []
        return out + [("t", t["stock"], float(t.get("k") or 0.0)) for t in rate.get("terms") or []]
    if form == "constant":
        return [("c", float(rate.get("value", rate.get("k", 0.0)) or 0.0))]
    if form == "expr":
        return _parse_expr(rate.get("expr") or "")
    raise Unsupported(f"rate form {form!r}")


class Net:
    """Numbers and flows of one model, plus what the boundary holds."""

    def __init__(self, ids: list[str], inputs: list[str]):
        self.ids, self.inputs = ids, inputs
        self.var = {k: i for i, k in enumerate(ids)} | {k: len(ids) + i for i, k in enumerate(inputs)}
        self.theta: list[float] = []
        self.fixed: list[bool] = []
        self.flows: list[dict] = []

    def num(self, v: float, fixed: bool = False) -> int:
        self.theta.append(float(v))
        self.fixed.append(bool(fixed))
        return len(self.theta) - 1

    def copy(self) -> "Net":
        n = Net(self.ids, self.inputs)
        n.theta, n.fixed = list(self.theta), list(self.fixed)
        n.flows = [{**f, "comps": list(f["comps"])} for f in self.flows]
        return n

    def nfree(self) -> int:
        used = {p for f in self.flows for c in f["comps"] for p in _params(c)}
        return sum(1 for p in used if not self.fixed[p])

    def encode(self):
        """Flat arrays for the simulator: per flow its ends, per term (flow, kind, level, number,
        level, number); a constant's and a plain term's second pair is -1."""
        fs = [f["src"] for f in self.flows]
        fd = [f["dst"] for f in self.flows]
        rows = []
        for i, f in enumerate(self.flows):
            for c in f["comps"]:
                if c[0] == "c":
                    rows.append((i, 0, -1, c[1], -1, -1))
                elif c[0] == "t":
                    rows.append((i, 1, c[1], c[2], -1, -1))
                else:
                    rows.append((i, 2, c[1], c[2], c[3], c[4]))
        cols = np.asarray(rows, dtype=np.int64).reshape(-1, 6)
        return (np.asarray(fs, dtype=np.int64), np.asarray(fd, dtype=np.int64),
                *(np.ascontiguousarray(cols[:, j]) for j in range(6)))


def _params(c: tuple) -> list[int]:
    return [c[1]] if c[0] == "c" else [c[2]] if c[0] == "t" else [c[2], c[4]]


@njit(cache=True)
def _flows_at(theta, x, u, fs, cf, ck, v1, p1, v2, p2, nf, n):
    """Each flow's amount this step and its derivative by the levels (the engine's floor and share
    rule applied; the derivative of a MIN is its binding side's)."""
    r = np.zeros(nf)
    dr = np.zeros((nf, n))
    for j in range(cf.shape[0]):
        f = cf[j]
        if ck[j] == 0:
            r[f] += theta[p1[j]]
            continue
        a = x[v1[j]] if v1[j] < n else u[v1[j] - n]
        if ck[j] == 1:
            r[f] += theta[p1[j]] * a
            if v1[j] < n:
                dr[f, v1[j]] += theta[p1[j]]
            continue
        b = x[v2[j]] if v2[j] < n else u[v2[j] - n]
        if theta[p1[j]] * a <= theta[p2[j]] * b:
            r[f] += theta[p1[j]] * a
            if v1[j] < n:
                dr[f, v1[j]] += theta[p1[j]]
        else:
            r[f] += theta[p2[j]] * b
            if v2[j] < n:
                dr[f, v2[j]] += theta[p2[j]]
    for f in range(nf):
        if r[f] < 0.0:
            r[f] = 0.0
            for i in range(n):
                dr[f, i] = 0.0
    for i in range(n):                           # a stock's outflows share what it holds
        want = 0.0
        for f in range(nf):
            if fs[f] == i:
                want += r[f]
        if want > x[i] and want > 0.0 and x[i] > -1.0:
            q = max(0.0, x[i]) / want
            for f in range(nf):
                if fs[f] == i:
                    r[f] *= q
                    for k in range(n):
                        dr[f, k] = 0.0
                    if x[i] > 0.0:
                        dr[f, i] = r[f] / x[i]
    return r, dr


@njit(cache=True)
def _kf(theta, noise, U, INJ, Y, fs, fd, cf, ck, v1, p1, v2, p2):
    """-2 log-likelihood of the levels (less the first) under the model: an extended Kalman filter
    with counting noise in every flow (variance = its amount) and measurement error of variance
    noise[i] + noise[n + i] x level^2."""
    T, n = Y.shape
    nf = fs.shape[0]
    x = Y[0].copy()
    P = np.zeros((n, n))
    FP = np.zeros((n, n))
    S = np.zeros((n, n))
    L = np.zeros((n, n))
    F = np.zeros((n, n))
    K = np.zeros((n, n))
    w = np.zeros(n)
    nu = np.zeros(n)
    for i in range(n):
        P[i, i] = max(noise[i] + noise[n + i] * Y[0, i] ** 2, 1e-9)
    out = 0.0
    for s in range(1, T):
        for i in range(n):
            x[i] += INJ[s, i]
        r, dr = _flows_at(theta, x, U[s], fs, cf, ck, v1, p1, v2, p2, nf, n)
        for i in range(n):
            for j in range(n):
                F[i, j] = 1.0 if i == j else 0.0
        for f in range(nf):
            a, b = fs[f], fd[f]
            for j in range(n):
                if a >= 0:
                    F[a, j] -= dr[f, j]
                if b >= 0:
                    F[b, j] += dr[f, j]
        for i in range(n):                       # P = F P F' (+ Q below)
            for j in range(n):
                acc = 0.0
                for k in range(n):
                    acc += F[i, k] * P[k, j]
                FP[i, j] = acc
        for i in range(n):
            for j in range(i + 1):
                acc = 0.0
                for k in range(n):
                    acc += FP[i, k] * F[j, k]
                P[i, j] = acc
                P[j, i] = acc
        for f in range(nf):
            a, b = fs[f], fd[f]
            q = r[f]
            if a >= 0:
                x[a] -= q
                P[a, a] += q
            if b >= 0:
                x[b] += q
                P[b, b] += q
            if a >= 0 and b >= 0:
                P[a, b] -= q
                P[b, a] -= q
        for i in range(n):
            if not np.isfinite(x[i]) or abs(x[i]) > 1e12:
                return 1e300
            nu[i] = Y[s, i] - x[i]
            for j in range(n):
                S[i, j] = P[i, j]
            S[i, i] += max(noise[i] + noise[n + i] * x[i] ** 2, 1e-9)
        for i in range(n):                       # S = L L'
            for j in range(i + 1):
                acc = S[i, j]
                for k in range(j):
                    acc -= L[i, k] * L[j, k]
                if i == j:
                    if acc <= 0.0:
                        return 1e300
                    L[i, i] = math.sqrt(acc)
                else:
                    L[i, j] = acc / L[j, j]
        logdet = 0.0
        for i in range(n):
            logdet += 2.0 * math.log(L[i, i])
        for i in range(n):                       # w = L^-1 nu
            acc = nu[i]
            for k in range(i):
                acc -= L[i, k] * w[k]
            w[i] = acc / L[i, i]
        quad = 0.0
        for i in range(n):
            quad += w[i] * w[i]
        out += logdet + quad
        for c in range(n):                       # K' = S^-1 P: solve L L' K' = P column by column
            for i in range(n):
                acc = P[i, c]
                for k in range(i):
                    acc -= L[i, k] * FP[k, c]
                FP[i, c] = acc / L[i, i]
            for i in range(n - 1, -1, -1):
                acc = FP[i, c]
                for k in range(i + 1, n):
                    acc -= L[k, i] * K[c, k]
                K[c, i] = acc / L[i, i]
        for i in range(n):                       # x += K nu
            acc = 0.0
            for k in range(n):
                acc += K[i, k] * nu[k]
            w[i] = acc
        for i in range(n):
            x[i] += w[i]
        for i in range(n):                       # P = P - K P  (K S K' = K P' = K P)
            for j in range(n):
                acc = 0.0
                for k in range(n):
                    acc += K[i, k] * P[k, j]
                FP[i, j] = P[i, j] - acc
        for i in range(n):
            for j in range(i + 1):
                v = 0.5 * (FP[i, j] + FP[j, i])
                P[i, j] = v
                P[j, i] = v
    return out


@njit(cache=True)
def _one_step(theta, Y, U, INJ, fs, fd, cf, ck, v1, p1, v2, p2):
    """Each step's change predicted from the measured levels before it (rows 1..T-1)."""
    T, n = Y.shape
    nf = fs.shape[0]
    D = np.zeros((T - 1, n))
    for s in range(1, T):
        x = Y[s - 1].copy()
        for i in range(n):
            x[i] += INJ[s, i]
            D[s - 1, i] += INJ[s, i]
        r, _ = _flows_at(theta, x, U[s], fs, cf, ck, v1, p1, v2, p2, nf, n)
        for k in range(nf):
            if fs[k] >= 0:
                D[s - 1, fs[k]] -= r[k]
            if fd[k] >= 0:
                D[s - 1, fd[k]] += r[k]
    return D


# --- data -----------------------------------------------------------------------------------------

class Data:
    def __init__(self, stocks: list[dict], run: dict, opts: dict | None):
        opts = opts or {}
        self.ids = [s["id"] for s in stocks]
        self.final = {s["id"] for s in stocks if s.get("final")}
        lv = run["levels"]
        if any(i not in lv for i in self.ids):
            raise Unsupported("a stock is not measured")
        self.Y = np.column_stack([np.asarray(lv[i], dtype=float) for i in self.ids])
        self.T, self.n = self.Y.shape
        t = np.asarray(run["t"], dtype=float)
        ins = opts.get("inputs") or {}
        self.inputs = sorted(ins)
        self.U = np.column_stack([np.asarray(ins[k], dtype=float) for k in self.inputs]) if self.inputs else np.zeros((self.T, 0))
        if self.U.shape[0] != self.T:
            raise Unsupported("inputs not aligned with t")
        self.INJ = np.zeros((self.T, self.n))
        for j in opts.get("injections") or []:
            if j.get("stock") in self.ids:
                hit = np.nonzero(t == float(j["t"]))[0]
                if len(hit):
                    self.INJ[hit[0], self.ids.index(j["stock"])] += float(j["amount"])
        self.bd = run.get("boundary") if run.get("boundary_declared") else None
        self.N = self.T * self.n


def _net(flows: list[dict], data: Data) -> Net:
    net = Net(data.ids, data.inputs)
    for f in flows:
        if f.get("byTime") or f.get("inflow") or f.get("uses") or f.get("effects") or f.get("bothWays") \
                or float(f.get("ratio") or 1) != 1.0 or f.get("coflow"):
            raise Unsupported("a form this stage does not run")
        src, dst = f.get("from"), f.get("to")
        for s in (src, dst):
            if s is not None and s not in data.ids:
                raise Unsupported("a hidden stock")
        held = _held_input(f, data)
        comps = []
        for p in _rate_parts(f.get("rate") or {}):
            if p[0] == "c":
                comps.append(("c", net.num(p[1])))
            elif p[0] == "t":
                if p[1] not in net.var:
                    raise Unsupported(f"reads {p[1]!r}")
                comps.append(("t", net.var[p[1]], net.num(p[2], fixed=held)))
            else:
                if p[1] not in net.var or p[3] not in net.var:
                    raise Unsupported("a MIN reads something unknown")
                comps.append(("m", net.var[p[1]], net.num(p[2]), net.var[p[3]], net.num(p[4])))
        net.flows.append({"src": -1 if src is None else data.ids.index(src), "dst": -1 if dst is None else data.ids.index(dst),
                          "comps": comps, "orig": f, "held": held})
    return net


def _held_input(f: dict, data: Data) -> bool:
    """An outside inflow the boundary declares as the input itself: its gain is held."""
    if f.get("from") is not None or not data.bd:
        return False
    kinds = (data.bd.get(f.get("to")) or {}).get("in") or []
    rate = f.get("rate") or {}
    reads = [t.get("stock") for t in rate.get("terms") or []] if rate.get("form") == "linear" else [rate.get("stock")]
    return "input" in kinds and bool(reads) and all(r in data.inputs for r in reads)


# --- fitting --------------------------------------------------------------------------------------

def _bounds(net: Net, p: int) -> tuple[float, float]:
    """A coefficient on the flow's own source takes at most all of it a step (the engine's share
    rule clips more, so more is not identified); a MIN's sides are not negative."""
    for f in net.flows:
        for c in f["comps"]:
            if c[0] == "m" and p == c[2]:
                return (0.0, 1.0) if c[1] == f["src"] else (0.0, np.inf)
            if c[0] == "m" and p == c[4]:
                return (0.0, 1.0) if c[3] == f["src"] else (0.0, np.inf)
            if c[0] == "t" and c[2] == p and c[1] == f["src"]:
                return (0.0, 1.0)
    return (-np.inf, np.inf)


class Fit:
    """The Kalman likelihood of a model's numbers, the measurement noise held (self.noise) or fitted."""

    def __init__(self, data: Data, noise: np.ndarray):
        self.d, self.noise = data, np.asarray(noise, float)

    def prefix(self, steps: int) -> "Fit":
        """The same likelihood on the first `steps` steps only (for screening)."""
        if steps >= self.d.T:
            return self
        d = copy.copy(self.d)
        d.Y, d.U, d.INJ, d.T, d.N = self.d.Y[:steps], self.d.U[:steps], self.d.INJ[:steps], steps, steps * self.d.n
        return Fit(d, self.noise)

    def nll(self, net: Net, theta=None) -> float:
        th = np.asarray(net.theta if theta is None else theta, float)
        try:
            v = _kf(th, self.noise, self.d.U, self.d.INJ, self.d.Y, *net.encode())
        except Exception:                        # noqa: BLE001  (a covariance that is not positive)
            return 1e300
        return float(v) if np.isfinite(v) else 1e300

    def fit(self, net: Net, free: list[int] | None = None, maxiter: int = 200, noise: bool = False) -> float:
        """The fitted -2 log-likelihood; net.theta (and with noise=True, self.noise) updated."""
        used = sorted({p for f in net.flows for c in f["comps"] for p in _params(c)})
        free = [p for p in (used if free is None else free) if p in used and not net.fixed[p]]
        enc = net.encode()
        th = np.asarray(net.theta, float)
        sc = np.maximum(np.abs(th[free]), 1e-3)
        bnds = [(lo / s if np.isfinite(lo) else None, hi / s if np.isfinite(hi) else None)
                for (lo, hi), s in zip([_bounds(net, p) for p in free], sc)]
        z0 = [min(max(t / s, lo if lo is not None else -np.inf), hi if hi is not None else np.inf)
              for t, s, (lo, hi) in zip(th[free], sc, bnds)]
        nz = 2 * self.d.n if noise else 0
        ln0 = np.log(np.maximum(self.noise, 1e-12))
        bnds += [(-28.0, 40.0)] * nz
        z0 = np.concatenate([z0, ln0 if noise else []])
        if not len(z0):
            return self.nll(net)

        def f(z):
            t = th.copy()
            t[free] = z[:len(free)] * sc
            nn = np.exp(z[len(free):]) if noise else self.noise
            try:
                v = _kf(t, nn, self.d.U, self.d.INJ, self.d.Y, *enc)
            except Exception:                    # noqa: BLE001
                return 1e300
            return float(v) if np.isfinite(v) else 1e300

        z0 = np.asarray(z0, float)
        f0 = f(z0)
        sol = minimize(f, z0, method="L-BFGS-B", bounds=bnds, options={"maxiter": maxiter, "eps": 1e-7})
        if not sol.fun <= f0:                    # finite differences across a MIN's kink can end above the start
            sol.x, sol.fun = z0, f0
        th[free] = sol.x[:len(free)] * sc
        net.theta = [float(v) for v in th]
        if noise:
            self.noise = np.exp(sol.x[len(free):])
        return float(sol.fun)


def _gate(net: Net, d: Data) -> tuple[bool, np.ndarray]:
    """Measurement error shown, and each step's one-step residuals (rows 1..T-1)."""
    D = _one_step(np.asarray(net.theta, float), d.Y, d.U, d.INJ, *net.encode())
    e = np.diff(d.Y, axis=0) - D
    zs = []
    for i in range(d.n):
        x = e[:, i] - e[:, i].mean()
        v = float(x @ x)
        zs.append(float(x[1:] @ x[:-1]) / v * math.sqrt(len(x)) if v > 1e-12 * max(1.0, float(np.mean(d.Y[:, i] ** 2))) else 0.0)
    return min(zs) < norm.ppf(ALPHA / max(1, d.n)), e


def _noise0(e: np.ndarray, d: Data) -> np.ndarray:
    """A first measurement variance per stock, a + b x level^2, from -e_t e_{t-1} (white error),
    without negative parts (the fit then refines it)."""
    out = np.zeros(2 * d.n)
    for i in range(d.n):
        g = -(e[1:, i] * e[:-1, i])
        lvl = d.Y[1:-1, i]
        A = np.column_stack([np.ones_like(lvl), lvl ** 2])
        best = None
        for cols in ([0, 1], [0], [1]):
            sol, *_ = np.linalg.lstsq(A[:, cols], g, rcond=None)
            if np.all(sol >= 0):
                c = np.zeros(2)
                c[cols] = sol
                res = float(np.sum((A @ c - g) ** 2))
                if best is None or res < best[0]:
                    best = (res, c)
        a, b = best[1] if best else (float(np.var(e[:, i])) / 2, 0.0)
        out[i] = max(a, 1e-6 * max(1e-9, float(np.var(d.Y[:, i]))), 1e-9)
        out[d.n + i] = max(b, 1e-10)
    return out


# --- the search -----------------------------------------------------------------------------------

def _outs(net: Net, i: int) -> int:
    return sum(1 for f in net.flows if f["src"] == i and f["dst"] == -1)


def _protected(net: Net, k: int, d: Data) -> bool:
    f = net.flows[k]
    if f["held"]:
        return True
    if d.bd is None:
        return False
    if f["src"] == -1:
        return True                              # an outside inflow: the declared side keeps it
    if f["dst"] == -1:
        st = d.ids[f["src"]]
        return bool((d.bd.get(st) or {}).get("out")) and _outs(net, f["src"]) <= len((d.bd.get(st) or {}).get("out") or [])
    return False


def _may_leave(net: Net, i: int, d: Data) -> bool:
    if d.bd is None:
        return True
    return _outs(net, i) < len((d.bd.get(d.ids[i]) or {}).get("out") or [])


def _candidates(net: Net, d: Data) -> list[tuple[str, Net, list[int]]]:
    out = []
    nonfinal = [i for i, s in enumerate(d.ids) if s not in d.final]
    have = {(f["src"], f["dst"]) for f in net.flows}
    for k, f in enumerate(net.flows):            # drop
        if not _protected(net, k, d):
            m = net.copy()
            del m.flows[k]
            out.append((f"drop {_lab(net, f)}", m, []))
    for x in nonfinal:                           # add a move in proportion to its source
        for r in [j for j in range(d.n) if j != x] + [-1]:
            if (x, r) in have or (r == -1 and not _may_leave(net, x, d)):
                continue
            m = net.copy()
            m.flows.append({"src": x, "dst": r, "comps": [("t", x, m.num(0.01))], "orig": None, "held": False})
            out.append((f"add {d.ids[x]} -> {d.ids[r] if r >= 0 else 'outside'}", m, [len(m.theta) - 1]))
    for k, f in enumerate(net.flows):            # a constant becomes a share of the flow's source (a declared
        if f["held"] or f["src"] < 0:            # flow too: it stays, its form changes)
            continue
        for ci, c in enumerate(f["comps"]):
            if c[0] != "c" or any(x[0] == "t" and x[1] == f["src"] for x in f["comps"]):
                continue
            m = net.copy()
            mean = max(1e-9, float(np.mean(d.Y[:, f["src"]])))
            comps = list(f["comps"])
            comps[ci] = ("t", f["src"], m.num(min(1.0, max(0.0, net.theta[c[1]]) / mean)))
            m.flows[k] = {**f, "comps": comps, "orig": None}
            out.append((f"share {_lab(net, f)}", m, [len(m.theta) - 1]))
    for k, f in enumerate(net.flows):            # take it from the stock it reads
        if f["held"] or _protected(net, k, d):
            continue
        for v in sorted({c[1] for c in f["comps"] if c[0] == "t" and c[1] < d.n and c[1] != f["src"]}):
            if d.ids[v] in d.final or v == f["dst"] or (f["src"] == -1 and d.bd is not None):
                continue
            m = net.copy()
            g = {**f, "src": v, "comps": list(f["comps"]), "orig": None}
            j = next((i for i, h in enumerate(m.flows) if i != k and h["src"] == v and h["dst"] == f["dst"]), None)
            if j is not None:                    # the pair has a flow already: one flow, the terms summed
                m.flows[j] = {**m.flows[j], "comps": _joined_terms(m, m.flows[j]["comps"] + g["comps"]), "orig": m.flows[j]["orig"]}
                del m.flows[k]
            else:
                m.flows[k] = g
            out.append((f"take {_lab(net, f)} from {d.ids[v]}", m, [p for c in g["comps"] for p in _params(c)]))
    for k, f in enumerate(net.flows):            # move its source, and the share it takes with it
        if f["src"] < 0 or _protected(net, k, d) or len(f["comps"]) != 1 or f["comps"][0][0] != "t" or f["comps"][0][1] != f["src"]:
            continue
        for z in nonfinal:
            if z in (f["src"], f["dst"]) or (z, f["dst"]) in have:
                continue
            m = net.copy()
            m.flows[k] = {**f, "src": z, "comps": [("t", z, f["comps"][0][2])], "orig": None}
            out.append((f"move {_lab(net, f)} to come from {d.ids[z]}", m, [f["comps"][0][2]]))
    for k, f in enumerate(net.flows):            # send elsewhere
        if f["src"] == -1 or _protected(net, k, d):
            continue
        for r in [j for j in range(d.n) if j != f["src"]] + [-1]:
            if r == f["dst"] or (f["src"], r) in have or (r == -1 and not _may_leave(net, f["src"], d)):
                continue
            m = net.copy()
            m.flows[k] = {**f, "dst": r, "comps": list(f["comps"]), "orig": None}
            out.append((f"send {_lab(net, f)} to {d.ids[r] if r >= 0 else 'outside'}", m, [p for c in f["comps"] for p in _params(c)]))
    for k, f in enumerate(net.flows):            # pass it through another stock: X -> R becomes X -> R' -> R
        if f["src"] < 0 or f["dst"] < 0 or _protected(net, k, d):
            continue
        for z in nonfinal:
            if z in (f["src"], f["dst"]) or (f["src"], z) in have:
                continue
            m = net.copy()
            m.flows[k] = {**f, "dst": z, "comps": list(f["comps"]), "orig": None}
            new = []
            if (z, f["dst"]) not in have:
                m.flows.append({"src": z, "dst": f["dst"], "comps": [("t", z, m.num(0.1))], "orig": None, "held": False})
                new = [len(m.theta) - 1]
            out.append((f"through {_lab(net, f)} via {d.ids[z]}", m, new + [p for c in f["comps"] for p in _params(c)]))
    caps = [j for j in nonfinal] + [d.n + i for i in range(len(d.inputs))]
    for k, f in enumerate(net.flows):            # limit a term on the flow's own source
        if f["src"] < 0 or f["held"]:
            continue
        for ci, c in enumerate(f["comps"]):
            if c[0] != "t" or c[1] != f["src"]:
                continue
            kx = net.theta[c[2]]
            xs = d.Y[:, f["src"]]
            for y in caps:
                if y == f["src"] or y == f["dst"]:
                    continue
                ys = d.Y[:, y] if y < d.n else d.U[:, y - d.n]
                ok = ys > 1e-9
                if ok.sum() < 10 or kx <= 0:
                    continue
                for share in SHARE:
                    th = float(np.quantile(xs[ok] / ys[ok], 1 - share))
                    if not th > 0:
                        continue
                    m = net.copy()
                    comps = list(f["comps"])
                    comps[ci] = ("m", c[1], c[2], y, m.num(kx * th))
                    m.flows[k] = {**f, "comps": comps, "orig": None}
                    yn = d.ids[y] if y < d.n else d.inputs[y - d.n]
                    out.append((f"limit {_lab(net, f)} by {yn} ({share:g})", m, [c[2], len(m.theta) - 1]))
    return out


def _lab(net: Net, f: dict) -> str:
    a = net.ids[f["src"]] if f["src"] >= 0 else "outside"
    b = net.ids[f["dst"]] if f["dst"] >= 0 else "outside"
    return f"{a} -> {b}"


def _price(v: float, net: Net, d: Data) -> float:
    """Bayes' price: -2 log-likelihood plus log n per number (n: the measured values); a MIN that does
    not switch (one side binds on fewer than REGIME of the steps, on the measured levels) is no limit."""
    return v + math.log(d.N) * net.nfree() if _switches(net, d) else math.inf


def _switches(net: Net, d: Data) -> bool:
    for f in net.flows:
        for c in f["comps"]:
            if c[0] != "m":
                continue
            a = net.theta[c[2]] * (d.Y[:, c[1]] if c[1] < d.n else d.U[:, c[1] - d.n])
            b = net.theta[c[4]] * (d.Y[:, c[3]] if c[3] < d.n else d.U[:, c[3] - d.n])
            share = float(np.mean(a <= b))
            if not REGIME <= share <= 1 - REGIME:
                return False
    return True


def _joined_terms(net: Net, comps: list[tuple]) -> list[tuple]:
    """Terms on the same level summed into one (its number the sum), so a joined flow is priced once."""
    out, seen = [], {}
    for c in comps:
        if c[0] == "t" and c[1] in seen and not net.fixed[c[2]] and not net.fixed[seen[c[1]]]:
            net.theta[seen[c[1]]] += net.theta[c[2]]
            continue
        if c[0] == "t":
            seen[c[1]] = c[2]
        out.append(c)
    return out


def _canonical(net: Net, d: Data) -> Net:
    """The same flows, each one whose rate is one term on another measured stock (not final, not its
    receiver) taken from that stock: a flow drains what it reads. Flows then between the same stocks
    are one flow, their terms summed."""
    m = net.copy()
    for k in range(len(m.flows)):
        f = m.flows[k]
        if f["held"] or f["src"] < 0 or _protected(m, k, d) or len(f["comps"]) != 1 or f["comps"][0][0] != "t":
            continue
        v = f["comps"][0][1]
        if v >= d.n or v == f["src"] or v == f["dst"] or d.ids[v] in d.final:
            continue
        m.flows[k] = {**f, "src": v, "orig": None}
    joined: list[dict] = []
    for f in m.flows:
        g = next((h for h in joined if h["src"] == f["src"] and h["dst"] == f["dst"] and not h["held"] and not f["held"]), None)
        if g is None:
            joined.append({**f, "comps": list(f["comps"])})
        else:
            g["comps"] = _joined_terms(m, g["comps"] + f["comps"])
            g["orig"] = g["orig"] or f["orig"]
    m.flows = joined
    return m


def _search(net: Net, fit: Fit, trail: list[str], kinds: tuple = ()) -> tuple[Net, float]:
    """Greedy moves on fit's likelihood (screened on its first SCREEN_T steps) while one lowers the price
    (kinds: only the moves whose label starts so)."""
    d = fit.d
    v = fit.fit(net, maxiter=FULL)
    short = fit.prefix(SCREEN_T)
    for _ in range(ROUNDS):
        now = _price(v, net, d)
        screened = []
        for lab, m, focus in _candidates(net, d):
            if kinds and not lab.startswith(kinds):
                continue
            c = short.fit(m.copy(), maxiter=SCREEN)
            screened.append((_price(c, m, short.d), lab, m, focus))
        screened.sort(key=lambda z: z[0])
        best = None
        for _c, lab, m, focus in screened[:FINALISTS]:
            c = fit.fit(m, maxiter=FULL)
            p = _price(c, m, d)
            if best is None or p < best[0]:
                best = (p, lab, m, c)
        if best is None or best[0] >= now - 1e-9:
            break
        _, lab, net, v = best
        trail.append(f"{lab}: {best[0]:.1f}")
    return net, v


def refine(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    try:
        d = Data(stocks, run, opts)
        net = _net(result["flows"], d)
    except Unsupported:
        return result
    shown, e = _gate(net, d)
    if not shown:
        return result
    orig = net.copy()
    noise0 = _noise0(e, d)                       # the noise from the data first: fitted on a wrong model, a
    best = None                                  # stock's measurement variance would take in what it misses
    for name, start in (("found", net), ("drains what it reads", _canonical(net, d))):
        full = Fit(d, noise0)
        part = full.prefix(SEARCH_T)
        m = start.copy()
        trail = [f"state space from the {name} structure, first {part.d.T} steps: found model "
                 f"{_price(part.nll(orig), orig, part.d):.1f}"]
        m, _ = _search(m, part, trail)
        full.fit(m, noise=True, maxiter=FULL)    # the noise on the model the search reached (the whole run); again
        part = full.prefix(SEARCH_T)
        trail.append(f"noise refitted: {_price(part.nll(m), m, part.d):.1f}")
        m, _ = _search(m, part, trail)
        v = full.fit(m, maxiter=FULL)            # the numbers on the whole run
        trail.append(f"whole run: {_price(v, m, d):.1f} (found model {_price(full.nll(orig), orig, d):.1f})")
        if best is None or _price(v, m, d) < _price(best[1], best[0], d):
            best = (m, v, trail, full)
    net, v, trail, full = best
    if _price(v, net, d) >= _price(full.nll(orig), orig, d):
        return result
    out = dict(result)
    out["flows"] = _write(net, d)
    out["state_space"] = trail
    return out


def _saturated(net: Net) -> None:
    """A stock whose flows each take a share of it, summing past 1 a step, loses all of it, shared in
    proportion (the engine's rule): the same model with the shares scaled to sum to 1."""
    for i in range(len(net.ids)):
        own = [f for f in net.flows if f["src"] == i]
        if own and all(len(f["comps"]) == 1 and f["comps"][0][0] == "t" and f["comps"][0][1] == i for f in own):
            tot = sum(net.theta[f["comps"][0][2]] for f in own)
            if tot > 1.0:
                for f in own:
                    net.theta[f["comps"][0][2]] /= tot


def _write(net: Net, d: Data) -> list[dict]:
    _saturated(net)
    flows = []
    names = net.ids + net.inputs
    for n, f in enumerate(net.flows):
        th = [float(x) for x in net.theta]
        terms, c, mins = [], 0.0, []
        for comp in f["comps"]:
            if comp[0] == "c":
                c += th[comp[1]]
            elif comp[0] == "t":
                terms.append((names[comp[1]], th[comp[2]]))
            else:
                mins.append((names[comp[1]], th[comp[2]], names[comp[3]], th[comp[4]]))
        src = d.ids[f["src"]] if f["src"] >= 0 else None
        if mins:
            parts = ([repr(c)] if c else []) + [f"{k!r} * {s}" for s, k in terms] + [f"min({a!r} * {x}, {b!r} * {y})" for x, a, y, b in mins]
            rate = {"form": "expr", "expr": " + ".join(parts)}
        elif not c and len(terms) == 1 and terms[0][0] == src:
            rate = {"form": "proportional", "stock": src, "k": terms[0][1]}
        else:
            rate = {"form": "linear", "c": c, "terms": [{"stock": s, "k": k} for s, k in terms]}
        g = copy.deepcopy(f["orig"]) if f["orig"] is not None else {}
        for k in ("note", "driver", "nearly", "perStep"):
            g.pop(k, None)
        g.update({"from": src, "to": d.ids[f["dst"]] if f["dst"] >= 0 else None, "ratio": 1, "rate": rate, "rates": [rate],
                  "bothWays": False})
        if rate["form"] == "expr":
            g.setdefault("id", f"oe{n}")
        else:
            g.pop("id", None) if str(g.get("id", "")).startswith(("oe", "capmin")) else None
        flows.append(g)
    return flows


_DEPTH = [0]


def wrap(identify, stocks: list[dict], run: dict, opts: dict | None, *args, **kw) -> dict:
    """identify(stocks, run, opts), refined on the state-space likelihood where the levels carry
    measurement error (once: a strategy that calls itself is refined only at the outside)."""
    _DEPTH[0] += 1
    try:
        r = identify(stocks, run, opts, *args, **kw)
    finally:
        _DEPTH[0] -= 1
    return r if _DEPTH[0] else refine(r, stocks, run, opts)
