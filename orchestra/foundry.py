"""The software foundry's built-in stocks, flows, and loops, as data.

Orchestra is a foundry whose product is good software; these are the stocks it holds by
construction (see docs/proposals/software-foundry-model.md). A project in another domain
declares its own stocks beside these. Nothing here computes anything: the readings come
from `foundrymetrics`, the drawing from the Agents page."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stock:
    key: str
    name: str
    unit: str
    description: str
    inflows: tuple[str, ...] = ()
    outflows: tuple[str, ...] = ()
    estimators: tuple[str, ...] = ()     # kinds used: events, git, gate, sessions, repo
    consumers: tuple[str, ...] = ()      # agents that read it
    addition: bool = False               # Orchestra's addition, not in the published models
    hidden: bool = False                 # inferred, never counted


STOCKS: dict[str, Stock] = {s.key: s for s in [
    Stock("D", "Demand", "tickets", "Work ordered and not started: OPEN and BLOCKED tickets in open milestones.",
          ("ticket_created",), ("ticket_transition:IN_PROGRESS", "ticket_transition:CANCELLED"), ("events",), ("worker",)),
    Stock("W", "Work in progress", "commits ahead of main", "Commits on ticket branches that have not landed, whatever state the ticket is in.",
          ("commits",), ("gate_landed",), ("git",), ("reviewer", "merge_gate")),
    Stock("K", "Known rework", "send-backs", "Changes a reviewer or the gate sent back because of a defect. Conflicts and machine failures are counted apart.",
          ("ticket_transition:REJECTED", "gate_rejected"), ("ticket_transition:READY_FOR_REVIEW",), ("events",), ("worker",)),
    Stock("U", "Undiscovered rework", "commits", "Defects in work in progress and landed software not yet found. Hidden; not estimable until a post-landing discovery series exists.",
          (), (), (), (), hidden=True),
    Stock("L", "Landed software", "commits", "Commits the gate put on main, with first-parent diff size. The product.",
          ("gate_landed",), (), ("events", "git"), ()),
    Stock("A", "Really done", "acceptance tests passing", "Acceptance tests that pass, not skipped, against the current build on main. Actual progress, against DONE tickets as perceived progress.",
          ("gate_landed",), (), ("gate",), ()),
    Stock("B", "Working build", "builds", "The staging build the acceptance suite last ran against, and whether it is up.",
          ("staging_deployed",), ("staging_failed", "staging_restarted"), ("events",), ()),
    Stock("T", "Verified behaviour", "tests", "Tests on main by stage from the last gate run: passed, failed, skipped. Skipped tests are never counted as verified.",
          ("gate_landed",), (), ("gate",), ("reviewer", "merge_gate"), addition=True),
    Stock("R", "Environment resources", "documents", "What the worker and reviewer read before working: AGENTS.md, README, team and role docs, decided lessons.",
          ("gate_landed",), (), ("repo",), ("worker", "reviewer"), addition=True),
    Stock("C", "Agent time", "agent-hours per day", "Wall time of agent sessions by activity: implement, fix, review, plan, and each team's own. Losses are shown beside it.",
          ("session_started",), ("session_settled",), ("sessions",), ()),
]}


@dataclass(frozen=True)
class Flow:
    key: str
    name: str
    src: str                       # stock key, or "effort"
    dst: str                       # stock key, or "loss"
    machine: str | None            # built-in agent or system on the valve; None = whoever is bound, else unattended
    event: str                     # the event a new agent would wake on, or what to add
    measured_by: str
    exists: bool = True            # False when the event does not exist yet
    binds: tuple[str, ...] = ()    # events whose subscribers are on this flow (custom agents, or named built-ins)
    builtin_ok: tuple[str, ...] = ()   # built-in agents that count as bound when subscribed


FLOWS: tuple[Flow, ...] = (
    Flow("start", "start", "D", "W", "orchestra", "ticket_transition:IN_PROGRESS", "OPEN → IN_PROGRESS"),
    Flow("implement", "implement", "effort", "W", "worker", "ticket_transition:READY_FOR_REVIEW", "commits on the ticket branch; READY_FOR_REVIEW arrivals"),
    Flow("precheck", "pre-review check", "W", "W", "orchestra", "worktree_checked", "the unit stage run in the worktree before review; no event today", exists=False),
    Flow("review", "inspect in review", "W", "K", "reviewer", "ticket_transition:REJECTED", "IN_REVIEW → REJECTED"),
    Flow("gate", "inspect at the gate", "W", "K", "merge_gate", "gate_rejected", "gate runs that failed on their own result"),
    Flow("conflict", "conflict", "W", "W", "merge_gate", "gate_conflict", "gate_conflict: concurrence rework, driven by work in progress"),
    Flow("failure", "machine failure", "W", "loss", None, "turn_timed_out", "gate timeouts, start failures, reviewer without a verdict, worker crashes, turn timeouts", binds=("turn_timed_out", "agent_crashed", "gate_error")),
    Flow("escape", "discover after landing", "L", "K", None, "staging_failed", "a test that passed before and fails now; a bug ticket citing a landed commit; staging restarted", binds=("staging_failed", "gate_base_broken", "staging_restarted"), builtin_ok=("pipeline_manager",)),
    Flow("fix", "fix", "K", "W", "worker", "ticket_transition:IN_PROGRESS", "REJECTED → IN_PROGRESS … READY_FOR_REVIEW"),
    Flow("land", "land", "W", "L", "merge_gate", "gate_landed", "gate_landed"),
    Flow("deploy", "deploy", "L", "B", "orchestra", "staging_deployed", "staging_deployed"),
    Flow("verify", "verify", "B", "A", "orchestra", "gate_landed", "the acceptance stage of the gate run that landed the build"),
    Flow("tests", "add tests", "effort", "T", None, "gate_landed", "tests on main after each landing, against before", binds=("ticket_transition:DONE", "gate_landed")),
    Flow("improve", "improve", "K", "R", None, "lesson_decided", "lessons decided; agent-facing docs landed; no event today", exists=False, binds=("ticket_transition:REJECTED", "gate_rejected", "gate_conflict", "lesson_decided")),
    Flow("base", "broken base", "L", "K", None, "gate_base_broken", "gate_base_broken", binds=("gate_base_broken",), builtin_ok=("pipeline_manager",)),
)


@dataclass(frozen=True)
class Loop:
    key: str
    name: str
    polarity: str                  # B or R
    structure: str
    signal: str
    source: str
    addition: bool = False
    observed_when: tuple[str, ...] = field(default_factory=tuple)   # event types that, seen in the window, make it observed


LOOPS: tuple[Loop, ...] = (
    Loop("B1", "defect removal", "B", "known rework → fix → known rework falls", "fix round trip short and stable; bad-fix fraction low",
         "Cooper 1980; Lyneis & Ford 2007", observed_when=("ticket_transition:REJECTED",)),
    Loop("B2", "earlier detection", "B", "tests and pre-review checks → defects found before the gate", "share of defects found before the gate rising",
         "Orchestra's addition", addition=True, observed_when=("worktree_checked",)),
    Loop("B3", "WIP limit", "B", "work in progress → pickup paused, capacity lowered → conflicts and queue ages fall", "conflicts per landing and queue ages not rising",
         "Reinertsen 2009; Ford & Sterman 1998 (concurrence)", observed_when=("capacity_changed", "pickup_paused")),
    Loop("B4", "capability", "B", "known rework by cause → improve → resources → fewer send-backs for that cause", "the cause-specific send-back rate falling after its lesson lands",
         "Repenning & Sterman 2001 (work smarter)", observed_when=("lesson_decided",)),
    Loop("B5", "broken base", "B", "base broken → pipeline paused → repaired", "time from base broken to next landing",
         "Abdel-Hamid & Madnick 1991 (errors build errors)", observed_when=("gate_base_broken",)),
    Loop("R1", "firefighting", "R", "rework share → worker slots and coordinator priority go to fixes → less add-tests and improve → more send-backs", "rework share rising week on week with add-tests falling",
         "Repenning 2001 (hypothesised here: the shared resource is worker slots)"),
    Loop("R2", "debt drag", "R", "churn → maintainability → landed per worker-hour falls", "landed per worker-hour falling while diff size is constant",
         "Franco et al. 2016 (hypothesised here)"),
)


def bound_agents(agents: dict) -> dict[str, list[str]]:
    """For each flow without a built-in machine, the agents whose wake rules bind them to it:
    custom agents on any of the flow's events, and the named built-ins. The worker and the
    reviewer are valves of their own flows and never count here."""
    from .org import event_matches
    out: dict[str, list[str]] = {}
    for f in FLOWS:
        if f.machine is not None:
            continue
        names = []
        for name, ag in agents.items():
            if name in ("worker", "reviewer") or (ag.builtin and name not in f.builtin_ok):
                continue
            for b in f.binds:
                t, _, suffix = b.partition(":")
                ev = {"type": t, "to": suffix, "status": suffix, "probe": suffix, "subject": suffix} if suffix else {"type": t}
                if event_matches(list(ag.wake_on), ev):
                    names.append(name)
                    break
        out[f.key] = sorted(names)
    return out


def as_dict() -> dict:
    return {"stocks": [vars(s) for s in STOCKS.values()], "flows": [vars(f) for f in FLOWS], "loops": [vars(lp) for lp in LOOPS]}
