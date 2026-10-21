"""Prototype (scratch, not a strategy): output-error refit of a found model on measured levels.

Data only: stocks (page stocks, 'final' flags), measured levels, inputs, injections. No truth.
Flows supported: proportional, linear (c + sum k X), expr [g *] min(a X, b Y). Anything else -> None.
Simulation follows the engine: injections first, then flows read the previous levels (+ injection) and
the input at step t; outflows are floored at 0 and capped at what the stock holds.
Stocks without flows in the model are exogenous: initial + announced injections (initial = median).
Noise sd per stock: sqrt(a + b x^2) from the lag-1 covariance of the level changes (measurement error
makes consecutive changes negatively correlated).
"""
from __future__ import annotations

import math
import re

import numpy as np
from scipy.optimize import least_squares

NUM = r"(-?[0-9.]+(?:e[-+]?[0-9]+)?)"
MIN_RE = re.compile(rf"^\s*(?:{NUM}\s*\*\s*)?min\(\s*(?:{NUM}\s*\*\s*)?\(?(\w+)\)?\s*,\s*(?:{NUM}\s*\*\s*)?\(?(\w+)\)?\s*\)\s*$")


def parse(flows):
    """[(from, to, kind, reads, p0)] or None. kind: 'lin' (reads: ['1'?, X...]) or 'min' (reads [X, Y])."""
    out = []
    for f in flows:
        if f.get("effects") or f.get("uses") or f.get("byTime") or f.get("pieces"):
            return None
        r = f.get("rate") or {}
        form = r.get("form")
        if form == "proportional":
            out.append([f.get("from"), f.get("to"), "lin", [r["stock"]], [float(r["k"])]])
        elif form == "linear":
            reads, p = [], []
            if float(r.get("c") or 0) != 0:
                reads.append("1"); p.append(float(r["c"]))
            for t in r.get("terms") or []:
                reads.append(t["stock"]); p.append(float(t["k"]))
            out.append([f.get("from"), f.get("to"), "lin", reads, p])
        elif form == "expr":
            m = MIN_RE.match(r.get("expr", ""))
            if not m:
                return None
            g, a, x, b, y = m.groups()
            g = float(g) if g else 1.0
            a = float(a) if a else 1.0
            b = float(b) if b else 1.0
            if g <= 0:
                return None
            out.append([f.get("from"), f.get("to"), "min", [x, y], [g * a, g * b]])
        else:
            return None
    return out


def noise_sd(x):
    d = np.diff(x)
    y = -d[:-1] * d[1:]
    lv = x[1:-1] ** 2
    A = np.column_stack([np.ones_like(lv), lv])
    from scipy.optimize import nnls
    coef, _ = nnls(A, y)
    v = A @ coef
    v = np.concatenate([[v[0]], v, [v[-1]]])
    floor = max(1e-12, 1e-6 * np.var(x))
    return np.sqrt(np.maximum(v, floor))


class Model:
    def __init__(self, spec, stocks, run, opts):
        self.spec = spec
        self.ids = [s["id"] for s in stocks]
        self.final = {s["id"] for s in stocks if s.get("final")}
        self.L = {k: np.asarray(v, float) for k, v in run["levels"].items()}
        self.T = len(run["t"])
        self.t = np.asarray(run["t"])
        self.inputs = {k: np.asarray(v, float) for k, v in (opts.get("inputs") or {}).items()}
        self.inj = {}
        for j in opts.get("injections") or []:
            self.inj.setdefault(j["stock"], np.zeros(self.T))
            idx = np.searchsorted(self.t, j["t"])
            if idx < self.T:
                self.inj[j["stock"]][idx] += float(j["amount"])
        self.sim_ids = sorted(self.L)                     # every measured stock is simulated and scored
        self.exo = {}
        for k in self.L:
            if k not in self.sim_ids:
                cum = np.cumsum(self.inj.get(k, np.zeros(self.T)))
                self.exo[k] = np.median(self.L[k] - cum) + cum
        self.sd = {k: noise_sd(self.L[k]) for k in self.sim_ids}
        self.np_ = sum(len(f[4]) for f in spec if f[2] != "fix")

    def p0(self):
        return np.array([v for f in self.spec if f[2] != "fix" for v in f[4]] + [self.L[k][0] for k in self.sim_ids])

    def sim(self, P):
        """P: (B, p). Levels (B, T, n) of sim_ids."""
        B = P.shape[0]
        n = len(self.sim_ids)
        pos = {k: i for i, k in enumerate(self.sim_ids)}
        x = P[:, self.np_:].copy()
        out = np.empty((B, self.T, n))
        injm = np.column_stack([self.inj.get(k, np.zeros(self.T)) for k in self.sim_ids])
        takers = {}
        for fi, f in enumerate(self.spec):
            if f[0] in pos:
                takers.setdefault(f[0], []).append(fi)
        for s in range(self.T):
            x = x + injm[s]
            def val(name):
                if name == "1":
                    return np.ones(B)
                if name in pos:
                    return x[:, pos[name]]
                if name in self.exo:
                    return np.full(B, self.exo[name][s])
                if name in self.inputs:
                    return np.full(B, self.inputs[name][s])
                return np.zeros(B)
            amt = []
            j = 0
            for f in self.spec:
                if f[2] == "fix":
                    amt.append(np.maximum(sum(c * val(r) for c, r in zip(f[4], f[3])), 0.0)); continue
                k = len(f[4])
                if f[2] == "lin":
                    q = sum(P[:, j + i] * val(r) for i, r in enumerate(f[3]))
                else:
                    q = np.minimum(P[:, j] * val(f[3][0]), P[:, j + 1] * val(f[3][1]))
                amt.append(np.maximum(q, 0.0))
                j += k
            for st, fis in takers.items():
                want = sum(amt[i] for i in fis)
                have = np.maximum(x[:, pos[st]], 0.0)
                sc = np.where(want > have, have / np.maximum(want, 1e-300), 1.0)
                for i in fis:
                    amt[i] = amt[i] * sc
            dx = np.zeros_like(x)
            for f, q in zip(self.spec, amt):
                if f[0] in pos:
                    dx[:, pos[f[0]]] -= q
                if f[1] in pos:
                    dx[:, pos[f[1]]] += q
            x = x + dx
            out[:, s, :] = x
        return out

    def resid(self, P):
        Y = np.column_stack([self.L[k] for k in self.sim_ids])
        W = np.column_stack([self.sd[k] for k in self.sim_ids])
        return (self.sim(P) - Y[None]) / W[None]

    def fit(self, p0=None, nfev=60):
        p = self.p0() if p0 is None else np.asarray(p0, float)
        def fun(q):
            return self.resid(q[None])[0].ravel()
        def jac(q):
            h = 1e-6 * np.maximum(np.abs(q), 1e-3)
            P = np.vstack([q] + [q + np.eye(len(q))[i] * h[i] for i in range(len(q))])
            R = self.resid(P).reshape(len(P), -1)
            return ((R[1:] - R[0]) / h[:, None]).T
        sol = least_squares(fun, p, jac=jac, x_scale="jac", max_nfev=nfev)
        self.p = sol.x
        self.ssr = float(2 * sol.cost)
        N = self.T * len(self.sim_ids)
        self.bic = self.ssr + len(p) * math.log(N)
        return self

    def flows(self):
        out, j = [], 0
        for f in self.spec:
            if f[2] == "fix":
                out.append({"id": f"oe{len(out)}", "from": f[0], "to": f[1], "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": r, "k": float(v)} for r, v in zip(f[3], f[4])]}}); continue
            k = len(f[4]); q = self.p[j:j + k]; j += k
            if f[2] == "lin":
                terms = [{"stock": r, "k": float(v)} for r, v in zip(f[3], q) if r != "1"]
                c = float(q[f[3].index("1")]) if "1" in f[3] else 0.0
                out.append({"id": f"oe{len(out)}", "from": f[0], "to": f[1], "rate": {"form": "linear", "c": c, "terms": terms}})
            else:
                out.append({"id": f"oe{len(out)}", "from": f[0], "to": f[1], "rate": {"form": "expr", "expr": f"min({q[0]} * {f[3][0]}, {q[1]} * {f[3][1]})"}})
        return out


def with_params(spec, m):
    j, new = 0, []
    for f in spec:
        if f[2] == "fix":
            new.append(list(f)); continue
        k = len(f[4]); new.append([f[0], f[1], f[2], list(f[3]), list(m.p[j:j + k])]); j += k
    return new


def refit(flows, stocks, run, opts, search=True, log=print):
    spec = parse(flows)
    if spec is None:
        return None
    bnd = run.get("boundary") or {}
    for f in spec:
        if f[0] is None and f[2] == "lin" and len(f[3]) == 1 and f[3][0] in (opts.get("inputs") or {}) and "input" in (bnd.get(f[1], {}).get("in") or []):
            f[2], f[4] = "fix", [1.0]
    m = Model(spec, stocks, run, opts).fit()
    log(f"  refit own structure: bic {m.bic:.1f}")
    if not search:
        return m
    while True:
        spec = with_params(m.spec, m)
        best = m
        cands = []
        for i in range(len(spec)):                       # drop a flow
            cands.append(("drop", spec[:i] + spec[i + 1:]))
        sim = m.sim_ids
        ends = set(m.L)
        for x in [k for k in ends if k not in m.final]:  # add a move x -> y (or out) at k x, from 0.01
            outs = [None] if (not run.get("boundary_declared") or (run.get("boundary") or {}).get(x, {}).get("out")) else []
            for y in [k for k in ends if k != x] + outs:
                if any(f[0] == x and f[1] == y and f[2] == "lin" and f[3] == [x] for f in spec):
                    continue
                cands.append((f"add {x}->{y}", spec + [[x, y, "lin", [x], [0.01]]]))
        for i, f in enumerate(spec):                     # re-source: a move that reads one stock x comes from x
            if f[2] == "lin" and len(f[3]) == 1 and f[3][0] in m.L and f[3][0] != f[0] and f[3][0] != f[1] and f[3][0] not in m.final:
                cands.append((f"resource {f[0]}->{f[1]} from {f[3][0]}", spec[:i] + [[f[3][0], f[1], "lin", list(f[3]), list(f[4])]] + spec[i + 1:]))
        for label, sp in cands:
            try:
                c = Model(sp, stocks, run, opts)
                c.fit(p0=np.concatenate([[v for f in sp if f[2] != "fix" for v in f[4]], [m.L[k][0] for k in c.sim_ids]]), nfev=40)
            except Exception as e:                          # noqa: BLE001
                continue
            if c.bic < best.bic - 1e-6:
                best, lab = c, label
        if best is m:
            return m
        log(f"  {lab}: bic {best.bic:.1f}")
        m = best.fit(p0=best.p, nfev=60)


def normalise_drains(flows):
    """A stock whose own proportional outflows sum above 1 a step is emptied each step (the engine caps
    them at what it holds): only their shares are seen, so they are written summing to 1."""
    out = [dict(f, rate=dict(f["rate"])) for f in flows]
    by = {}
    for f in out:
        r = f["rate"]
        if f.get("from") and r.get("form") == "linear" and not r.get("c") and len(r["terms"]) == 1 and r["terms"][0]["stock"] == f["from"]:
            by.setdefault(f["from"], []).append(f)
    for s, fs in by.items():
        tot = sum(f["rate"]["terms"][0]["k"] for f in fs)
        if tot > 1:
            for f in fs:
                f["rate"]["terms"] = [{"stock": s, "k": f["rate"]["terms"][0]["k"] / tot}]
    return out
