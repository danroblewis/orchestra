"""Orchestra's own task system, declared as a model: descriptive only.

Ticket states are stocks (bound to ``orchestra_tickets{state}``), creation and every transition
the loop can make are flows (bound to ``orchestra_tickets_created_total`` and
``orchestra_ticket_transitions_total{from, to}``), and today's loop steps are machines attributed to the
flows they cause (docs/proposals/orchestra-kernel.md §3). Nothing here changes behaviour: the loop
still runs as before. Equations start empty; ``orchestra sd fit`` fills them from the history."""

from __future__ import annotations

from ..collectors import CREATED, OUTSIDE, TICKETS
from ..collectors import TRANSITIONS as TRANSITIONS_SERIES
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
    "supervisor": ("Supervisor", "agent", "Talks with the human and creates tickets from the conversation.",
                   ["outside>OPEN", "OPEN>CANCELLED", "BLOCKED>CANCELLED", "REJECTED>CANCELLED",
                    "READY_FOR_REVIEW>CANCELLED", "APPROVED>CANCELLED"], [Engagement("continuous", "harness")]),
    "coordinator": ("Coordinator", "agent", "Keeps the plan executable: splits, orders and unblocks tickets.",
                    ["BLOCKED>OPEN"], [Engagement("continuous", "harness")]),
    "pipeline-manager": ("Pipeline manager", "agent", "On call for the merge pipeline; files fix tickets.",
                         [], [Engagement("continuous", "harness")]),
}


# The events program machines emit and are woken by (agents declare theirs in the org). A
# machine's ticket events also follow from the flows it is attributed to (flow_event).
PROGRAM_EVENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "orchestra-host": (("session_started", "session_settled", "turn_timed_out", "turn_interrupted", "agent_compacted",
                        "agent_reset", "pickup_paused", "pickup_resumed", "loop_started", "loop_stopped"),
                       ("ticket_created", "ticket_transition:OPEN", "ticket_transition:READY_FOR_REVIEW",
                        "ticket_transition:REJECTED", "ticket_transition:APPROVED")),
    "gate": (("gate_started", "gate_landed", "gate_rejected", "gate_conflict", "gate_error", "gate_base_broken",
              "staging_deployed", "staging_failed", "pipeline_paused"),
             ("ticket_transition:MERGING",)),
    "recovery": ((), ("turn_timed_out", "agent_crashed", "loop_started")),
}


def flow_event(fid: str) -> str:
    """The event a move along a flow shows up as: creation, or a transition into its target."""
    src, _, dst = fid.partition(">")
    return "ticket_created" if src == OUTSIDE else f"ticket_transition:{dst}"


def ticket_factory(project_key: str) -> Model:
    lab = {"project": project_key}
    stocks = [Stock(s.value, s.value.replace("_", " ").capitalize(), "tickets",
                    SeriesRef(TICKETS, {**lab, "state": s.value})) for s in State]
    flows = [Flow(flow_id(a, b), f"{(a or 'outside').lower()} → {b.lower()}", a, b,
                  SeriesRef(CREATED, lab) if a is None else SeriesRef(TRANSITIONS_SERIES, {**lab, "from": a, "to": b}))
             for a, b in TRANSITIONS]
    machines = [Machine(mid, name, kind, desc, flows_, [], eng, bootstrap=(mid == "orchestra-host"))
                for mid, (name, kind, desc, flows_, eng) in MACHINES.items()]
    return Model("system", "The system",
                 "Today it holds Orchestra's own task system: ticket states as stocks, creation and transitions as "
                 "flows, today's loop steps as machines. Descriptive: equations are fitted from the event history.",
                 "hour", stocks, flows, machines)
