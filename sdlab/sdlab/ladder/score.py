"""Scoring a found model against a case's true model: did discovery recover the true equations?

**Parts.** Every flow is cut into parts, one per number in its equation, keyed by where it goes and
what it reads. A flow's rate in a linear form (constant, proportional, gap, linear) is
c + sum k_j x level_j: its parts are (from, to, "1") = c and (from, to, j) = k_j, with from / to the
measured stock or outside. The kind follows from the key: a **move** (measured to measured), an
**outside inflow** (from outside, reading nothing), a **link** (from outside, reading a stock), an
**outside outflow** (to outside). A flow's co-flow is a part (uses, from, to, stock) = per; an
effect is a part (effect, from, to, stock); a hidden stock between measured A and B (A -> H -> B, H
not measured) is one part (hidden, A, B) = {k_in, delay}. Found and true parts with the same key
are summed (two links into one stock from the same driver are one number in the data).

**Windows.** A rate that changes (announced eras, unannounced schedule changes) is compared in
every window where the truth's equations hold still: the found flow's numbers are averaged over
the window (its byTime segments or outside inflow pieces), and a part must be right in every one.

**Tolerance.** A number k is right when |found - true| <= max(rel x |true|, floor / mean level of
what it reads, z x its standard error), with rel 10% (2% without noise), floor 1% (0.2% without
noise) of the median size of the true parts (size: |k| x the mean level it reads, a flow amount per
step), and z = 3 standard errors of the oracle (oracle.py: the truth's own structure fitted by least
squares on the run, so a short noisy run is not asked for more than it can tell; for a truth with a
hidden stock, hidden_oracle.py: its structure fitted by the Kalman filter's likelihood on the
measured data, which also gives the delay's SE; a hidden part's delay is right within
max(rel x delay, z x SE)). A flow with
effects is compared as a whole: its amount on the run's states (rate x effects) against the found
flows between the same stocks, as relative rms error within rel. Override per case: "tolerance":
{"rel", "rel_exact", "floor", "floor_exact", "spurious", "z"}.

**Scores.** recall = true parts whose key the found model has (right kind and ends); precision =
found parts above the size threshold whose key is true; pass = every true part right and no
spurious part (a found part the truth lacks, larger than "spurious", 5% of the median true part
size, and with an oracle, larger than z standard errors of that term added to the truth's fit). **equivalent** (when not pass): the found flows make the same linear system as the truth
(every stock's change the same function of the levels and the outside, within tolerance), so the
data cannot tell them apart (births and deaths of one stock seen as their difference, a gap seen as
an inflow and a drain); it is reported apart from pass. Not checked for cases with effects or
hidden stocks (nonlinear, or of another size).

**Behaviour.** skill@20 and skill@100 (sdlab/skill.py) on the run discovery saw and on a fresh run
(another seed), each with a 95% bootstrap interval over the start moments.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from ..runner import multiplier
from ..skill import same_behaviour, truth_by_time, truth_runs
from .hidden_oracle import HiddenOracle
from .oracle import Oracle
from .parts import ONE, form_over, kind, label, linear_system, parts, windows

DEFAULTS = {"rel": 0.10, "rel_exact": 0.02, "floor": 0.01, "floor_exact": 0.002, "spurious": 0.05, "z": 3.0}
HORIZONS = (20, 100)


def score_hash() -> str:
    """The scoring code: a change re-scores stored results (without re-running discovery)."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in (here / "score.py", here / "parts.py", here / "oracle.py", here / "hidden_oracle.py", here.parent / "skill.py", here.parent / "discovery" / "simulate.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---- the comparison ----

def _tolerances(case: dict, noise: str) -> dict:
    t = {**DEFAULTS, **(case.get("tolerance") or {})}
    exact = noise == "none"
    return {"rel": t["rel_exact"] if exact else t["rel"], "floor": t["floor_exact"] if exact else t["floor"], "spurious": t["spurious"], "z": t["z"]}


def _size(key: tuple, value, means: dict, among: dict) -> float:
    """A part's size: its flow amount per step (|k| x the mean level it reads; a co-flow's per x
    the amount of its flow; an effect counts as large)."""
    if key[0] == "flow":
        return abs(value) * (1.0 if key[3] == ONE else means.get(key[3], 0.0))
    if key[0] == "hidden":
        return abs(value["k_in"]) * means.get(key[1], 0.0)
    if key[0] == "uses":
        return abs(value) * sum(_size(k, v, means, among) for k, v in among.items() if k[0] == "flow" and k[1:3] == key[1:3])
    return math.inf


def _amounts(flows: list[dict], ends: tuple, measured: set, data: dict) -> np.ndarray | None:
    """The amount per step of the flows between `ends` on the run's states (rate x effects, floored
    at 0 as the engine does; no cap)."""
    lv = data.get("all_levels") or data["levels"]
    t = data["t"]
    n = len(t)
    total = np.zeros(n - 1)
    for f in flows:
        a = f.get("from") if f.get("from") in measured else None
        b = f.get("to") if f.get("to") in measured else None
        if (a, b) != ends or f.get("via"):
            continue
        for i in range(n - 1):
            level = {s: v[i] for s, v in lv.items()}
            lf = form_over(f, t[i + 1], t[i + 1])
            if lf is None:
                return None
            rate = max(0.0, lf[0] + sum(k * level.get(j, 0.0) for j, k in lf[1].items()))
            total[i] += rate * multiplier(f, level)
    return total


def _close(true: float, found: float, reader: str | None, tol: dict, means: dict, scale: float, se: float | None = None) -> tuple[bool, float]:
    """Within tolerance (relative, the floor, or z standard errors of the oracle), and the relative
    error (absolute when the true number is 0)."""
    level = 1.0 if reader in (None, ONE) else max(1e-9, means.get(reader, 0.0))
    allowed = max(tol["rel"] * abs(true), tol["floor"] * scale / level, tol["z"] * (se or 0.0))
    err = abs(found - true)
    return err <= allowed + 1e-12, (err / abs(true) if true else err)


def equations(case: dict, noise: str, truth_model: dict, found_flows: list[dict], data: dict) -> dict:
    """Equation recovery: {status, pass, equivalent, recall, precision, parts: [...], spurious: [...],
    notes}. status is "pass", "equivalent" or "fail"."""
    tol = _tolerances(case, noise)
    measured = set(data["levels"])
    ids = list(data["levels"])
    lv = data.get("all_levels") or data["levels"]
    means = {s: float(np.mean(v)) if len(v) else 0.0 for s, v in lv.items()}
    t = data["t"]
    wins = windows(truth_model, t)
    truth_flows, _ = truth_by_time(truth_model, t)
    effect_ends = {(f.get("from") if f.get("from") in measured else None, f.get("to") if f.get("to") in measured else None)
                   for f in truth_model["flows"] if f.get("effects")}
    true_w, found_w, notes = [], [], []
    for w in wins:
        tp, tn = parts(truth_flows, measured, w)
        fp, fn = parts(found_flows, measured, w)
        true_w.append(tp)
        found_w.append(fp)
        notes += [f"truth: {x}" for x in tn] + [f"found: {x}" for x in fn]
    weights = np.array([b - a + 1 for a, b in wins], dtype=float)
    weights /= weights.sum()
    true_keys = list(dict.fromkeys(k for tp in true_w for k in tp))
    found_keys = list(dict.fromkeys(k for fp in found_w for k in fp))
    sizes = [sum(wt * _size(k, tp[k], means, tp) for wt, tp in zip(weights, true_w) if k in tp) for k in true_keys]
    finite = [s for s in sizes if math.isfinite(s) and s > 0]
    scale = float(np.median(finite)) if finite else 1.0

    oracle = Oracle(truth_flows, data, wins)
    hidden = HiddenOracle(truth_flows, data, wins, noise) if not oracle.ok and any(k[0] == "hidden" for k in true_keys) else None
    function_check: dict[tuple, tuple[bool, float]] = {}
    for ends in effect_ends:
        want = _amounts(truth_flows, ends, measured, data)
        got = _amounts(found_flows, ends, measured, data)
        if want is None or got is None:
            function_check[ends] = (False, math.inf)
            continue
        err = float(np.sqrt(np.mean((got - want) ** 2)) / max(1e-9, np.sqrt(np.mean(want ** 2))))
        function_check[ends] = (err <= tol["rel"], err)

    rows = []
    for k in true_keys:
        row = {"key": label(k), "kind": kind(k), "found": k in found_keys}
        if k[0] == "effect" or (k[0] in ("flow", "uses") and (k[1], k[2]) in effect_ends):
            ok, err = function_check[(k[1], k[2])]
            row.update(true=_show(true_w[0].get(k)), found_value=_show(next((fp[k] for fp in found_w if k in fp), None)),
                       ok=bool(row["found"] and ok), error=err, compared="as a whole flow (effects)")
        elif k[0] == "hidden":
            oks, errs, ses = [], [], []
            for w, (tp, fp) in enumerate(zip(true_w, found_w)):
                if k not in tp:
                    continue
                hse = (hidden.hidden_se(k, w) if hidden else None) or {}
                ses.append(hse or None)
                if k not in fp:
                    oks.append(False)
                    continue
                o1, e1 = _close(tp[k]["k_in"], fp[k]["k_in"], k[1], tol, means, scale, hse.get("k_in"))
                allowed = max(tol["rel"] * tp[k]["delay"], tol["z"] * (hse.get("delay") or 0.0)) if math.isfinite(tp[k]["delay"]) else -1.0
                o2 = abs(fp[k]["delay"] - tp[k]["delay"]) <= allowed + 1e-9
                oks.append(o1 and o2)
                errs.append(max(e1, abs(fp[k]["delay"] - tp[k]["delay"]) / max(1e-9, tp[k]["delay"])))
            row.update(true=true_w[0].get(k), found_value=next((fp[k] for fp in found_w if k in fp), None), ok=bool(oks) and all(oks),
                       error=max(errs) if errs else None, se_hidden=ses[0] if hidden and hidden.ok and ses else None)
        else:
            oks, errs, ses = [], [], []
            for w, (tp, fp) in enumerate(zip(true_w, found_w)):
                se = oracle.part_se(k, true_keys, w) if oracle.ok else hidden.part_se(k, w) if hidden else None
                ok, err = _close(float(tp.get(k, 0.0)), float(fp.get(k, 0.0)), k[3] if k[0] == "flow" else None, tol, means, scale, se)
                oks.append(ok)
                errs.append(err)
                ses.append(se)
            tv = [float(tp.get(k, 0.0)) for tp in true_w]
            fv = [float(fp.get(k, 0.0)) for fp in found_w]
            row.update(true=_one(tv, weights), found_value=_one(fv, weights) if row["found"] else None,
                       ok=bool(row["found"] and all(oks)), error=max(errs), windows=len(wins) if len(wins) > 1 else None,
                       se=_one([x if x is not None else math.nan for x in ses], weights) if oracle.ok or (hidden and hidden.ok) else None)
        rows.append(row)

    spurious, extra = [], []
    for k in found_keys:
        if k in true_keys:
            continue
        size = sum(wt * _size(k, fp[k], means, fp) for wt, fp in zip(weights, found_w) if k in fp)
        # an extra term is spurious when it is large, and (with an oracle) clearly more than the data's
        # noise could make of a term that is not there: |k| above z standard errors in every window it is in
        if k[0] == "flow" and oracle.ok:
            ses = [oracle.part_se(k, true_keys, w) for w, fp in enumerate(found_w) if k in fp]
            noise_only = all(s is not None and abs(fp[k]) <= tol["z"] * s for s, fp in zip(ses, [fp for fp in found_w if k in fp]))
        else:
            noise_only = False
        entry = {"key": label(k), "kind": kind(k), "value": _show(_one([float(fp.get(k, 0.0)) for fp in found_w], weights) if k[0] in ("flow", "uses")
                                                                   else next(fp[k] for fp in found_w if k in fp)), "size": size}
        (spurious if size > tol["spurious"] * scale and not noise_only else extra).append(entry)
    big_found = [k for k in found_keys if k in true_keys] + [e for e in spurious]
    recall = sum(r["found"] for r in rows) / len(rows) if rows else 1.0
    precision = (sum(1 for k in found_keys if k in true_keys) / len(big_found)) if big_found else (1.0 if not rows else 0.0)
    passed = all(r["ok"] for r in rows) and not spurious
    equivalent = False
    if not passed and not effect_ends and not any(k[0] == "hidden" for k in true_keys):
        equivalent = True
        for w in wins:
            T, F = linear_system(truth_flows, ids, w), linear_system(found_flows, ids, w)
            if T is None or F is None or not _same_system(T, F, ids, tol, means, scale, oracle, wins.index(w)):
                equivalent = False
                break
    status = "pass" if passed else "equivalent" if equivalent else "fail"
    return {"status": status, "pass": passed, "equivalent": equivalent, "recall": recall, "precision": precision,
            "right": sum(r["ok"] for r in rows), "of": len(rows), "parts": rows, "spurious": spurious, "negligible": extra,
            "windows": len(wins), "tolerance": tol, "scale": scale, "notes": sorted(set(notes))}


def _same_system(T, F, ids, tol, means, scale, oracle, w) -> bool:
    (Bt, ut), (Bf, uf) = T, F
    for i, row in enumerate(ids):
        if not _close(ut[i], uf[i], None, tol, means, scale, oracle.se(row, ONE, w))[0]:
            return False
        for j, s in enumerate(ids):
            if not _close(Bt[i, j], Bf[i, j], s, tol, means, scale, oracle.se(row, s, w))[0]:
                return False
    return True


def _one(values: list[float], weights: np.ndarray):
    """One number for a part over the windows: the value if it never changes, else per window."""
    if all(abs(v - values[0]) < 1e-12 for v in values):
        return values[0]
    return {"mean": float(np.dot(values, weights)), "per_window": values if len(values) <= 12 else None}


def _show(v):
    if isinstance(v, dict) and v.get("shape"):
        return {k: v[k] for k in ("shape", "normal", "max", "min", "points") if k in v}
    return v


# ---- behaviour ----

def behaviour(truth_model: dict, found_flows: list[dict], data: dict, fresh: dict | None, inferred: dict | None = None) -> dict:
    """skill@20 / @100 with 95% bootstrap intervals, in-sample and (if given) on a fresh run. A found
    model's own unmeasured stocks start from its estimate of their levels (`inferred`) on the run it
    saw, and from the estimate it gives from the fresh run's levels on the fresh run."""
    out = {}
    for name, d in (("in_sample", data), ("fresh", fresh)):
        if d is None:
            continue
        res = {}
        for h in HORIZONS:
            if len(d["t"]) < h + 10:
                continue
            tr = truth_runs(truth_model, d, horizon=h)
            result = {"flows": found_flows, **({"inferred_levels": inferred} if inferred and name == "in_sample" else {})}
            b = same_behaviour(result, truth_model, d, horizon=h, truth=tr, ci=True, own_run=name == "in_sample")
            res[str(h)] = {"skill": _finite(b["skill"]), "ci": [_finite(x) for x in b["ci"]] if b.get("ci") else None, "moved": _finite(b["moved"])}
        out[name] = res
    return out


def _finite(x):
    x = float(x)
    return x if math.isfinite(x) else None


def score(case: dict, noise: str, truth_model: dict, found_flows: list[dict], data: dict, fresh: dict | None = None,
          inferred: dict | None = None) -> dict:
    """Everything the ladder records for one found model: equations and behaviour."""
    eq = equations(case, noise, truth_model, found_flows, data)
    return {**eq, "behaviour": behaviour(truth_model, found_flows, data, fresh, inferred)}
