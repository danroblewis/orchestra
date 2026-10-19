"""Noise that real data carries, laid on the recorded levels AFTER the engine has run (the engine is
fixed): measurement error, missing points, weekly reporting, a reporting delay, outliers and a
calibration bias. Every one sits on top of counting noise (the run is the case's `counts` run with
the same seed), since real counts move in whole things and are then measured badly.

A case opts in by naming them in its variants (cases.py); the defaults stay `none` and `counts`:

    variants:
      noise: [none, counts, meas, gaps, weekly, lag, outliers, bias]
      # or with numbers:          [counts, {meas: {rel: 0.1, abs: 0}}, {lag: {steps: 5}}]

| noise    | what discovery sees                                                            | numbers (default)       |
|----------|--------------------------------------------------------------------------------|-------------------------|
| meas     | every level plus Gaussian error, sd = sqrt(abs^2 + (rel x level)^2)              | rel 0.05, abs 1         |
| gaps     | each point (not the first or last) missing with probability `missing`: t jumps | missing 0.3             |
| weekly   | one point per `every` steps: the mean over the period (how: mean) or its last   | every 7, how mean       |
| lag      | the level of `steps` steps before, stamped now (announced events keep their t) | steps 3                 |
| outliers | each level, with probability `rate`, off by +-U(0.5, 1) x the stock's mean level | rate 0.01               |
| bias     | one stock's levels (default: the last measured stock) times `factor`           | factor 1.2              |

Each is deterministic from the run's seed (the fresh run: seed + 1). A variant of one of these has
`observe: {kind, ...numbers}` beside its name, noise, length and steps; `none` and `counts` variants
have no `observe`, so existing cases and their hashes are untouched.

apply(clean, observe, seed) -> the data discovery and the scorer get: {"t", "levels" (what is
reported), "all_levels" (every stock's true level at the reported times, for grading), "eras",
"injections", "counters", "observation" (what was done: for each reported point the true time it
shows (`at`) and how many steps it averages (`span`), the outliers made, the bias; the scorer's
oracle, noise_oracle.py, reads it), "clean" (the counts run underneath, every step, with the truth's
flows over it: for behaviour, the long run and the oracle; discovery never gets it)}.
"""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = "counts"                                  # the engine noise every one of these sits on
DEFAULTS: dict[str, dict] = {
    "meas": {"rel": 0.05, "abs": 1.0},
    "gaps": {"missing": 0.3},
    "weekly": {"every": 7, "how": "mean"},
    "lag": {"steps": 3},
    "outliers": {"rate": 0.01},
    "bias": {"factor": 1.2, "stock": None},
}
KINDS = tuple(DEFAULTS)
ENGINE = ("none", "counts")


class NoiseError(ValueError):
    pass


def code_hash() -> str:
    """The code that makes and scores these variants (a case that opts in is hashed with it)."""
    h = hashlib.sha256()
    for name in ("noise.py", "noise_kf.py", "noise_oracle.py"):
        h.update((HERE / name).read_bytes())
    return h.hexdigest()[:16]


def entries(spec) -> list[tuple[str, dict | None]]:
    """A case's `variants: noise:` list as [(name, observe or None)]: a string names a noise with its
    default numbers, a one-key mapping {name: {numbers}} sets some."""
    out, seen = [], set()
    for item in spec:
        if isinstance(item, str):
            name, nums = item, {}
        elif isinstance(item, dict) and len(item) == 1:
            name, nums = next(iter(item.items()))
            nums = dict(nums or {})
        else:
            raise NoiseError(f"a noise is a name or {{name: {{numbers}}}}, not {item!r}")
        if name in seen:
            raise NoiseError(f"noise {name!r} is listed twice")
        seen.add(name)
        if name in ENGINE:
            if nums:
                raise NoiseError(f"noise {name!r} takes no numbers")
            out.append((name, None))
            continue
        if name not in DEFAULTS:
            raise NoiseError(f"unknown noise {name!r} (have: {', '.join(ENGINE + KINDS)})")
        unknown = set(nums) - set(DEFAULTS[name])
        if unknown:
            raise NoiseError(f"noise {name!r} has no {', '.join(sorted(unknown))} (has: {', '.join(DEFAULTS[name])})")
        obs = {"kind": name, **DEFAULTS[name], **nums}
        _check(obs)
        out.append((name, obs))
    return out


def _check(o: dict) -> None:
    k = o["kind"]
    bad = (k == "meas" and (o["rel"] < 0 or o["abs"] < 0)) or (k == "gaps" and not 0 <= o["missing"] < 1) \
        or (k == "weekly" and (int(o["every"]) < 2 or o["how"] not in ("mean", "end"))) or (k == "lag" and int(o["steps"]) < 1) \
        or (k == "outliers" and not 0 <= o["rate"] < 0.5) or (k == "bias" and o["factor"] <= 0)
    if bad:
        raise NoiseError(f"noise {k}: numbers out of range: {o}")


def engine_noise(v: dict) -> str:
    """The engine noise a variant's run is made with."""
    return BASE if v.get("observe") else v["noise"]


def _rng(seed: int, kind: str) -> np.random.Generator:
    return np.random.default_rng([int(seed), zlib.crc32(kind.encode()), 20261018])


def apply(clean: dict, observe: dict, seed: int, flows: list[dict] | None = None) -> dict:
    """The data a noisy variant reports, from the counts run `clean` (data.py's dict)."""
    kind = observe["kind"]
    rng = _rng(seed, kind)
    t = list(clean["t"])
    ids = list(clean["levels"])
    X = {s: np.asarray(v, dtype=float) for s, v in clean["levels"].items()}
    n = len(t)
    at = np.arange(n)                                    # the clean index each reported point shows
    span = 1
    Y = {s: v.copy() for s, v in X.items()}
    stamp = np.asarray(t)
    outliers: list[list] = []
    bias: dict[str, float] = {}
    if kind == "meas":
        for s in ids:                                    # stocks in order, each its own draws
            sd = np.sqrt(observe["abs"] ** 2 + (observe["rel"] * X[s]) ** 2)
            Y[s] = X[s] + sd * rng.standard_normal(n)
    elif kind == "gaps":
        keep = rng.random(n) >= observe["missing"]
        keep[0] = keep[-1] = True
        at = np.flatnonzero(keep)
    elif kind == "weekly":
        L = int(observe["every"])
        ends = np.arange(L - 1, n, L)                     # whole periods only
        at, span = ends, (L if observe["how"] == "mean" else 1)
        if span > 1:
            for s in ids:
                Y[s] = np.convolve(X[s], np.ones(L) / L, mode="full")[: n]   # Y[i] = mean of X[i-L+1..i]
    elif kind == "lag":
        k = int(observe["steps"])
        if k >= n - 2:
            raise NoiseError(f"lag {k} leaves no data")
        at = np.arange(n - k)
        stamp = np.asarray(t)[k:]                        # x(t - k) reported at t
    elif kind == "outliers":
        for s in ids:
            hit = rng.random(n) < observe["rate"]
            size = rng.uniform(0.5, 1.0, n) * rng.choice([-1.0, 1.0], n) * max(float(np.mean(np.abs(X[s]))), 10.0)
            Y[s] = np.where(hit, np.maximum(0.0, X[s] + size), X[s])
            outliers += [[int(i), s] for i in np.flatnonzero(hit)]
    elif kind == "bias":
        s = observe.get("stock") or ids[-1]
        if s not in ids:
            raise NoiseError(f"bias: {s!r} is not a measured stock")
        bias[s] = float(observe["factor"])
        Y[s] = X[s] * bias[s]
    if kind != "lag":
        stamp = np.asarray(t)[at]
    levels = {s: [round(float(x), 4) for x in Y[s][at]] for s in ids}
    all_levels = {s: [v[i] for i in at.tolist()] for s, v in (clean.get("all_levels") or clean["levels"]).items()}
    if kind == "lag":                                    # graded at the times stamped
        all_levels = {s: list(v[int(observe["steps"]):]) for s, v in (clean.get("all_levels") or clean["levels"]).items()}
    out = {"t": [int(x) for x in stamp], "levels": levels, "all_levels": all_levels, "eras": clean["eras"], "counters": clean.get("counters"),
           "observation": {**observe, "at": at.tolist(), "span": span, "outliers": outliers, "bias": bias},
           "clean": {k: clean[k] for k in ("t", "levels", "all_levels", "eras", "injections", "inputs") if k in clean}}
    if flows is not None:
        out["clean"]["flows"] = flows                    # the truth's flows over every step (the scorer's)
    if clean.get("injections"):
        out["injections"] = clean["injections"]
    if clean.get("inputs"):
        out["inputs"] = clean["inputs"]
    return out
