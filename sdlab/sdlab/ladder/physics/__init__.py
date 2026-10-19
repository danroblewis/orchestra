"""Physics cases: data from physical systems that are not stock-and-flow models, solved in continuous
time by an ODE solver and sampled once per step (docs/LADDER.md, "Physics cases"). Tag `physics`;
scored by their own view and never counted in the Tests pass rate.

A physics case is a small YAML file in cases/physics/, named phys-<slug>.yaml:

    system: draining-tank            # systems.py: the ODE, its drivers, couplings and reference
    title: Draining tank
    level: 20
    tags: [physics, sqrt, input]     # `physics` is added if missing
    tests: one sentence on what the case probes
    seed: 1                          # optional (default 1): the run's initial state and drivers; the fresh run is seed + 1
    params: {k: 0.5}                 # optional: override the system's parameters; [lo, hi] is drawn from the seed
    meas: {rel: 0.02, abs: 0.1}      # the measurement-noise variant's numbers (noise.py's meas)
    lengths: {short: 300, long: 2000}   # optional

Variants: `none` (the sampled solution, to 4 decimals) and `meas` (noise.py's measurement error laid
on it), at each length. There is no counting noise: nothing moves in whole things.

The case dict is the ladder's (cases.py), with `physics` beside it: {system, title, about, params,
inputs, couplings, differs, reference: {how, theta}}. Its `model` is the reference, the best SD
model of the physics fitted on the long noise-free run (reference.py), so the pages draw it as the
model a found one is compared with. Its data are written where data.py reads them (its cache, named
by case, variant, seed and hash) when the case is loaded, so data.load gives the physics' runs to
every reader. The hash covers the case file's content, the system's code (systems.py, ode.py,
reference.py) and noise.py; the scoring code (score.py, structure.py) is added to the scorer's hash
for physics cases only (score_hash), so a change there re-scores their results, not the others'.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from ..caseformat import CaseError
from . import ode, reference, systems

HERE = Path(__file__).resolve().parent
ID_RE = re.compile(r"^phys-[a-z0-9][a-z0-9-]{0,60}$")
KEYS = {"system", "title", "level", "tags", "tests", "seed", "params", "meas", "lengths", "timeout"}
TAG = "physics"
LENGTHS = {"short": 300, "long": 2000}
DATA_CODE = ("systems.py", "ode.py", "reference.py")
SCORE_CODE = ("score.py", "structure.py")
_lock = threading.Lock()
_memo: dict = {}                     # in-process copies of runs and references, by hash


def folder(cases: Path) -> Path:
    return cases / "physics"


def files(cases: Path) -> dict[str, Path]:
    d = folder(cases)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.yaml")) if ID_RE.match(p.stem)}


def is_physics(case: dict) -> bool:
    return bool(case.get("physics"))


def _code(names) -> str:
    h = hashlib.sha256()
    for n in names:
        h.update((HERE / n).read_bytes())
    return h.hexdigest()[:16]


def score_hash(base: str) -> str:
    """The scorer's hash for a physics case: the ladder's, and the physics scoring code."""
    return hashlib.sha256((base + _code(SCORE_CODE)).encode()).hexdigest()[:16]


def stamp(path: Path) -> tuple[float, int]:
    st = path.stat()
    return st.st_mtime + sum((HERE / n).stat().st_mtime for n in DATA_CODE), st.st_size


def spec(path: Path) -> dict:
    """The case file read and checked: {system, title, level, tags, tests, seed, params, meas, lengths}."""
    try:
        w = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CaseError(f"{path.name}: not valid YAML: {e}") from None
    if not isinstance(w, dict):
        raise CaseError(f"{path.name}: a physics case is a mapping")
    extra = set(w) - KEYS
    if extra:
        raise CaseError(f"{path.name}: unknown key(s) {', '.join(sorted(extra))} (a physics case has {', '.join(sorted(KEYS))})")
    if w.get("system") not in systems.SYSTEMS:
        raise CaseError(f"{path.name}: system must be one of {', '.join(systems.SYSTEMS)} (got {w.get('system')!r})")
    tags = list(w.get("tags") or [])
    if TAG not in tags:
        tags.insert(0, TAG)
    meas = dict(w.get("meas") or {})
    if set(meas) - {"rel", "abs"}:
        raise CaseError(f"{path.name}: meas takes rel and abs")
    return {"system": w["system"], "title": w.get("title") or systems.SYSTEMS[w["system"]].title, "level": int(w.get("level", 20)),
            "tags": tags, "tests": w.get("tests") or "", "seed": int(w.get("seed", 1)), "params": dict(w.get("params") or {}),
            "meas": {"rel": float(meas.get("rel", 0.02)), "abs": float(meas.get("abs", 0.0))},
            "lengths": {k: int(v) for k, v in (w.get("lengths") or LENGTHS).items()},
            **({"timeout": float(w["timeout"])} if w.get("timeout") is not None else {})}


def build(path: Path) -> dict:
    """{"spec", "case"}: the case dict (module docstring), its data written where data.py reads them."""
    return _build(str(path), *stamp(path))


@lru_cache(maxsize=None)
def _build(path_s: str, mtime: float, size: int) -> dict:
    path = Path(path_s)
    w = spec(path)
    system = systems.SYSTEMS[w["system"]]
    try:
        p = ode.params(system, w["params"], w["seed"])
    except ValueError as e:
        raise CaseError(f"{path.name}: {e}") from None
    variants = [{"name": f"{n}-{ln}", "noise": n, "length": ln, "steps": steps,
                 **({"observe": {"kind": "meas", "rel": w["meas"]["rel"], "abs": w["meas"]["abs"]}} if n == "meas" else {})}
                for n in ("none", "meas") for ln, steps in w["lengths"].items()]
    from ..noise import code_hash as noise_code
    h = hashlib.sha256(json.dumps({"system": w["system"], "params": p, "seed": w["seed"], "variants": variants}, sort_keys=True).encode()
                       + _code(DATA_CODE).encode() + noise_code().encode()).hexdigest()[:16]
    cid = path.stem
    longest = max(w["lengths"].values())
    ref = _reference(cid, h, system, p, w["seed"], longest)
    stocks = [dict(s) for s in system.stocks]
    case = {"id": cid, "title": w["title"], "level": w["level"], "tags": w["tags"], "tests": w["tests"], "tolerance": {},
            "variants": variants, "hash": h,
            "model": {"seed": w["seed"], "stocks": stocks, "flows": ref["flows"]},
            "physics": {"system": system.name, "title": system.title, "about": system.about, "params": p, "inputs": list(system.inputs),
                        "couplings": [list(c) for c in system.couplings], "differs": system.differs,
                        "reference": {"how": ref["how"], "theta": ref["theta"]}},
            **({"timeout": w["timeout"]} if "timeout" in w else {})}
    out = {"spec": {k: v for k, v in w.items()}, "case": case}
    ensure(case)
    return out


def run(case: dict, seed: int, steps: int) -> dict:
    """One clean run of the case's system (cached in this process)."""
    key = ("run", case["hash"], seed, steps)
    if key not in _memo:
        system = systems.SYSTEMS[case["physics"]["system"]]
        _memo[key] = ode.simulate(system, case["physics"]["params"], seed, steps)
    return _memo[key]


def _reference(cid: str, h: str, system, p: dict, seed: int, steps: int) -> dict:
    from ..data import cache_root
    key = ("ref", h)
    if key in _memo:
        return _memo[key]
    path = cache_root() / "physics" / f"ref-{cid}-{h}.json"
    if path.exists():
        try:
            _memo[key] = json.loads(path.read_text())
            return _memo[key]
        except ValueError:
            pass
    d = ode.simulate(system, p, seed, steps)
    _memo[("run", h, seed, steps)] = d
    r = reference.fit(system, p, d)
    _write(path, r)
    _memo[key] = r
    return r


def ensure(case: dict) -> None:
    """Write the case's runs (every variant, its seed and the fresh seed) where data.py reads them,
    unless they are there: data.load then gives the physics' data (a noise variant's noise laid on by
    data.load itself, from noise.py)."""
    from ..data import cache_root
    root = cache_root() / "data"
    seed = int(case["model"]["seed"])
    for v in case["variants"]:
        for s in (seed, seed + 1):
            path = root / f"{case['id']}-{v['name']}-s{s}-{case['hash']}.json"
            if not path.exists():
                _write(path, run(case, s, v["steps"]))


def long_truth(case: dict) -> dict:
    """The physics continued for score.LONG steps from the fresh run's start (the fresh seed): the long run's truth."""
    from ..data import cache_root
    from .score import LONG
    seed = int(case["model"]["seed"]) + 1
    key = ("long", case["hash"])
    if key in _memo:
        return _memo[key]
    path = cache_root() / "physics" / f"long-{case['id']}-{case['hash']}.json"
    if path.exists():
        try:
            _memo[key] = json.loads(path.read_text())
            return _memo[key]
        except ValueError:
            pass
    d = run(case, seed, LONG)
    _write(path, d)
    _memo[key] = d
    return d


def sampling(case: dict) -> list[list[str]]:
    """The couplings only the physics' exact one-step map has, not its ODE (structure.py): [[receiver,
    source]], from the case's long noise-free run (cached per case and scoring code; none for a
    switching system)."""
    from ..data import cache_root
    from . import structure
    key = ("sampling", case["hash"], _code(SCORE_CODE))
    if key in _memo:
        return _memo[key]
    path = cache_root() / "physics" / f"sampling-{case['id']}-{case['hash']}-{key[2]}.json"
    if path.exists():
        try:
            _memo[key] = json.loads(path.read_text())
            return _memo[key]
        except ValueError:
            pass
    system = systems.SYSTEMS[case["physics"]["system"]]
    out: list[list[str]] = []
    if not system.hybrid:
        p, seed = case["physics"]["params"], int(case["model"]["seed"])
        steps = max(v["steps"] for v in case["variants"])
        d = run(case, seed, steps)
        lv = systems.levels_for(system, p)
        x = np.array([d["levels"][k] for k in system.ids], dtype=float)
        if lv:
            x = x - lv(np.zeros((len(system.ids), 1)))
        J, pick = structure.sampled_jacobian(system, p, ode.drive(system, p, seed, steps), x, np.arange(1, steps + 1, dtype=float))
        names, V, _ = structure.variables(d, system.inputs)
        declared = {(a, b) for a, b, *_ in system.couplings}
        out = [[c["receiver"], c["source"]] for c in structure.couplings(system.ids, names, J, V[:, pick])
               if c["present"] and (c["receiver"], c["source"]) not in declared]
    _write(path, out)
    _memo[key] = out
    return out


def reference_grade(case: dict, variant: str, clean: dict, fresh: dict) -> dict:
    """The reference graded on this variant's runs (cached per case, variant and scoring code)."""
    from ..data import cache_root
    from .score import grade
    key = ("grade", case["hash"], variant, _code(SCORE_CODE))
    if key in _memo:
        return _memo[key]
    path = cache_root() / "physics" / f"refgrade-{case['id']}-{variant}-{case['hash']}-{key[3]}.json"
    if path.exists():
        try:
            _memo[key] = json.loads(path.read_text())
            return _memo[key]
        except ValueError:
            pass
    g = grade(case, case["model"]["flows"], clean, fresh, long_truth(case), sampling=sampling(case))
    _write(path, g)
    _memo[key] = g
    return g


def score_found(case: dict, variant: str, flows: list[dict], d: dict, fresh: dict, inferred: dict | None = None) -> dict:
    """The scores of one found model (score.py), on the data data.load gave (a noisy variant is graded on
    the clean run underneath, its `clean`)."""
    from .score import score as _score
    clean, fr = d.get("clean") or d, fresh.get("clean") or fresh
    ref = reference_grade(case, variant, clean, fr)
    return _score(case, flows, clean, fr, long_truth(case), ref, inferred if d.get("t") == clean.get("t") else None, sampling(case))


def _write(path: Path, x) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(x, separators=(",", ":")))
    tmp.replace(path)


# ---- the summary ----

def cell(row: dict | None) -> dict:
    """The physics numbers a summary cell carries (api.py): structure agreement, shape, long run and
    the reference's."""
    s = (row or {}).get("scores") or {}
    ph = s.get("physics")
    if not ph:
        return {}
    ref = ph.get("reference") or {}
    rb = ref.get("behaviour") or {}
    sk = lambda b, w, h: ((b.get(w) or {}).get(str(h)) or {}).get("skill")    # noqa: E731
    r20, gap = sk(rb, "fresh", 20), ph.get("gap20")
    if gap is not None and r20 is not None:            # the gap of the run's skill clipped at -100%, as every mean of skills is
        gap = max(-1.0, gap + r20) - r20
    return {"ph_structure": 1 if ph.get("structure_ok") else 0, "ph_right": s.get("right"), "ph_of": s.get("of"),
            "ph_spurious": len(ph.get("spurious") or []), "ph_shape": (ph["shape_right"] / ph["shape_of"]) if ph.get("shape_of") else None,
            "ph_lr": (ph.get("longrun") or {}).get("err"), "ph_lr_mean": (ph.get("longrun") or {}).get("mean_err"),
            "ph_diverges": bool((ph.get("longrun") or {}).get("diverges")), "ph_gap20": gap,
            "ref_fresh20": r20, "ref_fresh100": sk(rb, "fresh", 100), "ref_lr": (ref.get("longrun") or {}).get("err")}


def aggregate(cells: list[dict]) -> dict:
    """One strategy over the physics cells: {cells, run, pass, fail, error, timeout, missing, structure
    (runs whose coupling graph and signs agree), couplings (mean share of the physics' couplings right),
    shape (mean share with the physics' shape), fresh20, fresh100 (means, each clipped at -100%),
    ref_fresh20, gap20 (mean fresh@20, each clipped at -100%, minus the reference's), lr, ref_lr (mean long-run error), diverges, seconds}."""
    out: dict = {"cells": len(cells), **{k: 0 for k in ("pass", "equivalent", "fail", "error", "timeout", "missing")}}
    for c in cells:
        out[c["status"] or "missing"] = out.get(c["status"] or "missing", 0) + 1
    ran = [c for c in cells if c["status"] and c["status"] not in ("error", "timeout") and c.get("ph_of") is not None]
    out["run"] = sum(1 for c in cells if c["status"])

    def mean(xs):
        xs = [float(x) for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    out["structure"] = sum(c.get("ph_structure") or 0 for c in ran)
    out["couplings"] = mean([c["ph_right"] / c["ph_of"] if c.get("ph_of") else None for c in ran])
    out["shape"] = mean([c.get("ph_shape") for c in ran])
    for k in ("fresh20", "fresh100"):
        out[k] = mean([max(-1.0, c[k]) if c.get(k) is not None else None for c in ran])
    out["ref_fresh20"] = mean([c.get("ref_fresh20") for c in ran])
    out["gap20"] = mean([c.get("ph_gap20") for c in ran])
    out["lr"] = mean([c.get("ph_lr") for c in ran])
    out["ref_lr"] = mean([c.get("ref_lr") for c in ran])
    out["diverges"] = sum(bool(c.get("ph_diverges")) for c in ran)
    out["graded"] = len(ran)
    out["seconds"] = sum(c.get("seconds") or 0.0 for c in cells)
    return out
