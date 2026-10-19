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
covers what a run is made from, not how the file is written or described: the compiled model,
variants and tolerance (canonical JSON; not the title, level, tags or tests sentence), the truth
model of every variant (without its id and name), the engine (sdlab/sdtruth.py and the equations in sdlab/runner.py) and
the code that turns a truth model into data (data.py). Rewriting a case in the other format, or
changing this file without changing any truth model, keeps its results current.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

from .. import runner as _runner
from . import draws as _draws
from . import realistic as _realistic
from .caseformat import CaseError, compile_case


CASES = Path(__file__).resolve().parent / "cases"
SDLAB = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[0-9]{3}-[a-z0-9][a-z0-9-]{0,60}$")
NOISES = {"none": {}, "counts": {"counts": True}}
LENGTHS = {"short": 300, "long": 2000}
SUFFIXES = (".json", ".yaml")


# The engine and data.py as they were before the features added on 2026-10-18 (measured inputs,
# sub-steps, ceilings, exact flows, compiled delays). A case that uses none of them is hashed with
# these, so its results stay current: tests/test_engine_additive.py proves that the engine still gives
# every such case bit-identical data (tests/engine_outputs.sha256, recorded before the change). A case
# that uses one is hashed with the code as it is now.
LEGACY_ENGINE, LEGACY_DATA = "d9f38a8c64cdac28", "39b9a5b7cf6a49b6"


def uses_added_features(model: dict) -> bool:
    """Does a case's model use any engine feature added on 2026-10-18?"""
    return (model.get("dt") is not None or bool(model.get("inputs")) or any(s.get("max") is not None for s in model.get("stocks") or [])
            or any(f.get("exact") or f.get("delay") for f in model.get("flows") or []))


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
    return dict(_listing(str(CASES), CASES.stat().st_mtime_ns))


@lru_cache(maxsize=8)
def _listing(folder: str, mtime_ns: int) -> dict[str, Path]:
    """The folder's case files (a file added, removed or renamed changes the folder's mtime)."""
    out: dict[str, Path] = {}
    for p in sorted(Path(folder).iterdir()):
        if p.suffix in SUFFIXES and ID_RE.match(p.stem):
            if p.stem in out:
                raise CaseError(f"case {p.stem} is written twice: {out[p.stem].name} and {p.name}")
            out[p.stem] = p
    return out


def realistic_files() -> dict[str, Path]:
    """The realistic cases (cases/realistic/sd-*.yaml, realistic.py): the examples, by reference."""
    d = _realistic.folder(CASES)
    return dict(_realistic_listing(str(d), d.stat().st_mtime_ns)) if d.is_dir() else {}


@lru_cache(maxsize=8)
def _realistic_listing(folder: str, mtime_ns: int) -> dict[str, Path]:
    return _realistic.files(Path(folder).parent)


def _all_files() -> dict[str, Path]:
    return {**case_files(), **realistic_files()}


def is_realistic(case_id: str) -> bool:
    """Is this one of the realistic cases (an example by reference), not a test case?"""
    return split(case_id)[0] in realistic_files()


def case_ids() -> list[str]:
    """Every case, simplest first: by level, then by id. (Ids are stable names in the order the cases
    were written; a basic case added later still sorts among the basics.) A parametric case is listed
    as its draws, NNN-slug#1 .. NNN-slug#N (draws.py). The realistic cases (realistic.py) are listed
    too, by their level (20: after the tests)."""
    files = _all_files()
    out = []
    for cid, p in files.items():
        n, level = _safe_count(p), _level(p)
        out += [(level, cid, i, f"{cid}#{i}") for i in range(1, n + 1)] if n else [(level, cid, 0, cid)]
    return [x[3] for x in sorted(out)]


def known(case_id: str) -> bool:
    """Is this a case id (a case, or a draw of a parametric case)?"""
    try:
        base, i = split(case_id)
        p = _all_files().get(base)
        return p is not None and (1 <= i <= _safe_count(p) if i else not _safe_count(p))
    except (CaseError, KeyError, ValueError):
        return False


def split(case_id: str) -> tuple[str, int]:
    """(file id, draw number; 0 for a case that is not a draw)."""
    if "#" not in case_id:
        return case_id, 0
    base, i = case_id.split("#", 1)
    if not i.isdigit():
        raise KeyError(case_id)
    return base, int(i)


def parametric() -> dict[str, dict]:
    """The parametric cases: {file id: {title, level, tags, tests, draws: [draw ids]}} in ladder order."""
    out: dict[str, dict] = {}
    for cid in case_ids():
        base, i = split(cid)
        if i:
            c = load(cid)
            g = out.setdefault(base, {k: c[k] for k in ("title", "level", "tags", "tests")} | {"draws": []})
            g["draws"].append(cid)
    return out


def _safe_count(path: Path) -> int:
    """How many draws (0 for an ordinary case, and for a parametric case whose draws do not parse:
    it is then listed under its file id, and loading it reports the mistake)."""
    try:
        return _draw_count(path)
    except CaseError:
        return 0


def _draw_count(path: Path) -> int:
    if path.suffix != ".yaml" or path.parent.name == "realistic":
        return 0
    st = path.stat()
    return _count(str(path), st.st_mtime, st.st_size)


@lru_cache(maxsize=None)
def _count(path: str, mtime: float, size: int) -> int:
    p = Path(path)
    return _draws.count(p.read_text(), p.name)


def _level(path: Path) -> int:
    st = path.stat()
    return _level_of(str(path), st.st_mtime, st.st_size)


@lru_cache(maxsize=None)
def _level_of(path_s: str, mtime: float, size: int) -> int:
    path = Path(path_s)
    try:
        if _safe_count(path):
            text = path.read_text()
            ss = _draws.sites(text, path.name)
            return int(compile_case(_draws.resolve(text, ss, [x.lo for x in ss]), path.name).get("level") or 0)
        return int(read(path).get("level") or 0)
    except Exception:                                             # noqa: BLE001  (a broken case sorts last; check reports it)
        return 10**6


def read(path: Path) -> dict:
    """A case file as its case dict (a YAML case compiled; CaseError if it does not compile). A
    parametric case has no single case dict: read a draw with load / spec."""
    if path.parent.name == "realistic":
        return _realistic.spec(path)
    text = path.read_text()
    if path.suffix == ".yaml":
        if _draws.count(text, path.name):
            raise CaseError(f"{path.name}: a parametric case (draw(...)): its draws are the cases")
        return compile_case(text, path.name)
    try:
        return json.loads(text)
    except ValueError as e:
        raise CaseError(f"{path.name}: not valid JSON: {e}") from None


def _canonical(x) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":")).encode()


def _build(case_id: str, spec: dict) -> dict:
    if not isinstance(spec, dict) or not isinstance(spec.get("model"), dict):
        raise CaseError(f"{case_id}: a case needs a model")
    v = spec.get("variants") or {}
    lengths = v.get("lengths") or LENGTHS
    variants = [{"name": f"{n}-{ln}", "noise": n, "length": ln, "steps": int(steps)}
                for n in v.get("noise") or list(NOISES) for ln, steps in lengths.items()]
    case = {"id": case_id, "title": spec.get("title") or case_id, "level": spec.get("level", 0), "tags": list(spec.get("tags") or []),
            "tests": spec.get("tests") or "", "tolerance": dict(spec.get("tolerance") or {}), "variants": variants,
            "model": spec["model"], **{k: spec[k] for k in ("example", "timeout") if k in spec}}
    return {"spec": spec, "case": {**case, "hash": case_hash(case)}}


def case_hash(case: dict) -> str:
    """What a run is made from and scored against: the model, the variants, the tolerance and each
    variant's truth model (without its id and name), the engine and data.py. Not the id, title,
    level, tags or tests sentence: rewording a case keeps its results current."""
    h = hashlib.sha256(_canonical({"model": case["model"], "variants": case["variants"], "tolerance": case["tolerance"]}))
    for x in case["variants"]:
        tm = truth_model(case, x["name"])
        h.update(_canonical({k: v for k, v in tm.items() if k not in ("id", "name")}))
    if uses_added_features(case["model"]):
        h.update(engine_hash().encode() + _code_hash().encode())
    else:
        h.update(LEGACY_ENGINE.encode() + LEGACY_DATA.encode())
    return h.hexdigest()[:16]


@lru_cache(maxsize=None)
def _load(path: str, mtime: float, size: int) -> dict:
    p = Path(path)
    return _build(p.stem, read(p))


@lru_cache(maxsize=None)
def _load_draw(path: str, mtime: float, size: int, i: int) -> dict:
    """Draw i of a parametric case: the first attempt whose numbers pass the case checks (the
    accepted attempt is remembered in $SDLAB_LADDER_CACHE/draws, so checks run once per draw)."""
    from . import checks
    from .data import cache_root

    p = Path(path)
    text = p.read_text()
    ss = _draws.sites(text, p.name)
    n = _draws.count(text, p.name)
    seed = _draws.seed(text)
    case_id = f"{p.stem}#{i}"
    key = hashlib.sha256(text.encode() + engine_hash().encode() + _code_hash().encode()
                         + (Path(__file__).resolve().parent / "checks.py").read_bytes()
                         + (Path(__file__).resolve().parent / "draws.py").read_bytes()).hexdigest()[:16]
    memo = cache_root() / "draws" / f"{p.stem}-{i}-{key}.json"
    known_ = None
    if memo.exists():
        try:
            known_ = json.loads(memo.read_text())
        except ValueError:
            known_ = None
    rejected = list((known_ or {}).get("rejected") or [])
    attempts = [known_["attempt"]] if known_ and isinstance(known_.get("attempt"), int) else range(_draws.ATTEMPTS)
    built, problems = None, []
    for attempt in attempts:
        vals = _draws.values(ss, seed, i, attempt)
        built = _build(case_id, compile_case(_draws.resolve(text, ss, vals), p.name))
        built["case"]["draw"] = {"base": p.stem, "i": i, "of": n, "seed": seed, "attempt": attempt,
                                 "values": _draws.describe(text, ss, vals)}
        if known_ is not None:
            problems = list(known_.get("problems") or [])
            break
        try:
            problems = checks.problems(built["case"])
        except (ArithmeticError, ValueError) as e:                 # the run blew up (overflow): not bounded
            problems = [f"the run fails: {type(e).__name__}: {e}"]
        if not problems:
            break
        rejected.append({"attempt": attempt, "values": {d["label"]: d["value"] for d in built["case"]["draw"]["values"]}, "problems": problems})
    if known_ is None:
        rejected = [r for r in rejected if r["attempt"] != built["case"]["draw"]["attempt"]]
        memo.parent.mkdir(parents=True, exist_ok=True)
        tmp = memo.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")   # threads in one server must not share it
        tmp.write_text(json.dumps({"attempt": built["case"]["draw"]["attempt"], "rejected": rejected, "problems": problems}))
        tmp.replace(memo)
    built["case"]["draw"].update(rejected=rejected, problems=problems)
    return built


def _get(case_id: str) -> dict:
    base, i = split(case_id)
    p = _all_files().get(base)
    if p is None or not known(case_id):
        raise KeyError(case_id)
    if p.parent.name == "realistic":
        return _load(str(p), *_realistic.stamp(p))
    st = p.stat()
    return _load_draw(str(p), st.st_mtime, st.st_size, i) if i else _load(str(p), st.st_mtime, st.st_size)


def load(case_id: str) -> dict:
    """A case: {id, title, level, tags, tests, tolerance, variants: [{name, noise, length, steps}],
    model (the truth model without steps or noise), hash}; a draw also has draw: {base, i, of, seed,
    attempt, values: [{label, value, lo, hi, log, int, line}], rejected: [{attempt, values, problems}],
    problems} (problems: what is still wrong when no attempt passed the checks)."""
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
            **{k: m[k] for k in ("schedule", "injections", "dt", "inputs") if m.get(k)},
            "steps": v["steps"], "noise": dict(NOISES[v["noise"]]),
            "stocks": [{"name": s["id"], "unit": "things", **s} for s in m["stocks"]],
            "flows": [{"name": f["id"], **f} for f in m["flows"]]}


def page_stocks(model: dict) -> list[dict]:
    """What discovery is told about the stocks: the measured ones' id, name, unit, final and group."""
    return [{k: s[k] for k in ("id", "name", "unit", "final", "group") if k in s} for s in model["stocks"] if s.get("measured", True)]
