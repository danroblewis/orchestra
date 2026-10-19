"""A case's data: made by the ground-truth engine (sdlab/sdtruth.py, unchanged; the case's model is
handed to it), cached on disk.

The cache is $SDLAB_LADDER_CACHE/data (default ~/.cache/sdlab/ladder/data); a file is named by the
case, the variant, the seed and the case's hash (which covers the engine), so a change to any of them
makes new data and old files are never read again. Writes are atomic, so workers that make the same
file at once do no harm.

A run's data: {"t", "levels" (measured stocks), "all_levels" (every stock, hidden ones too, for
grading), "eras" (announced: [{start, label}]), "injections"? (announced), "inputs"? (measured inputs,
{name: value per step}: announced, like injections), "counters" (every flow's amount per step, for the
case checks)}. The fresh run is the same model with seed + 1: the grade of a
found model on a run it was not fitted on (the same as the run itself without noise).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from ..sdtruth import Truth
from .cases import truth_model, variant


def cache_root() -> Path:
    return Path(os.environ.get("SDLAB_LADDER_CACHE") or Path.home() / ".cache" / "sdlab" / "ladder")


def simulate(model: dict, seed: int | None = None, steps: int | None = None) -> dict:
    """Run a truth model (a dict) through the engine: the measured data plus every stock's levels."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "truth.model.json"
        p.write_text(json.dumps(model))
        truth = Truth(p)
        seed = truth.seed if seed is None else seed
        steps = truth.steps if steps is None else steps
        run = truth.run(seed, steps)
        measured = truth.measured(seed, steps)
    out = {"t": measured["t"], "levels": measured["levels"], "all_levels": run["levels"], "eras": measured["eras"], "counters": run["counters"]}
    if measured.get("injections"):
        out["injections"] = measured["injections"]
    if measured.get("inputs"):
        out["inputs"] = measured["inputs"]           # measured inputs (each one's mean over each step): a page input
    return out


def load(case: dict, variant_name: str, fresh: bool = False) -> dict:
    """The case's data in a variant (cached); fresh: the run with the next seed."""
    v = variant(case, variant_name)
    model = truth_model(case, variant_name)
    seed = int(model["seed"]) + (1 if fresh else 0)
    path = cache_root() / "data" / f"{case['id']}-{v['name']}-s{seed}-{case['hash']}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    data = simulate(model, seed, v["steps"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")      # unique per thread: a server loads in several
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)
    return data
