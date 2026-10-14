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
PLAN_ROLES = {"coordinator", "supervisor", "pipeline_manager"}
GATE_TIMEOUT_RC = 124
NOTE_SLACK = 180          # seconds between a reviewer's verdict note and the transition it caused
MAX_LOG_BYTES = 2_000_000


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
            elif to == "READY_FOR_REVIEW" and frm == "IN_PROGRESS" or to in ("DONE", "CANCELLED"):
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
    return {"by": by, "defect_stage": stages, "defect_tickets": tickets, "defect_tests": tests, "distinct_defects": len(tests) or len(tickets), "runs": len(runs), "own_result": own,
            "pass": _ratio(by.get("landed", 0), own)}


def _run_tests(run: dict | None) -> dict | None:
    if not run:
        return None
    out = {}
    for s in run.get("stages") or []:
        if "pytest" in (s.get("command") or ""):
            out[s.get("name") or s.get("stage")] = {**_pytest_tail(s.get("tail", "")), "status": s.get("status")}
    return {"run": run.get("id"), "at": run.get("finished_at"), "status": run.get("status"), "stages": out} if out else None


def _window(hist: History, store, events: list[dict], agents: dict, since: float, until: float) -> dict[str, Any]:
    """The flow readings for one window [since, until)."""
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
    starts = repicks = 0
    for tid, ts, f, to in tr:
        if (f, to) != ("OPEN", "IN_PROGRESS"):
            continue
        if hist.previous(tid, ts, f, to) in (("IN_PROGRESS", "OPEN"), ("BLOCKED", "OPEN")):
            repicks += 1
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
        if (f, to) != ("IN_PROGRESS", "READY_FOR_REVIEW") or not hist.pending_defect(tid, ts - 1):
            continue
        fix_rounds += 1
        nxt = next(((t2, to2) for t2, f2, to2 in hist.seq.get(tid, []) if t2 > ts and to2 in ("REJECTED", "APPROVED", "DONE")), None)
        if nxt and nxt[1] == "REJECTED" and hist.cause.get((tid, nxt[0])) in ("defect", "gate"):
            bad += 1
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
            if hist.pending_defect(tid, st + 5):
                act = "fix"
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
    worker_hours = hours.get("implement", 0.0) + hours.get("fix", 0.0) + hours.get("rerun", 0.0)
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
    restores = []
    for t in troubles:
        if t["type"] == "staging_failed":
            nxt = next((d for d in deploys if _ts(d) > _ts(t)), None)
            if nxt:
                restores.append(_ts(nxt) - _ts(t))
    leads = [ts - hist.created[tid] for tid, ts, _, to in tr if to == "DONE" and tid in hist.created]
    landed_at = {e.get("commit"): _ts(e) for e in landed}
    land_to_deploy = [_ts(d) - landed_at[d["commit"]] for d in deploys if d.get("commit") in landed_at]
    return {
        "since": dt.datetime.fromtimestamp(since, dt.UTC).isoformat(timespec="seconds"), "until": dt.datetime.fromtimestamp(until, dt.UTC).isoformat(timespec="seconds"), "days": days,
        "counts": counts, "pairs": pairs,
        "flows": {"start": starts, "repick": repicks, "implement": arrivals, "redo": redo, "review": rev_defects, "review_no_verdict": rev_cause.get("no_verdict", 0),
                  "gate": gate["by"].get("defect", 0), "conflict": gate["by"].get("conflict", 0),
                  "failure": gate["by"].get("timeout", 0) + gate["by"].get("start_failure", 0) + gate["by"].get("error", 0),
                  "escape": 0, "fix": fix_rounds, "land": len(landed), "deploy": len(deploys), "verify": sum(1 for r in runs if r.get("status") == "landed"),
                  "base": gate["by"].get("base_broken", 0), "restart": pairs.get("IN_PROGRESS>OPEN", 0), "blocked": pairs.get("IN_PROGRESS>BLOCKED", 0)},
        "inspections": {
            "review": {"arrivals": arrivals, "redo": redo, "approvals": approvals, "verdicts": verdicts, "by_cause": rev_cause, "defects": rev_defects, "distinct_defects": len(tickets_defect),
                       "pass": _ratio(approvals, verdicts), "tickets": len(tickets_reviewed), "tickets_sent_back": len(tickets_defect), "pass_per_ticket": _ratio(len(tickets_reviewed - tickets_defect), len(tickets_reviewed)),
                       "cause": "pass = APPROVED verdicts over all verdicts (APPROVED + REJECTED with a reviewer note); reviews with no verdict are not inspections and are counted as losses"},
            "gate": {**gate, "cause": "defect = a stage failed on its own result; timeouts, start failures and conflicts counted apart"},
        },
        "rounds": {"fix_rounds": fix_rounds, "bad_fixes": bad, "bad_fix_fraction": _ratio(bad, fix_rounds), "lead_values": sorted(leads)},
        "time": {"hours": {k: round(v / days, 1) for k, v in sorted(hours.items(), key=lambda kv: -kv[1])}, "turns": nturns,
                 "rework_share": _ratio(hours.get("fix", 0.0), worker_hours), "worker_hours": round(worker_hours / days, 1),
                 "turn_limit": max(set(limits), key=limits.count) if limits else None,
                 "timeout_share": {k: _ratio(timed_out.get(k, 0), n) for k, n in turns_by_kind.items()}, "timed_out": timed_out, "turns_by_kind": turns_by_kind,
                 "losses": {"restarts": pairs.get("IN_PROGRESS>OPEN", 0), "repicks": repicks, "turn_timeouts": counts.get("turn_timed_out", 0), "turn_errors": counts.get("turn_error", 0),
                            "compactions": counts.get("agent_compacted", 0), "resets": counts.get("agent_reset", 0), "crashes": counts.get("agent_crashed", 0),
                            "review_no_verdict": rev_cause.get("no_verdict", 0), "review_redo": redo, "gate_lost": gate["by"].get("timeout", 0) + gate["by"].get("start_failure", 0),
                            "rerun_hours": round(hours.get("rerun", 0.0) / days, 1), "worker_hours_ending_in_timeout": round(lost_worker / days, 1), "hours_ending_in_timeout": round(lost_all / days, 1)}},
        "dora": {"landing_per_day": round(len(landed) / days, 1), "lead_time": _median(leads), "lead_n": len(leads), "land_to_deploy": _median(land_to_deploy),
                 "deploys": len(deploys), "deploys_troubled": troubled, "change_failure": _ratio(troubled, len(deploys)),
                 "restarts": sum(1 for t in troubles if t["type"] == "staging_restarted"), "staging_failed": sum(1 for t in troubles if t["type"] == "staging_failed"), "restore": _median(restores)},
    }


def _signals(w: dict) -> dict[str, float | None]:
    """The loop signals as plain numbers, for direction between windows."""
    t, f, g = w["time"], w["flows"], w["inspections"]["gate"]
    wh = t["worker_hours"] or 0.0
    return {"review_pass": w["inspections"]["review"]["pass"], "gate_defects": f["gate"], "gate_distinct_defects": w["inspections"]["gate"]["distinct_defects"], "gate_pass": g["pass"], "rework_share": t["rework_share"],
            "worker_timeout_share": t["timeout_share"].get("worker"), "reviewer_timeout_share": t["timeout_share"].get("reviewer"), "hours_lost": t["losses"]["hours_ending_in_timeout"],
            "defects_before_gate_share": _ratio(w["inspections"]["review"]["distinct_defects"], w["inspections"]["review"]["distinct_defects"] + w["inspections"]["gate"]["distinct_defects"]),
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
        out.update(value=sum(1 for x in tk.values() if x.state in states), by_state={s_: sum(1 for x in tk.values() if x.state == s_) for s_ in states},
                   estimator=f"tickets in {', '.join(states)} in the tracker now")
    elif kind == "pending_defects":
        pend = pool["pending"]
        out.update(value=len(pend), tickets=pend, estimator="tickets sent back for a defect (reviewer verdict or gate result) and not yet re-submitted, whatever their state now")
    elif kind == "git_ahead":
        wip = pool["wip"]
        out.update(value=sum(w["commits"] for w in wip), tickets=len(wip), detail=wip, commits_per_day=git.get("commits_in_window"),
                   estimator="commits ahead of main on each open ticket's branch (git rev-list), and commits made on any branch in the window")
    elif kind == "landed":
        out.update(**pool["landed"], estimator="every gate_landed commit on main; lines by first-parent diff; survival by first-parent blame")
    elif kind == "gate_tests":
        src = est.get("source", "main")
        run = pool["deployed_tests"] if src == "deployed" and pool["deployed_tests"] else pool["main_tests"]
        source = "deployed build" if src == "deployed" and pool["deployed_tests"] else ("main's latest run (nothing deployed)" if src == "deployed" else "main's latest run")
        stage = est.get("stage")
        stages = (run or {}).get("stages", {})
        if stage:
            sg = stages.get(stage) or {}
            out.update(value=sg.get("passed"), skipped=sg.get("skipped", 0), failed=sg.get("failed", 0), stage=stage)
        else:
            out.update(value=sum(v.get("passed", 0) for v in stages.values()) if run else None, stages=stages)
        mt = pool["main_tests"] or {}
        macc = (mt.get("stages", {}).get(stage) if stage else None) or {}
        out.update(source=source, build=pool["build_id"] if src == "deployed" else None, from_run=(run or {}).get("run"), at=(run or {}).get("at"), done_tickets=sum(1 for x in tk.values() if x.state == "DONE"),
                   main_now={"passed": macc.get("passed"), "skipped": macc.get("skipped", 0), "failed": macc.get("failed", 0), "run": mt.get("run"), "status": mt.get("status")} if stage else None,
                   estimator=f"pytest summary of the {stage or 'all'} stage{'s' if not stage else ''} in the gate run that produced the {source}; skipped shown, never counted")
    elif kind == "staging":
        stg = pool["staging"]
        out.update(value=1 if stg.get("status") == "running" else 0, build=pool["build_id"], deployed_at=pool["deployed_at"],
                   last_restart_at=stg.get("deployed_at") if stg.get("deployed_at") != pool["deployed_at"] else None, last_health_at=stg.get("last_health_at"),
                   estimator="the staging process state in the runtime store; deployed at = the staging_deployed event for this build")
    elif kind == "repo_docs":
        docs = git.get("documents") or {}
        out.update(value=docs.get("count"), lines=docs.get("lines"), lessons_decided=docs.get("lessons_decided"), files=docs.get("files", []),
                   estimator=f"files matching {', '.join(est.get('globs') or [])} in the checkout, their lines, and decided lessons")
    elif kind == "turn_hours":
        t = cur["time"]
        out.update(value=round(sum(t["hours"].values()), 1), by_activity=t["hours"], turns=t["turns"], rework_share=t["rework_share"], worker_hours=t["worker_hours"], turn_limit=t["turn_limit"], losses=t["losses"],
                   estimator="turn time per day by activity (session_started to session_settled); a worker turn while a defect send-back is pending is a fix; one after a no-verdict send-back is a re-run")
    elif kind == "events":
        since = est.get("since", "")
        n_in = sum(1 for e in pool["events"] if e.get("ts", "") >= since and any(_matches(e, t) for t in st.inflows))
        n_out = sum(1 for e in pool["events"] if e.get("ts", "") >= since and any(_matches(e, t) for t in st.outflows))
        out.update(value=(est.get("initial") or 0) + n_in - n_out, inflow_count=n_in, outflow_count=n_out, estimator=f"{est.get('initial') or 0} + inflows − outflows since {since}")
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
        out.update(value=None, estimable=False, reason=est.get("reason", "hidden"), estimator="not estimable")
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
    cur = _window(hist, store, events, agents, now - hours * 3600, now)
    prev = _window(hist, store, events, agents, now - 2 * hours * 3600, now - hours * 3600)
    sig_now, sig_prev = _signals(cur), _signals(prev)
    signals = {k: {"now": sig_now[k], "before": sig_prev[k], "direction": (None if sig_now[k] is None or sig_prev[k] is None else "up" if sig_now[k] > sig_prev[k] else "down" if sig_now[k] < sig_prev[k] else "flat")} for k in sig_now}
    # -- the instrument pool: git, gate runs, staging, tracker ----------------------------------
    landed_events = [e for e in events if e["type"] == "gate_landed" and e.get("commit")]
    git: dict = {}
    if use_git:
        try:
            git = foundrygit.readings(project.repo_root, project.config.base_branch, [e["commit"] for e in landed_events])
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
    deployed_at = next((e.get("ts") for e in reversed(events) if e["type"] == "staging_deployed" and e.get("build") == build_id), None)
    tk = store.tickets_by_id()
    ahead = git.get("ahead", {})
    wip = sorted(({"ticket": t.id, "state": t.state, "commits": ahead[t.branch], "rounds": t.review_rounds or 0} for t in tk.values()
                  if t.state not in ("DONE", "CANCELLED") and getattr(t, "branch", None) and t.branch in ahead), key=lambda w: -w["commits"])
    pool = {"cur": cur, "git": git, "tickets": tk, "wip": wip, "pending": [tid for tid in tk if hist.pending_defect(tid, now)], "landed": landed,
            "deployed_tests": _run_tests(deployed_run), "main_tests": _run_tests(main_run), "build_id": build_id, "deployed_at": deployed_at, "staging": staging, "events": events, "store": store}
    rounds = sorted(((t.review_rounds or 0), t.id) for t in tk.values())
    hist_r = {"0": 0, "1-2": 0, "3-5": 0, "6+": 0}
    for n, _ in rounds:
        hist_r["0" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else "6+"] += 1
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
    system_changes = sum(1 for e in events if e["type"] in ("capacity_changed", "pickup_paused") and e.get("ts", "") >= since_iso and e.get("by") not in ("operator", "supervisor"))
    t = cur["time"]
    return {"hours": hours, "model_source": model.get("source"), "stocks": stocks, "event_counts": counter, "pipeline": cur["flows"], "inspections": cur["inspections"], "system_capacity_changes": system_changes,
            "rounds": {"histogram": hist_r, "worst": [{"ticket": tid, "rounds": n} for n, tid in rounds[-3:] if n > 0][::-1], **cur["rounds"]},
            "time": t, "dora": cur["dora"], "losses": t["losses"], "counts": cur["counts"], "pairs": cur["pairs"], "signals": signals,
            "window": {"since": cur["since"], "until": cur["until"], "before": {"since": prev["since"], "until": prev["until"]}}, "git": bool(git)}
