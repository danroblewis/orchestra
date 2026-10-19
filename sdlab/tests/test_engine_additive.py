"""The engine features added on 2026-10-18 (measured inputs, a sub-step dt, stock ceilings, exact flows,
DELAY/SMOOTH and test inputs compiled by the case format), and the proof that they are additive.

Additive: tests/engine_outputs.sha256 was recorded *before* the change (tests/engine_outputs.py):
every ladder case's data in every variant and on both seeds, every sd-* example's runs, measured data
and answer key, and 40 generated bench models with their datasets. They must still be bit-identical.
The new features are then each checked against an analytic expectation.
"""

import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine_outputs  # noqa: E402

from sdlab.discovery.matrix import identify_one  # noqa: E402
from sdlab.discovery.simulate import Model, levels_array  # noqa: E402
from sdlab.ladder import cases, data  # noqa: E402
from sdlab.ladder.caseformat import CaseError, compile_case  # noqa: E402
from sdlab.sdtruth import input_value  # noqa: E402

HEAD = "title: t\nlevel: 1\ntags: [x]\ntests: x\n"


def run(model: dict, steps: int, noise: dict | None = None, seed: int = 1) -> dict:
    m = {"id": "x", "name": "x", "time_unit": "step", "seed": seed, "steps": steps, "noise": noise or {},
         "stocks": [{"name": s["id"], "unit": "things", **s} for s in model["stocks"]],
         "flows": [{"name": f["id"], **f} for f in model["flows"]], **{k: model[k] for k in ("dt", "inputs", "schedule", "injections") if k in model}}
    return data.simulate(m, seed, steps)


def case_model(text: str) -> dict:
    return compile_case(HEAD + text)["model"]


# ---- additive: every existing number unchanged ----

def test_every_existing_simulation_gives_the_same_numbers():
    """Every recorded output (ladder data, examples, bench models and answer keys) is bit-identical."""
    old = engine_outputs.recorded()
    ladder = sorted({k.split("/")[1] for k in old if k.startswith("ladder/")})       # the cases recorded (not ones added since)
    examples = [i for i in engine_outputs.example_items() if f"example/{i.split('|', 1)[1]}/truth" in old]       # the examples recorded
    now = engine_outputs.fingerprints([f"ladder|{c}" for c in ladder] + examples + engine_outputs.bench_items())
    missing = sorted(k for k in old if k not in now)
    changed = sorted(k for k in old if k in now and now[k] != old[k])
    assert not changed, f"{len(changed)} outputs changed: {changed[:10]}"
    assert not missing, f"{len(missing)} recorded outputs no longer made: {missing[:10]}"
    assert sum(k.startswith("ladder/") for k in old) > 1500 and sum(k.startswith("example/") for k in old) > 100


def test_old_cases_keep_their_hashes_and_new_ones_cover_the_new_code():
    recorded = {k.split("/")[1] for k in engine_outputs.recorded() if k.startswith("ladder/")}
    for cid in recorded:
        # hashed with the legacy engine, or (a case that uses the 2026-10-18 features, recorded at 05ae898
        # before queue item 2d's) with the engine of that day: never with the code as it is now
        assert not cases.uses_2d_features(cases.load(cid)["model"]), cid
    for cid in ("062-tank-fed-by-measured-pump", "063-delay3-supply-line"):
        assert cases.uses_added_features(cases.load(cid)["model"])
    assert cases.uses_added_features(case_model("stocks: {A: 0 max=5}\nflows:\n  outside -> A: 1\n"))
    assert not cases.uses_added_features(case_model("stocks: {A: 0}\nflows:\n  outside -> A: 1\n"))


# ---- sub-steps ----

def test_dt_refines_towards_the_ode_solution():
    """A first-order drain A' = -0.5 A from 100: Euler's error at t = 4 shrinks with dt, about in proportion."""
    m = {"stocks": [{"id": "A", "initial": 100}], "flows": [{"id": "out", "from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.5}}]}
    exact = 100 * math.exp(-0.5 * 4)
    errs = []
    for dt in (1, 0.5, 0.1, 0.01):
        a4 = run({**m, "dt": dt}, 4)["levels"]["A"][3]
        assert a4 == pytest.approx(100 * (1 - 0.5 * dt) ** (4 / dt), abs=1e-3)       # exactly Euler at dt
        errs.append(abs(a4 - exact))
    assert errs == sorted(errs, reverse=True) and errs[-1] < 0.01 * errs[0]
    assert errs[2] / errs[3] == pytest.approx(10, rel=0.15)                            # first order in dt


def test_dt_keeps_the_counting_variance_of_a_recorded_step():
    """Poisson per sub-step: a constant rate 4 moves Poisson(4) per recorded step at any dt."""
    m = {"stocks": [{"id": "A", "initial": 0}], "flows": [{"id": "in", "from": None, "to": "A", "rate": {"form": "constant", "value": 4}}]}
    for dt in (1, 0.25, 0.1):
        c = run({**m, "dt": dt}, 6000, {"counts": True}, seed=3)["counters"]["in"]
        assert all(isinstance(x, int) for x in c)
        assert statistics.fmean(c) == pytest.approx(4, rel=0.03), dt
        assert statistics.variance(c) == pytest.approx(4, rel=0.08), dt


def test_dt_rejects_a_step_that_does_not_divide_one():
    with pytest.raises(ValueError):
        run({"stocks": [{"id": "A", "initial": 1}], "flows": [], "dt": 0.3}, 2)
    with pytest.raises(CaseError):
        case_model("dt: 0.3\nstocks: {A: 0}\nflows:\n  outside -> A: 1\n")


# ---- ceilings ----

def test_a_ceiling_holds_and_a_move_into_a_full_stock_stays_where_it_was():
    """T fills at 50 with a drain of 0.1 T: without a ceiling it would settle at 500; with max=200 its
    inflows are cut to the room left. As with the floor (outflows share what a stock holds before the
    step's inflows), the room is taken before the step's outflows, so at dt = 1 T settles at
    200 / (1 + 0.1) and at a fine dt at 200. A move from A into the full T is cut too, so A keeps what
    could not go (conserved), for as long as T is full."""
    m = case_model("stocks: {A: 100, T: 0 max=200}\nflows:\n  outside -> T: 50\n  T -> outside: 0.1 * T\n  A -> T: 0.2 * A\n")
    for noise in ({}, {"counts": True}):
        d = run(m, 300, noise)
        T, A = d["levels"]["T"], d["levels"]["A"]
        assert max(T) <= 200 and T[-1] == pytest.approx(200 / 1.1, abs=15 if noise else 0.01)
        free = run(case_model("stocks: {A: 100, T: 0}\nflows:\n  outside -> T: 50\n  T -> outside: 0.1 * T\n  A -> T: 0.2 * A\n"), 10, noise)
        assert A[9] > 2 * free["levels"]["A"][9]                # the move was cut while T was full
        moved = sum(d["counters"]["at"])
        assert A[-1] == pytest.approx(100 - moved, abs=1)        # conserved: A lost exactly what T took
    fine = run({**m, "dt": 0.01}, 300)["levels"]["T"]
    assert max(fine) <= 200 and fine[-1] == pytest.approx(200 / 1.001, abs=0.01)


def test_an_injection_never_fills_a_stock_past_its_ceiling():
    m = case_model("stocks: {A: 10 max=50}\nflows:\n  A -> outside: 0.1 * A\ninjections: [{t: 3, stock: A, amount: 400}]\n")
    d = run(m, 5)
    assert max(d["levels"]["A"]) <= 50 and d["injections"][0]["amount"] < 50


# ---- measured inputs ----

def test_a_rate_reads_a_measured_input_and_the_run_reports_it():
    m = case_model("inputs:\n  pump: [1, 2, 3, 4]\nstocks: {T: 0}\nflows:\n  outside -> T: 2 * input(pump)\n")
    d = run(m, 6)
    assert d["inputs"] == {"pump": [1, 2, 3, 4, 4, 4]}                 # after the series ends, its last value
    assert d["counters"]["in"] == [2, 4, 6, 8, 8, 8]
    assert d["levels"]["T"] == [2, 6, 12, 20, 28, 36]


def test_input_formulas():
    spec = {"terms": [{"fn": "constant", "value": 1}, {"fn": "step", "height": 2, "start": 5}, {"fn": "pulse", "height": 10, "start": 3, "width": 2},
                      {"fn": "ramp", "slope": 1, "start": 7, "end": 9}, {"fn": "pulse_train", "height": 100, "first": 10, "width": 1, "every": 3, "last": 16}]}
    got = [input_value(spec, t, t) for t in range(1, 20)]
    assert got == [1, 1, 11, 11, 3, 3, 3, 4, 5, 105, 5, 5, 105, 5, 5, 105, 5, 5, 5]
    sin = {"terms": [{"fn": "sin", "amplitude": 2, "period": 4}]}
    assert [round(input_value(sin, t, t), 9) for t in (0, 1, 2, 3)] == [0, 2, 0, -2]
    assert input_value({"values": [1, 2, 3], "repeat": True}, 5, 5) == 2
    m = case_model("inputs:\n  u: 1 + step(2, 5) + 3 * pulse(1, 3, 2) - ramp(1, 7, 9)\nstocks: {A: 0}\nflows:\n  outside -> A: u\n")
    assert m["inputs"]["u"]["terms"][2] == {"fn": "pulse", "height": 3.0, "start": 3, "width": 2}


def test_an_input_is_held_over_a_step_and_its_formula_follows_the_sub_steps():
    m = case_model("dt: 0.25\ninputs:\n  s: [4, 8]\n  r: ramp(1, 1)\nstocks: {A: 0, B: 0}\nflows:\n  outside -> A: s\n  outside -> B: r\n")
    d = run(m, 3)
    assert d["inputs"]["s"] == [4, 8, 8] and d["counters"]["in"] == [4, 8, 8]
    assert d["inputs"]["r"] == pytest.approx([0.375, 1.375, 2.375])         # the mean of t + j/4 - 1 over j
    assert d["counters"]["b_in"] == pytest.approx([0.375, 1.375, 2.375])


def test_an_input_from_a_file(tmp_path, monkeypatch):
    from sdlab.ladder import caseformat
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "u.csv").write_text("t,u\n1,3\n2,5\n")
    (tmp_path / "data" / "v.json").write_text("[7, 9]")
    monkeypatch.setattr(caseformat, "CASES_DIR", tmp_path)
    m = case_model("inputs:\n  u: {file: data/u.csv, column: u}\n  v: {file: data/v.json, repeat: true}\nstocks: {A: 0}\nflows:\n  outside -> A: u + 0.5 * v\n")
    assert m["inputs"] == {"u": {"values": [3.0, 5.0]}, "v": {"values": [7.0, 9.0], "repeat": True}}
    with pytest.raises(CaseError, match="column"):
        case_model("inputs:\n  u: {file: data/u.csv}\nstocks: {A: 0}\nflows:\n  outside -> A: u\n")
    with pytest.raises(CaseError, match="no file"):
        case_model("inputs:\n  u: {file: ../../etc/passwd}\nstocks: {A: 0}\nflows:\n  outside -> A: u\n")


def test_input_names_are_checked():
    for bad in ("inputs:\n  A: [1]\n", "inputs:\n  u: {values: [1], speed: 2}\n", "inputs:\n  u: 1 + bogus(2)\n"):
        with pytest.raises(CaseError):
            case_model(bad + "stocks: {A: 0}\nflows:\n  outside -> A: 1\n")
    with pytest.raises(CaseError, match="names an input"):
        case_model("inputs:\n  u: [1]\nstocks: {A: 0}\nflows:\n  outside -> A: 1 uses(u, 0.1)\n")


# ---- delays, smoothing and test inputs (compiled to existing parts) ----

def test_delay1_step_response_is_exactly_first_order():
    """10 per step into DELAY1 of 4 steps: the outflow in step n + 1 is 10 (1 - (3/4)^n) (Euler, dt 1)."""
    m = case_model("stocks: {B: 0}\nflows:\n  outside -> B: delay1(10, 4)\n")
    assert [s["id"] for s in m["stocks"]] == ["B", "in_d1"] and m["stocks"][1]["measured"] is False
    out = run(m, 12)["counters"]["in_1"]
    assert out == pytest.approx([10 * (1 - 0.75 ** n) for n in range(12)], abs=1e-3)


def test_delay3_step_response_approaches_the_erlang_curve():
    """DELAY3 of 6 at a fine dt: the output follows 10 (1 - e^-x (1 + x + x^2 / 2)), x = 3t / 6."""
    m = case_model("dt: 0.01\nstocks: {B: 0}\nflows:\n  outside -> B: delay3(10, 6)\n")
    assert [f["id"] for f in m["flows"]] == ["in", "in_1", "in_2", "in_3"]
    assert all(f["rate"]["k"] == 0.5 for f in m["flows"][1:])
    d = run(m, 30)
    B = [0] + d["levels"]["B"]
    for t in (2, 6, 12, 24):
        x = 3 * (t + 0.5) / 6                                   # step t + 1 runs from time t to t + 1
        rate = 10 * (1 - math.exp(-x) * (1 + x + x * x / 2))
        assert B[t + 1] - B[t] == pytest.approx(rate, abs=0.15), t


def test_a_delay3_chain_is_one_hidden_path_in_the_answer_key():
    from sdlab.ladder.parts import parts
    c = cases.load("063-delay3-supply-line")
    flows = cases.truth_model(c, "none-short")["flows"]
    p, notes = parts(flows, {"A", "B"}, (1, 300))
    assert p[("hidden", "A", "B")] == {"k_in": 0.1, "delay": 6.0}
    assert not notes
    t = engine_outputs._truth(cases.truth_model(c, "none-short")).truth()
    assert [h["via"] for h in t["hidden"]] == [["ab_d1", "ab_d2", "ab_d3"]] and t["hidden"][0]["delay"] == 6.0


def test_smooth_is_a_hidden_stock_with_exact_flows():
    """SMOOTH(A, 5) of a constant A = 100 from 0: 100 (1 - (4/5)^n), with no counting noise."""
    m = case_model("stocks: {A: 100, C: 0}\nflows:\n  outside -> C: 0.1 * smooth(A, 5, initial=0)\n  C -> outside: 0.5 * C\n")
    sm = next(s for s in m["stocks"] if s["id"] == "smooth_A_5")
    assert sm["initial"] == 0 and sm["measured"] is False
    d = run(m, 10, {"counts": True})
    assert d["all_levels"]["smooth_A_5"][:6] == [round(100 * (1 - 0.8 ** n)) for n in range(1, 7)]
    m3 = case_model("stocks: {A: 100, C: 0}\nflows:\n  outside -> C: 0.1 * smooth3(A, 6)\n")
    assert [s["initial"] for s in m3["stocks"] if s["id"].startswith("smooth3")] == [100, 100, 100]


def test_test_inputs_compile_to_the_same_run_as_an_input_formula():
    a = case_model("stocks: {A: 0}\nflows:\n  outside -> A: 10 + step(5, 4) - pulse(3, 7, 2) + pulse_train(1, 2, 1, 5)\n  A -> outside: 0.1 * A\n")
    assert [c["t"] for c in a["schedule"]["changes"]][:8] == [2, 3, 4, 7, 8, 9, 12, 13]
    assert all(not c.get("announce") for c in a["schedule"]["changes"])
    b = case_model("inputs:\n  u: 10 + step(5, 4) - pulse(3, 7, 2) + pulse_train(1, 2, 1, 5)\nstocks: {A: 0}\nflows:\n  outside -> A: u\n  A -> outside: 0.1 * A\n")
    assert run(a, 40)["levels"] == run(b, 40)["levels"]
    g = case_model("stocks: {A: 0, B: 5}\nflows:\n  outside -> A: (50 - A) / 5 + step(2, 3)\n  outside -> B: 0.5 * B + step(1, 2)\n")
    assert g["schedule"]["changes"][1]["set"]["in"] == {"form": "gap", "stock": "A", "goal": 60, "time": 5}
    assert g["schedule"]["changes"][0]["set"]["b_in"] == {"form": "linear", "c": 1.0, "terms": [{"stock": "B", "k": 0.5}]}
    with pytest.raises(CaseError, match="periodic"):
        case_model("stocks: {A: 0}\nflows:\n  outside -> A: 1 + step(1, 5)\nschedule:\n  every: 10\n  at 2: {in: 3}\n")


# ---- the simulator and discovery mirror them ----

def test_the_simulator_steps_inputs_dt_and_ceilings_as_the_engine_does():
    m = case_model("dt: 0.25\ninputs:\n  u: 4 + 2 * sin(1, 20)\nstocks: {A: 10 max=30, B: 0}\nflows:\n  outside -> A: 2 * u\n  A -> B: 0.3 * A\n  B -> outside: 0.05 * B\n")
    d = run(m, 200)
    ids = ["A", "B"]
    A = levels_array(d["all_levels"], ids)
    model = Model(m["flows"], ids, inputs={"t": d["t"], "values": d["inputs"]}, dt=0.25, ceilings={"A": 30})
    pred = model.step(A[:, :-1], np.asarray(d["t"][1:], float))
    # one step from each recorded level; the engine averages the formula over sub-steps, the simulator
    # holds the step's mean, so they agree to the curvature of the sine within a step
    assert np.abs(pred - A[:, 1:]).max() < 0.05
    assert A[0].max() == pytest.approx(30 / (1 + 0.3 * 0.25), abs=1e-3)   # held under max (room taken before outflows)
    legacy = Model(m["flows"][1:], ids)
    assert legacy.n_sub == 1 and legacy.inputs is None and not legacy.ceilings


def test_matrix_reads_a_measured_input_as_a_column():
    c = cases.load("062-tank-fed-by-measured-pump")
    d = data.load(c, "none-short")
    r = identify_one([{"id": "T"}], {"t": d["t"], "levels": d["levels"]}, {"inputs": d["inputs"]})
    got = {(f["from"], f["to"], tuple(x["stock"] for x in f["rate"].get("terms") or [])): f["rate"] for f in r["flows"]}
    assert got[(None, "T", ("pump",))]["terms"][0]["k"] == pytest.approx(2, rel=1e-3)
