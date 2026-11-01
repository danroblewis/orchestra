"""More of the comparison (docs/proposals/intended-model.md §3.2, §3.3, §6.1, §6.3): an unsettled
suggestion stays listed and ringed until it settles; ``design()`` reads presence by id or key and
lists absent parts before any model; one resolver for a draft's names; a retired placeholder is
said to be one; a target on an input-only effect is judged; a recording is this project's."""

import time

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.intended.facts import Facts
from orchestra.sd.intended.machines_view import expected_effect
from orchestra.sd.intended.view import dynamics_block
from orchestra.sd.model import Flow, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "track it"}


def st(sid, name=None, **labels):
    return Stock(sid, sid, series=SeriesRef(name or sid, {"instrument": "i", **labels}))


def model(stocks, flows=(), **discovery):
    model.n = getattr(model, "n", 0) + 1                    # each one its own body, so each is saved
    m = Model("system", "s", f"discovered {model.n}", stocks=list(stocks), flows=list(flows))
    m.discovery = dict(discovery)
    return m


def saved(tmp_path, *models_):
    ms = ModelStore(tmp_path / "model")
    for i, m in enumerate(models_):
        ms.save(m, note=str(i))
    return ms


def block(ms, **kw):
    n = ms.current_version()
    return dynamics_block(ms.intended(), ms.load(n), kw.pop("since", None), version=n, live=False, hold=3, **kw)


def plus(b):
    return [(c["key"], c["status"], c["since"], c["why"], c["controls"]) for c in b["changes"] if c["sign"] == "+"]


def test_an_unsettled_suggestion_stays_listed_and_ringed_until_it_settles(tmp_path):
    a, s = st("a"), st("s")
    ms = saved(tmp_path, model([a]), model([a, s]), model([a, s]))
    b = block(ms)                                    # v3 against v2: s is not new, but has not settled
    assert plus(b) == [("s", "suggestion", 2, "new in v2", ["expect", "ignore"])]
    assert b["marks"]["stocks"] == {"s": ["new"]} and b["unsettled"] == 1 and not b["stabilised"]
    assert {"what": "unsettled suggestion", "part": "stock", "key": "s"} in ms.intended().design(hold=3)["open"]
    ms.save(model([a, s]))                           # in 3 consecutive versions: settled
    b = block(ms)
    assert plus(b) == [] and b["marks"]["stocks"] == {} and b["stabilised"]
    assert not [o for o in ms.intended().design(hold=3)["open"] if o["what"] == "unsettled suggestion"]


def test_an_expected_or_ignored_suggestion_is_answered(tmp_path):
    a, s, t = st("a"), st("s"), st("t")
    ms = saved(tmp_path, model([a]), model([a, s, t]), model([a, s, t]))
    ms.intended().apply([{"op": "expect", "part": "stock", "key": "s"}, {"op": "ignore", "part": "stock", "key": "t"}], OWNER)
    b = block(ms)
    assert plus(b) == [] and b["stabilised"] and b["marks"]["stocks"] == {"s": ["expected"]}


def test_design_reads_presence_by_id_for_declarations_and_by_key_for_marks(tmp_path):
    done = Stock("tasks_tickets_DONE", "DONE", series=SeriesRef("tasks_tickets", {"state": "DONE", "instrument": "tasks"}))
    a = st("a")
    f = Flow("a_to_done", "a to done", "a", "tasks_tickets_DONE", SeriesRef("moved_total", {"instrument": "i"}))
    ms = saved(tmp_path, model([a, done], [f]))
    stock_key, flow_key = 'tasks_tickets{state="DONE"}', 'a -> tasks_tickets{state="DONE"} by moved_total'
    ms.intended().apply([{"op": "expect", "part": "stock", "key": stock_key}, {"op": "expect", "part": "flow", "key": flow_key},
                         {"op": "declare_stock", "id": "done", "name": "Done"}, {"op": "link", "id": "done", "found_as": stock_key}],
                        OWNER)
    rows = {(e["part"], e.get("key") or e.get("id")): e for e in ms.intended().design(hold=3)["elements"]}
    assert rows[("stock", stock_key)]["present"] is True and rows[("flow", flow_key)]["present"] is True
    assert rows[("stock", "done")]["present"] is True


def test_one_resolver_for_a_drafts_names(tmp_path):
    queue, done = st("queue_id", name="queue"), st("done_id", name="done")
    ms = saved(tmp_path, model([queue, done], [Flow("moved", "moved", "queue_id", "done_id", SeriesRef("moved_total", {}))]))
    edits = [{"stock": "queue", "rises": True}, {"from": "queue", "to": "done", "appears": True},
             {"from": "queue", "to": "done_id", "appears": True}, {"from": "queue", "to": "nowhere", "appears": True},
             {"stock": "nowhere", "falls": True}]
    it = ms.intended()
    it.apply([{"op": "propose_machine", "id": "fci"}, {"op": "set_expected_effect", "machine": "fci", "horizon_s": 60, "edits": edits}],
             {"author": "supervisor"})
    layer = it.read()["layer"]
    rows = expected_effect(layer["machines"]["fci"], layer, ms.load(), {})["edits"]
    assert [(r["publishable"], r["why"]) for r in rows] == [(True, None), (True, None), (True, None), (False, "not in the model"),
                                                           (False, "not in the model")]
    assert rows[0]["label"] == "queue_id ↑" and rows[0]["link"] == "/dynamics#s:queue_id"
    assert rows[1]["label"] == "queue_id → done_id appears"
    predicted = block(ms)["predicted"]
    assert [(p["present"], p["id"]) for p in predicted] == [(True, "moved"), (True, "moved"), (False, None)]
    drafts = [o["why"] for o in it.design(hold=3)["open"] if o["what"] == "unpublishable draft"]
    assert drafts == ["not in the model", "not in the model"]


def test_a_retired_placeholder_is_removed_as_simulated(tmp_path):
    sim = st("ramp", simulated="true")
    sim.evidence["simulated"] = True
    ms = saved(tmp_path, model([st("a"), sim]), model([st("a")]))
    b = block(ms)
    assert b["removed"]["stocks"] == [{"key": "ramp", "id": "ramp", "name": "ramp", "in": 1, "simulated": True}]
    assert next(c for c in b["changes"] if c["sign"] == "-")["simulated"] is True


def test_design_lists_absent_declared_parts_before_any_model(tmp_path):
    it = ModelStore(tmp_path / "model").intended()
    it.apply([{"op": "declare_stock", "name": "Features"}, {"op": "declare_effect", "name": "Latency"},
              {"op": "declare_flow", "from": "features", "to": None}], OWNER)
    d = it.design(hold=3)
    absent = [o for o in d["open"] if o["what"] == "absent expected part"]
    assert absent == [{"what": "absent expected part", "part": "stock", "id": "features"},
                      {"what": "absent expected part", "part": "effect", "id": "latency"}]
    rows = {e["id"]: e for e in d["elements"]}
    assert rows["features"]["present"] is False and rows["latency"]["present"] is False and "present" not in rows["features_to_outside"]


def test_a_target_on_an_effect_found_only_as_an_input_is_judged(tmp_path):
    m = model([st("a")], inputs={"latency": {"name": "latency_seconds", "labels": {"instrument": "x"}}})
    ms = saved(tmp_path, m)
    ms.intended().apply([{"op": "declare_effect", "name": "Latency"}, {"op": "link", "id": "latency", "found_as": "latency_seconds"},
                         {"op": "set_target", "part": "effect", "id": "latency", "target": "below", "value": 1, "over_s": 600}], OWNER)
    metrics = FileMetrics(tmp_path / "metrics.jsonl")
    now = time.time()
    metrics.write([Point("latency_seconds", v, now - 300 + 100 * i, {"instrument": "x"}) for i, v in enumerate([0.4, 0.5, 0.6])])
    e = next(e for e in block(ms, metrics=metrics, now=now)["expected"] if e.get("id") == "latency")
    assert e["present"] and e["target"]["met"] == "met" and e["target"]["mean"] == 0.5


def test_a_recording_is_read_for_this_project_only(tmp_path):
    metrics = FileMetrics(tmp_path / "metrics.jsonl")
    now = time.time()
    for project, n in (("mine", 2), ("theirs", 5)):
        metrics.write([Point("passing", float(i), now - 60 * (n - i), {"instrument": "acc", "project": project}) for i in range(n)])
    assert Facts(metrics, now=now, project="mine").recording("acc")["points"] == 2
    assert Facts(metrics, now=now).recording("acc")["points"] == 5          # no project: the busiest series
