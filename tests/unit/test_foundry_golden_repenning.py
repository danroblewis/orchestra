"""A second golden case from outside software: Repenning and Sterman's capability trap
("Nobody ever gets credit for fixing problems that never happened", 2001). Two balancing
loops close the same performance gap: work harder (fast) and work smarter (slow, through
capability). The detector must find both from stocks and bindings alone, with the right
polarity, and must not find work smarter when nobody improves capability. The reinforcing
trap itself needs an explicit improvement-time stock and is not encoded here."""

from orchestra import foundrygraph as fg
from orchestra.foundry import Stock
from orchestra.org import AgentDef


def agent(name, wake_on, emits):
    return AgentDef(name=name, roles=["r"], kind="ad_hoc", session="ephemeral", wake_on=wake_on, emits=emits)


STOCKS = [
    Stock("backlog", "Work to do", "orders", inflows=["order_received"], outflows=["work_completed"]),
    Stock("capability", "Process capability", "capability", inflows=["improvement_made"], outflows=["capability_eroded"],
          consumers=[{"agent": "producer", "effect": "+"}]),
]
PRODUCER = agent("producer", ["order_received"], ["work_completed"])
IMPROVER = agent("improver", ["order_received"], ["improvement_made"])
EXPECTED = [
    {"key": "work_harder", "nodes": ["backlog", "producer"], "polarity": "B"},
    {"key": "work_smarter", "nodes": ["backlog", "improver", "capability", "producer"], "polarity": "B"},
]


def test_work_harder_and_work_smarter_are_both_found():
    det = fg.detect(STOCKS, {"producer": PRODUCER, "improver": IMPROVER}, EXPECTED, system={})
    by = {d["key"]: d for d in det["declared"]}
    assert by["work_harder"]["detected"] and by["work_harder"]["cycle"]["polarity"] == "B"
    assert by["work_smarter"]["detected"] and by["work_smarter"]["cycle"]["polarity"] == "B", by["work_smarter"]
    assert set(by["work_smarter"]["cycle"]["members"]) == {"backlog", "improver", "capability", "producer"}


def test_without_an_improver_only_work_harder_remains():
    det = fg.detect(STOCKS, {"producer": PRODUCER}, EXPECTED, system={})
    by = {d["key"]: d for d in det["declared"]}
    assert by["work_harder"]["detected"] and not by["work_smarter"]["detected"]
