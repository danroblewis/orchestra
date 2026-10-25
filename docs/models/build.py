"""python3 docs/models/build.py — emit the user-story models in SD Lab's editor format (MODEL.md) into docs/models/.

Each story is one model of the orchestrated design, plus a variants file describing other
machine assignments (the manual baseline, and others). Extra keys on stocks and flows ("side",
"crosses", "note") are annotations for our planning; SD Lab ignores keys it does not know.
"""
import copy
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)

TIME_UNIT = "working hour"

# Machines shared by every story. Capacities are in machine-hours per working hour.
MACHINES = [
    {"id": "me", "name": "Me", "kind": "person", "color": "#b45309", "capacity": 0.6,
     "note": "About 60% of my working hours are free for this work; the rest is meetings and duties not modelled."},
    {"id": "analyst", "name": "Analyst agent", "kind": "agent", "color": "#7c3aed", "capacity": 1,
     "note": "Research, context, stakeholders, runbooks, root cause. Ad hoc sessions."},
    {"id": "drafter", "name": "Drafter agent", "kind": "agent", "color": "#2563eb", "capacity": 1,
     "note": "Tickets, PR descriptions, replies, Slack and Jira messages. Everything it writes goes to my outbox."},
    {"id": "implementer", "name": "Implementation agents", "kind": "agent", "color": "#0f766e", "capacity": 2,
     "note": "Two worker slots. Code, tests, fixes."},
    {"id": "orchestra", "name": "Orchestra programs", "kind": "code", "color": "#475569", "capacity": 5,
     "note": "Probes, routing, pings, labels, pattern-matched SAIL triage. No model calls."},
]

BUDGET = [
    {"id": "budget", "name": "Agent budget", "unit": "dollars", "initial": 120, "side": "ours",
     "note": "Refilled at $3 per working hour (about $120 a week) from the $190 weekly total."},
]
BUDGET_FLOWS = [
    {"id": "fund", "name": "Weekly budget, spread over working hours", "from": None, "to": "budget",
     "rate": {"form": "constant", "value": 3}, "machine": "environment", "side": "ours"},
]


def stock(id, name, unit, initial=0, side="ours", **kw):
    return {"id": id, "name": name, "unit": unit, "initial": initial, "side": side, **kw}


def flow(id, name, frm, to, rate, machine, work=None, cost=None, side="ours", **kw):
    f = {"id": id, "name": name, "from": frm, "to": to, "rate": rate, "machine": machine, "side": side}
    if work is not None:
        f["work"] = work
    if cost:
        f["uses"] = [{"stock": "budget", "per": cost}]
    f.update(kw)
    return f


AV = {"form": "available"}


def prop(stock, k):
    return {"form": "proportional", "stock": stock, "k": k}


def const(v):
    return {"form": "constant", "value": v}


# Bands: ours on top, the interface in the middle, the company at the bottom. Columns follow the
# order work moves; a second company row (ROW2) holds the stocks work returns from.
BAND = {"ours": 140, "interface": 360, "company": 580}
ROW2 = 760
POS = {
    # story 1
    "t_inbox": (80, "interface"), "t_scoped": (240, "ours"), "t_researched": (400, "ours"),
    "t_ticket_draft": (560, "ours"), "t_ready": (720, "ours"), "t_verifying": (880, "ours"),
    "t_pr_draft": (1040, "ours"), "t_ci": (1200, "company"), "t_ci_failed": (1200, ROW2),
    "t_bot_review": (1360, "company"), "t_bot_comments": (1360, ROW2), "t_post_draft": (1520, "interface"),
    "t_awaiting_review": (1680, "company"), "t_nudges": (1680, "interface"),
    "t_changes_requested": (1840, ROW2), "t_reply_draft": (1840, "interface"), "t_approved": (1840, "company"),
    "t_sailing": (2000, "company"), "t_sail_failed": (2000, ROW2), "t_landed": (2160, "company"),
    "t_close_draft": (2320, "interface"), "t_delivered": (2480, "ours"),
    # story 2
    "p_inbox": (80, "interface"), "p_explained": (240, "ours"), "p_authorised": (400, "ours"),
    "p_briefed": (560, "ours"), "p_gov_followups": (560, 20), "p_gov_tickets": (720, "interface"),
    "p_approved_to_run": (720, "ours"), "p_declined": (560, "interface"), "p_ran": (880, "interface"),
    "p_candidates": (1040, "ours"), "p_archived": (1200, 20), "p_problem_statements": (1200, "ours"),
    "p_in_review": (1360, "company"), "p_policies": (720, "company"),
    # story 3
    "s_current": (240, "ours"), "s_stale": (240, "company"), "s_asks": (560, "interface"),
    "s_answered": (800, "interface"),
    # story 4
    "r_requests": (80, "interface"), "r_briefed": (240, "ours"), "r_comments_draft": (400, "ours"),
    "r_recent": (560, "company"),
}


def layout(stocks):
    for s in stocks:
        if s["id"] == "budget":
            s.setdefault("x", 1300)
            s.setdefault("y", -60)
            continue
        x, row = POS[s["id"]]
        s.setdefault("x", round(x * 1.4))
        s.setdefault("y", BAND.get(row, row) if isinstance(row, str) else row)


SHORT = {
    # story 1 stocks
    "t_inbox": "Asks", "t_scoped": "Scoped", "t_researched": "Researched", "t_ticket_draft": "Ticket draft",
    "t_ready": "Ready", "t_verifying": "Verifying", "t_pr_draft": "PR draft", "t_ci": "Checks running",
    "t_ci_failed": "Checks failed", "t_bot_review": "AI review", "t_bot_comments": "AI comments",
    "t_post_draft": "Review post draft", "t_awaiting_review": "Awaiting review", "t_nudges": "Recent pings",
    "t_changes_requested": "Changes requested", "t_reply_draft": "Replies draft", "t_approved": "Approved",
    "t_sailing": "In SAIL", "t_sail_failed": "SAIL failed", "t_landed": "Landed", "t_close_draft": "Close-out draft",
    "t_delivered": "Delivered",
    # story 1 flows
    "t_arrive": "ask", "t_collect": "collect reqs", "t_research": "research", "t_author": "write ticket",
    "t_approve_ticket": "approve ticket", "t_implement": "implement", "t_verify": "test + AI review",
    "t_submit": "approve + open PR", "t_checks": "PR checks", "t_fix_ci": "fix checks", "t_bot": "company AI review",
    "t_fix_bot": "fix AI comments", "t_post": "post for review", "t_ping": "ping", "t_forget": "fade",
    "t_review": "human review", "t_fix_review": "address comments", "t_send_replies": "send replies",
    "t_label": "SAIL label", "t_sail": "SAIL", "t_triage": "triage failure", "t_close": "draft close-out",
    "t_send_close": "send close-out",
    # story 2
    "p_inbox": "Command asks", "p_explained": "Explained", "p_authorised": "Authorised", "p_briefed": "Briefed",
    "p_approved_to_run": "To run", "p_declined": "Declined", "p_ran": "Ran", "p_gov_followups": "Other-env repeats",
    "p_gov_tickets": "Follow-up tickets", "p_candidates": "Logged", "p_archived": "Archived",
    "p_problem_statements": "Problem statements", "p_in_review": "Proposals in review", "p_policies": "Preventions adopted",
    "p_arrive": "ask", "p_explain": "explain + runbooks", "p_authority": "check authority", "p_context": "root cause + context",
    "p_decide": "decide", "p_run": "run (me only)", "p_log": "log", "p_file_followups": "file follow-ups",
    "p_pattern": "find patterns", "p_propose": "propose", "p_adopt": "adopt",
    # story 3
    "s_current": "Status current", "s_stale": "Status stale", "s_asks": "Manager asks", "s_answered": "Answered",
    "s_drift": "projects move on", "s_refresh": "refresh", "s_ask": "ask", "s_answer": "answer",
    # story 4
    "r_requests": "Review requests", "r_briefed": "Briefed", "r_comments_draft": "Review written",
    "r_recent": "Reviews given (goodwill)", "r_arrive": "request", "r_brief": "pre-read brief", "r_review": "my review",
    "r_post": "post review", "r_fade": "fade",
    # shared
    "budget": "Agent budget", "fund": "weekly budget",
}


def shorten(items):
    for it in items:
        if it["id"] in SHORT:
            long = it["name"]
            it["name"] = SHORT[it["id"]]
            it["note"] = f"{long}. {it['note']}" if it.get("note") else long


def model(id, name, description, stocks, flows, horizon=160):
    stocks = stocks + copy.deepcopy(BUDGET)
    budget_flows = copy.deepcopy(BUDGET_FLOWS)
    layout(stocks)
    shorten(stocks)
    shorten(flows + budget_flows)
    return {"id": id, "name": name, "description": description, "time_unit": TIME_UNIT,
            "horizon": horizon, "dt": 0.25, "stocks": stocks, "flows": flows + budget_flows,
            "machines": MACHINES}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=1) + "\n")


# ---------------------------------------------------------------------------------------------
# Story 1: a simple task asked for by another team, carried from request to landed and announced.
# ---------------------------------------------------------------------------------------------
t_stocks = [
    stock("t_inbox", "Requests waiting for me to collect requirements", "requests", 4, "interface"),
    stock("t_scoped", "Requirements collected", "requests"),
    stock("t_researched", "Researched: problem, stakeholders, related projects", "requests"),
    stock("t_ticket_draft", "Ticket drafted, waiting for my approval", "requests"),
    stock("t_ready", "Ticket approved, waiting for an implementer", "requests"),
    stock("t_verifying", "Implemented, being tested and reviewed by AI", "requests"),
    stock("t_pr_draft", "PR ready, description waiting for my approval", "requests"),
    stock("t_ci", "PR checks running", "PRs", 0, "company"),
    stock("t_ci_failed", "PR checks failed", "PRs", 0, "company"),
    stock("t_bot_review", "Company AI review running", "PRs", 0, "company"),
    stock("t_bot_comments", "Company AI review comments to address", "PRs", 0, "company"),
    stock("t_post_draft", "Review request post drafted, waiting for my approval", "PRs", 0, "interface"),
    stock("t_awaiting_review", "Waiting for human reviewers", "PRs", 0, "company"),
    stock("t_nudges", "Recent review pings", "pings", 0, "interface",
          note="An information stock: pings sent recently. It speeds reviewers up, with diminishing returns."),
    stock("t_changes_requested", "Changes requested by reviewers", "PRs", 0, "company"),
    stock("t_reply_draft", "Fixes pushed, replies waiting for my approval", "PRs", 0, "interface"),
    stock("t_approved", "Approved, waiting for the SAIL label", "PRs", 0, "company"),
    stock("t_sailing", "In SAIL", "PRs", 0, "company"),
    stock("t_sail_failed", "SAIL failed", "PRs", 0, "company"),
    stock("t_landed", "Landed on master", "PRs", 0, "company"),
    stock("t_close_draft", "Jira update and requester message drafted", "requests", 0, "interface"),
    stock("t_delivered", "Delivered: landed, Jira updated, requester told", "requests", 0, "ours",
          final=True, target={"value": 20, "by": 160}),
]
t_flows = [
    flow("t_arrive", "Someone asks me for a simple task", None, "t_inbox", const(0.15), "environment",
         side="company", crosses="slack/jira in"),
    flow("t_collect", "Collect the requirements (me, in the conversation)", "t_inbox", "t_scoped", AV, "me", 0.25,
         side="interface"),
    flow("t_research", "Research the problem, find stakeholders and related projects", "t_scoped", "t_researched",
         AV, "analyst", 0.5, 1.5, crosses="read: jira, docs, slack, code"),
    flow("t_author", "Author the ticket with requirements and completion criteria", "t_researched",
         "t_ticket_draft", AV, "drafter", 0.2, 0.5),
    flow("t_approve_ticket", "Approve the ticket (me)", "t_ticket_draft", "t_ready", AV, "me", 0.1,
         crosses="jira write (via outbox)"),
    flow("t_implement", "Implement on a branch", "t_ready", "t_verifying", AV, "implementer", 2, 6),
    flow("t_verify", "Run tests, internal AI review; sent back or passed", "t_verifying", "t_pr_draft", AV,
         "implementer", 0.5, 1.5, outputs=["t_ready"], split={"t_pr_draft": 0.75, "t_ready": 0.25},
         note="Internal rework loop: a quarter go back for another implementation pass."),
    flow("t_submit", "Approve the PR description; push and open the PR", "t_pr_draft", "t_ci", AV, "me", 0.15,
         side="interface", crosses="github push + open PR"),
    flow("t_checks", "Company PR checks", "t_ci", "t_bot_review", prop("t_ci", 1.0), "environment",
         side="company", outputs=["t_ci_failed"], split={"t_bot_review": 0.85, "t_ci_failed": 0.15}),
    flow("t_fix_ci", "Fix check failures", "t_ci_failed", "t_ci", AV, "implementer", 0.5, 1.5,
         side="interface", crosses="read: check logs; github push"),
    flow("t_bot", "Company AI review", "t_bot_review", "t_post_draft", prop("t_bot_review", 2.0), "environment",
         side="company", outputs=["t_bot_comments"], split={"t_post_draft": 0.5, "t_bot_comments": 0.5}),
    flow("t_fix_bot", "Address the AI review's comments", "t_bot_comments", "t_ci", AV, "implementer", 0.5, 1.5,
         side="interface", crosses="read: PR comments; github push"),
    flow("t_post", "Post for review in our and owning teams' channels (me approves)", "t_post_draft",
         "t_awaiting_review", AV, "me", 0.05, side="interface", crosses="slack write (via outbox)"),
    flow("t_ping", "Ping reviewers about a waiting PR, about once a day", None, "t_nudges",
         prop("t_awaiting_review", 0.125), "orchestra", 0.001, side="interface", crosses="slack write",
         note="Auto after the template earned autonomy; until then each ping is an outbox item."),
    flow("t_forget", "Pings fade from reviewers' minds", "t_nudges", None, prop("t_nudges", 0.25), "environment",
         side="company"),
    flow("t_review", "Human review", "t_awaiting_review", "t_approved", prop("t_awaiting_review", 1 / 16),
         "environment", side="company", outputs=["t_changes_requested"],
         split={"t_approved": 0.6, "t_changes_requested": 0.4},
         effects=[{"stock": "t_nudges", "shape": "table", "points": [[0, 0.6], [0.5, 1], [2, 1.5], [6, 1.7]]}],
         note="Mean first response 16 working hours at one recent ping per waiting PR; slower with none."),
    flow("t_fix_review", "Address reviewers' comments; draft replies", "t_changes_requested", "t_reply_draft", AV,
         "implementer", 1.0, 3, side="interface", crosses="read: review threads"),
    flow("t_send_replies", "Approve replies; push; re-request review", "t_reply_draft", "t_ci", AV, "me", 0.15,
         side="interface", crosses="github push + replies (via outbox)"),
    flow("t_label", "Add the SAIL label", "t_approved", "t_sailing", AV, "me", 0.02, side="interface",
         crosses="github label"),
    flow("t_sail", "SAIL", "t_sailing", "t_landed", prop("t_sailing", 0.25), "environment", side="company",
         outputs=["t_sail_failed"], split={"t_landed": 0.7, "t_sail_failed": 0.3}),
    flow("t_triage", "Triage the SAIL failure: known flake gets a re-label, real failure goes to a fix",
         "t_sail_failed", "t_sailing", AV, "orchestra", 0.01, side="interface", outputs=["t_ci_failed"],
         split={"t_sailing": 0.67, "t_ci_failed": 0.33}, crosses="read: SAIL logs; github label"),
    flow("t_close", "Draft the Jira update and the message to the requester", "t_landed", "t_close_draft", AV,
         "drafter", 0.1, 0.3, crosses="read: jira, slack"),
    flow("t_send_close", "Approve and send: Jira comment and status, Slack reply", "t_close_draft", "t_delivered",
         AV, "me", 0.05, side="interface", crosses="jira write + slack write (via outbox)"),
]
write("story-1-simple-task.json", model(
    "story-1-simple-task", "Story 1: a simple task for another team",
    "A member of another team asks for a simple task. I collect the requirements; everything from research "
    "to the requester being told is carried by agents and programs, with my approval at each point where "
    "something is said or pushed as me. The company's side (checks, AI review, human review, SAIL) is the "
    "environment. Time unit: a working hour; horizon four weeks.",
    t_stocks, t_flows))

ME = lambda work: {"machine": "me", "work": work, "uses": []}  # noqa: E731
write("story-1-simple-task.variants.json", {
    "manual": {
        "description": "Today: I do every step myself, with no agents and no budget spent.",
        "flows": {
            "t_research": ME(1.5), "t_author": ME(1.0), "t_approve_ticket": ME(0.01),
            "t_implement": ME(3.0), "t_verify": ME(1.0), "t_submit": ME(0.5),
            "t_fix_ci": ME(0.75), "t_fix_bot": ME(0.5), "t_post": ME(0.15),
            "t_ping": {"machine": "me", "work": 0.1, "rate": prop("t_awaiting_review", 1 / 24)},
            "t_fix_review": ME(1.0), "t_send_replies": ME(0.25), "t_label": ME(0.05),
            "t_triage": ME(0.25), "t_close": ME(0.25),
        },
    },
    "rising": {
        "description": "Orchestrated, with requests rising to 10 a week (0.25 an hour).",
        "flows": {"t_arrive": {"rate": const(0.25)}},
    },
    "manual-rising": {
        "base": "manual",
        "description": "Manual, with requests rising to 10 a week.",
        "flows": {"t_arrive": {"rate": const(0.25)}},
    },
    "better-first-pass": {
        "description": "Orchestrated, with fewer rounds at every boundary: internal rework 10%, company AI "
                       "review comments on 35%, human change requests on 25%.",
        "flows": {"t_verify": {"split": {"t_pr_draft": 0.9, "t_ready": 0.1}},
                  "t_bot": {"split": {"t_post_draft": 0.65, "t_bot_comments": 0.35}},
                  "t_review": {"split": {"t_approved": 0.75, "t_changes_requested": 0.25}}},
    },
})

# ---------------------------------------------------------------------------------------------
# Story 2: a request to run a command on a production bastion host.
# ---------------------------------------------------------------------------------------------
p_stocks = [
    stock("p_inbox", "Requests to run a production command", "requests", 1, "interface"),
    stock("p_explained", "Command explained: runbooks, impact, risks", "requests"),
    stock("p_authorised", "Chain of authority verified", "requests"),
    stock("p_briefed", "Context ready: customer ticket, unsafe ramp, rollout follow-up, other environments",
          "requests"),
    stock("p_approved_to_run", "Decided to run, waiting for me to run it", "requests"),
    stock("p_declined", "Declined or redirected", "requests", 0, "interface", final=True),
    stock("p_ran", "Ran; being logged", "requests"),
    stock("p_gov_followups", "Manual repeats needed in government and monthly environments", "follow-ups", 0,
          "ours"),
    stock("p_gov_tickets", "Follow-up tickets filed", "tickets", 0, "interface", final=True),
    stock("p_candidates", "Logged; candidate for prevention", "requests"),
    stock("p_archived", "No pattern worth acting on", "requests", 0, "ours", final=True),
    stock("p_problem_statements", "Problem statements drafted from patterns", "documents"),
    stock("p_in_review", "Problem statements and proposals in company review", "documents", 0, "company"),
    stock("p_policies", "Prevention adopted: policy or automation", "policies", 0, "company", final=True,
          target={"value": 2, "by": 480}),
]
p_flows = [
    flow("p_arrive", "Someone asks me to run a command on a bastion", None, "p_inbox", const(0.05), "environment",
         side="company", crosses="slack/jira in",
         effects=[{"stock": "p_policies", "shape": "table", "points": [[0, 1], [2, 0.75], [5, 0.5], [10, 0.35]]}],
         note="Adopted prevention lowers how often these requests come at all: the long balancing loop."),
    flow("p_explain", "Find runbooks; explain what the command does, its impact and risks", "p_inbox",
         "p_explained", AV, "analyst", 0.5, 2, crosses="read: runbooks, code, docs"),
    flow("p_authority", "Verify the chain of authority for a production change", "p_explained", "p_authorised",
         AV, "orchestra", 0.02, outputs=["p_declined"], split={"p_authorised": 0.9, "p_declined": 0.1},
         crosses="read: jira approvals, change tickets, org chart"),
    flow("p_context", "Root cause and context: customer ticket? unsafe ramp? rollout follow-up? repeats elsewhere?",
         "p_authorised", "p_briefed", AV, "analyst", 0.75, 3,
         outputs=["p_gov_followups"], split={"p_briefed": 0.8, "p_gov_followups": 0.2},
         crosses="read: customer jira, flag history, deploys, release calendars",
         note="Simplification: a fifth of requests need a repeat in other environments; the split moves "
              "that share into follow-ups rather than duplicating the request."),
    flow("p_decide", "Read the brief and decide (me)", "p_briefed", "p_approved_to_run", AV, "me", 0.25,
         outputs=["p_declined"], split={"p_approved_to_run": 0.85, "p_declined": 0.15}),
    flow("p_run", "Run the command (me only, never an agent)", "p_approved_to_run", "p_ran", AV, "me", 0.25,
         side="interface", crosses="bastion host (human only)"),
    flow("p_log", "Log what happened and why, where the company will see it", "p_ran", "p_candidates", AV,
         "drafter", 0.1, 0.3, side="interface", crosses="jira/slack write (via outbox)"),
    flow("p_file_followups", "File follow-up tickets for the other environments", "p_gov_followups",
         "p_gov_tickets", AV, "drafter", 0.1, 0.3, side="interface", crosses="jira write (via outbox)"),
    flow("p_pattern", "Look for a pattern across requests worth preventing", "p_candidates", "p_archived", AV,
         "analyst", 0.2, 0.8, outputs=["p_problem_statements"],
         split={"p_archived": 0.75, "p_problem_statements": 0.25}),
    flow("p_propose", "Turn a problem statement into a proposal (me edits, agent drafts)", "p_problem_statements",
         "p_in_review", AV, "me", 1.5, 2, side="interface", crosses="docs write; slack post for review"),
    flow("p_adopt", "Company reviews and adopts the prevention", "p_in_review", "p_policies",
         prop("p_in_review", 1 / 80), "environment", side="company",
         note="About two working weeks from proposal to adoption, when it is adopted at all."),
]
write("story-2-prod-command.json", model(
    "story-2-prod-command", "Story 2: a request to run a production command",
    "Someone asks me to run a command on a production bastion. Before I run it: what it does, its impact and "
    "risk, who authorised it, why it is needed, and whether it repeats in other environments. After: it is "
    "logged, and patterns become problem statements that, once adopted, make these requests rarer. Agents "
    "never run the command. Time unit: a working hour; horizon twelve weeks.",
    p_stocks, p_flows, horizon=480))
write("story-2-prod-command.variants.json", {
    "manual": {
        "description": "Today: I explain and check it myself, and there is no time for root cause, logging "
                       "for others, follow-up tickets or prevention.",
        "flows": {
            "p_explain": ME(1.0), "p_authority": ME(0.5), "p_context": ME(0.5),
            "p_log": ME(0.1), "p_file_followups": {"machine": None}, "p_pattern": {"machine": None},
            "p_propose": {"machine": None},
        },
    },
    "manual-thorough": {
        "description": "Me doing all of it properly: root cause, logging, follow-ups, patterns and proposals.",
        "flows": {
            "p_explain": ME(1.0), "p_authority": ME(0.5), "p_context": ME(1.5),
            "p_log": ME(0.25), "p_file_followups": ME(0.25), "p_pattern": ME(0.5),
            "p_propose": ME(4.0),
        },
    },
})

# ---------------------------------------------------------------------------------------------
# Story 3: a manager asks for status I don't have in my head.
# ---------------------------------------------------------------------------------------------
s_stocks = [
    stock("s_current", "Status items current in my status page", "items", 30),
    stock("s_stale", "Status items stale: something changed since they were read", "items", 30),
    stock("s_asks", "Questions from managers waiting for an answer", "questions", 1, "interface"),
    stock("s_answered", "Questions answered", "questions", 0, "interface", final=True,
          target={"value": 14, "by": 160}),
]
s_flows = [
    flow("s_drift", "Projects move on: tickets, docs and threads change", "s_current", "s_stale",
         prop("s_current", 0.05), "environment", side="company",
         note="About a twentieth of what I know goes stale every working hour across 60 tracked items."),
    flow("s_refresh", "Re-read changed tickets, docs and threads; update the status page", "s_stale",
         "s_current", AV, "analyst", 0.05, 0.1, crosses="read: jira, docs, slack"),
    flow("s_ask", "A manager asks for an update", None, "s_asks", const(0.1), "environment", side="company",
         crosses="slack/meeting in"),
    flow("s_answer", "Answer: send the prepared update, or do the research first", "s_asks", "s_answered", AV,
         "me", 1.5, side="interface", crosses="slack write",
         effects=[{"stock": "s_stale", "shape": "table", "points": [[0, 10], [5, 6], [20, 2], [45, 1], [60, 0.8]]}],
         note="1.5 hours of my research per answer when everything is stale; under 10 minutes when the "
              "status page is current."),
]
write("story-3-status-request.json", model(
    "story-3-status-request", "Story 3: a manager asks for status",
    "Managers ask me about projects assuming I remember. If the status page is current I send it; if not I "
    "redo the research. The analyst keeps the page current as tickets, docs and threads change. Time unit: "
    "a working hour; horizon four weeks.",
    s_stocks, s_flows))
write("story-3-status-request.variants.json", {
    "manual": {"description": "Today: nobody keeps a status page; every answer starts from scratch.",
               "flows": {"s_refresh": {"machine": None}}},
})

# ---------------------------------------------------------------------------------------------
# Story 4 (invented): teammates' review requests, and the goodwill that comes back.
# ---------------------------------------------------------------------------------------------
r_stocks = [
    stock("r_requests", "Review requests to me", "PRs", 3, "interface"),
    stock("r_briefed", "Pre-read brief ready: what changed, risk, likely bugs, related commits", "PRs"),
    stock("r_comments_draft", "My review written, comments waiting to be posted", "PRs"),
    stock("r_recent", "Reviews I gave recently", "reviews", 0, "company",
          note="Stands in for reviewer goodwill toward me; decays over about two weeks."),
]
r_flows = [
    flow("r_arrive", "A teammate requests my review", None, "r_requests", const(0.2), "environment",
         side="company", crosses="github in"),
    flow("r_brief", "Pre-read the change and prepare a brief", "r_requests", "r_briefed", AV, "analyst", 0.2, 0.5,
         crosses="read: PR, code, git log"),
    flow("r_review", "Review it myself (the verdict is mine)", "r_briefed", "r_comments_draft", AV, "me", 0.4),
    flow("r_post", "Post the review", "r_comments_draft", "r_recent", AV, "me", 0.02, side="interface",
         crosses="github write"),
    flow("r_fade", "Goodwill fades", "r_recent", None, prop("r_recent", 1 / 80), "environment", side="company"),
]
write("story-4-reviews-given.json", model(
    "story-4-reviews-given", "Story 4: reviewing teammates' PRs",
    "Teammates ask me for reviews. An agent prepares a brief; I review and post. Reviews given recently stand "
    "in for goodwill, which (in the desk model) speeds up reviews of my own PRs. Time unit: a working hour; "
    "horizon four weeks.",
    r_stocks, r_flows))
write("story-4-reviews-given.variants.json", {
    "manual": {"description": "Today: no brief; I read each change cold.",
               "flows": {"r_brief": ME(0.01), "r_review": ME(0.75)}},
})

# Declared couplings between stories, applied when the desk model is assembled.
write("desk.couplings.json", {
    "description": "Effects one story's stocks have on another story's flows. Every coupling is declared here.",
    "effects": [
        {"flow": "t_review", "effect": {"stock": "r_recent", "shape": "table",
                                         "points": [[0, 0.7], [10, 1], [25, 1.3], [50, 1.4]]},
         "note": "Reciprocity: reviewers I recently reviewed for respond faster to my PRs."},
    ],
})
print("wrote", sorted(p.name for p in OUT.iterdir()))
