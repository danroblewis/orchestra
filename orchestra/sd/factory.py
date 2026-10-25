"""Orchestra's own task system, declared as a model: descriptive only.

Ticket states are stocks (bound to ``orchestra_stock``), every transition the loop can make is a
flow (bound to ``orchestra_flow_total``), and today's loop steps are machines attributed to the
flows they cause (docs/proposals/orchestra-kernel.md §3). Nothing here changes behaviour: the loop
still runs as before. Equations start empty; ``orchestra sd fit`` fills them from the history."""

from __future__ import annotations

from ..collectors import FLOW, OUTSIDE, STOCK
from ..model import State
from .model import Engagement, Flow, Machine, Model, SeriesRef, Stock

# every transition SPEC.md section 3 allows, plus creation; (from, to) with None for outside
TRANSITIONS: list[tuple[str | None, str]] = [
    (None, "OPEN"),
    ("OPEN", "IN_PROGRESS"), ("IN_PROGRESS", "READY_FOR_REVIEW"), ("IN_PROGRESS", "BLOCKED"),
    ("READY_FOR_REVIEW", "IN_REVIEW"), ("IN_REVIEW", "APPROVED"), ("IN_REVIEW", "REJECTED"),
    ("REJECTED", "IN_PROGRESS"), ("APPROVED", "MERGING"), ("MERGING", "DONE"), ("MERGING", "REJECTED"),
    ("MERGING", "APPROVED"), ("BLOCKED", "OPEN"),
    ("IN_PROGRESS", "OPEN"), ("IN_REVIEW", "READY_FOR_REVIEW"),            # recovery
    ("OPEN", "CANCELLED"), ("BLOCKED", "CANCELLED"), ("REJECTED", "CANCELLED"), ("READY_FOR_REVIEW", "CANCELLED"),
    ("APPROVED", "CANCELLED"),
]


def flow_id(src: str | None, dst: str) -> str:
    return f"{src or OUTSIDE}>{dst}"


# machine id -> (name, kind, description, flows it is attributed to, engagement)
MACHINES = {
    "orchestra-host": ("Orchestra host", "program",
                       ("The bootstrap machine: runs the loop and the dispatcher, hosts the drivers. Moves tickets "
                        "into active states when a slot is free."),
                       ["OPEN>IN_PROGRESS", "READY_FOR_REVIEW>IN_REVIEW", "REJECTED>IN_PROGRESS", "APPROVED>MERGING"],
                       [Engagement("continuous", "process")]),
    "worker": ("Worker", "agent", "Implements a ticket in its worktree and reports ready for review or blocked.",
               ["IN_PROGRESS>READY_FOR_REVIEW", "IN_PROGRESS>BLOCKED"], [Engagement("ad_hoc", "harness")]),
    "reviewer": ("Reviewer", "agent", "Reviews the commit under review and reports approved or rejected.",
                 ["IN_REVIEW>APPROVED", "IN_REVIEW>REJECTED"], [Engagement("ad_hoc", "harness")]),
    "gate": ("Merge gate", "program", "Builds, tests and lands batches; bisects failures.",
             ["MERGING>DONE", "MERGING>REJECTED", "MERGING>APPROVED"], [Engagement("ad_hoc", "process")]),
    "recovery": ("Recovery", "program", "Returns tickets whose owner stopped to the state before.",
                 ["IN_PROGRESS>OPEN", "IN_REVIEW>READY_FOR_REVIEW"], [Engagement("ad_hoc", "process")]),
    "planners": ("Supervisor and Coordinator", "agent", "Create, unblock and cancel tickets.",
                 ["outside>OPEN", "BLOCKED>OPEN", "OPEN>CANCELLED", "BLOCKED>CANCELLED", "REJECTED>CANCELLED",
                  "READY_FOR_REVIEW>CANCELLED", "APPROVED>CANCELLED"], [Engagement("continuous", "harness")]),
}


def ticket_factory(project_key: str) -> Model:
    lab = {"project": project_key}
    stocks = [Stock(s.value, s.value.replace("_", " ").capitalize(), "tickets",
                    SeriesRef(STOCK, {**lab, "stock": s.value})) for s in State]
    flows = [Flow(flow_id(a, b), f"{(a or 'outside').lower()} → {b.lower()}", a, b,
                  SeriesRef(FLOW, {**lab, "flow": flow_id(a, b)})) for a, b in TRANSITIONS]
    machines = [Machine(mid, name, kind, desc, flows_, [], eng, bootstrap=(mid == "orchestra-host"))
                for mid, (name, kind, desc, flows_, eng) in MACHINES.items()]
    return Model("tickets", "Orchestra's task system",
                 "Ticket states as stocks, transitions as flows, today's loop steps as machines. Descriptive: "
                 "equations are fitted from the event history.", "hour", stocks, flows, machines)
