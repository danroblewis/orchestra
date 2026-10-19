"""Jump-ahead for a model's linear part: its levels at any step, in O(log t), without stepping.

When every flow's rate is a linear form (constant, proportional, gap, linear: c + sum k_j x level_j),
with no effects, co-flows or hidden delays, one step is an affine map

    x_{t+1} = M_t x_t + b_t,   M_t = I + B_t,   b_t = u_t

(B_t, u_t: what the flows add to each stock per unit of each level and per step, at step t; they
change only where a rate's byTime segment or outside inflow piece does). Steps compose as affine
maps, so after the steps that differ (the recorded run, injections) the model repeats one period P
of steps (P = 1 without a schedule): the period map (M_P, b_P) composed k times is a power of the
augmented matrix [[M_P, b_P], [0, 1]], which squaring gives in O(log k) multiplications. Then

    x_{t0 + kP} = M_P^k (x_{t0} - x*) + x*,   x* = (I - M_P)^-1 b_P  (the fixed point, when I - M_P
    is invertible; the augmented power needs no inverse, so it also covers stocks that only grow).

**When it is exact.** Only while no floor binds: every rate stays >= 0, no stock is asked for more
than it holds (the engine shares what a stock holds among its outflows), and no level goes below 0.
A stable model settling where every rate is positive (most chains, links, loops of the ladder) never
touches a floor once it is near its fixed point, and the jump is exact to float precision. A model
whose floor binds (024: a link that stops at zero; 025: a demand capped by what arrives), a model
with effects or co-flows (not affine), and a found model that runs away or empties a stock are not
covered: there, the levels come from stepping (longrun.py), which is cheap anyway.

`spectrum` gives the period map's eigenvalues as per-step factors: the spectral radius (above 1:
the model grows without bound, unstable), and each mode's time constant tau = -1 / ln|lambda| steps
(a mode decays by e every tau steps; |lambda| = 1 is a stock that only accumulates).
"""

from __future__ import annotations

import math

import numpy as np

from ..discovery.simulate import _Segments
from .parts import linear_form

UNSTABLE = 1e-9            # spectral radius above 1 + this is growth
MARGINAL = 1e-9            # |lambda| within this of 1 is a stock that only accumulates (no time constant)


def is_affine(flows: list[dict]) -> bool:
    """Every flow's rate (and every segment of it) is a linear form, with no effects, co-flows or
    hidden delays."""
    for f in flows:
        if f.get("effects") or f.get("uses") or f.get("via"):
            return False
        if f.get("inflow"):
            continue
        rates = [g.get("rate") for g in f["byTime"]] if f.get("byTime") else [f.get("rate")]
        if any(linear_form(r) is None for r in rates):
            return False
    return True


class Affine:
    """A model's flows compiled to per-step affine maps over the stocks `ids` (any other stock reads 0)."""

    def __init__(self, flows: list[dict], ids: list[str]):
        if not is_affine(flows):
            raise ValueError("not an affine model (effects, co-flows, hidden delays or a non-linear rate)")
        self.ids = list(ids)
        self.index = {s: i for i, s in enumerate(ids)}
        self.flows = []
        for f in flows:
            src, dst = self.index.get(f.get("from")), self.index.get(f.get("to"))
            ratio = float(f.get("ratio") or 1)
            if f.get("inflow"):
                forms = [(max(0.0, float(g["value"])), {}) for g in f["inflow"]]
                segs = _Segments(f["inflow"])
            elif f.get("byTime"):
                forms = [linear_form(g["rate"]) for g in f["byTime"]]
                segs = _Segments(f["byTime"])
            else:
                forms, segs = [linear_form(f.get("rate"))], None
            self.flows.append((src, dst, ratio, segs, [self._vec(c, ks) for c, ks in forms]))

    def _vec(self, c: float, ks: dict) -> tuple[float, np.ndarray]:
        k = np.zeros(len(self.ids))
        for s, v in ks.items():
            if s in self.index:
                k[self.index[s]] += v
        return c, k

    def step_maps(self, times) -> tuple[np.ndarray, np.ndarray]:
        """(M, b) for each step at `times`: M is steps x n x n, b steps x n."""
        times = np.asarray(times, dtype=float)
        n, m = len(self.ids), len(times)
        M = np.broadcast_to(np.eye(n), (m, n, n)).copy()
        b = np.zeros((m, n))
        for src, dst, ratio, segs, forms in self.flows:
            seg = segs(times) if segs is not None else np.zeros(m, int)
            cs = np.array([c for c, _ in forms])[seg]
            ks = np.array([k for _, k in forms])[seg]                 # steps x n
            for stock, sign in ((src, -ratio), (dst, 1.0)):
                if stock is not None:
                    b[:, stock] += sign * cs
                    M[:, stock, :] += sign * ks
        return M, b

    def compose(self, times) -> tuple[np.ndarray, np.ndarray]:
        """The map of the steps at `times`, in order: x_end = M x_start + b."""
        Ms, bs = self.step_maps(times)
        M, b = np.eye(len(self.ids)), np.zeros(len(self.ids))
        for Mt, bt in zip(Ms, bs):
            M, b = Mt @ M, Mt @ b + bt
        return M, b

    def path(self, x0: np.ndarray, times) -> np.ndarray:
        """Levels after each step at `times` from x0 (no floors): n x steps."""
        Ms, bs = self.step_maps(times)
        out = np.empty((len(self.ids), len(Ms)))
        x = np.asarray(x0, dtype=float)
        for i, (Mt, bt) in enumerate(zip(Ms, bs)):
            x = Mt @ x + bt
            out[:, i] = x
        return out


def power(M: np.ndarray, b: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """The affine map (M, b) applied k times, by squaring the augmented matrix: O(log k)."""
    n = len(b)
    A = np.eye(n + 1)
    A[:n, :n], A[:n, n] = M, b
    Ak = np.linalg.matrix_power(A, int(k))
    return Ak[:n, :n], Ak[:n, n]


def fixed_point(M: np.ndarray, b: np.ndarray) -> np.ndarray | None:
    """x* with M x* + b = x*, or None when I - M is singular (a stock that only accumulates)."""
    I_M = np.eye(len(b)) - M
    if not len(b) or np.linalg.cond(I_M) > 1e12:
        return None
    return np.linalg.solve(I_M, b)


def spectrum(M: np.ndarray, steps: int = 1) -> dict:
    """The eigenvalues of a map over `steps` steps as per-step factors: {rho (spectral radius per
    step), unstable, taus (time constants of the decaying modes, steps, slowest first), tau (the
    slowest), marginal (modes that neither grow nor decay)}."""
    if not len(M):
        return {"rho": 0.0, "unstable": False, "taus": [], "tau": None, "marginal": 0}
    mags = np.abs(np.linalg.eigvals(M)) ** (1.0 / max(1, steps))
    mags = np.where(np.isfinite(mags), mags, np.inf)
    rho = float(mags.max())
    taus = sorted((-1.0 / math.log(m) for m in mags if 0 < m < 1 - MARGINAL), reverse=True)
    return {"rho": rho, "unstable": bool(rho > 1 + UNSTABLE), "taus": taus, "tau": taus[0] if taus else None,
            "marginal": int(sum(abs(m - 1) <= MARGINAL for m in mags))}


class Jump:
    """Levels at any step of an affine model started at x0 before step t1: the steps t1..t_free are
    composed one by one (the recorded run, where pieces and injections differ), then the period of P
    steps after t_free repeats and is jumped over by squaring. Injections ({t, stock, amount}) are
    added before their step, as the engine adds them (without its floor at 0)."""

    def __init__(self, affine: Affine, x0: np.ndarray, t1: int, t_free: int, period: int = 1, injections: list[dict] | None = None):
        self.a, self.t1, self.P = affine, int(t1), max(1, int(period))
        self.t_free = max(int(t_free), self.t1 - 1)
        pulses = {}
        for j in injections or []:
            if j.get("stock") in affine.index and self.t1 <= int(j["t"]) <= self.t_free:
                pulses.setdefault(int(j["t"]), []).append((affine.index[j["stock"]], float(j["amount"])))
        x = np.asarray(x0, dtype=float).copy()
        Ms, bs = affine.step_maps(np.arange(self.t1, self.t_free + 1))
        self.prefix = np.empty((len(x), len(Ms)))
        for i, (Mt, bt) in enumerate(zip(Ms, bs)):
            for s, amount in pulses.get(self.t1 + i, ()):
                x[s] += amount
            x = Mt @ x + bt
            self.prefix[:, i] = x
        self.x_free = x
        self.M_P, self.b_P = affine.compose(np.arange(self.t_free + 1, self.t_free + self.P + 1))

    def at(self, t: int) -> np.ndarray:
        """Levels after step t (t >= t1)."""
        t = int(t)
        if t <= self.t_free:
            return self.prefix[:, t - self.t1].copy()
        k, r = divmod(t - self.t_free, self.P)
        Mk, bk = power(self.M_P, self.b_P, k)
        x = Mk @ self.x_free + bk
        if r:
            M, b = self.a.compose(np.arange(self.t_free + 1, self.t_free + r + 1))
            x = M @ x + b
        return x

    def fixed_point(self) -> np.ndarray | None:
        """The levels at the period's start the model settles to (None if it does not settle)."""
        return fixed_point(self.M_P, self.b_P)

    def spectrum(self) -> dict:
        return spectrum(self.M_P, self.P)
