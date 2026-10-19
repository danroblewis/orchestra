"""The engine features added for queue item 2d (2026-10-19): expressions (ratios, MIN/MAX/CEIL, sqrt and
power, lookups, comparisons), auxiliaries, switches with memory (hysteresis), signed stocks, two-way
flows, flows that read another flow's amount, ceilings that count the step's outflows, DELAY FIXED,
delays whose time changes, and TREND / FORECAST, each checked against an analytic expectation.

Additive: tests/test_engine_additive.py proves every existing case, example and bench model gives
bit-identical numbers (tests/engine_outputs.sha256, recorded before the change). Here, also: the
extended loop (Truth._run_ext, which only 2d models use) gives those same numbers for every existing
case, so it is the old loop plus the new features, not a second engine.
"""

import math
import random

import numpy as np
import pytest

from sdlab.ladder import cases, data
from sdlab.ladder.caseformat import CaseError, compile_case
from sdlab.sdtruth import Truth, uses_2d
from sdlab.sdtruth_expr import ExprError, compile_expr, parse

HEAD = "title: t\nlevel: 1\ntags: [x]\ntests: x\n"


def run(model: dict, steps: int, noise: dict | None = None, seed: int = 1) -> dict:
    m = {"id": "x", "name": "x", "time_unit": "step", "seed": seed, "steps": steps, "noise": noise or {},
         "stocks": [{"name": s["id"], "unit": "things", **s} for s in model["stocks"]],
         "flows": [{"name": f["id"], **f} for f in model["flows"]],
         **{k: model[k] for k in ("dt", "inputs", "schedule", "injections", "auxiliaries") if k in model}}
    return data.simulate(m, seed, steps)


def case_model(text: str) -> dict:
    return compile_case(HEAD + text)["model"]


def _truth(model: dict) -> Truth:
    t = Truth.__new__(Truth)
    t.path, t.model = None, model
    t.seed, t.steps, t.long_steps = int(model["seed"]), int(model["steps"]), int(model["steps"]) * 10
    t.measured_ids = [s["id"] for s in model["stocks"] if s.get("measured", True)]
    t.stock_ids = [s["id"] for s in model["stocks"]]
    return t


# ---- additive ----

def test_no_case_recorded_before_the_change_uses_a_2d_feature_and_the_new_canonical_ones_do():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import engine_outputs
    recorded = {k.split("/")[1] for k in engine_outputs.recorded() if k.startswith("ladder/")}
    for cid in recorded:
        assert not uses_2d(cases.load(cid)["model"]), cid
        assert not cases.uses_2d_features(cases.load(cid)["model"]), cid
    for cid in ("113-canonical-harmonic-oscillator", "114-canonical-workforce-capacity", "116-canonical-world3-pollution-full",
                "117-canonical-fixed-delay-line"):
        assert cases.uses_2d_features(cases.load(cid)["model"]), cid


@pytest.mark.parametrize("noise", ["none", "counts"])
def test_the_extended_loop_gives_every_existing_case_the_same_numbers(noise):
    """Every case's shortest variant of this noise, through run() and through _run_ext: bit-identical."""
    n = 0
    for cid in cases.case_ids():
        c = cases.load(cid)
        vs = [v for v in c["variants"] if v.get("noise") == noise and not v.get("observe")]
        if not vs or c.get("real"):
            continue
        v = min(vs, key=lambda v: v["steps"])
        tm = cases.truth_model(c, v["name"])
        t = _truth(tm)
        steps = min(v["steps"], 400)
        assert t.run(steps=steps) == t._run_ext(None, steps, None, None, 1), cid
        n += 1
    assert n > 250


# ---- expressions ----

def test_expression_syntax_and_functions():
    ev = lambda text, **v: compile_expr(parse(text))(v, {})  # noqa: E731
    assert ev("1 + 2 * 3 - 4 / 2") == 5
    assert ev("-2 ^ 2") == -4 and ev("2 ^ -1") == 0.5 and ev("2 ^ 3 ^ 2") == 512
    assert ev("min(A, B, 3) + max(A, B)", A=1, B=5) == 6
    assert ev("ceil(A / B) + floor(-0.5) + integer(-2.7)", A=7, B=2) == 4 - 1 - 2
    assert ev("sqrt(A) + power(A, 0.5) + abs(-3)", A=16) == 11
    assert ev("(A > 2) + (A <= 2) * 10 + (A == 3)", A=3) == 2
    assert ev("if_then_else(A > 2, 1 / A, 1 / 0)", A=4) == 0.25           # only the branch taken
    assert ev("zidz(A, B) + xidz(A, B, 7)", A=1, B=0) == 7 and ev("zidz(A, B)", A=1, B=4) == 0.25
    assert ev("lookup(A, [[0, 0], [10, 100], [20, -50]])", A=15) == 25 and ev("lookup(A, [[0, 1], [1, 2]])", A=-5) == 1
    assert ev("modulo(7, 3) + modulo(-7, 3) + quantum(7.5, 2)", ) == 1 + -1 + 6     # Vensim's: -7 mod 3 is -1
    assert ev("and(A, 0) + or(A, 0) + not(A)", A=1) == 1
    assert ev("ln(exp(2)) + log(100) + log(8, 2)") == pytest.approx(7)
    for bad in ("1 +", "foo(1)", "min()", "lookup(A, 2)", "A $ 2", "flow(1 + 2)"):
        with pytest.raises(ExprError):
            parse(bad)


def test_a_square_root_outflow_is_torricelli():
    """T' = -c sqrt(T): Euler at dt 1 exactly, and at a fine dt (sqrt(T0) - c t / 2)^2."""
    m = case_model("stocks: {T: 100}\nflows:\n  T -> outside: 0.5 * sqrt(T)\n")
    assert m["flows"][0]["rate"] == {"form": "expr", "expr": "(0.5 * sqrt(T))"}
    got, x = run(m, 30)["levels"]["T"], 100.0
    for g in got:
        x = max(0.0, x - min(x, 0.5 * math.sqrt(x)))
        assert g == pytest.approx(x, abs=1e-4)
    fine = run({**m, "dt": 0.01}, 20)["levels"]["T"]
    for t in (5, 10, 19):
        assert fine[t - 1] == pytest.approx((10 - 0.5 * t / 2) ** 2, rel=2e-3)


def test_ratios_min_max_and_ceil_of_stocks():
    """One step of A -> B at min(A / 4, 10 B / C) and of the HPA's ceil(desired x ratio)."""
    m = case_model("stocks: {A: 80, B: 3, C: 6, D: 2}\nflows:\n  A -> B: min(A / 4, 10 * B / C)\n"
                   "  outside -> D as hpa: ceil(D * C / 4) - D\n")
    r = run(m, 1)
    assert r["counters"]["ab"] == [5.0] and r["counters"]["hpa"] == [1.0]
    assert r["levels"]["A"] == [75] and r["levels"]["D"] == [3]


def test_formerly_rejected_rates_are_expressions_now():
    for rate, expr in (("0.5 * A * B", "(0.5 * A * B)"), ("0.5 * A ^ 2", "(0.5 * (A ^ 2))"), ("1 + 2 + A", "(1 + 2 + A)"),
                       ("(A - 300) / 5", "((A - 300) / 5)"), ("max(1, A)", "max(1, A)"), ("2 * -A", "(2 * (-A))")):
        m = case_model(f"stocks: {{A: 1, B: 1}}\nflows:\n  A -> B: {rate}\n")
        assert m["flows"][0]["rate"] == {"form": "expr", "expr": expr}, rate
    with pytest.raises(CaseError, match="unknown stock 'Z'"):
        case_model("stocks: {A: 1}\nflows:\n  A -> outside: sqrt(Z)\n")
    with pytest.raises(CaseError, match="not allowed inside"):
        case_model("stocks: {A: 1}\nflows:\n  A -> outside: sqrt(A + 1) * 2 + delay1(A, 2)\n")


# ---- auxiliaries ----

def test_auxiliaries_are_computed_in_order_every_sub_step():
    """util = cpu / ready (an auxiliary) read the same as the expression written out, at a sub-step."""
    a = case_model("dt: 0.25\nauxiliaries:\n  per: util * 2\n  util: cpu / max(1, ready)\nstocks: {cpu: 100, ready: 4}\n"
                   "flows:\n  cpu -> outside: 0.1 * per\n  outside -> ready: 0.01 * util * effect(util, table, [[0, 1], [50, 2]])\n")
    b = case_model("dt: 0.25\nstocks: {cpu: 100, ready: 4}\nflows:\n  cpu -> outside: 0.1 * cpu / max(1, ready) * 2\n"
                   "  outside -> ready: 0.01 * cpu / max(1, ready) * lookup(cpu / max(1, ready), [[0, 1], [50, 2]])\n")
    ra, rb = run(a, 50), run(b, 50)
    assert np.allclose(ra["levels"]["cpu"], rb["levels"]["cpu"], atol=2e-4) and np.allclose(ra["levels"]["ready"], rb["levels"]["ready"], atol=2e-4)
    with pytest.raises(CaseError, match="loop"):
        case_model("auxiliaries:\n  a: b + 1\n  b: a * 2\nstocks: {A: 1}\nflows:\n  A -> outside: a\n")
    with pytest.raises(CaseError, match="not an auxiliary name"):
        case_model("auxiliaries:\n  A: 2\nstocks: {A: 1}\nflows:\n  A -> outside: 1\n")


# ---- switches (hysteresis) ----

def test_a_switch_holds_between_its_levels():
    """A thermostat: on below 19, off above 21, held in between, read from each step's start."""
    m = case_model("switches:\n  heater: {of: T, on_below: 19, off_above: 21, initial: 1}\nstocks: {T: 15}\n"
                   "flows:\n  outside -> T: 2 * heater\n  T -> outside: 0.1 * T - 1\n")
    assert next(s for s in m["stocks"] if s["id"] == "heater") == {"id": "heater", "initial": 1, "measured": False,
                                                                     "switch": {"of": "T", "on_below": 19, "off_above": 21}}
    r = run(m, 300)
    T, on = [15.0] + r["all_levels"]["T"], [1.0] + r["all_levels"]["heater"]
    for i in range(1, 300):
        want = 1.0 if T[i] < 19 else 0.0 if T[i] > 21 else on[i]
        assert on[i + 1] == want
    assert 18 < min(T[50:]) < 19 and 21 < max(T[50:]) < 22.1                 # it cycles across the band, not at one level
    assert sum(abs(a - b) for a, b in zip(on[50:], on[51:])) > 20
    with pytest.raises(CaseError, match="unknown stock 's'"):                    # flows cannot name a switch
        case_model("switches:\n  s: {of: T, on_below: 1, off_above: 2}\nstocks: {T: 1}\nflows:\n  outside -> s: 1\n")
    with pytest.raises(ExprError, match="moves a switch"):
        _truth({**run_model(case_model("stocks: {T: 1, s: 0}\nflows:\n  outside -> s: 1\n")), "stocks": [{"id": "T", "initial": 1},
               {"id": "s", "initial": 0, "switch": {"of": "T", "on_below": 1, "off_above": 2}}]}).run(steps=2)


# ---- signed stocks, two-way flows ----

def test_a_spring_with_signed_stocks_and_two_way_flows_is_exactly_euler():
    """x' = v, v' = -w^2 x: each step is [x, v] <- [[1, dt], [-w^2 dt, 1]] [x, v]."""
    m = case_model("dt: 0.1\nstocks: {x: 1 signed, v: 0 signed}\nflows:\n  outside <-> x: v\n  outside <-> v: -0.25 * x\n")
    assert all(f["two_way"] for f in m["flows"])
    r = run(m, 40)
    M = np.linalg.matrix_power(np.array([[1, 0.1], [-0.25 * 0.1, 1]]), 10)
    s = np.array([1.0, 0.0])
    for t in range(40):
        s = M @ s
        assert r["levels"]["x"][t] == pytest.approx(s[0], abs=1e-4) and r["levels"]["v"][t] == pytest.approx(s[1], abs=1e-4)
    assert min(r["levels"]["x"]) < -0.9                                      # it went negative
    unsigned = run(case_model("dt: 0.1\nstocks: {x: 1, v: 0}\nflows:\n  outside -> x: v\n  outside -> v: -0.25 * x\n"), 40)
    assert min(unsigned["levels"]["x"]) >= 0 and min(unsigned["levels"]["v"]) >= 0


def test_a_two_way_exchange_conserves_and_is_floored_at_an_unsigned_stock():
    """A <-> B at 0.2 (A - B): both reach the mean; a reverse move out of an empty B moves nothing."""
    m = case_model("stocks: {A: 100, B: 0}\nflows:\n  A <-> B: 0.2 * A - 0.2 * B\n")
    r = run(m, 60)
    assert r["levels"]["A"][-1] == pytest.approx(50, abs=1e-3) and all(a + b == pytest.approx(100) for a, b in zip(r["levels"]["A"], r["levels"]["B"]))
    back = run(case_model("stocks: {A: 10, B: 0}\nflows:\n  A <-> B: -3\n"), 3)
    assert back["counters"]["ab"] == [0, 0, 0] and back["levels"]["A"] == [10, 10, 10]
    back = run(case_model("stocks: {A: 10, B: 4}\nflows:\n  A <-> B: -3\n"), 3)
    assert back["counters"]["ab"] == [-3, -1, 0] and back["levels"]["B"] == [1, 0, 0] and back["levels"]["A"] == [13, 14, 14]
    noisy = run(case_model("stocks: {A: 500 signed, B: 500 signed}\nflows:\n  A <-> B: -4\n"), 2000, {"counts": True})["counters"]["ab"]
    assert all(isinstance(q, int) and q <= 0 for q in noisy) and np.mean(noisy) == pytest.approx(-4, rel=0.05)
    assert np.var(noisy) == pytest.approx(4, rel=0.15)                        # Poisson of |rate|, signed


def test_a_signed_stock_takes_a_negative_injection():
    m = case_model("stocks: {A: 10 signed, B: 10}\nflows:\n  A -> outside: 1\n  B -> outside: 1\n"
                   "injections: [{t: 2, stock: A, amount: -30}, {t: 2, stock: B, amount: -30}]\n")
    r = run(m, 4)
    assert r["levels"]["A"] == [9, -22, -23, -24] and r["levels"]["B"] == [9, 0, 0, 0]   # an unsigned one stops at 0


# ---- a flow that reads a flow ----

def test_a_counter_equal_to_another_flows_amount():
    """Restarts = the OOM kills as moved (Poisson, then floored by what is ready): equal every step."""
    m = case_model("stocks: {ready: 3, oom: 0}\nflows:\n  ready -> outside as kill: 0.6 * ready\n  outside -> ready: 2\n"
                   "  outside -> oom as restarts: {rate: \"flow(kill)\", exact: true}\n  oom -> outside: {rate: oom, exact: true}\n")
    r = run(m, 500, {"counts": True}, seed=4)
    assert r["counters"]["restarts"] == r["counters"]["kill"] and sum(r["counters"]["kill"]) > 100
    assert r["levels"]["oom"] == [int(x) for x in r["counters"]["kill"]]
    with pytest.raises(CaseError, match="does not itself read a flow"):
        case_model("stocks: {A: 1}\nflows:\n  outside -> A as a: flow(b)\n  A -> outside as b: flow(a)\n")


# ---- a ceiling that counts the step's outflows ----

def test_a_net_ceiling_holds_at_max_at_dt_1():
    """T fills at 50, drains at 0.1 T, max 200: the plain ceiling settles at 200 / 1.1, a net one at 200."""
    plain = run(case_model("stocks: {T: 0 max=200}\nflows:\n  outside -> T: 50\n  T -> outside: 0.1 * T\n"), 200)["levels"]["T"]
    net = run(case_model("stocks: {T: 0 max=200 net}\nflows:\n  outside -> T: 50\n  T -> outside: 0.1 * T\n"), 200)["levels"]["T"]
    assert plain[-1] == pytest.approx(200 / 1.1, abs=1e-3) and net[-1] == pytest.approx(200, abs=1e-3) and max(net) <= 200
    with pytest.raises(CaseError, match="net is a word of a ceiling"):
        case_model("stocks: {T: 0 net}\nflows:\n  outside -> T: 1\n")


# ---- delays ----

@pytest.mark.parametrize("dt", [1, 0.5, 0.25])
def test_delay_fixed_arrives_exactly_its_time_later(dt):
    """What leaves A in step t arrives at B in step t + 4; B gets the initial rate before that."""
    m = case_model(f"dt: {dt}\ninputs:\n  u: [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]\nstocks: {{B: 0}}\n"
                   "flows:\n  outside -> B: delay_fixed(u, 4, initial=7)\n")
    assert sum(1 for s in m["stocks"] if s["id"].startswith("in_p")) == round(4 / dt)
    r = run(m, 14)
    got = r["counters"]["in_" + str(round(4 / dt))]
    u = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 5, 5, 5]
    assert got == pytest.approx([7] * 4 + u[:10], abs=1e-9)
    t = _truth({**run_model(m), "steps": 14})
    hidden = t.truth()["hidden"]
    assert hidden == [] or hidden[0]["shape"] == "pipe"


def run_model(m: dict) -> dict:
    return {"id": "x", "name": "x", "time_unit": "step", "seed": 1, "steps": 10, "noise": {},
            "stocks": [{"name": s["id"], "unit": "things", **s} for s in m["stocks"]], "flows": [{"name": f["id"], **f} for f in m["flows"]],
            **{k: m[k] for k in ("dt", "inputs") if k in m}}


def test_a_fixed_delay_between_measured_stocks_is_a_pipe_in_the_answer_key():
    m = case_model("stocks: {A: 100, B: 0}\nflows:\n  A -> B: delay_fixed(0.1 * A, 3)\n  B -> outside: 0.2 * B\n")
    t = _truth({**run_model(m), "steps": 50})
    assert t.truth()["hidden"] == [{"from": "A", "to": "B", "via": ["ab_p1", "ab_p2", "ab_p3"], "via_name": "ab_p1, ab_p2, ab_p3", "shape": "pipe",
                                     "order": 3, "delay": 3.0, "what": "ab"}]
    r = run(m, 10)
    A = [100.0] + r["levels"]["A"]
    assert r["counters"]["ab_3"][3:] == pytest.approx([0.1 * A[i] for i in range(7)], abs=1e-3)


def test_a_delay_whose_time_changes():
    """DELAY3 with a time that is an expression: the same as a number while it is constant, and
    each stage drains at 3 / time when it moves."""
    fixed = run(case_model("dt: 0.25\nstocks: {A: 100, C: 0}\nflows:\n  A -> C: delay3(0.1 * A, 6)\n"), 40)
    moving = case_model("dt: 0.25\nstocks: {A: 100, C: 0, K: 6}\nflows:\n  A -> C: delay3(0.1 * A, K)\n")
    assert moving["flows"][1]["rate"] == {"form": "expr", "expr": "3 * ac_d1 / (K)"}
    same = run(moving, 40)
    assert np.allclose(same["levels"]["C"], fixed["levels"]["C"], atol=1e-3)
    grow = case_model("stocks: {A: 100, C: 0, K: 2}\nflows:\n  A -> C: delay3(0.1 * A, K)\n  outside -> K: 0.5\n")
    r = run(grow, 30)
    K = [2] + r["all_levels"]["K"]
    h = [0] + r["all_levels"]["ac_d3"]
    assert r["counters"]["ac_3"][5:] == pytest.approx([3 * h[i] / K[i] for i in range(5, 30)], abs=1e-3)


# ---- TREND / FORECAST ----

def test_trend_and_forecast_follow_pysd():
    """TREND(x, T, g): av' = (x - av) / T from x0 / (1 + g T), trend = zidz(x - av, T |av|);
    FORECAST(x, T, h): av from x0, x (1 + zidz(x - av, T av) h). x = A grows by 2 a step."""
    m = case_model("stocks: {A: 10, D: 0, F: 0}\nflows:\n  outside -> A: 2\n  outside -> D: 100 * trend(A, 5, 0.1)\n"
                   "  outside -> F: forecast(A, 5, 3)\n")
    r = run(m, 30)
    x, av_t, av_f = 10.0, 10 / 1.5, 10.0
    D = F = 0.0
    for t in range(30):
        D += 100 * max(0.0, (x - av_t) / (5 * abs(av_t)))
        F += max(0.0, x * (1 + (x - av_f) / (5 * av_f) * 3))
        av_t, av_f, x = av_t + (x - av_t) / 5, av_f + (x - av_f) / 5, x + 2
        assert r["levels"]["D"][t] == pytest.approx(D, abs=1e-3) and r["levels"]["F"][t] == pytest.approx(F, abs=1e-3)


# ---- the scorer reads 2d truths through the engine (sdlab/ladder/sim.py) ----

def test_a_truth_written_as_an_expression_scores_like_its_linear_form():
    from sdlab.ladder import score
    from sdlab.skill import same_behaviour

    c = {"tolerance": {}}
    tm = run_model(case_model("stocks: {A: 0, B: 0}\nflows:\n  outside -> A: 20\n  A -> B: sqrt(A ^ 2) * 0.3\n  B -> outside: 0.1 * B\n"))
    tm["steps"] = 300
    d = data.simulate(tm, 1, 300)
    right = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 20}}, {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.3}},
             {"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.1}}]
    wrong = [dict(right[0]), {**right[1], "rate": {"form": "proportional", "stock": "A", "k": 0.2}}, dict(right[2])]
    ok, bad = score.equations(c, "none", tm, right, d), score.equations(c, "none", tm, wrong, d)
    assert ok["status"] == "pass", ok
    assert bad["status"] == "fail" and any(r["kind"] == "whole flow" and not r["ok"] for r in bad["parts"])
    assert same_behaviour({"flows": right}, tm, d, horizon=20)["skill"] == pytest.approx(1, abs=1e-6)


def test_the_engine_runs_from_a_recorded_state():
    """run(start=..., t0=...) from the state after step 9 gives steps 10.. of the whole run (sim.truth_end)."""
    m = run_model(case_model("inputs:\n  u: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]\nstocks: {A: 0, x: 1 signed}\n"
                             "flows:\n  outside -> A: sqrt(u + A)\n  outside <-> x: -0.2 * x\n"))
    t = _truth({**m, "steps": 15})
    whole = t.run(steps=15)
    part = t.run(steps=6, start={s: whole["levels"][s][8] for s in t.stock_ids}, t0=10)
    for s in t.stock_ids:
        assert part["levels"][s] == pytest.approx(whole["levels"][s][9:], abs=1e-3)      # (the recorded state is rounded to 4 decimals)


def test_random_expressions_round_trip_through_the_case_format():
    """A rate the case format writes as an expression evaluates as the engine's parser reads the text."""
    rng = random.Random(3)
    for _ in range(60):
        a, b, c = (round(rng.uniform(0.5, 3), 2) for _ in range(3))
        text = rng.choice([f"{a} * A / (B + {b})", f"min({a} * A, B ^ {b})", f"max({c}, A) - {b} * sqrt(B)", f"ceil(A / {c}) * {a}"])
        m = case_model(f"stocks: {{A: 5, B: 2}}\nflows:\n  A -> B: {text}\n")
        r = m["flows"][0]["rate"]
        view = {"A": 5.0, "B": 2.0}
        assert compile_expr(parse(r["expr"]))(view, {}) == pytest.approx(compile_expr(parse(text))(view, {})), text
