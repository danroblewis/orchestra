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


# rows for stocks placed by hand (x, y given on the stock)
ROW = {"ours_top": -80, "ours": 100, "ours_low": 240, "interface": 420, "company": 620, "company_low": 800}


def at(x, row):
    return {"x": x, "y": ROW[row]}


def table(stock, *points):
    return {"stock": stock, "shape": "table", "points": [list(p) for p in points]}


def linear(c, **terms):
    return {"form": "linear", "c": c, "terms": [{"stock": k, "k": v} for k, v in terms.items()]}


def layout(stocks):
    for s in stocks:
        if s["id"] == "budget":
            s.setdefault("x", 1300)
            s.setdefault("y", -60)
            continue
        if "x" in s and "y" in s:
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
        if it["id"] in SHORT and "note" not in it:
            long = it["name"]
            it["name"] = SHORT[it["id"]]
            it["note"] = f"{long}. {it['note']}" if it.get("note") else long


def model(id, name, description, stocks, flows, horizon=160, loops=None, inputs=None):
    stocks = stocks + copy.deepcopy(BUDGET)
    budget_flows = copy.deepcopy(BUDGET_FLOWS)
    layout(stocks)
    shorten(stocks)
    shorten(flows + budget_flows)
    extra = {"loops": loops} if loops else {}
    if inputs:
        extra["inputs"] = inputs
    return {**extra, "id": id, "name": name, "description": description, "time_unit": TIME_UNIT,
            "horizon": horizon, "dt": 0.25, "stocks": stocks, "flows": flows + budget_flows,
            "machines": MACHINES}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=1) + "\n")


# ---------------------------------------------------------------------------------------------
# Story 1: simple tasks for other teams, done by agents that learn (or don't).
#
# The chain from ask to landed is the material. The loops are what make it dynamic:
#   R learning      failures and late findings -> lessons -> playbook -> fewer failures and flaws
#   B decay         the playbook goes stale as our own changes land (churn)
#   B overload      past a size, a bigger playbook hurts (context rot): the effect tables turn down
#   R trap          a big backlog stops lessons being captured -> playbook decays -> more failures
#   B trust         clean landings raise my trust; late findings and bugs cut it; trust decides
#                   how much I check, which decides how many flaws escape
#   B fatigue       a long review queue slows reviewers and lowers how many flaws they catch
#   R debt          landings add debt; debt lowers success; paying it down competes for agents
#   R reputation    delivering builds requesters' confidence, which brings more asks
#   B budget        agent work draws on the budget; an empty budget stops agent work
# Outcome splits and routing run on program or environment flows with no machine time, so the
# effects change their rates; work that takes time (attempts, checks, fixes) runs on machines.
# ---------------------------------------------------------------------------------------------
S1_LOOPS = [
    {"id": "R-learning", "polarity": "reinforcing", "stocks": ["t_failed", "t_lessons", "t_playbook", "t_attempted"],
     "says": "Failures become lessons; lessons become playbook; a better playbook means fewer failures and flaws."},
    {"id": "B-decay", "polarity": "balancing", "stocks": ["t_playbook", "t_landed_recent"],
     "says": "The playbook goes stale as the code it describes changes; the faster we land, the faster it rots."},
    {"id": "B-overload", "polarity": "balancing", "stocks": ["t_playbook"],
     "says": "Past about 120 entries a bigger playbook lowers success: too much context."},
    {"id": "R-trap", "polarity": "reinforcing", "stocks": ["t_open", "t_lessons", "t_playbook"],
     "says": "When the backlog is long, lessons are not captured; the playbook decays; more work fails; the backlog grows."},
    {"id": "B-trust", "polarity": "balancing", "stocks": ["t_trust", "t_check_flawed", "t_review_flawed", "t_latent", "t_bugs"],
     "says": "Clean landings raise trust; trust lowers how much I check; more flaws escape; late findings cut trust."},
    {"id": "B-fatigue", "polarity": "balancing", "stocks": ["t_review_sound", "t_review_flawed"],
     "says": "A long review queue slows reviewers and lowers how many flaws they catch."},
    {"id": "R-debt", "polarity": "reinforcing", "stocks": ["t_debt", "t_attempted", "t_latent"],
     "says": "Landings, especially flawed ones, add debt; debt slows attempts and raises flaws; paying it down competes for agents."},
    {"id": "R-reputation", "polarity": "reinforcing", "stocks": ["t_reputation", "t_asks", "t_landed_recent"],
     "says": "Delivering builds requesters' confidence, which brings more asks; bugs erode it."},
]

t_stocks = [
    # demand
    stock("t_reputation", "Requesters' confidence", "points", 20, "company", **at(0, "company"),
          note="How much other teams expect me to deliver. It brings asks, grows with landings, falls with bugs."),
    stock("t_asks", "Asks", "requests", 4, "interface", **at(0, "interface")),
    stock("t_scoped", "Scoped", "requests", 0, "ours", **at(200, "ours")),
    stock("t_ticket_draft", "Ticket draft", "requests", 0, "interface", **at(400, "interface"),
          note="Researched and written up; waiting for my approval."),
    stock("t_open", "Open tickets", "requests", 2, "ours", **at(600, "ours"),
          note="Ready for an implementation attempt: new tickets, diagnosed failures, bugs coming back."),
    # attempts and their outcomes
    stock("t_attempted", "Attempted", "attempts", 0, "ours", **at(800, "ours"),
          note="An attempt finished; its outcome is decided by the playbook and the debt."),
    stock("t_sound", "Done, sound", "changes", 0, "ours", **at(1000, "ours")),
    stock("t_flawed", "Done, hidden flaw", "changes", 0, "ours", **at(1000, "ours_low"),
          note="Looks done, tests pass, but has a defect nobody has seen yet."),
    stock("t_failed", "Failed or caught", "attempts", 0, "ours", **at(800, "ours_low"),
          note="Visibly failed attempts, flaws I caught, and flaws reviewers caught: to be diagnosed."),
    # learning and the area's health
    stock("t_lessons", "Lessons not written down", "lessons", 0, "ours", **at(700, "ours_top")),
    stock("t_playbook", "Agent playbook", "entries", 20, "ours", **at(950, "ours_top"),
          note="Policies, docs, skills and tools the agents use for this class of task, written by the agents from lessons."),
    stock("t_debt", "Technical debt", "points", 20, "ours", **at(1250, "ours_top"),
          note="Shortcuts in the code the agents work in."),
    stock("t_trust", "My trust in the agents", "points", 30, "ours", **at(1550, "ours_top"),
          note="Decides how much of the agents' work I check myself."),
    # my checks
    stock("t_check_sound", "To check (sound)", "changes", 0, "interface", **at(1200, "interface")),
    stock("t_check_flawed", "To check (flawed)", "changes", 0, "interface", **at(1400, "interface")),
    stock("t_nudges", "Recent pings", "pings", 0, "interface", **at(1700, "interface")),
    # the company's side
    stock("t_pr_sound", "PR checks (sound)", "PRs", 0, "company", **at(1250, "company")),
    stock("t_pr_flawed", "PR checks (flawed)", "PRs", 0, "company", **at(1250, "company_low")),
    stock("t_review_sound", "In review (sound)", "PRs", 0, "company", **at(1500, "company")),
    stock("t_review_flawed", "In review (flawed)", "PRs", 0, "company", **at(1500, "company_low")),
    stock("t_nits", "Nits requested", "PRs", 0, "company", **at(1750, "company_low"),
          note="Change requests on sound PRs: style, naming, small asks. A fix round, not a flaw."),
    stock("t_changes", "Flaw found late", "PRs", 0, "company", **at(2000, "company_low"),
          note="A real flaw found by company checks or reviewers. It costs trust and teaches a lesson."),
    stock("t_approved", "Approved", "PRs", 0, "company", **at(1750, "company")),
    stock("t_sailing", "In SAIL", "PRs", 0, "company", **at(2000, "company")),
    stock("t_sail_failed", "SAIL failed", "PRs", 0, "company", **at(2250, "company_low")),
    stock("t_landed_recent", "Landed recently", "PRs", 0, "company", **at(2250, "company"),
          note="Landed in about the last two weeks: the code churn that ages the playbook, and the evidence that builds trust and reputation."),
    stock("t_latent", "Landed with a hidden flaw", "PRs", 0, "company", **at(2500, "company_low")),
    stock("t_bugs", "Bugs found in production", "bugs", 0, "company", **at(2750, "company_low")),
    stock("t_delivered", "Delivered", "PRs", 0, "ours", final=True, target={"value": 100, "by": 1040},
          **at(2500, "ours"), note="Landed and out of the recent window."),
]
P = "t_playbook"
t_flows = [
    # demand and reputation
    flow("t_ask", "ask", None, "t_asks", linear(0.06, t_reputation=0.003), "environment", side="company",
         crosses="slack/jira in", note="Someone asks me for a simple task; more asks when requesters trust me to deliver."),
    flow("t_rep_gain", "confidence grows", None, "t_reputation", prop("t_landed_recent", 0.05), "environment",
         side="company"),
    flow("t_rep_loss", "confidence fades", "t_reputation", None, prop("t_reputation", 0.012), "environment",
         side="company", effects=[table("t_bugs", (0, 1), (2, 1.6), (5, 2.5)),
                                  table("t_open", (0, 1), (10, 1.3), (25, 2), (50, 3))],
         note="Confidence fades on its own, faster while bugs are open, and faster when asks sit in my backlog."),
    # intake
    flow("t_collect", "collect reqs", "t_asks", "t_scoped", AV, "me", 0.25, side="interface"),
    flow("t_research", "research + ticket", "t_scoped", "t_ticket_draft", AV, "analyst", 0.6, 2,
         crosses="read: jira, docs, slack, code"),
    flow("t_approve_ticket", "approve ticket", "t_ticket_draft", "t_open", AV, "me", 0.1, side="interface",
         crosses="jira write (via outbox)"),
    # attempts: machine time; slower in debt-laden code
    flow("t_attempt", "attempt", "t_open", "t_attempted", AV, "implementer", 2, 6,
         effects=[table("t_debt", (0, 1.2), (20, 1), (60, 0.7), (120, 0.5))],
         note="An implementation attempt with tests. Slower where the debt is high."),
    # outcomes: no machine time; shares set by the playbook (with overload) and the debt
    flow("t_ok", "sound", "t_attempted", "t_sound", prop("t_attempted", 2.2), "environment",
         effects=[table(P, (0, 0.7), (20, 1), (60, 1.35), (120, 1.45), (220, 1.1)),
                  table("t_debt", (0, 1.1), (20, 1), (80, 0.75), (150, 0.55))]),
    flow("t_flaw", "hidden flaw", "t_attempted", "t_flawed", prop("t_attempted", 0.8), "environment",
         effects=[table(P, (0, 1.4), (20, 1), (60, 0.6), (120, 0.5), (220, 0.85)),
                  table("t_debt", (0, 0.8), (20, 1), (80, 1.6), (150, 2.2))]),
    flow("t_fail", "fails", "t_attempted", "t_failed", prop("t_attempted", 1.0), "environment",
         effects=[table(P, (0, 1.4), (20, 1), (60, 0.55), (120, 0.45), (220, 0.75))]),
    # diagnosis and learning
    flow("t_diagnose", "diagnose + requeue", "t_failed", "t_open", AV, "analyst", 0.4, 1.5),
    flow("t_lesson", "capture lessons", None, "t_lessons",
         linear(0, t_failed=3, t_changes=2, t_bugs=2, t_sound=1.5),
         "orchestra", 0, effects=[table("t_open", (0, 1), (10, 0.8), (25, 0.4), (50, 0.15))],
         note="Failures and late findings leave lessons, and successes leave patterns worth keeping, unless the backlog is long and nobody stops to write them down."),
    flow("t_codify", "write playbook", "t_lessons", P, AV, "drafter", 0.3, 1,
         note="The agents turn lessons into policies, docs, skills and tools for themselves."),
    flow("t_obsolete", "goes stale", P, None, prop(P, 0.003), "environment",
         effects=[table("t_landed_recent", (0, 0.5), (10, 1), (30, 1.8))],
         note="About six weeks' half-life, faster when much is landing in the area."),
    # debt
    flow("t_debt_in", "debt added", None, "t_debt", linear(0, t_landed_recent=0.01, t_latent=0.1), "environment",
         effects=[table(P, (0, 1.5), (60, 0.7), (150, 0.6))],
         note="Every landing adds some debt; flawed ones add more; a good playbook adds less."),
    flow("t_refactor", "pay down debt", "t_debt", None, prop("t_debt", 0.01), "implementer", 0.2, 0.4,
         note="Agents pay debt down when they have time; under load this is the first thing squeezed."),
    # my checks: trust decides the routing
    flow("t_route_check_s", "route to my check", "t_sound", "t_check_sound", prop("t_sound", 2), "orchestra", 0,
         effects=[table("t_trust", (0, 1), (40, 0.6), (70, 0.25), (100, 0.1))]),
    flow("t_route_pass_s", "auto-pass", "t_sound", "t_pr_sound", prop("t_sound", 2), "orchestra", 0,
         effects=[table("t_trust", (0, 0.05), (40, 0.6), (70, 1.2), (100, 1.6))], crosses="github push + open PR"),
    flow("t_route_check_f", "route to my check", "t_flawed", "t_check_flawed", prop("t_flawed", 2), "orchestra", 0,
         effects=[table("t_trust", (0, 1), (40, 0.6), (70, 0.25), (100, 0.1))]),
    flow("t_route_pass_f", "auto-pass", "t_flawed", "t_pr_flawed", prop("t_flawed", 2), "orchestra", 0,
         effects=[table("t_trust", (0, 0.05), (40, 0.6), (70, 1.2), (100, 1.6))], crosses="github push + open PR"),
    flow("t_check_s", "my check: fine", "t_check_sound", "t_pr_sound", AV, "me", 0.3, side="interface",
         crosses="github push + open PR"),
    flow("t_check_f", "my check: caught", "t_check_flawed", "t_failed", AV, "me", 0.4, side="interface"),
    # company checks and AI review: catch some flaws
    flow("t_ci_s", "checks + AI review", "t_pr_sound", "t_review_sound", prop("t_pr_sound", 1.0), "environment",
         side="company"),
    flow("t_ci_f", "checks + AI review", "t_pr_flawed", "t_review_flawed", prop("t_pr_flawed", 1.0), "environment",
         side="company", outputs=["t_changes"], split={"t_review_flawed": 0.6, "t_changes": 0.4},
         note="Company checks and the AI reviewer catch about 40% of flaws."),
    # human review: pings help; a long queue slows reviewers and blunts their attention
    flow("t_ping", "ping", None, "t_nudges", linear(0, t_review_sound=0.125, t_review_flawed=0.125), "orchestra", 0,
         side="interface", crosses="slack write"),
    flow("t_forget", "fade", "t_nudges", None, prop("t_nudges", 0.25), "environment", side="company"),
    flow("t_rev_ok", "approve", "t_review_sound", "t_approved", prop("t_review_sound", 1 / 24), "environment",
         side="company", effects=[table("t_nudges", (0, 0.6), (1, 1), (3, 1.4), (8, 1.6)),
                                  table("t_review_sound", (0, 1.2), (5, 1), (15, 0.7), (30, 0.45))]),
    flow("t_rev_nit", "request nits", "t_review_sound", "t_nits", prop("t_review_sound", 1 / 48), "environment",
         side="company", effects=[table("t_nudges", (0, 0.6), (1, 1), (3, 1.4), (8, 1.6))]),
    flow("t_fix_nits", "fix nits", "t_nits", "t_pr_sound", AV, "implementer", 0.5, 1.5, side="interface",
         crosses="read: threads; github push; replies via outbox"),
    flow("t_rev_catch", "reviewer catches flaw", "t_review_flawed", "t_changes", prop("t_review_flawed", 0.7 / 16),
         "environment", side="company",
         effects=[table("t_nudges", (0, 0.6), (1, 1), (3, 1.4), (8, 1.6)),
                  table("t_review_sound", (0, 1.1), (5, 1), (15, 0.6), (30, 0.3))]),
    flow("t_rev_miss", "reviewer misses flaw", "t_review_flawed", "t_latent", prop("t_review_flawed", 0.3 / 16),
         "environment", side="company",
         effects=[table("t_nudges", (0, 0.6), (1, 1), (3, 1.4), (8, 1.6)),
                  table("t_review_sound", (0, 0.8), (15, 1.4), (30, 2))],
         note="Approved with the flaw still in it; it lands, and surfaces later."),
    flow("t_back", "back to diagnosis", "t_changes", "t_failed", prop("t_changes", 0.5), "orchestra", 0,
         side="interface"),
    # landing
    flow("t_label", "SAIL label", "t_approved", "t_sailing", AV, "me", 0.02, side="interface", crosses="github label"),
    flow("t_sail", "SAIL", "t_sailing", "t_landed_recent", prop("t_sailing", 0.25), "environment", side="company",
         outputs=["t_sail_failed"], split={"t_landed_recent": 0.75, "t_sail_failed": 0.25}),
    flow("t_relabel", "re-label flake", "t_sail_failed", "t_sailing", prop("t_sail_failed", 0.5), "orchestra", 0,
         side="interface", crosses="read: SAIL logs; github label"),
    flow("t_settle", "leaves the recent window", "t_landed_recent", "t_delivered", prop("t_landed_recent", 1 / 80),
         "environment", side="company"),
    # flaws that landed surface as bugs, which come back as work
    flow("t_surface", "bug surfaces", "t_latent", "t_bugs", prop("t_latent", 1 / 120), "environment",
         side="company"),
    flow("t_bug_ticket", "bug becomes a ticket", "t_bugs", "t_open", prop("t_bugs", 0.1), "orchestra", 0,
         side="interface", crosses="read: jira; jira write"),
    # trust
    flow("t_trust_gain", "trust earned", None, "t_trust", prop("t_landed_recent", 0.03), "environment",
         effects=[table("t_trust", (0, 1), (80, 0.5), (100, 0))]),
    flow("t_trust_loss", "trust lost", "t_trust", None, prop("t_trust", 0.002), "environment",
         effects=[table("t_changes", (0, 1), (1, 3), (3, 6)), table("t_bugs", (0, 1), (1, 4), (3, 8))],
         note="Trust erodes slowly on its own, and sharply when flaws are found late or bugs appear."),
]
write("story-1-simple-task.json", model(
    "story-1-simple-task", "Story 1: simple tasks, done by agents that learn",
    "Other teams ask me for simple tasks. I collect the requirements; agents research, write the ticket, attempt it, "
    "and learn from failures by writing their own playbook. Whether an attempt succeeds, fails, or hides a flaw "
    "depends on the playbook and the code's debt. My trust in the agents decides how much I check; what I don't "
    "check goes to the company, whose checks and reviewers catch some flaws and miss others, which land and come "
    "back as bugs. Delivering builds requesters' confidence, which brings more asks. Time unit: a working hour; "
    "horizon 26 weeks.",
    t_stocks, t_flows, horizon=1040, loops=S1_LOOPS))

ME = lambda work: {"machine": "me", "work": work, "uses": []}  # noqa: E731
OFF = {"machine": None}
write("story-1-simple-task.variants.json", {
    "manual": {
        "description": "Today: I research, implement and fix everything myself. I check my own work as I go, "
                       "so nothing is routed for a separate check. My know-how stays where it is: "
                       "nobody writes a playbook, and nothing decays.",
        "flows": {
            "t_research": ME(1.5), "t_attempt": ME(4.0), "t_diagnose": ME(0.75), "t_codify": OFF,
            "t_route_check_s": OFF, "t_route_check_f": OFF,
            "t_route_pass_s": {"effects": []}, "t_route_pass_f": {"effects": []},
            "t_fix_nits": ME(0.75), "t_refactor": ME(1.0),
            "t_lesson": OFF, "t_obsolete": OFF,
        },
    },
    "no-learning": {
        "description": "Agents, but nobody writes the playbook: failures are fixed and forgotten.",
        "flows": {"t_codify": OFF},
    },
    "surge": {
        "description": "Twice the asks from week one (a reorganisation sends everything my way).",
        "flows": {"t_ask": {"rate": linear(0.2, t_reputation=0.003)}},
    },
    "surge-protected": {
        "base": "surge",
        "description": "The surge, with lesson capture protected: lessons are written down however long the backlog.",
        "flows": {"t_lesson": {"effects": []}},
    },
    "blind-trust": {
        "description": "Agents, starting with high trust (80): I check little from day one.",
        "stocks": {"t_trust": {"initial": 80}},
    },
})


# ---------------------------------------------------------------------------------------------
# Story 2: requests to run production commands, and the loops that make them rarer and safer.
#
#   B prevention    logged cases -> problem statements -> proposals -> adopted policies -> fewer asks
#   R evidence      more logged cases make a stronger proposal, adopted sooner
#   R crisis        an incident caused by a command speeds adoption (never waste a crisis) and
#                   becomes a postmortem, which becomes a problem statement
#   R runbooks      every case and incident teaches the runbooks; better runbooks mean faster
#                   explanations and fewer incidents
#   B decay         runbooks go stale as systems change; policies erode as people work around them
#   B compliance    asking requesters for missing authority teaches them to bring it next time
#   R repeats       repeats needed in other environments, if never filed, come back later as
#                   surprise requests; filed ones come back as planned work, fewer as policies automate them
# ---------------------------------------------------------------------------------------------
S2_LOOPS = [
    {"id": "B-prevention", "polarity": "balancing", "stocks": ["p_asks", "p_logged", "p_cases", "p_statements", "p_in_review", "p_policies"],
     "says": "Cases become problem statements and proposals; adopted policies make these requests rarer."},
    {"id": "R-evidence", "polarity": "reinforcing", "stocks": ["p_cases", "p_in_review", "p_policies"],
     "says": "The more cases logged, the stronger the proposal and the sooner it is adopted."},
    {"id": "R-crisis", "polarity": "reinforcing", "stocks": ["p_incidents", "p_postmortem", "p_statements", "p_in_review"],
     "says": "An incident caused by a command speeds adoption and becomes a postmortem and a problem statement."},
    {"id": "R-runbooks", "polarity": "reinforcing", "stocks": ["p_lessons", "p_runbooks", "p_explained", "p_incidents"],
     "says": "Cases and incidents teach the runbooks; better runbooks explain faster and cause fewer incidents."},
    {"id": "B-decay", "polarity": "balancing", "stocks": ["p_runbooks", "p_policies"],
     "says": "Runbooks go stale as systems change; policies erode as people work around them."},
    {"id": "B-compliance", "polarity": "balancing", "stocks": ["p_authority_gap", "p_compliance"],
     "says": "Asking for missing authority teaches requesters to bring it; fewer requests arrive incomplete."},
    {"id": "R-repeats", "polarity": "reinforcing", "stocks": ["p_followups", "p_repeat_due", "p_asks"],
     "says": "Repeats needed in other environments come back as requests: as surprises if never filed."},
]

p_stocks = [
    stock("p_compliance", "Requesters following the process", "points", 30, "company", **at(0, "company"),
          note="Share of requesters who bring the change ticket and approvals with the ask, out of 100."),
    stock("p_asks", "Command asks", "requests", 1, "interface", **at(0, "interface")),
    stock("p_explained", "Explained", "requests", 0, "ours", **at(200, "ours"),
          note="What the command does, runbooks, blast radius, risks, how to undo it."),
    stock("p_authority_gap", "Authority missing", "requests", 0, "interface", **at(300, "interface"),
          note="Asked back for the change ticket or approvals."),
    stock("p_authorised", "Authorised", "requests", 0, "ours", **at(400, "ours")),
    stock("p_briefed", "Briefed", "requests", 0, "ours", **at(600, "ours"),
          note="Root cause and context: customer ticket, unsafe ramp, rollout follow-up, other environments."),
    stock("p_declined", "Declined or redirected", "requests", 0, "interface", final=True, **at(600, "interface")),
    stock("p_to_run", "To run", "requests", 0, "ours", **at(800, "ours")),
    stock("p_ran", "Ran", "requests", 0, "interface", **at(900, "interface")),
    stock("p_logged", "Logged", "requests", 0, "ours", **at(1000, "ours")),
    stock("p_cases", "Cases on file", "cases", 0, "ours", **at(1200, "ours"),
          note="Logged requests that are evidence for prevention, until they are too old to matter."),
    stock("p_archived", "Archived", "cases", 0, "ours", final=True, **at(1200, "ours_low")),
    stock("p_statements", "Problem statements", "documents", 0, "ours", **at(1400, "ours")),
    stock("p_in_review", "Proposals in review", "documents", 0, "company", **at(1400, "company")),
    stock("p_rejected", "Rejected", "documents", 0, "company", final=True, **at(1650, "company_low")),
    stock("p_policies", "Preventions in force", "policies", 0, "company", **at(1650, "company"),
          note="Policies and automation that remove the need for these requests."),
    stock("p_incidents", "Incidents caused by a command", "incidents", 0, "company", **at(1000, "company")),
    stock("p_postmortem", "Postmortems in progress", "documents", 0, "ours", **at(1400, "ours_low")),
    stock("p_lessons", "Runbook lessons", "lessons", 0, "ours", **at(400, "ours_top")),
    stock("p_runbooks", "Runbook coverage", "entries", 20, "ours", **at(650, "ours_top"),
          note="How much of what gets asked is covered by an accurate runbook."),
    stock("p_followups", "Repeats not yet filed", "follow-ups", 0, "interface", **at(1150, "interface"),
          note="Repeats needed in government and monthly-deployed environments."),
    stock("p_followup_tickets", "Repeats filed", "tickets", 0, "interface", **at(1400, "interface")),
    stock("p_repeat_due", "Repeats coming due", "follow-ups", 0, "company", **at(250, "company_low"),
          note="Repeats that will come back as requests when the next monthly deploy lands."),
]
PRV = table("p_policies", (0, 1), (2, 0.75), (5, 0.5), (10, 0.35))
p_flows = [
    flow("p_ask", "ask", None, "p_asks", linear(0.06, company_growth=0.12), "environment", side="company",
         crosses="slack/jira in", effects=[PRV],
         note="About 2.4 a week to start, rising to about 7 as the company's systems grow; fewer as preventions take hold."),
    flow("p_repeat", "repeat comes due", "p_repeat_due", "p_asks", prop("p_repeat_due", 1 / 160), "environment",
         side="company", note="Monthly deploys bring the repeats back."),
    flow("p_surprise", "surprise repeat", "p_followups", "p_asks", prop("p_followups", 1 / 160), "environment",
         side="company", note="A repeat nobody filed comes back as a surprise."),
    flow("p_explain", "explain + runbooks", "p_asks", "p_explained", AV, "analyst", 0.5, 2,
         crosses="read: runbooks, code, docs",
         effects=[table("p_runbooks", (0, 0.5), (20, 1), (60, 1.8), (120, 2.5))],
         note="Faster where runbooks already cover the command."),
    flow("p_auth_ok", "authority complete", "p_explained", "p_authorised", prop("p_explained", 2), "orchestra", 0,
         crosses="read: jira approvals, change tickets, org chart",
         effects=[table("p_compliance", (0, 0.2), (30, 0.6), (70, 1.2), (100, 1.5))]),
    flow("p_auth_gap", "authority missing", "p_explained", "p_authority_gap", prop("p_explained", 2), "orchestra", 0,
         side="interface", effects=[table("p_compliance", (0, 1.6), (30, 1), (70, 0.4), (100, 0.1))],
         crosses="slack write (the question back, via outbox)"),
    flow("p_completed", "requester completes it", "p_authority_gap", "p_authorised", prop("p_authority_gap", 1 / 8),
         "environment", side="company"),
    flow("p_gave_up", "requester gives up", "p_authority_gap", "p_declined", prop("p_authority_gap", 1 / 40),
         "environment", side="company"),
    flow("p_learn_process", "requesters learn the process", None, "p_compliance", prop("p_authority_gap", 0.6),
         "environment", side="company", effects=[table("p_compliance", (0, 1), (80, 0.4), (100, 0))]),
    flow("p_forget_process", "turnover, new requesters", "p_compliance", None, prop("p_compliance", 0.003),
         "environment", side="company"),
    flow("p_context", "root cause + context", "p_authorised", "p_briefed", AV, "analyst", 0.75, 3,
         outputs=["p_followups"], split={"p_briefed": 0.8, "p_followups": 0.2},
         crosses="read: customer jira, flag history, deploys, release calendars"),
    flow("p_decide", "decide", "p_briefed", "p_to_run", AV, "me", 0.25,
         outputs=["p_declined"], split={"p_to_run": 0.85, "p_declined": 0.15}),
    flow("p_run", "run (me only)", "p_to_run", "p_ran", AV, "me", 0.25, side="interface",
         crosses="bastion host (human only)"),
    flow("p_clean", "goes as expected", "p_ran", "p_logged", prop("p_ran", 3.75), "environment", side="interface"),
    flow("p_incident", "causes an incident", "p_ran", "p_incidents", prop("p_ran", 0.25), "environment",
         side="company", effects=[table("p_runbooks", (0, 2), (20, 1), (60, 0.5), (120, 0.3))],
         note="About 6% of commands cause an incident at today's runbook coverage; more when thinner, fewer as they improve."),
    flow("p_respond", "respond to the incident", "p_incidents", "p_postmortem", AV, "me", 2.0, side="interface",
         crosses="pagerduty, slack, incident process"),
    flow("p_pm", "postmortem → problem statement", "p_postmortem", "p_statements", AV, "analyst", 1.0, 3,
         crosses="read: slack, pagerduty, deploys, flags"),
    flow("p_log", "log for the company", "p_logged", "p_cases", AV, "drafter", 0.1, 0.3, side="interface",
         crosses="jira/slack write (via outbox)"),
    flow("p_file", "file the repeats", "p_followups", "p_followup_tickets", AV, "drafter", 0.1, 0.3,
         side="interface", crosses="jira write (via outbox)"),
    flow("p_plan_repeat", "repeat scheduled", "p_followup_tickets", "p_repeat_due", prop("p_followup_tickets", 0.1),
         "environment", side="company", effects=[table("p_policies", (0, 1), (5, 0.6), (10, 0.3))],
         note="Filed repeats come back as planned work; preventions automate some of them away."),
    flow("p_automated", "repeat automated away", "p_followup_tickets", "p_archived", prop("p_followup_tickets", 0.02),
         "environment", side="company", effects=[table("p_policies", (0, 0.2), (5, 1.5), (10, 3))]),
    flow("p_lesson", "runbook lessons", None, "p_lessons", linear(0, p_cases=0.03, p_incidents=3, p_postmortem=2),
         "orchestra", 0),
    flow("p_runbook", "update runbooks", "p_lessons", "p_runbooks", AV, "drafter", 0.3, 1,
         crosses="wiki/runbook write (via outbox)"),
    flow("p_runbook_stale", "runbooks go stale", "p_runbooks", None, prop("p_runbooks", 0.002), "environment"),
    flow("p_pattern", "find a pattern", "p_cases", "p_statements", prop("p_cases", 0.01), "analyst", 0.5, 2,
         note="A problem statement needs several cases; the more on file, the more often a pattern appears."),
    flow("p_age", "cases age out", "p_cases", "p_archived", prop("p_cases", 0.01), "environment"),
    flow("p_propose", "propose", "p_statements", "p_in_review", AV, "me", 1.5, 2, side="interface",
         crosses="docs write; slack post for review"),
    flow("p_adopt", "adopt", "p_in_review", "p_policies", prop("p_in_review", 1 / 80), "environment",
         side="company", effects=[table("p_cases", (0, 0.6), (5, 1), (15, 1.6), (30, 2)),
                                  table("p_incidents", (0, 1), (1, 1.5), (3, 2.5))],
         note="Faster with more evidence on file, and much faster right after an incident."),
    flow("p_reject", "reject", "p_in_review", "p_rejected", prop("p_in_review", 1 / 160), "environment",
         side="company"),
    flow("p_erode", "policies erode", "p_policies", None, prop("p_policies", 0.001), "environment", side="company",
         note="People find ways around policies; automation drifts."),
]
write("story-2-prod-command.json", model(
    "story-2-prod-command", "Story 2: production command requests, made rarer and safer",
    "People ask me to run commands on production bastions. Agents explain the command from runbooks, check the "
    "authority chain (asking back when it is missing, which teaches requesters the process), and gather context, "
    "including repeats needed in other environments. I decide and run it; nobody else can. Every case is logged; "
    "patterns and incidents become problem statements and proposals, which the company adopts faster with more "
    "evidence and right after an incident. Runbooks learn from every case and incident and go stale on their own. "
    "Time unit: a working hour; horizon 26 weeks.",
    p_stocks, p_flows, horizon=1040, loops=S2_LOOPS,
    inputs={"company_growth": {"terms": [{"fn": "ramp", "slope": 1 / 1040, "start": 0}]}}))
write("story-2-prod-command.variants.json", {
    "manual": {
        "description": "Today's shortcut: I explain and check it myself, shallowly. No runbook updates, no logging "
                       "for others, no filing of repeats, no patterns or proposals; postmortems only when an "
                       "incident forces one.",
        "flows": {
            "p_explain": ME(1.0), "p_context": ME(0.5), "p_log": ME(0.05),
            "p_runbook": OFF, "p_file": OFF, "p_pattern": OFF, "p_propose": OFF, "p_pm": ME(3.0),
        },
    },
    "manual-thorough": {
        "description": "Me doing all of it properly myself: runbooks, logs, repeats, patterns, proposals.",
        "flows": {
            "p_explain": ME(1.0), "p_context": ME(1.5), "p_log": ME(0.25), "p_file": ME(0.25),
            "p_runbook": ME(0.5), "p_pattern": ME(1.0), "p_propose": ME(4.0), "p_pm": ME(3.0),
        },
    },
    "no-runbooks": {
        "description": "Agents, but nobody updates the runbooks.",
        "flows": {"p_runbook": OFF},
    },
    "no-evidence": {
        "description": "Agents, but cases are not logged where the company sees them: proposals carry no evidence.",
        "flows": {"p_adopt": {"effects": [{"stock": "p_incidents", "shape": "table", "points": [[0, 1], [1, 1.5], [3, 2.5]]},
                                          {"stock": "p_cases", "shape": "table", "points": [[0, 0.6], [100, 0.6]]}]}},
    },
})


# ---------------------------------------------------------------------------------------------
# Story 3: a manager asks for an update I don't have prepared, and the loops around it.
#
#   B freshness     projects drift; the analyst refreshes; refresh is faster when sources are kept up
#   B hygiene       nudging owners keeps their tickets current
#   R nagging       too many nudges wear out the team's patience; patience gone, nudges stop working
#                   (fixes that fail)
#   B confidence    accurate, quick answers build my manager's confidence; they ask less and read the page
#   R spiral        wrong answers and surprises cut confidence; they check in more; I have less time
#                   to keep up; more answers come from stale knowledge (micromanagement spiral)
#   B early warning a current page shows blocked projects before my manager finds them
# ---------------------------------------------------------------------------------------------
S3_LOOPS = [
    {"id": "B-freshness", "polarity": "balancing", "stocks": ["s_current", "s_stale", "s_hygiene"],
     "says": "Projects drift and the page goes stale; refreshing brings it back, faster when the sources are kept up."},
    {"id": "B-hygiene", "polarity": "balancing", "stocks": ["s_stale", "s_nudges", "s_hygiene"],
     "says": "Stale sources prompt nudges to owners, which keep their tickets current."},
    {"id": "R-nagging", "polarity": "reinforcing", "stocks": ["s_nudges", "s_patience", "s_hygiene"],
     "says": "Too many nudges wear out patience; without patience nudges stop working and sources rot anyway."},
    {"id": "B-confidence", "polarity": "balancing", "stocks": ["s_good_recent", "s_confidence", "s_asks"],
     "says": "Accurate, quick answers build confidence; a confident manager asks less and reads the page."},
    {"id": "R-spiral", "polarity": "reinforcing", "stocks": ["s_bad_recent", "s_surprise_recent", "s_confidence", "s_asks", "s_stale"],
     "says": "Wrong answers and surprises cut confidence; more check-ins take my time; more answers come from stale knowledge."},
    {"id": "B-early-warning", "polarity": "balancing", "stocks": ["s_blocked_hidden", "s_blocked_known", "s_surprises", "s_surprise_recent"],
     "says": "A current page shows blocked projects before my manager finds them."},
]
s_stocks = [
    stock("s_current", "Status current", "items", 30, "ours", **at(200, "ours")),
    stock("s_stale", "Status stale", "items", 30, "ours", **at(200, "ours_low"),
          note="Something changed in the ticket, doc or thread since the page last read it."),
    stock("s_hygiene", "Source hygiene", "points", 50, "company", **at(450, "company"),
          note="How well owners keep their tickets and docs current, out of 100."),
    stock("s_nudges", "Recent nudges to owners", "nudges", 0, "interface", **at(450, "interface")),
    stock("s_patience", "Team's patience with nudges", "points", 80, "company", **at(450, "company_low")),
    stock("s_asks", "Manager questions", "questions", 1, "interface", **at(800, "interface")),
    stock("s_drafted", "Answer given, accuracy unknown", "questions", 0, "interface", **at(1050, "interface")),
    stock("s_good_recent", "Good answers, recently", "questions", 0, "company", **at(1300, "company")),
    stock("s_wrong", "Answers found wrong", "questions", 0, "company", **at(1300, "company_low")),
    stock("s_answered", "Answered", "questions", 0, "interface", final=True, **at(1550, "interface")),
    stock("s_confidence", "Manager's confidence in me", "points", 50, "company", **at(800, "company")),
    stock("s_blocked_hidden", "Blocked, not yet noticed", "projects", 0, "ours", **at(550, "ours_top")),
    stock("s_blocked_known", "Blocked, I know", "projects", 0, "ours", **at(850, "ours_top")),
    stock("s_surprises", "Blocked, manager found it first", "projects", 0, "company", **at(1050, "company_low")),
    stock("s_escalated", "Escalated and handled", "projects", 0, "ours", final=True, **at(1150, "ours_top")),
    stock("s_bad_recent", "Wrong answers, recently", "questions", 0, "company", **at(1550, "company_low"),
          note="Remembered for about two weeks."),
    stock("s_surprise_recent", "Surprises, recently", "projects", 0, "company", **at(1300, "ours_low"),
          note="Remembered for about a month."),
]
s_flows = [
    flow("s_new", "new items to track", None, "s_stale", const(0.05), "environment", side="company",
         note="About two new projects, tickets or threads a week."),
    flow("s_retire", "items finish", "s_current", None, prop("s_current", 0.002), "environment", side="company"),
    flow("s_drift", "projects move on", "s_current", "s_stale", prop("s_current", 0.05), "environment",
         side="company"),
    flow("s_refresh", "refresh", "s_stale", "s_current", AV, "analyst", 0.05, 0.1, crosses="read: jira, docs, slack",
         effects=[table("s_hygiene", (0, 0.3), (50, 1), (100, 1.5))],
         note="Slow where sources are out of date: the agent has to reconstruct what happened."),
    flow("s_nudge", "nudge owners", None, "s_nudges", prop("s_current", 0.005), "orchestra", 0, side="interface",
         crosses="slack write (via outbox; earned autonomy)",
         effects=[table("s_hygiene", (0, 2), (50, 1), (100, 0.2))],
         note="When a refresh finds a source out of date, its owner gets a nudge; more often when hygiene is poor."),
    flow("s_nudge_fade", "fade", "s_nudges", None, prop("s_nudges", 0.25), "environment", side="company"),
    flow("s_hygiene_up", "owners update", None, "s_hygiene", prop("s_nudges", 0.6), "environment", side="company",
         effects=[table("s_patience", (0, 0), (30, 0.3), (60, 1), (100, 1.2)), table("s_hygiene", (0, 1), (80, 0.5), (100, 0))]),
    flow("s_hygiene_down", "sources rot", "s_hygiene", None, prop("s_hygiene", 0.01), "environment", side="company"),
    flow("s_patience_loss", "patience wears", "s_patience", None, prop("s_nudges", 0.1), "environment",
         side="company", effects=[table("s_nudges", (0, 1), (1, 1), (3, 3), (6, 5))],
         note="A few nudges are fine; many wear patience out much faster."),
    flow("s_patience_gain", "patience recovers", None, "s_patience", {"form": "gap", "stock": "s_patience", "goal": 100,
                                                                       "time": 200}, "environment", side="company"),
    flow("s_ask", "manager asks", None, "s_asks", const(0.1), "environment", side="company", crosses="slack/meeting in",
         effects=[table("s_confidence", (0, 2.5), (50, 1), (100, 0.4)), table("s_surprise_recent", (0, 1), (1, 2), (3, 3))],
         note="Four a week at middling confidence; fewer when confident, many more after surprises."),
    flow("s_answer", "answer", "s_asks", "s_drafted", AV, "me", 1.5, side="interface", crosses="slack write",
         effects=[table("s_stale", (0, 10), (5, 6), (20, 2), (45, 1), (60, 0.8))],
         note="1.5 hours of research when everything is stale; minutes when the page is current."),
    flow("s_right", "turns out right", "s_drafted", "s_good_recent", prop("s_drafted", 3.8), "environment",
         side="company", effects=[table("s_stale", (0, 1.05), (20, 1), (60, 0.85))]),
    flow("s_wrong_flow", "turns out wrong", "s_drafted", "s_wrong", prop("s_drafted", 0.2), "environment",
         side="company", effects=[table("s_stale", (0, 0.2), (20, 1), (60, 3))]),
    flow("s_correct", "correct it", "s_wrong", "s_bad_recent", AV, "me", 0.5, side="interface", crosses="slack write"),
    flow("s_bad_settle", "forgotten", "s_bad_recent", "s_answered", prop("s_bad_recent", 1 / 80), "environment",
         side="company"),
    flow("s_surprise_settle", "forgotten", "s_surprise_recent", None, prop("s_surprise_recent", 1 / 160),
         "environment", side="company"),
    flow("s_settle", "leaves recent memory", "s_good_recent", "s_answered", prop("s_good_recent", 1 / 40),
         "environment", side="company"),
    flow("s_conf_gain", "confidence earned", None, "s_confidence", prop("s_good_recent", 0.25), "environment",
         side="company", effects=[table("s_confidence", (0, 1), (80, 0.5), (100, 0))]),
    flow("s_conf_loss", "confidence lost", "s_confidence", None, prop("s_confidence", 0.003), "environment",
         side="company", effects=[table("s_bad_recent", (0, 1), (1, 3), (3, 6)), table("s_surprise_recent", (0, 1), (1, 4), (3, 8))]),
    flow("s_block", "a project gets blocked", None, "s_blocked_hidden", const(0.025), "environment", side="company"),
    flow("s_notice", "page shows the block", "s_blocked_hidden", "s_blocked_known", prop("s_blocked_hidden", 0.3),
         "orchestra", 0, effects=[table("s_stale", (0, 1.5), (20, 1), (60, 0.1))]),
    flow("s_found_first", "manager finds it first", "s_blocked_hidden", "s_surprises", prop("s_blocked_hidden", 1 / 40),
         "environment", side="company"),
    flow("s_escalate", "escalate early", "s_blocked_known", "s_escalated", AV, "me", 0.5, side="interface",
         crosses="slack/jira write"),
    flow("s_firefight", "firefight the surprise", "s_surprises", "s_escalated", AV, "me", 1.5, side="interface",
         crosses="slack/meetings"),
    flow("s_remember", "remembered", None, "s_surprise_recent", prop("s_surprises", 4), "orchestra", 0,
         side="company", note="Each surprise is remembered while it is handled, and for weeks after."),
]
write("story-3-status-request.json", model(
    "story-3-status-request", "Story 3: a manager asks for an update",
    "One of my managers asks me for an update, assuming I already have the context. Today I don't: I re-read "
    "tickets, docs and Slack threads to reconstruct it before I can give a small update. With a status page the "
    "analyst keeps current, the update is already prepared. Around that core are the loops that decide whether "
    "it stays that way: the page is refreshed faster when owners keep their sources up; nudges keep them up "
    "until they wear out the team's patience. Accurate, quick answers build my manager's confidence and they ask "
    "less; wrong answers and surprises (blocked projects they found before me) send them checking in more. "
    "Time unit: a working hour; horizon 26 weeks.",
    s_stocks, s_flows, horizon=1040, loops=S3_LOOPS))
write("story-3-status-request.variants.json", {
    "manual": {"description": "Today: no status page and no nudges; every answer starts from memory or scratch.",
               "flows": {"s_refresh": OFF, "s_nudge": OFF, "s_notice": OFF}},
    "no-nudges": {"description": "A status page, but nobody nudges owners.", "flows": {"s_nudge": OFF}},
    "nagging": {"description": "A status page, nudging four times as hard.",
                "flows": {"s_nudge": {"rate": prop("s_current", 0.02)}}},
})


# ---------------------------------------------------------------------------------------------
# Story 4 (invented): reviewing teammates' PRs, with the loops around being a good reviewer.
#
#   R reciprocity   reviews I give build goodwill; goodwill speeds reviews of my own PRs (desk coupling)
#   B fatigue       a long queue of PRs to review: I skim, and miss more defects
#   B coaching      substantive comments raise the team's skill; skilled authors send fewer flawed PRs
#   R reputation    defects I catch make me the reviewer people ask for; more requests, until load bites
#   R knowledge     every brief teaches the agent's map of the codebase; a better map, better briefs,
#                   faster and sharper reviews; the map decays as the code changes
#   R goodhart      a comment quota adds nitpicks; nitpicks cost goodwill (fixes that fail)
#   B escapes       defects I miss land and come back as production bugs, which cut my reputation
# ---------------------------------------------------------------------------------------------
S4_LOOPS = [
    {"id": "R-reciprocity", "polarity": "reinforcing", "stocks": ["r_recent", "r_goodwill"],
     "says": "Reviews I give build goodwill; in the desk model goodwill speeds reviews of my own PRs."},
    {"id": "B-fatigue", "polarity": "balancing", "stocks": ["r_briefed_clean", "r_judged_flawed", "r_escaped"],
     "says": "A long queue means I skim and miss more defects."},
    {"id": "B-coaching", "polarity": "balancing", "stocks": ["r_substantive", "r_skill", "r_req_flawed"],
     "says": "Substantive comments raise the team's skill; skilled authors send fewer flawed PRs, so there is less to catch."},
    {"id": "R-reputation", "polarity": "reinforcing", "stocks": ["r_substantive", "r_reputation", "r_req_clean", "r_req_flawed"],
     "says": "Catching real defects makes me the reviewer people ask for; more requests, until the queue blunts me."},
    {"id": "R-knowledge", "polarity": "reinforcing", "stocks": ["r_recent", "r_knowledge", "r_judged_flawed"],
     "says": "Briefs teach the agent's map of the codebase; better maps make faster, sharper reviews; it decays as code changes."},
    {"id": "R-goodhart", "polarity": "reinforcing", "stocks": ["r_nits", "r_goodwill"],
     "says": "A comment quota adds nitpicks; nitpicks cost goodwill."},
    {"id": "B-escapes", "polarity": "balancing", "stocks": ["r_escaped", "r_bugs", "r_reputation"],
     "says": "Defects I miss come back as production bugs and cut my reputation as a reviewer."},
]
r_stocks = [
    stock("r_reputation", "My reputation as a reviewer", "points", 50, "company", **at(0, "company")),
    stock("r_skill", "Team's skill", "points", 50, "company", **at(0, "company_low"),
          note="How often teammates' PRs arrive without real defects."),
    stock("r_req_clean", "Requests (clean PR)", "PRs", 2, "interface", **at(250, "interface")),
    stock("r_req_flawed", "Requests (PR with a defect)", "PRs", 1, "interface", **at(250, "company_low")),
    stock("r_briefed_clean", "Briefed (clean)", "PRs", 0, "ours", **at(500, "ours")),
    stock("r_briefed_flawed", "Briefed (defect)", "PRs", 0, "ours", **at(500, "ours_low")),
    stock("r_judged_flawed", "Reviewed (defect)", "PRs", 0, "interface", **at(750, "interface"),
          note="I have reviewed it; whether I caught the defect depends on the brief and my queue."),
    stock("r_substantive", "Defect caught: comments posted", "PRs", 0, "company", **at(1000, "company")),
    stock("r_escaped", "Approved with the defect", "PRs", 0, "company", **at(1000, "company_low")),
    stock("r_bugs", "Bugs from PRs I approved", "bugs", 0, "company", **at(1250, "company_low")),
    stock("r_recent", "Reviews given recently", "reviews", 0, "company", **at(1250, "company")),
    stock("r_given", "Reviews given", "reviews", 0, "ours", final=True, **at(1500, "ours")),
    stock("r_goodwill", "Teammates' goodwill toward me", "points", 30, "company", **at(1500, "company")),
    stock("r_nits", "Nitpicks, recently", "comments", 0, "interface", **at(1500, "interface")),
    stock("r_knowledge", "Agent's map of the codebase", "entries", 30, "ours", **at(750, "ours_top"),
          note="What the brief writer knows about the code: owners, risky areas, past bugs, conventions."),
]
DEMAND = linear(0.15, r_reputation=0.001)
FATIGUE = table("r_briefed_clean", (0, 1), (5, 0.85), (15, 0.6))
r_flows = [
    flow("r_ask_clean", "review requested", None, "r_req_clean", DEMAND, "environment", side="company",
         crosses="github in", effects=[table("r_skill", (0, 0.5), (50, 0.7), (100, 0.9))]),
    flow("r_ask_flawed", "review requested", None, "r_req_flawed", DEMAND, "environment", side="company",
         crosses="github in", effects=[table("r_skill", (0, 0.5), (50, 0.3), (100, 0.1))],
         note="Six to eight a week; the share with a real defect falls as the team's skill rises."),
    flow("r_brief_clean", "pre-read brief", "r_req_clean", "r_briefed_clean", AV, "analyst", 0.2, 0.5,
         crosses="read: PR, code, git log", effects=[table("r_knowledge", (0, 0.6), (50, 1), (100, 1.4))]),
    flow("r_brief_flawed", "pre-read brief", "r_req_flawed", "r_briefed_flawed", AV, "analyst", 0.2, 0.5,
         crosses="read: PR, code, git log", effects=[table("r_knowledge", (0, 0.6), (50, 1), (100, 1.4))]),
    flow("r_review_clean", "my review", "r_briefed_clean", "r_recent", AV, "me", 0.4, side="interface",
         crosses="github write (approve, comments)", effects=[table("r_knowledge", (0, 0.6), (50, 1), (100, 1.3))]),
    flow("r_review_flawed", "my review", "r_briefed_flawed", "r_judged_flawed", AV, "me", 0.5, side="interface",
         effects=[table("r_knowledge", (0, 0.6), (50, 1), (100, 1.3))]),
    flow("r_catch", "I catch the defect", "r_judged_flawed", "r_substantive", prop("r_judged_flawed", 3.4),
         "environment", side="interface", crosses="github write (comments)",
         effects=[table("r_knowledge", (0, 0.7), (50, 1), (100, 1.15)), FATIGUE]),
    flow("r_miss", "I miss it", "r_judged_flawed", "r_escaped", prop("r_judged_flawed", 0.6), "environment",
         side="company", effects=[table("r_knowledge", (0, 1.6), (50, 1), (100, 0.6)),
                                  table("r_briefed_clean", (0, 1), (5, 1.5), (15, 3))]),
    flow("r_fixed", "author fixes it", "r_substantive", "r_recent", prop("r_substantive", 1 / 8), "environment",
         side="company"),
    flow("r_lands", "lands, defect surfaces", "r_escaped", "r_bugs", prop("r_escaped", 1 / 120), "environment",
         side="company"),
    flow("r_bug_done", "bug fixed", "r_bugs", None, prop("r_bugs", 1 / 40), "environment", side="company"),
    flow("r_settle", "leaves the recent window", "r_recent", "r_given", prop("r_recent", 1 / 80), "environment",
         side="company"),
    flow("r_nit", "nitpicks", None, "r_nits", prop("r_recent", 0.005), "environment", side="interface",
         crosses="github write (comments)", note="Style and naming comments; more under a comment quota."),
    flow("r_nit_fade", "forgotten", "r_nits", None, prop("r_nits", 1 / 40), "environment", side="company"),
    flow("r_gw_gain", "goodwill earned", None, "r_goodwill", prop("r_recent", 0.05), "environment", side="company",
         effects=[table("r_goodwill", (0, 1), (80, 0.5), (100, 0)),
                  table("r_req_clean", (0, 1.2), (5, 1), (15, 0.5))],
         note="Reviews given build goodwill, more when they come quickly."),
    flow("r_gw_loss", "goodwill fades", "r_goodwill", None, prop("r_goodwill", 0.01), "environment", side="company",
         effects=[table("r_nits", (0, 1), (3, 1.5), (10, 3))]),
    flow("r_rep_gain", "reputation earned", None, "r_reputation", prop("r_substantive", 0.4), "environment",
         side="company", effects=[table("r_reputation", (0, 1), (80, 0.5), (100, 0))]),
    flow("r_rep_loss", "reputation lost", "r_reputation", None, prop("r_reputation", 0.002), "environment",
         side="company", effects=[table("r_bugs", (0, 1), (1, 3), (3, 6))]),
    flow("r_teach", "authors learn", None, "r_skill", prop("r_substantive", 0.3), "environment", side="company",
         effects=[table("r_skill", (0, 1), (80, 0.5), (100, 0))]),
    flow("r_turnover", "new joiners, forgetting", "r_skill", None, prop("r_skill", 0.0015), "environment",
         side="company"),
    flow("r_learn", "agent learns the code", None, "r_knowledge", prop("r_recent", 0.02), "orchestra", 0),
    flow("r_forget", "code changes under it", "r_knowledge", None, prop("r_knowledge", 0.004), "environment"),
]
write("story-4-reviews-given.json", model(
    "story-4-reviews-given", "Story 4: reviewing teammates' PRs",
    "Teammates ask me for reviews; some PRs carry a real defect, fewer as the team's skill rises. An agent writes a "
    "pre-read brief from its map of the codebase, which it improves with every review. I review: whether I catch a "
    "defect depends on the brief and how long my queue is. Caught defects teach authors and build my reputation, "
    "which brings more requests; missed ones land and come back as bugs. Reviews given build goodwill (which, in "
    "the desk model, speeds reviews of my own PRs); nitpicks spend it. Time unit: a working hour; horizon 26 weeks.",
    r_stocks, r_flows, horizon=1040, loops=S4_LOOPS))
write("story-4-reviews-given.variants.json", {
    "manual": {"description": "Today: no brief; I read each change cold, and nothing learns the codebase for me.",
               "flows": {"r_brief_clean": ME(0.01), "r_brief_flawed": ME(0.01), "r_review_clean": ME(0.75),
                         "r_review_flawed": ME(0.9), "r_learn": OFF}},
    "comment-quota": {"description": "Briefs, plus a quota of comments per review: five times the nitpicks.",
                      "flows": {"r_nit": {"rate": prop("r_recent", 0.03)}}},
    "no-agent-learning": {"description": "Briefs, but the agent never updates its map of the codebase.",
                          "flows": {"r_learn": OFF}},
})


# Declared couplings between stories, applied when the desk model is assembled.
write("desk.couplings.json", {
    "description": "Effects one story's stocks have on another story's flows. Every coupling is declared here.",
    "effects": [
        {"flow": "t_rev_ok", "effect": {"stock": "r_goodwill", "shape": "table",
                                         "points": [[0, 0.7], [30, 1], [60, 1.3], [100, 1.5]]},
         "note": "Reciprocity: teammates who feel well treated by my reviews review my PRs sooner."},
        {"flow": "t_rev_catch", "effect": {"stock": "r_skill", "shape": "table",
                                            "points": [[0, 0.8], [50, 1], [100, 1.2]]},
         "note": "A team I've helped grow catches more flaws in my agents' PRs."},
    ],
})
print("wrote", sorted(p.name for p in OUT.iterdir()))


# ---------------------------------------------------------------------------------------------
# Charts and measures. What each chart plots is data, not render code: every measure says how it
# is computed from the simulation (a stock, a sum of stocks, a flow's rate, a share of flows, a
# machine's time, the agents' spend), so the page can print the formula beside the chart.
# ---------------------------------------------------------------------------------------------
COMMON = {
    "my_hours": {"name": "My hours per week on this story", "unit": "hours / week", "machine_hours_per_week": "me"},
    "waiting_for_me": {"name": "Work waiting for me", "unit": "items", "waiting_for": "me"},
    "spend": {"name": "Agent spend per week", "unit": "dollars / week", "agent_spend_per_week": True},
    "spend_total": {"name": "Agent spend, cumulative", "unit": "dollars", "agent_spend_total": True},
    "budget": {"name": "Agent budget balance", "unit": "dollars", "stocks": ["budget"]},
}


def ser(variant, measure, label, color):
    return {"variant": variant, "measure": measure, "label": label, "color": color}


def chart(title, measure_unit, series, why, every=40):
    return {"title": title, "unit": measure_unit, "every": every, "x": "week", "series": series, "why": why}


write("story-1-simple-task.charts.json", {
    "measures": {**COMMON,
        "asks_week": {"name": "Asks per week", "unit": "requests / week", "flows": ["t_ask"], "per_week": True},
        "playbook": {"name": "Agent playbook", "unit": "entries", "stocks": ["t_playbook"]},
        "going_wrong": {"name": "Attempts that fail or hide a flaw", "unit": "% of attempts",
                        "share": {"of": ["t_flaw", "t_fail"], "in": ["t_ok", "t_flaw", "t_fail"]}},
        "confidence": {"name": "Requesters' confidence", "unit": "points", "stocks": ["t_reputation"]},
        "backlog": {"name": "Backlog", "unit": "requests", "stocks": ["t_asks", "t_scoped", "t_ticket_draft", "t_open"]},
        "trust": {"name": "My trust in the agents", "unit": "points", "stocks": ["t_trust"]},
        "delivered": {"name": "Delivered (cumulative)", "unit": "tasks",
                      "stocks": ["t_landed_recent", "t_delivered", "t_latent", "t_bugs"]},
    },
    "charts": [
        chart("Asks per week (the demand driving everything else)", "requests / week", [
            ser("designed", "asks_week", "designed", "designed"), ser("manual", "asks_week", "manual (today)", "manual"),
            ser("surge", "asks_week", "surge of asks", "red")],
            "Not a fixed input: asks are 0.06 an hour plus 0.003 × requesters' confidence, so they rise as I deliver."),
        chart("Agent playbook: learning against decay and the capability trap", "entries", [
            ser("designed", "playbook", "designed", "designed"), ser("no-learning", "playbook", "no learning", "manual"),
            ser("surge", "playbook", "surge of asks", "red"),
            ser("surge-protected", "playbook", "surge, lesson capture protected", "purple")],
            "Starts at 20 entries in every variant."),
        chart("Attempts that fail or hide a flaw", "% of attempts", [
            ser("designed", "going_wrong", "designed", "designed"), ser("no-learning", "going_wrong", "no learning", "manual"),
            ser("surge", "going_wrong", "surge of asks", "red")],
            "The outcome split moves with the playbook and the debt."),
        chart("Requesters' confidence: success breeds demand", "points", [
            ser("designed", "confidence", "designed", "designed"), ser("no-learning", "confidence", "no learning", "manual"),
            ser("manual", "confidence", "manual (today)", "yellow")], "Starts at 20 in every variant."),
        chart("Backlog: asks and open tickets", "requests", [
            ser("manual", "backlog", "manual (today)", "yellow"), ser("designed", "backlog", "designed", "designed"),
            ser("no-learning", "backlog", "no learning", "manual"), ser("surge", "backlog", "surge of asks", "red")],
            "Starts at 6 (4 asks, 2 open tickets) in every variant."),
        chart("Agent spend per week", "dollars / week", [
            ser("designed", "spend", "designed", "designed"), ser("no-learning", "spend", "no learning", "manual"),
            ser("surge", "spend", "surge of asks", "red")],
            "What the agents' LLM work costs, summed from every agent flow's rate × its cost per item. The budget refills at $120 a week; spend above that draws down the balance."),
        chart("Agent budget balance", "dollars", [
            ser("designed", "budget", "designed", "designed"), ser("no-learning", "budget", "no learning", "manual")],
            "A stock: starts at $120, refilled at $3 per working hour, drained by agent spend. At zero, agent work stops."),
        chart("My trust in the agents", "points", [
            ser("designed", "trust", "designed", "designed"), ser("blind-trust", "trust", "starting from blind trust", "purple")],
            "Starts at 30 (designed) or 80 (blind trust)."),
        chart("My hours per week on this story", "hours / week", [
            ser("designed", "my_hours", "designed", "designed"), ser("manual", "my_hours", "manual (today)", "manual")],
            "My free time is 0.6 of each working hour: 24 hours a week at most."),
        chart("Delivered (cumulative)", "tasks", [
            ser("manual", "delivered", "manual (today)", "yellow"), ser("designed", "delivered", "designed", "designed"),
            ser("no-learning", "delivered", "no learning", "manual")], "Landed changes, sound or flawed."),
    ]})

write("story-2-prod-command.charts.json", {
    "measures": {**COMMON,
        "asks_week": {"name": "Command requests per week", "unit": "requests / week", "flows": ["p_ask", "p_repeat", "p_surprise"], "per_week": True},
        "new_asks_week": {"name": "New command requests per week", "unit": "requests / week", "flows": ["p_ask"], "per_week": True},
        "policies": {"name": "Preventions in force", "unit": "policies", "stocks": ["p_policies"]},
        "runbooks": {"name": "Runbook coverage", "unit": "entries", "stocks": ["p_runbooks"]},
        "incidents_week": {"name": "Incidents caused by commands per week", "unit": "incidents / week", "flows": ["p_incident"], "per_week": True},
        "unfiled": {"name": "Repeats nobody filed", "unit": "follow-ups", "stocks": ["p_followups"]},
    },
    "charts": [
        chart("Command requests per week: growth against prevention", "requests / week", [
            ser("designed", "asks_week", "designed", "designed"), ser("manual", "asks_week", "today's shortcut (no prevention)", "manual")],
            "New requests start at 0.06 an hour (2.4 a week) and grow by 0.12 × company growth, a ramp from 0 to 1 over the 26 weeks; adopted preventions scale them down. Repeats and surprises come on top."),
        chart("Preventions in force", "policies", [
            ser("designed", "policies", "designed", "designed"), ser("no-evidence", "policies", "no evidence logged", "purple"),
            ser("manual", "policies", "today's shortcut", "manual")], "Starts at 0."),
        chart("Runbook coverage: learning against decay", "entries", [
            ser("designed", "runbooks", "designed", "designed"), ser("no-runbooks", "runbooks", "no runbook updates", "red"),
            ser("manual", "runbooks", "today's shortcut", "manual")], "Starts at 20 entries."),
        chart("Incidents caused by commands, per week", "incidents / week", [
            ser("designed", "incidents_week", "designed", "designed"), ser("no-runbooks", "incidents_week", "no runbook updates", "red"),
            ser("manual", "incidents_week", "today's shortcut", "manual")], "About 6% of commands at 20 runbook entries; the share moves with coverage."),
        chart("Repeats in other environments nobody filed", "follow-ups", [
            ser("designed", "unfiled", "designed", "designed"), ser("manual", "unfiled", "today's shortcut", "manual")], "Starts at 0."),
        chart("My hours per week on these requests", "hours / week", [
            ser("designed", "my_hours", "designed", "designed"), ser("manual", "my_hours", "today's shortcut", "manual"),
            ser("manual-thorough", "my_hours", "doing it all properly myself", "yellow")], "My free time is at most 24 hours a week."),
        chart("Agent spend per week", "dollars / week", [ser("designed", "spend", "designed", "designed")],
            "Summed from every agent flow's rate × its cost per item."),
    ]})

write("story-3-status-request.charts.json", {
    "measures": {**COMMON,
        "confidence": {"name": "Manager's confidence in me", "unit": "points", "stocks": ["s_confidence"]},
        "questions_week": {"name": "Manager questions per week", "unit": "questions / week", "flows": ["s_ask"], "per_week": True},
        "stale": {"name": "Stale status items", "unit": "items", "stocks": ["s_stale"]},
        "hygiene": {"name": "Source hygiene", "unit": "points", "stocks": ["s_hygiene"]},
        "patience": {"name": "Team's patience with nudges", "unit": "points", "stocks": ["s_patience"]},
    },
    "charts": [
        chart("Manager questions per week: confidence or the spiral", "questions / week", [
            ser("designed", "questions_week", "designed", "designed"), ser("manual", "questions_week", "manual (today)", "manual")],
            "Not a fixed input: 0.1 an hour (4 a week) × an effect of my manager's confidence (2.5× at 0, 1× at 50, 0.4× at 100) × an effect of recent surprises (up to 3×)."),
        chart("Manager's confidence in me", "points", [
            ser("designed", "confidence", "designed", "designed"), ser("manual", "confidence", "manual (today)", "manual")], "Starts at 50 of 100."),
        chart("Stale status items", "items", [
            ser("designed", "stale", "designed", "designed"), ser("manual", "stale", "manual (today)", "manual")],
            "Starts at 30 stale of 60 tracked; about 5% of current items go stale each working hour; 2 new items a week."),
        chart("Source hygiene: no nudges, enough, too many", "points", [
            ser("designed", "hygiene", "designed", "designed"), ser("no-nudges", "hygiene", "no nudges", "manual"),
            ser("nagging", "hygiene", "nagging", "red")], "Starts at 50 of 100."),
        chart("Team's patience with nudges", "points", [
            ser("designed", "patience", "designed", "designed"), ser("nagging", "patience", "nagging", "red")], "Starts at 80 of 100."),
        chart("My hours per week on this story", "hours / week", [
            ser("designed", "my_hours", "designed", "designed"), ser("manual", "my_hours", "manual (today)", "manual")],
            "My free time is at most 24 hours a week."),
    ]})

write("story-4-reviews-given.charts.json", {
    "measures": {**COMMON,
        "requests_week": {"name": "Review requests per week", "unit": "PRs / week", "flows": ["r_ask_clean", "r_ask_flawed"], "per_week": True},
        "knowledge": {"name": "Agent's map of the codebase", "unit": "entries", "stocks": ["r_knowledge"]},
        "missed": {"name": "Defects I miss", "unit": "% of defective PRs", "share": {"of": ["r_miss"], "in": ["r_catch", "r_miss"]}},
        "goodwill": {"name": "Teammates' goodwill", "unit": "points", "stocks": ["r_goodwill"]},
        "reputation": {"name": "My reputation as a reviewer", "unit": "points", "stocks": ["r_reputation"]},
        "skill": {"name": "Team's skill", "unit": "points", "stocks": ["r_skill"]},
    },
    "charts": [
        chart("Review requests per week", "PRs / week", [
            ser("designed", "requests_week", "designed", "designed"), ser("manual", "requests_week", "manual (today)", "manual")],
            "Not a fixed input: 0.15 an hour plus 0.001 × my reputation as a reviewer (about 7 a week at 50)."),
        chart("Agent's map of the codebase: learning against code churn", "entries", [
            ser("designed", "knowledge", "designed", "designed"), ser("no-agent-learning", "knowledge", "agent not learning", "red"),
            ser("manual", "knowledge", "manual (today)", "manual")], "Starts at 30 entries."),
        chart("Defects I miss", "% of defective PRs", [
            ser("designed", "missed", "designed", "designed"), ser("manual", "missed", "manual (today)", "manual")],
            "The catch/miss split moves with the code map and my review queue."),
        chart("Teammates' goodwill toward me", "points", [
            ser("designed", "goodwill", "designed", "designed"), ser("comment-quota", "goodwill", "comment quota", "red")], "Starts at 30."),
        chart("Team's skill", "points", [
            ser("designed", "skill", "designed", "designed"), ser("manual", "skill", "manual (today)", "manual")], "Starts at 50."),
        chart("My reputation as a reviewer", "points", [
            ser("designed", "reputation", "designed", "designed"), ser("manual", "reputation", "manual (today)", "manual")], "Starts at 50."),
    ]})

write("desk.charts.json", {
    "measures": {**COMMON,
        "busy": {"name": "Share of my free time in use", "unit": "%", "machine_busy_share": "me"}},
    "charts": [
        chart("Work waiting for me, every story together", "items", [
            ser("designed", "waiting_for_me", "designed", "designed"), ser("manual", "waiting_for_me", "manual (today)", "manual")],
            "The sum of every stock that only I drain, across the four stories."),
        chart("Share of my free time in use", "%", [
            ser("designed", "busy", "designed", "designed"), ser("manual", "busy", "manual (today)", "manual")],
            "My machine's busy share each working hour (100% = all 24 free hours a week)."),
        chart("Agent spend per week, every story together", "dollars / week", [
            ser("designed", "spend", "designed", "designed")],
            "Summed from every agent flow's rate × its cost per item, across the four stories. The budget refills at $120 a week."),
        chart("Agent budget balance", "dollars", [ser("designed", "budget", "designed", "designed")],
            "A stock shared by every story: starts at $120, refilled at $3 per working hour, drained by agent spend."),
    ]})
