"""Ladder cases: one file per case in cases/, NNN-slug.yaml (the compact format, caseformat.py and
docs/LADDER.md) or NNN-slug.json (the case dict itself), a tiny true model plus metadata:

    {"title": "Chain of two", "level": 2, "tags": ["chain"],
     "tests": "a move between two measured stocks and their outside flows are recovered",
     "tolerance": {"rel": 0.1},                                    # optional overrides (score.py)
     "variants": {"noise": ["none", "counts"], "lengths": {"short": 300, "long": 2000}},   # optional
     "model": {"seed": 7, "stocks": [{"id": "A", "initial": 0}],    # the truth.model.json format
               "flows": [{"id": "in", "from": null, "to": "A", "rate": {"form": "constant", "value": 20}}],
               "schedule": {...}, "injections": [...]}}

A case is run in every variant: each noise ("none": the engine's exact flows; "counts": whole things,
Poisson around the rate) at each length. Its id is the file name without its extension. Its hash
covers what a run is made from, not how the file is written: the compiled case (canonical JSON), the
truth model of every variant, the engine (sdlab/sdtruth.py and the equations in sdlab/runner.py) and
the code that turns a truth model into data (data.py). Rewriting a case in the other format, or
changing this file without changing any truth model, keeps its results current.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from functools import lru_cache
from pathlib import Path

from .. import runner as _runner
from .caseformat import CaseError, compile_case


CASES = Path(__file__).resolve().parent / "cases"
SDLAB = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[0-9]{3}-[a-z0-9][a-z0-9-]{0,60}$")
NOISES = {"none": {}, "counts": {"counts": True}}
LENGTHS = {"short": 300, "long": 2000}
SUFFIXES = (".json", ".yaml")


def engine_hash() -> str:
    """The ground-truth engine: sdtruth.py and the equation functions it uses from runner.py."""
    h = hashlib.sha256((SDLAB / "sdtruth.py").read_bytes())
    for fn in (_runner.desired_rate, _runner.multiplier, _runner.effect_value):
        h.update(inspect.getsource(fn).encode())
    return h.hexdigest()[:16]


def _code_hash() -> str:
    return hashlib.sha256((Path(__file__).resolve().parent / "data.py").read_bytes()).hexdigest()[:16]


def case_files() -> dict[str, Path]:
    """Every case file by id, in ladder order (by file name): NNN-slug.yaml or NNN-slug.json."""
    if not CASES.is_dir():
        return {}
    out: dict[str, Path] = {}
    for p in sorted(CASES.iterdir()):
        if p.suffix in SUFFIXES and ID_RE.match(p.stem):
            if p.stem in out:
                raise CaseError(f"case {p.stem} is written twice: {out[p.stem].name} and {p.name}")
            out[p.stem] = p
    return out


def case_ids() -> list[str]:
    return list(case_files())


def read(path: Path) -> dict:
    """A case file as its case dict (a YAML case compiled; CaseError if it does not compile)."""
    text = path.read_text()
    if path.suffix == ".yaml":
        return compile_case(text, path.name)
    try:
        return json.loads(text)
    except ValueError as e:
        raise CaseError(f"{path.name}: not valid JSON: {e}") from None


def _canonical(x) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":")).encode()


@lru_cache(maxsize=None)
def _load(path: str, mtime: float, size: int) -> dict:
    p = Path(path)
    spec = read(p)
    if not isinstance(spec, dict) or not isinstance(spec.get("model"), dict):
        raise CaseError(f"{p.name}: a case needs a model")
    v = spec.get("variants") or {}
    lengths = v.get("lengths") or LENGTHS
    variants = [{"name": f"{n}-{ln}", "noise": n, "length": ln, "steps": int(steps)}
                for n in v.get("noise") or list(NOISES) for ln, steps in lengths.items()]
    case = {"id": p.stem, "title": spec.get("title") or p.stem, "level": spec.get("level", 0), "tags": list(spec.get("tags") or []),
            "tests": spec.get("tests") or "", "tolerance": dict(spec.get("tolerance") or {}), "variants": variants,
            "model": spec["model"]}
    h = hashlib.sha256(_canonical(spec))
    for x in variants:
        h.update(_canonical(truth_model(case, x["name"])))
    h.update(engine_hash().encode() + _code_hash().encode())
    return {"spec": spec, "case": {**case, "hash": h.hexdigest()[:16]}}


def _get(case_id: str) -> dict:
    p = case_files().get(case_id)
    if p is None:
        raise KeyError(case_id)
    st = p.stat()
    return _load(str(p), st.st_mtime, st.st_size)


def load(case_id: str) -> dict:
    """A case: {id, title, level, tags, tests, tolerance, variants: [{name, noise, length, steps}],
    model (the truth model without steps or noise), hash}."""
    return dict(_get(case_id)["case"])


def spec(case_id: str) -> dict:
    """The case dict a case file holds (compiled, for a YAML case): what a JSON case file would say."""
    return json.loads(json.dumps(_get(case_id)["spec"]))


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
