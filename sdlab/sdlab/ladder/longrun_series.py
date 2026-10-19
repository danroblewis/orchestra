"""What the run page (/ladder/run) plots for one stored result: per measured stock, the true model
vs the found model's prediction, both run free from the run's start (longrun.py).

    graph(result_id, at=[...], window=W) -> {
      result: {id, case, variant, strategy, status}, stocks: [measured ids],
      run:      {t, data (recorded levels), truth, found}           the recorded run (at most ~800 points)
      overview: {t, truth, found}                                   log-spaced times from the start to the far end
      windows:  [{T, label, t, truth, found, err}]                  W steps ending at each T (1k, 10k, 100k,
                                                                    10 and 100 tau, and any `at`)
      metrics:  longrun.grade(...),  how: {true, found}             how each run's future was known
    }

Levels past a runaway are null. A time far past the end the models were stepped to is answered
in constant time when the run settled or drifts (any T), and otherwise only up to where it was stepped.
"""

from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np

from . import cases as casemod
from . import data as datamod
from . import longrun, longrun_cache, store

MAX_POINTS = 800
OVERVIEW = 400
T_LIMIT = 10 ** 12
_setups: OrderedDict = OrderedDict()
_found: OrderedDict = OrderedDict()           # (result id, setup): the found model's trajectory


def setup(case_id: str, variant: str) -> longrun.Setup:
    c = casemod.load(case_id)
    key = (case_id, c["hash"], variant)
    if key not in _setups:
        d = datamod.load(c, variant)
        _setups[key] = longrun.Setup(casemod.truth_model(c, variant), d.get("clean") or d)     # noise.py's variants: the run underneath
        while len(_setups) > 32:
            _setups.popitem(last=False)
    _setups.move_to_end(key)
    return _setups[key]


def _list(a: np.ndarray) -> list:
    return [[None if not math.isfinite(x) else round(float(x), 6) for x in row] for row in a]


def _stride(ts: np.ndarray, n: int) -> np.ndarray:
    if len(ts) <= n:
        return ts
    return ts[np.unique(np.linspace(0, len(ts) - 1, n).round().astype(int))]


def graph(result_id: int, at: list[int] | None = None, window: int | None = None) -> dict | None:
    row = store.get(result_id, found=True)
    if row is None or row.get("found") is None or row["case"] not in casemod.case_ids():
        return None
    s = setup(row["case"], row["variant"])
    key = (result_id, id(s))
    if key not in _found:
        _found[key] = s.found(row["found"])[0]
        while len(_found) > 64:
            _found.popitem(last=False)
    ftraj = _found[key]
    nm = len(s.measured)
    metrics = longrun_cache.of_result(row)
    if not metrics or metrics.get("error"):
        metrics = longrun.grade(s, row["found"])

    def both(ts):
        return _list(s.traj.at(ts)[s.m]), _list(ftraj.at(ts)[:nm])

    t_run = _stride(np.arange(s.t1, s.n_run + 1), MAX_POINTS)
    run_truth, run_found = both(t_run)
    rec = s.recorded[s.m][:, t_run - s.t0]
    far = max(max(s.points.values()), *(at or [0]))
    t_over = np.unique(np.geomspace(s.t1, max(far, s.t1 + 1), OVERVIEW).round().astype(np.int64))
    over_truth, over_found = both(t_over)
    W = int(window or max(s.traj.C, 200))
    W = max(10, min(W, 20_000))
    marks = [(k, v) for k, v in s.points.items()] + [(f"t={x}", int(x)) for x in at or [] if s.t1 < int(x) <= T_LIMIT]
    windows = []
    for label, T in sorted(marks, key=lambda x: x[1]):
        ts = _stride(np.arange(max(s.t1, T - W + 1), T + 1), MAX_POINTS)
        tr, fd = both(ts)
        known = s.traj.how in ("settled", "drift") or T <= s.traj.t_sim
        windows.append({"T": T, "label": label, "t": ts.tolist(), "truth": tr, "found": fd, "known": known,
                        "err": (metrics["err"] or {}).get(label)})
    return {"result": {k: row[k] for k in ("id", "case", "variant", "strategy", "status")}, "stocks": s.measured,
            "run": {"t": t_run.tolist(), "data": _list(rec), "truth": run_truth, "found": run_found},
            "overview": {"t": t_over.tolist(), "truth": over_truth, "found": over_found},
            "windows": windows, "window": W, "metrics": metrics, "chunk": s.traj.C,
            "how": {"true": s.traj.how, "found": ftraj.how, "true_until": s.traj.t_sim, "found_until": ftraj.t_sim},
            "scale": [float(x) for x in s.scale[s.m]]}
