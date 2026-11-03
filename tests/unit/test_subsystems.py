"""Subsystems: the one model's parts partitioned by a label its series carry, derived and display
only (docs/proposals/subsystems.md, step 1)."""

import subprocess

from orchestra.config import init_project
from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore
from orchestra.sd.subsystems import subsystems
from orchestra.web.dynamics import model_view


def pile(sid, wf, step, writer="workflows.piles"):
    return Stock(sid, sid, series=SeriesRef("workflow_pile_items", {"instrument": writer, "machine": "floor",
                                                                     "workflow": wf, "step": step}))


def model():
    stocks = [pile("a1", "hotfix", "write"), pile("a2", "hotfix", "review"),
              pile("b1", "delivery", "write"), pile("b2", "delivery", "review"),
              Stock("disk", "disk", series=SeriesRef("disk_free_bytes", {"machine": "telemetry"})),
              Stock("hidden", "hidden", evidence={"level": {"name": "between", "labels": {"workflow": "delivery"}}})]
    hyp = lambda *ms: {"machines": {"hypotheses": [{"machine": m} for m in ms]}}
    flows = [Flow("in_a", "in", None, "a1", evidence=hyp("planner")),
             Flow("a1_a2", "x", "a1", "a2", evidence=hyp("worker")),
             Flow("b1_b2", "x", "b1", "b2", evidence=hyp("worker")),
             Flow("b2_h", "x", "b2", "hidden"),
             Flow("a2_b1", "x", "a2", "b1", evidence=hyp("reviewer")),
             Flow("sim", "x", "b2", "a1", evidence={"simulated": True}),
             Flow("b2_disk", "x", "b2", "disk", evidence=hyp("cleaner")),
             Flow("old", "x", "b1", None)]
    machines = [Machine("planner", "planner", "machine"), Machine("worker", "worker", "machine"),
                Machine("reviewer", "reviewer", "machine"), Machine("cleaner", "cleaner", "machine"),
                Machine("legacy", "legacy", "machine", attributed=["old"]), Machine("idle", "idle", "machine")]
    return Model("m", "m", stocks=stocks, flows=flows, machines=machines)


def test_a_label_the_series_carry_partitions_stocks_flows_and_machines():
    out = subsystems(model())
    by = {p["label"]: p for p in out["partitions"]}
    # who wrote a series is never a subsystem (rule 7), nor Orchestra's own flags
    assert set(by) == {"workflow", "step"}
    wf = by["workflow"]
    groups = {g["value"]: g for g in wf["groups"]}
    assert groups["hotfix"]["stocks"] == ["a1", "a2"] and groups["delivery"]["stocks"] == ["b1", "b2", "hidden"]
    assert wf["unassigned"]["stocks"] == ["disk"]                       # no such label: outside every box
    # a flow from outside belongs to its stock's group; a flow to an unassigned stock crosses nothing
    assert groups["hotfix"]["flows"] == ["in_a", "a1_a2"] and groups["delivery"]["flows"] == ["b1_b2", "b2_h", "old"]
    assert wf["unassigned"]["flows"] == ["b2_disk"]
    # the separation measure: crossing flows per pair, the simulated counted apart
    assert wf["crossing"] == [{"between": ["delivery", "hotfix"], "flows": ["a2_b1", "sim"], "count": 1, "simulated": 1, "simulated_flows": ["sim"]}]
    assert (wf["joined"], wf["crossed"], wf["crossed_simulated"]) == (3, 1, 1)
    # machines only by their hypotheses: one group (a flow to an unassigned stock places it by its
    # other end), spanning several, or none (the old attributed list too)
    assert groups["hotfix"]["machines"] == ["planner"] and groups["delivery"]["machines"] == ["cleaner", "legacy"]
    assert {s["machine"]: s["groups"] for s in wf["spanning"]} == {"worker": ["delivery", "hotfix"], "reviewer": ["delivery", "hotfix"]}
    assert wf["unassigned"]["machines"] == ["idle"]


def test_the_default_is_what_the_data_separates_best():
    out = subsystems(model())
    assert out["default"] == "workflow" and out["partitions"][0]["label"] == "workflow"
    step = next(p for p in out["partitions"] if p["label"] == "step")
    assert step["joined"] == 0 and step["crossed"] == 3


def test_a_label_with_one_value_partitions_nothing():
    m = Model("m", "m", stocks=[pile("a1", "hotfix", "write"), pile("a2", "hotfix", "write")])
    assert subsystems(m) == {"default": None, "partitions": []}
    assert subsystems(Model("m", "m")) == {"default": None, "partitions": []}


def test_the_model_view_reports_them_and_changes_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    m = model()
    ModelStore.for_state(project.state_dir).write_discovery(m)
    out = model_view(project)["model"]
    assert out["subsystems"] == subsystems(m)
    assert [s["id"] for s in out["stocks"]] == [s.id for s in m.stocks] and len(out["flows"]) == len(m.flows)
