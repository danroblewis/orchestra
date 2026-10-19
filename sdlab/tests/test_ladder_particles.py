"""Particle cases (sdlab/ladder/particles): runs that are deterministic and fast, a mean-field model that
tracks the particles' average within sampling error where the case scores equations (and does not
where it is prediction only), the mean-field model passing its own scoring, and particle runs kept
out of the Tests totals."""

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from sdlab.ladder import api, catalog, data, particles, runner, store
from sdlab.ladder import cases as casemod
from sdlab.ladder.particles import engine, meanfield, systems

PART = Path(casemod.__file__).resolve().parent / "cases" / "particles"
IDS = sorted(p.stem for p in PART.glob("part-*.yaml"))
FAST = ["part-conveyor-bottleneck", "part-galton-board", "part-reacting-particles", "part-stirred-chambers"]   # cheap to build from scratch


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def test_the_particle_cases_cover_every_system_and_are_tagged_physics_and_particles():
    assert len(IDS) >= 6
    w = {i: particles.spec(PART / f"{i}.yaml") for i in IDS}
    assert sorted(x["system"] for x in w.values()) == sorted(systems.SYSTEMS)
    for x in w.values():
        assert {"physics", "particles"} <= set(x["tags"]) and x["tests"]
    assert any(len(systems.SYSTEMS[x["system"]].ids({**systems.SYSTEMS[x["system"]].defaults, **x["params"]})) >= 30 for x in w.values()), "one large case"
    assert {systems.SYSTEMS[x["system"]].tier for x in w.values()} == {"exact", "measured", "prediction"}
    assert all(casemod.is_physics(i) and casemod.is_particles(i) for i in IDS)


@pytest.mark.parametrize("name", sorted(systems.SYSTEMS))
def test_a_run_is_fixed_by_its_seed_and_a_short_run_is_the_start_of_a_long_one(name):
    s = systems.SYSTEMS[name]
    p = dict(s.defaults)
    a, b = meanfield.simulate(s, p, 3, 120), meanfield.simulate(s, p, 3, 120)
    assert a == b
    short = meanfield.simulate(s, p, 3, 60)
    assert all(short["levels"][k] == a["levels"][k][:60] for k in a["levels"])
    assert short.get("inputs", {}) == {k: v[:60] for k, v in a.get("inputs", {}).items()}
    other = meanfield.simulate(s, p, 4, 120)
    assert other["levels"] != a["levels"], "another seed: other initial counts and drivers"
    assert all(isinstance(x, int) and x >= 0 for v in a["levels"].values() for x in v), "whole particles"


def test_thousands_of_particles_over_2000_steps_in_seconds():
    s = systems.SYSTEMS["stirred-chambers"]
    t0 = time.perf_counter()
    d = meanfield.simulate(s, dict(s.defaults), 1, 2000)
    took = time.perf_counter() - t0
    total = np.sum([d["levels"][k] for k in d["levels"]], axis=0)
    assert total.mean() > 2000 and took < 10, (total.mean(), took)


def test_hops_move_at_their_probabilities_and_a_gate_caps_them():
    rng = np.random.default_rng(0)
    h = engine.Hops(3, [(0, 1, 0.2), (0, engine.OUT, 0.1), (1, 2, 0.5)])
    reg = np.zeros(200_000, dtype=np.int32)
    new = h.step(reg, rng)
    assert np.mean(new == 1) == pytest.approx(0.2, abs=0.005) and np.mean(new == engine.OUT) == pytest.approx(0.1, abs=0.004)
    g = engine.Hops(2, [(0, 1, 0.5)], gates={0: 7})
    assert int(np.sum(g.step(np.zeros(1000, dtype=np.int32), rng) == 1)) == 7


def test_stirred_chambers_cross_an_opening_at_its_width_over_the_chamber_s_area():
    s = systems.SYSTEMS["stirred-chambers"]
    p = dict(s.defaults)
    st = meanfield.measure(s, p, 11, 3000)
    mf = meanfield.model(s, p, st, 3000)
    want = {(a, b): q for a, b, q in s.moves(p)}
    got = {(a, b): q for a, b, q in mf["moves"]}
    assert set(got) == set(want), "the measured moves are exactly the openings and the drain"
    for k, q in want.items():
        assert got[k] == pytest.approx(q, rel=0.08), (k, got[k], q)


@pytest.mark.parametrize("cid", FAST)
def test_the_mean_field_model_tracks_the_particles_average_within_sampling_error(cid):
    """40 particle runs from the same start with the same drivers: their average minus the mean-field
    model, over its standard error, is a standard normal at every step and region (exact tier), or close
    to one (measured tier)."""
    c = casemod.load(cid)
    chk = c["particles"]["check"]
    assert c["particles"]["tier"] in ("exact", "measured") and c["particles"]["equations"]
    assert 0.7 <= chk["z_rms"] <= 1.3 and abs(chk["z_mean"]) <= 0.4 and chk["within"] >= 0.98, chk
    assert chk["rel"] < 0.05


def test_where_the_mean_field_model_is_not_exact_it_does_not_track_and_only_prediction_is_scored():
    s = systems.SYSTEMS["gate"]
    p = dict(s.defaults)
    mf = meanfield.model(s, p, meanfield.measure(s, p, 5, 4000), 4000)
    chk = meanfield.check(s, p, mf, 7, 300, runs=20)
    assert chk["z_rms"] > 5, "a capacity gate: no proportional rate tracks the queue"
    assert s.tier == "prediction"


@pytest.mark.parametrize("cid", FAST)
def test_the_mean_field_model_passes_its_own_scoring_and_is_its_own_reference(cid):
    c = casemod.load(cid)
    for v in ("counts-short", "counts-long"):
        d, fr = data.load(c, v), data.load(c, v, fresh=True)
        s = particles.score_found(c, v, casemod.truth_model(c, v), particles.reference_flows(c), d, fr)   # the model, its schedule written out
        assert s["status"] == "pass", (v, [p["key"] for p in s["parts"] if not p["ok"]], s["spurious"])
        assert s["particles"]["gap20"] == pytest.approx(0.0, abs=1e-9) and s["particles"]["near_reference"]
        assert s["physics"]["structure_ok"]


def test_a_linear_model_of_a_product_fails_the_equations():
    c = casemod.load("part-reacting-particles")
    d, fr = data.load(c, "counts-short"), data.load(c, "counts-short", fresh=True)
    linear = [f for f in c["model"]["flows"] if not f.get("effects")] + [
        {"id": "ac", "from": "A", "to": "C", "rate": {"form": "proportional", "stock": "A", "k": 0.04}}]
    s = particles.score_found(c, "counts-short", casemod.truth_model(c, "counts-short"), linear, d, fr)
    assert s["status"] == "fail" and s["particles"]["equations"] == "fail"


def test_particle_cases_are_kept_out_of_the_tests_totals(tmp_path, monkeypatch):
    folder = tmp_path / "cases"
    (folder / "particles").mkdir(parents=True)
    (folder / "003-chain-2.json").write_text(json.dumps(casemod.spec("003-chain-2")))
    shutil.copy(PART / "part-conveyor-bottleneck.yaml", folder / "particles" / "part-conveyor-bottleneck.yaml")
    monkeypatch.setattr(casemod, "CASES", folder)
    items = runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}])
    assert len(items) == 4 + 2
    part = [i for i in items if i["case"].startswith("part-")]
    assert {i["score_hash"] for i in part} != {i["score_hash"] for i in items if i not in part}, "particle scoring is in its own hash"
    c = casemod.load("part-conveyor-bottleneck")
    for it in items:
        if it["case"].startswith("part-"):
            d, fr = data.load(c, it["variant"]), data.load(c, it["variant"], fresh=True)
            flows = c["model"]["flows"] if it["variant"] == "counts-long" else [f for f in c["model"]["flows"] if f["id"] != "V8_out"]
            sc = particles.score_found(c, it["variant"], casemod.truth_model(c, it["variant"]), flows, d, fr)
        else:
            sc = {"status": "pass", "recall": 1.0}
        store.record({**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")},
                      "status": sc["status"], "seconds": 1.0, "scores": sc, "found": []})
    sm = api._summary(["matrix"], catalog.listing())
    t, pt = sm["totals"]["matrix"], sm["particles"]["matrix"]
    assert t["total"] == 4 and t["pass"] == 4, "the tests' pass rate leaves the particle runs out"
    assert pt["cells"] == 2 and pt["pass"] == 1 and pt["fail"] == 1 and pt["scored"] == 2 and pt["eq_pass"] == 1
    assert "matrix" not in sm["physics"], "particle cells have their own aggregate, beside the physics one"
    case = next(x for x in sm["cases"] if x["id"] == "part-conveyor-bottleneck")
    assert case["particles"]["tier"] == "exact" and case["physics"]["system"] == "conveyor"
    assert runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}]) == []
