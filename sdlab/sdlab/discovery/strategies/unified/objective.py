"""The one objective (unified-design.md, section 4), code table v1:

    J(M) = min over (theta, eta) of D(y | M, theta, eta)  +  P_num(M)  +  P_struct(M)

D is the filter's one-step bin code (kalman.py), the prices are in price.py. A fit holds the structure
fixed and refits every number (theta) and the noise character (eta) by L-BFGS-B on JAX gradients
(log/logit transforms for eta; the design's Fisher scoring is not built yet). eta is always estimated,
never switched: every fit first fits eta alone from three declared starts (counting, measurement
error, splitting) at the first theta start (later theta starts begin from the eta it chose), then
fits everything jointly from the best.

    m = prepare(view, flows, dt=..., ceilings=..., signed=..., hidden_starts=...)
    r = fit(m, starts=[m.theta0], fit_theta=True)   # {"J", "D", "P_num", "P_struct", "theta", "eta", ...}

prepare() raises frontend.NotExpressible for what the class cannot hold (class C).
"""

from __future__ import annotations

import math
import time

import numpy as np

from . import price
from .frontend import Grid, Structure, build, grid_of, write_back
from .kalman import eta_read, make_filter, n_eta

ETA_BOUNDS = {"ln_phi": (-25.0, 5.0), "logit_beta": (-12.0, 12.0), "ln_tau": (-40.0, 4.0), "ln_alpha": (-40.0, 4.0),
              "ln_rho2": (-40.0, 0.0)}
# the declared eta starts: counting noise; measurement error on nearly exact flows; particle splitting
ETA_STARTS = ({"ln_phi": 0.0, "logit_beta": -6.0, "ln_tau": -14.0, "ln_alpha": -14.0, "ln_rho2": -14.0},
              {"ln_phi": -12.0, "logit_beta": -6.0, "ln_tau": -14.0, "ln_alpha": -7.0, "ln_rho2": -7.0},
              {"ln_phi": 0.0, "logit_beta": 0.0, "ln_tau": -14.0, "ln_alpha": -14.0, "ln_rho2": -14.0})
MAXITER = 400


class Model:
    """A structure on a grid, with its filter compiled once."""

    def __init__(self, st: Structure, grid: Grid):
        self.st, self.grid = st, grid
        self.filt = make_filter(st, grid)
        self.P_num = price.p_num(st, grid)
        self.P_struct = price.p_struct(st)
        self.theta0 = st.theta0()

    def eta_vector(self, spec: dict) -> np.ndarray:
        m = len(self.grid.ids)
        return np.array([spec["ln_phi"], spec["logit_beta"]] + [spec["ln_tau"]] * (m + 1) + [spec["ln_alpha"]] * m + [spec["ln_rho2"]] * m)

    def eta_bounds(self) -> list[tuple]:
        m = len(self.grid.ids)
        b = ETA_BOUNDS
        return [b["ln_phi"], b["logit_beta"]] + [b["ln_tau"]] * (m + 1) + [b["ln_alpha"]] * m + [b["ln_rho2"]] * m

    def D(self, theta: np.ndarray, eta: np.ndarray) -> float:
        return float(self.filt["D"](np.asarray(theta, float), np.asarray(eta, float)))

    def J(self, D: float) -> float:
        return D + self.P_num + self.P_struct["total"]

    def theta_scale(self, theta: np.ndarray) -> np.ndarray:
        msc = float(np.mean(self.grid.scale))
        out = []
        for sl, v in zip(self.st.slots, theta):
            const = sl.kind == "start" or (sl.kind == "coef" and sl.path[2] is None)
            out.append(max(abs(v), 1e-2 * msc if const else 1e-2))
        return np.array(out)


def prepare(view: dict, flows: list[dict], grid: Grid | None = None, **opts) -> Model:
    g = grid or grid_of(view)
    return Model(build(view, flows, grid=g, **opts), g)


def _minimize(m: Model, theta: np.ndarray, eta: np.ndarray, fit_theta: bool) -> dict:
    from scipy.optimize import minimize

    P = m.st.P
    vg = m.filt["value_and_grad"]
    sc = m.theta_scale(theta) if fit_theta else np.ones(P)
    w0 = np.concatenate([theta / sc, eta]) if fit_theta else eta.copy()
    bounds = ([(None, None)] * P if fit_theta else []) + m.eta_bounds()
    calls = [0]

    def f(w):
        calls[0] += 1
        full = np.concatenate([w[:P] * sc, w[P:]]) if fit_theta else np.concatenate([theta, w])
        v, g = vg(full, P)
        v, g = float(v), np.asarray(g, dtype=float)
        if not np.isfinite(v) or not np.all(np.isfinite(g)):
            return 1e300, np.zeros_like(w)
        g = np.concatenate([g[:P] * sc, g[P:]]) if fit_theta else g[P:]
        return v, g

    res = minimize(f, w0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": MAXITER, "maxfun": 2 * MAXITER})
    w = res.x
    th = w[:P] * sc if fit_theta else theta
    et = w[P:] if fit_theta else w
    _, g = f(w)
    lo = np.array([b[0] if b[0] is not None else -np.inf for b in bounds])
    hi = np.array([b[1] if b[1] is not None else np.inf for b in bounds])
    free = ~(((w <= lo + 1e-8) & (g > 0)) | ((w >= hi - 1e-8) & (g < 0)))
    gnorm = float(np.linalg.norm(g[free])) if free.any() else 0.0
    return {"D": float(res.fun), "theta": th, "eta": et, "nit": int(res.nit), "calls": calls[0], "gnorm": gnorm,
            "message": str(res.message), "ok": bool(res.success)}


def fit(m: Model, starts: list[np.ndarray] | None = None, fit_theta: bool = True, eta_starts=ETA_STARTS) -> dict:
    """The best fit over the theta starts: eta alone first (from each declared eta start, keep the
    best), then everything jointly (fit_theta). Returns J, D, the prices, theta, eta (raw and read),
    every start's J, and whether it converged (gradient norm below 1e-4 N and the best two starts
    within EPSILON, when there are two)."""
    began = time.perf_counter()
    starts = [m.theta0] if starts is None else starts
    N = max(1, m.grid.n_reports)
    tries = []
    etas = [m.eta_vector(spec) for spec in eta_starts]
    for th0 in starts:
        th0 = np.asarray(th0, dtype=float)
        best = None
        for eta in etas:
            r = _minimize(m, th0, eta, fit_theta=False)
            if best is None or r["D"] < best["D"]:
                best = r
        etas = [best["eta"]]                         # later theta starts begin from the eta the first one chose
        r = _minimize(m, th0, best["eta"], fit_theta=True) if fit_theta and m.st.P else best
        if r["D"] > best["D"]:                       # never worse than its own eta-only start
            r = best
        tries.append(r)
    tries.sort(key=lambda r: r["D"])
    b = tries[0]
    agree = len(tries) < 2 or (tries[1]["D"] - b["D"]) <= price.EPSILON
    out = {"J": m.J(b["D"]), "D": b["D"], "P_num": m.P_num, "P_struct": m.P_struct["total"], "P_struct_items": m.P_struct,
           "theta": b["theta"].tolist(), "eta": b["eta"].tolist(), "eta_read": eta_read(b["eta"], m.grid),
           "gnorm": b["gnorm"], "converged": bool(b["gnorm"] < 1e-4 * N or b["ok"]), "restarts_agree": bool(agree),
           "start_J": [m.J(r["D"]) for r in tries], "message": b["message"],
           "numbers": m.st.P, "complexity": price.complexity(m.st), "seconds": round(time.perf_counter() - began, 3)}
    out["diagnostics"] = diagnostics(m, b["theta"], b["eta"])
    return out


def diagnostics(m: Model, theta, eta) -> dict:
    """Reported beside J, never deciding anything (4.6): the standardised innovations' dispersion z
    and the largest Ljung-Box z (10 lags) over the measured stocks."""
    _, _, z = m.filt["run"](np.asarray(theta, float), np.asarray(eta, float))
    z = np.asarray(z)
    mask = np.isfinite(m.grid.y[1:])
    disp, lb = [], []
    for j in range(z.shape[1]):
        zz = z[mask[:, j], j]
        n = len(zz)
        if n < 12:
            continue
        disp.append((float((zz ** 2).sum()) - n) / math.sqrt(2 * n))
        zc = zz - zz.mean()
        den = float((zc ** 2).sum()) or 1.0
        h = 10
        Q = n * (n + 2) * sum((float((zc[k:] * zc[:-k]).sum()) / den) ** 2 / (n - k) for k in range(1, h + 1))
        lb.append((Q - h) / math.sqrt(2 * h))
    return {"dispersion_z": max(disp, key=abs) if disp else None, "ljung_box_z": max(lb) if lb else None}


def lean_start(m: Model) -> np.ndarray:
    """The lean start (6, step 1a) for any structure: outside inflows' constants at the stock's mean
    rise per step, a flow's term on its own source stock at 0.05, every other coefficient 0, effects
    and co-flows as written, hidden stocks at 0."""
    st, g = m.st, m.grid
    rise = {}
    for j, s in enumerate(g.ids):
        d = np.diff(g.y[:, j])
        d = d[np.isfinite(d)]
        rise[s] = float(np.mean(np.maximum(d, 0))) if d.size else 0.0
    out = []
    for sl, v in zip(st.slots, st.theta0()):
        if sl.kind == "coef":
            f = st.flows[sl.flow]
            r = sl.path[2]
            if r is None:
                out.append(rise.get(f.get("to"), 0.0) if f.get("from") is None else 0.0)
            elif r == f.get("from"):
                out.append(0.05)
            else:
                out.append(0.0)
        elif sl.kind == "start":
            out.append(0.0)
        else:
            out.append(v)
    return np.array(out)


def fitted_flows(m: Model, theta) -> list[dict]:
    return write_back(m.st, np.asarray(theta, float))


__all__ = ["Model", "prepare", "fit", "lean_start", "fitted_flows", "diagnostics", "n_eta"]
