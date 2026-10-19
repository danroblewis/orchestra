"""Long-horizon behaviour: the true and the found model run free from the run's start, far into the future.

skill@H (sdlab/skill.py) re-anchors both models on the true levels at ~150 moments and runs them H
steps: it grades short and medium-horizon dynamics. Here nothing is re-anchored. Both models start
from the run's first levels (a found model's own unmeasured stocks from 0, as its observer would
start them) and run, fed the truth's outside inflows exactly as skill@H feeds them (the truth's
schedule replaces the found model's constant outside inflow into every stock the truth feeds from
outside), out to 100,000 steps and beyond.

**Beyond the recorded run** the truth's schedule repeats (its `every`), and a found model's own
time-varying rates (byTime segments: announced eras; outside inflow pieces it keeps) repeat its last
period of the run; without a schedule, a found rate's last piece of at least 10 steps holds (a one-step
piece at the run's very end is a fitting end effect, which held for ever would decide the equilibrium).

**Constant time far ahead.** Stepping is the reference, made cheap by noticing when the future is
known: after the run, both models are periodic in time (period P of the schedule, or none), so once
the levels over one chunk of steps (a multiple of P, >= 64 steps) equal the previous chunk's, they
repeat forever (settled), and any later step is read off that chunk. If instead they change by the
same amount every chunk (a stock that only accumulates, e.g. a final stock), and no flow reads,
drains or uses a growing stock, they keep doing so exactly (drift), and any later step is the chunk
plus k times the drift. A model that does neither within SIM_BUDGET steps is jumped ahead with its
linear part (jump.py: the period map raised to a power by squaring) when it is affine and its last
chunk agrees with that jump (no floor binding); else it is simulated to the end (a few seconds at
most). A run that passes 1e12 x the truth's scale stops there (runaway).

**Metrics** (normalised per measured stock by the truth's scale: its range over the recorded run, or
its largest level in the window graded if that is larger; rms over stocks):
- `err`: at 1k, 10k and 100k steps, and at 10 and 100 x the truth's slowest time constant, the rms
  of (found - true) / scale over a window of one chunk ending there;
- `eq_err`: the settled behaviour: the mean level over the settled chunk (and the drift per step of
  a stock that only accumulates, relative to the truth's), found vs true; None when either never
  settles;
- `tau_true`, `tau_found`, `tau_err` = |tau_found / tau_true - 1|: the slowest time constant
  (steps), from the linear part's eigenvalues for an affine model, else from the Jacobian of the
  chunk map at the settled levels (finite differences);
- `rho_true`, `rho_found`: spectral radius per step; `unstable`: the found model's is above 1, enough
  to grow 2x within the graded horizon (rho^100,000 > 2), where the truth's is not;
- `flag`: "runaway" (grows without bound, or 100x the truth's scale where the truth stays put),
  "dies" (a stock goes to ~0 where the truth stays above 1% of its scale), "unstable", or None;
  `hard_fail`: runaway, or unstable (even when it also dies out).
"""

from __future__ import annotations

import math

import numpy as np

from ..discovery.observer import unmeasured
from ..discovery.simulate import Model, _Segments
from ..skill import _renamed, truth_by_time
from .jump import Affine, Jump, is_affine, spectrum

FAR = (1_000, 10_000, 100_000)
TAU_X = (10, 100)
CHUNK_MIN = 64
SIM_BUDGET = 20_000            # steps stepped before an unsettled affine model is jumped ahead
T_MAX = 100_000 * 10           # never grade beyond this (100 tau of a very slow truth)
RUNAWAY = 1e12
TOL = 1e-9


# ---- the models, as they run past the recorded run ----

def period(truth_model: dict) -> int | None:
    every = int(((truth_model.get("schedule") or {}).get("every")) or 0)
    return every or None


def _values(f: dict, key: str) -> tuple[list, callable]:
    segs = f[key]
    vals = [g["rate"] if key == "byTime" else g["value"] for g in segs]
    return vals, _Segments(segs)


HOLD_MIN = 10              # without a period, the last piece at least this long holds past the run


def extend(f: dict, n_end: int, P: int | None, t_end: int) -> dict:
    """The flow with its byTime / inflow segments repeating their last period (n_end - P, n_end]
    up to t_end; without a period (or a run shorter than one), its last piece of at least HOLD_MIN
    steps holds after n_end (a piece of a step or two at the run's very end is an end effect of
    fitting, not a level the model claims for ever)."""
    key = "byTime" if f.get("byTime") else "inflow" if f.get("inflow") else None
    if key is None or t_end <= n_end:
        return f
    if not P or n_end < P:
        segs = f[key]
        lasting = [g for g in segs if min(g["to"], n_end) - g["from"] + 1 >= HOLD_MIN and g["from"] <= n_end]
        if not lasting or lasting[-1] is segs[-1]:
            return f
        head = [{**g, "to": min(g["to"], n_end)} for g in segs if g["from"] <= n_end]
        vk = "rate" if key == "byTime" else "value"
        return {**f, key: head + [{"from": n_end + 1, "to": t_end, vk: lasting[-1][vk]}]}
    vals, segs = _values(f, key)
    win = np.arange(n_end - P + 1, n_end + 1)
    which = segs(win.astype(float))
    runs = []                                    # (from offset, to offset, value index) within the window
    for i, w in enumerate(which):
        if runs and runs[-1][2] == w:
            runs[-1][1] = i
        else:
            runs.append([i, i, int(w)])
    head = [dict(g) for g in f[key] if g["from"] <= n_end]
    for g in head:
        g["to"] = min(g["to"], n_end)
    vk = "rate" if key == "byTime" else "value"
    tiles = [{"from": int(win[a] + k * P), "to": int(win[b] + k * P), vk: vals[w]}
             for k in range(1, (t_end - n_end) // P + 2) for a, b, w in runs]
    return {**f, key: head + tiles}


def truth_flows(truth_model: dict, n_run: int, t_end: int) -> tuple[list[dict], set, int]:
    """The truth's flows with its schedule laid out (byTime) to t_end, the stocks it feeds with a
    constant outside inflow, and the step after which it repeats with period P."""
    P = period(truth_model)
    n0 = max(n_run, 2 * P) if P else n_run
    flows, fed = truth_by_time(truth_model, list(range(1, n0 + 1)))
    return [extend(f, n0, P, t_end) for f in flows], fed, n0


def found_model(found_flows: list[dict], truth: list[dict], fed: set, measured: list[str], ids: list[str], n_run: int,
                P: int | None, t_end: int) -> tuple[list[dict], list[str], list[str]]:
    """The found model as skill@H runs it (the truth's outside inflows replace its constant ones into
    the stocks the truth feeds; its own unmeasured stocks renamed apart), with its time-varying rates
    repeating past the run: (flows, ids, its hidden stocks)."""
    exo = [{**f, "byTime": [{**g, "rate": g["rate"] if (g["rate"] or {}).get("form") == "constant" else {"form": "constant", "value": 0}}
                            for g in f["byTime"]]} for f in truth if not f.get("from") and f.get("to") in fed]
    own = [f for f in found_flows if not (not f.get("from") and f.get("to") in fed and not f.get("driver")
                                          and (f.get("rate") or {}).get("form") == "constant")]
    own = [extend(f, n_run, P, t_end) for f in own]
    hidden = unmeasured(own, measured)
    names = {x: f"found:{x}" for x in hidden}
    return _renamed(own, names) + exo, ids + list(names.values()), hidden


# ---- stepping, with the future read off once it is known ----

class Trajectory:
    """Levels after each step from t1 on: stepped up to t_sim, then read off the last chunk (settled
    or drifting), jumped (affine), or unknown past a runaway."""

    def __init__(self, X: np.ndarray, t1: int, chunk: int, how: str, drift: np.ndarray | None = None, jump: Jump | None = None):
        self.X, self.t1, self.C, self.how, self.drift, self.jump = X, t1, chunk, how, drift, jump
        self.t_sim = t1 + X.shape[1] - 1

    def at(self, ts) -> np.ndarray:
        """Levels after each step in ts (stocks x len(ts)); nan past a runaway."""
        ts = np.asarray(ts, dtype=np.int64)
        out = np.full((self.X.shape[0], len(ts)), np.nan)
        inside = ts <= self.t_sim
        out[:, inside] = self.X[:, ts[inside] - self.t1]
        late = ~inside
        if not late.any():
            return out
        if self.how in ("settled", "drift"):
            k = -(-(ts[late] - self.t_sim) // self.C)               # chunks ahead (ceil)
            base = ts[late] - k * self.C
            out[:, late] = self.X[:, base - self.t1] + (np.outer(self.drift, k) if self.how == "drift" else 0.0)
        elif self.how == "jump":
            for i in np.flatnonzero(late):
                out[:, i] = np.maximum(0.0, self.jump.at(int(ts[i])))
        elif self.how == "runaway":
            out[:, late] = np.inf
        return out

    def last_chunk(self) -> np.ndarray:
        return self.X[:, -self.C:]


def _readers(flows: list[dict]) -> set:
    """Every stock some flow reads (its rate, segments, effects), drains or uses up."""
    out = set()
    for f in flows:
        out.add(f.get("from"))
        for r in [f.get("rate")] + [g.get("rate") for g in f.get("byTime") or []]:
            r = r or {}
            out |= {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
        out |= {e.get("stock") for e in (f.get("effects") or []) + (f.get("uses") or [])}
    return out - {None}


def free_run(flows: list[dict], ids: list[str], x0: np.ndarray, t1: int, t_free: int, P: int | None, t_end: int,
             scale: np.ndarray, injections: list[dict] | None = None) -> Trajectory:
    """Step the model from x0 (levels before step t1) towards t_end, stopping as soon as the rest is
    known (see the module docstring). `scale`: per stock, what counts as large (runaway, tolerances)."""
    model = Model(flows, ids)
    C = (P or 1) * max(1, math.ceil(CHUNK_MIN / (P or 1)))
    index = {s: i for i, s in enumerate(ids)}
    pulses: dict[int, list] = {}
    for j in injections or []:
        if j.get("stock") in index:
            pulses.setdefault(int(j["t"]), []).append((index[j["stock"]], float(j["amount"])))
    t_free = max(t_free, max(pulses, default=0))
    read = {index[s] for s in _readers(flows) if s in index}
    affine = is_affine(flows)
    n_total = t_end - t1 + 1
    X = np.empty((len(ids), min(n_total, 4096)))
    L = np.asarray(x0, dtype=float).reshape(-1, 1).copy()
    tol = TOL * np.maximum(scale, 1.0)
    big = RUNAWAY * np.maximum(scale, 1.0)
    tarr = np.empty(1)
    drift_seen = None
    for i in range(n_total):
        t = t1 + i
        for s, amount in pulses.get(t, ()):
            L[s, 0] = max(0.0, L[s, 0] + amount)
        tarr[0] = t
        L = model.step(L, tarr)
        if i >= X.shape[1]:
            X = np.concatenate([X, np.empty_like(X)], axis=1)
        X[:, i] = L[:, 0]
        if not np.all(np.isfinite(L)) or np.any(np.abs(L[:, 0]) > big):
            return Trajectory(X[:, : i + 1], t1, C, "runaway")
        n = i + 1
        if t < t_free + 2 * C or n % C or n < 2 * C:
            continue
        a, b = X[:, n - C: n], X[:, n - 2 * C: n - C]
        d = a[:, -1] - b[:, -1]
        if np.all(np.abs((a - b) - d[:, None]) <= tol[:, None]):
            moving = np.abs(d) > tol
            if not moving.any():
                return Trajectory(X[:, :n], t1, C, "settled", drift=np.zeros(len(ids)))
            if np.all(d[moving] > 0) and not (set(np.flatnonzero(moving)) & read):
                if drift_seen is not None and np.allclose(drift_seen, d, rtol=1e-9, atol=0):
                    return Trajectory(X[:, :n], t1, C, "drift", drift=np.where(moving, d, 0.0))
                drift_seen = d
                continue
        drift_seen = None
        if affine and n >= SIM_BUDGET and t + C < t_end:
            j = Jump(Affine(flows, ids), X[:, n - C - 1], t - C + 1, t - C, C)
            if np.all(np.abs(j.at(t) - X[:, n - 1]) <= 1e-6 * np.maximum(scale, 1.0)):
                return Trajectory(X[:, :n], t1, C, "jump", jump=j)
    return Trajectory(X[:, :n_total], t1, C, "stepped")


# ---- local dynamics ----

def local_spectrum(flows: list[dict], ids: list[str], x: np.ndarray, t_start: int, steps: int) -> dict:
    """The eigenvalues of the map over `steps` steps from t_start, linearised at x by finite
    differences (one-sided upwards, so a stock at 0 stays valid)."""
    n = len(ids)
    h = 1e-6 * np.maximum(1.0, np.abs(x))
    L = np.repeat(np.asarray(x, dtype=float)[:, None], n + 1, axis=1)
    L[np.arange(n), np.arange(1, n + 1)] += h
    times = np.repeat(np.arange(t_start, t_start + steps, dtype=float)[:, None], n + 1, axis=1)
    out = Model(flows, ids).run(L, times)
    J = (out[:, 1:] - out[:, :1]) / h[None, :]
    if not np.all(np.isfinite(J)):
        return {"rho": math.inf, "unstable": True, "taus": [], "tau": None, "marginal": 0}
    s = spectrum(J, steps)
    s["unstable"] = bool(s["rho"] > 1 + 1e-6)              # finite differences are not exact
    return s


def dynamics(flows: list[dict], ids: list[str], traj: Trajectory, x0: np.ndarray, t1: int, t_free: int, P: int | None) -> dict:
    """The model's slowest time constant and spectral radius: of its linear part when it is affine
    (exact, global), else linearised over one chunk at its last stepped levels."""
    if is_affine(flows):
        j = Jump(Affine(flows, ids), x0, t1, t_free, P or 1)
        s = j.spectrum()
        s["how"] = "linear"
        xs = j.fixed_point()
        s["fixed_point"] = xs.tolist() if xs is not None else None
        return s
    end = traj.t_sim
    x = np.nan_to_num(traj.X[:, -1], nan=0.0, posinf=1e12)
    s = local_spectrum(flows, ids, x, end + 1, traj.C)
    s["how"] = "local"
    return s


# ---- grading ----

def _rms(found: np.ndarray, true: np.ndarray, scale: np.ndarray) -> float:
    sc = np.maximum(scale[:, None], np.abs(true).max(axis=1, keepdims=True))
    sc = np.where(sc > 0, sc, 1.0)
    e = (found - true) / sc
    if not np.all(np.isfinite(e)):
        return math.inf
    return float(np.sqrt(np.mean(e ** 2)))


class Setup:
    """The truth's side of a long run on one case variant (shared by every found model graded on it)."""

    def __init__(self, truth_model: dict, data: dict, t_end: int = FAR[-1]):
        self.truth_model, self.data = truth_model, data
        t = [int(x) for x in data["t"]]
        self.t0, self.n_run = t[0], t[-1]
        all_levels = data.get("all_levels") or data["levels"]
        self.ids = list(all_levels)
        self.measured = list(data["levels"])
        self.m = [self.ids.index(k) for k in self.measured]
        self.P = period(truth_model)
        A = np.nan_to_num(np.array([np.asarray(all_levels[i], dtype=float) for i in self.ids]))
        self.recorded = A
        rng = A.max(axis=1) - A.min(axis=1)
        self.scale = np.where(rng > 0, rng, np.maximum(np.abs(A).max(axis=1), 1.0))
        self.x0 = A[:, 0]
        self.t1 = self.t0 + 1
        self.injections = data.get("injections")
        # first the truth to 100k, to find its slowest time constant; then far enough for 100 tau
        self.t_end = t_end
        self.flows, self.fed, n0 = truth_flows(truth_model, self.n_run, t_end)
        self.t_free = n0
        self.traj = free_run(self.flows, self.ids, self.x0, self.t1, self.t_free, self.P, t_end, self.scale, self.injections)
        self.dyn = dynamics(self.flows, self.ids, self.traj, self.x0, self.t1, self.t_free, self.P)
        tau = self.dyn.get("tau")
        self.points = {f"{n // 1000}k": n for n in FAR}
        if tau:
            for x in TAU_X:
                self.points[f"{x}tau"] = int(min(T_MAX, max(self.t1 + 1, round(x * tau))))
        far = max(self.points.values())
        if far > t_end:
            self.t_end = far
            self.flows, self.fed, _ = truth_flows(truth_model, self.n_run, far)
            self.traj = free_run(self.flows, self.ids, self.x0, self.t1, self.t_free, self.P, far, self.scale, self.injections)

    def found(self, found_flows: list[dict]) -> tuple[Trajectory, list[dict], list[str]]:
        flows, ids, hidden = found_model(found_flows, self.flows, self.fed, self.measured, self.measured, self.n_run, self.P, self.t_end)
        x0 = np.concatenate([self.x0[self.m], np.zeros(len(hidden))])
        scale = np.concatenate([self.scale[self.m], np.ones(len(hidden)) * float(self.scale[self.m].max(initial=1.0))])
        traj = free_run(flows, ids, x0, self.t1, max(self.t_free, self.n_run), self.P, self.t_end, scale, self.injections)
        return traj, flows, ids

    def window(self, T: int) -> np.ndarray:
        return np.arange(max(self.t1, T - self.traj.C + 1), T + 1)


def grade(setup: Setup, found_flows: list[dict]) -> dict:
    """The long-run metrics of one found model (see the module docstring); JSON-safe."""
    s = setup
    ftraj, fflows, fids = s.found(found_flows)
    nm = len(s.measured)
    err = {}
    for name, T in s.points.items():
        w = s.window(T)
        err[name] = _finite(_rms(ftraj.at(w)[:nm], s.traj.at(w)[s.m], s.scale[s.m]))
    fdyn = dynamics(fflows, fids, ftraj, np.concatenate([s.x0[s.m], np.zeros(len(fids) - nm)]), s.t1, max(s.t_free, s.n_run), s.P)
    tau_t, tau_f = s.dyn.get("tau"), fdyn.get("tau")
    eq = None
    if s.traj.how in ("settled", "drift") and ftraj.how in ("settled", "drift"):
        tc, fc = s.traj.last_chunk()[s.m], ftraj.last_chunk()[:nm]
        if tc.shape == fc.shape:
            td, fd = s.traj.drift[s.m], ftraj.drift[:nm]
            parts = []
            for i in range(nm):
                if fd[i] and not td[i]:
                    parts.append(math.inf)                  # grows where the truth settles: no equilibrium
                elif td[i]:
                    parts.append((fd[i] - td[i]) / abs(td[i]))
                else:
                    parts.append((fc[i].mean() - tc[i].mean()) / max(s.scale[s.m][i], abs(tc[i].mean()), 1e-12))
            eq = float(np.sqrt(np.mean(np.square(parts))))
    # divergence, judged on the farthest window
    T = max(s.points.values())
    w = s.window(T)
    fw, tw = ftraj.at(w)[:nm], s.traj.at(w)[s.m]
    sc = np.maximum(s.scale[s.m], np.abs(tw).max(axis=1))
    flag = None
    if ftraj.how == "runaway" or not np.all(np.isfinite(fw)) or np.any(np.abs(fw).max(axis=1) > 100 * sc):
        flag = "runaway"
    elif np.any((np.abs(fw).max(axis=1) < 1e-6 * sc) & (np.abs(tw).mean(axis=1) > 1e-2 * sc)):
        flag = "dies"
    # unstable: grows at least 2x within the graded horizon (a mode at 1 + 1e-7, a fitting rounding,
    # doubles only after millions of steps), where the truth does not
    grows = lambda d: bool(d.get("unstable")) and (d.get("rho") or 0) ** max(s.points.values()) > 2  # noqa: E731
    unstable = grows(fdyn) and not grows(s.dyn)
    if flag is None and unstable:
        flag = "unstable"
    return {"err": err, "far": err.get("100k"), "eq_err": _finite(eq), "tau_true": tau_t, "tau_found": tau_f,
            "tau_err": _finite(abs(tau_f / tau_t - 1)) if tau_t and tau_f else None,
            "rho_true": _finite(s.dyn["rho"]), "rho_found": _finite(fdyn["rho"]), "unstable": unstable,
            "flag": flag, "hard_fail": flag == "runaway" or unstable,
            "how": {"true": s.traj.how, "found": ftraj.how, "true_dyn": s.dyn["how"], "found_dyn": fdyn["how"]},
            "settled_at": {"true": s.traj.t_sim, "found": ftraj.t_sim}, "points": s.points}


def _finite(x):
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None
