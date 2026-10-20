"""Evidence beside the pass: is a found model consistent with what the data can say about the truth?

Two checks on a found model and the run discovery saw. Neither changes score.py or any status; each
reports what it found and, when it fails, what kind of wrong it points to. Both are scoring, so they
use the truth (rule 1 is about discovery).

**BOUND** (`bound_check`). For every true number (the scorer's parts, score.py, per window; and the
measured stocks' linear system, its entries) the Cramer-Rao standard error of the truth's own
structure on this run: the Kalman filter's information over every stock jointly (noise_kf.SSM, the
same model noise_oracle.py scales the scorer's tolerances by; for a counts variant, the counts run
observed at every step to the whole number, as strict.refit builds it). The found number's error in
units of that SE (z), the truth's own refit on the same run in the same units (so a number the run
itself pulls off is told from a method's error), each found part the truth lacks against the SE of
that term added to the truth, and the joint distance of all found numbers from the true ones under
the bound's covariance (chi-square on the directions the run pins down; its p-value is the
confidence that the found numbers are a draw the data could have given). A number the run does not pin
down at all (unidentified) is listed in `unidentified` and is no evidence either way: it does not make `ok`
false (the truth itself has it). Noise-free data (`none`)
have no noise model: every SE is the floor FLOOR_REL x |true| (the data carry 4 decimals; the
scorer's own tolerance there is 2%), and the joint test is not made.

**LIKELIHOOD** (`likelihood_check`). The found model's and the truth's log-likelihood on the
reported data under one noise model, the truth's (process noise from the true rates at the true
levels, the variant's reading error, the same diffuse start): the Kalman filter's one-step
prediction errors, so only the mean dynamics differ. The truth's numbers are refitted on the run
(SSM.refit: the best the true structure does on these data). LR = 2 (ll_truth_refit - ll_found):

- LR > chi2_(1-ALPHA)(df), df the truth's identifiable numbers: **the data reject the found model**:
  it fits worse than the true structure does even at its true numbers in all but ALPHA of runs;
- -LR > chi2_(1-ALPHA)(max(1, extra)), extra = found numbers - true numbers (found_numbers: a breakpoint
  the method placed counts as one number, which is generous to it): **the found model fits better than
  the truth can**: it fits the run's noise with its extra numbers or pieces (or the refit failed);
- otherwise **the data cannot tell them apart**. p = P(chi2_df >= LR) is the confidence.

Three guards (an adversarial check, 2026-10-20, on the truth itself given as the found model): the reference is
the better of the refit and the true numbers (the refit, Gauss-Newton at fixed innovation covariances, can end
below the true numbers on weekly means); a biased variant gives the found model its bias free, as the refit has
it (a found model that took the bias out and one in the reported units are both judged at their best bias; the
truth itself was rejected by LR 400-1000 without it); and where the noise model rejects the truth itself against
its refit (LR_truth > the critical value: a floor that binds, a two-way flow's counting noise, readings that are
not Gaussian), a found model is rejected only when it also fits worse than the true numbers by the critical value.

A rejection comes with where the misfit is: each measured stock's share of the likelihood loss, its
one-step errors' mean (a level offset: a constant or an inflow wrong or missing) and lag-1
autocorrelation (a slow error: a rate or time constant wrong), and the reader (a stock's level, an
input, or the constant) the stock's errors follow most (the term in that stock's equation to look at).

**Covered**: truths whose rates are linear in the stocks and the measured inputs (constant,
proportional, gap, linear; schedules, eras and injections too), on every variant (noisy ones by
their observation model). **Not covered** (None, with the reason): effects, co-flows, delays, MIN,
switches, expressions and other non-linear rates, sub-step truths (dt < 1), and, for the
likelihood, a found model that is not linear in the measured stocks and inputs or has a stock of its
own (a hidden stock).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import chi2

from ..skill import truth_by_time
from . import noise_kf
from .fisher import _rate_leaves, bound as _pinv
from .noise_oracle import _Kalman, clean_view
from .parts import ONE, label, linear_system, parts, windows
from .substep import substeps

Z = 3.0                 # the scorer's z
ALPHA = 0.01            # the likelihood test's and the joint bound's level
FLOOR_REL = 1e-3        # noise-free data: an SE of 0.1% of the true number
NOT_COVERED = ("the truth has effects, co-flows, delays or a rate that is not linear in the stocks and measured inputs "
               "(MIN, switches, expressions): the Kalman model does not cover it")


class Cell:
    """One case x variant x run: the truth's Kalman model (or why there is none) and its refit."""

    def __init__(self, case: dict, variant_name: str, data: dict | None = None):
        from . import cases as casemod
        from . import data as datamod
        self.case, self.variant = case, variant_name
        v = casemod.variant(case, variant_name)
        self.tm = casemod.truth_model(case, variant_name)
        self.data = data if data is not None else datamod.load(case, variant_name)
        self.noise_free = v.get("noise") == "none" and not self.data.get("observation")
        t = self.data["t"]
        self.wins = windows(self.tm, t)
        self.truth_flows = truth_by_time(self.tm, t)[0]
        self.measured = list(self.data["levels"])
        lv = self.data.get("all_levels") or self.data["levels"]
        self.inputs = sorted(set(self.data.get("inputs") or {}) - set(lv))
        self.means = {s: float(np.mean(x)) for s, x in lv.items() if len(x)}
        self.means.update({k: float(np.mean(x)) for k, x in (self.data.get("inputs") or {}).items() if k in self.inputs and len(x)})
        self.m, self.why = None, None
        if substeps(self.tm) != 1:
            self.why = "a sub-step truth (dt < 1) is not covered"
        elif not noise_kf.covered(self.truth_flows):
            self.why = NOT_COVERED
        elif not self.noise_free:
            if self.data.get("observation"):
                self.m = noise_kf.model(self.data, self.wins)
            else:
                self.m = noise_kf.model(clean_view({"clean": {**self.data, "flows": self.truth_flows}}), self.wins)
            if self.m is None:
                self.why = "the Kalman model could not be built on this run"
        self._refit = self._K = self._parts = self._entries = None

    @property
    def covered(self) -> bool:
        return self.why is None

    def refit(self) -> np.ndarray:
        if self._refit is None:
            self._refit = self.m.refit()
        return self._refit

    def kalman(self) -> _Kalman:
        if self._K is None:
            self._K = _Kalman(self.m)
        return self._K

    def truth_numbers(self) -> int:
        """The truth's numbers (non-zero rate leaves per schedule segment; a variant's bias not counted)."""
        return sum(_nonzero(g["rate"]) for f in self.truth_flows for g in f["byTime"])


# ---- found models' numbers ----

def _nonzero(rate: dict | None) -> int:
    return sum(1 for _, v in _rate_leaves(rate) if v)


def found_numbers(flows: list[dict], announced: set | frozenset = frozenset()) -> int:
    """How many numbers a found model fitted: its non-zero rate leaves (per byTime segment), its outside-inflow
    pieces' values (distinct levels when it says how many), co-flow pers, and every breakpoint between pieces or
    segments that is not an announced era's start (a breakpoint placed by the method is a fitted number; one
    chosen among many positions is worth more than one, so this count is generous to the found model). A zero
    constant is not a number the model uses; the truth is counted the same way (its breakpoints are given)."""
    n = 0
    for f in flows:
        segs = f.get("inflow") or f.get("byTime") or []
        if f.get("inflow"):
            n += int(f.get("levels") or len(f["inflow"]))
        elif f.get("byTime"):
            n += sum(_nonzero(g.get("rate")) for g in f["byTime"])
        else:
            n += _nonzero(f.get("rate"))
        n += sum(1 for g in segs[1:] if not any(abs(int(g["from"]) - a) <= 1 for a in announced))
        n += sum(1 for u in f.get("uses") or [] if isinstance(u.get("per"), (int, float)))
    return n


def _flows(found) -> list[dict]:
    return found.get("flows") if isinstance(found, dict) else list(found or [])


def _found_parts(cell: Cell, flows: list[dict]) -> list[dict]:
    return [parts(flows, set(cell.measured), w, set(cell.inputs))[0] for w in cell.wins]


def _scale(cell: Cell) -> float:
    """score.py's scale: the median size of the true parts (|k| x mean level of what it reads)."""
    sizes = []
    for w in cell.wins:
        for k, v in parts(cell.truth_flows, set(cell.measured), w, set(cell.inputs))[0].items():
            if k[0] in ("flow", "via") and isinstance(v, (int, float)):
                sizes.append(abs(v) * (1.0 if k[3] == ONE else cell.means.get(k[3], 0.0)))
    sizes = [s for s in sizes if s > 0]
    return float(np.median(sizes)) if sizes else 1.0


def _floor_se(cell: Cell, true: float, reader: str | None, scale: float) -> float:
    if true:
        return FLOOR_REL * abs(true)
    level = 1.0 if reader in (None, ONE) else max(1e-9, cell.means.get(reader, 0.0))
    return FLOOR_REL * scale / level


def _z(a: float | None, b: float | None, se: float | None) -> float | None:
    if a is None or b is None or not se:
        return None
    return float((a - b) / se)


def _joint(dev: np.ndarray, D: np.ndarray, C: np.ndarray) -> dict | None:
    """The deviation's chi-square under the covariance D C D' (on the directions with variance) and its p-value."""
    if not len(dev):
        return None
    S = D @ C @ D.T
    Sinv, null = _pinv(S + 1e-300 * np.eye(len(S)))
    df = len(S) - (null.shape[1] if null.size else 0)
    if df <= 0:
        return None
    stat = float(dev @ Sinv @ dev)
    return {"chi2": stat, "df": int(df), "p": float(chi2.sf(stat, df))}


def _diagnose(row: dict) -> str:
    z, zr, zfr = row.get("z"), row.get("z_refit"), row.get("z_found_refit")
    if row.get("se") is None:
        return "unidentified: the data do not pin this number down"
    if not row["found_has"]:
        return "missing term: the truth has it, the found model does not" if abs(z) > Z else "missing but small: within the bound"
    if abs(z) <= Z:
        return "within the bound"
    if zr is not None and abs(zr) > Z and zfr is not None and abs(zfr) <= Z:
        return "the run's draw: the truth's own refit on this run is as far off (data-limited, not the method)"
    return "method error: further from the truth than this run allows, and the truth's refit is not"


def bound_check(cell: Cell, found) -> dict | None:
    """Each true number's Cramer-Rao SE on this run and the found number's error in those units (see the
    module docstring). None (with cell.why) when the truth is not covered."""
    if not cell.covered:
        return None
    flows = _flows(found)
    fparts = _found_parts(cell, flows)
    scale = _scale(cell)
    rows, extras, dev, Drows, ext = [], [], [], [], []
    if cell.noise_free:
        tparts = [parts(cell.truth_flows, set(cell.measured), w, set(cell.inputs))[0] for w in cell.wins]
        tvals = {(w, k, None): float(v) for w, tp in enumerate(tparts) for k, v in tp.items() if k[0] in ("flow", "via") and isinstance(v, (int, float))}
        refit_vals, D = None, None
    else:
        K = cell.kalman()
        keys, vals, D = K._table("parts")
        tvals = {k: float(vals[i]) for k, i in keys.items()}
        refit_vals = cell.m.part_values(cell.refit())
    for key, tv in tvals.items():
        w, k, sub = key
        fp = fparts[w]
        if sub is None:
            has = k in fp and isinstance(fp[k], (int, float))
            fv = float(fp[k]) if has else 0.0
        else:
            has = k in fp and isinstance(fp[k], dict) and sub in fp[k]
            fv = float(fp[k][sub]) if has else None
        reader = k[3] if k[0] in ("flow", "via") else None
        se = _floor_se(cell, tv, reader, scale) if cell.noise_free else cell.kalman().se("parts", key)
        se = None if se is False else se
        rv = None if refit_vals is None else refit_vals.get(key)
        row = {"key": label(k) + (f" {sub}" if sub else ""), "window": w, "true": tv, "found": fv if has else None, "found_has": has,
               "se": se, "z": _z(fv, tv, se), "refit": rv, "z_refit": _z(rv, tv, se),
               "z_found_refit": _z(fv, rv, se)}
        if fv is None:                                    # a hidden part's delay the found model lacks
            row["z"] = None
            row["diagnosis"] = "missing term: the truth has it, the found model does not"
        else:
            row["diagnosis"] = _diagnose(row)
        rows.append(row)
        if not cell.noise_free and fv is not None:
            dev.append(fv - tv)
            Drows.append(D[keys[key]])
    true_keys = {k for _, k, _ in tvals}
    for w, fp in enumerate(fparts):
        for k, v in fp.items():
            if k in true_keys or k[0] != "flow" or not isinstance(v, (int, float)):
                continue
            _, a, b, j = k
            if cell.noise_free:
                se = _floor_se(cell, 0.0, j, scale)
            else:
                rws = {s: x for s, x in ((b, 1.0), (a, -1.0)) if s}
                se = cell.kalman().extra_se(rws, j) if rws else None
            z = _z(float(v), 0.0, se)
            if not cell.noise_free and rws:
                ext.append((rws, j, w, float(v)))
            extras.append({"key": label(k), "window": w, "found": float(v), "se": se, "z": z,
                           "diagnosis": "spurious term: larger than the run's noise could make of a term that is not there"
                           if z is not None and abs(z) > Z else "extra but within the noise" if z is not None else "extra: no SE"})
    # the joint test in the truth extended by the found model's extra terms (each one more number, as the scorer's
    # spurious test adds it): a found model that trades a true number for an extra term is judged with that freedom
    C = None
    if not cell.noise_free:
        C = cell.m.bound([(r_, c_, w_) for r_, c_, w_, _ in ext])[0] if ext else cell.kalman()._bound()[0]
        E = len(ext)
        Drows = [np.concatenate([d_, np.zeros(E)]) for d_ in Drows]
        for i, (_, _, _, v) in enumerate(ext):
            dev.append(v)
            Drows.append(np.concatenate([np.zeros(cell.m.P), np.eye(E)[i]]))
    entries = _entries(cell, flows, ext, C)
    out = {"check": "bound", "noise_free": cell.noise_free, "floor_rel": FLOOR_REL if cell.noise_free else None, "z_limit": Z,
           "parts": rows, "extra": extras, "entries": entries}
    if not cell.noise_free:
        out["joint"] = _joint(np.array(dev), np.array(Drows), C) if dev else None
        if out["joint"] is not None:
            out["joint"]["extra_terms"] = len(ext)
    zs = [abs(r["z"]) for r in rows + extras if r.get("z") is not None]
    out["worst_z"] = max(zs) if zs else None
    # an unidentified number is no evidence either way (the truth itself has it): reported, not held against the model
    out["unidentified"] = [r["key"] for r in rows if r["diagnosis"].startswith("unidentified")]
    bad = [r for r in rows if r["diagnosis"] not in ("within the bound", "missing but small: within the bound")
           and not r["diagnosis"].startswith("unidentified")] + \
          [e for e in extras if e["diagnosis"].startswith("spurious")]
    out["ok"] = not bad and (out.get("joint") is None or out["joint"]["p"] >= ALPHA)
    kinds = sorted({r["diagnosis"].split(":")[0] for r in bad})
    ratios = [r["found"] / r["true"] for r in bad if r.get("found") is not None and r.get("true") and r in rows]
    if len(ratios) >= 2 and max(ratios) - min(ratios) <= 0.2 * abs(1 - float(np.mean(ratios))) + 0.005 and abs(1 - float(np.mean(ratios))) > 0.005:
        kinds.append(f"common factor: every number off by about x{float(np.mean(ratios)):.3f} (a time scale or a gain off as a whole; "
                     "with measurement error, the attenuation of a regression on noisy levels)")
    if not bad and out.get("joint") and out["joint"]["p"] < ALPHA:
        kinds = ["jointly off: no number alone is beyond the bound, together they are (p < ALPHA)"]
    if bad and entries is not None and entries["ok"]:
        kinds.append("re-parameterisation: the parts differ but the measured stocks' linear system is within the bound (the data cannot tell)")
    out["kinds"] = kinds
    return out


def _entries(cell: Cell, flows: list[dict], ext: list = (), C_ext: np.ndarray | None = None) -> dict | None:
    """The measured stocks' linear system per window (every stock's change as a function of the levels,
    the inputs and the constant), true vs found, in SE units: structure-free, so an equivalent found
    structure is within it."""
    if cell.m is not None and cell.m.hidden:
        return None
    cols = cell.measured + cell.inputs
    rows = []
    if cell.noise_free:
        scale = _scale(cell)
        for w, win in enumerate(cell.wins):
            T, F = linear_system(cell.truth_flows, cols, win), linear_system(flows, cols, win)
            if T is None or F is None:
                return None
            for i, r in enumerate(cell.measured):
                for j, c in enumerate([*cols, ONE]):
                    tv = float(T[1][i]) if c == ONE else float(T[0][i, j])
                    fv = float(F[1][i]) if c == ONE else float(F[0][i, j])
                    if tv == 0 and fv == 0:
                        continue
                    se = _floor_se(cell, tv, c, scale)
                    rows.append({"row": r, "col": c, "window": w, "true": tv, "found": fv, "se": se, "z": _z(fv, tv, se)})
        joint = None
    else:
        K = cell.kalman()
        keys, vals, D = K._table("entries")
        dev, Dr = [], []
        found_sys = {}
        for w, win in enumerate(cell.wins):
            F = linear_system(flows, cols, win)
            if F is None:
                return None
            found_sys[w] = F
        for key, i in keys.items():
            w, r, c = key
            F = found_sys[w]
            ri = cell.measured.index(r)
            fv = float(F[1][ri]) if c == ONE else float(F[0][ri, cols.index(c)])
            tv = float(vals[i])
            if tv == 0 and fv == 0:
                continue
            se = K.se("entries", key)
            if se is False:
                se = K.extra_se({r: 1.0}, c)
            rows.append({"row": r, "col": c, "window": w, "true": tv, "found": fv, "se": se, "z": _z(fv, tv, se)})
            e_cols = np.array([rws.get(r, 0.0) if (cc == c and ww == w) else 0.0 for rws, cc, ww, _ in ext])
            row_ = np.concatenate([D[i], e_cols])
            if np.any(row_):
                dev.append(fv - tv)
                Dr.append(row_)
        joint = _joint(np.array(dev), np.array(Dr), C_ext if C_ext is not None else K._bound()[0]) if dev else None
    bad = [r for r in rows if r["z"] is not None and abs(r["z"]) > Z]
    return {"rows": rows, "joint": joint, "ok": not bad and (joint is None or joint["p"] >= ALPHA),
            "outside": [f"d{r['row']}/d{r['col']} (window {r['window']}): z {r['z']:.1f}" for r in bad]}


# ---- the likelihood ----

def _found_system(cell: Cell, flows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | str:
    """The found model on the Kalman model's state (every true stock; a stock the found model does not
    touch stays put), in its own units: (A per configuration, configuration per step, u per step, the inputs'
    part per step), or why not."""
    m = cell.m
    n = len(m.ids)
    for f in flows:
        for end in (f.get("from"), f.get("to")):
            if end and end not in cell.measured:
                return f"the found model has a stock of its own ({end}): not covered"
        if f.get("effects") or f.get("via") or f.get("delay") or f.get("whole"):
            return "the found model has effects, a hidden path or a non-linear flow: not covered"
    cols = m.cols
    cache: dict[bytes, int] = {}
    A_list, cfg = [], np.zeros(len(m.t), dtype=np.int64)
    u = np.zeros((len(m.t), n))
    vin = np.zeros((len(m.t), n))
    for k, tt in enumerate(m.t):
        sys_ = linear_system(flows, cols, (tt, tt))
        if sys_ is None:
            return "the found model is not linear in the measured stocks and inputs: not covered"
        B, uu = sys_
        Bs, Bi = B[:n, :n], B[:n, n:]
        A = np.eye(n) + Bs
        key = A.tobytes()
        if key not in cache:
            cache[key] = len(A_list)
            A_list.append(A)
        cfg[k] = cache[key]
        u[k] = uu[:n]
        if Bi.size:
            vin[k] = Bi @ m.U[:, k]
    return np.array(A_list), cfg, u, vin


def _in_units(cell: Cell, sys_, Dv: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The found system followed in reported units x' = Dv x (a biased stock's bias), as SSM.system follows
    the truth: (A per configuration, configuration per step, d per step)."""
    A_list, cfg, u, vin = sys_
    A = Dv[None, :, None] * A_list / Dv[None, None, :]
    d = np.einsum("kij,kj->ki", A[cfg], cell.m.inj * Dv) + (u + vin) * Dv
    return A, cfg, d


def _found_ll(cell: Cell, sys_) -> tuple[float, np.ndarray, np.ndarray, dict]:
    """The found model's log-likelihood with the variant's bias free (the truth's refit frees it too): a
    found model in the reported units (bias 1) and one that took the bias out (bias the truth's) are both
    judged at their best bias. Returns (ll, errors, covariances, {stock: bias})."""
    m = cell.m
    n = len(m.ids)
    D = np.ones(n)
    if not m.bias:
        return (*_loglik(cell, *_in_units(cell, sys_, D)), {})
    from scipy.optimize import minimize
    where = [m.idx[s] for s in m.bias]

    def nll(z):
        Dv = D.copy()
        Dv[where] = np.exp(np.clip(z, -3.0, 3.0))
        ll = _loglik(cell, *_in_units(cell, sys_, Dv))[0]
        return -ll if math.isfinite(ll) else 1e300

    best = None
    for z0 in (np.zeros(len(where)), np.log(np.maximum(1e-6, m.D0[where]))):
        r = minimize(nll, z0, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 400})
        if best is None or r.fun < best.fun:
            best = r
    Dv = D.copy()
    Dv[where] = np.exp(np.clip(best.x, -3.0, 3.0))
    ll, E, S = _loglik(cell, *_in_units(cell, sys_, Dv))
    return ll, E, S, {s: float(Dv[i]) for s, i in zip(m.bias, where)}


def _loglik(cell: Cell, A_cfg, cfg, d) -> tuple[float, np.ndarray, np.ndarray]:
    """log-likelihood of the reported data (the Kalman filter's prediction errors), and the errors and their covariances."""
    m = cell.m
    h = np.ones(len(m.measured))
    E, S = noise_kf._kf(A_cfg, cfg, d, m.Q, m.obs_at, m.Y, m.R, m.mask, h, m.span, m.reset, m.meas, m.m0, m.P0, m.aug, True)
    ll = 0.0
    for i in range(len(E)):
        keep = m.mask[i]
        if not keep.any():
            continue
        e, Si = E[i][keep], S[i][np.ix_(keep, keep)]
        _, ld = np.linalg.slogdet(Si)
        ll -= 0.5 * (float(e @ np.linalg.solve(Si, e)) + ld + keep.sum() * math.log(2 * math.pi))
    return ll, E, S


def _truth_ll(cell: Cell, theta: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    A, d, _ = cell.m.system(theta)
    return _loglik(cell, A, cell.m.cfg, d)


def _where(cell: Cell, Ef, Sf, Et, St) -> list[dict]:
    """Per measured stock: its share of the likelihood loss, the found model's standardized one-step errors'
    mean and lag-1 autocorrelation, and the reader its errors follow most."""
    m = cell.m
    first = int(np.argmax(m.mask.any(axis=1))) + 1                      # past the diffuse start
    out = []
    obs_rows = np.flatnonzero(m.obs_at >= 0)
    at_step = {int(m.obs_at[k]): k for k in obs_rows}
    regs = {ONE: None}
    for j, s in enumerate(m.measured):
        regs[s] = j
    for r, s in enumerate(m.measured):
        idx = [i for i in range(first, len(Ef)) if m.mask[i, r] and i - 1 >= 0 and m.mask[i - 1].all()]
        if len(idx) < 5:
            continue
        zf = np.array([Ef[i, r] / math.sqrt(Sf[i, r, r]) for i in idx])
        zt = np.array([Et[i, r] / math.sqrt(St[i, r, r]) for i in idx])
        loss = 0.5 * float(np.sum(zf ** 2 - zt ** 2))
        mean_z = float(np.mean(zf) * math.sqrt(len(zf)))                 # in SEs of the mean
        ac1 = float(np.corrcoef(zf[:-1], zf[1:])[0, 1]) if len(zf) > 3 and np.std(zf) > 0 else 0.0
        # the reader the found model's errors follow: the measured levels at the previous point, the inputs during the step
        best, best_t = None, 0.0
        cand = {ONE: np.ones(len(idx))}
        for j, x in enumerate(m.measured):
            cand[x] = np.array([m.Y[i - 1, j] for i in idx])
        for q, name in enumerate(m.inputs):
            cand[name] = np.array([m.U[q, at_step[i]] for i in idx])
        for name, x in cand.items():
            if name != ONE:
                x = x - x.mean()
                if not np.any(x):
                    continue
                x = x / np.linalg.norm(x)
                tstat = float(abs(x @ (zf - zf.mean())) / max(np.std(zf), 1e-12))
            else:
                tstat = abs(mean_z)
            if tstat > best_t:
                best, best_t = name, tstat
        kinds = []
        if abs(mean_z) > Z:
            kinds.append("level offset: a constant or an outside inflow wrong or missing")
        if ac1 > 2 / math.sqrt(len(zf)) and ac1 > 0.1:
            kinds.append("slow error: a rate or time constant wrong (the errors persist from step to step)")
        if best is not None and best != ONE and best_t > Z:
            kinds.append(f"the errors follow {best}: the term reading {best} in {s}'s equation is wrong or missing")
        out.append({"stock": s, "loss": loss, "mean_z": mean_z, "lag1": ac1, "follows": best, "follows_t": best_t, "kinds": kinds})
    out.sort(key=lambda x: -x["loss"])
    return out


def likelihood_check(cell: Cell, found) -> dict | None:
    """The found model against the truth's refit on the reported data (see the module docstring). None
    when the truth is not covered or the data are noise-free; {"covered": False, "why"} when the found model
    is not."""
    if not cell.covered or cell.noise_free:
        return None
    flows = _flows(found)
    sys_ = _found_system(cell, flows)
    if isinstance(sys_, str):
        return {"check": "likelihood", "covered": False, "why": sys_}
    ll_f, Ef, Sf, bias = _found_ll(cell, sys_)
    ll_r, Er, Sr = _truth_ll(cell, cell.refit())
    ll_0, E0, S0 = _truth_ll(cell, cell.m.theta0)
    refit_failed = ll_0 > ll_r
    if refit_failed:                    # the true numbers are a point of the true structure: the best it does is at least that
        ll_r, Er, Sr = ll_0, E0, S0
    _, null = cell.kalman()._bound()
    P = cell.m.P
    df = max(1, P - (null.shape[1] if null.size else 0))
    n_true, n_found = cell.truth_numbers(), found_numbers(flows, {int(e["start"]) for e in cell.data.get("eras") or []})
    extra = n_found - n_true
    LR = 2.0 * (ll_r - ll_f)
    LR0 = 2.0 * (ll_0 - ll_f)
    LR_truth = 2.0 * (ll_r - ll_0)
    crit = float(chi2.ppf(1 - ALPHA, df))
    crit_extra = float(chi2.ppf(1 - ALPHA, max(1, extra)))
    misfit = LR_truth > crit            # the noise model rejects the truth itself on this run (a floor that binds, two-way
                                        # counting noise, non-Gaussian readings): judged against the true numbers as well
    rejected = LR > crit and (not misfit or LR0 > crit)
    if rejected:
        verdict = "the data reject the found model"
    elif LR > crit:
        verdict = ("the data cannot tell it from the truth at its true numbers (the Kalman noise model is approximate on this run: "
                   "it rejects the truth itself against its refit)")
    elif -LR > crit_extra:
        verdict = "the found model fits better than the truth can: it fits the run's noise with its extra numbers, or the truth's refit failed"
    else:
        verdict = "the data cannot tell them apart"
    out = {"check": "likelihood", "covered": True, "ll_found": ll_f, "ll_truth_refit": ll_r, "ll_truth": ll_0,
           "LR": LR, "LR_truth": LR_truth, "LR_vs_true_numbers": LR0, "df": df, "critical": crit, "p": float(chi2.sf(max(LR, 0.0), df)),
           "numbers": {"truth": n_true, "truth_identifiable": df, "found": n_found, "extra": extra}, "alpha": ALPHA,
           "verdict": verdict, "rejected": rejected, "noise_model_misfit": misfit, "refit_failed": refit_failed}
    if bias:
        out["bias"] = bias
    if rejected or -LR > crit_extra:
        out["where"] = _where(cell, Ef, Sf, Er, Sr)
    return out


def check(case: dict, variant_name: str, found, data: dict | None = None, cell: Cell | None = None) -> dict:
    """Both checks on one found model: {covered, why?, bound, likelihood}."""
    cell = cell or Cell(case, variant_name, data)
    if not cell.covered:
        return {"covered": False, "why": cell.why, "bound": None, "likelihood": None}
    return {"covered": True, "bound": bound_check(cell, found), "likelihood": likelihood_check(cell, found)}
