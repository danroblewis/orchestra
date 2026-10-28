"""The equation language (sd/experiments/language.py, forms.py, compile.py): every form the model
holds renders in it, round-trips, and evaluates as SD Lab's own simulator evaluates it; unsafe or
unknown input is refused, saying why."""

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from orchestra.sd.experiments.compile import Frame, compile_rate
from orchestra.sd.experiments.forms import Names, equation_of, flow_text, text_of
from orchestra.sd.experiments.language import EquationError, parse, reference, syntax
from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.rates import numbers
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="the comparisons step SD Lab's simulator (orchestra[sd])")

BAKERY = Path(__file__).parent.parent / "fixtures" / "sd" / "bakery-whatif.json.gz"
STOCKS = ["a", "b", "weird:id"]
INPUTS = ["demand"]


def spec_flow(rate: dict) -> Flow:
    return Flow("f", "f", "a", None, equations=[Equation(rate.get("form"), numbers(rate), "discovered", "sdlab:x", spec=rate)])


SPECS = [
    {"form": "constant", "value": 2.5},
    {"form": "proportional", "stock": "a", "k": 0.3},
    {"form": "linear", "c": 1.0, "terms": [{"stock": "a", "k": 0.2}, {"stock": "demand", "k": -0.1}, {"stock": "weird:id", "k": 0.05}]},
    {"form": "gap", "stock": "b", "goal": 10.0, "time": 4.0},
    {"form": "proportional", "stock": "a", "k": 0.5, "effects": [{"stock": "b", "shape": "linear", "normal": 5.0, "min": 0, "max": 2}]},
    {"form": "constant", "value": 3.0, "effects": [{"stock": "b", "shape": "table", "points": [[0, 0.0], [5, 1.0], [10, 0.5]]}]},
    {"form": "linear", "c": 0.5, "terms": [{"stock": "b", "k": 0.1}],
     "effects": [{"stock": "a", "shape": "linear", "normal": 2.0, "min": 0.5, "max": 1.5}]},
]


def frame(params: dict, n: int = 6, seed: int = 0):
    rng = np.random.default_rng(seed)
    ids = STOCKS + INPUTS
    fr = Frame({**{f"stock:{s}": i for i, s in enumerate(STOCKS)}, "input:demand": len(STOCKS)}, 1.0, n)
    fr.R = rng.uniform(0, 12, (len(ids), n))
    fr.params["f"] = params
    return fr


def names() -> Names:
    return Names(STOCKS, INPUTS)


def round_trip(f: Flow) -> tuple[str, dict]:
    text, params = flow_text(f, names())
    p = parse(text, stocks=STOCKS, inputs=INPUTS, params=params)
    again = text_of(equation_of(p, "test"), f.src, names())
    assert again == (text, params), "what a machine reads is what it would write"
    return text, params


@pytest.mark.parametrize("rate", SPECS, ids=[f"{r['form']}{'+effects' if r.get('effects') else ''}" for r in SPECS])
def test_every_sdlab_form_renders_round_trips_and_evaluates_as_sdlab_does(rate):
    from orchestra.sdlab.discovery.simulate import Model as Stepper

    text, params = round_trip(spec_flow(rate))
    fr = frame(params)
    got = np.maximum(0.0, np.broadcast_to(compile_rate(parse(text, stocks=STOCKS, inputs=INPUTS, params=params), "f")(fr), (6,)))
    probe = Stepper([{"id": "f", "from": None, "to": "\0p", "rate": rate, **({"effects": rate["effects"]} if rate.get("effects") else {})}],
                    STOCKS + INPUTS + ["\0p"])
    want = probe.change(np.vstack([fr.R, np.zeros((1, 6))]), np.zeros(6))[-1]
    assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_sdlab_expressions_sums_and_no_equation_render_as_written():
    from orchestra.sdlab.sdtruth_expr import compile_expr
    from orchestra.sdlab.sdtruth_expr import parse as sd_parse

    expr = {"form": "expr", "expr": "0.5 * min(a, 2 ^ 2 * b) + ceil(demand / 3) * (a > b) + log(b + 1) + and(a, b)",
            "per_step_of_time_unit": 0.25}
    text, params = round_trip(spec_flow(expr))
    assert text.endswith("/ per_step_of_time_unit") and "log10(b + 1)" in text and "and_(a, b)" in text and "2 ** 2" in text
    fr = frame(params)
    got = compile_rate(parse(text, stocks=STOCKS, inputs=INPUTS, params=params), "f")(fr)
    fn = compile_expr(sd_parse(expr["expr"]))
    want = [fn({k: fr.R[i, c] for i, k in enumerate(STOCKS + INPUTS)}, {}) / 0.25 for c in range(6)]
    assert got == pytest.approx(want, rel=1e-12)
    total = {"form": "sum", "parts": [{"form": "constant", "value": 1.0}, {"form": "proportional", "stock": "b", "k": -0.2}]}
    text, params = round_trip(spec_flow(total))
    assert text == "max(0, p1_value) + max(0, p2_k * b)" and params == {"p1_value": 1.0, "p2_k": -0.2}
    assert round_trip(Flow("f", "f", "a", None)) == ("observed()", {})


def test_the_classic_forms_render_as_a_machine_writes_them_and_stay_those_forms():
    for eq, text in ((Equation("constant", {"c": 2.0}, "fitted"), "c"),
                     (Equation("proportional", {"k": 0.1}, "fitted", inputs=["a"]), "k * a"),
                     (Equation("proportional", {"k": 0.1}, "fitted"), "k * a"),
                     (Equation("linear", {"c": 1.0, "k": 0.2}, "fitted", inputs=["input:demand"]), "c + k * demand"),
                     (Equation("linear", {"c": 1.0, "k": 0.2}, "fitted", inputs=["weird:id"]), 'c + k * stock("weird:id")')):
        assert round_trip(Flow("f", "f", "a", None, equations=[eq]))[0] == text
        back = equation_of(parse(text, stocks=STOCKS, inputs=INPUTS, params=eq.params), "experiment x-1 by m")
        assert back.form == eq.form and back.origin == "declared" and back.method == "experiment x-1 by m"
    written = equation_of(parse("k*a", stocks=STOCKS, inputs=INPUTS, params={"k": 1}), "m")
    assert written.form == "expr" and text_of(written, "a", names()) == ("k*a", {"k": 1.0}), "a text written otherwise is kept as written"


def test_every_equation_of_the_bakery_round_trips():
    with gzip.open(BAKERY, "rt") as fh:
        m = Model.from_json(json.load(fh)["model"])
    n = Names.of(m)
    for f in m.flows:
        text, params = flow_text(f, n)
        p = parse(text, stocks=n.stocks, inputs=n.inputs, params=params)
        assert text_of(equation_of(p, "x"), f.src, n) == (text, params)
        assert equation_of(p, "x").form == f.current().form


def test_what_an_equation_reads_is_reported():
    p = parse('k * min(a, cap) + smooth(demand, 5) + stock("weird:id")', stocks=STOCKS, inputs=INPUTS, params={"k": 1.0, "cap": 3.0})
    d = p.describe()
    assert d["reads"] == {"stocks": ["a", "weird:id"], "inputs": ["demand"], "params": ["cap", "k"], "functions": ["min", "smooth", "stock"]}
    assert p.reads() == ["a", "weird:id", "input:demand"]


@pytest.mark.parametrize(("text", "params", "says"), [
    ("__import__('os').system('true')", {}, "unknown function __import__"),
    ("a.__class__", {}, "attribute is not part of the equation language"),
    ("(lambda: 1)()", {}, "unknown function"),
    ("[a for a in b]", {}, "listcomp is not part"),
    ("a[0]", {}, "subscript is not part"),
    ("'text'", {}, "only numbers are constants"),
    ("min(a, key=b)", {}, "takes its arguments in order"),
    ("eval('1')", {}, "unknown function eval"),
    ("a if b else 1", {}, "ifexp is not part"),
    ("1 < a < 2", {}, "one comparison at a time"),
    ("k * nobody", {"k": 1}, "unknown name nobody"),
    ("k * a", {"k": 1, "spare": 2}, "parameter spare not read"),
    ("a +", {}, "does not parse"),
    ("k * a", {"k": float("nan")}, "finite number"),
    ("a", {"a": 1.0}, "parameter a has the name of a stock"),
    ('stock("nope")', {}, "no stock 'nope'"),
    ("lookup(a, [[2, 1], [1, 0]])", {}, "rise in x"),
    ("delay(a, -1)", {}, "tau must be above 0"),
    ("sqrt(a, b)", {}, "sqrt takes 1 argument"),
    ("x" * 5000, {}, "at most 4000 characters"),
])
def test_unsafe_or_unknown_input_is_refused_saying_why(text, params, says):
    with pytest.raises(EquationError, match=says.replace("(", r"\(").replace("[", r"\[")):
        parse(text, stocks=STOCKS, inputs=INPUTS, params=params)


def test_a_name_both_a_stock_and_an_input_must_be_qualified():
    with pytest.raises(EquationError, match='write stock\\("x"\\) or input\\("x"\\)'):
        parse("x", stocks=["x"], inputs=["x"])
    assert parse('stock("x") - input("x")', stocks=["x"], inputs=["x"]).reads() == ["x", "input:x"]
    assert Names(["x"], ["x"]).ref("input:x") == 'input("x")'


def test_syntax_alone_takes_every_other_name_as_a_stock():
    assert syntax("k * min(q, r)", {"k": 1}).stocks == ["q", "r"]
    with pytest.raises(EquationError):
        syntax("open('f')")


def test_numbers_that_are_not_numbers_are_zero_and_counted():
    from orchestra.sd.experiments import engine

    m = Model("m", "m", time_unit="minute", stocks=[Stock("q", "q")],
              flows=[Flow("in", "in", None, "q", equations=[equation_of(parse("log(q)", stocks=["q"]), "t")])])
    r = engine.run(m, t0=0.0, steps=3, step_s=60.0, unit_s=60.0, levels={"q": 0.0})
    assert r.nonfinite == {"in": 3} and r.levels[0, 0, -1] == 0.0, "log(0) moved nothing in any of the 3 steps, and was counted"


def test_the_reference_lists_every_function_and_says_units_are_not_checked():
    ref = reference()
    assert {"min", "max", "abs", "exp", "log", "smooth", "delay", "observed"} <= set(ref["functions"]) and ref["units"] == "not checked"
