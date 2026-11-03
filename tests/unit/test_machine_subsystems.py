"""The Machines page's subsystems (docs/proposals/subsystems.md B9, B10, B15, step 3): the model's
partitions carried to machines by their flow hypotheses, one partition per announced field that
groups machines, event types inside a box or between boxes, hand-offs crossing, and a machine in
two groups outside every box. Display only; no label's name known."""

from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.subsystems import subsystems as derived
from orchestra.web.machine_subsystems import subsystems
from orchestra.web.machines import MachineIndex, _ListBus

T0 = 1_790_000_000.0


def announce(src, t, **d):
    return {"type": "orchestra.machine.started", "source": src, "time": t, "data": {"mode": "ad hoc", **d}}


def ev(src, t, type_, subject):
    return {"type": type_, "source": src, "time": t, "subject": subject}


def index(evs):
    idx = MachineIndex(_ListBus(evs))
    idx.update()
    return idx


def bus():
    """planner and writer in team a, reviewer and shipper in team b; planner -> writer -> reviewer -> shipper."""
    evs = [announce("planner", T0, group="a", listens_for=[]), announce("writer", T0, group="a", listens_for=["plan.made"]),
           announce("reviewer", T0, group="b", listens_for=["draft.written"]), announce("shipper", T0, group="b", listens_for=["review.passed"]),
           announce("helper/1", T0, group="a", listens_for=["plan.made"]), announce("helper/2", T0, group="b", listens_for=["plan.made"])]
    for i in range(3):
        s, t = f"item{i}", T0 + 10 + i * 10
        evs += [ev("planner", t, "plan.made", s), ev("writer", t + 1, "draft.written", s),
                ev("reviewer", t + 2, "review.passed", s), ev("shipper", t + 3, "item.shipped", s)]
    return evs


def view(evs, model=None):
    idx = index(evs)
    out = idx.view(now=T0 + 100)
    subs = derived(model) if model is not None else {"default": None, "partitions": []}
    return out, subsystems(out, subs, idx.announced_fields())


def test_one_partition_per_announced_field_named_by_the_field():
    _, subs = view(bus())
    by = {p["label"]: p for p in subs["partitions"]}
    assert set(by) == {"group"}                         # no machine announced a package: no partition by it
    g = by["group"]
    assert g["source"] == "announced" and subs["default"] == "group"
    groups = {x["value"]: x for x in g["groups"]}
    assert groups["a"]["machines"] == ["planner", "writer"] and groups["b"]["machines"] == ["reviewer", "shipper"]
    # a machine whose instances announced two groups is in two: outside every box
    assert g["spanning"] == [{"machine": "helper", "groups": ["a", "b"]}]
    assert "orchestra-host" in g["unassigned"]["machines"]


def test_event_types_inside_a_box_or_between_boxes():
    _, subs = view(bus())
    g = subs["partitions"][0]
    groups = {x["value"]: x for x in g["groups"]}
    # every machine on review.passed (its publisher, its listener) is in b: inside b's box
    assert "review.passed" in groups["b"]["events"] and "item.shipped" in groups["b"]["events"]
    # draft.written: published in a, heard in b: between the boxes
    assert {"type": "draft.written", "groups": ["a", "b"]} in g["between"]
    # plan.made is heard by helper, in two groups: outside every box
    assert "plan.made" in g["unassigned"]["events"]


def test_hand_offs_crossing_are_counted_per_pair():
    _, subs = view(bus())
    g = subs["partitions"][0]
    [c] = g["crossing"]
    assert c["between"] == ["a", "b"] and c["count"] == 1 and c["subjects"] == 3
    assert [(h["from"], h["to"]) for h in c["handoffs"]] == [("writer", "reviewer")]
    assert g["joined"] == 2 and g["crossed"] == 1       # planner -> writer in a, reviewer -> shipper in b


def model():
    """The model's partition by workflow: writer's hypotheses in hotfix, reviewer's in delivery,
    worker's in both."""
    pile = lambda sid, wf: Stock(sid, sid, series=SeriesRef("pile_items", {"instrument": "piles", "workflow": wf, "machine": "floor"}))
    hyp = lambda *ms: {"machines": {"hypotheses": [{"machine": m} for m in ms]}}
    return Model("m", "m", stocks=[pile("h1", "hotfix"), pile("h2", "hotfix"), pile("d1", "delivery"), pile("d2", "delivery")],
                 flows=[Flow("h", "x", "h1", "h2", evidence=hyp("writer", "worker")), Flow("d", "x", "d1", "d2", evidence=hyp("reviewer", "worker"))],
                 machines=[Machine("writer", "writer", "machine"), Machine("reviewer", "reviewer", "machine"), Machine("worker", "worker", "machine")])


def test_the_models_partitions_are_carried_to_machines_by_their_hypotheses():
    _, subs = view(bus(), model())
    assert [p["label"] for p in subs["partitions"]] == ["workflow", "group"]   # the model's first, then the announced
    assert subs["default"] == "workflow"
    wf = subs["partitions"][0]
    assert wf["by"] == "hypotheses"
    groups = {x["value"]: x for x in wf["groups"]}
    assert groups["hotfix"]["machines"] == ["writer"] and groups["delivery"]["machines"] == ["reviewer"]
    # a machine the model does not hold (no hypothesis) is in no box, never placed by a series' machine label
    assert "planner" in wf["unassigned"]["machines"] and "shipper" in wf["unassigned"]["machines"]
    [c] = wf["crossing"]
    assert c["between"] == ["delivery", "hotfix"] and [(h["from"], h["to"]) for h in c["handoffs"]] == [("writer", "reviewer")]
    assert {"type": "draft.written", "groups": ["delivery", "hotfix"]} in wf["between"]


def test_a_machine_in_two_groups_by_its_hypotheses_is_outside_every_box():
    evs = bus() + [ev("worker", T0 + 90, "work.done", "x")]
    _, subs = view(evs, model())
    wf = subs["partitions"][0]
    assert {"machine": "worker", "groups": ["delivery", "hotfix"]} in wf["spanning"]
    assert all("worker" not in g["machines"] for g in wf["groups"]) and "worker" not in wf["unassigned"]["machines"]
    assert "work.done" in wf["unassigned"]["events"]


def test_the_maps_default_is_the_models_whatever_it_boxes():
    """Every machine's hypotheses in both workflows: the model's default boxes none, and it stays
    the map's default (the page starts with boxes off and says why); a state is never chosen instead."""
    hyp = lambda *ms: {"machines": {"hypotheses": [{"machine": m} for m in ms]}}
    m = model()
    for f in m.flows:
        f.evidence = hyp("writer", "reviewer", "worker")
    _, subs = view(bus(), m)
    assert [p["label"] for p in subs["partitions"]] == ["workflow", "group"] and subs["default"] == "workflow"
    assert sum(len(g["machines"]) for g in subs["partitions"][0]["groups"]) == 0
