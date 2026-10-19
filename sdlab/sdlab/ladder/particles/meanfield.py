"""Particle runs, and the mean-field SD model of a particle system.

Averaged over many particles, the per-region counts follow the mean-field (master-equation) model:
each region is a stock, each move a proportional flow whose rate is the per-step move probability,
each arrival stream an inflow equal to its input, and a binding A + B -> C a product kappa x A x B
(SD Lab's form: a proportional rate times a linear effect of B, with a co-flow using up one B per C).

  exact tier     the numbers are the rules' own (systems.py `moves`, `reaction`)
  other tiers    the numbers are transition frequencies measured over one very long run of the
                 particles (`measure`): k(i -> j) = moves from i to j / particle-steps spent in i, a
                 switched move's only over the steps it is open, kappa = bindings / sum of A x B,
                 a move seen fewer than MIN_EVENTS times left out

`check` runs the particles many times from the same start with the same drivers (only the motion
differs) and compares their average with the mean-field model run from that start: the z-score of the
gap at every step and region, against the ensemble's standard error.
"""

from __future__ import annotations

import math

import numpy as np

from ...discovery.simulate import Model
from ...skill import truth_by_time
from .engine import OUT, record, streams

MEASURE_STEPS = 20000
MIN_EVENTS = 20
MIN_RATE = 1e-4      # a move rarer than this per particle-step is left out of a measured model
NORMAL = 100.0          # the linear effect's normal level for a product (kappa x A x B = (kappa x NORMAL) x A x (B / NORMAL))
EFFECT_MAX = 1e6        # its cap, never reached


def _sig(x: float, n: int = 4) -> float:
    return float(f"{x:.{n}g}") if x else 0.0


def simulate(system, p: dict, seed: int, steps: int, motion_seed: int | None = None, stats: bool = False) -> dict:
    """One particle run in data.py's format; with stats, also {"stats": O, T, O_open, T_open, react, ab}."""
    r_init, r_drive, r_mot = streams(seed, motion_seed)
    drive = system.drive(p, r_drive, steps)
    sw = system.start(p, r_init)
    ids = system.ids(p)
    n = len(ids)
    ix = {s: i for i, s in enumerate(ids)}
    inject: dict[int, list] = {}
    for j in drive.injections:
        inject.setdefault(int(j["t"]), []).append(j)
    counts = np.zeros((n, steps), dtype=np.int64)
    closed = drive.switches.get("closed")
    if stats:
        O, T = np.zeros(n), np.zeros((n, n + 1))
        Oo, To = np.zeros(n), np.zeros((n, n + 1))
        react, ab = 0.0, 0.0
        rx = system.reaction(p)
        ia, ib = (ix[rx["a"]], ix[rx["b"]]) if rx else (None, None)
    for t in range(1, steps + 1):
        for j in inject.get(t, []):
            k = int(j["amount"])
            sw.add(np.full(k, ix[j["stock"]]), **system.place(p, ix[j["stock"]], k, r_mot))
        if stats:
            c0 = sw.counts(n).astype(float)
        src, dst, ev = system.step(p, sw, t, drive, r_mot)
        if stats:
            moved = src != dst
            pair = np.zeros((n, n + 1))
            np.add.at(pair, (src[moved], np.where(dst[moved] == OUT, n, dst[moved])), 1)
            O += c0
            T += pair
            if closed is None or not closed[t - 1]:
                Oo += c0
                To += pair
            if rx:
                react += ev.get("react", 0)
                ab += c0[ia] * c0[ib]
        counts[:, t - 1] = sw.counts(n)
    out = record(ids, counts, drive, steps)
    if stats:
        out["stats"] = {"O": O.tolist(), "T": T.tolist(), "O_open": Oo.tolist(), "T_open": To.tolist(), "react": react, "ab": ab}
    return out


def start_levels(system, p: dict, seed: int) -> list[int]:
    """The counts at time 0 of a run with this seed."""
    r_init, _, _ = streams(seed)
    return [int(x) for x in system.start(p, r_init).counts(len(system.ids(p)))]


def fid(a: str, b: str | None) -> str:
    return f"{a}_{b}" if b else f"{a}_out"


def model(system, p: dict, stats: dict | None = None, steps: int = MEASURE_STEPS) -> dict:
    """The mean-field model: {flows, schedule?, how, moves: [(from, to, k)], kappa}. With stats (measured over
    `steps`), the moves' numbers and kappa are the measured frequencies; without (exact tier), the rules' own."""
    ids = system.ids(p)
    n = len(ids)
    rx = system.reaction(p)
    shut = {tuple(x) for x in (system.switched(p).get("closed") or [])}
    if stats is None:
        moves = [(a, b, float(q)) for a, b, q in system.moves(p) if q > 0]
        kappa = rx["kappa"] if rx else None
    else:
        O, T = np.asarray(stats["O"]), np.asarray(stats["T"])
        Oo, To = np.asarray(stats["O_open"]), np.asarray(stats["T_open"])
        if rx:
            ia, ib, ic = ids.index(rx["a"]), ids.index(rx["b"]), ids.index(rx["c"])
            T = T.copy()
            T[ia, ic] -= stats["react"]                   # every A -> C is a binding, every bound B leaves: not a leak
            T[ib, n] -= stats["react"]
        moves = []
        for i in range(n):
            for j in range(n + 1):
                b = ids[j] if j < n else None
                if i == j or (rx and i == ia and j == ic):
                    continue
                ev, occ = (To[i, j], Oo[i]) if (ids[i], b) in shut else (T[i, j], O[i])
                if ev >= MIN_EVENTS and occ > 0 and ev / occ >= MIN_RATE:
                    moves.append((ids[i], b, _sig(ev / occ)))
        kappa = _sig(stats["react"] / stats["ab"]) if rx and stats["ab"] > 0 else None
    how = ("exact: the rules' own per-step probabilities" if stats is None else
           f"measured: transition frequencies over {steps:,} steps of one particle run (a move seen fewer than {MIN_EVENTS} times or at under {MIN_RATE:g} a step left out)")
    return assemble(system, p, moves, kappa, how)


def assemble(system, p: dict, moves: list, kappa: float | None, how: str) -> dict:
    """The mean-field model's flows (and schedule) from its moves' numbers and kappa."""
    rx = system.reaction(p)
    flows = [{"id": fid(a, b), "from": a, "to": b, "rate": {"form": "proportional", "stock": a, "k": float(q)}} for a, b, q in moves]
    for name, region, share in system.inflows(p):
        flows.append({"id": f"{name}_{region}", "from": None, "to": region, "rate": {"form": "proportional", "stock": name, "k": float(share)}})
    if rx and kappa:
        flows.append({"id": fid(rx["a"], rx["c"]), "from": rx["a"], "to": rx["c"],
                      "rate": {"form": "proportional", "stock": rx["a"], "k": _sig(kappa * NORMAL, 6)},
                      "effects": [{"stock": rx["b"], "shape": "linear", "normal": NORMAL, "max": EFFECT_MAX}],
                      "uses": [{"stock": rx["b"], "per": 1}]})
    out = {"flows": flows}
    sw = system.switched(p)
    if sw.get("closed"):
        ids_shut = {fid(a, b) for a, b in sw["closed"]}
        byid = {f["id"]: f for f in flows}
        per, frm = int(p["period"]), int(p["shut_from"])
        out["schedule"] = {"every": per, "changes": [
            {"t": 1, "label": "open", "announce": True, "set": {k: dict(byid[k]["rate"]) for k in sorted(ids_shut) if k in byid}},
            {"t": frm, "label": "shut", "announce": True,
             "set": {k: {**byid[k]["rate"], "k": 0.0} for k in sorted(ids_shut) if k in byid}}]}
    out.update(how=how, moves=[[a, b, float(q)] for a, b, q in moves], kappa=kappa)
    return out


def timed(mf: dict, steps: int) -> list[dict]:
    """The model's flows over steps 1..steps with the schedule written out (byTime), as a found model's are."""
    truth = {"flows": mf["flows"], **({"schedule": mf["schedule"]} if mf.get("schedule") else {})}
    return truth_by_time(truth, list(range(1, steps + 1)))[0] if mf.get("schedule") else [dict(f) for f in mf["flows"]]


def measure(system, p: dict, seed: int, steps: int = MEASURE_STEPS) -> dict:
    """The stats of one long particle run (simulate's `stats`)."""
    return simulate(system, p, seed, steps, stats=True)["stats"]


def run_model(mf: dict, ids: list[str], start: list[float], d: dict) -> np.ndarray:
    """The mean-field model run from `start` (the counts at time 0) over the steps of data `d` (its
    inputs and announced injections): stocks x steps, as the data's levels."""
    t = d["t"]
    truth = {"flows": mf["flows"], **({"schedule": mf["schedule"]} if mf.get("schedule") else {})}
    flows, _ = truth_by_time(truth, t)
    inputs = {"t": t, "values": d["inputs"]} if d.get("inputs") else None
    m = Model(flows, ids, inputs=inputs)
    inj: dict[int, list] = {}
    for j in d.get("injections") or []:
        inj.setdefault(int(j["t"]), []).append(j)
    L = np.asarray(start, dtype=float)[:, None]
    out = np.zeros((len(ids), len(t)))
    for k, tk in enumerate(t):
        for j in inj.get(int(tk), []):
            i = ids.index(j["stock"])
            L[i, 0] = max(0.0, L[i, 0] + float(j["amount"]))
        L = m.step(L, np.asarray([tk], dtype=float))
        out[:, k] = L[:, 0]
    return out


def check(system, p: dict, mf: dict, seed: int, steps: int, runs: int = 40) -> dict:
    """The mean-field model against the average of `runs` particle runs (same start, same drivers, other
    motion): {z_rms, z_mean, z_max, within (share of |z| <= 3), rel (rms gap over the mean level), steps, runs}."""
    ids = system.ids(p)
    X = []
    for r in range(runs):
        d = simulate(system, p, seed, steps, motion_seed=10_000 + r)
        X.append(np.array([d["levels"][s] for s in ids], dtype=float))
    X = np.array(X)
    mean, sd = X.mean(axis=0), X.std(axis=0, ddof=1)
    M = run_model(mf, ids, start_levels(system, p, seed), d)
    se = np.maximum(sd / math.sqrt(runs), 0.5 / math.sqrt(runs))
    z = (mean - M) / se
    rel = float(np.sqrt(np.mean((mean - M) ** 2)) / max(1e-9, float(np.mean(mean))))
    return {"z_rms": float(np.sqrt(np.mean(z ** 2))), "z_mean": float(np.mean(z)), "z_max": float(np.max(np.abs(z))),
            "within": float(np.mean(np.abs(z) <= 3)), "rel": rel, "steps": steps, "runs": runs,
            "by_region": {s: float(np.sqrt(np.mean(z[i] ** 2))) for i, s in enumerate(ids)}}
