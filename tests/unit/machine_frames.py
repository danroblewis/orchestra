"""The Machines page's frames E1–E4 (mockups/README.md) as seeded projects: the captured demo's
machines replayed onto the project's bus as events (announcements, then what each published, and
hand-offs by subject), the captured model saved as discovered versions (``intended_seed``), and the
declared layer of each frame applied through the intended model's own ops. Nothing is faked in the
answer of ``/api/machines``: E4's ``measured`` block is C4's, from a real ``[[scrape]]`` entry and
its points."""

from __future__ import annotations

import datetime as dt
import time

from intended_seed import fixture, seed

from orchestra.config import load_project
from orchestra.events import Events

FCI, NM, SAIL = "feature_count_improver", "nightly_metrics", "sail"
EMIT = "work.improvement_proposed"
ADDED = ["changes.requested", "gate.rejected", "gate.landed"]
REMOVED = ["session.settled", "task.reported"]
FRAMES = ("E1", "E2", "E3", "E3-continuous", "E3-external", "E4")

SUPERVISOR = {"author": "supervisor", "source": "supervisor", "reason": "the owner asked for a feedback loop",
              "quote": "create a new Universal Machine called Feature Count Improver"}
# the frames' Supervisor acts on the owner's requests, as orchestra-agents' Supervisor does: it
# announces it listens for them, so the page names it and offers ask / confirm / discard / the kind
# switch (static/intended-core.js: no listener, no request controls). The capture predates that rule.
REQUESTS = {"supervisor": ["orchestra.intent.requested"]}


def owner(quote: str) -> dict:
    return {"author": "owner", "source": "supervisor", "turn": "sessions/supervisor/42", "message": "msg_0201", "quote": quote}


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.UTC).isoformat().replace("+00:00", "Z")


def replay_observed(project, span_s: float = 660.0) -> int:
    """Publish the captured machines' events: each instance announces itself (mode, kind, what it
    listens for, its package), then each machine's events of each type, spread over the last
    ``span_s`` seconds, and the hand-offs between machines (the same subject, one after the
    other). Returns how many events were published."""
    events, cap = Events.for_project(project), fixture("machines")
    t0, n = time.time() - span_s, 0
    for m in cap["machines"]:
        if m["bootstrap"]:
            continue
        insts = m["instances"] or [{"id": m["id"], "mode": m["mode"], "kind": m["kind"]}]
        for i in insts:
            src = m["id"] if i["id"] == m["id"] else f"{m['id']}/{i['id']}"
            data = {"mode": i.get("mode") or m["mode"], "kind": i.get("kind") or m["kind"], "listens_for": m["subscribes"] + REQUESTS.get(m["id"], [])}
            if m.get("package"):
                data["package"] = m["package"]
            events.publish("orchestra.machine.started", data, source=src, time=_iso(t0))
            n += 1
    for m in cap["machines"]:
        if m["bootstrap"]:
            continue
        srcs = [m["id"] if not m["instances"] else f"{m['id']}/{i['id']}" for i in (m["instances"] or [None])]
        for p in m["publishes"]:
            for k in range(p["count"]):
                t = t0 + 5 + (span_s - 10) * (k + 0.5) / p["count"]
                events.publish(p["type"], {"n": k}, source=srcs[k % len(srcs)], time=_iso(t))
                n += 1
    for h in cap["handoffs"]:
        to = next(m for m in cap["machines"] if m["id"] == h["to"])
        nxt = to["publishes"][0]["type"] if to["publishes"] else None
        if not nxt or not h.get("via"):
            continue
        for k in range(min(h["count"], 6)):
            subj = f"T-{h['from']}-{h['to']}-{k}"
            t = time.time() - 60 + k
            events.publish(h["via"], {}, source=h["from"], subject=subj, time=_iso(t))
            events.publish(nxt, {}, source=h["to"], subject=subj, time=_iso(t + 0.5))
            n += 2
    return n


def improver(engagement: dict | None = None) -> dict:
    return {"op": "propose_machine", "id": FCI, "title": "Feature Count Improver",
            "description": "Finds why tickets are rejected or fail the gate and proposes work to remove those causes",
            "tags": ["features", "feedback loop", "delivery"], "kind": "universal", "managed": "orchestra",
            "engagement": engagement or {"mode": "continuous"}, "receives": list(REMOVED), "emits": [EMIT],
            "reads": ["features", "acceptance_tests_passing"],
            "spec": {"invariants": ["never changes code itself; it proposes work", "reads the Features series, never writes it",
                                    "one proposal per cause, with evidence"],
                     "steps": ["On each settled session or task report, read the ticket's history: its review and its gate result.",
                               "Say why it fell short, if it did: rejected in review, failed the gate, reopened.",
                               "Group the causes across tickets; keep the evidence (tickets, gate logs).",
                               "For a cause seen at least twice, write one proposal that would remove it.",
                               f"Publish it as {EMIT}, with its evidence."],
                     "uses": ["the ticket queue and each ticket's history · reads", "review notes and the merge gate's logs · reads",
                              "the Coordinator · sends it proposals, through what it emits"]},
            "guessed": ["receives[0]", "receives[1]"]}


E2_STEPS = [("At 00:00, read the day's tickets that reached DONE or REJECTED from the queue, and the merge gate's results "
             "(gate.rejected, gate.landed)."),
            "For each rejection, read why: the reviewer's changes.requested; for each gate failure, the failing unit and its log.",
            "Group the causes across the day; keep the evidence (tickets, review notes, gate logs).",
            "For each cause, come up with an idea that would remove it, and what it should do to Features.",
            f"Send the ideas to the Coordinator as {EMIT}, one per cause with its evidence, for it to schedule."]


def e1_calls() -> list[tuple[list[dict], dict]]:
    return [([improver(), {"op": "declare_event", "type": EMIT, "description": "one idea to remove a cause of rejected work, with its evidence"},
              {"op": "set_expected_effect", "machine": FCI, "horizon_s": 604800, "edits": [
                  {"stock": "features", "rises": True},
                  {"flow": "tasks_gate_runs_total_landed", "factor": 1.2},
                  {"flow": "tasks_ticket_transitions_total_worker_REJECTED_IN_PROGRESS", "factor": 0.8},
                  {"to": "tasks_tickets_OPEN", "appears": True}]}], SUPERVISOR)]


def e2_calls() -> list[tuple[list[dict], dict]]:
    spec = improver()["spec"] | {"steps": E2_STEPS}
    return [*e1_calls(), ([{"op": "revise_machine", "id": FCI,
                            "set": {"engagement": {"mode": "scheduled", "at": "00:00", "tz": "America/Los_Angeles", "missed": "skip"},
                                    "spec": spec},
                            "add": {"receives": ADDED}, "remove": {"receives": REMOVED}}],
                          owner("…watch the ticket queue for DONE and REJECTED tickets, and the Merge Gate… "
                                "…make this a scheduled task for 12am every day"))]


NM_SPEC = {
    "adhoc": {"command": "python -m tools.nightly_metrics",
              "arguments": {"--date YYYY-MM-DD": "the day to summarise (default: yesterday)",
                            "--out DIR": "where the summary is written (default: reports/)",
                            "--dry-run": "say what it would publish; publish nothing"},
              "environment": {"ORCHESTRA_REPO": "the repository's root", "ORCHESTRA_MACHINE_LOG": "where its log goes",
                              "NIGHTLY_TZ": "America/Los_Angeles"},
              "stdin": "JSON of the offer", "exit": "0: done · anything else: refused, with its stderr as the reason"},
    "continuous": {"command": "python -m tools.nightly_metrics --serve", "protocol": "http", "listens_on": "127.0.0.1:8130",
                   "send": "POST /events", "receive": {"how": "poll", "call": "getTasks()", "every": "10 s"}, "health": "GET /health"},
    "external": {"source": NM, "runs_where": "the analytics team's own service",
                 "log": "not readable: a log is read only within the project's repository or state directory"},
}


def e3_calls(mode: str) -> list[tuple[list[dict], dict]]:
    receives = ["gate.landed", *(["summary.requested"] if mode == "adhoc" else [])]
    op = {"op": "propose_machine", "id": NM, "title": "Nightly metrics",
          "description": "Summarises the day's landed tickets and gate results for the Coordinator's morning planning",
          "tags": ["reporting", "nightly"], "kind": "programmatic", "managed": "external" if mode == "external" else "orchestra",
          "engagement": {"mode": "ad hoc" if mode == "adhoc" else "continuous"}, "receives": receives, "emits": ["summary.ready"],
          "spec": NM_SPEC[mode]}
    return [([op], owner("add a nightly metrics job that summarises the day for the coordinator"))]


def e4_calls() -> list[tuple[list[dict], dict]]:
    who = owner("we merge through SAIL, the company's landing queue; it runs three runners")
    return [([{"op": "propose_machine", "id": SAIL, "title": "SAIL", "description": "the company's landing queue", "kind": "programmatic",
               "managed": "external", "engagement": {"mode": "continuous"}, "spec": {"source": SAIL}},
              {"op": "confirm", "part": "machine", "id": SAIL},
              {"op": "propose_attachment", "machine": SAIL, "instrument": "company_prom",
               "match": {"prefix": "sail_", "labels": {"job": "sail"}}, "instance_label": "runner"}], who),
            ([{"op": "confirm", "part": "attachment", "id": "sail_company_prom"}], who)]


# E4's instrument: the company's Prometheus, scraped (C4: an attachment names an instrument the
# Instruments page lists), and the three runners' points as the scrape writes them
COMPANY_PROM = """
[[scrape]]
name = "company_prom"
url = "http://127.0.0.1:1/metrics"
"""
RUNNERS = [("runner-1", 1, 4), ("runner-2", 1, 2), ("runner-3", 0, 0)]


def measure_sail(project) -> None:
    from orchestra.metrics import Point
    from orchestra.metrics import for_project as metrics_for

    now, pts = time.time(), []
    for runner, up, depth in RUNNERS:
        for k in range(6):
            t = now - 60 - (5 - k) * 30
            lab = {"project": project.key, "instrument": "company_prom", "job": "sail", "runner": runner}
            pts += [Point("sail_up", float(up), t, lab), Point("sail_queue_depth", float(depth), t, lab),
                    Point("sail_runs_total", float(10 * k), t, lab)]
    metrics_for(project).write(pts)


def calls(frame: str) -> list[tuple[list[dict], dict]]:
    if frame == "E1":
        return e1_calls()
    if frame == "E2":
        return e2_calls()
    if frame.startswith("E3"):
        return e3_calls(frame.split("-")[1] if "-" in frame else "adhoc")
    if frame == "E4":
        return e4_calls()
    raise ValueError(f"no frame {frame}")


def seed_frame(project, frame: str):
    """The frame's project: the discovered versions, Features declared (D1), the frame's machine;
    for E4 its instrument and points. Returns the project as reloaded (E4 adds configuration)."""
    if frame == "E4":
        project.config_file.write_text(project.config_file.read_text() + COMPANY_PROM)
        project = load_project(project.repo_root)
        measure_sail(project)
    seed(project, declared=False)
    project.intended.apply([{"op": "declare_stock", "id": "features", "name": "Features", "near": 'tasks_tickets{state="DONE"}'}],
                           owner("I'm going to create a Features stock."))
    for ops, prov in calls(frame):
        project.intended.apply(ops, prov)
    return project
