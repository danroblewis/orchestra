"""Ladder cases: one JSON file per case in cases/ (NNN-slug.json), a tiny true model plus metadata.

    {"title": "Chain of two", "level": 2, "tags": ["chain"],
     "tests": "a move between two measured stocks and their outside flows are recovered",
     "tolerance": {"rel": 0.1},                                    # optional overrides (score.py)
     "variants": {"noise": ["none", "counts"], "lengths": {"short": 300, "long": 2000}},   # optional
     "model": {"seed": 7, "stocks": [{"id": "A", "initial": 0}],    # the truth.model.json format
               "flows": [{"id": "in", "from": null, "to": "A", "rate": {"form": "constant", "value": 20}}],
               "schedule": {...}, "injections": [...]}}

A case is run in every variant: each noise ("none": the engine's exact flows; "counts": whole things,
Poisson around the rate) at each length. Its id is the file name without .json; its hash covers the
file, the engine (sdlab/sdtruth.py and the equations in sdlab/runner.py) and the code that turns a
case into data (this file and data.py), so a change to any of them makes its results stale.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from functools import lru_cache
from pathlib import Path

from .. import runner as _runner

CASES = Path(__file__).resolve().parent / "cases"
SDLAB = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[0-9]{3}-[a-z0-9][a-z0-9-]{0,60}$")
NOISES = {"none": {}, "counts": {"counts": True}}
LENGTHS = {"short": 300, "long": 2000}


def engine_hash() -> str:
    """The ground-truth engine: sdtruth.py and the equation functions it uses from runner.py."""
    h = hashlib.sha256((SDLAB / "sdtruth.py").read_bytes())
    for fn in (_runner.desired_rate, _runner.multiplier, _runner.effect_value):
        h.update(inspect.getsource(fn).encode())
    return h.hexdigest()[:16]


def _code_hash() -> str:
    h = hashlib.sha256()
    for name in ("cases.py", "data.py"):
        h.update((Path(__file__).resolve().parent / name).read_bytes())
    return h.hexdigest()[:16]


def case_files() -> dict[str, Path]:
    """Every case file by id, in ladder order (by file name)."""
    if not CASES.is_dir():
        return {}
    return {p.stem: p for p in sorted(CASES.glob("*.json")) if ID_RE.match(p.stem)}


def case_ids() -> list[str]:
    return list(case_files())


@lru_cache(maxsize=None)
def _load(path: str, mtime: float, size: int) -> dict:
    p = Path(path)
    raw = p.read_bytes()
    spec = json.loads(raw)
    h = hashlib.sha256(raw)
    h.update(engine_hash().encode() + _code_hash().encode())
    return {"raw_hash": hashlib.sha256(raw).hexdigest()[:16], "hash": h.hexdigest()[:16], "spec": spec}


def load(case_id: str) -> dict:
    """A case: {id, title, level, tags, tests, tolerance, variants: [{name, noise, length, steps}],
    model (the truth model without steps or noise), hash}."""
    p = case_files().get(case_id)
    if p is None:
        raise KeyError(case_id)
    st = p.stat()
    got = _load(str(p), st.st_mtime, st.st_size)
    spec = got["spec"]
    v = spec.get("variants") or {}
    lengths = v.get("lengths") or LENGTHS
    variants = [{"name": f"{n}-{ln}", "noise": n, "length": ln, "steps": int(steps)}
                for n in v.get("noise") or list(NOISES) for ln, steps in lengths.items()]
    return {"id": case_id, "title": spec.get("title") or case_id, "level": spec.get("level", 0), "tags": list(spec.get("tags") or []),
            "tests": spec.get("tests") or "", "tolerance": dict(spec.get("tolerance") or {}), "variants": variants,
            "model": spec["model"], "hash": got["hash"]}


def variant(case: dict, name: str) -> dict:
    for v in case["variants"]:
        if v["name"] == name:
            return v
    raise KeyError(name)


def truth_model(case: dict, variant_name: str) -> dict:
    """The case's true model for a variant, as the engine takes it (truth.model.json)."""
    v = variant(case, variant_name)
    m = case["model"]
    return {"id": case["id"], "name": case["title"], "time_unit": "step", "seed": int(m.get("seed", 1)),
            **{k: m[k] for k in ("schedule", "injections") if m.get(k)},
            "steps": v["steps"], "noise": dict(NOISES[v["noise"]]),
            "stocks": [{"name": s["id"], "unit": "things", **s} for s in m["stocks"]],
            "flows": [{"name": f["id"], **f} for f in m["flows"]]}


def page_stocks(model: dict) -> list[dict]:
    """What discovery is told about the stocks: the measured ones' id, name, unit, final and group."""
    return [{k: s[k] for k in ("id", "name", "unit", "final", "group") if k in s} for s in model["stocks"] if s.get("measured", True)]
