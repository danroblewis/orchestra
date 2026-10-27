"""A machine's card shows what is known of the machine (its events, instances, how it is engaged,
its kind, its log) and the flows it is hypothesised to be associated with, with their
confidence; never the series labelled with its name (AGENTS.md rules 2, 6 and 7)."""

from orchestra.sd.model import Flow, Model, SeriesRef, Stock
from orchestra.web.machines import flow_hypotheses, machines_view

T0 = 1_800_000_000.0


def ev(source, type_, t, **data):
    return {"specversion": "1.0", "id": f"{source}-{type_}-{t}", "source": source, "type": type_, "time": t, "data": data}


def model():
    done = Flow("done", "jobs done", "queue", None, counter=SeriesRef("jobs_done_total", {"instrument": "probe"}))
    done.evidence = {"machines": {"hypotheses": [
        {"machine": "worker", "origin": "inferred", "by": "events on the bus", "confidence": 0.93,
         "events": {"type": "job.done", "source": "worker"}, "why": "worker's job.done events match its increments"},
        {"machine": "dispatcher", "origin": "inferred", "by": "events on the bus", "confidence": 1.0,
         "events": {"type": "job.acked", "source": "dispatcher"}, "why": "dispatcher's job.acked events match"}]}}
    came = Flow("came", "jobs arrived", None, "queue", counter=SeriesRef("jobs_arrived_total", {"instrument": "probe"}))
    came.evidence = {"machines": {"hypotheses": [{"machine": "worker", "confidence": 0.6, "by": "events on the bus",
                                                  "events": {"type": "job.taken", "source": "worker"}, "why": "covers every increment"}]}}
    return Model("system", "s", stocks=[Stock("queue", "queue", series=SeriesRef("jobs_queued", {"machine": "worker"}))], flows=[done, came])


def test_a_machines_flows_are_hypotheses_best_first():
    flows = flow_hypotheses(model())
    assert [(h["flow"], h["confidence"]) for h in flows["worker"]] == [("done", 0.93), ("came", 0.6)]
    assert all(h["hypothesis"] for h in flows["worker"]) and flows["worker"][0]["name"] == "jobs done"
    assert flows["dispatcher"][0]["events"] == {"type": "job.acked", "source": "dispatcher"}
    assert flow_hypotheses(None) == {} and flow_hypotheses(Model("m", "m", flows=[Flow("x", "x", None, None)])) == {}


def test_the_card_carries_flows_and_no_series_labelled_with_the_machine():
    evs = [ev("worker/1", "orchestra.machine.started", T0, mode="continuous", kind="program"), ev("worker/1", "job.done", T0 + 1)]
    view = machines_view(evs, now=T0 + 2, flows=flow_hypotheses(model()))
    worker = {m["id"]: m for m in view["machines"]}["worker"]
    assert [h["flow"] for h in worker["flows"]] == ["done", "came"]
    assert "metrics" not in worker and "from_source" not in worker
    assert worker["mode"] == "continuous" and worker["kind"] == "program" and worker["publishes"][0]["type"] == "job.done"
    # a hypothesis about a machine never seen on the bus makes no machine
    assert "dispatcher" not in {m["id"] for m in view["machines"]}
