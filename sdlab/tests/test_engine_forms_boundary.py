"""engine_forms inside the declared boundary (its copy of kalman_lna in _kalman/ carries the boundary hooks;
judge.improve offers no form that leaves the boundary; the answer through _kalman/boundary.apply)."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.engine_forms._kalman import boundary as bd
from sdlab.discovery.strategies.engine_forms.judge import _shape

STOCKS = [{"id": "A", "unit": "x"}, {"id": "B", "unit": "x"}]
DECLARED = {"boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}


def _chain(T: int = 300, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    A, B = [10.0], [5.0]
    for _ in range(T):
        a, b = A[-1], B[-1]
        A.append(a + 20 - 0.4 * a + rng.normal(0, 0.3))
        B.append(b + 0.4 * a - 0.2 * b + rng.normal(0, 0.3))
    return {"t": list(range(T + 1)), "levels": {"A": A, "B": B}}


def test_a_form_that_drains_a_tied_source_counts_as_outside():
    move = {"from": "A", "to": "B", "ratio": 1, "rate": {"form": "proportional", "stock": "A", "k": 0.4}}
    form = type("F", (), {"flows": [{"from": None, "to": "B", "ratio": 1, "rate": {"form": "constant", "value": 4.0}}]})()
    shaped = _shape([move], [0], form, "B", ["A", "B"])          # the move into B replaced: A -> outside, outside -> B
    assert len(bd.violations(shaped, ["A", "B"], bd.Boundary(DECLARED), set())) == 2


def test_engine_forms_stays_inside_the_boundary():
    r = load("engine_forms")(STOCKS, {**_chain(), **DECLARED}, {})
    assert not bd.violations(r["flows"], ["A", "B"], bd.Boundary(DECLARED), set()), r["flows"]
    assert r["boundary"]["declared"] and r["boundary_claims"] == []


def _run_case(case: str, variant: str = "none-short") -> dict:
    from sdlab.ladder import cases as casemod, data, runner
    c = casemod.load(case)
    return runner.discover("engine_forms", casemod.truth_model(c, variant), {**data.load(c, variant), **casemod.announced(c)})


def test_a_chosen_form_is_checked_against_the_boundary():
    # judge.improve once named its drained flows `outside`, shadowing the boundary counter it then
    # called: "'list' object is not callable" on every cell where a form was chosen (14 cells of job 130)
    trace = _run_case("102-canonical-bass")["engine_forms"]["trace"]
    assert any("chosen" in t for t in trace), trace


def test_a_form_that_leaves_the_boundary_is_undone():
    # judge.improve refuses such a form before it is weighed ("leaves the declared boundary") or, when
    # only the chosen rewrite leaves it, undoes it ("undone"); either way it is never chosen
    trace = _run_case("196-concave-move-between-tanks")["engine_forms"]["trace"]
    left = [t.split(":")[0] for t in trace if "leaves the declared boundary" in t]
    assert left, trace
    assert not any(t.startswith(f"{x}:") and "chosen" in t for x in left for t in trace), trace
