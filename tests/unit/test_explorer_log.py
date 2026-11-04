"""The explorer's experiment log (``sd/explorer.py``, ``orchestra explorer log``): an experiment
recorded before its effect with the last discovery run, judged by the runs since with their stocks,
trust, fits and store cost from the run record, listed; and the run record's numbers it reads
(``sd/runs.result_of``)."""

from __future__ import annotations

import json
import subprocess

import pytest

from orchestra import cli
from orchestra.config import init_project
from orchestra.sd.explorer import ExperimentError, ExperimentLog
from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.runs import result_of
from orchestra.sd.store import ModelStore

T = 1_800_000_000.0


def run(i, at, stocks, trust, fitted, r2, requests):
    return {"id": f"r{i}", "kind": "discovery", "trigger": "schedule", "started": at - 30, "ended": at, "duration_s": 30.0,
            "outcome": "saved v1", "cost": {"chrono": {"requests": requests}},
            "result": {"stocks": stocks, "flows": stocks * 2, "left_out": 4, "trust": trust, "fitted": fitted, "r2": r2}}


@pytest.fixture
def store(tmp_path):
    s = ModelStore.for_state(tmp_path)
    log = s.runs()
    log.append(run(1, T - 600, 2, 0.4, 3, 0.7, 40))
    log.append({"id": "r1~infer-chrono", "kind": "inference", "started": T - 500, "ended": T - 400, "cost": {}})
    log.append(run(2, T - 300, 2, 0.5, 3, 0.72, 41))
    return s


def test_add_records_the_change_the_expectation_and_the_run_before(store):
    log = store.explorer()
    assert isinstance(log, ExperimentLog) and log.path == store.dir / "explorer.jsonl"
    e = log.add('{"source": "chrono", "match": ["{namespace=\\"payments\\"}"]}', "the backlog gets its ack rate as an outflow", now=T)
    assert e["change"] == {"source": "chrono", "match": ['{namespace="payments"}']} and e["by"] == "explorer"
    assert e["before"] == {"id": "r2", "ended": T - 300, "outcome": "saved v1", "stocks": 2, "flows": 4, "left_out": 4, "trust": 0.5,
                           "fitted": 3, "r2": 0.72, "requests": {"chrono": 41}}
    assert e["verdict"] is None and [x["id"] for x in log.entries()] == [e["id"]]


def test_judge_fills_the_runs_since_and_the_effect(store):
    log = store.explorer()
    e = log.add({"source": "chrono", "split": ["subscription_id"]}, "a stock per subscription", now=T)
    with pytest.raises(ExperimentError, match="no discovery run has ended since"):
        log.judge(e["id"], "kept", "more stocks", now=T + 10)
    store.runs().append(run(3, T + 300, 3, 0.6, 5, 0.8, 55))
    store.runs().append(run(4, T + 600, 4, 0.62, 6, 0.81, 60))
    j = log.judge(e["id"], "kept", "two stocks more, trust up", now=T + 700)
    assert j["rounds"] == ["r3", "r4"] and j["before"]["id"] == "r2" and j["after"]["id"] == "r4"
    assert j["effect"] == {"stocks": 2, "flows": 4, "left_out": 0, "trust": 0.12, "fitted": 3, "r2": 0.09, "requests": 19}
    assert j["verdict"] == "kept" and j["why"] == "two stocks more, trust up" and j["judged"] == T + 700
    [kept] = log.entries()
    assert kept == j


def test_refusals_say_why(store):
    log = store.explorer()
    for change, expect, why in (("not json", "x", "not JSON"), ("[]", "x", "JSON object"), ("{}", "x", "JSON object"),
                                ('{"a": 1}', " ", "--expect")):
        with pytest.raises(ExperimentError, match=why):
            log.add(change, expect, now=T)
    e = log.add({"a": 1}, "something", now=T)
    with pytest.raises(ExperimentError, match="--verdict"):
        log.judge(e["id"], "great", "x")
    with pytest.raises(ExperimentError, match="no experiment"):
        log.judge("nope", "kept", "x")
    assert log.judge(e["id"], "inconclusive", "no run yet", now=T + 1)["after"] is None


def test_result_of_counts_trust_and_fits():
    m = Model("m", "m")
    m.stocks = [Stock("a", "a", evidence={"trust": {"score": 0.8}}), Stock("b", "b", evidence={"trust": {"score": 0.4}}), Stock("c", "c")]
    f1, f2 = Flow("f1", "f1", None, "a"), Flow("f2", "f2", "a", None)
    f1.equations = [Equation("constant", {"c": 1.0}, origin="fitted", quality={"r2": 0.9})]
    f2.equations = [Equation("constant", {"c": 1.0}, origin="declared")]
    m.flows = [f1, f2]
    assert result_of(m) == {"stocks": 3, "flows": 2, "left_out": 0, "trust": 0.6, "fitted": 1, "r2": 0.9}


def test_the_command_adds_judges_and_lists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    p = init_project(repo)
    runs = ModelStore.for_state(p.state_dir).runs()
    runs.append(run(1, 1000.0, 1, 0.3, 1, 0.5, 10))
    base = ["--repo", str(repo), "explorer", "log"]
    assert cli.main([*base, "add", "--change", '{"source": "s", "kinds": {"x": "level"}}', "--expect", "x becomes a stock", "--json"]) == 0
    e = json.loads(capsys.readouterr().out)
    assert e["before"]["id"] == "r1"
    assert cli.main([*base, "judge", e["id"], "--verdict", "reverted", "--why", "x"]) == 1
    assert "no discovery run has ended since" in capsys.readouterr().err
    runs.append(run(2, e["t"] + 1, 1, 0.2, 1, 0.4, 12))
    assert cli.main([*base, "judge", e["id"], "--verdict", "reverted", "--why", "trust fell"]) == 0
    assert "reverted, after 1 run(s); effect" in capsys.readouterr().out
    assert cli.main([*base, "list"]) == 0
    out = capsys.readouterr().out
    assert e["id"] in out and "reverted" in out and "expect: x becomes a stock" in out and "why: trust fell" in out
    assert cli.main([*base, "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["verdict"] == "reverted"
