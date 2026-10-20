"""Physics cases (sdlab/ladder/physics): ODE data that are reproducible and accurate, the physics'
declared structure matches its own equations, the reference (best SD model) is fitted and graded,
the scorer passes the reference and fails a wrong structure, and physics runs stay out of the Tests
totals."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from sdlab.ladder import api, catalog, data, physics, runner, store
from sdlab.ladder import cases as casemod
from sdlab.ladder.physics import ode, structure, systems

PHYS = Path(casemod.__file__).resolve().parent / "cases" / "physics"
IDS = sorted(p.stem for p in PHYS.glob("phys-*.yaml"))


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def test_seven_physics_cases_one_per_system_tagged_and_listed_after_the_tests():
    assert len(IDS) == 7
    cs = [casemod.load(i) for i in IDS]
    assert sorted(c["physics"]["system"] for c in cs) == sorted(systems.SYSTEMS)
    for c in cs:
        assert "physics" in c["tags"] and c["tests"] and casemod.is_physics(c["id"])
        assert [v["name"] for v in c["variants"]] == ["none-short", "none-long", "meas-short", "meas-long"]
        assert [v["observe"]["kind"] for v in c["variants"] if v.get("observe")] == ["meas", "meas"], "no counting noise: meas only"
    ids = casemod.case_ids()
    assert all(not casemod.is_physics(i) for i in ids[: ids.index(IDS[0])] if not i.startswith("sd-")), "the tests come first"


def test_the_ode_data_are_reproducible_and_a_short_run_is_the_start_of_a_long_one(cache):
    c = casemod.load("phys-coupled-tanks")
    a = data.load(c, "none-long")
    shutil.rmtree(cache / "data")
    physics._memo.clear()
    physics.ensure(c)
    assert data.load(c, "none-long") == a, "rebuilt from scratch: the same numbers"
    short = data.load(c, "none-short")
    assert all(short["levels"][s] == a["levels"][s][:300] for s in a["levels"])
    assert short["inputs"]["pump"] == a["inputs"]["pump"][:300]
    fresh = data.load(c, "none-long", fresh=True)
    assert fresh["levels"]["H1"][:5] != a["levels"]["H1"][:5], "the fresh run starts elsewhere"
    noisy = data.load(c, "meas-long")
    assert noisy["clean"]["levels"] == a["levels"] and noisy["levels"] != a["levels"], "meas: noise.py's error on the same run"
    assert data.load(c, "meas-long")["levels"] == noisy["levels"]


def test_the_data_are_in_the_engine_s_format():
    d = data.load(casemod.load("phys-reaction-chain"), "none-short")
    assert d["t"] == list(range(1, 301)) and d["eras"] == [{"start": 1, "label": "Start"}] and set(d["levels"]) == {"A", "B", "C"}
    assert d["injections"] and all(j["stock"] == "A" and j["amount"] > 0 for j in d["injections"])
    j = d["injections"][0]
    a = d["levels"]["A"]
    assert a[j["t"] - 1] > a[j["t"] - 2] + 0.5 * j["amount"], "an injection at t is in the level reported at t"
    th = data.load(casemod.load("phys-thermostat"), "none-short")
    assert set(th["inputs"]) == {"outside", "setpoint"} and len(th["inputs"]["setpoint"]) == 300


def test_the_solver_agrees_with_a_fine_rk4():
    s = systems.SYSTEMS["draining-tank"]
    p = ode.params(s, None, 1)
    got = np.array(ode.simulate(s, p, 1, 60)["levels"]["H"])
    dr = ode.drive(s, p, 1, 60)
    x = np.asarray(s.initial(ode._rng_for(1)("initial"), p), dtype=float)
    h, out = 2e-3, []
    for i in range(60 * 500):
        t = i * h
        k1 = s.rhs(t, x, p, dr, None)
        k2 = s.rhs(t + h / 2, x + h / 2 * k1, p, dr, None)
        k3 = s.rhs(t + h / 2, x + h / 2 * k2, p, dr, None)
        k4 = s.rhs(t + h, x + h * k3, p, dr, None)
        x = x + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        if (i + 1) % 500 == 0:
            out.append(x[0])
    assert np.max(np.abs(np.array(out) - got)) < 1e-3


@pytest.mark.parametrize("cid", [i for i in IDS if i != "phys-thermostat"])
def test_the_declared_couplings_are_the_ode_s_own(cid):
    """The structure the scorer expects is what the right-hand side's Jacobian says on every run the
    case grades (both lengths, its seed and the fresh one), every coupling clear of the 10% presence
    threshold (the thermostat's switch has memory, so its control coupling is declared, not read off
    the Jacobian)."""
    c = casemod.load(cid)
    s, p = systems.SYSTEMS[c["physics"]["system"]], c["physics"]["params"]
    lv = systems.levels_for(s, p)
    for steps in (300, 2000):
        for seed in (c["model"]["seed"], c["model"]["seed"] + 1):
            d = ode.simulate(s, p, seed, steps)
            x = np.array([d["levels"][k] for k in s.ids]) - (lv(np.zeros((len(s.ids), 1))) if lv else 0)
            J = structure.physics_jacobian(s, p, ode.drive(s, p, seed, steps), x, np.arange(1, steps + 1, dtype=float))
            names, V, _ = structure.variables(d, s.inputs)
            found = structure.couplings(s.ids, names, J, V)
            cmp = structure.compare(s.couplings, found)
            assert cmp["ok"] and cmp["shape_right"] == cmp["shape_of"], (steps, seed, cmp)
            weakest = min(f["rel"] for f in found if (f["receiver"], f["source"]) in {(a, b) for a, b, *_ in s.couplings})
            assert weakest >= 1.5 * structure.REL, (steps, seed, weakest)


@pytest.mark.parametrize("cid", IDS)
def test_the_reference_is_fitted_graded_and_passes_its_own_scoring(cid):
    c = casemod.load(cid)
    d, fr = data.load(c, "none-short"), data.load(c, "none-short", fresh=True)
    ref = physics.reference_grade(c, "none-short", d, fr)
    f20 = ref["behaviour"]["fresh"]["20"]["skill"]
    assert f20 is not None and np.isfinite(f20) and ref["longrun"]["err"] is not None
    s = physics.score_found(c, "none-short", c["model"]["flows"], d, fr)
    assert s["physics"]["gap20"] == pytest.approx(0.0, abs=1e-9)
    # the thermostat's structure is the reference's (closed loop: the best predicting SD model all but
    # drops the outside's coupling, the heater absorbs it), so the reference passes there too
    assert ref["structure"]["ok"], ref["structure"]
    assert s["status"] == "pass"
    if c["physics"]["system"] in ("newton-cooling", "reaction-chain", "mass-spring-damper"):
        assert f20 > 0.99, "exactly linear physics: the best SD model is (almost) exact"


def test_a_wrong_structure_fails_and_says_why():
    c = casemod.load("phys-draining-tank")
    d, fr = data.load(c, "none-short"), data.load(c, "none-short", fresh=True)
    no_pump = [{"id": "in", "from": None, "to": "H", "rate": {"form": "constant", "value": 2.0}}] + [f for f in c["model"]["flows"] if f["id"] != "in"]
    s = physics.score_found(c, "none-short", no_pump, d, fr)
    rows = {r["key"]: r for r in s["physics"]["couplings"]}
    assert s["status"] == "fail" and not rows["H <- pump"]["present"] and rows["H <- H"]["sign_ok"]
    assert rows["H <- H"]["shape_found"] == "linear" and rows["H <- H"]["shape_true"] == "sqrt", "SD writes the sqrt drain as a line"
    births = c["model"]["flows"] + [{"id": "b", "from": None, "to": "H", "rate": {"form": "proportional", "stock": "H", "k": 0.5}}]
    s = physics.score_found(c, "none-short", births, d, fr)
    assert not s["physics"]["structure_ok"] and [r["sign_found"] for r in s["physics"]["couplings"] if r["key"] == "H <- H"] == ["+"]


def test_physics_cases_are_kept_out_of_the_tests_totals(tmp_path, monkeypatch):
    folder = tmp_path / "cases"
    (folder / "physics").mkdir(parents=True)
    (folder / "003-chain-2.json").write_text(json.dumps(casemod.spec("003-chain-2")))
    shutil.copy(PHYS / "phys-newton-cooling.yaml", folder / "physics" / "phys-newton-cooling.yaml")
    monkeypatch.setattr(casemod, "CASES", folder)
    items = runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}])
    assert len(items) == 4 + 4
    phys = [i for i in items if i["case"] == "phys-newton-cooling"]
    assert {i["score_hash"] for i in phys} != {i["score_hash"] for i in items if i not in phys}, "physics scoring is in its own hash"
    c = casemod.load("phys-newton-cooling")
    for it in items:
        if it["case"].startswith("phys-"):
            d, fr = data.load(c, it["variant"]), data.load(c, it["variant"], fresh=True)
            sc = physics.score_found(c, it["variant"], c["model"]["flows"] if it["variant"].startswith("none") else [], d, fr)
        else:
            sc = {"status": "pass", "recall": 1.0}
        store.record({**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")},
                      "status": sc["status"], "seconds": 1.0, "scores": sc, "found": []})
    sm = api._summary(["matrix"], catalog.listing())
    t, ph = sm["totals"]["matrix"], sm["physics"]["matrix"]
    assert t["total"] == 4 and t["pass"] == 4, "the tests' pass rate leaves the physics runs out"
    assert ph["cells"] == 4 and ph["pass"] == 2 and ph["fail"] == 2 and ph["structure"] == 2 and ph["gap20"] is not None
    assert next(x for x in sm["cases"] if x["id"] == "phys-newton-cooling")["physics"]["system"] == "newton-cooling"
    assert runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}]) == []


def test_sampling_couplings_are_allowed_never_required():
    """The exact one-step map of the sampled oscillator reads P itself and the force (position moves by
    about half the force over a step): a found model with them is not charged for it; a stock it does
    not have is still invented."""
    c = casemod.load("phys-mass-spring-damper")
    assert sorted(map(tuple, physics.sampling(c))) == [("P", "P"), ("P", "force")]
    assert all(physics.sampling(casemod.load(i)) == [] for i in IDS if i != "phys-mass-spring-damper")
    d, fr = data.load(c, "none-long"), data.load(c, "none-long", fresh=True)
    ref = c["model"]["flows"]
    extra = [{"id": "x1", "from": None, "to": "P", "rate": {"form": "proportional", "stock": "force", "k": 0.5}},
             {"id": "x2", "from": "P", "to": None, "rate": {"form": "proportional", "stock": "P", "k": 0.005}}]
    s = physics.score_found(c, "none-long", ref + extra, d, fr)
    assert s["physics"]["structure_ok"] and {x["key"] for x in s["physics"]["sampling"]} == {"P <- force", "P <- P"}
    s = physics.score_found(c, "none-long", ref + [{"id": "x3", "from": "V", "to": None, "rate": {"form": "proportional", "stock": "V", "k": 0.3}}], d, fr)
    assert s["physics"]["structure_ok"], "V <- V is the physics' own (damping): a stronger one is a number, not a structure"
    s = physics.score_found(c, "none-long", ref + [{"id": "x4", "from": None, "to": "V", "rate": {"form": "proportional", "stock": "V", "k": 0.3}}], d, fr)
    assert not s["physics"]["structure_ok"], "V reading itself positively is the wrong sign"


def test_thermostat_structure_is_the_references_and_the_declared_outside_coupling_is_allowed():
    from sdlab.ladder.physics import score as pscore
    c = casemod.load("phys-thermostat")
    d = data.load(c, "none-long")
    expected, allowed = pscore.expected_structure(c, d.get("clean") or d)
    keys = {(x, y) for x, y, *_ in expected}
    assert ("T", "outside") not in keys and ["T", "outside"] in allowed and ("T", "T") in keys
    # a non-switching system keeps the physics' declared couplings
    tank = casemod.load("phys-draining-tank")
    dt = data.load(tank, "none-short")
    assert pscore.expected_structure(tank, dt) == ([tuple(x) for x in tank["physics"]["couplings"]], [])
    # a model with the outside coupling at full strength is not spurious; one without T <- setpoint fails
    fr = data.load(c, "none-long", fresh=True)
    no_setpoint = [f for f in c["model"]["flows"] if "setpoint" not in str(f)]
    s = physics.score_found(c, "none-long", no_setpoint, d, fr)
    assert not s["physics"]["structure_ok"]
