"""The push test: the truth and a found model pushed the same way, their responses compared.

Evidence beside the pass (score.py is not changed and nothing here changes a status). skill@H and the
long run (longrun.py) compare a found model with the truth on the inputs the case happened to have; the
push test asks the interventional question (docs/research/injection-response-judge.md): when the system
is pushed, does the found model move the way the truth moves? A model that only fits the recorded run
(a reversed flow, a link that stands in for a shared inflow, a wrong coefficient on an input balanced by
a wrong drain) answers differently. This is scoring, so it reads the truth.

**The environment, frozen.** Both models run in the environment at the run's last step, held still: the
truth's schedule as it stands then (skill.truth_flows_at), every measured input held at its mean over the
run, the truth's exogenous constant inflows fed to the found model in place of its own (skill.own_flows,
as skill@H feeds them), and a found model's time-varying rates (byTime, inflow pieces) frozen at the
piece that holds then.

**The start.** The truth is started from its recorded levels at the run's end (every stock, hidden ones
too) and run in the frozen environment until it settles (at most SETTLE steps, 20 x its slowest time
constant); both models start from that state. A found model's own unmeasured stocks settle with its
measured stocks held at that state. A truth that does not settle (a counter that only accumulates, an
oscillation) starts from where it got to; `settled` says which.

**The battery** (the same for every case, sized from the case):
- an impulse into each measured stock (IMPULSE x the stock's recorded range, added before the first step,
  as an injection is);
- on each measured input series and on the outside inflow into each measured stock the truth feeds from
  outside: an impulse (one step), a step, and a sine u = a (1 + sin(2 pi h / P)) at the periods
  PERIOD_X x 2 pi tau (tau: the truth's slowest time constant at the start; at least 4 steps), with
  a = INPUT_REL x the input's mean (the inflow's mean amount per step).
Every response is the pushed run minus the same model's unpushed run from the same state, per unit
pushed, so a found model's own drift (a different equilibrium) cancels; for a model that is not linear
(floors, MIN, effects) the response depends on the push's size, and these sizes are the ones measured.

**Compared, per push and measured stock B** (hidden stocks are not compared):
- impulse and step: the response's peak (signed, per unit), time to peak, settling time (last step
  more than 5% of the peak from its final value), area (impulse) or final value (step: the steady
  gain), and `err` = |found - true| / |true| over the horizon (2-norms of the response curves; |true|
  floored at FOOT x the push's largest true peak over the stocks, per step), so a short transient is
  not averaged away by the quiet steps after it;
- the causal footprint: whether B responds at all (its peak at least FOOT x that largest peak) and with
  which sign;
- sine: gain (amplitude of B's sine part per unit of the push's) and phase (degrees, negative = lags),
  fitted over the last two periods after the transient (with a constant and a linear trend, so a
  counter's growth does not leak in); `err` = |gain_f - gain_t| / the truth's gain, floored as above.
A comparison **agrees** when the footprint and sign match and err <= TOL_SHAPE (TOL_GAIN for gain, and
the phase within TOL_PHASE degrees). With a reference (`reference=K`: the truth's own structure refit,
strict.refit, on the run discovery saw and on K - 1 more runs of the same variant, strict's seeds), each
tolerance widens to Z x the refits' rms error on the same comparison: what the data allow the truth's
own structure, so a noisy variant's limit is not blamed on a strategy. One refit is a sample of one;
strict.py uses 1 + 6.

**Returned**: per push, per stock, the numbers; `agree`: the fraction of comparisons that agree (a
confidence score, 1 = every push answered as the truth); `agree_fixed`: the same at the fixed
tolerances, and `data_limited`: how many comparisons the reference widened (where even the truth's own
structure, refit, misses the fixed tolerance: there an "agree" says little); `footprint`: missing / spurious / wrong-sign
responses; `diagnosis`: short plain sentences on the worst disagreements and what kind of wrong each
points to (a missing or spurious path, a path too strong or too weak, a wrong time constant, a wrong
steady-state gain); `not_covered`: what the test could not push or compare.

**Engines.** A truth that uses queue item 2d's features (expressions, MIN, switches, auxiliaries,
two-way flows, delays: sdtruth.uses_2d) runs on the engine itself (sim._quiet, noise none), one push at
a time and a shorter horizon (ENGINE_H); every other truth, and every found model, on
simulate.Model (sim.found_model for a found model that says it is two-way or signed), all pushes at once
as columns. The engine rounds levels to 4 decimals; pushes are sized so this is far below FOOT.

**Not covered**: real-data and physics cases (no truth model to push); outside inflows into hidden
stocks (no found counterpart); a found flow whose rate the engine alone evaluates (expressions).

Run it: `uv run python -m sdlab.ladder.pushes RESULT_ID [...] [--reference K] [--json]`.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys

import numpy as np

from ..discovery.observer import unmeasured
from ..discovery.simulate import Model, _Segments
from ..sdtruth import uses_2d
from ..skill import exogenous, own_flows, truth_flows_at
from .jump import spectrum

IMPULSE = 0.25          # a stock impulse, x the stock's recorded range
INPUT_REL = 0.2         # an input or inflow push, x its mean
PERIOD_X = (0.25, 1.0, 4.0)   # sine periods, x 2 pi tau
P_MIN = 4               # shortest period (steps)
H_MIN, H_MAX = 30, 4000  # impulse and step horizon: 8 tau within these
TAU_H = 8
SETTLE_X, SETTLE_MAX = 20, 20_000
ENGINE_H = 3000         # an engine truth: every horizon at most this
FOOT = 0.01             # a response below this x the push's largest true response is none
TOL_SHAPE = 0.10
TOL_GAIN = 0.10
TOL_PHASE = 10.0        # degrees
Z = 3.0                 # a reference widens a tolerance to Z x the refits' rms error
SETTLE_FRAC = 0.05
PUSH = "push__"         # the rows that carry an outside inflow push


# ---- the environment, frozen ----

def _freeze(f: dict, t: int) -> dict:
    """A flow with its byTime / inflow pieces replaced by the piece that holds at step t."""
    for key in ("byTime", "inflow"):
        segs = f.get(key)
        if segs:
            k = int(_Segments(segs)(np.array([float(t)]))[0])
            g = {x: v for x, v in f.items() if x not in ("byTime", "inflow")}
            g["rate"] = segs[k]["rate"] if key == "byTime" else {"form": "constant", "value": max(0.0, float(segs[k]["value"]))}
            return g
    return f


def _push_flow(target: str) -> dict:
    return {"id": f"{PUSH}{target}", "from": None, "to": target, "rate": {"form": "proportional", "stock": f"{PUSH}{target}", "k": 1}}


class _ModelRunner:
    """simulate.Model (or sim.found_model's SignedModel) with the inputs and push rows as extra stocks no
    flow touches: their values are set before every step, column by column."""

    def __init__(self, flows: list[dict], ids: list[str], ext: list[str], dt: float = 1.0, ceilings: dict | None = None, found: bool = False):
        from .sim import found_model
        self.ids, self.ext = ids, ext
        all_ids = ids + ext
        self.model = found_model(flows, all_ids, dt=dt, ceilings=ceilings) if found else Model(flows, all_ids, dt=dt, ceilings=ceilings)
        self.S = len(ids)

    def run(self, L0: np.ndarray, U: np.ndarray, clamp: list[int] | None = None) -> np.ndarray:
        """Levels after each of H steps (S x N x H) from L0 (S x N), the extra rows following U (E x N x H)."""
        E, N, H = U.shape
        L = np.vstack([np.asarray(L0, float), np.zeros((E, N))])
        out = np.empty((self.S, N, H))
        tarr = np.ones(N)
        fixed = L[clamp].copy() if clamp else None
        for h in range(H):
            L[self.S:] = U[:, :, h]
            if clamp:
                L[clamp] = fixed
            L = self.model.step(L, tarr)
            out[:, :, h] = L[: self.S]
        return out


class _EngineRunner:
    """The engine (sdtruth, noise none) on a frozen model (the truth, or a found model with a flow only the
    engine evaluates), one column at a time."""

    def __init__(self, tm: dict, flows: list[dict], ext: list[str]):
        self.tm = {k: v for k, v in copy.deepcopy(tm).items() if k not in ("schedule", "injections")}
        self.tm["flows"] = [{**f, "id": f.get("id") or f"flow{i}"} for i, f in enumerate(flows)]
        self.tm["noise"] = {}
        self.ids = [s["id"] for s in tm["stocks"]]
        self.ext, self.S = ext, len(self.ids)

    def run(self, L0: np.ndarray, U: np.ndarray, clamp=None) -> np.ndarray:
        from .sim import _quiet
        E, N, H = U.shape
        out = np.empty((self.S, N, H))
        for n in range(N):
            m = dict(self.tm)
            m["inputs"] = {name: {"values": U[e, n].tolist()} for e, name in enumerate(self.ext)}
            run = _quiet(m).run(steps=H, start={s: float(L0[i, n]) for i, s in enumerate(self.ids)}, t0=1)
            for i, s in enumerate(self.ids):
                out[i, n] = run["levels"][s]
        return out


def _tau(runner, x: np.ndarray, u: np.ndarray, rows: list[int]) -> dict:
    """The slowest time constant at x (one step, finite differences upwards, inputs held at u), over
    `rows` (the stocks a model moves)."""
    n = len(rows)
    if not n:
        return {"tau": None, "rho": 0.0, "marginal": 0}
    h = 1e-4 * np.maximum(1.0, np.abs(x[rows]))
    L = np.repeat(x[:, None], n + 1, axis=1)
    L[rows, np.arange(1, n + 1)] += h
    U = np.repeat(u[:, None, None], n + 1, axis=1)
    out = runner.run(L, U)[:, :, 0]
    J = (out[rows][:, 1:] - out[rows][:, :1]) / h[None, :]
    if not np.all(np.isfinite(J)):
        return {"tau": None, "rho": math.inf, "marginal": 0}
    s = spectrum(J, 1)
    return {"tau": s["tau"], "rho": s["rho"], "marginal": s["marginal"]}


def _moved(flows: list[dict], ids: list[str]) -> list[int]:
    touched = {x for f in flows for x in (f.get("from"), f.get("to")) if x} | {u.get("stock") for f in flows for u in f.get("uses") or []}
    return [i for i, s in enumerate(ids) if s in touched]


# ---- the battery ----

class Bench:
    """The truth's side of the push test on one case variant: the frozen environment, the start, the
    battery and the truth's responses (shared by every found model graded on it)."""

    def __init__(self, truth_model: dict, data: dict):
        tm = truth_model
        self.tm, self.data = tm, data
        t = [int(x) for x in data["t"]]
        self.t_s = t[-1]
        all_levels = data.get("all_levels") or data["levels"]
        self.ids = [s["id"] for s in tm["stocks"]]
        self.measured = [s for s in data["levels"] if s in self.ids]
        A = np.nan_to_num(np.array([np.asarray(all_levels.get(s, [0.0] * len(t)), float) for s in self.ids]))
        rng = A.max(axis=1) - A.min(axis=1)
        self.scale = dict(zip(self.ids, np.where(rng > 0, rng, np.maximum(np.abs(A).max(axis=1), 1.0)).tolist()))
        self.not_covered: list[str] = []
        # frozen truth
        self.flows = [f for f in truth_flows_at(tm, self.t_s)]
        self.fed = {f["to"] for f in self.flows if exogenous(f)}
        self.inputs = list((data.get("inputs") or {}).keys())
        self.input_mean = {k: float(np.mean(np.asarray(data["inputs"][k], float))) for k in self.inputs}
        outside = {}
        for f in self.flows:
            if not f.get("from") and f.get("to"):
                outside.setdefault(f["to"], []).append(f["id"])
        self.inflow_targets = [s for s in self.measured if s in outside]
        for s in outside:
            if s not in self.measured:
                self.not_covered.append(f"the outside inflow into {s} (hidden: no found counterpart)")
        counters = data.get("counters") or {}
        self.inflow_mean = {}
        for s in self.inflow_targets:
            amt = sum(float(np.mean(counters[fid])) for fid in outside[s] if counters.get(fid))
            self.inflow_mean[s] = amt if amt > 0 else 0.25 * self.scale[s]
        self.ext = self.inputs + [f"{PUSH}{s}" for s in self.inflow_targets]
        self.engine = uses_2d(tm)
        tflows = self.flows + [_push_flow(s) for s in self.inflow_targets]
        ceilings = {s["id"]: s["max"] for s in tm["stocks"] if s.get("max") is not None}
        self.ceilings = ceilings
        self.dt = float(tm.get("dt") or 1)
        self.runner = _EngineRunner(tm, tflows, self.ext) if self.engine else _ModelRunner(tflows, self.ids, self.ext, self.dt, ceilings)
        self.u0 = np.array([self.input_mean[k] for k in self.inputs] + [0.0] * len(self.inflow_targets))
        # start: the recorded end, settled
        x = A[:, -1].copy()
        rows = _moved(self.flows, self.ids)
        tau0 = _tau(self.runner, x, self.u0, rows)["tau"] or 10.0
        cap = ENGINE_H if self.engine else SETTLE_MAX
        n_settle = int(min(cap, max(200, SETTLE_X * tau0)))
        X = self.runner.run(x[:, None], np.repeat(self.u0[:, None, None], n_settle, axis=2))[:, 0]
        self.x = X[:, -1]
        w = min(64, n_settle // 2)
        sc = np.array([self.scale[s] for s in self.ids])
        self.settled = bool(np.all(np.abs(X[:, -1] - X[:, -w]) <= 1e-6 * np.maximum(sc, 1.0)))
        dyn = _tau(self.runner, self.x, self.u0, rows)
        self.tau, self.rho = dyn["tau"], dyn["rho"]
        tau = self.tau or tau0
        hmax = ENGINE_H if self.engine else H_MAX
        self.h_imp = int(min(hmax, max(H_MIN, math.ceil(TAU_H * tau))))
        periods = sorted({int(max(P_MIN, round(x * 2 * math.pi * tau))) for x in PERIOD_X})
        warm = int(min(hmax, math.ceil(5 * tau)))
        self.periods = [P for P in periods if warm + 3 * P <= max(hmax, self.h_imp)] or periods[:1]
        self.H = max(self.h_imp, max(warm + 3 * P for P in self.periods))
        if self.engine:
            self.H = min(self.H, ENGINE_H)
            self.periods = [P for P in self.periods if 2 * P + warm <= self.H] or [min(self.periods)]
        self.pushes = self._battery()
        self.U, self.kicks = self._signals()
        self.truth = self._respond(self.runner, self.x, list(range(len(self.ids))))

    # pushes
    def _battery(self) -> list[dict]:
        out = []
        for s in self.measured:
            out.append({"kind": "impulse", "on": "stock", "target": s, "size": IMPULSE * self.scale[s], "name": f"an impulse into {s}"})
        sources = [("input", k, INPUT_REL * max(abs(self.input_mean[k]), 1e-9) if self.input_mean[k] else 1.0) for k in self.inputs]
        sources += [("inflow", s, INPUT_REL * self.inflow_mean[s]) for s in self.inflow_targets]
        for on, target, a in sources:
            label = target if on == "input" else f"the outside inflow into {target}"
            out.append({"kind": "impulse", "on": on, "target": target, "size": a, "name": f"a one-step impulse in {label}"})
            out.append({"kind": "step", "on": on, "target": target, "size": a, "name": f"a step in {label}"})
            for P in self.periods:
                out.append({"kind": "sine", "on": on, "target": target, "size": a, "period": P, "name": f"a sine in {label} (period {P})"})
        return out

    def _signals(self) -> tuple[np.ndarray, list]:
        """The extra rows' values (E x N x H; column 0 unpushed) and the stock kicks [(stock, column, amount)]."""
        N = len(self.pushes) + 1
        U = np.repeat(np.repeat(self.u0[:, None, None], N, axis=1), self.H, axis=2)
        kicks = []
        h = np.arange(self.H)
        for n, p in enumerate(self.pushes, start=1):
            if p["on"] == "stock":
                kicks.append((p["target"], n, p["size"]))
                continue
            row = self.inputs.index(p["target"]) if p["on"] == "input" else len(self.inputs) + self.inflow_targets.index(p["target"])
            a = p["size"]
            if p["kind"] == "impulse":
                U[row, n, 0] += a
            elif p["kind"] == "step":
                U[row, n, :] += a
            else:
                U[row, n, :] += a * (1 + np.sin(2 * math.pi * h / p["period"]))
        return U, kicks

    def _respond(self, runner, x: np.ndarray, rows: list[int]) -> np.ndarray:
        """Responses per unit pushed of the model's stocks `rows` (named as self.measured order is
        decided by the caller): (pushes x stocks x H)."""
        N = len(self.pushes) + 1
        ids = runner.ids
        L0 = np.repeat(np.asarray(x, float)[:, None], N, axis=1)
        for s, n, a in self.kicks:
            i = ids.index(s)
            L0[i, n] = max(0.0, L0[i, n] + a)
        X = runner.run(L0, self.U)
        R = (X[:, 1:, :] - X[:, :1, :]) / np.array([p["size"] for p in self.pushes])[None, :, None]
        return np.transpose(R, (1, 0, 2))[:, rows, :]

    def measured_rows(self) -> list[int]:
        return [self.ids.index(s) for s in self.measured]

    # the found model
    def found(self, found_flows: list[dict], ceilings: dict | None = None) -> tuple[np.ndarray, dict]:
        from ..skill import _renamed
        from .sim import mark_found, signed_stocks
        frozen = [_freeze(f, self.t_s) for f in found_flows]
        own = own_flows(frozen, self.fed)
        exo = [f for f in self.flows if exogenous(f) and f.get("to") in self.fed]
        hidden = unmeasured(own, self.measured)
        engine = any(f.get("whole") for f in mark_found(own, self.tm))   # an expression: only the engine evaluates it
        names = {} if engine else {h: f"found:{h}" for h in hidden}      # (a separate run: renaming only keeps simulate's ids apart)
        flows = _renamed(own, names) + exo + [_push_flow(s) for s in self.inflow_targets]
        ids = self.measured + [names.get(h, h) for h in hidden]
        notes = []
        if engine:
            signed = signed_stocks(own)
            stocks = [{"id": s, **({"signed": True} if s in signed else {}),
                       **({"max": (ceilings or {})[s]} if (ceilings or {}).get(s) is not None else {})} for s in ids]
            runner = _EngineRunner({"stocks": stocks, "seed": 0, "steps": 1, "dt": self.tm.get("dt")}, flows, self.ext)
            notes.append("found model run on the engine (a flow with an expression)")
        else:
            runner = _ModelRunner(flows, ids, self.ext, 1.0, ceilings, found=True)
        m = [self.ids.index(s) for s in self.measured]
        x = np.concatenate([self.x[m], np.zeros(len(hidden))])
        if hidden and engine:
            notes.append("its own hidden stocks start at 0 (not settled: the engine runner holds no stock fixed)")
        elif hidden:                                    # its own hidden stocks settle with the measured held
            n = int(min(SETTLE_MAX, max(200, SETTLE_X * (self.tau or 10.0))))
            X = runner.run(x[:, None], np.repeat(self.u0[:, None, None], n, axis=2), clamp=list(range(len(self.measured))))
            x[len(self.measured):] = X[len(self.measured):, 0, -1]
        dyn = _tau(runner, x, self.u0, _moved(flows, ids))
        R = self._respond(runner, x, list(range(len(self.measured))))
        return R, {"tau": dyn["tau"], "rho": dyn["rho"], "hidden": hidden, "notes": notes}


# ---- the comparison ----

def _shape(r: np.ndarray, kind: str) -> dict:
    k = int(np.argmax(np.abs(r)))
    peak = float(r[k])
    end = float(r[-1])
    far = np.flatnonzero(np.abs(r - end) > SETTLE_FRAC * max(abs(peak), 1e-300))
    out = {"peak": peak, "t_peak": k + 1, "settle": int(far[-1] + 2) if len(far) else 1}
    out["area" if kind == "impulse" else "final"] = float(r.sum()) if kind == "impulse" else end
    return out


def _sine(r: np.ndarray, P: int) -> tuple[float, float]:
    """Gain and phase (degrees) of r's part at period P over its last two periods."""
    n = len(r)
    h = np.arange(n - 2 * P, n, dtype=float)
    w = 2 * math.pi * h / P
    M = np.column_stack([np.sin(w), np.cos(w), np.ones_like(h), h - h.mean()])
    coef, *_ = np.linalg.lstsq(M, r[n - 2 * P:], rcond=None)
    return float(math.hypot(coef[0], coef[1])), float(math.degrees(math.atan2(coef[1], coef[0])))


def _wrap(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def _fin(x, nd: int = 6):
    if x is None:
        return None
    x = float(x)
    return float(f"{x:.{nd}g}") if math.isfinite(x) else None


def _moves(v: float) -> str:
    return "rises" if v > 0 else "falls"


def _reference_errors(reference: list[dict]) -> dict:
    """(push, stock) -> {err, dphase}: the rms over the refits' compare() outputs."""
    acc: dict = {}
    for r in reference:
        for p in r.get("pushes", []):
            for s, v in p["stocks"].items():
                a = acc.setdefault((p["push"], s), {"err": [], "dphase": []})
                a["err"].append(v.get("err") or 0.0)
                a["dphase"].append(v.get("dphase") or 0.0)
    return {k: {x: float(np.sqrt(np.mean(np.square(v[x])))) for x in v} for k, v in acc.items()}


def compare(bench: Bench, found_flows: list[dict], ceilings: dict | None = None, reference: list[dict] | None = None) -> dict:
    """The push test of one found model (see the module docstring); JSON-safe. `reference`: compare()'s
    outputs for the truth's own structure refit on runs of the same variant, whose errors widen the tolerances."""
    b = bench
    Rt = b.truth[:, b.measured_rows(), :]
    Rf, fdyn = b.found(found_flows, ceilings)
    ref = _reference_errors(reference or [])
    pushes, comps, issues = [], [], []
    fixed, limited = [], 0
    footprint = {"missing": [], "spurious": [], "sign": []}
    for i, p in enumerate(b.pushes):
        H = b.h_imp if p["kind"] != "sine" else b.H
        rt, rf = Rt[i, :, :H], Rf[i, :, :H]
        if p["kind"] == "sine":
            gt = [_sine(rt[j], p["period"]) for j in range(len(b.measured))]
            gf = [_sine(rf[j], p["period"]) for j in range(len(b.measured))]
            top = max((g for g, _ in gt), default=0.0)
        else:
            top = float(np.abs(rt).max(initial=0.0))
        floor = FOOT * top if top > 0 else 1e-12
        stocks = {}
        for j, s in enumerate(b.measured):
            r_ref = ref.get((p["name"], s)) or {}
            if p["kind"] == "sine":
                (g_t, ph_t), (g_f, ph_f) = gt[j], gf[j]
                on_t, on_f = g_t >= floor, g_f >= floor
                err = abs(g_f - g_t) / max(g_t, floor)
                dph = abs(_wrap(ph_f - ph_t)) if on_t and on_f else None
                tol = max(TOL_GAIN, Z * (r_ref.get("err") or 0.0))
                tol_ph = max(TOL_PHASE, Z * (r_ref.get("dphase") or 0.0))
                ok = on_t == on_f and err <= tol and (dph is None or dph <= tol_ph)
                fixed.append(on_t == on_f and err <= TOL_GAIN and (dph is None or dph <= TOL_PHASE))
                limited += tol > TOL_GAIN or tol_ph > TOL_PHASE
                row = {"gain_true": _fin(g_t), "gain_found": _fin(g_f), "phase_true": _fin(ph_t, 4) if on_t else None,
                       "phase_found": _fin(ph_f, 4) if on_f else None, "dphase": _fin(dph, 4), "err": _fin(err), "agree": ok,
                       "responds": [bool(on_t), bool(on_f)]}
                sign_t = sign_f = 1
            else:
                st, sf = _shape(rt[j], p["kind"]), _shape(rf[j], p["kind"])
                on_t, on_f = abs(st["peak"]) >= floor, abs(sf["peak"]) >= floor
                sign_t, sign_f = np.sign(st["peak"]), np.sign(sf["peak"])
                err = float(np.linalg.norm(rf[j] - rt[j])) / max(float(np.linalg.norm(rt[j])), floor * math.sqrt(H))
                tol = max(TOL_SHAPE, Z * (r_ref.get("err") or 0.0))
                ok = on_t == on_f and (not on_t or sign_t == sign_f) and err <= tol
                fixed.append(on_t == on_f and (not on_t or sign_t == sign_f) and err <= TOL_SHAPE)
                limited += tol > TOL_SHAPE
                row = {"true": {k: v if isinstance(v, int) else _fin(v) for k, v in st.items()}, "found": {k: v if isinstance(v, int) else _fin(v) for k, v in sf.items()},
                       "err": _fin(err), "agree": ok, "responds": [bool(on_t), bool(on_f)]}
            if r_ref:
                row["tol"] = _fin(tol)
            stocks[s] = row
            comps.append(ok)
            if ok:
                continue
            # what kind of wrong
            if on_t and not on_f:
                footprint["missing"].append([p["name"], s])
                v = row["gain_true"] if p["kind"] == "sine" else row["true"]["peak"]
                issues.append((3, err, f"found model's {s} does not respond to {p['name']}; truth's {s} "
                               + (f"follows it with gain {abs(v):.3g}" if p["kind"] == "sine" else f"{_moves(v)} {abs(v):.3g} per unit (peak at step {row['true']['t_peak']})")
                               + ": a missing path"))
            elif on_f and not on_t:
                footprint["spurious"].append([p["name"], s])
                v = row["gain_found"] if p["kind"] == "sine" else row["found"]["peak"]
                issues.append((3, err, f"found model's {s} " + (f"follows {p['name']} with gain {abs(v):.3g}" if p["kind"] == "sine"
                               else f"{_moves(v)} {abs(v):.3g} per unit after {p['name']}") + f" where the truth's {s} does not move: a path the truth does not have"))
            elif p["kind"] != "sine" and sign_t != sign_f:
                footprint["sign"].append([p["name"], s])
                issues.append((3, err, f"{s} moves the wrong way after {p['name']}: the truth's {_moves(row['true']['peak'])} "
                               f"{abs(row['true']['peak']):.3g} per unit, the found model's {_moves(row['found']['peak'])} {abs(row['found']['peak']):.3g}: a reversed or wrong-signed path"))
            elif p["kind"] == "sine":
                pass                                   # summarised per path below
            else:
                t_, f_ = row["true"], row["found"]
                ratio = abs(f_["peak"]) / max(abs(t_["peak"]), 1e-300)
                what = []
                if abs(ratio - 1) > TOL_SHAPE:
                    path = (f"{s} keeps {'more' if ratio > 1 else 'less'} of what arrives (its own drain is too {'slow' if ratio > 1 else 'fast'})"
                            if p["target"] == s and p["on"] != "input" else
                            f"the path from {p['target']} to {s} is too {'strong' if ratio > 1 else 'weak'}")
                    what.append(f"peaks at {f_['peak']:.3g} per unit vs the truth's {t_['peak']:.3g} ({ratio:.2f}x): {path}")
                if t_["settle"] and abs(f_["settle"] / t_["settle"] - 1) > 0.5 and t_["settle"] > 2:
                    what.append(f"settles in {f_['settle']} steps vs the truth's {t_['settle']}: a time constant on the path is "
                                f"{'too slow' if f_['settle'] > t_['settle'] else 'too fast'}")
                if p["kind"] == "step" and abs(t_["final"]) >= floor and abs(f_["final"] / t_["final"] - 1) > TOL_SHAPE:
                    what.append(f"its steady-state gain is {f_['final']:.3g} vs the truth's {t_['final']:.3g}")
                if not what:
                    what.append(f"its response curve differs from the truth's by {err:.0%}")
                issues.append((2, err, f"{s} after {p['name']}: " + "; ".join(what)))
        pushes.append({"push": p["name"], "kind": p["kind"], "on": p["on"], "target": p["target"], "size": _fin(p["size"]),
                       **({"period": p["period"]} if p["kind"] == "sine" else {}), "stocks": stocks})
    # frequency response per path: where along the periods it goes wrong
    for src in {(p["on"], p["target"]) for p in b.pushes if p["kind"] == "sine"}:
        rows = [(p["period"], q) for p, q in zip(b.pushes, pushes) if p["kind"] == "sine" and (p["on"], p["target"]) == src]
        rows.sort()
        label = src[1] if src[0] == "input" else f"the outside inflow into {src[1]}"
        for s in b.measured:
            bad = [(P, q["stocks"][s]) for P, q in rows if not q["stocks"][s]["agree"] and all(q["stocks"][s]["responds"])]
            if not bad:
                continue
            slow_ok = rows[-1][1]["stocks"][s]["agree"]
            worst = max(bad, key=lambda x: x[1]["err"] or 0)
            P, r = worst
            kind = ("right steady-state gain, wrong dynamics (a time constant or delay) at faster periods" if slow_ok
                    else "wrong steady-state gain (the coefficient or balance on the path)")
            issues.append((2, r["err"] or 0, f"{s} driven by a sine in {label}: gain {r['gain_found']:.3g} vs the truth's {r['gain_true']:.3g}"
                           f" at period {P}" + (f", phase {r['phase_found']:.0f} vs {r['phase_true']:.0f} degrees" if r.get("phase_found") is not None else "")
                           + f": {kind}"))
    issues.sort(key=lambda x: (-x[0], -(x[1] or 0)))
    agree = sum(comps) / len(comps) if comps else None
    out = {"agree": _fin(agree, 4), "n": len(comps), "verdict": None if agree is None else "agrees" if agree == 1 else "differs",
           "agree_fixed": _fin(sum(fixed) / len(fixed), 4) if fixed else None, "data_limited": limited,
           "footprint": footprint, "diagnosis": [m for *_, m in issues[:8]], "issues": len(issues),
           "tau_true": _fin(b.tau), "tau_found": _fin(fdyn["tau"]), "rho_true": _fin(b.rho), "rho_found": _fin(fdyn["rho"]),
           "settled": b.settled, "start_step": b.t_s, "periods": b.periods, "horizon": {"impulse": b.h_imp, "sine": b.H},
           "engine": "sdtruth" if b.engine else "simulate", "not_covered": list(b.not_covered), "notes": fdyn["notes"], "pushes": pushes}
    if fdyn["tau"] and b.tau and abs(fdyn["tau"] / b.tau - 1) > 0.25:
        out["diagnosis"].append(f"the found model's slowest time constant is {fdyn['tau']:.3g} steps vs the truth's {b.tau:.3g}")
    if reference is not None:
        out["reference"] = {"refits": len(reference), "agree": [r.get("agree") for r in reference], "how": sorted({r.get("how") for r in reference})}
    if not issues and agree == 1:
        out["diagnosis"] = ["every push answered as the truth answers" if not limited else
                            f"every push answered within what the data allow the truth's own refits ({limited} of {len(comps)} "
                            f"comparisons widened; {out['agree_fixed']:.0%} agree at the fixed tolerances)"]
        if limited:
            out["verdict"] = "agrees within the data's limits"
    return out


# ---- a stored result ----

def for_result(result_id: int, reference: int = 0) -> dict:
    """The push test of a stored result (its case, variant and found flows from the store)."""
    from . import cases as casemod
    from . import data, store
    r = store.get(result_id, found=True)
    if r is None or not r.get("found"):
        return {"error": f"result {result_id}: no found model"}
    c = casemod.load(r["case"])
    if c.get("real") or c.get("physics") or c.get("particles"):
        return {"error": "no truth model to push (real-data, physics or particle case)"}
    tm = casemod.truth_model(c, r["variant"])
    d = data.load(c, r["variant"])
    bench = Bench(tm, d.get("clean") or d)
    found = r["found"] if isinstance(r["found"], list) else r["found"].get("flows", r["found"])
    ref = None
    if reference:
        from .strict import SEED_BASE, _run, refit
        v = casemod.variant(c, r["variant"])
        ref = []
        for i in range(reference):
            run = d if i == 0 else _run(c, v, tm, int(tm["seed"]) + SEED_BASE + i - 1)
            flows, how = refit(tm, run, v["noise"])
            if flows is not None:
                ref.append({**compare(bench, flows), "how": how})
            if v["noise"] == "none" and not v.get("observe"):
                break                                   # noise-free: the refit is the truth on every run
    out = compare(bench, found, reference=ref)
    out.update({"result": result_id, "case": r["case"], "variant": r["variant"], "strategy": r["strategy"], "status": r["status"]})
    return out


def summary(out: dict) -> str:
    if out.get("error"):
        return f"{out.get('result', '')}: {out['error']}"
    head = (f"{out['result']} {out['case']} {out['variant']} {out['strategy']} ({out['status']}): push test {out['verdict']}, "
            f"{out['agree']:.0%} of {out['n']} comparisons agree; tau true {out['tau_true']}, found {out['tau_found']}")
    fp = out["footprint"]
    if any(fp.values()):
        head += f"; footprint: {len(fp['missing'])} missing, {len(fp['spurious'])} spurious, {len(fp['sign'])} wrong sign"
    if out.get("reference"):
        ra = out["reference"]["agree"]
        head += f"; {out['agree_fixed']:.0%} at the fixed tolerances, {out['data_limited']} comparisons widened by the reference"
        head += (f"; the truth's own refits ({out['reference']['refits']}, {'/'.join(out['reference']['how'])}) agree on "
                 + ", ".join(f"{a:.0%}" for a in ra if a is not None))
    return head + "\n" + "\n".join(f"  - {m}" for m in out["diagnosis"]) + (
        "\n  not covered: " + "; ".join(out["not_covered"]) if out["not_covered"] else "") + (
        "\n  notes: " + "; ".join(out["notes"]) if out.get("notes") else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sdlab.ladder.pushes", description="The push test of stored results.")
    ap.add_argument("ids", nargs="+", type=int)
    ap.add_argument("--reference", type=int, default=0, metavar="K",
                    help="also push the truth's own structure refit on K runs (the one discovery saw, then strict's seeds): their errors widen the tolerances")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for i in a.ids:
        out = for_result(i, reference=a.reference)
        print(json.dumps(out) if a.json else summary(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
