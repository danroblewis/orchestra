"""Which stocks what is measured determines (sd/observability.py), on hand-built models."""

import json
import subprocess

import pytest

from orchestra.sd.model import Equation, Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="the observability report needs orchestra[sd]")


def k(stock: str, value: float) -> Equation:
    return Equation("proportional", {"k": value}, "fitted", inputs=[stock])


def c(value: float) -> Equation:
    return Equation("constant", {"c": value}, "fitted")


def measured(sid: str) -> Stock:
    return Stock(sid, sid, series=SeriesRef(f"{sid}_level"))


def hidden(sid: str) -> Stock:
    return Stock(sid, sid, evidence={"hidden": True})


def by_id(r: dict) -> dict:
    return {s["id"]: s for s in r["stocks"]}


def two_stocks(y_measured: bool = False) -> Model:
    """x and y fill and drain on their own; only x is measured, and nothing about y reaches x."""
    return Model("m", "m", stocks=[measured("x"), measured("y") if y_measured else hidden("y")],
                 flows=[Flow("in_x", "in x", None, "x", equations=[c(1.0)]), Flow("out_x", "out x", "x", None, equations=[k("x", 0.1)]),
                        Flow("in_y", "in y", None, "y", equations=[c(1.0)]), Flow("out_y", "out y", "y", None, equations=[k("y", 0.2)])],
                 machines=[Machine("baker", "baker", "program", attributed=["in_x"])])


def test_a_stock_nothing_measured_depends_on_is_undetermined_and_measuring_it_fixes_that():
    from orchestra.sd.observability import report
    r = report(two_stocks(), {"x": 10.0})
    assert not r["observable"] and r["rank"] == 1 and r["states"] == 2
    y = by_id(r)["y"]
    assert not y["determined"] and "no sensor reads it" in y["why"]
    assert y["would_determine"] == ["series on y", "counter on out_y"]
    assert r["directions"] == [{"stocks": {"y": 1.0}, "text": "the level of y alone: no measurement changes when it does"}]
    # its outflow's number multiplies a level nobody can know; its inflow moves nothing determined
    assert {tuple(p["params"]) for p in r["combinations"]} == {("out_y: k on y",), ("in_y: constant",)}
    # the one machine's flow reaches x, not y (structural and weak)
    ctl = r["controllability"]
    assert ctl["movable"] == ["x"] and ctl["unreachable"] == ["y"] and "weak" in ctl["note"]

    r = report(two_stocks(y_measured=True), {"x": 10.0, "y": 5.0})
    assert r["observable"] and r["rank"] == 2 and not r["directions"]


def test_a_counter_on_the_hidden_stocks_outflow_determines_it():
    m = two_stocks()
    m.flow("out_y").counter = SeriesRef("y_out_total")
    from orchestra.sd.observability import report
    r = report(m, {"x": 10.0})
    y = by_id(r)["y"]
    assert r["observable"] and y["determined"]
    assert y["why"] == "y sets the rate of flow out_y (its equation reads it), which counter y_out_total measures"
    assert y["relies_on"] == ["counter y_out_total (flow out_y)"]


def test_a_chain_measured_at_its_end_is_determined_and_says_how():
    m = Model("c", "chain", stocks=[hidden("a"), hidden("b"), measured("z")],
              flows=[Flow("in", "in", None, "a", equations=[c(1.0)]), Flow("ab", "a to b", "a", "b", equations=[k("a", 0.1)]),
                     Flow("bz", "b to z", "b", "z", equations=[k("b", 0.3)]), Flow("out", "out", "z", None, equations=[k("z", 0.5)])])
    from orchestra.sd.observability import lines, report
    r = report(m, {"z": 3.0})
    assert r["observable"] and r["rank"] == 3 and r["generically_observable"]
    a = by_id(r)["a"]
    assert a["determined"]
    assert a["why"] == "a drives b through flow ab; b drives z through flow bz; z is measured by series z_level (the level of z)"
    assert a["relies_on"] == ["series z_level (the level of z)"]
    text = "\n".join(lines(r))
    assert "hidden stock a: determined — a drives b" in text
    # measured at the start instead, nothing downstream reaches it
    m.stocks = [measured("a"), hidden("b"), hidden("z")]
    r = report(m, {"a": 3.0})
    assert [s["id"] for s in r["stocks"] if not s["determined"]] == ["b", "z"]
    assert "series on b" in by_id(r)["b"]["would_determine"]


def test_a_hidden_stock_with_a_constant_outflow_is_undetermined_though_both_its_flows_are_counted():
    # what goes in and out is known, so its changes are; its level is not: nothing depends on it
    m = Model("d", "delay", stocks=[measured("x"), hidden("h")],
              flows=[Flow("xh", "x to h", "x", "h", SeriesRef("xh_total"), [k("x", 0.2)]),
                     Flow("hout", "h out", "h", None, SeriesRef("hout_total"), [c(1.0)]),
                     Flow("in", "in", None, "x", equations=[c(2.0)])])
    from orchestra.sd.observability import report
    r = report(m, {"x": 10.0})
    h = by_id(r)["h"]
    assert not h["determined"] and h["would_determine"] == ["series on h"]


def test_two_hidden_stocks_draining_alike_are_told_apart_only_in_sum_and_that_is_a_coincidence_of_numbers():
    m = Model("e", "equal", stocks=[hidden("p"), hidden("q"), measured("z")],
              flows=[Flow("pz", "p to z", "p", "z", equations=[k("p", 0.3)]), Flow("qz", "q to z", "q", "z", equations=[k("q", 0.3)]),
                     Flow("out", "out", "z", None, equations=[k("z", 0.5)])])
    from orchestra.sd.observability import report
    r = report(m, {"z": 1.0})
    assert r["rank"] == 2 and not r["observable"] and r["generically_observable"]
    assert r["directions"][0]["stocks"] == {"p": 1.0, "q": -1.0}
    assert "coincidence" in by_id(r)["p"]
    m.flow("qz").equations = [k("q", 0.6)]
    assert report(m, {"z": 1.0})["observable"]


def test_numbers_that_show_only_in_combination_are_flagged_until_one_flow_is_counted():
    m = Model("f", "two drains", stocks=[measured("x")],
              flows=[Flow("in", "in", None, "x", equations=[c(2.0)]),
                     Flow("d1", "drain 1", "x", None, equations=[k("x", 0.1)]), Flow("d2", "drain 2", "x", None, equations=[k("x", 0.3)])])
    from orchestra.sd.observability import report
    combos = report(m, {"x": 5.0})["combinations"]
    assert [p["params"] for p in combos] == [["d1: k on x", "d2: k on x"]]
    m.flow("d1").counter = SeriesRef("d1_total")
    assert report(m, {"x": 5.0})["combinations"] == []


def test_a_measured_stock_the_counters_also_determine_is_told_apart_from_one_only_its_series_does():
    m = Model("g", "g", stocks=[measured("x"), measured("y")],
              flows=[Flow("in", "in", None, "x", equations=[c(2.0)]), Flow("out", "out", "x", None, SeriesRef("out_total"), [k("x", 0.1)]),
                     Flow("yin", "y in", None, "y", SeriesRef("yin_total"), [c(1.0)])])
    from orchestra.sd.observability import report
    s = by_id(report(m, {"x": 5.0, "y": 3.0}))
    assert s["x"]["without_its_series"].startswith("x sets the rate of flow out")
    assert s["y"]["without_its_series"] is None


def test_nonlinear_and_floored_rates_are_named_in_the_caveats():
    eff = Equation("proportional", {"k": 0.2}, "discovered", spec={"form": "proportional", "stock": "x", "k": 0.2,
                                                                     "effects": [{"stock": "y", "normal": 4.0, "min": 0.0, "max": 2.0}]})
    floored = Equation("linear", {"c": -5.0, "k": 0.1}, "fitted", inputs=["y"])
    m = Model("n", "n", stocks=[measured("x"), measured("y")],
              flows=[Flow("xy", "x to y", "x", "y", equations=[eff]), Flow("yout", "y out", "y", None, equations=[floored]),
                     Flow("mystery", "?", None, "x", equations=[Equation("expr", {}, "discovered", spec={"form": "unknown"})])])
    from orchestra.sd.linearise import linearise
    from orchestra.sd.observability import report
    lin = linearise(m, {"x": 10.0, "y": 2.0})
    # rate 0.2 × x × y/4: slopes 0.2 × 0.5 on x and 0.2 × 10 / 4 on y
    assert lin.R[0].tolist() == pytest.approx([0.1, 0.5])
    assert lin.R[1].tolist() == [0.0, 0.0]                  # 0.1 × 2 − 5 is below 0: floored
    caveats = "\n".join(report(m, {"x": 10.0, "y": 2.0}, point="here")["caveats"])
    assert "flow xy: its effects are curves" in caveats
    assert "flow yout: its rate is floored at 0 here" in caveats
    assert "taken as outside inputs" in caveats and "mystery" in caveats


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    from orchestra.config import init_project
    return init_project(r)


def test_the_command_and_the_endpoint_report_on_the_current_model(project, capsys):
    from fastapi.testclient import TestClient

    from orchestra.cli import main
    from orchestra.sd.store import ModelStore
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    ModelStore.for_state(project.state_dir).save(two_stocks())
    assert main(["--repo", str(project.repo_root), "sd", "observability"]) == 0
    out = capsys.readouterr().out
    assert "1 of 2 stock levels determined" in out and "hidden stock y: NOT determined" in out
    assert main(["--repo", str(project.repo_root), "sd", "observability", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rank"] == 1
    d = TestClient(create_app(project), headers=bearer(project)).get("/api/dynamics/observability").json()
    assert d["ok"] and d["rank"] == 1 and by_id(d)["y"]["would_determine"] == ["series on y", "counter on out_y"]
