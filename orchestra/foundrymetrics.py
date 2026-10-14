"""The foundry's readings: what the log, the store, and the repository say about each stock
and flow in `foundry`, over a window, and the same signals over the window before it so
every loop has a direction. Everything is a count, a ratio, or a time taken from data;
each reading carries the estimator that produced it so the page can state it.

Send-backs are split by cause from what the store already holds: a review rejection with
a reviewer's REJECTED note is a defect; one without is Orchestra's send-back after three
reviews produced no verdict (a machine failure, not an inspection result); a gate run that
failed on its own result is a defect, a timeout or start failure is a machine failure, a
conflict is a conflict. Restarts and re-pickups are losses, not flows of work."""

from __future__ import annotations

import datetime as dt
import re
import statistics
import subprocess
from pathlib import Path
from typing import Any

from . import foundrygit
from .loopmetrics import _ts

CHURN_DAYS = 14
HEALTH_STALE = 600        # seconds without a health check after which "up" is not believed
PLAN_ROLES = {"coordinator", "supervisor", "pipeline_manager"}
GATE_TIMEOUT_RC = 124
NOTE_SLACK = 180          # seconds between a reviewer's verdict note and the transition it caused
MAX_LOG_BYTES = 2_000_000


def _n(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _median(xs):
    return statistics.median(xs) if xs else None


def _ratio(a, b, nd=2):
    return round(a / b, nd) if b else None


def _epoch(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(str(v)).timestamp()
        except ValueError:
            return None


def _pytest_tail(tail: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for n, word in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed)", tail or ""):
        key = "error" if word.startswith("error") else word
        out[key] = out.get(key, 0) + int(n)
    return out


def _failed_tests(stage: dict) -> list[str]:
    """The tests pytest reported as FAILED in the stage's log, if the log is still there."""
    path = stage.get("log")
    if not path:
        return []
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_LOG_BYTES:
            return []
        return sorted(set(re.findall(r"^FAILED (\S+)", p.read_text(errors="replace"), re.MULTILINE)))
    except OSError:
        return []


# -- the ticket history ----------------------------------------------------------------------

class History:
    """Every ticket's transitions and rejection causes, from the whole log plus the store's
    notes and gate runs, so that windowed readings can ask what state a ticket was in at
    any time. A review rejection is a defect only with a reviewer's REJECTED verdict; a gate
    send-back is a defect only when its run failed on its own result."""

    def __init__(self, events: list[dict], store) -> None:
        self.seq: dict[str, list[tuple[float, str, str]]] = {}
        self.created: dict[str, float] = {}
        for e in events:                                   # log order is kept: same-second ties stay in sequence
            if e["type"] == "ticket_transition" and e.get("ticket"):
                self.seq.setdefault(e["ticket"], []).append((_ts(e), e.get("from") or "", e["to"]))
            elif e["type"] == "ticket_created" and e.get("ticket"):
                self.created[e["ticket"]] = _ts(e)
        runs = []
        for r in store.gate_runs():
            end = _epoch(r.get("finished_at"))
            if end is not None:
                runs.append((end, set(r.get("batch") or []), _run_class(r)))
        self.cause: dict[tuple[str, float], str] = {}       # (ticket, ts of the REJECTED transition) -> defect | gate | gate_lost | conflict | no_verdict
        for tid in self.seq:
            try:
                notes = store.notes(tid)
            except (KeyError, ValueError, OSError):
                notes = []
            vs = [(_epoch(n.get("created_at")) or 0.0, n.get("text", "")[:8].upper()) for n in notes if n.get("author") == "reviewer" and n.get("kind") == "review"]
            for ts, frm, to in self.seq[tid]:
                if to != "REJECTED":
                    continue
                if frm == "MERGING":
                    run = min((r for r in runs if tid in r[1] and abs(r[0] - ts) <= NOTE_SLACK), key=lambda r: abs(r[0] - ts), default=None)
                    cls = run[2] if run else "defect"
                    self.cause[(tid, ts)] = "gate" if cls == "defect" else "conflict" if cls == "conflict" else "gate_lost"
                elif any(abs(ts - vts) <= NOTE_SLACK and v.startswith("REJECTED") for vts, v in vs):
                    self.cause[(tid, ts)] = "defect"
                else:
                    self.cause[(tid, ts)] = "no_verdict"

    def previous(self, tid: str, ts: float, frm: str, to: str) -> tuple[str, str] | None:
        """The transition logged before the given one."""
        seq = self.seq.get(tid, [])
        for i, (t, f, x) in enumerate(seq):
            if t == ts and f == frm and x == to:
                return (seq[i - 1][1], seq[i - 1][2]) if i else None
        return None

    def pending_defect(self, tid: str, at: float) -> bool:
        """Was the ticket sent back for a defect and not yet re-submitted, at that time?"""
        pending = False
        for t, frm, to in self.seq.get(tid, []):
            if t > at:
                break
            if to == "REJECTED" and self.cause.get((tid, t)) in ("defect", "gate"):
                pending = True
            elif (to == "READY_FOR_REVIEW" and frm == "IN_PROGRESS") or to in ("DONE", "CANCELLED"):
                pending = False                                   # a block does not clear it: on this kind of org a block is a turn-limit escape
        return pending

    def spell_origin(self, tid: str, at: float, frm: str) -> str | None:
        """The state a ticket came from into its current spell: for a transition out of
        IN_PROGRESS, the state before the working spell began, looking past the restarts
        (IN_PROGRESS → OPEN → IN_PROGRESS) a turn limit causes; otherwise the state before."""
        seq = [x for x in self.seq.get(tid, []) if x[0] < at]
        if not seq:
            return None
        if frm != "IN_PROGRESS":
            return seq[-1][1]
        i = len(seq) - 1
        while i >= 1 and seq[i][1:] == ("OPEN", "IN_PROGRESS") and seq[i - 1][1:] == ("IN_PROGRESS", "OPEN"):
            i -= 2
        return seq[i][1] if seq[i][2] == "IN_PROGRESS" else None

    def cause_before(self, tid: str, at: float, frm: str, to: str | None = None) -> str | None:
        """The cause a transition carries: a send-back's own cause; otherwise, while a defect is
        unresolved (sent back and not landed since), that defect's cause, through pickups,
        re-submissions, approvals, blocks and re-plans; otherwise, for a pickup or a re-submission
        after a send-back with no verdict, that send-back's cause."""
        seq = [x for x in self.seq.get(tid, []) if x[0] < at]
        norm = lambda c: {"gate_lost": "lost"}.get(c, c)
        last_defect = lambda: next((self.cause.get((tid, t)) for t, f, x in reversed(seq) if x == "REJECTED" and self.cause.get((tid, t)) in ("defect", "gate")), None)
        if to == "REJECTED":                                      # a send-back carries its own cause
            return norm(self.cause.get((tid, at)))
        rej = next(((t, f, x) for t, f, x in reversed(seq) if x == "REJECTED"), None)
        if rej is None or any(x in ("DONE", "CANCELLED") for t, f, x in seq if t > rej[0]):
            return None
        if frm == "REJECTED":                                     # a pickup carries the send-back it follows: a fix pickup or a re-pick
            return norm(self.cause.get((tid, rej[0])))
        before = seq[-1][0] if seq else at                        # strictly before this transition, so a submission does not clear the defect it is fixing
        if frm == "IN_PROGRESS":                                  # a submission is a fix while a defect is pending (through blocks and re-plans), else a re-run after a send-back with no verdict
            if self.unresolved_defect(tid, before):
                return last_defect()
            return norm(self.cause.get((tid, rej[0]))) if self.spell_origin(tid, at, frm) == "REJECTED" else None
        return last_defect() if self.unresolved_defect(tid, before) else None   # a verdict on a fix, while the defect is not yet landed

    def returned(self, tid: str, at: float) -> bool:
        """Sent back without a verdict and not yet re-picked: a machine loss waiting its turn."""
        waiting = False
        for t, frm, to in self.seq.get(tid, []):
            if t > at:
                break
            if to == "REJECTED":
                waiting = self.cause.get((tid, t)) in ("no_verdict", "gate_lost", "conflict")
            elif (frm, to) == ("REJECTED", "IN_PROGRESS") or to in ("DONE", "CANCELLED"):
                waiting = False
        return waiting

    def awaiting_fix(self, tid: str, at: float) -> bool:
        """Was the ticket sent back for a defect and not yet picked up for a fix, at that time?
        The stock's level: the pickup is the rework flow into work in progress."""
        waiting = False
        for t, frm, to in self.seq.get(tid, []):
            if t > at:
                break
            if to == "REJECTED" and self.cause.get((tid, t)) in ("defect", "gate"):
                waiting = True
            elif (frm, to) == ("REJECTED", "IN_PROGRESS") or to in ("DONE", "CANCELLED"):
                waiting = False
        return waiting

    def unresolved_defect(self, tid: str, at: float) -> bool:
        """Was the ticket sent back for a defect and not yet landed or cancelled, at that time?
        Re-submissions and approvals do not resolve it; only a landing does."""
        pending = False
        for t, frm, to in self.seq.get(tid, []):
            if t > at:
                break
            if to == "REJECTED" and self.cause.get((tid, t)) in ("defect", "gate"):
                pending = True
            elif to in ("DONE", "CANCELLED"):
                pending = False
        return pending

    def last_rejection(self, tid: str, at: float) -> tuple[float, str] | None:
        last = None
        for t, _, to in self.seq.get(tid, []):
            if t > at:
                break
            if to == "REJECTED":
                last = (t, self.cause.get((tid, t), "defect"))
        return last


def _run_class(r: dict) -> str:
    """What ended a gate run: landed, defect, timeout, start_failure, conflict, base_broken, error."""
    st = r.get("status")
    if st in ("landed", "conflict", "base_broken", "error"):
        return st
    failed = next((s for s in r.get("stages") or [] if s.get("status") not in ("passed", None)), None)
    if failed is None or failed.get("stage") == "start" or failed.get("name") == "target":
        return "start_failure"
    if str(failed.get("returncode")) == str(GATE_TIMEOUT_RC):
        return "timeout"
    return "defect"


# -- windowed readings -------------------------------------------------------------------------

from .foundrygraph import TRANSITION_OWNER


def attributed_counts(events: list[dict], hist: History, since: str, runs: list[dict] | None = None) -> dict[str, int]:
    """Events in the window by the agent that caused them: ``agent|type`` and ``agent|type:filter``.
    An event with ``by`` or ``author`` is theirs; a ticket transition belongs to the agent
    that moves tickets out of its source state, with REJECTED split by its cause."""
    out: dict[str, int] = {}
    run_class = {r.get("id"): _run_class(r) for r in (runs or [])}
    recent_note: dict[str, tuple[float, str]] = {}          # ticket -> (ts, author) of the last note seen
    for e in events:
        if e["type"] == "note_added" and e.get("ticket") and e.get("author"):
            recent_note[e["ticket"]] = (_ts(e), e["author"])
        if e.get("ts", "") < since:
            continue
        t = e["type"]
        if t == "ticket_transition":
            frm, to = e.get("from") or "", e["to"]
            who = TRANSITION_OWNER.get((frm, to))
            if (frm, to) == ("IN_REVIEW", "REJECTED"):
                who = "reviewer" if hist.cause.get((e.get("ticket"), _ts(e))) == "defect" else "orchestra"
            elif (frm, to) in (("BLOCKED", "OPEN"), ("OPEN", "CANCELLED"), ("BLOCKED", "CANCELLED"), ("OPEN", "OPEN")):
                note = recent_note.get(e.get("ticket") or "")
                if note and 0 <= _ts(e) - note[0] <= 60:         # evidence: whoever wrote on the ticket seconds before moved it
                    who = note[1]
            if not who:
                continue
            for k in (f"{who}|{t}", f"{who}|{t}:{to}", f"{who}|{t}:{frm}>{to}"):
                out[k] = out.get(k, 0) + 1
            origin = hist.spell_origin(e.get("ticket") or "", _ts(e), frm)
            prev = (origin, frm) if origin else None
            # a transition that follows a send-back carries the send-back's cause (defect, gate, no_verdict, lost, conflict),
            # so a pickup or a re-submission can be counted as a fix or as a re-run
            cause = hist.cause_before(e.get("ticket") or "", _ts(e), frm, to)
            keys = [f"{who}|{t}:{to}", f"{who}|{t}:{frm}>{to}"]
            if prev:
                keys += [f"{who}|{t}:{to}|from:{prev[0]}", f"{who}|{t}:{frm}>{to}|from:{prev[0]}"]
            if cause:
                keys += [f"{k}|cause:{cause}" for k in keys]
            for k in keys[2:]:
                out[k] = out.get(k, 0) + 1
            continue
        if t == "gate_rejected" and run_class.get(e.get("gate_run")) not in (None, "defect"):
            out["merge_gate|gate_rejected:lost"] = out.get("merge_gate|gate_rejected:lost", 0) + 1     # a timeout or start failure, not an inspection result
            continue
        who = e.get("by") or e.get("author") or {"gate_started": "merge_gate", "gate_landed": "merge_gate", "gate_rejected": "merge_gate", "gate_conflict": "merge_gate", "gate_error": "merge_gate",
                                                "gate_base_broken": "merge_gate", "staging_deployed": "merge_gate", "staging_failed": "merge_gate", "staging_restarted": "orchestra",
                                                "pipeline_resumed": "pipeline_manager", "pipeline_paused": "merge_gate", "session_started": "orchestra", "session_settled": "orchestra",
                                                "turn_timed_out": "orchestra", "agent_crashed": "orchestra", "pickup_paused": "orchestra", "pickup_resumed": "orchestra"}.get(t)
        if not who:
            continue
        v = e.get("status") or e.get("probe") or e.get("subject")
        for k in ([f"{who}|{t}"] + ([f"{who}|{t}:{v}"] if v else [])):
            out[k] = out.get(k, 0) + 1
    return out


def _activity(kind: str, agents: dict) -> str:
    if kind in ("worker", "reviewer"):
        return kind
    if kind in PLAN_ROLES:
        return "plan"
    ag = agents.get(kind)
    if ag is not None and ag.team:
        return ag.team.split("/")[0]
    return "other"


def gate_outcomes(runs: list[dict]) -> dict:
    """Every gate run by what ended it, and the concentration of defects by ticket and test."""
    by: dict[str, int] = {}
    stages: dict[str, int] = {}
    tickets: dict[str, int] = {}
    tests: dict[str, int] = {}
    for r in runs:
        key = _run_class(r)
        by[key] = by.get(key, 0) + 1
        if key != "defect":
            continue
        failed = next((s for s in r.get("stages") or [] if s.get("status") not in ("passed", None)), None) or {}
        name = failed.get("name") or failed.get("stage") or "?"
        stages[name] = stages.get(name, 0) + 1
        for tid in r.get("batch") or []:
            tickets[tid] = tickets.get(tid, 0) + 1
        for tname in _failed_tests(failed):
            tests[tname] = tests.get(tname, 0) + 1
    own = by.get("landed", 0) + by.get("defect", 0)
    # a defect is a (ticket, stage) that failed, however many runs or tests it failed in: an
    # environment fault that fails twenty tests is one defect
    return {"by": by, "defect_stage": stages, "defect_tickets": tickets, "defect_tests": tests, "distinct_defects": len(tickets), "runs": len(runs), "own_result": own,
            "pass": _ratio(by.get("landed", 0), own)}


def _run_tests(run: dict | None, *, main: bool = False) -> dict | None:
    """pytest counts per stage of a run. For main's own state, a base_broken run's
    ``base_check`` stages are what ran on main; its ``stages`` ran on the failed candidate."""
    if not run:
        return None
    out = {}
    stages = run.get("base_check") if main and run.get("status") == "base_broken" and run.get("base_check") else run.get("stages")
    for s in stages or []:
        if "pytest" in (s.get("command") or ""):
            out[s.get("name") or s.get("stage")] = {**_pytest_tail(s.get("tail", "")), "status": s.get("status")}
    return {"run": run.get("id"), "at": run.get("finished_at"), "status": run.get("status"), "stages": out} if out else None


def _open_outage(events: list[dict], until: float) -> float | None:
    """How long the current outage has been open: from the first trouble after the last deploy
    that stayed healthy, if no deploy since has stayed healthy. None when the build is fine."""
    deploys = sorted((e for e in events if e["type"] == "staging_deployed"), key=_ts)
    troubles = sorted((e for e in events if e["type"] in ("staging_failed", "staging_restarted")), key=_ts)
    if not deploys or not troubles:
        return None
    start = None
    for j, d in enumerate(deploys):
        after = _ts(deploys[j + 1]) if j + 1 < len(deploys) else until
        first = next((_ts(x) for x in troubles if _ts(d) < _ts(x) < after), None)
        if first is None:
            start = None                                          # a deploy that stayed healthy closes any outage
        elif start is None:
            start = first
    return until - start if start is not None else None


def _window(hist: History, store, events: list[dict], agents: dict, since: float, until: float, tickets_by_id: dict | None = None) -> dict[str, Any]:
    """The flow readings for one window [since, until)."""
    tickets_by_id = tickets_by_id if tickets_by_id is not None else store.tickets_by_id()
    evs = [e for e in events if since <= _ts(e) < until]
    days = max((until - since) / 86400, 1e-9)
    counts: dict[str, int] = {}
    for e in evs:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    tr = [(e["ticket"], _ts(e), e.get("from") or "", e["to"]) for e in evs if e["type"] == "ticket_transition" and e.get("ticket")]
    pairs: dict[str, int] = {}
    for _, _, f, to in tr:
        pairs[f"{f}>{to}"] = pairs.get(f"{f}>{to}", 0) + 1
    # starts: a pickup after a restart or an unblock is a re-pickup, not new work
    starts = repicks = replanned = 0
    for tid, ts, f, to in tr:
        if (f, to) != ("OPEN", "IN_PROGRESS"):
            continue
        before = hist.previous(tid, ts, f, to)
        if before == ("IN_PROGRESS", "OPEN"):
            repicks += 1                                          # after a restart: the turn was lost
        elif before == ("BLOCKED", "OPEN"):
            replanned += 1                                        # after a re-plan: the re-planning loop's own flow
        else:
            starts += 1
    # review inspections: verdicts given; send-backs by cause; defects distinct by ticket
    arrivals = pairs.get("IN_PROGRESS>READY_FOR_REVIEW", 0)
    redo = pairs.get("IN_REVIEW>READY_FOR_REVIEW", 0)
    approvals = pairs.get("IN_REVIEW>APPROVED", 0)
    rev_cause: dict[str, int] = {}
    for tid, ts, f, to in tr:
        if (f, to) == ("IN_REVIEW", "REJECTED"):
            c = hist.cause.get((tid, ts), "defect")
            rev_cause[c] = rev_cause.get(c, 0) + 1
    rev_defects = rev_cause.get("defect", 0)
    verdicts = approvals + rev_defects
    tickets_reviewed = {tid for tid, _, f, to in tr if (f, to) in (("IN_REVIEW", "APPROVED"), ("IN_REVIEW", "REJECTED"))}
    tickets_defect = {tid for tid, ts, f, to in tr if (f, to) == ("IN_REVIEW", "REJECTED") and hist.cause.get((tid, ts)) == "defect"}
    runs = [r for r in store.gate_runs() if since <= (_epoch(r.get("started_at")) or 0) < until]
    gate = gate_outcomes(runs)
    # fix rounds and bad fixes: a re-submission while a defect send-back is pending
    fix_rounds = bad = 0
    for tid, ts, f, to in tr:
        if (f, to) != ("IN_PROGRESS", "READY_FOR_REVIEW") or not hist.unresolved_defect(tid, ts - 1):
            continue
        fix_rounds += 1                                           # every re-submission while a defect is unlanded is rework progress (Cooper; Lyneis & Ford)
        # followed to the defect's next verdict: a review or gate rejection for a defect makes it a bad fix,
        # a landing makes it good; approvals, no-verdict reviews, blocks and further re-submissions on the
        # way do not decide it (the defect is the same until a verdict says otherwise)
        for t2, f2, to2 in hist.seq.get(tid, []):
            if t2 <= ts:
                continue
            if to2 in ("DONE", "CANCELLED"):
                break
            if to2 == "REJECTED" and hist.cause.get((tid, t2)) in ("defect", "gate"):
                bad += 1
                break
    # how late a defect is found: from the submission the verdict judged to the verdict, by stage; after landing, from the deploy to its first trouble
    def _since_submission(tid: str, ts: float) -> float | None:
        sub = next((t for t, f, x in reversed(hist.seq.get(tid, [])) if t < ts and (f, x) == ("IN_PROGRESS", "READY_FOR_REVIEW")), None)
        return ts - sub if sub is not None else None
    delay_review = [d for tid, ts, f, to in tr if (f, to) == ("IN_REVIEW", "REJECTED") and hist.cause.get((tid, ts)) == "defect" for d in [_since_submission(tid, ts)] if d is not None]
    delay_gate = [d for tid, ts, f, to in tr if (f, to) == ("MERGING", "REJECTED") and hist.cause.get((tid, ts)) == "gate" for d in [_since_submission(tid, ts)] if d is not None]
    # F2: review misses: approvals the gate then rejected for a defect, before the next re-submission
    approvals_missed, missed_defects = 0, set()
    for tid, ts, f, to in tr:
        if (f, to) != ("IN_REVIEW", "APPROVED"):
            continue
        for t2, f2, to2 in hist.seq.get(tid, []):
            if t2 <= ts:
                continue
            if to2 == "DONE" or (f2, to2) == ("IN_PROGRESS", "READY_FOR_REVIEW"):
                break
            if (f2, to2) == ("MERGING", "REJECTED") and hist.cause.get((tid, t2)) == "gate":
                approvals_missed += 1
                run = min((r for r in runs if tid in (r.get("batch") or []) and abs((_epoch(r.get("finished_at")) or 0) - t2) <= NOTE_SLACK), key=lambda r: abs((_epoch(r.get("finished_at")) or 0) - t2), default=None)
                failed = next((st for st in (run or {}).get("stages") or [] if st.get("status") not in ("passed", None)), None) or {}
                missed_defects.add((tid, failed.get("name") or failed.get("stage") or "?"))
                break
    # turns: active time per activity; a worker turn while a defect send-back is pending is a fix,
    # a turn after a no-verdict send-back is a re-run (a loss), otherwise implementation
    kinds = {s.get("id"): s.get("kind") for s in [*store.sessions(), *store.runtime().get("archived_sessions", {}).values()]}
    open_turns: dict[str, tuple[float, str]] = {}
    turns: list[tuple[str, str, float, float]] = []
    for e in evs:
        sid = e.get("session")
        if e["type"] == "session_started" and sid:
            open_turns[sid] = (_ts(e), e.get("kind") or kinds.get(sid) or "")
        elif e["type"] == "session_settled" and sid in open_turns:
            st, kind = open_turns.pop(sid)
            turns.append((sid, kind, st, _ts(e)))
    for sid, (st, kind) in open_turns.items():
        turns.append((sid, kind, st, until))
    timeouts = [(e.get("session"), _ts(e)) for e in evs if e["type"] == "turn_timed_out"]
    hours: dict[str, float] = {}
    nturns: dict[str, int] = {}
    lost_worker = lost_all = 0.0
    timed_out: dict[str, int] = {}
    turns_by_kind: dict[str, int] = {}
    for sid, kind, st, en in turns:
        dur = max(0.0, en - st) / 3600
        act = _activity(kind, agents)
        k0 = "worker" if act in ("worker", "fix", "rerun", "implement") else act
        turns_by_kind[k0] = turns_by_kind.get(k0, 0) + 1
        if any(ts_sid == sid and st <= ts <= en + 5 for ts_sid, ts in timeouts):
            timed_out[k0] = timed_out.get(k0, 0) + 1
        if act == "worker":
            tid = sid.split("-", 1)[1] if sid.startswith("worker-") else ""
            if hist.unresolved_defect(tid, st + 5):
                act = "fix"                                       # any turn on a change with an unlanded defect is rework
            else:
                last = hist.last_rejection(tid, st + 5)
                nxt_ready = next((t for t, f, to in hist.seq.get(tid, []) if t > (last[0] if last else 0) and (f, to) == ("IN_PROGRESS", "READY_FOR_REVIEW")), None)
                act = "rerun" if last and last[1] == "no_verdict" and (nxt_ready is None or nxt_ready > st) else "implement"
        hours[act] = hours.get(act, 0.0) + dur
        nturns[act] = nturns.get(act, 0) + 1
        if any(ts_sid == sid and st <= ts <= en + 5 for ts_sid, ts in timeouts):
            lost_all += dur
            if act in ("implement", "fix", "rerun"):
                lost_worker += dur
    worker_hours = hours.get("implement", 0.0) + hours.get("fix", 0.0)        # productive hours; re-runs after no-verdict reviews are a loss
    limits = [e.get("limit") for e in evs if e["type"] == "turn_timed_out" and e.get("limit")]
    # landed, deployed
    landed = [e for e in evs if e["type"] == "gate_landed"]
    deploys = sorted((e for e in evs if e["type"] == "staging_deployed"), key=_ts)
    troubles = sorted((e for e in evs if e["type"] in ("staging_failed", "staging_restarted")), key=_ts)
    troubled = 0
    for i, d in enumerate(deploys):
        nxt = _ts(deploys[i + 1]) if i + 1 < len(deploys) else until
        if any(_ts(d) < _ts(t) < nxt for t in troubles):
            troubled += 1
    restores, open_until = [], -1.0
    for t in troubles:
        if _ts(t) <= open_until:
            continue                                           # inside an outage already counted from its first trouble
        open_until = float("inf")                              # not restored until a deploy stays healthy
        for j, d in enumerate(deploys):
            if _ts(d) <= _ts(t):
                continue
            after = _ts(deploys[j + 1]) if j + 1 < len(deploys) else until
            if not any(_ts(d) < _ts(x) < after for x in troubles):   # a deploy that stayed healthy
                restores.append(_ts(d) - _ts(t))
                open_until = _ts(d)
                break
    leads = [ts - hist.created[tid] for tid, ts, _, to in tr if to == "DONE" and tid in hist.created]
    # defects found after landing: a ticket created in the window that cites a landed ticket
    # or commit (a bug report against something that shipped), and each build that
    # crash-restarted in service (one defect per build, however many restarts)
    done_ids = {tid for tid, seq in hist.seq.items() if any(to == "DONE" for _, _, to in seq)}
    landed_shas = {e.get("commit", "")[:7] for e in events if e["type"] == "gate_landed" and e.get("commit")}
    bug_tickets = []
    for e in evs:
        if e["type"] != "ticket_created":
            continue
        t = tickets_by_id.get(e.get("ticket"))
        text = f"{getattr(t, 'title', '')} {getattr(t, 'description', '')}" if t else ""
        cites = set(re.findall(r"\b[A-Z]{2,5}-\d+\b", text)) & done_ids
        cites_sha = any(sha and sha in text for sha in landed_shas)
        if (cites or cites_sha) and e.get("ticket") not in cites:
            bug_tickets.append(e.get("ticket"))
    crashing_builds = sorted({t.get("build") for t in troubles if t["type"] == "staging_restarted" and t.get("build")})
    # a defect that survives successive landings is one defect: consecutive deployed builds that all
    # crash-restarted, with no healthy build between them, are one escape; a ticket that names one of
    # those builds is that escape's ticket; other bug tickets citing shipped work count each
    all_deploys = sorted((e for e in events if e["type"] == "staging_deployed" and e.get("build")), key=_ts)
    crashed = {t.get("build") for t in events if t["type"] == "staging_restarted" and t.get("build")}
    groups, run = [], []
    for d in all_deploys:
        if d["build"] in crashed:
            run.append(d["build"])
        elif run:
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    in_window = [g for g in groups if any(b in crashing_builds for b in g)]
    crash_tickets = [tid for tid in bug_tickets if any(b and b[:7] in f"{getattr(tickets_by_id.get(tid), 'title', '')} {getattr(tickets_by_id.get(tid), 'description', '')}" for b in crashing_builds)]
    other_tickets = [tid for tid in bug_tickets if tid not in crash_tickets]
    escape = len(other_tickets) + len(in_window)
    landed_at = {e.get("commit"): _ts(e) for e in landed}
    land_to_deploy = [_ts(d) - landed_at[d["commit"]] for d in deploys if d.get("commit") in landed_at]
    return {
        "since": dt.datetime.fromtimestamp(since, dt.UTC).isoformat(timespec="seconds"), "until": dt.datetime.fromtimestamp(until, dt.UTC).isoformat(timespec="seconds"), "days": days,
        "counts": counts, "pairs": pairs,
        "flows": {"start": starts, "repick": repicks, "replanned": replanned, "implement": arrivals, "redo": redo, "review": rev_defects, "review_no_verdict": rev_cause.get("no_verdict", 0),
                  "gate": gate["by"].get("defect", 0), "conflict": gate["by"].get("conflict", 0),
                  "failure": gate["by"].get("timeout", 0) + gate["by"].get("start_failure", 0) + gate["by"].get("error", 0),
                  "escape": escape, "escape_bug_tickets": other_tickets, "escape_crash_tickets": crash_tickets, "escape_crashing_builds": crashing_builds, "escape_crash_runs": len(in_window), "escape_crash_groups": in_window, "fix": fix_rounds, "land": len(landed), "deploy": len(deploys), "verify": sum(1 for r in runs if r.get("status") == "landed"),
                  "base": gate["by"].get("base_broken", 0), "restart": pairs.get("IN_PROGRESS>OPEN", 0), "blocked": pairs.get("IN_PROGRESS>BLOCKED", 0)},
        "inspections": {
            "delay": {"review": _median(delay_review), "gate": _median(delay_gate), "after_landing": _median([_ts(t) - _ts(d) for i, d in enumerate(deploys) for t in [next((x for x in troubles if _ts(d) < _ts(x) < (_ts(deploys[i + 1]) if i + 1 < len(deploys) else until)), None)] if t])},
            "review": {"arrivals": arrivals, "redo": redo, "approvals": approvals, "verdicts": verdicts, "by_cause": rev_cause, "defects": rev_defects, "distinct_defects": len(tickets_defect),
                       "pass": _ratio(approvals, verdicts), "tickets": len(tickets_reviewed), "tickets_sent_back": len(tickets_defect), "pass_per_ticket": _ratio(len(tickets_reviewed - tickets_defect), len(tickets_reviewed)),
                       "approvals_gate_rejected": approvals_missed, "distinct_missed": len(missed_defects), "miss_rate": _ratio(approvals_missed, approvals),
                       "cause": "pass = APPROVED verdicts over all verdicts (APPROVED + REJECTED with a reviewer note); reviews with no verdict are not inspections and are counted as losses"},
            "gate": {**gate, "cause": "defect = a stage failed on its own result; timeouts, start failures and conflicts counted apart"},
        },
        "rounds": {"fix_rounds": fix_rounds, "bad_fixes": bad, "bad_fix_fraction": _ratio(bad, fix_rounds), "lead_values": sorted(leads)},
        "time": {"hours": {k: round(v / days, 1) for k, v in sorted(hours.items(), key=lambda kv: -kv[1])}, "turns": nturns,
                 "rework_share": _ratio(hours.get("fix", 0.0), worker_hours), "worker_hours": round(worker_hours / days, 1), "rerun_share": _ratio(hours.get("rerun", 0.0), worker_hours + hours.get("rerun", 0.0)),
                 "turn_limit": max(set(limits), key=limits.count) if limits else None,
                 "timeout_share": {k: _ratio(timed_out.get(k, 0), n) for k, n in turns_by_kind.items()}, "timed_out": timed_out, "turns_by_kind": turns_by_kind,
                 "losses": {"restarts": pairs.get("IN_PROGRESS>OPEN", 0), "repicks": repicks, "turn_timeouts": counts.get("turn_timed_out", 0), "turn_errors": counts.get("turn_error", 0),
                            "compactions": counts.get("agent_compacted", 0), "resets": counts.get("agent_reset", 0), "crashes": counts.get("agent_crashed", 0),
                            "review_no_verdict": rev_cause.get("no_verdict", 0), "review_redo": redo, "gate_lost": gate["by"].get("timeout", 0) + gate["by"].get("start_failure", 0),
                            "rerun_hours": round(hours.get("rerun", 0.0) / days, 1), "worker_hours_ending_in_timeout": round(lost_worker / days, 1), "hours_ending_in_timeout": round(lost_all / days, 1)}},
        "dora": {"landing_per_day": round(len(landed) / days, 1), "lead_time": _median(leads), "lead_n": len(leads), "land_to_deploy": _median(land_to_deploy),
                 "deploys": len(deploys), "deploys_troubled": troubled, "change_failure": _ratio(troubled, len(deploys)), "crashing_builds": crashing_builds,
                 "restarts": sum(1 for t in troubles if t["type"] == "staging_restarted"), "staging_failed": sum(1 for t in troubles if t["type"] == "staging_failed"), "restore": _median(restores),
                 "outage_open_for": _open_outage(events, until)},
        "pipeline_paused_since": next((e.get("ts") for e in reversed(events) if e["type"] == "pipeline_paused"), None) if not any(e["type"] == "pipeline_resumed" and e.get("ts", "") > next((x.get("ts", "") for x in reversed(events) if x["type"] == "pipeline_paused"), "") for e in events) else None,
    }


SIGNAL_KEYS = frozenset({"review_pass", "gate_defects", "gate_distinct_defects", "gate_pass", "rework_share", "worker_timeout_share", "reviewer_timeout_share", "hours_lost",
                         "fix_rounds", "review_defects", "defects_after_landing", "review_miss_rate", "acceptance_defects_at_gate", "bad_fix_fraction", "conflicts_per_landing",
                         "landed_per_worker_hour", "restarts", "defects_found_after_landing", "base_broken", "worker_hours_lost", "starts", "defects_before_gate_share"})


def _signals(w: dict) -> dict[str, float | None]:
    """The loop signals as plain numbers, for direction between windows."""
    t, f, g = w["time"], w["flows"], w["inspections"]["gate"]
    wh = t["worker_hours"] or 0.0
    return {"review_pass": w["inspections"]["review"]["pass"], "gate_defects": f["gate"], "gate_distinct_defects": w["inspections"]["gate"]["distinct_defects"], "gate_pass": g["pass"], "rework_share": t["rework_share"],
            "worker_timeout_share": t["timeout_share"].get("worker"), "reviewer_timeout_share": t["timeout_share"].get("reviewer"), "hours_lost": t["losses"]["hours_ending_in_timeout"],
            "fix_rounds": f["fix"], "review_defects": w["inspections"]["review"]["distinct_defects"], "defects_after_landing": f["escape"], "review_miss_rate": w["inspections"]["review"]["miss_rate"],
            "acceptance_defects_at_gate": w["inspections"]["gate"]["defect_stage"].get("acceptance", 0),
            "defects_before_gate_share": _ratio(w["inspections"]["review"]["distinct_defects"], w["inspections"]["review"]["distinct_defects"] + w["inspections"]["gate"]["distinct_defects"] + f["escape"]),
            "bad_fix_fraction": w["rounds"]["bad_fix_fraction"], "conflicts_per_landing": _ratio(f["conflict"], f["land"]) if f["land"] else (f["conflict"] or None),
            "landed_per_worker_hour": _ratio(f["land"] / w["days"], wh) if wh else None, "restarts": f["restart"], "defects_found_after_landing": f["escape"],
            "base_broken": f["base"], "worker_hours_lost": t["losses"]["worker_hours_ending_in_timeout"], "starts": f["start"]}


def _stock_reading(st, pool: dict) -> dict:
    """One stock's reading from its first estimator; the others are listed beside it."""
    est = st.estimators[0] if st.estimators else {"kind": "none", "reason": "no estimator declared"}
    kind = est.get("kind", "none")
    out: dict = {"estimator_kind": kind}
    tk, git, cur = pool["tickets"], pool["git"], pool["cur"]
    if kind == "tracker":
        states = est.get("states") or []
        now = dt.datetime.now(dt.UTC).timestamp()
        ages = sorted(now - (_epoch(getattr(x, "state_since", None)) or now) for x in tk.values() if x.state in states)
        worst = max(((x.review_rounds or 0), x.id) for x in tk.values() if x.state in states) if ages else (0, None)
        ahead_ = (pool.get("git") or {}).get("ahead") or {}
        branches = [(x.id, ahead_[x.branch]) for x in tk.values() if x.state in states and getattr(x, "branch", None) and x.branch in ahead_]
        out.update(commits_ahead=sum(n for _, n in branches) if ahead_ else None, branches=branches, commits_per_day=(pool.get("git") or {}).get("commits_in_window"))
        out.update(value=sum(1 for x in tk.values() if x.state in states), by_state={s_: sum(1 for x in tk.values() if x.state == s_) for s_ in states},
                   oldest_age=ages[-1] if ages else None, median_age=_median(ages), ages=len(ages), worst_rounds={"ticket": worst[1], "rounds": worst[0]} if worst[0] >= 6 else None,
                   estimator=f"tickets in {', '.join(states)} in the tracker now; ages from each ticket's state_since (residence time in the queue)")
    elif kind == "pending_defects":
        unresolved = pool["unresolved"]
        out.update(value=len(unresolved), tickets=unresolved, awaiting_pickup=pool["awaiting_fix"], not_resubmitted=pool["pending"], unresolved=unresolved, blocked=[tid for tid in unresolved if tk[tid].state == "BLOCKED"],
                   estimator="tickets sent back for a defect (reviewer verdict or gate result) whose send-back has not yet been followed by a landing: work known to need rework and not yet done; beside it, those not yet picked up for a fix. The reviewer's verdict is inferred from the first word of its review note within three minutes of the send-back (step 2 records the cause on the event)")
    elif kind == "returned":
        ret = pool["returned"]
        out.update(value=len(ret), tickets=ret, estimator="tickets sent back with no verdict (a review turn that ended at the limit, a lost gate run, a conflict) and not yet re-picked; a machine loss, not rework")
    elif kind == "git_ahead":
        wip = pool["wip"]
        out.update(value=sum(w["commits"] for w in wip), tickets=len(wip), detail=wip, commits_per_day=git.get("commits_in_window"),
                   estimator="commits ahead of main on the branch of each ticket IN_PROGRESS now (git rev-list), and commits made on any branch in the window")
    elif kind == "landed":
        out.update(**pool["landed"], estimator="every gate_landed commit on main; lines by first-parent diff; survival by first-parent blame")
    elif kind == "gate_tests":
        src = est.get("source", "main")
        run = pool["deployed_tests"] if src == "deployed" and pool["deployed_tests"] else (pool["main_tests"] if src == "main" else (pool["landed_tests"] or pool["main_tests"]))
        source = "deployed build" if src == "deployed" and pool["deployed_tests"] else ("the last landing (nothing deployed)" if src == "deployed" else "main's latest gate check")
        stage = est.get("stage")
        stages = (run or {}).get("stages", {})
        if stage:
            sg = stages.get(stage) or {}
            out.update(value=sg.get("passed"), skipped=sg.get("skipped", 0), failed=sg.get("failed", 0), errors=sg.get("error", 0), stage=stage)
        else:
            out.update(value=sum(v.get("passed", 0) for v in stages.values()) if run else None, stages=stages,
                       failed=sum(v.get("failed", 0) for v in stages.values()), errors=sum(v.get("error", 0) for v in stages.values()), skipped=sum(v.get("skipped", 0) for v in stages.values()))
        mt = pool["main_tests"] or {}
        macc = (mt.get("stages", {}).get(stage) if stage else None) or {}
        errors = macc.get("error", 0)
        lt = pool["landed_tests"] or {}
        # a stock that is drained when the build fails or main breaks: served only while neither has happened since
        main_broken = mt.get("status") == "base_broken"
        down = src == "deployed" and not pool.get("build_healthy")
        served = not down and not main_broken
        why = None if served else ("the deployed build is down" if down else "main's latest gate check failed")
        at_landing = sum(v.get("passed", 0) for k, v in lt.get("stages", {}).items() if not stage or k == stage) if lt else None
        suspect = bool(errors) or (mt.get("status") == "base_broken" and pool.get("main_commit_landed_clean"))
        if src == "main" and suspect and at_landing is not None:                 # the check that failed looks like the host, not the code: the last clean check is the level, marked stale
            out.update(stale=True, latest_check={"passed": out.get("value"), "failed": out.get("failed"), "errors": out.get("errors")}, value=at_landing, failed=0, errors=0, verification="stale: the latest check failed on a suspect host")
        if src == "deployed" and not served:                                     # what was proved at the last deploy stands; it is unverified while the build is down or main is broken
            out.update(unverified=True, verification=f"unverified: {why}")
        out.update(served=served, not_served_because=why, at_last_landing=at_landing)
        out.update(source=source, build=pool["build_id"] if src == "deployed" else None, from_run=(run or {}).get("run"), at=(run or {}).get("at"), done_tickets=sum(1 for x in tk.values() if x.state == "DONE"),
                   main_now={"passed": macc.get("passed"), "skipped": macc.get("skipped", 0), "failed": macc.get("failed", 0), "errors": errors, "run": mt.get("run"), "status": mt.get("status"),
                             "environment_suspect": bool(errors) or (mt.get("status") == "base_broken" and pool.get("main_commit_landed_clean")), "landed_clean_before": pool.get("main_commit_landed_clean")} if stage else None,
                   estimator=f"pytest summary of {('the ' + stage + ' stage') if stage else 'every stage'} in the gate run of {source}; skipped shown, never counted")
    elif kind == "staging":
        stg = pool["staging"]
        now_ = dt.datetime.now(dt.UTC).timestamp()
        healthy_at = _epoch(stg.get("last_health_at"))
        healthy = stg.get("status") == "running" and healthy_at is not None and now_ - healthy_at <= HEALTH_STALE
        out.update(value=1 if healthy else 0, status=stg.get("status"), last_healthy_ago=(now_ - healthy_at) if healthy_at is not None else None, build=pool["build_id"], deployed_at=pool["deployed_at"],
                   last_restart_at=stg.get("deployed_at") if stg.get("deployed_at") != pool["deployed_at"] else None, last_health_at=stg.get("last_health_at"),
                   estimator=f"up only when the runtime store says running and the health check answered within {HEALTH_STALE // 60} minutes; deployed at = the staging_deployed event for this build")
    elif kind == "repo_docs":
        docs = (git.get("documents") or {}).get(tuple(est.get("globs") or foundrygit.DOC_GLOBS)) or {}
        out.update(value=docs.get("count"), lines=docs.get("lines"), lessons_decided=docs.get("lessons_decided"), files=docs.get("files", []),
                   estimator=f"files matching {', '.join(est.get('globs') or [])} in the checkout, their lines, and decided lessons")
    elif kind == "turn_hours":
        t = cur["time"]
        out.update(value=round(sum(t["hours"].values()), 1), by_activity=t["hours"], turns=t["turns"], rework_share=t["rework_share"], worker_hours=t["worker_hours"], turn_limit=t["turn_limit"], losses=t["losses"],
                   estimator="turn time per day by activity (session_started to session_settled); a worker turn while a defect send-back is pending is a fix; one after a no-verdict send-back is a re-run")
    elif kind == "events":
        since = est.get("since", "")
        consumers = {c if isinstance(c, str) else c.get("agent") for c in (st.consumers or [])}
        n_in = sum(1 for e in pool["events"] if e.get("ts", "") >= since and any(_matches(e, t) for t in st.inflows))
        n_out = sum(1 for e in pool["events"] if e.get("ts", "") >= since and any(_matches(e, t) for t in st.outflows) and (not consumers or (e.get("by") or e.get("author")) in consumers))
        out.update(value=(est.get("initial") or 0) + n_in - n_out, inflow_count=n_in, outflow_count=n_out, estimator=f"{est.get('initial') or 0} + inflows − outflows since {since}" + (" (outflows only when caused by a consumer)" if consumers else ""))
    elif kind == "probe":
        ps = pool["store"].probe_state(f"model_{st.key}") if hasattr(pool["store"], "probe_state") else None
        num = None
        if ps and ps.get("output"):
            m = re.search(r"-?\d+(?:\.\d+)?", ps["output"])
            num = float(m.group()) if m else None
        out.update(value=num, probe=ps, estimator=f"the number printed by `{est.get('command')}` every {est.get('every', '1h')}")
    elif kind == "judge":
        out.update(value=None, estimable=False, reason="judge estimators need the judge agent (spec step 3)", estimator="not yet available")
    else:
        esc = cur["flows"]
        out.update(value=None, estimable=False, reason=est.get("reason", "hidden"), estimator="not estimable",
                   outflows_seen={"review": cur["inspections"]["review"]["distinct_defects"], "gate": cur["inspections"]["gate"]["distinct_defects"], "after_landing": esc.get("escape", 0)})
    if st.hidden:
        out.update(value=None, estimable=False)
    return out


def _matches(e: dict, t: str) -> bool:
    typ, _, suffix = t.partition(":")
    return e.get("type") == typ and (not suffix or suffix in (e.get("to"), e.get("status"), e.get("probe"), e.get("subject")))


def readings(project, store, events: list[dict], agents: dict, teams: dict, hours: float = 24.0, use_git: bool = True, model: dict | None = None) -> dict[str, Any]:
    """All readings for the model's stocks and flows: levels now, flows over the window, the
    same signals over the window before, and the shared instrument pool behind them."""
    from . import foundry
    model = model or foundry.load_model(project)
    now = dt.datetime.now(dt.UTC).timestamp()
    hist = History(events, store)
    tk0 = store.tickets_by_id()
    cur = _window(hist, store, events, agents, now - hours * 3600, now, tk0)
    prev = _window(hist, store, events, agents, now - 2 * hours * 3600, now - hours * 3600, tk0)
    sig_now, sig_prev = _signals(cur), _signals(prev)
    signals = {k: {"now": sig_now[k], "before": sig_prev[k], "direction": (None if sig_now[k] is None or sig_prev[k] is None else "up" if sig_now[k] > sig_prev[k] else "down" if sig_now[k] < sig_prev[k] else "flat")} for k in sig_now}
    # -- the instrument pool: git, gate runs, staging, tracker ----------------------------------
    landed_events = [e for e in events if e["type"] == "gate_landed" and e.get("commit")]
    git: dict = {}
    if use_git:
        try:
            doc_globs = [list(e.get("globs") or foundrygit.DOC_GLOBS) for st in model["stocks"] for e in st.estimators if e.get("kind") == "repo_docs"] or None
            git = foundrygit.readings(project.repo_root, project.config.base_branch, [e["commit"] for e in landed_events], doc_globs)
            git["commits_in_window"] = foundrygit.commits_since(project.repo_root, cur["since"])
        except (OSError, subprocess.SubprocessError, ValueError):   # the map must render without git
            git = {}
    sizes = git.get("landings", {})
    cutoff = now - CHURN_DAYS * 86400
    cohort = [e for e in landed_events if _ts(e) <= cutoff]
    surv = git.get("survival", {})
    added = sum((sizes.get(e["commit"]) or {}).get("added", 0) for e in cohort)
    kept = sum(surv.get(e["commit"], 0) for e in cohort)
    all_added = sum((sizes.get(e["commit"]) or {}).get("added", 0) for e in landed_events)
    all_kept = sum(surv.get(e["commit"], 0) for e in landed_events)
    win_landed = [e for e in landed_events if _ts(e) >= now - hours * 3600]
    landed = {"value": len(landed_events), "lines": all_added, "window": len(win_landed), "window_added": sum((sizes.get(e["commit"]) or {}).get("added", 0) for e in win_landed),
              "window_removed": sum((sizes.get(e["commit"]) or {}).get("removed", 0) for e in win_landed), "median_added": _median([(sizes.get(e["commit"]) or {}).get("added", 0) for e in win_landed]),
              "fcc_upper": _ratio(kept, added), "cohort": len(cohort), "churn_days": CHURN_DAYS, "survival_all": _ratio(all_kept, all_added)}
    runs = store.gate_runs()
    staging = store.runtime().get("staging") or {}
    build_id = staging.get("current_build_id")
    deployed_run = next((r for r in runs if r.get("id") == build_id), None)
    main_run = next((r for r in reversed(runs) if r.get("status") in ("landed", "base_broken")), None)
    landed_run = next((r for r in reversed(runs) if r.get("status") == "landed"), None)
    deployed_at = next((e.get("ts") for e in reversed(events) if e["type"] == "staging_deployed" and e.get("build") == build_id), None)
    tk = store.tickets_by_id()
    ahead = git.get("ahead", {})
    wip = sorted(({"ticket": t.id, "state": t.state, "commits": ahead[t.branch], "rounds": t.review_rounds or 0} for t in tk.values()
                  if t.state == "IN_PROGRESS" and getattr(t, "branch", None) and t.branch in ahead), key=lambda w: -w["commits"])
    main_commit = (main_run or {}).get("base_commit") if (main_run or {}).get("status") == "base_broken" else None
    clean_before = bool(main_commit) and any(r.get("status") == "landed" and (r.get("gate_commit") or "").startswith(main_commit[:10]) for r in runs)
    healthy_at = _epoch(staging.get("last_health_at"))
    build_healthy = staging.get("status") == "running" and healthy_at is not None and now - healthy_at <= HEALTH_STALE
    pool = {"build_healthy": build_healthy, "cur": cur, "git": git, "tickets": tk, "wip": wip, "pending": [tid for tid in tk if hist.pending_defect(tid, now)], "unresolved": [tid for tid in tk if hist.unresolved_defect(tid, now)], "awaiting_fix": [tid for tid in tk if hist.awaiting_fix(tid, now)], "returned": [tid for tid in tk if hist.returned(tid, now)], "landed": landed, "main_commit_landed_clean": clean_before,
            "deployed_tests": _run_tests(deployed_run), "main_tests": _run_tests(main_run, main=True), "landed_tests": _run_tests(landed_run), "build_id": build_id, "deployed_at": deployed_at, "staging": staging, "events": events, "store": store}
    rounds = sorted(((t.review_rounds or 0), t.id) for t in tk.values() if t.state != "CANCELLED")
    hist_r = {"0": 0, "1-2": 0, "3-5": 0, "6+": 0}
    for n, _ in rounds:
        hist_r["0" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else "6+"] += 1
    cur["time"]["turn_limit_now"] = getattr(project.config, "silence_timeout", None)
    cur["time"]["last_timeout_at"] = max((e.get("ts", "") for e in events if e["type"] == "turn_timed_out"), default=None)
    stocks = {st.key: _stock_reading(st, pool) for st in model["stocks"]}
    counter: dict[str, int] = {}
    for e in events:
        if e.get("ts", "") < cur["since"]:
            continue
        counter[e["type"]] = counter.get(e["type"], 0) + 1
        v = e.get("to") or e.get("status") or e.get("probe") or e.get("subject")
        if v:
            counter[f"{e['type']}:{v}"] = counter.get(f"{e['type']}:{v}", 0) + 1
    since_iso = cur["since"]
    cap_changes = [e for e in events if e["type"] in ("capacity_changed", "pickup_paused") and e.get("ts", "") >= since_iso]
    system_changes = sum(1 for e in cap_changes if e.get("by") not in ("operator", "supervisor"))
    operator_changes = len(cap_changes) - system_changes
    attributed = attributed_counts(events, hist, since_iso, runs)
    pf, ins_ = cur["flows"], cur["inspections"]
    pk = lambda c: attributed.get(f"orchestra|ticket_transition:REJECTED>IN_PROGRESS|cause:{c}", 0)
    edge_labels = {
        "orchestra|ticket_transition:IN_PROGRESS": f"{pf['start']} starts · {pf['replanned']} re-planned · {pf['repick']} re-picked after a restart (loss)",
        "orchestra|ticket_transition:OPEN": f"{pf['restart']} restarts (loss)",
        "orchestra|ticket_transition:IN_PROGRESS>OPEN": f"{pf['restart']} restarts (loss)",
        "worker|ticket_transition:READY_FOR_REVIEW": f"{pf['implement']} submitted · {pf['fix']} of them fixes",
        "reviewer|ticket_transition:REJECTED": f"{_n(ins_['review']['distinct_defects'], 'defect')} in {_n(pf['review'], 'rejection')}",
        "reviewer|ticket_transition:APPROVED": f"{ins_['review']['approvals']} approved",
        "orchestra|ticket_transition:REJECTED": f"{pf['review_no_verdict']} no-verdict send-backs (loss)",
        "merge_gate|gate_rejected": f"{_n(ins_['gate']['distinct_defects'], 'defect')} in {_n(pf['gate'], 'run')}",
        "merge_gate|ticket_transition:REJECTED": f"{pf['gate']} gate send-backs",
        "merge_gate|gate_landed": f"{pf['land']} landed",
        "merge_gate|staging_deployed": f"{pf['deploy']} deployed",
        "merge_gate|gate_base_broken": f"{pf['base']} base broken",
        "worker|ticket_transition:BLOCKED": f"{pf['blocked']} blocked",
        "orchestra|staging_restarted": f"{attributed.get('orchestra|staging_restarted', 0)} restarts (crash proxy)",
        "orchestra|ticket_transition:OPEN>IN_PROGRESS": f"{pf['start']} starts · {pf['replanned']} re-planned · {pf['repick']} re-picked after a restart (loss)",
        "orchestra|ticket_transition:REJECTED>IN_PROGRESS": f"{attributed.get('orchestra|ticket_transition:REJECTED>IN_PROGRESS', 0)} fix pickups",
        "worker|ticket_transition:READY_FOR_REVIEW|known_rework": f"{pf['fix']} fix rounds · {cur['rounds']['bad_fixes']} later found bad",
        "worker|ticket_transition:READY_FOR_REVIEW|undiscovered": f"{pf['implement']} submitted (an unknown share carries a defect)",
        "worker|ticket_transition:IN_PROGRESS>READY_FOR_REVIEW|wip": f"{pf['implement']} submitted · {pf['fix']} of them fixes",
        "orchestra|ticket_transition:REJECTED>IN_PROGRESS": f"{pk('defect') + pk('gate')} fix pickups · {pk('no_verdict')} re-picks after no-verdict reviews · {pk('lost') + pk('conflict')} after lost runs or conflicts (losses)",
        "orchestra|ticket_transition:REJECTED>IN_PROGRESS|known_rework": f"{pk('defect') + pk('gate')} fix pickups",
        "orchestra|ticket_transition:REJECTED>IN_PROGRESS|returned": f"{pk('no_verdict') + pk('lost') + pk('conflict')} re-picks (loss)",
        "reviewer|ticket_transition:IN_REVIEW>REJECTED|returned": f"{pf['review_no_verdict']} reviews with no verdict (loss)",
        "reviewer|ticket_transition:REJECTED|returned": f"{pf['review_no_verdict']} reviews with no verdict (loss)",
        "merge_gate|gate_rejected|returned": f"{pf['failure']} lost gate runs (loss)",
        "merge_gate|gate_conflict|returned": f"{pf['conflict']} conflicts",
        "coordinator|ticket_transition:BLOCKED>OPEN": f"{attributed.get('coordinator|ticket_transition:BLOCKED>OPEN', 0)} re-planned",
    }
    t = cur["time"]
    return {"hours": hours, "model_source": model.get("source"), "stocks": stocks, "event_counts": counter, "attributed_counts": attributed, "edge_labels": edge_labels, "pipeline": cur["flows"], "inspections": cur["inspections"], "pipeline_paused_since": cur.get("pipeline_paused_since"),
            "system_capacity_changes": system_changes, "operator_capacity_changes": operator_changes,
            "rounds": {"histogram": hist_r, "worst": [{"ticket": tid, "rounds": n} for n, tid in rounds[-3:] if n > 0][::-1], **cur["rounds"]},
            "time": t, "dora": cur["dora"], "losses": t["losses"], "counts": cur["counts"], "pairs": cur["pairs"], "signals": signals,
            "window": {"since": cur["since"], "until": cur["until"], "before": {"since": prev["since"], "until": prev["until"]}}, "git": bool(git)}
