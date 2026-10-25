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


def _penalty(eta: np.ndarray, prior: float | None) -> float:
    """The phi prior's code (code table option phi-prior): 1/2 (ln phi / width)^2; 0 without one."""
    return 0.0 if prior is None else 0.5 * float(eta[0] / prior) ** 2


def _minimize(m: Model, theta: np.ndarray, eta: np.ndarray, fit_theta: bool, fixed: dict | None = None,
              prior: float | None = None) -> dict:
    """L-BFGS-B over theta (when fit_theta) and the free eta components; `fixed` {eta index: value}
    holds the others; `prior` adds the phi prior to what is minimised. With neither, this is code table
    v1's fit exactly. Returns D (the data code alone) and obj (D plus the prior)."""
    from scipy.optimize import minimize

    P = m.st.P
    vg = m.filt["value_and_grad"]
    eta = np.asarray(eta, dtype=float).copy()
    free = np.ones(len(eta), dtype=bool)
    for i, v in (fixed or {}).items():
        free[i] = False
        eta[i] = v
    if not fit_theta and not free.any():               # nothing to fit: evaluate
        D = m.D(theta, eta)
        return {"D": D, "obj": D + _penalty(eta, prior), "theta": np.asarray(theta, float), "eta": eta, "nit": 0, "calls": 1,
                "gnorm": 0.0, "message": "nothing free", "ok": True}
    sc = m.theta_scale(theta) if fit_theta else np.ones(P)
    w0 = np.concatenate([theta / sc, eta[free]]) if fit_theta else eta[free]
    bounds = ([(None, None)] * P if fit_theta else []) + [b for b, k in zip(m.eta_bounds(), free) if k]
    calls = [0]

    def unpack(w):
        et = eta.copy()
        et[free] = w[P:] if fit_theta else w
        return (w[:P] * sc if fit_theta else theta), et

    def f(w):
        calls[0] += 1
        th, et = unpack(w)
        v, g = vg(np.concatenate([th, et]), P)
        v, g = float(v), np.asarray(g, dtype=float)
        if not np.isfinite(v) or not np.all(np.isfinite(g)):
            return 1e300, np.zeros_like(w)
        ge = g[P:]
        if prior is not None:
            v = v + _penalty(et, prior)
            ge = ge.copy()
            ge[0] += et[0] / prior ** 2
        g = np.concatenate([g[:P] * sc, ge[free]]) if fit_theta else ge[free]
        return v, g

    res = minimize(f, w0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": MAXITER, "maxfun": 2 * MAXITER})
    w = res.x
    th, et = unpack(w)
    _, g = f(w)
    lo = np.array([b[0] if b[0] is not None else -np.inf for b in bounds])
    hi = np.array([b[1] if b[1] is not None else np.inf for b in bounds])
    fr = ~(((w <= lo + 1e-8) & (g > 0)) | ((w >= hi - 1e-8) & (g < 0)))
    gnorm = float(np.linalg.norm(g[fr])) if fr.any() else 0.0
    obj = float(res.fun)
    return {"D": obj - _penalty(et, prior), "obj": obj, "theta": th, "eta": et, "nit": int(res.nit), "calls": calls[0],
            "gnorm": gnorm, "message": str(res.message), "ok": bool(res.success)}


def tau_index(m: Model) -> list[int]:
    """The eta components that are a tau (kalman.eta_names): one per measured stock, and the pooled
    hidden-stock one when the structure has hidden stocks."""
    k = len(m.grid.ids)
    return list(range(2, 2 + k)) + ([2 + k] if len(m.st.ids) > m.st.n_measured else [])


def tau_price(m: Model, i: int) -> float:
    """The price of tau component i when it is on (code table option tau-priced): 1/2 ln N, N the
    stock's scored reports (the pooled hidden tau: every scored report)."""
    k = len(m.grid.ids)
    N = int(np.isfinite(m.grid.y[1:, i - 2]).sum()) if i < 2 + k else m.grid.n_reports
    return 0.5 * math.log(max(1, N))


def _fit_starts(m: Model, starts: list, fit_theta: bool, eta_starts, fixed: dict, prior) -> list[dict]:
    """v1's multi-start fit: per theta start, eta alone from each declared eta start (keep the best),
    then everything jointly; later theta starts begin from the eta the first chose. Sorted by obj."""
    tries = []
    etas, seen = [], set()
    for spec in eta_starts:
        e = m.eta_vector(spec)
        for i, v in fixed.items():
            e[i] = v
        if tuple(e) not in seen:                         # held components can make two starts one
            seen.add(tuple(e))
            etas.append(e)
    for th0 in starts:
        th0 = np.asarray(th0, dtype=float)
        best = None
        for eta in etas:
            r = _minimize(m, th0, eta, False, fixed, prior)
            if best is None or r["obj"] < best["obj"]:
                best = r
        etas = [best["eta"]]                         # later theta starts begin from the eta the first one chose
        r = _minimize(m, th0, best["eta"], True, fixed, prior) if fit_theta and m.st.P else best
        if r["obj"] > best["obj"]:                   # never worse than its own eta-only start
            r = best
        tries.append(r)
    tries.sort(key=lambda r: r["obj"])
    return tries


TAU_ON_START = ETA_STARTS[0]["ln_tau"]           # a tau that is turned on starts where the declared starts put it


def _select_tau(m: Model, b: dict, fit_theta: bool, fixed: dict, prior) -> tuple[dict, list[int]]:
    """tau-priced: from the fit with every tau off, turn each tau on alone (refit from b) and keep the
    ones that lower obj + their price; with several, try them together and keep the better. A tau stays
    off when counting noise (and the rest of eta) already explains the innovations."""
    idx = tau_index(m)
    ft = fit_theta and bool(m.st.P)
    base = b["obj"]
    gains = []
    for i in idx:
        e = np.asarray(b["eta"], float).copy()
        e[i] = TAU_ON_START
        fx = {k: v for k, v in fixed.items() if k != i}
        r = _minimize(m, np.asarray(b["theta"], float), e, ft, fx, prior)
        c = r["obj"] + tau_price(m, i)
        if c < base:
            gains.append((c, i, r))
    if not gains:
        return b, []
    gains.sort(key=lambda x: x[0])
    best_c, i0, best = gains[0]
    on = [i0]
    if len(gains) > 1:
        e = np.asarray(best["eta"], float).copy()
        all_on = [i for _, i, _ in gains]
        for _, i, r in gains[1:]:
            e[i] = r["eta"][i]
        fx = {k: v for k, v in fixed.items() if k not in all_on}
        r = _minimize(m, np.asarray(best["theta"], float), e, ft, fx, prior)
        c = r["obj"] + sum(tau_price(m, i) for i in all_on)
        if c < best_c:
            best, on = r, sorted(all_on)
    return best, on


def fit(m: Model, starts: list[np.ndarray] | None = None, fit_theta: bool = True, eta_starts=ETA_STARTS,
        held=None, table=None) -> dict:
    """The best fit over the theta starts: eta alone first (from each declared eta start, keep the
    best), then everything jointly (fit_theta). Returns J, D, the prices, theta, eta (raw and read),
    every start's J, and whether it converged (gradient norm below 1e-4 N and the best two starts
    within EPSILON, when there are two).

    table: the code table (codetable.py; default the active one, v1 unless chosen). held: the data
    set's eta vector, whose components the table holds (eta-*/phi-* options) are fixed at it; without
    `held` nothing is held. J = D + P_num + P_struct + P_eta, P_eta the priced eta elements (0 in v1)."""
    from .codetable import TAU_OFF, active

    table = active() if table is None else table
    began = time.perf_counter()
    starts = [m.theta0] if starts is None else starts
    N = max(1, m.grid.n_reports)
    fixed = {}
    if held is not None:
        fixed = {i: float(held[i]) for i in table.held_index(len(m.grid.ids))}
    taus = tau_index(m) if table.tau_priced else []
    off = {**fixed, **{i: TAU_OFF for i in taus if i not in fixed}}
    tries = _fit_starts(m, starts, fit_theta, eta_starts, off, table.phi_prior)
    agree = len(tries) < 2 or (tries[1]["obj"] - tries[0]["obj"]) <= price.EPSILON
    b, on = (_select_tau(m, tries[0], fit_theta, off, table.phi_prior) if taus else (tries[0], []))
    p_tau = sum(tau_price(m, i) for i in on)
    P_eta = p_tau + _penalty(b["eta"], table.phi_prior)
    out = {"J": m.J(b["D"]) + P_eta, "D": b["D"], "P_num": m.P_num, "P_struct": m.P_struct["total"], "P_struct_items": m.P_struct,
           "theta": np.asarray(b["theta"]).tolist(), "eta": np.asarray(b["eta"]).tolist(), "eta_read": eta_read(np.asarray(b["eta"]), m.grid),
           "gnorm": b["gnorm"], "converged": bool(b["gnorm"] < 1e-4 * N or b["ok"]), "restarts_agree": bool(agree),
           "start_J": [m.J(r["D"]) + _penalty(r["eta"], table.phi_prior) for r in tries], "message": b["message"],
           "numbers": m.st.P, "complexity": price.complexity(m.st), "seconds": round(time.perf_counter() - began, 3)}
    if not table.is_v1:
        out.update({"P_eta": P_eta, "code_table": table.name, "held": sorted(fixed), "tau_on": on})
    out["diagnostics"] = diagnostics(m, b["theta"], b["eta"])
    return out


def lean_flows(view: dict) -> list[dict]:
    """The lean model (design 6, step 1a): each measured stock has a constant inflow and an own drain."""
    out = []
    for s in view["stocks"]:
        out.append({"from": None, "to": s["id"], "rate": {"form": "constant", "value": 1.0}})
        out.append({"from": s["id"], "to": None, "rate": {"form": "proportional", "stock": s["id"], "k": 0.05}})
    return out


def lean_eta(view: dict, grid: Grid, table=None) -> dict:
    """The data set's eta from the lean model, eta free (the table's other options apply): the fit."""
    from .codetable import active

    table = active() if table is None else table
    m = prepare(view, lean_flows(view), grid=grid)
    return fit(m, [lean_start(m), m.theta0], table=table.free_only())


def joint_eta(fits: list[tuple], table=None, maxiter: int = 200) -> dict:
    """The data set's eta jointly across a candidate set: fits = [(model, theta, eta)], each a
    candidate's own free-eta fit. The held components (table.held_index) minimise the sum over
    candidates of D(theta_c, eta_c with those components shared), each candidate's other components
    and theta at their own fit. Started from the better of the candidates' componentwise median and
    the first candidate's eta. Returns {"eta", "sum_D", "candidates", "message"}."""
    from scipy.optimize import minimize

    from .codetable import active

    table = active() if table is None else table
    if not fits:
        raise ValueError("joint_eta: no candidates")
    k = len(fits[0][0].grid.ids)
    idx = np.array(table.held_index(k), dtype=int)
    etas = np.array([np.asarray(e, float) for _, _, e in fits])
    bounds = [fits[0][0].eta_bounds()[i] for i in idx]

    def total(w):
        v, gs = 0.0, np.zeros(len(idx))
        for mm, th, e in fits:
            et = np.asarray(e, float).copy()
            et[idx] = w
            P = mm.st.P
            val, g = mm.filt["value_and_grad"](np.concatenate([np.asarray(th, float), et]), P)
            val, g = float(val), np.asarray(g, float)
            if not np.isfinite(val) or not np.all(np.isfinite(g)):
                return 1e300, np.zeros(len(idx))
            v += val
            gs += g[P:][idx]
        return v, gs

    cands = [np.median(etas[:, idx], axis=0), etas[0, idx]]
    w0 = min(cands, key=lambda w: total(w)[0])
    res = minimize(total, w0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": maxiter})
    eta = etas[0].copy()
    eta[idx] = res.x
    return {"eta": eta.tolist(), "sum_D": float(res.fun), "candidates": len(fits), "message": str(res.message)}


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


__all__ = ["Model", "prepare", "fit", "lean_start", "lean_flows", "lean_eta", "joint_eta", "fitted_flows", "diagnostics", "n_eta"]
