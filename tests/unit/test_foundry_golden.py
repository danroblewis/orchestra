"""The golden case: an ideal software-foundry configuration of agents, events, and stocks,
fed to the loop detector, must yield the feedback loops the literature expects (Cooper's
rework cycle; Repenning's capability loop; earlier detection; broken base), and nothing
that contradicts them. The configuration is the reference arrangement a project's
Supervisor should move towards; the detector is what Orchestra trusts to tell a project
which loops it actually has. Both are under test here, bottom up."""


import datetime as dt

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
        Stock("demand", "Demand", "tickets", inflows=["ticket_created", "ticket_transition:OPEN", "playtest_finding"], outflows=["ticket_transition:OPEN>IN_PROGRESS", "ticket_transition:OPEN>CANCELLED"]),
        Stock("blocked", "Blocked", "tickets", row="rework", inflows=["ticket_transition:IN_PROGRESS>BLOCKED"], outflows=["ticket_transition:BLOCKED>OPEN", "ticket_transition:BLOCKED>CANCELLED"]),
        Stock("returned", "Returned without a verdict", "changes", row="rework", inflows=["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected", "gate_conflict"], outflows=["ticket_transition:REJECTED>IN_PROGRESS", "ticket_transition:REJECTED>CANCELLED"]),
        Stock("wip", "Work in progress", "changes", inflows=["ticket_transition:OPEN>IN_PROGRESS", "ticket_transition:REJECTED>IN_PROGRESS"], outflows=["ticket_transition:IN_PROGRESS>READY_FOR_REVIEW", "ticket_transition:CANCELLED", "ticket_transition:IN_PROGRESS>BLOCKED", "ticket_transition:IN_PROGRESS>OPEN"]),
        Stock("awaiting_review", "Awaiting review", "changes", inflows=["ticket_transition:READY_FOR_REVIEW"], outflows=["ticket_transition:IN_REVIEW>APPROVED", "ticket_transition:IN_REVIEW>REJECTED"]),
        Stock("undiscovered", "Undiscovered rework", "defects", row="rework", inflows=["ticket_transition:READY_FOR_REVIEW"],
              outflows=["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected", "playtest_finding"], hidden=True),
        Stock("approved", "Awaiting the gate", "changes", inflows=["ticket_transition:APPROVED"], outflows=["gate_landed", "gate_rejected", "gate_conflict"]),
        Stock("known_rework", "Known rework", "changes", row="rework", inflows=["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], outflows=["ticket_transition:REJECTED>IN_PROGRESS", "ticket_transition:REJECTED>CANCELLED"], consumers=[{"agent": "worker", "effect": "+"}], estimators=[{"kind": "known_rework"}]),
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
    ags["playtester"] = custom("playtester", "playtest", ["staging_deployed"], ["playtest_finding"])   # a finding is a discovery (drains U) and a ticket (fills demand)
    return ags


EXPECTED = [
    # the rework cycle: a defect found in review goes back through the worker and is inspected again;
    # a conserved material loop, balancing (Cooper; Lyneis & Ford)
    {"key": "review_rework", "nodes": ["known_rework", "orchestra", "wip", "worker", "awaiting_review", "reviewer"]},
    # the same cycle closed through the gate
    {"key": "gate_rework", "nodes": ["known_rework", "orchestra", "wip", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"]},
    # Repenning's capability loop: rework teaches the resources the worker reads, which cuts injection
    {"key": "capability", "nodes": ["known_rework", "environment_keeper", "resources", "worker", "undiscovered", "reviewer"], "polarity": "B"},
    # earlier detection: landings grow the tests the gate runs, which finds more before landing
    {"key": "earlier_detection", "nodes": ["landed", "qa_engineer", "tests", "merge_gate"]},
    # broken base: a failed build wakes the pipeline manager, which resumes the gate
    {"key": "broken_base", "nodes": ["pipeline_blocked", "pipeline_manager"], "polarity": "B"},
    # re-planning: a worker blocks a ticket, the coordinator re-plans it into demand, Orchestra starts it again
    {"key": "replanning", "nodes": ["wip", "worker", "blocked", "coordinator", "demand", "orchestra"]},
    # discovery after landing: the deployed build is exercised, findings are filed into demand, the fix goes round
    {"key": "field_discovery", "nodes": ["build", "playtester", "demand", "orchestra", "wip", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"]},   # closed by a discovery event: the defect's circuit, no polarity
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
    # drains it: the controller is this first-order pair, balancing by its link signs; the gate's re-run is
    # the pair's effect, not part of the loop
    assert bb["detected"] and bb["cycle"]["pair"] and bb["cycle"]["polarity"] == "B" and bb["polarity_agrees"] is True, bb
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
    assert sum(1 for e in g["edges"] if e["src"] == "agent:merge_gate" and e["dst"] == "known_rework" and e["kind"] == "fills") == 1   # one fill per gate send-back, via gate_rejected; the pickup drains it
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
    # the rework cycles are conserved circuits of the change: the pickup carries it out of known rework (a carrying
    # link, the defect stays open), the worker re-submits it, the inspection sends it back; no causal polarity
    rv = next(d for d in det["declared"] if d["key"] == "review_rework")["cycle"]
    assert "awaiting_review" in rv["nodes"] and rv["basis"] == "material circuit" and rv["polarity"] is None
    gt = next(d for d in det["declared"] if d["key"] == "gate_rework")["cycle"]
    assert gt["basis"] == "material circuit" and gt["polarity"] is None
    # the blocked ticket is a conserved circuit too: wip → demand (blocked) → wip (started again)
    rp = next(d for d in det["declared"] if d["key"] == "replanning")["cycle"]
    # the blocked ticket is conserved: W → blocked (the worker) → demand (the coordinator re-plans) → W (Orchestra starts it)
    assert {"wip", "blocked", "demand", "agent:coordinator", "agent:orchestra"} <= set(rp["nodes"]) and rp["basis"] == "material circuit"
    fd = next(d for d in det["declared"] if d["key"] == "field_discovery")["cycle"]
    assert fd["basis"].startswith("closes through a discovery") and fd["polarity"] is None and "agent:playtester" in fd["nodes"]   # closed by the finding that drains undiscovered rework: balancing through U, unsigned
    # the hidden stock wakes nobody: only the agents whose verdicts drain it inspect it
    g = fg.build(foundry_stocks(), foundry_agents(), SYSTEM_BINDINGS)
    from_u = {(e["dst"], e["kind"]) for e in g["edges"] if e["src"] == "undiscovered"}
    assert from_u == {("agent:reviewer", "inspects"), ("agent:merge_gate", "inspects"), ("agent:playtester", "inspects")}, from_u   # every agent whose verdict drains it
    assert not any(c["observed"] for c in fg.detect(foundry_stocks(), foundry_agents(), system=SYSTEM_BINDINGS)["cycles"] if "undiscovered" in c["nodes"])
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


def test_conversions_follow_the_products_path_and_mark_coflows():
    """Round 13: a submission is one flow, work in progress → awaiting review; the known defect it
    carries on into undiscovered rework is a co-flow, and the same event seen from known rework
    is not a second flow. A gate landing moves the approved change only."""
    stocks = foundry_stocks()
    g = fg.build(stocks, foundry_agents(), SYSTEM_BINDINGS)
    cs = fg.conversions(g, {}, stocks)
    flows = {(c["src"], c["dst"], c["agent"]) for c in cs if not c["coflow"]}
    coflows = {(c["src"], c["dst"], c["agent"]) for c in cs if c["coflow"]}
    assert ("wip", "awaiting_review", "worker") in flows and ("known_rework", "awaiting_review", "worker") not in flows
    assert ("known_rework", "wip", "orchestra") in flows                                             # the rework flow: the pickup drains known rework into W
    assert ("wip", "undiscovered", "worker") in coflows and ("undiscovered", "known_rework", "reviewer") in coflows
    assert ("approved", "landed", "merge_gate") in flows and not any(c["src"] == "wip" and c["dst"] == "landed" for c in cs)
    assert ("awaiting_review", "known_rework", "reviewer") in flows and ("approved", "known_rework", "merge_gate") in flows


def test_inspect_and_what_if_answer_where_an_agent_belongs():
    """The questions a curator asks before placing an agent: what a stock or agent is connected
    to, and what a hypothetical agent would close. Without the keeper, capability is open and
    the stock view says so; trying the keeper's bindings reports capability closing."""
    from orchestra import foundryquery as fq
    stocks, agents = foundry_stocks(), foundry_agents(keeper=False)
    model = {"stocks": stocks, "loops": EXPECTED}
    det = fg.detect(stocks, agents, EXPECTED, system=SYSTEM_BINDINGS)
    k = fq.inspect(model, agents, det, stock="known_rework")
    assert "reviewer" in k["inflows"]["ticket_transition:IN_REVIEW>REJECTED"] and "orchestra" in k["outflows"]["ticket_transition:REJECTED>IN_PROGRESS"]
    assert any(o["loop"] == "capability" for o in k["open_loops"]) and any(line.startswith("drained by") for line in k["lines"])
    rv = fq.inspect(model, agents, det, agent="reviewer")
    assert {(c["src"], c["dst"]) for c in rv["valve_on"]} >= {("awaiting_review", "approved"), ("awaiting_review", "known_rework")}
    assert {l["key"] for l in rv["loops"]} >= {"review_rework", "gate_rework"} and rv["woken_by"][0]["stock"] == "awaiting_review"
    ev = fq.inspect(model, agents, det, event="staging_restarted")
    assert "build" in ev["drains"] and "orchestra" in ev["emitted_by"] and ev["wakes"] == []
    over = fq.inspect(model, agents, det, system=SYSTEM_BINDINGS)
    assert any(o["loop"] == "capability" for o in over["open_loops"]) and any(u["event"] == "staging_restarted" for u in over["unconsumed_outflows"])
    assert not any(u["event"] == "gate_landed" for u in over["unconsumed_outflows"])      # Orchestra's own loop wakes on it
    w = fq.what_if(model, agents, SYSTEM_BINDINGS, "environment_keeper", ["ticket_transition:REJECTED", "gate_rejected"], ["lesson_decided"], "devex")
    assert w["would_close"] == ["capability"] and w["create_agent"]["wake_on"] == ["ticket_transition:REJECTED", "gate_rejected"]
    assert any(x["stock"] == "resources" for x in w["fills"]) and w["lines"][0].startswith("environment_keeper would close capability")
    blind = fq.what_if(model, agents, SYSTEM_BINDINGS, "watcher", ["staging_restarted"], ["smoke_result"])
    assert blind["would_close"] == [] and {"stock": "build", "event": "staging_restarted"} in blind["would_consume"]
    assert blind["emits_no_stock_carries"] == ["smoke_result"] and any("no stock lists" in line for line in blind["lines"])


def test_a_wake_rule_can_name_the_state_a_transition_leaves():
    from orchestra.org import event_matches
    pickup = {"type": "ticket_transition", "from": "REJECTED", "to": "IN_PROGRESS"}
    start = {"type": "ticket_transition", "from": "OPEN", "to": "IN_PROGRESS"}
    assert event_matches(["ticket_transition:REJECTED>IN_PROGRESS"], pickup) and not event_matches(["ticket_transition:REJECTED>IN_PROGRESS"], start)
    assert event_matches(["ticket_transition:IN_PROGRESS"], start) and event_matches(["ticket_transition:IN_PROGRESS"], pickup)
    cs = fg.conversions(fg.build(foundry_stocks(), foundry_agents(), SYSTEM_BINDINGS), {}, foundry_stocks())
    pick = next(c for c in cs if (c["src"], c["dst"]) == ("known_rework", "wip"))
    assert pick["wake"] == "ticket_transition:REJECTED>IN_PROGRESS"           # the flows table advises the pickup, not every start


def test_a_pause_names_the_candidate_result_it_swallowed():
    from orchestra.foundrymetrics import pause_diagnosis
    st = lambda name, status, tail="": {"name": name, "status": status, "tail": tail}
    runs = [{"id": "r1", "status": "rejected", "batch": ["T-1"], "finished_at": "x", "stages": [st("unit", "passed"), st("acceptance", "failed", "1 failed")]},
            {"id": "r2", "status": "landed", "batch": ["T-2"], "finished_at": "x", "stages": [st("acceptance", "passed")]},
            {"id": "r3", "status": "base_broken", "batch": ["T-1"], "finished_at": "x", "stages": [st("acceptance", "failed", "1 failed, 21 passed")],
             "base_check": [st("acceptance", "failed", "14 failed, 17 errors")]}]
    d = pause_diagnosis(runs)
    assert d["batch"] == ["T-1"] and d["candidate_stage"] == "acceptance" and d["candidate_prior_same"] == 1 and d["base_summary"] == "14 failed, 17 errors" and d["staging_trouble_during"] == 0
    assert pause_diagnosis(runs[:2]) is None


def test_the_broken_base_signal_is_time_since_main_broke_with_nothing_landed():
    from orchestra.foundrymetrics import _base_broken_open
    ev = [{"type": "gate_base_broken", "ts": "2026-10-14T10:00:00+00:00"}]
    t = lambda h: dt.datetime(2026, 10, 14, 10, tzinfo=dt.UTC).timestamp() + h * 3600
    assert _base_broken_open(ev, t(3)) == 3.0 and _base_broken_open(ev, t(-1)) is None
    assert _base_broken_open(ev + [{"type": "gate_landed", "ts": "2026-10-14T11:00:00+00:00"}], t(3)) is None


def test_an_outage_closes_after_an_hour_without_trouble_even_with_no_new_deploy():
    """A paused gate deploys nothing; DORA's restore is service back, so an hour quiet closes it."""
    from orchestra.foundrymetrics import _open_outage
    ev = [{"type": "staging_deployed", "ts": "2026-10-14T00:00:00+00:00"}, {"type": "staging_restarted", "ts": "2026-10-14T01:00:00+00:00"}]
    t = lambda h: dt.datetime(2026, 10, 14, tzinfo=dt.UTC).timestamp() + h * 3600
    assert _open_outage(ev, t(1.5)) == 1800 and _open_outage(ev, t(2.5)) is None
    ev2 = ev + [{"type": "staging_restarted", "ts": "2026-10-14T05:00:00+00:00"}]
    assert _open_outage(ev2, t(5.5)) == 1800                         # the quiet hours between closed the first outage; this one began at 05:00
