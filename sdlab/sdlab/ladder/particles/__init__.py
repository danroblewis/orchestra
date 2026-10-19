"""Particle cases: individual particles moving under explicit rules, measured as the count of particles in
each region per step (docs/LADDER.md, "Particle cases"). Tags `physics` and `particles`; shown in the
physics view, scored by their own rules (score.py), never counted in the Tests pass rate.

A particle case is a small YAML file in cases/particles/, named part-<slug>.yaml:

    system: galton                   # systems.py: the rules, the drivers, the mean-field structure
    title: Galton board into draining bins
    level: 20
    tags: [physics, particles, ...]  # physics and particles are added if missing
    tests: one sentence on what the case probes
    seed: 1                          # the run's initial counts and drivers; the fresh run is seed + 1
    params: {pf: 0.6}                # optional: override the system's numbers
    lengths: {short: 300, long: 2000}   # optional
    timeout: 900                     # optional: seconds per item

Variants: `counts-short` and `counts-long` (noise `counts`: the particles' own randomness; there is no
noise-free particle run).

The case dict is the ladder's (cases.py). Its `model` is the mean-field model (meanfield.py): the
truth the equations are scored against on the exact and measured tiers, the reference on the
prediction tier before its refit. Beside it: `physics` (so the physics view, its exclusions from the
Tests totals and its couplings table apply: {system, title, about, params, inputs, couplings,
differs, reference}) and `particles` ({system, tier, equations, regions, mean_field, check, allowed,
differs}). Its data are written where data.py reads them when the case is loaded. The hash covers the
case's content and the particle code that makes the data and the mean-field model (engine.py,
systems.py, meanfield.py, reference.py); the scoring code (score.py here, physics/score.py and
physics/structure.py) is added to the scorer's hash for particle cases only (score_hash).
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
from . import meanfield, reference, systems

HERE = Path(__file__).resolve().parent
ID_RE = re.compile(r"^part-[a-z0-9][a-z0-9-]{0,60}$")
KEYS = {"system", "title", "level", "tags", "tests", "seed", "params", "lengths", "timeout"}
TAGS = ("physics", "particles")
LENGTHS = {"short": 300, "long": 2000}
DATA_CODE = ("engine.py", "systems.py", "meanfield.py", "reference.py")
SCORE_CODE = ("score.py",)
MEASURE_SEED = 1000            # the long run the mean-field numbers are measured on: seed + this
CHECK = {"steps": 300, "runs": 40}
_lock = threading.Lock()
_memo: dict = {}


def folder(cases: Path) -> Path:
    return cases / "particles"


def files(cases: Path) -> dict[str, Path]:
    d = folder(cases)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.yaml")) if ID_RE.match(p.stem)}


def is_particles(case: dict) -> bool:
    return bool(case.get("particles"))


def _code(names, base: Path = HERE) -> str:
    h = hashlib.sha256()
    for n in names:
        h.update((base / n).read_bytes())
    return h.hexdigest()[:16]


def score_hash(base: str) -> str:
    """The scorer's hash for a particle case: the ladder's, the particle scoring code and the physics
    scoring code it grades with."""
    from .. import physics
    return hashlib.sha256((base + _code(SCORE_CODE) + _code(physics.SCORE_CODE, physics.HERE)).encode()).hexdigest()[:16]


def stamp(path: Path) -> tuple[float, int]:
    st = path.stat()
    return st.st_mtime + sum((HERE / n).stat().st_mtime for n in DATA_CODE), st.st_size


def spec(path: Path) -> dict:
    """The case file read and checked."""
    try:
        w = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CaseError(f"{path.name}: not valid YAML: {e}") from None
    if not isinstance(w, dict):
        raise CaseError(f"{path.name}: a particle case is a mapping")
    extra = set(w) - KEYS
    if extra:
        raise CaseError(f"{path.name}: unknown key(s) {', '.join(sorted(extra))} (a particle case has {', '.join(sorted(KEYS))})")
    if w.get("system") not in systems.SYSTEMS:
        raise CaseError(f"{path.name}: system must be one of {', '.join(systems.SYSTEMS)} (got {w.get('system')!r})")
    system = systems.SYSTEMS[w["system"]]
    unknown = set(w.get("params") or {}) - set(system.defaults)
    if unknown:
        raise CaseError(f"{path.name}: {w['system']} has no parameter(s) {', '.join(sorted(unknown))}")
    tags = list(w.get("tags") or [])
    for t in reversed(TAGS):
        if t not in tags:
            tags.insert(0, t)
    return {"system": w["system"], "title": w.get("title") or system.title, "level": int(w.get("level", 20)), "tags": tags,
            "tests": w.get("tests") or "", "seed": int(w.get("seed", 1)), "params": dict(w.get("params") or {}),
            "lengths": {k: int(v) for k, v in (w.get("lengths") or LENGTHS).items()},
            **({"timeout": float(w["timeout"])} if w.get("timeout") is not None else {})}


def build(path: Path) -> dict:
    """{"spec", "case"}: the case dict (module docstring)."""
    return _build(str(path), *stamp(path))


@lru_cache(maxsize=None)
def _build(path_s: str, mtime: float, size: int) -> dict:
    path = Path(path_s)
    w = spec(path)
    system = systems.SYSTEMS[w["system"]]
    p = {**system.defaults, **w["params"]}
    variants = [{"name": f"counts-{ln}", "noise": "counts", "length": ln, "steps": steps} for ln, steps in w["lengths"].items()]
    h = hashlib.sha256(json.dumps({"system": w["system"], "params": p, "seed": w["seed"], "variants": variants}, sort_keys=True).encode()
                       + _code(DATA_CODE).encode()).hexdigest()[:16]
    cid = path.stem
    longest = max(w["lengths"].values())
    dv = derived(cid, h, system, p, w["seed"], longest)
    mf = dv["mean_field"]
    starts = meanfield.start_levels(system, p, w["seed"])
    stocks = [{"id": s, "initial": n} for s, n in zip(system.ids(p), starts)]
    model = {"seed": w["seed"], "stocks": stocks, "flows": mf["flows"], **({"schedule": mf["schedule"]} if mf.get("schedule") else {})}
    scored = system.tier != "prediction"
    case = {"id": cid, "title": w["title"], "level": w["level"], "tags": w["tags"], "tests": w["tests"], "tolerance": {},
            "variants": variants, "hash": h, "model": model,
            "physics": {"system": system.name, "title": system.title, "about": system.about, "params": p, "inputs": list(system.inputs),
                        "couplings": dv["couplings"], "differs": system.differs,
                        "reference": {"how": dv["reference"]["how"], "theta": []}},
            "particles": {"system": system.name, "tier": system.tier, "equations": scored, "regions": len(stocks),
                          "mean_field": mf["how"], "check": dv["check"], "allowed": dv["allowed"], "differs": system.differs,
                          "particles": dv["particles"]},
            **({"timeout": w["timeout"]} if "timeout" in w else {})}
    out = {"spec": dict(w), "case": case}
    ensure(case)
    return out


def _cached(name: str, make):
    from ..data import cache_root
    key = ("file", name)
    if key in _memo:
        return _memo[key]
    path = cache_root() / "particles" / f"{name}.json"
    if path.exists():
        try:
            _memo[key] = json.loads(path.read_text())
            return _memo[key]
        except ValueError:
            pass
    x = make()
    _write(path, x)
    _memo[key] = x
    return x


def derived(cid: str, h: str, system, p: dict, seed: int, longest: int) -> dict:
    """What the case's dict is built from (cached per case and hash): {mean_field, check, reference (flows timed
    over the long run, how), couplings (the mean-field model's present couplings on the case's long run),
    allowed (its weaker ones: allowed in a found model, never required), particles (the mean count of particles)}."""
    from ..physics import structure
    from ..physics.score import LONG

    def make():
        steps = int(p.get("measure_steps") or meanfield.MEASURE_STEPS)
        if system.tier == "exact":
            mf = meanfield.model(system, p)
        else:
            mf = meanfield.model(system, p, meanfield.measure(system, p, seed + MEASURE_SEED, steps), steps)
        chk = meanfield.check(system, p, mf, seed, CHECK["steps"], CHECK["runs"])
        if system.tier == "prediction":
            data = meanfield.simulate(system, p, seed + MEASURE_SEED + 1, reference.FIT_STEPS)
            ref = reference.fitted(system, p, mf, data, LONG)
            ref = {"flows": meanfield.timed(ref, LONG), "how": ref["how"], "moves": ref["moves"], "kappa": ref["kappa"]}
        else:
            ref = {"flows": meanfield.timed(mf, LONG), "how": f"the mean-field model itself ({mf['how']}): the best possible forecasts"
                   + (" on average" if system.tier == "exact" else ", up to the measured numbers' error")}
        d = run_raw(system, p, seed, longest)
        names, V, _ = structure.variables(d, list(system.inputs))
        rec, src, J = structure.found_jacobian(meanfield.timed(mf, LONG), d, list(system.inputs))
        cps = structure.couplings(rec, src, J, V)
        couplings = [[c["receiver"], c["source"], c["sign"], c["shape"]] for c in cps if c["present"]]
        allowed = [[c["receiver"], c["source"]] for c in cps if not c["present"] and c["strength"] > 1e-12]
        total = float(np.mean(np.sum([d["levels"][s] for s in d["levels"]], axis=0)))
        return {"mean_field": mf, "check": chk, "reference": ref, "couplings": couplings, "allowed": allowed, "particles": round(total)}

    return _cached(f"derived-{cid}-{h}", make)


def run_raw(system, p: dict, seed: int, steps: int) -> dict:
    return meanfield.simulate(system, p, seed, steps)


def run(case: dict, seed: int, steps: int) -> dict:
    """One particle run of the case (cached in this process)."""
    key = ("run", case["hash"], seed, steps)
    if key not in _memo:
        system = systems.SYSTEMS[case["particles"]["system"]]
        _memo[key] = run_raw(system, case["physics"]["params"], seed, steps)
    return _memo[key]


def ensure(case: dict) -> None:
    """Write the case's runs (every variant, its seed and the fresh seed) where data.py reads them."""
    from ..data import cache_root
    root = cache_root() / "data"
    seed = int(case["model"]["seed"])
    for v in case["variants"]:
        for s in (seed, seed + 1):
            path = root / f"{case['id']}-{v['name']}-s{s}-{case['hash']}.json"
            if not path.exists():
                _write(path, run(case, s, v["steps"]))


def long_truth(case: dict) -> dict:
    """The particles run for physics/score.py's LONG steps from the fresh run's start (seed + 1)."""
    from ..physics.score import LONG
    seed = int(case["model"]["seed"]) + 1
    return _cached(f"long-{case['id']}-{case['hash']}", lambda: run(case, seed, LONG))


def reference_flows(case: dict) -> list[dict]:
    system = systems.SYSTEMS[case["particles"]["system"]]
    longest = max(v["steps"] for v in case["variants"])
    return derived(case["id"], case["hash"], system, case["physics"]["params"], int(case["model"]["seed"]), longest)["reference"]["flows"]


def reference_grade(case: dict, variant: str, d: dict, fresh: dict) -> dict:
    """The mean-field reference graded on this variant's runs (cached per case, variant and scoring code)."""
    from .score import grade
    return _cached(f"refgrade-{case['id']}-{variant}-{case['hash']}-{score_hash('')}",
                   lambda: grade(case, reference_flows(case), d, fresh, long_truth(case)))


def score_found(case: dict, variant: str, model: dict, flows: list[dict], d: dict, fresh: dict, inferred: dict | None = None) -> dict:
    """The scores of one found model (score.py)."""
    from .score import score as _score
    ref = reference_grade(case, variant, d, fresh)
    return _score(case, model, flows, d, fresh, long_truth(case), ref, inferred)


def _write(path: Path, x) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(x, separators=(",", ":")))
    tmp.replace(path)


def cell(row: dict | None) -> dict:
    """The particle numbers a summary cell carries (api.py)."""
    s = (row or {}).get("scores") or {}
    pt, ph = s.get("particles"), s.get("physics")
    if not pt or not ph:
        return {}
    rb = (ph.get("reference") or {}).get("behaviour") or {}
    sk = lambda b, w, h: ((b.get(w) or {}).get(str(h)) or {}).get("skill")    # noqa: E731
    r20, r100 = sk(rb, "fresh", 20), sk(rb, "fresh", 100)
    f20, f100 = sk(s.get("behaviour") or {}, "fresh", 20), sk(s.get("behaviour") or {}, "fresh", 100)
    clip = lambda f, r: None if f is None or r is None else max(-1.0, f) - r     # noqa: E731  (a skill clipped at -100%, as every mean is)
    return {"pt_tier": pt["tier"], "pt_eq": pt.get("equations"), "pt_near": bool(pt.get("near_reference")),
            "pt_structure": 1 if ph.get("structure_ok") else 0, "pt_cpl": (pt["coupling_right"] / pt["coupling_of"]) if pt.get("coupling_of") else None,
            "pt_gap20": clip(f20, r20), "pt_gap100": clip(f100, r100), "pt_lr": (ph.get("longrun") or {}).get("err"),
            "pt_diverges": bool((ph.get("longrun") or {}).get("diverges")), "ref_fresh20": r20, "ref_fresh100": r100,
            "ref_lr": ((ph.get("reference") or {}).get("longrun") or {}).get("err")}


def aggregate(cells: list[dict]) -> dict:
    """One strategy over the particle cells: {cells, run, pass, equivalent, fail, error, timeout, missing,
    scored (cells whose equations are scored), eq_pass, eq_equivalent, near (cells within 5 points of the
    reference at @20 and @100), structure, couplings, fresh20, fresh100, ref_fresh20, ref_fresh100, gap20,
    gap100 (means of each run's fresh skill, clipped at -100%, minus the reference's), lr, ref_lr,
    diverges, graded, seconds}."""
    out: dict = {"cells": len(cells), **{k: 0 for k in ("pass", "equivalent", "fail", "error", "timeout", "missing")}}
    for c in cells:
        out[c["status"] or "missing"] = out.get(c["status"] or "missing", 0) + 1
    ran = [c for c in cells if c["status"] and c["status"] not in ("error", "timeout") and c.get("pt_tier")]
    out["run"] = sum(1 for c in cells if c["status"])

    def mean(xs):
        xs = [float(x) for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    sc = [c for c in ran if c.get("pt_eq")]
    out["scored"] = len(sc)
    out["eq_pass"] = sum(c["pt_eq"] == "pass" for c in sc)
    out["eq_equivalent"] = sum(c["pt_eq"] == "equivalent" for c in sc)
    out["near"] = sum(bool(c.get("pt_near")) for c in ran)
    out["structure"] = sum(c.get("pt_structure") or 0 for c in ran)
    out["couplings"] = mean([c.get("pt_cpl") for c in ran])
    for k in ("fresh20", "fresh100"):
        out[k] = mean([max(-1.0, c[k]) if c.get(k) is not None else None for c in ran])
    for k in ("ref_fresh20", "ref_fresh100", "ref_lr"):
        out[k] = mean([c.get(k) for c in ran])
    out["gap20"] = mean([c.get("pt_gap20") for c in ran])
    out["gap100"] = mean([c.get("pt_gap100") for c in ran])
    out["lr"] = mean([c.get("pt_lr") for c in ran])
    out["diverges"] = sum(bool(c.get("pt_diverges")) for c in ran)
    out["graded"] = len(ran)
    out["seconds"] = sum(c.get("seconds") or 0.0 for c in cells)
    return out
