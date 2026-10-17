"""Synthetic ground truth for testing one discovery mechanism in isolation.

    from synth import generate
    d = generate(stocks=[...], flows=[...], steps=2000)            # SD Lab model parts, as in truth.model.json
    r = identify(d["stocks"], d["run"], {"eras": d["eras"]})

The data is made by the same engine as the ground-truth examples (sdlab/sdtruth.py, unchanged; a
model is just handed to it), so a test can build the smallest model where a mechanism's answer is
known exactly: one hidden stock, one goal-seeking flow, one announced change. `skill()` grades a
result the way the bench does.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

from sdlab.sdtruth import Truth

_GRADE = Path(__file__).resolve().parent / "bench" / "grade.py"


def generate(stocks: list[dict], flows: list[dict], steps: int, schedule: dict | None = None, seed: int = 1, noise: dict | None = None) -> dict:
    """stocks: {"id", "initial"?, "unit"?, "measured"?}; flows: {"id", "from", "to", "rate"}."""
    model = {"id": "synthetic", "time_unit": "step", "seed": seed, "steps": steps, "noise": {"counts": True} if noise is None else noise,
             "stocks": [{"name": s["id"], "unit": "things", **s} for s in stocks], "flows": [{"name": f["id"], **f} for f in flows]}
    if schedule:
        model["schedule"] = schedule
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "truth.model.json"
        p.write_text(json.dumps(model))
        truth = Truth(p)
        measured = truth.measured(seed, steps)
        everything = truth.run(seed, steps)["levels"]
    shown = [{"id": s["id"], "name": s["name"], "unit": s["unit"]} for s in model["stocks"] if s.get("measured", True)]
    data = {"t": measured["t"], "levels": measured["levels"], "eras": measured["eras"], "all_levels": everything}
    return {"stocks": shown, "run": {"t": data["t"], "levels": data["levels"]}, "eras": measured["eras"], "data": data, "model": model}


def skill(result: dict, d: dict, horizon: int = 20) -> float:
    spec = importlib.util.spec_from_file_location("bench_grade", _GRADE)
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)
    return grade.same_behaviour(result, d["model"], d["data"], horizon=horizon)["skill"]
