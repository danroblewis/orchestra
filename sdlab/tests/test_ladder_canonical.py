"""The canonical cases (sdlab/ladder/canonical/, cases 1NN-canonical-*) and the PySD importer
(sdlab/ladder/pysd_import.py).

Without pysd and sympy (optional packages) only the case files are tested: each states its source and
licence and compiles. With them (`uv run --with pysd --with sympy pytest tests/test_ladder_canonical.py`),
every case file is checked to be exactly what the importer writes from its source model, every import
is checked against PySD's own run, and the importer is checked on small models written here. The ladder's
own checks (every case is sane, the true model passes its own scoring) cover these cases in test_ladder.py.
"""

from __future__ import annotations

import textwrap

import pytest
from sdlab.ladder import cases as casemod
from sdlab.ladder.caseformat import compile_case

CANONICAL = [i for i in casemod.case_ids() if "canonical" in casemod.load(i)["tags"]]


def test_there_are_canonical_cases():
    assert len(CANONICAL) >= 10


@pytest.mark.parametrize("case_id", CANONICAL)
def test_each_canonical_case_states_its_source_and_licence(case_id):
    spec = casemod.spec(case_id)
    assert "source" in spec and ("MIT" in spec["source"]), case_id
    assert spec["tests"]


def test_the_case_format_keeps_a_source_and_it_does_not_change_the_hash():
    head = "title: t\nlevel: 1\ntags: []\ntests: t\nstocks: {A: 5}\nflows:\n  A -> outside: 0.1 * A\n"
    a = compile_case(head)
    b = compile_case(head + "source: somewhere (MIT)\n")
    assert b["source"] == "somewhere (MIT)" and a["model"] == b["model"]


# ---- with pysd and sympy ----

def _need_pysd():
    pytest.importorskip("pysd")
    pytest.importorskip("sympy")


def _recipes():
    from sdlab.ladder.canonical.build import recipes
    return recipes()


@pytest.mark.parametrize("recipe", _recipes(), ids=lambda r: r["id"])
def test_each_case_file_is_the_import_of_its_model_and_matches_pysd(recipe):
    _need_pysd()
    from sdlab.ladder.canonical.build import CASES, build_one

    text, _conv, eq = build_one(recipe)            # raises if blocked or if SD Lab's run differs from PySD's
    assert eq.ok and max(eq.error.values()) < 1e-4
    assert (CASES / f"{recipe['id']}.yaml").read_text() == text, "rebuild: python -m sdlab.ladder.canonical.build"


def _model(tmp_path, body: str, final: int = 40, dt: float = 0.25):
    text = "{UTF-8}\n" + textwrap.dedent(body).strip() + f"""
FINAL TIME = {final}
\t~\tDay\n\t~\t|
INITIAL TIME = 0
\t~\tDay\n\t~\t|
SAVEPER = TIME STEP
\t~\tDay\n\t~\t|
TIME STEP = {dt}
\t~\tDay\n\t~\t|
\\\\\\---/// Sketch information
"""
    p = tmp_path / "m.mdl"
    p.write_text(text)
    return p


def _eq(name, expr):
    return f"{name}=\n\t{expr}\n\t~\t\n\t~\t|\n"


def _stock(name, flows, initial):
    return f"{name}= INTEG (\n\t{flows},\n\t\t{initial})\n\t~\t\n\t~\t|\n"


def _convert(tmp_path, body, **kw):
    from sdlab.ladder.pysd_import import convert, equivalent

    conv = convert(_model(tmp_path, body, **kw))
    return conv, (equivalent(conv) if conv.text else None)


def test_a_move_with_a_gap_a_lookup_effect_and_max_0_round_trips(tmp_path):
    _need_pysd()
    body = (_stock("A", "-Move", 100) + _stock("B", "Move+Fill-Drain", 10)
            + _eq("Move", "MAX(0, 0.2*A*Effect(B))") + _eq("Fill", "(50-B)/4") + _eq("Drain", "B/8")
            + "Effect(\n\t[(0,0)-(100,2)],(0,1),(50,0.5),(100,0.2))\n\t~\t\n\t~\t|\n")
    conv, eq = _convert(tmp_path, body)
    assert conv.text and eq.ok, (conv.blocked, eq)
    assert "A -> B as move: \"0.2 * A * effect(B, table, [[0, 1], [50, 0.5], [100, 0.2]])\"" in conv.text
    assert "(50 - B) / 4" in conv.text


def test_a_delay3_between_two_stocks_becomes_one_material_delay(tmp_path):
    _need_pysd()
    body = (_stock("A", "Inflow-Leaving", 50) + _stock("B", "Arriving-Out", 0) + _eq("Inflow", "5")
            + _eq("Leaving", "A/10") + _eq("Arriving", "DELAY3(Leaving, 6)") + _eq("Out", "B/5"))
    conv, eq = _convert(tmp_path, body, final=60)
    assert eq.ok, eq
    assert "A -> B as arriving: \"delay3(0.1 * A, 6, initial=10)\"" in conv.text
    assert "leaving" not in conv.text                           # merged into the delay


def test_a_smooth_of_a_stock_is_a_smooth_reader(tmp_path):
    _need_pysd()
    body = (_stock("A", "Inflow-Out", 10) + _eq("Inflow", "3") + _eq("Out", "0.5*SMOOTH(A, 4)"))
    conv, eq = _convert(tmp_path, body)
    assert eq.ok, eq
    assert "smooth(A, 4, initial=10)" in conv.text


def test_steps_and_pulses_of_time_are_measured_inputs(tmp_path):
    _need_pysd()
    body = _stock("A", "Inflow-Out", 0) + _eq("Inflow", "2+STEP(3, 10)+PULSE(20, 2)") + _eq("Out", "A/5")
    conv, eq = _convert(tmp_path, body)
    assert eq.ok, eq
    assert conv.drivers == ["PULSE", "STEP"] and "inputs:" in conv.text


@pytest.mark.parametrize("expr,feature", [
    ("SQRT(A)", "SQRT"), ("MIN(A, 3)", "MIN / MAX"), ("IF THEN ELSE(A > 5, 1, 0)", "IF THEN ELSE"),
    ("A/B", "division by a stock (a ratio)"), ("EXP(A/100)", "EXP / LN / LOG"), ("A^0.5", "a non-integer power"),
    ("DELAY FIXED(A, 3, 0)", "fixed delay (DELAY FIXED)"),
])
def test_what_cannot_be_held_is_named(tmp_path, expr, feature):
    _need_pysd()
    body = _stock("A", "Inflow-Out", 10) + _stock("B", "Out", 5) + _eq("Inflow", "2") + _eq("Out", expr)
    conv, _ = _convert(tmp_path, body)
    assert conv.text is None and feature in conv.features, conv.blocked


def test_a_two_way_flow_converts_but_differs_and_says_why(tmp_path):
    _need_pysd()
    body = _stock("A", "Net", 10) + _eq("Net", "5-0.5*A+3*SIN(Time)")       # goes negative once A is above 10 + ...
    conv, eq = _convert(tmp_path, body, final=30)
    assert conv.text is not None and not eq.ok and eq.reason.startswith("a two-way flow"), eq


def test_the_full_world3_pollution_sector_is_blocked_by_its_ratio():
    _need_pysd()
    from sdlab.ladder.canonical.build import MODELS
    from sdlab.ladder.pysd_import import convert

    conv = convert(MODELS / "world3-pollution-full.mdl")
    assert conv.text is None and conv.features == ["division by a stock (a ratio)"]
