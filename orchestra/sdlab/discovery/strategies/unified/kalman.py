"""The filter (code table v1): an extended Kalman filter on the engine's step, and the data code D.

    D = - sum_i ln P( y_i in [y_i - q/2, y_i + q/2] | y_<i )        (unified-design.md, 4.1)

Each step: injections, then the step's mean through the engine (engine.py) and its Jacobian A (JAX),
the process noise

    Q = phi * V (diag(a) - beta * B) V' + diag(tau)

(a: the step's amounts at the mean; B: for each source stock, the outer product of the amounts it gives
up over its level, the multinomial split of `master_eq`; V: the stoichiometry with co-flows), P = A P A'
+ Q, then each measured stock's report in turn as a scalar update with variance

    R = q^2/12 + alpha + rho^2 mu^2

scored as the probability of its quantisation bin under the Gaussian predictive. A report at or below
q/2 of a stock with a floor takes the whole mass below the bin (the censoring mass, A-cens). The
first report of each measured stock starts the filter and is not scored (the same constant for every
model with the same measured stocks). Hidden stocks start at their slot with a fixed variance.

Deviation from the design, stated: v1 linearises at the filtered mean (plain EKF), not around an
RTS-smoothed reference path (the iterated EKF); phi scales the split term too, so the noise stays
positive semi-definite for every beta in [0, 1].

eta (one layout for every model on a grid): [ln phi, logit beta, ln tau_i (measured), ln tau_hidden,
ln alpha_i, ln rho2_i]; tau and alpha are in units of the stock's level scale squared.
"""

from __future__ import annotations

import math
import os

import numpy as np

os.environ.setdefault("XLA_FLAGS", "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1")

from .engine import make_step  # noqa: E402
from .frontend import Grid, Structure  # noqa: E402

HIDDEN_START_SD = 0.25          # a hidden stock's start: sd = this x the measured stocks' mean level scale


def n_eta(grid: Grid) -> int:
    return 3 + 3 * len(grid.ids)


def eta_names(grid: Grid) -> list[str]:
    m = grid.ids
    return ["ln_phi", "logit_beta"] + [f"ln_tau[{s}]" for s in m] + ["ln_tau[hidden]"] + [f"ln_alpha[{s}]" for s in m] + [f"ln_rho2[{s}]" for s in m]


def eta_read(eta: np.ndarray, grid: Grid) -> dict:
    """The noise character in plain numbers."""
    m = len(grid.ids)
    sc2 = grid.scale ** 2
    return {"phi": float(np.exp(eta[0])), "beta": float(1 / (1 + np.exp(-eta[1]))),
            "tau": {s: float(np.exp(eta[2 + i]) * sc2[i]) for i, s in enumerate(grid.ids)},
            "tau_hidden": float(np.exp(eta[2 + m]) * float(np.mean(sc2))),
            "alpha": {s: float(np.exp(eta[3 + m + i]) * sc2[i]) for i, s in enumerate(grid.ids)},
            "rho2": {s: float(np.exp(eta[3 + 2 * m + i])) for i, s in enumerate(grid.ids)}}


def _jax():
    import jax
    jax.config.update("jax_enable_x64", True)
    return jax


def arrays(st: Structure, grid: Grid) -> dict:
    """The per-step inputs of the scan (numpy)."""
    S, Sm = len(st.ids), st.n_measured
    Tg = len(grid.times)
    u = np.stack([grid.inputs[k] for k in st.inputs], axis=1) if st.inputs else np.zeros((Tg, 0))
    inj = np.zeros((Tg, S))
    pos = {int(t): i for i, t in enumerate(grid.times)}
    for t, s, amt in grid.injections:
        if t in pos and s in st.ids:
            inj[pos[t], st.ids.index(s)] += amt
    y = grid.y.copy()
    mask = np.isfinite(y)
    first = np.array([y[np.flatnonzero(mask[:, j])[0], j] if mask[:, j].any() else 0.0 for j in range(Sm)])
    return {"tidx": st.tidx, "u": u, "inj": inj, "y": np.nan_to_num(y), "mask": mask, "first": first}


def make_filter(st: Structure, grid: Grid, censor: bool = True):
    """run(theta, eta) -> (D, per-report log bin probabilities, standardised innovations), jitted."""
    jax = _jax()
    import jax.numpy as jnp
    from jax.scipy.special import log_ndtr

    step = make_step(st)
    ar = arrays(st, grid)
    S, Sm = len(st.ids), st.n_measured
    q = jnp.asarray(grid.q)
    sc2 = jnp.asarray(grid.scale ** 2)
    unsigned = ~np.asarray(st.signed)
    floor_m = jnp.asarray(unsigned[:Sm] & censor)
    uns = jnp.asarray(unsigned)
    hid = [(i, sl) for i, sl in st.starts]
    msc = float(np.mean(grid.scale))
    hvar = (HIDDEN_START_SD * msc) ** 2
    # each source stock's takers as a 0/1 row over flows (the split term)
    take_rows = []
    for c, tk in step.takers.items():
        row = np.zeros(len(st.flows))
        for fi, _, _ in tk:
            row[fi] = 1.0
        take_rows.append((c, jnp.asarray(row)))
    xs = (jnp.asarray(ar["tidx"][1:]), jnp.asarray(ar["u"][1:]), jnp.asarray(ar["inj"][1:]), jnp.asarray(ar["y"][1:]), jnp.asarray(ar["mask"][1:]))
    first = jnp.asarray(ar["first"])
    eye = jnp.eye(S)

    def logbin(y, mu, s, qq, cens):
        lo_z, hi_z = (y - qq / 2 - mu) / s, (y + qq / 2 - mu) / s
        up = y > mu
        a = jnp.where(up, log_ndtr(-lo_z), log_ndtr(hi_z))
        b = jnp.where(up, log_ndtr(-hi_z), log_ndtr(lo_z))
        lp = a + jnp.log(jnp.maximum(-jnp.expm1(b - a), 1e-300))
        return jnp.where(cens, log_ndtr(hi_z), lp)

    def run(theta, eta):
        th = jnp.concatenate([theta, jnp.zeros(1)])
        phi = jnp.exp(eta[0])
        beta = jax.nn.sigmoid(eta[1])
        tau = jnp.concatenate([jnp.exp(eta[2:2 + Sm]) * sc2, jnp.full(S - Sm, jnp.exp(eta[2 + Sm]) * jnp.mean(sc2))])
        alpha = jnp.exp(eta[3 + Sm:3 + 2 * Sm]) * sc2
        rho2 = jnp.exp(eta[3 + 2 * Sm:3 + 3 * Sm])
        V = step.stoich(th)
        m0 = jnp.zeros(S).at[:Sm].set(first)
        for i, sl in hid:
            m0 = m0.at[i].set(th[sl])
        R0 = q ** 2 / 12 + alpha + rho2 * first ** 2
        P0 = jnp.diag(jnp.concatenate([R0, jnp.full(S - Sm, hvar)]))

        def body(carry, inp):
            m, P = carry
            trow, urow, irow, yrow, mrow = inp
            x = m + irow
            x = jnp.where(uns, jnp.maximum(x, 0.0), x)
            f = lambda xx: step(th, xx, trow, urow)  # noqa: E731
            (mp, a), A = f(x), jax.jacfwd(lambda xx: f(xx)[0])(x)
            aa = jnp.abs(a)
            C = jnp.diag(aa)
            for c, row in take_rows:
                ac = aa * row
                C = C - beta * jnp.outer(ac, ac) / jnp.maximum(x[c], 1e-9)
            Q = phi * (V @ C @ V.T) + jnp.diag(tau) + 1e-12 * eye
            P = A @ P @ A.T + Q
            m = mp
            lps, zs = [], []
            for j in range(Sm):
                mu = m[j]
                s2 = P[j, j] + q[j] ** 2 / 12 + alpha[j] + rho2[j] * mu ** 2
                s = jnp.sqrt(s2)
                yj, ok = yrow[j], mrow[j]
                lp = logbin(yj, mu, s, q[j], floor_m[j] & (yj <= q[j] / 2))
                K = P[:, j] / s2
                m = jnp.where(ok, m + K * (yj - mu), m)
                P = jnp.where(ok, P - jnp.outer(K, P[j, :]), P)
                lps.append(jnp.where(ok, lp, 0.0))
                zs.append(jnp.where(ok, (yj - mu) / s, 0.0))
            m = jnp.where(uns, jnp.maximum(m, 0.0), m)
            P = 0.5 * (P + P.T)
            return (m, P), (jnp.stack(lps), jnp.stack(zs))

        _, (lp, z) = jax.lax.scan(body, (m0, P0), xs)
        return -lp.sum(), lp, z

    jrun = jax.jit(run)
    D = jax.jit(lambda th, et: run(th, et)[0])
    grad = jax.jit(jax.value_and_grad(lambda w, n: run(w[:n], w[n:])[0]), static_argnums=1)
    return {"run": jrun, "D": D, "value_and_grad": grad, "P": st.P, "n_eta": n_eta(grid)}


def bin_constant(grid: Grid) -> float:
    """sum over scored reports of ln q (the bin's width): D + this is the density code."""
    m = np.isfinite(grid.y[1:])
    return float(sum(m[:, j].sum() * math.log(grid.q[j]) for j in range(len(grid.ids))))
