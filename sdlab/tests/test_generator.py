"""The procedural generator of ground-truth models (tests/bench/generator.py): deterministic, every
model passing the checks the hand-made examples pass, the held-out families kept out of development,
and the sealed pool refused unless a change is being adopted."""

import functools
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sdlab.discovery.simulate import Model
from sdlab.server import validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "bench"))
import generated  # noqa: E402
import generator  # noqa: E402
from grade import key_of, truth_by_time  # noqa: E402

# a few models of each pool (generation takes seconds each); sealed 0 has the held-out family
SAMPLE = [("dev", 3), ("dev", 6), ("sealed", 0)]


@functools.lru_cache(maxsize=None)
def model(pool: str, index: int) -> dict:
    return generator.generate(pool, index)


def test_the_generator_is_deterministic():
    a = model("dev", 3)
    again = generator.generate("dev", 3)
    assert json.dumps(a, sort_keys=True) == json.dumps({**again, "generated": {**again["generated"], "seconds": a["generated"]["seconds"]}}, sort_keys=True)
    assert a["id"] == "gen1-dev-00003" == generator.model_id("dev", 3)
    assert a["generated"]["motifs"] and set(a["generated"]["motifs"]) <= set(generator.FAMILIES)
    assert json.dumps(model("dev", 6)) != json.dumps(a)


@pytest.mark.parametrize("pool,index", SAMPLE)
def test_a_generated_model_passes_the_examples_checks(pool, index):
    """As tests/test_sd_examples.py checks every example: a valid model, sane over fifty times its
    default length (finite, never negative, bounded, everything accounted for), still exercising
    its model late in that run, 3-15 measured stocks, and an answer key."""
    m = model(pool, index)
    assert validate({**m, "stocks": [{k: v for k, v in s.items() if k != "measured"} for s in m["stocks"]]}) == []
    t = generator.truth(m)
    assert 3 <= len(t.measured_ids) <= 15
    n = t.steps * 50
    r = t.run(steps=n)
    for s, v in r["levels"].items():
        assert len(v) == n and all(math.isfinite(x) and x >= 0 for x in v), s
        assert max(v) <= 5 * max(v[: t.steps]) + 50, s
        w = len(v) // 10
        early, late = v[w: 2 * w], v[-w:]
        step = lambda a: statistics.pstdev([b - x for x, b in zip(a, a[1:])])  # noqa: E731
        if step(early):
            assert step(late) >= 0.8 * step(early) and statistics.pstdev(late) >= 0.5 * statistics.pstdev(early), s
    start = {s["id"]: s.get("initial") or 0 for s in m["stocks"]}
    for s in t.stock_ids:
        net = sum(sum(r["counters"][f["id"]]) for f in m["flows"] if f.get("to") == s) \
            - sum(sum(r["counters"][f["id"]]) * float(f.get("ratio") or 1) for f in m["flows"] if f.get("from") == s) \
            - sum(sum(r["counters"][f["id"]]) * float(u.get("per") or 0) for f in m["flows"] for u in f.get("uses") or [] if u.get("stock") == s)
        assert abs(start[s] + net - r["levels"][s][-1]) < 1e-6 * max(1, abs(net)) + 1, s
    assert key_of(t.truth())["rel"] or key_of(t.truth())["outside"]
    assert generator.check(m, ()) == []


@pytest.mark.parametrize("pool,index", SAMPLE)
def test_the_grader_steps_a_generated_model_as_the_engine_does(pool, index):
    """Without noise, the discovery simulator (which the grader runs) follows the engine's own run."""
    m = {**model(pool, index), "noise": {}}
    t = generator.truth(m)
    steps = min(t.steps, 400)
    engine = t.run(steps=steps)["levels"]
    flows, _ = truth_by_time(m, list(range(1, steps + 1)))
    sim, L = Model(flows, t.stock_ids), np.array([[float(s.get("initial") or 0)] for s in m["stocks"]])
    for k in range(1, steps + 1):
        L = sim.step(L, np.array([float(k)]))
        for i, s in enumerate(t.stock_ids):
            assert abs(L[i, 0] - engine[s][k - 1]) <= 1e-3 * max(1.0, abs(engine[s][k - 1])), (s, k)


def test_the_held_out_families_never_reach_the_development_pool():
    for i in range(500):
        assert not generator.held_out(generator.plan("dev", i)["families"]), i
    sealed = [generator.plan("sealed", i)["families"] for i in range(0, 40, 2)]
    assert all(generator.held_out(f) for f in sealed)
    seen = {h for f in sealed for h in generator.held_out(f)}
    assert seen >= {*generator.HELD_OUT_FAMILIES, *("+".join(sorted(c)) for c in generator.HELD_OUT_COMBOS)}
    assert "effect_peaked" in model("sealed", 0)["generated"]["motifs"]
    with pytest.raises(ValueError):
        generator.plan("dev", 0, ("effect_peaked",))
    with pytest.raises(ValueError):
        generator.plan("sealed", generator.SEALED_SIZE)


def test_the_sealed_pool_is_refused_unless_adopting():
    a = SimpleNamespace(pool="sealed", i_am_adopting=False, label="")
    assert generated.refuse_sealed(a)
    assert generated.refuse_sealed(SimpleNamespace(pool="sealed", i_am_adopting=True, label=""))
    assert generated.refuse_sealed(SimpleNamespace(pool="sealed", i_am_adopting=True, label="adopt X")) is None
    assert generated.refuse_sealed(SimpleNamespace(pool="dev", i_am_adopting=False, label="")) is None
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "bench" / "evaluate.py"), "--generated", "1", "--pool", "sealed"],
                       capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert p.returncode == 2 and "Refused" in p.stderr and "--i-am-adopting" in p.stderr
