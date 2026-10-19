"""Realistic cases: SD Lab's real-world-style examples (sdlab/examples/sd-*) on the ladder, by reference.

A realistic case is a small YAML file in cases/realistic/, named after the example it references:

    example: sd-saas                     # sdlab/examples/sd-saas/truth.model.json: the truth, seed, schedule
    title: SaaS growth
    level: 20
    tags: [realistic, hidden, coflow, effect]
    tests: one sentence on what the example exercises
    timeout: 900                         # optional: seconds per item (default TIMEOUT); a timeout is not a pass
    lengths: {short: 730, long: 3650}    # optional: default the example's steps and long_steps, as on the bench

Nothing of the example is copied. The case's model is the example's truth.model.json as it is, so
its data come from the same engine with the same seed and length as the examples' bench
(tests/bench/evaluate.py: `--lengths default,long`, counting noise, the fresh run on seed + 1), and
its hash is the example's model and the variants, not this file's wording. Hidden stocks, schedules,
eras, injections, co-flows and effects are the example's own.

For these cases behaviour is the headline: skill@20 and skill@100 as on the bench, and whether a run
**meets the goal** (docs/DISCOVERY-GOAL.md: skill@20 >= 90% and skill@100 >= 80%; an error or a
timeout never does). Exact equation recovery on a 10-17-flow model rarely passes, and is still scored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .caseformat import CaseError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
ID_RE = re.compile(r"^sd-[a-z0-9][a-z0-9-]{0,60}$")
KEYS = {"example", "title", "level", "tags", "tests", "timeout", "lengths", "tolerance"}
TAG = "realistic"
TIMEOUT = 300.0                                   # seconds per item unless the case says otherwise (the watcher's own)
GOAL_SKILL20, GOAL_SKILL100 = 0.9, 0.8            # tests/bench/evaluate.py


def folder(cases: Path) -> Path:
    return cases / "realistic"


def files(cases: Path) -> dict[str, Path]:
    """Every realistic case file by id (the example's id), in name order."""
    d = folder(cases)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.yaml")) if ID_RE.match(p.stem)}


def truth_path(example: str) -> Path:
    return EXAMPLES / example / "truth.model.json"


def spec(path: Path) -> dict:
    """The case dict of a realistic case file: its metadata, and the example's truth model as the model."""
    try:
        w = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CaseError(f"{path.name}: not valid YAML: {e}") from None
    if not isinstance(w, dict):
        raise CaseError(f"{path.name}: a realistic case is a mapping")
    extra = set(w) - KEYS
    if extra:
        raise CaseError(f"{path.name}: unknown key(s) {', '.join(sorted(extra))} (a realistic case has {', '.join(sorted(KEYS))})")
    ex = w.get("example")
    if ex != path.stem:
        raise CaseError(f"{path.name}: example: must be {path.stem!r}, the file's name (got {ex!r})")
    tp = truth_path(ex)
    if not tp.exists():
        raise CaseError(f"{path.name}: no example {ex} ({tp} is missing)")
    model = json.loads(tp.read_text())
    if (model.get("noise") or {}) != {"counts": True}:
        raise CaseError(f"{path.name}: the example's noise is {model.get('noise')!r}; realistic cases take counts")
    tags = list(w.get("tags") or [])
    if TAG not in tags:
        tags.insert(0, TAG)
    steps = int(model["steps"])
    lengths = w.get("lengths") or {"short": steps, "long": int(model.get("long_steps", steps * 10))}   # sdtruth.Truth's default
    out = {"title": w.get("title") or model.get("name") or ex, "level": int(w.get("level", 20)), "tags": tags,
           "tests": w.get("tests") or f"the example {ex} as on the examples' bench", "example": ex,
           "variants": {"noise": ["counts"], "lengths": {k: int(v) for k, v in lengths.items()}},
           "model": {k: model[k] for k in ("seed", "stocks", "flows", "schedule", "injections") if k in model}}
    if w.get("timeout") is not None:
        out["timeout"] = float(w["timeout"])
    if w.get("tolerance"):
        out["tolerance"] = dict(w["tolerance"])
    return out


def stamp(path: Path) -> tuple[float, int]:
    """What decides whether a loaded realistic case is current: the file's and the example's mtime and size."""
    a, b = path.stat(), truth_path(path.stem).stat()
    return a.st_mtime + b.st_mtime, a.st_size + b.st_size


def is_realistic(case: dict) -> bool:
    return bool(case.get("example")) or TAG in (case.get("tags") or [])


def meets_goal(status: str | None, skill20, skill100) -> bool:
    """The bench's goal for one run: no error or timeout, skill@20 >= 90% and skill@100 >= 80%."""
    return status not in (None, "error", "timeout") and skill20 is not None and skill100 is not None \
        and skill20 >= GOAL_SKILL20 and skill100 >= GOAL_SKILL100


def aggregate(cells: list[dict]) -> dict:
    """One strategy over the realistic cells (summary cells, api.py), the bench's headline: {cells, run
    (cells with a result), pass, equivalent, fail, error, timeout, missing, skill20, skill100, fresh20,
    fresh100 (means over the runs graded, each clipped at -100% as on the bench; an error or timeout has
    no skill and is left out), skill20_ci, fresh20_ci (95% bootstrap of the mean over runs), graded,
    goals, goals_fresh (runs meeting the goal; an error or timeout never does), recall, seconds (the
    strategy's own time on the runs it finished), slowest}."""
    from ..bench_stats import bootstrap_mean

    out: dict = {"cells": len(cells), **{k: 0 for k in ("pass", "equivalent", "fail", "error", "timeout", "missing")}}
    for c in cells:
        out[c["status"] or "missing"] = out.get(c["status"] or "missing", 0) + 1
    ran = [c for c in cells if c["status"]]
    out["run"] = len(ran)

    def clipped(key):
        return [max(-1.0, float(c[key])) for c in ran if c.get(key) is not None]

    for key in ("skill20", "skill100", "fresh20", "fresh100"):
        v = clipped(key)
        out[key] = sum(v) / len(v) if v else None
        if key in ("skill20", "fresh20"):
            out[f"{key}_ci"] = bootstrap_mean(v)
    out["graded"] = len(clipped("skill20"))
    out["goals"] = sum(bool(c.get("goal")) for c in ran)
    out["goals_fresh"] = sum(bool(c.get("goal_fresh")) for c in ran)
    rec = [c["recall"] for c in ran if c.get("recall") is not None]
    out["recall"] = sum(rec) / len(rec) if rec else None
    secs = [c["seconds"] for c in ran if c.get("seconds") is not None]
    out["seconds"] = sum(secs)
    out["slowest"] = max(secs) if secs else None
    return out
