"""Scoring a found model on a physics case (the physics view; never in the Tests pass rate).

  structure   the coupling graph, sign and shape of the found model's Jacobian on the run's
              states against the physics' couplings (structure.py)
  behaviour   skill@20 and skill@100 (sdlab/skill.py's grading: the found model run H steps from
              ~150 moments of the true levels, fed the measured inputs and the announced injections,
              against what the physics did next), on the run discovery saw and on a fresh run (new
              initial state and drivers, seed + 1). With measurement noise, graded on the clean run
              underneath, as noise.py's variants are
  long run    the found model run free (nothing re-anchored) for LONG steps from the fresh run's
              first levels (a found model with hidden stocks of its own: from step 200, its hidden
              levels estimated from the measured ones before), against the physics continued as long: rms over stocks of (found -
              true) / the truth's range over the last 1,000 steps (`err`), and of the gap in mean
              levels there (`mean_err`), each capped at 1 (a run that diverges counts 1)
  reference   the best SD model (reference.py), graded the same way: what SD Lab's forms can do

**pass** (the physics view's verdict): the structure agrees (every coupling the physics has is
present with its sign, nothing spurious; the shape is reported, not required, since SD Lab's forms
cannot write a sqrt or a switch) and the fresh run's skill@20 is within 5 points of the
reference's, or better. Otherwise fail; an error or timeout is not scored.
"""

from __future__ import annotations

import numpy as np

from ...discovery.observer import observe, unmeasured
from ...discovery.simulate import Model, levels_array, starts_for
from ...skill import same_behaviour
from . import structure

HORIZONS = (20, 100)
STARTS = 150
LONG = 5000
TAIL = 1000
WARM = 200
GAP = 0.05


def _truth(data: dict, horizon: int) -> dict:
    """skill.py's truth side for a physics run: the truth's end is what the physics did next."""
    lv = data.get("all_levels") or data["levels"]
    ids = list(lv)
    A = levels_array(lv, ids)
    s0 = starts_for(A.shape[1], horizon, STARTS)
    times = np.asarray(data["t"], dtype=float)[s0[None, :] + np.arange(horizon)[:, None]]
    return {"horizon": horizon, "flows": [], "ids": ids, "fed": set(), "exo": [], "A": A, "s0": s0, "times": times,
            "truth_end": A[:, s0 + horizon - 1], "injections": data.get("injections"),
            "inputs": {"t": data["t"], "values": data["inputs"]} if data.get("inputs") else None}


def behaviour(flows: list[dict], clean: dict, fresh: dict | None, inferred: dict | None = None) -> dict:
    out = {}
    for name, d in (("in_sample", clean), ("fresh", fresh)):
        if d is None:
            continue
        res = {}
        for h in HORIZONS:
            if len(d["t"]) < h + 10:
                continue
            result = {"flows": flows, **({"inferred_levels": inferred} if inferred and name == "in_sample" else {})}
            b = same_behaviour(result, {}, d, horizon=h, truth=_truth(d, h), ci=True, own_run=name == "in_sample")
            res[str(h)] = {"skill": _finite(b["skill"]), "ci": [_finite(x) for x in b["ci"]] if b.get("ci") else None, "moved": _finite(b["moved"])}
        out[name] = res
    return out


def long_run(flows: list[dict], long: dict) -> dict:
    """The found model run free over the long run (module docstring)."""
    ids = list(long["levels"])
    T = levels_array(long["levels"], ids)
    t = np.asarray(long["t"], dtype=float)
    own = [{k: v for k, v in f.items() if k != "via"} for f in flows]
    hidden = unmeasured(own, ids)
    w = WARM if hidden else 0                       # the found model's own hidden stocks: estimated over the first steps
    L = T[:, w:w + 1].copy()
    if hidden:
        est = observe(own, ids, long["t"][:w + 1], {s: v[:w + 1] for s, v in long["levels"].items()}, hidden, {})
        L = np.vstack([L, np.array([[float(np.nan_to_num((est.get(h) or [0.0])[-1]))] for h in hidden])])
    inputs = {"t": long["t"], "values": long["inputs"]} if long.get("inputs") else None
    model = Model(own, ids + hidden, inputs=inputs)
    pulses: dict[float, list] = {}
    for j in long.get("injections") or []:
        if j["stock"] in ids:
            pulses.setdefault(float(j["t"]), []).append((ids.index(j["stock"]), float(j["amount"])))
    F = np.zeros_like(T)
    F[:, : w + 1] = T[:, : w + 1]
    span = np.maximum(T.max(axis=1) - T.min(axis=1), 1e-9)
    limit = 100 * (np.abs(T).max(axis=1) + span)
    diverged = False
    for k in range(w + 1, T.shape[1]):
        for i, amount in pulses.get(t[k], []):
            L[i, 0] = max(0.0, L[i, 0] + amount)
        L = model.step(L, t[k:k + 1])
        F[:, k] = L[: len(ids), 0]
        if not np.all(np.isfinite(F[:, k])) or np.any(np.abs(F[:, k]) > limit):
            diverged = True
            break
    if diverged:
        return {"err": 1.0, "mean_err": 1.0, "diverges": True, "steps": int(T.shape[1])}
    tail = slice(T.shape[1] - TAIL, None)
    e = (F[:, tail] - T[:, tail]) / span[:, None]
    err = float(np.sqrt(np.mean(e ** 2)))
    mean_err = float(np.sqrt(np.mean(((F[:, tail].mean(axis=1) - T[:, tail].mean(axis=1)) / span) ** 2)))
    return {"err": min(1.0, err), "mean_err": min(1.0, mean_err), "diverges": False, "steps": int(T.shape[1])}


def grade(case: dict, flows: list[dict], clean: dict, fresh: dict, long: dict, inferred: dict | None = None) -> dict:
    """Structure, behaviour and long run of one model (found or the reference)."""
    ph = case["physics"]
    names, V, _ = structure.variables(clean, ph["inputs"])
    rec, src, p = structure.found_jacobian(flows, clean, ph["inputs"])
    cmp = structure.compare([tuple(c) for c in ph["couplings"]], structure.couplings(rec, src, p, V))
    return {"structure": cmp, "behaviour": behaviour(flows, clean, fresh, inferred), "longrun": long_run(flows, long)}


def skill(b: dict, where: str, h: int):
    return ((b.get(where) or {}).get(str(h)) or {}).get("skill")


def score(case: dict, flows: list[dict], clean: dict, fresh: dict, long: dict, ref: dict, inferred: dict | None = None) -> dict:
    """Everything stored for one found model: the ladder's usual keys (status, recall, precision, right,
    of, behaviour) and `physics` (structure, long run, the reference and the gaps to it)."""
    g = grade(case, flows, clean, fresh, long, inferred)
    st, b = g["structure"], g["behaviour"]
    f20, r20 = skill(b, "fresh", 20), skill(ref["behaviour"], "fresh", 20)
    f100, r100 = skill(b, "fresh", 100), skill(ref["behaviour"], "fresh", 100)
    near = f20 is not None and r20 is not None and f20 >= r20 - GAP
    passed = bool(st["ok"] and near)
    ph = case["physics"]
    notes = []
    if ph.get("differs"):
        notes.append(f"physics vs SD: {ph['differs']}")
    wrong_shape = [r for r in st["couplings"] if r["present"] and not r["shape_ok"]]
    if wrong_shape:
        notes.append("shape: " + "; ".join(f"{r['key']} found {r['shape_found']}, physics {r['shape_true']}" for r in wrong_shape))
    return {"status": "pass" if passed else "fail", "pass": passed, "equivalent": False,
            "recall": st["recall"], "precision": st["precision"], "right": st["right"], "of": st["of"],
            "parts": [], "spurious": [], "negligible": [], "windows": 1, "notes": notes,
            "physics": {"system": ph["system"], "couplings": st["couplings"], "spurious": st["spurious"], "structure_ok": st["ok"],
                        "shape_right": st["shape_right"], "shape_of": st["shape_of"], "longrun": g["longrun"],
                        "near_reference": near, "gap20": None if f20 is None or r20 is None else f20 - r20,
                        "gap100": None if f100 is None or r100 is None else f100 - r100,
                        "reference": {"how": ph["reference"]["how"], "behaviour": ref["behaviour"], "longrun": ref["longrun"],
                                      "structure_ok": ref["structure"]["ok"], "shape_right": ref["structure"]["shape_right"]}},
            "behaviour": b}


def _finite(x):
    x = float(x)
    return x if np.isfinite(x) else None
