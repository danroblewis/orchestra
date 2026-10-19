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


# (SQRT, MIN, IF THEN ELSE, a ratio, EXP, a power and DELAY FIXED of a stock were named here as missing
# until queue item 2d; they convert now: the tests after this one)
@pytest.mark.parametrize("expr,feature", [
    ("RANDOM UNIFORM(0, A, 1)", "random functions"), ("STEP(A, 5)", "STEP / PULSE / RAMP of a stock"),
])
def test_what_cannot_be_held_is_named(tmp_path, expr, feature):
    _need_pysd()
    body = _stock("A", "Inflow-Out", 10) + _stock("B", "Out", 5) + _eq("Inflow", "2") + _eq("Out", expr)
    conv, _ = _convert(tmp_path, body)
    assert conv.text is None and feature in conv.features, conv.blocked


# ---- the engine features of queue item 2d ----

@pytest.mark.parametrize("expr,text", [
    ("SQRT(A)", "sqrt(A)"), ("MIN(A, 3)", "min(A, 3)"), ("IF THEN ELSE(A > 5, 1, 0)", "if_then_else((A > 5), 1, 0)"),
    ("A/B", "(A / (B))"), ("EXP(A/100)", "exp((0.01 * A))"), ("A^0.5", "(A ^ 0.5)"),
])
def test_a_rate_without_a_linear_form_is_an_expression(tmp_path, expr, text):
    _need_pysd()
    body = _stock("A", "Inflow-Out", 10) + _stock("B", "Out", 5) + _eq("Inflow", "2") + _eq("Out", expr)
    conv, eq = _convert(tmp_path, body)
    assert conv.text is not None and eq.ok, (conv.blocked, eq)
    assert f'A -> B as out: "{text}"' in conv.text, conv.text


def test_delay_fixed_into_a_stock_is_a_pipe_and_out_of_one_a_delayed_reader(tmp_path):
    _need_pysd()
    body = (_stock("A", "Inflow-Leaving", 50) + _stock("B", "Arriving-Out", 0) + _eq("Inflow", "5") + _eq("Leaving", "A/10")
            + _eq("Arriving", "DELAY FIXED(Leaving, 3, 2)") + _eq("Out", "B/5"))
    conv, eq = _convert(tmp_path, body, final=40)
    assert eq.ok, eq
    assert 'A -> B as arriving: "delay_fixed(0.1 * A, 3, initial=2)"' in conv.text
    body = _stock("A", "Inflow-Out", 10) + _stock("B", "Out", 5) + _eq("Inflow", "2+STEP(3, 5)") + _eq("Out", "DELAY FIXED(A, 3, 0)")
    conv, eq = _convert(tmp_path, body, final=40)
    assert eq.ok, eq
    assert 'A <-> B as out: "delayed(A, 3, initial=0)"' in conv.text          # (A goes negative, and so does the delayed A)


def test_trend_and_forecast_are_a_smoothing_and_an_expression(tmp_path):
    _need_pysd()
    body = (_stock("A", "Inflow", 10) + _stock("T", "Tr", 0) + _stock("F", "Fc", 0) + _eq("Inflow", "1+STEP(2, 8)")
            + _eq("Tr", "TREND(A, 4, 0.1)") + _eq("Fc", "FORECAST(A, 4, 2)"))
    conv, eq = _convert(tmp_path, body, final=30)
    assert eq.ok, eq
    assert "zidz(" in conv.text and "smooth(A, 4, initial=" in conv.text


def test_a_two_way_flow_and_a_signed_stock_convert_exactly(tmp_path):
    _need_pysd()
    body = _stock("A", "Net", 10) + _eq("Net", "5-0.5*A+3*SIN(Time)")       # goes negative once A is above 10 + ...
    conv, eq = _convert(tmp_path, body, final=30)
    assert conv.text is not None and eq.ok, eq
    assert "outside <-> A as net:" in conv.text
    body = _stock("X", "Vx", 1) + _stock("V", "Ax", 0) + _eq("Vx", "V") + _eq("Ax", "-0.25*X")      # a spring
    conv, eq = _convert(tmp_path, body, final=30)
    assert conv.text is not None and eq.ok, eq
    assert "X: 1 signed" in conv.text and "V: 0 signed" in conv.text


def test_the_floor_is_lifted_only_where_euler_has_none(tmp_path):
    """Births 200, aging out 300 from 1000: SD Lab's floor cuts the last step's outflow, Euler does not;
    convert_checked makes that stock signed and no other."""
    _need_pysd()
    from sdlab.ladder.pysd_import import convert_checked

    body = _stock("P", "Births-Aging", 1000) + _stock("Q", "Aging-Out", 10) + _eq("Births", "200") + _eq("Aging", "300") + _eq("Out", "Q/10")
    conv, eq = convert_checked(_model(tmp_path, body, final=10, dt=1))
    assert eq.ok, eq
    assert "P: 1000 signed" in conv.text and "Q: 10\n" in conv.text


def test_the_full_world3_pollution_sector_converts_now():
    _need_pysd()
    from sdlab.ladder.canonical.build import MODELS
    from sdlab.ladder.pysd_import import convert, equivalent

    conv = convert(MODELS / "world3-pollution-full.mdl")
    assert conv.text is not None and equivalent(conv).ok


# ---- arrays, macros, external data, DELAY N / SMOOTH N (queue item 2c) ----

def _sub(name, elements):
    return f"{name}:\n\t{elements}\n\t~\t\n\t~\t|\n"


def test_a_subscripted_aging_chain_flattens_into_one_stock_per_element(tmp_path):
    _need_pysd()
    body = (_sub("Age", "young, adult, old") + _sub("Older", "adult, old") + _sub("Prev", "young, adult -> Older")
            + "Pop[young]= INTEG (\n\tBirths-Aging[young],\n\t\t100)\n\t~\t\n\t~\t|\n"
            + "Pop[Older]= INTEG (\n\tAging[Prev]-Aging[Older],\n\t\t50)\n\t~\t\n\t~\t|\n"
            + _eq("Aging[Age]", "Pop[Age]/Duration[Age]") + _eq("Duration[Age]", "5, 10, 20")
            + _eq("Births", "0.02*SUM(Pop[Age!])"))
    conv, eq = _convert(tmp_path, body, dt=1)
    assert eq is not None and eq.ok, (conv.blocked, eq)
    assert list(conv.stocks) == ["Pop__young", "Pop__adult", "Pop__old"]
    assert conv.stocks["Pop__adult"] == "Pop[adult]"                    # PySD's own name of the element
    assert "Pop__young -> Pop__adult as aging_young: \"0.2 * Pop__young\"" in conv.text
    assert "Pop__adult -> Pop__old as aging_adult: \"0.1 * Pop__adult\"" in conv.text
    assert "Pop__old -> outside as aging_old: \"0.05 * Pop__old\"" in conv.text
    assert "outside -> Pop__young as births: \"0.02 * Pop__adult + 0.02 * Pop__old + 0.02 * Pop__young\"" in conv.text


def test_a_vector_function_is_named_not_flattened(tmp_path):
    _need_pysd()
    body = (_sub("Dim", "a, b") + _stock("A", "Inflow", 1) + _eq("Inflow", "VECTOR SELECT(Sel[Dim!], V[Dim!], 0, 0, 0)")
            + _eq("Sel[Dim]", "1, 0") + _eq("V[Dim]", "2, 3"))
    conv, _ = _convert(tmp_path, body, dt=1)
    assert conv.text is None and any(f.startswith("vector and matrix functions") for f in conv.features), conv.blocked


def _macro(name, params, body):
    return f":MACRO: {name}({params})\n{body}\t~\t\n\t~\t|\n\n:END OF MACRO:\n"


def test_macros_are_inlined_and_a_stock_inside_one_is_a_stock_of_the_model(tmp_path):
    _need_pysd()
    body = (_macro("DOUBLE", "x", "DOUBLE = 2 * x\n") + _macro("FILL", "input", "FILL = INTEG(input, 0)\n")
            + _stock("A", "Inflow-Out", 10) + _eq("Inflow", "DOUBLE(1.5) + 0.01 * Total out") + _eq("Out", "A/5")
            + _eq("Total out", "FILL(Out)"))
    conv, eq = _convert(tmp_path, body, dt=1)
    assert eq is not None and eq.ok, (conv.blocked, eq)
    (sid,) = [s for s in conv.stocks if s != "A"]
    assert f"outside -> A as inflow: \"3 + 0.01 * {sid}\"" in conv.text
    assert "fill" in sid.lower() and f"outside -> {sid}" in conv.text and "\"0.2 * A\"" in conv.text
    assert conv.model.stocks[sid]["column"] == "Total out"                 # measured through the auxiliary that shows it


def test_a_delay_n_of_order_2_is_two_hidden_stocks_as_delay3_writes_three(tmp_path):
    _need_pysd()
    body = (_stock("A", "Inflow-Leaving", 50) + _stock("B", "Arriving-Out", 0) + _eq("Inflow", "5")
            + _eq("Leaving", "A/10") + _eq("Arriving", "DELAY N(Leaving, 6, Leaving, 2)") + _eq("Out", "B/5"))
    conv, eq = _convert(tmp_path, body, final=60, dt=1)
    assert eq is not None and eq.ok, (conv.blocked, eq)
    assert "A -> arriving_d1 as arriving: \"0.1 * A\"" in conv.text
    assert "arriving_d1 -> arriving_d2 as arriving_1: \"0.3333333333333333 * arriving_d1\"" in conv.text
    assert "arriving_d2 -> B as arriving_2: \"0.3333333333333333 * arriving_d2\"" in conv.text
    assert "arriving_d1: 15 hidden" in conv.text and "leaving" not in conv.text


def test_a_smooth_n_of_order_4_is_four_hidden_stages_with_exact_flows(tmp_path):
    _need_pysd()
    body = _stock("A", "Inflow-Out", 10) + _eq("Inflow", "3") + _eq("Out", "0.1*SMOOTH N(A, 8, A, 4)")
    conv, eq = _convert(tmp_path, body, final=60, dt=1)
    assert eq is not None and eq.ok, (conv.blocked, eq)
    assert "SM_1_4: 10 hidden" in conv.text
    assert "outside -> SM_1_1 as SM_1_1_in: {rate: \"0.5 * A\", exact: true}" in conv.text
    assert "A -> outside as out: \"0.1 * SM_1_4\"" in conv.text


def test_external_data_becomes_a_measured_input_and_constants_numbers(tmp_path):
    _need_pysd()
    (tmp_path / "data.csv").write_text("time,demand\n0,4\n5,6\n10,5\n20,8\n")
    (tmp_path / "k.csv").write_text("k\n0.25\n")
    body = (_stock("A", "Inflow-Out", 10) + _eq("Inflow", "Demand") + _eq("Out", "K*A")
            + "Demand:=\n\tGET DIRECT DATA('data.csv', ',', 'A', 'B2')\n\t~\t\n\t~\t|\n"
            + "K:=\n\tGET DIRECT CONSTANTS('k.csv', ',', 'A2')\n\t~\t\n\t~\t|\n")
    conv, eq = _convert(tmp_path, body, final=20, dt=1)
    assert eq is not None and eq.ok, (conv.blocked, eq)
    assert "demand: [4, 4.4, 4.8, 5.2, 5.6, 6" in conv.text                # PySD's values, one per step
    assert "A -> outside as out: \"0.25 * A\"" in conv.text and conv.drivers == ["LOOKUP"]


def test_existing_case_text_is_unchanged_by_the_new_features():
    """Arrays, macros, data and DELAY N only add: every canonical case still rebuilds to its file
    (the parametrized test above checks each); here the rendering of a delay3 case is unchanged."""
    _need_pysd()
    from sdlab.ladder.canonical.build import CASES, build_one

    r = next(r for r in _recipes() if r["id"].startswith("105"))
    assert build_one(r)[0] == (CASES / f"{r['id']}.yaml").read_text()
