"""A real case file (cases/real/<id>.yaml) as a ladder case.

The file is the case format (title, level, tags, tests, stocks, flows, injections: the published
model refitted on the training part, as the truth's place-holder) plus a `real:` block (source,
selector, points, train, sha256, twin, citation). It compiles to an ordinary case dict with:

- `real`: the block, and
- two variants:
  - `real`: the measured series; discovery sees its first `train` samples (noise "none" only so
    that the published model can be run as a truth model: the data are not made by the engine);
  - `twin`: the published model simulated by the engine (noise none) at the series' length and
    sampling, with the measured stocks' measurement error laid on (`real.twin`), so a failure on
    the real data can be told from a method failure (scored like a ladder case against the model).

Its hash covers the compiled model, the `real` block (the series' sha256 included), and the code
that loads, makes and scores the data (this package): a change re-runs the real cases, which are
short (the ladder's score hash, which would re-score every case, is not touched).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from ..caseformat import CaseError, compile_case

ID_RE = re.compile(r"^real-[a-z0-9][a-z0-9-]{0,70}$")
TAG = "real"
HERE = Path(__file__).resolve().parent
CODE = ("case.py", "data.py", "loaders.py", "score.py", "sources.py", "fit.py")


def folder(cases: Path) -> Path:
    return cases / "real"


def files(cases: Path) -> dict[str, Path]:
    d = folder(cases)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.yaml")) if ID_RE.match(p.stem)}


def code_hash() -> str:
    h = hashlib.sha256()
    for name in CODE:
        h.update((HERE / name).read_bytes())
    return h.hexdigest()[:16]


def compile_text(text: str, name: str) -> dict:
    """{"title", "level", "tags", "tests", "model", "real"} of a real case file's text."""
    try:
        w = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise CaseError(f"{name}: not valid YAML: {e}") from None
    if not isinstance(w, dict) or not isinstance(w.get("real"), dict):
        raise CaseError(f"{name}: a real case has a `real:` block")
    real = w.pop("real")
    for key in ("source", "select", "points", "train", "sha256", "twin"):
        if key not in real:
            raise CaseError(f"{name}: real: needs {key}")
    spec = compile_case(yaml.safe_dump(w, sort_keys=False, width=1000), name)
    tags = list(spec.get("tags") or [])
    if TAG not in tags:
        tags.insert(0, TAG)
    return {**spec, "tags": tags, "real": real}


def spec(path: Path) -> dict:
    return compile_text(path.read_text(), path.name)


def build(case_id: str, sp: dict) -> dict:
    """The case dict (cases.load's shape) of a real case's spec."""
    from ..cases import _canonical, engine_hash

    real = sp["real"]
    steps = int(real["points"]) - 1
    variants = [{"name": "real", "noise": "none", "length": "data", "steps": steps, "real": True},
                {"name": "twin", "noise": "none", "length": "data", "steps": steps, "twin": dict(real["twin"])}]
    case = {"id": case_id, "title": sp.get("title") or case_id, "level": sp.get("level", 30), "tags": sp["tags"], "tests": sp.get("tests") or "",
            "tolerance": dict(sp.get("tolerance") or {}), "variants": variants, "model": sp["model"], "real": real}
    h = hashlib.sha256(_canonical({"model": case["model"], "variants": variants, "real": real}))
    h.update(engine_hash().encode() + code_hash().encode())
    return {"spec": sp, "case": {**case, "hash": h.hexdigest()[:16]}}


def stamp(path: Path) -> tuple[float, int]:
    st = path.stat()
    return st.st_mtime, st.st_size


def is_real(case: dict) -> bool:
    return bool(case.get("real"))


def train(case: dict) -> int:
    return int(case["real"]["train"])


def describe(case: dict) -> dict:
    """What a listing shows of a real case: source, points, the training part, units of time, measured flows."""
    r = case["real"]
    return {"source": r["source"], "points": r["points"], "train": r["train"], "time": r.get("time"),
            "measured_flows": r.get("measured_flows") or [], "cite": r.get("cite"), "licence": r.get("licence"), "url": r.get("url"),
            "published": (r.get("published") or {}).get("family")}


def canonical(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))
