"""Strategy earned_pieces (docs/research/earned-pieces.md): a stock's outside inflow changes only where
the data earns it, and a drain is shared with the stocks that receive it.

On the ladder's short noisy runs the matrix gives a stock with no outside inflow chance pieces (004:
C gets 9, a spurious link from B and a drain of 0.171 against 0.1), and a stock with a constant
inflow chance pieces that bias its drain (002 long: 0.21 against 0.1). earned_pieces passes them,
keeps a real unannounced step (020) and a drain split between a receiver and outside (006), and
still finds an intake that changes every 30 steps (the sd-pipeline shape).
"""

from __future__ import annotations

import numpy as np
import pytest
from synth import generate

from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.earned_pieces.rows import white
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


def ladder(case_id: str, variant: str, strategy: str) -> tuple[dict, dict]:
    case = casemod.load(case_id)
    model = casemod.truth_model(case, variant)
    d = data.load(case, variant)
    opts = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    r = load(strategy)(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, opts)
    return r, score.equations(case, casemod.variant(case, variant)["noise"], model, r["flows"], d)


def row(r: dict, sid: str) -> dict:
    return next(x for x in r["matrix"] if x["id"] == sid)


def test_a_stock_with_no_outside_inflow_gets_no_pieces():
    base, s0 = ladder("004-chain-3", "counts-short", "matrix")
    assert s0["status"] == "fail" and len(row(base, "C")["inflow"]) > 1
    r, s = ladder("004-chain-3", "counts-short", "earned_pieces")
    assert s["status"] == "pass"
    c = row(r, "C")
    assert len(c["inflow"]) <= 1 and abs(-c["coef"]["C"] - 0.1) <= 0.02


def test_a_constant_inflow_keeps_one_piece_and_its_drain():
    r, s = ladder("002-inflow-outflow", "counts-long", "earned_pieces")
    assert s["status"] == "pass"
    a = row(r, "A")
    assert len(a["inflow"]) == 1 and abs(-a["coef"]["A"] - 0.1) <= 0.01


def test_an_exit_beside_a_move_is_kept_when_the_rows_together_say_so():
    _, s0 = ladder("006-chain-exit-middle", "counts-short", "matrix")
    assert s0["status"] == "fail"
    r, s = ladder("006-chain-exit-middle", "counts-short", "earned_pieces")
    assert s["status"] == "pass" and any(f["from"] == "A" and f["to"] is None for f in r["flows"])


def test_a_real_unannounced_step_is_kept():
    for variant in ("none-short", "counts-short", "counts-long"):
        r, s = ladder("020-unannounced-step", variant, "earned_pieces")
        assert s["status"] == "pass", variant
        assert len(row(r, "A")["inflow"]) >= 3, variant


P = lambda a, b, k: {"id": f"{a}_{b}", "from": a, "to": b, "rate": {"form": "proportional", "stock": a, "k": k}}  # noqa: E731
INTAKE = {"every": 120, "changes": [{"t": t, "set": {"intake": {"form": "constant", "value": v}}} for t, v in ((1, 5), (31, 9), (61, 3), (91, 6))]}


@pytest.fixture(scope="module")
def pipeline():
    return generate(stocks=[{"id": "inbox", "initial": 30}, {"id": "b", "initial": 40}, {"id": "c", "initial": 50}],
                    flows=[{"id": "intake", "from": None, "to": "inbox", "rate": {"form": "constant", "value": 5}},
                           P("inbox", "b", 0.3), P("b", "c", 0.2), {"id": "c_out", "from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.2}}],
                    steps=2000, schedule=INTAKE)


def test_an_intake_that_changes_every_30_steps_keeps_its_pieces(pipeline):
    """Each change is too weak to pay a textbook price, but a constant intake leaves a slow pattern
    in the inbox's residuals, so the pieces stay; the inbox's drain is what b receives."""
    r = load("earned_pieces")(pipeline["stocks"], pipeline["run"], {"eras": pipeline["eras"]})
    inbox, c = row(r, "inbox"), row(r, "c")
    assert len(inbox["inflow"]) >= 40 and abs(-inbox["coef"]["inbox"] - 0.3) <= 0.02
    assert len(c["inflow"]) <= 1 and abs(c["coef"]["b"] - 0.2) <= 0.01


def test_whiteness():
    rng = np.random.default_rng(0)
    e = rng.normal(0, 1, 2000)
    assert white(e)
    slow = np.repeat(rng.normal(0, 0.5, 2000 // 30 + 1), 30)[:2000]
    assert not white(e + slow)


# measured inputs (opts "inputs"): a flow on an input is a column of every fit and moves what the
# input says in every simulation, so its effect is in the model once (before the fix, earned_pieces
# stepped its models without the inputs and counted the pump, or the outside temperature, twice)

def _input_cell(case_id, variant):
    from sdlab.ladder import runner

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    return c, model, d, runner.discover("earned_pieces", model, d)


@pytest.mark.parametrize("variant", ["none-long", "counts-long"])
def test_a_measured_pump_is_read_once(variant):
    c, model, d, r = _input_cell("062-tank-fed-by-measured-pump", variant)
    s = score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)
    assert s["status"] == "pass", r["flows"]
    pump = [f for f in r["flows"] if f.get("to") == "T" and "pump" in str(f.get("rate"))]
    assert len(pump) == 1 and pump[0]["rate"]["terms"][0]["k"] == pytest.approx(2.0, rel=0.03)
    assert not any(f.get("to") == "T" and f.get("inflow") for f in r["flows"]), "no outside pieces beside the pump"


def test_cooling_to_a_measured_outside_temperature_is_read_once():
    from sdlab.ladder import physics

    c, _, d, r = _input_cell("phys-newton-cooling", "none-long")
    s = physics.score_found(c, "none-long", r["flows"], d, data.load(c, "none-long", fresh=True))
    assert s["status"] == "pass", r["flows"]
    drain = sum(f["rate"]["k"] for f in r["flows"] if f.get("from") == "T" and (f.get("rate") or {}).get("stock") == "T")
    warm = sum(t["k"] for f in r["flows"] if f.get("to") == "T" for t in (f.get("rate") or {}).get("terms") or [] if t["stock"] == "outside")
    assert drain == pytest.approx(warm, rel=0.05), "one k: the body warms toward the outside as fast as it cools"
