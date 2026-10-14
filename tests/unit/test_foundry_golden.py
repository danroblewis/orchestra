"""The golden case: an ideal software-foundry configuration of agents, events, and stocks,
fed to the loop detector, must yield the feedback loops the literature expects (Cooper's
rework cycle; Repenning's capability loop; earlier detection; broken base), and nothing
that contradicts them. The configuration is the reference arrangement a project's
Supervisor should move towards; the detector is what Orchestra trusts to tell a project
which loops it actually has. Both are under test here, bottom up."""


from orchestra import foundrygraph as fg
from orchestra.agents.roles import ROLES, SYSTEM_BINDINGS
from orchestra.foundry import Stock
from orchestra.org import AgentDef


def builtin(name: str) -> AgentDef:
    r = ROLES[name]
    return AgentDef(name=name, roles=[name], wake_on=list(r.wake_on), emits=list(r.emits), builtin=True)


def custom(name: str, team: str, wake_on: list[str], emits: list[str]) -> AgentDef:
    return AgentDef(name=name, roles=["analyst"], team=team, kind="ad_hoc", session="ephemeral", wake_on=wake_on, emits=emits)


# -- the ideal configuration ------------------------------------------------------------------

def foundry_stocks() -> list[Stock]:
    return [
        Stock("demand", "Demand", "tickets", inflows=["ticket_created", "ticket_transition:OPEN", "ticket_transition:IN_PROGRESS>BLOCKED"], outflows=["ticket_transition:OPEN>IN_PROGRESS"]),
        Stock("wip", "Work in progress", "changes", inflows=["ticket_transition:OPEN>IN_PROGRESS", "ticket_transition:REJECTED>IN_PROGRESS"], outflows=["gate_landed", "ticket_transition:CANCELLED", "ticket_transition:IN_PROGRESS>BLOCKED"]),
        Stock("awaiting_review", "Awaiting review", "changes", inflows=["ticket_transition:READY_FOR_REVIEW"], outflows=["ticket_transition:IN_REVIEW>APPROVED", "ticket_transition:IN_REVIEW>REJECTED"]),
        Stock("undiscovered", "Undiscovered rework", "defects", inflows=["ticket_transition:READY_FOR_REVIEW"],
              outflows=["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], hidden=True),
        Stock("approved", "Awaiting the gate", "changes", inflows=["ticket_transition:APPROVED"], outflows=["gate_landed", "gate_rejected", "gate_conflict"]),
        Stock("known_rework", "Known rework", "send-backs", inflows=["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], outflows=["ticket_transition:READY_FOR_REVIEW"]),
        Stock("landed", "Landed software", "commits", inflows=["gate_landed", "ticket_transition:DONE"], outflows=[]),
        Stock("build", "Working build", "builds", inflows=["staging_deployed"], outflows=["staging_failed", "staging_restarted"]),
        Stock("pipeline_blocked", "Pipeline blocked", "pauses", inflows=["pipeline_paused"], outflows=["pipeline_resumed"]),
        Stock("tests", "Verified behaviour", "tests", inflows=["tests_added"], outflows=[], consumers=[{"agent": "reviewer", "effect": "+"}, {"agent": "merge_gate", "effect": "+"}]),
        Stock("resources", "Environment resources", "documents", inflows=["lesson_decided"], outflows=[], consumers=[{"agent": "worker", "effect": "-"}, {"agent": "reviewer", "effect": "+"}]),
    ]


def foundry_agents(*, keeper: bool = True, qa: bool = True) -> dict[str, AgentDef]:
    ags = {n: builtin(n) for n in ("worker", "reviewer", "coordinator", "pipeline_manager", "supervisor")}
    if keeper:
        ags["environment_keeper"] = custom("environment_keeper", "devex", ["ticket_transition:REJECTED", "gate_rejected"], ["lesson_decided"])
    if qa:
        ags["qa_engineer"] = custom("qa_engineer", "qa", ["gate_landed"], ["tests_added"])
    return ags


EXPECTED = [
    # the rework cycle: a defect found in review goes back through the worker and is inspected again;
    # a conserved material loop, balancing (Cooper; Lyneis & Ford)
    {"key": "review_rework", "nodes": ["known_rework", "worker", "awaiting_review", "reviewer"]},
    # the same cycle closed through the gate
    {"key": "gate_rework", "nodes": ["known_rework", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"]},
    # Repenning's capability loop: rework teaches the resources the worker reads, which cuts injection
    {"key": "capability", "nodes": ["known_rework", "environment_keeper", "resources", "worker", "undiscovered", "reviewer"], "polarity": "B"},
    # earlier detection: landings grow the tests the gate runs, which finds more before landing
    {"key": "earlier_detection", "nodes": ["landed", "qa_engineer", "tests", "merge_gate"]},
    # broken base: a failed build wakes the pipeline manager, which resumes the gate
    {"key": "broken_base", "nodes": ["pipeline_blocked", "pipeline_manager", "merge_gate"]},
    # re-planning: a worker blocks a ticket, the coordinator re-plans it into demand, Orchestra starts it again
    {"key": "replanning", "nodes": ["wip", "worker", "demand", "orchestra"]},
]


def loops_for(stocks, agents, expected=EXPECTED):
    return fg.detect(stocks, agents, expected, system=SYSTEM_BINDINGS)


# -- bottom up ------------------------------------------------------------------------------------

def test_events_fit_with_or_without_a_filter():
    assert fg.event_fits("ticket_transition:REJECTED", "ticket_transition:REJECTED")
    assert fg.event_fits("ticket_transition", "ticket_transition:REJECTED")
    assert fg.event_fits("ticket_transition:REJECTED", "ticket_transition")
    assert not fg.event_fits("ticket_transition:REJECTED", "ticket_transition:APPROVED")
    assert not fg.event_fits("gate_landed", "ticket_transition")


def test_a_stock_and_its_draining_agent_make_the_balancing_drain_loop():
    stocks = [Stock("demand", "Demand", "tickets", inflows=["ticket_created"], outflows=["ticket_transition:IN_PROGRESS"])]
    g = fg.build(stocks, {}, SYSTEM_BINDINGS)
    assert {"src": "agent:orchestra", "dst": "demand", "sign": "-", "kind": "drains", "via": "ticket_transition:IN_PROGRESS"} in g["edges"]
    assert any(e["src"] == "demand" and e["dst"] == "agent:orchestra" and e["kind"] == "wakes" for e in g["edges"])   # woken by the arrival
    det = fg.detect(stocks, {}, [], system=SYSTEM_BINDINGS)
    drain = next(c for c in det["cycles"] if set(c["nodes"]) == {"demand", "agent:orchestra"})
    assert drain["polarity"] == "B" and drain["basis"] == "link signs"                        # arrival wakes (+), pickup drains (−)


def test_worker_and_reviewer_alone_make_the_rework_cycle():
    stocks = [s for s in foundry_stocks() if s.key in ("wip", "awaiting_review", "undiscovered", "known_rework")]
    agents = {"worker": builtin("worker"), "reviewer": builtin("reviewer")}
    det = loops_for(stocks, agents, EXPECTED[:1])
    assert det["declared"][0]["detected"], [c["members"] for c in det["cycles"]]
    cyc = det["declared"][0]["cycle"]
    assert set(cyc["members"]) >= {"known_rework", "worker", "awaiting_review", "reviewer"}


def test_the_keeper_closes_the_capability_loop_and_removing_it_opens_it():
    stocks = foundry_stocks()
    with_keeper = loops_for(stocks, foundry_agents(keeper=True, qa=False))
    without = loops_for(stocks, foundry_agents(keeper=False, qa=False))
    cap = next(d for d in with_keeper["declared"] if d["key"] == "capability")
    assert cap["detected"] and cap["cycle"]["polarity"] == "B", cap
    missing = next(d for d in without["declared"] if d["key"] == "capability")
    assert not missing["detected"] and missing["gaps"]["missing_members"] == ["environment_keeper"]
    # consecutive stocks are joined by an agent between them; only a step no agent closes is a gap
    g0 = loops_for(stocks, foundry_agents(keeper=False, qa=False), [{"key": "x", "nodes": ["demand", "wip", "nowhere_stock"]}])
    gp = g0["declared"][0]["gaps"]
    assert gp["missing_members"] == ["nowhere_stock"] and not any(l["from"] == "demand" and l["to"] == "wip" for l in gp["missing_links"])
    # a keeper that is woken but emits nothing declared: the gap names the event to emit
    mute = foundry_agents(keeper=False, qa=False)
    mute["environment_keeper"] = custom("environment_keeper", "devex", ["ticket_transition:REJECTED"], [])
    g = loops_for(stocks, mute)
    gap = next(d for d in g["declared"] if d["key"] == "capability")["gaps"]
    assert gap["missing_members"] == [] and gap["missing_links"][0]["from"] == "environment_keeper" and "lesson_decided" in gap["missing_links"][0]["fix"]
    # a custom agent is never told to emit one of Orchestra's own events
    mute["environment_keeper"] = custom("environment_keeper", "devex", ["gate_landed"], [])
    g2 = loops_for(stocks, mute, [{"key": "x", "nodes": ["landed", "environment_keeper", "build"]}])
    fix = g2["declared"][0]["gaps"]["missing_links"][0]["fix"]
    assert "staging_deployed" not in fix and "custom inflow" in fix


def test_the_qa_engineer_closes_earlier_detection():
    stocks = foundry_stocks()
    det = loops_for(stocks, foundry_agents(qa=True))
    ed = next(d for d in det["declared"] if d["key"] == "earlier_detection")
    assert ed["detected"], [c["members"] for c in det["cycles"] if "tests" in c["members"]]


def test_the_pipeline_manager_closes_broken_base():
    det = loops_for(foundry_stocks(), foundry_agents())
    bb = next(d for d in det["declared"] if d["key"] == "broken_base")
    # a broken main fills the blocked-pipeline stock, its arrival wakes the manager, and the manager's resume
    # reaches the gate as a departure: the path is closed, but its only negative is that departure, so the
    # balancing is credited to the pair pipeline_blocked ↔ pipeline_manager, not to the path
    assert bb["detected"] and bb["cycle"]["polarity"] == "?" and bb["cycle"]["basis"].startswith("closed; the balancing is in the first-order pair"), bb
    assert "pipeline_blocked" in bb["cycle"]["nodes"]
    pair = next(c for c in det["pairs"] if set(c["nodes"]) == {"pipeline_blocked", "agent:pipeline_manager"})
    assert pair["polarity"] == "B"


def test_parallel_links_are_indeterminate_and_the_window_only_says_which_dominates():
    """A sign is structural. When two mechanisms with opposite signs join the same nodes the
    link is indeterminate, and the window's event counts only say which dominates today."""
    stocks = [Stock("demand", "Demand", "tickets", inflows=["ticket_created", "ticket_transition:OPEN"], outflows=["ticket_transition:IN_PROGRESS", "ticket_transition:CANCELLED"])]
    g = fg.build(stocks, {}, SYSTEM_BINDINGS)
    assert fg._signs(g)[("demand", "agent:orchestra")] == "+"                             # arrivals wake; departures reach the agent through whoever caused them
    assert fg._signs(g)[("agent:orchestra", "demand")] == "?"                             # Orchestra both reopens (+) and starts (−) tickets: indeterminate from structure
    assert fg.dominant(g, ("agent:orchestra", "demand"), {"ticket_transition:OPEN": 12, "ticket_transition:IN_PROGRESS": 80}) == "-"
    assert fg.dominant(g, ("agent:orchestra", "demand"), {}) is None


def test_a_transition_with_a_source_state_fits_only_its_owner():
    assert fg.event_fits("ticket_transition:IN_REVIEW>REJECTED", "ticket_transition:REJECTED", "reviewer")
    assert not fg.event_fits("ticket_transition:IN_REVIEW>REJECTED", "ticket_transition:REJECTED", "merge_gate")   # the gate's REJECTED leaves MERGING
    assert fg.event_fits("ticket_transition:IN_REVIEW>REJECTED", "ticket_transition:REJECTED")                      # no agent given: matches by type and target
    g = fg.build(foundry_stocks(), foundry_agents(), SYSTEM_BINDINGS)
    assert not any(e["src"] == "agent:merge_gate" and e["dst"] == "awaiting_review" for e in g["edges"])         # the gate never drains the review queue
    assert sum(1 for e in g["edges"] if e["src"] == "agent:merge_gate" and e["dst"] == "known_rework") == 1       # one fill per gate send-back, via gate_rejected
    # one event, one link: a departure is never also a plain trigger
    pairs = [(e["src"], e["dst"], e["via"]) for e in g["edges"] if e["kind"] in ("departs", "triggers")]
    assert len(pairs) == len(set(pairs))


def test_golden_software_foundry():
    """The top test: every expected loop is detected with the polarity the literature gives
    where it gives one, and every other cycle the detector reports is a variant of a named
    one (shares at least two members with it), never a structure nobody can explain."""
    det = loops_for(foundry_stocks(), foundry_agents())
    missing = [d["key"] for d in det["declared"] if not d["detected"]]
    assert not missing, (missing, [c["members"] for c in det["cycles"]])
    wrong = [(d["key"], d["cycle"]["polarity"]) for d in det["declared"] if d["polarity_agrees"] is False]
    assert not wrong, wrong
    named = [set(d["cycle"]["members"]) for d in det["declared"]]
    strangers = [c["members"] for c in det["unnamed"] if not any(len(set(c["members"]) & n) >= 2 for n in named)]
    assert not strangers, strangers
    assert all(c["pair"] for c in det["pairs"]) and det["pairs"]                               # the stock-and-its-agent pairs are kept apart
    # the rework cycles close through the hidden stock, as Cooper draws them, and carry no causal polarity:
    # through review the same event moves the thing on (a material circuit); through the gate the defect
    # rides inside an approved change (a co-flow)
    rv = next(d for d in det["declared"] if d["key"] == "review_rework")["cycle"]
    assert "awaiting_review" in rv["nodes"] and rv["basis"] == "material circuit" and rv["polarity"] is None and all(e["sign"] is None for e in rv["edges"])
    gt = next(d for d in det["declared"] if d["key"] == "gate_rework")["cycle"]
    assert gt["basis"] == "material circuit" and gt["polarity"] is None                     # the change circulates: re-submitted, approved, rejected at the gate, re-submitted
    # the blocked ticket is a conserved circuit too: wip → demand (blocked) → wip (started again)
    rp = next(d for d in det["declared"] if d["key"] == "replanning")["cycle"]
    assert rp["basis"] == "material circuit" and {"wip", "demand"} <= set(rp["nodes"])
    # one agent that both fills and drains a stock is a controller, never a circuit
    pair = next(c for c in det["pairs"] if set(c["nodes"]) == {"demand", "agent:orchestra"})
    assert pair["basis"] != "material circuit" and pair["polarity"] in ("B", "?")


def test_the_reference_configuration_has_no_wip_limit_controller_yet():
    """Documented gap: nothing in the reference arrangement reads work in progress and
    throttles pickup. The coordinator's re-planning of BLOCKED tickets is a different loop
    and must not be mistaken for it."""
    det = loops_for(foundry_stocks(), foundry_agents(), [{"key": "wip_limit", "nodes": ["wip", "flow_controller"], "polarity": "B"}])
    assert not det["declared"][0]["detected"]
    replanning = [c for c in det["cycles"] if {"coordinator", "demand", "wip", "worker"} <= set(c["members"])]
    assert replanning and all("flow_controller" not in c["members"] for c in replanning)
