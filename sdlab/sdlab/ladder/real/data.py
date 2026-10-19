"""A real case's data in a variant: the measured series (`real`) or the published model's twin (`twin`).

load(case, variant) is what discovery gets: the first `train` samples. load(..., full=True) is the whole
series, for the held-out scoring (the runner passes it where a ladder case passes its fresh run).

Both have the ladder's data shape: {"t", "levels" (measured stocks), "all_levels" (the real series:
the same; the twin: every stock, hidden ones too, for its equation scoring), "eras" (one: the start),
"injections" (announced), "flows"? (measured gross flows, BLS)}.

The real variant reads the cache (loaders.py; nothing is downloaded here) and checks the series'
sha256 against the case's; a missing or different download raises sources.Missing (the runner's
planner skips such a variant: "not run", with the fetch command). The twin needs no download: the
engine runs the case's model with noise none (sdlab/ladder/data.simulate, cached under
$SDLAB_LADDER_CACHE/real), sample 0 being the initial levels, and Gaussian measurement error
sd = rel x max(level, floor) per measured stock (`real.twin`) is added, deterministic from the case's
seed, levels floored at 0; a stock the data give as a total minus another (`complement`: adoption's
N = 100 - A) is that total minus the other's noisy level, as in the data.
"""

from __future__ import annotations

import json
import os
import threading
import time
import zlib

import numpy as np

from . import loaders, sources
from .loaders import series_sha


_known: dict = {}


def available(case: dict, variant_name: str) -> str | None:
    """None if the variant's data can be loaded, else why not (with the command that fixes it). Remembered
    for a minute per case (the planner asks for every case on every sync)."""
    if variant_name != "real":
        return None
    key = (case["id"], case["hash"], int(time.time() // 60))
    if key not in _known:
        try:
            _series(case)
            _known[key] = None
        except sources.Missing as e:
            _known[key] = str(e)
        except (OSError, ValueError, KeyError) as e:          # a broken download: not run, and said so
            _known[key] = f"{case['id']}: the {case['real']['source']} data cannot be read ({type(e).__name__}: {e})"
    return _known[key]


def missing_notes(case_ids: list[str]) -> list[str]:
    """One line per real case (among these) whose data are missing: what the runner will not run, and why."""
    from .. import cases as casemod

    out = []
    for cid in case_ids:
        if not casemod.is_real(cid):
            continue
        why = available(casemod.load(cid), "real")
        if why:
            out.append(f"{cid} real (the twin still runs): {why}")
    return out


def _series(case: dict) -> dict:
    r = case["real"]
    s = loaders.series(r["source"], r["select"])
    got = series_sha(s)
    if got != r["sha256"]:
        raise sources.Missing(f"{case['id']}: the downloaded {r['source']} data differ from the case's (sha256 {got}, case {r['sha256']}): "
                              f"rebuild the real cases (`python -m sdlab.ladder.real build`) or fetch the version they were built from")
    return s


def load(case: dict, variant_name: str, full: bool = False) -> dict:
    d = _real(case) if variant_name == "real" else _twin(case)
    return d if full else cut(d, int(case["real"]["train"]))


def cut(d: dict, n: int) -> dict:
    """The first n samples of a data dict (what discovery sees)."""
    out = {**d, "t": d["t"][:n], "levels": {k: v[:n] for k, v in d["levels"].items()},
           "all_levels": {k: v[:n] for k, v in d["all_levels"].items()},
           "injections": [j for j in d.get("injections") or [] if j["t"] < n]}
    if d.get("flows"):
        out["flows"] = {k: v[:n] for k, v in d["flows"].items()}
    if d.get("counters"):
        out["counters"] = {k: v[: n - 1] for k, v in d["counters"].items()}
    return out


def _real(case: dict) -> dict:
    s = _series(case)
    out = {"t": s["t"], "levels": s["levels"], "all_levels": dict(s["levels"]), "eras": [{"start": 0, "label": "Start"}],
           "injections": s.get("injections") or [], "time": s.get("time")}
    if s.get("flows"):
        out["flows"] = s["flows"]
    return out


def _twin(case: dict) -> dict:
    from .. import data as ladder_data
    from ..cases import truth_model

    path = ladder_data.cache_root() / "real" / f"{case['id']}-twin-{case['hash']}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    model = truth_model(case, "twin")
    sim = ladder_data.simulate(model, int(model["seed"]), int(model["steps"]))
    init = {s["id"]: float(s["initial"]) for s in case["model"]["stocks"]}
    all_levels = {k: [init[k]] + list(v) for k, v in sim["all_levels"].items()}
    measured = [s["id"] for s in case["model"]["stocks"] if s.get("measured", True)]
    tw = case["real"]["twin"]
    rng = np.random.default_rng([int(model["seed"]), zlib.crc32(case["id"].encode()), 20261018])
    levels = {}
    for k in measured:
        x = np.asarray(all_levels[k], dtype=float)
        sd = float(tw["rel"].get(k, 0.0)) * np.maximum(np.abs(x), float(tw["floor"].get(k, 0.0)))
        levels[k] = [round(float(v), 4) for v in np.maximum(0.0, x + rng.normal(0.0, 1.0, len(x)) * sd)]
    for k, c in (tw.get("complement") or {}).items():        # a stock the data give as a total minus another (N = 100 - A)
        levels[k] = [round(float(c["total"]) - v, 4) for v in levels[c["of"]]]
    out = {"t": [0] + list(sim["t"]), "levels": levels, "all_levels": all_levels, "eras": [{"start": 0, "label": "Start"}],
           "injections": list(model.get("injections") or []), "counters": sim["counters"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")))
    tmp.replace(path)
    return out
