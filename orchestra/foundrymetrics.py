"""The foundry's readings: what the log, the store, and the repository say about each stock
and flow in `foundry`, over a window. Everything is a count, a ratio, or a time taken from
data; each reading carries the estimator that produced it so the page can state it.

Send-backs are split by what the data can tell today: a gate run that failed on its own
result is a defect, a timeout or start failure is a machine failure, a conflict is a
conflict. A review rejection cannot yet be told from a reviewer that produced no verdict
(the `cause` field is step 2 of the spec), so review send-backs are labelled "all"."""

from __future__ import annotations

import datetime as dt
import re
import statistics
from typing import Any

from . import foundrygit
from .loopmetrics import _ts, window

CHURN_DAYS = 14
PLAN_ROLES = {"coordinator", "supervisor", "pipeline_manager"}
GATE_TIMEOUT_RC = 124


def _median(xs):
    return statistics.median(xs) if xs else None


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).isoformat(timespec="seconds")


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
    out = {}
    for n, word in re.findall(r"(\d+) (passed|failed|skipped|error|errors|xfailed)", tail or ""):
        out[word.rstrip("s") if word != "passed" else "passed"] = out.get(word, 0) + int(n)
    return out


def gate_outcomes(runs: list[dict]) -> dict:
    """Every gate run by what ended it: landed, a defect at a stage, a timeout, a start
    failure, a conflict, a broken base, or an error."""
    by: dict[str, int] = {}
    stages: dict[str, int] = {}
    for r in runs:
        st = r.get("status")
        if st in ("landed", "conflict", "base_broken", "error"):
            by[st] = by.get(st, 0) + 1
            continue
        failed = next((s for s in r.get("stages") or [] if s.get("status") not in ("passed", None)), None)
        if failed is None or failed.get("stage") == "start" or failed.get("name") == "target":
            key = "start_failure"
        elif str(failed.get("returncode")) == str(GATE_TIMEOUT_RC):
            key = "timeout"
        else:
            key = "defect"
            stages[failed.get("name") or failed.get("stage") or "?"] = stages.get(failed.get("name") or failed.get("stage") or "?", 0) + 1
        by[key] = by.get(key, 0) + 1
    own = by.get("landed", 0) + by.get("defect", 0)
    return {"by": by, "defect_stage": stages, "runs": len(runs), "own_result": own,
            "pass": round(by.get("landed", 0) / own, 2) if own else None}


def main_tests(runs: list[dict]) -> dict | None:
    """Tests on main by stage, from the last run whose stages reflect main."""
    for r in reversed(runs):
        if r.get("status") not in ("landed", "base_broken"):
            continue
        out = {}
        for s in r.get("stages") or []:
            if "pytest" in (s.get("command") or ""):
                out[s.get("name") or s.get("stage")] = {**_pytest_tail(s.get("tail", "")), "status": s.get("status")}
        if out:
            return {"run": r.get("id"), "at": r.get("finished_at"), "stages": out, "commit": r.get("gate_commit") or r.get("base_commit")}
    return None


def _activity(kind: str, agents: dict, teams: dict) -> str:
    if kind in ("worker", "reviewer"):
        return kind
    if kind in PLAN_ROLES:
        return "plan"
    ag = agents.get(kind)
    if ag is not None and ag.team:
        return ag.team.split("/")[0]
    return "other"


def readings(project, store, events: list[dict], agents: dict, teams: dict, hours: float = 24.0, use_git: bool = True) -> dict[str, Any]:
    """All readings over the window. `events` is the whole log; the window is applied here
    because some readings (rounds per ticket, survival) need history."""
    evs = window(events, hours)
    days = max(hours / 24.0, 1e-9)
    counts: dict[str, int] = {}
    per_ticket: dict[str, list[tuple[float, str, str]]] = {}
    created: dict[str, float] = {}
    for e in evs:
        t = e["type"]
        counts[t] = counts.get(t, 0) + 1
        if t == "ticket_transition" and e.get("ticket"):
            per_ticket.setdefault(e["ticket"], []).append((_ts(e), e.get("from") or "", e["to"]))
        if t == "ticket_created" and e.get("ticket"):
            created[e["ticket"]] = _ts(e)
    for seq in per_ticket.values():
        seq.sort()
    pairs: dict[str, int] = {}
    for seq in per_ticket.values():
        for _, f, to in seq:
            pairs[f"{f}>{to}"] = pairs.get(f"{f}>{to}", 0) + 1

    # -- inspections -----------------------------------------------------------------
    ready = pairs.get("IN_PROGRESS>READY_FOR_REVIEW", 0) + pairs.get("IN_REVIEW>READY_FOR_REVIEW", 0)
    review_back = pairs.get("IN_REVIEW>REJECTED", 0)
    tickets_reviewed = {t for t, seq in per_ticket.items() if any(to == "READY_FOR_REVIEW" for _, _, to in seq)}
    tickets_back = {t for t, seq in per_ticket.items() if any(f == "IN_REVIEW" and to == "REJECTED" for _, f, to in seq)}
    runs = [r for r in store.gate_runs() if (r.get("started_at") or "") >= (dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)).isoformat(timespec="seconds")]
    gate = gate_outcomes(runs)
    inspections = {
        "review": {"arrivals": ready, "sent_back": review_back, "pass": round(1 - review_back / ready, 2) if ready else None,
                   "tickets": len(tickets_reviewed), "tickets_sent_back": len(tickets_back),
                   "pass_per_ticket": round(1 - len(tickets_back) / len(tickets_reviewed), 2) if tickets_reviewed else None,
                   "cause": "all send-backs; no-verdict and timeout send-backs are not yet told apart (spec step 2)"},
        "gate": {**gate, "cause": "defect = a stage failed on its own result; timeouts, start failures and conflicts counted apart"},
    }

    # -- rounds per ticket and bad fixes (all time, from the tracker) ------------------
    rounds = sorted(((t.review_rounds or 0), t.id) for t in store.tickets_by_id().values())
    hist = {"0": 0, "1-2": 0, "3-5": 0, "6+": 0}
    for n, _ in rounds:
        hist["0" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else "6+"] += 1
    worst = [{"ticket": tid, "rounds": n} for n, tid in rounds[-3:] if n > 0][::-1]
    bad_fix = 0
    fixes = 0
    for seq in per_ticket.values():
        pending = False
        for _, f, to in seq:
            if to == "REJECTED":
                if pending:
                    bad_fix += 1
                pending = True
            elif pending and to == "READY_FOR_REVIEW":
                fixes += 1
            elif to in ("DONE", "APPROVED", "MERGING"):
                pending = False

    # -- sessions: agent time by activity, losses ----------------------------------------
    # A turn's active time is from its session_started to the next session_settled of the
    # same session; a turn still running counts up to now. Resident agents idle between
    # turns are therefore not counted as working.
    now = dt.datetime.now(dt.UTC).timestamp()
    since = now - hours * 3600
    kinds = {s.get("id"): s.get("kind") for s in [*store.sessions(), *store.runtime().get("archived_sessions", {}).values()]}
    open_turns: dict[str, tuple[float, str, str]] = {}
    turns: list[tuple[str, str, float, float]] = []      # session, kind, start, end
    for e in evs:
        sid = e.get("session")
        if e["type"] == "session_started" and sid:
            open_turns[sid] = (_ts(e), e.get("kind") or kinds.get(sid) or "", e.get("ticket") or "")
        elif e["type"] == "session_settled" and sid in open_turns:
            st, kind, tid = open_turns.pop(sid)
            turns.append((sid, kind, st, _ts(e)))
    for sid, (st, kind, tid) in open_turns.items():
        turns.append((sid, kind, st, now))
    by_activity: dict[str, float] = {}
    turn_count: dict[str, int] = {}
    timeouts = [(e.get("session"), _ts(e)) for e in evs if e["type"] == "turn_timed_out"]
    lost_hours = 0.0
    lost_all = 0.0
    for sid, kind, st, en in turns:
        dur = max(0.0, en - st) / 3600
        act = _activity(kind, agents, teams)
        if act == "worker":
            tid = sid.split("-", 1)[1] if sid.startswith("worker-") else ""
            seq = per_ticket.get(tid, [])
            before = [(f, to) for ts, f, to in seq if ts <= st + 5]
            act = "fix" if before and before[-1] == ("REJECTED", "IN_PROGRESS") else "implement"
        by_activity[act] = by_activity.get(act, 0.0) + dur
        turn_count[act] = turn_count.get(act, 0) + 1
        if any(ts_sid == sid and st <= ts <= en + 5 for ts_sid, ts in timeouts):
            lost_all += dur
            if act in ("implement", "fix"):
                lost_hours += dur
    worker_hours = by_activity.get("implement", 0.0) + by_activity.get("fix", 0.0)
    losses = {"restarts": pairs.get("IN_PROGRESS>OPEN", 0), "turn_timeouts": counts.get("turn_timed_out", 0), "turn_errors": counts.get("turn_error", 0),
              "compactions": counts.get("agent_compacted", 0), "resets": counts.get("agent_reset", 0), "crashes": counts.get("agent_crashed", 0),
              "worker_hours_ending_in_timeout": round(lost_hours / days, 1), "hours_ending_in_timeout": round(lost_all / days, 1)}

    # -- landed, deployed, really done ---------------------------------------------------
    landed_events = [e for e in events if e["type"] == "gate_landed" and e.get("commit")]
    landed_window = [e for e in landed_events if e in evs or e.get("ts", "") >= _iso(since)]
    git = {}
    if use_git:
        try:
            git = foundrygit.readings(project.repo_root, project.config.base_branch, [e["commit"] for e in landed_events])
        except Exception:                       # the map must render without git
            git = {}
    sizes = [git.get("landings", {}).get(e["commit"]) for e in landed_window]
    sizes = [s for s in sizes if s]
    cutoff = now - CHURN_DAYS * 86400
    cohort = [e for e in landed_events if _ts(e) <= cutoff]
    surv = git.get("survival", {})
    added = sum((git.get("landings", {}).get(e["commit"]) or {}).get("added", 0) for e in cohort)
    kept = sum(surv.get(e["commit"], 0) for e in cohort)
    all_added = sum((git.get("landings", {}).get(e["commit"]) or {}).get("added", 0) for e in landed_events)
    all_kept = sum(surv.get(e["commit"], 0) for e in landed_events)
    landed = {"count": len(landed_window), "per_day": round(len(landed_window) / days, 1), "median_added": _median([s["added"] for s in sizes]),
              "added": sum(s["added"] for s in sizes), "removed": sum(s["removed"] for s in sizes),
              "fcc_upper": round(kept / added, 2) if added else None, "cohort": len(cohort), "churn_days": CHURN_DAYS,
              "survival_all": round(all_kept / all_added, 2) if all_added else None, "landings_all": len(landed_events)}
    tests = main_tests(store.gate_runs())
    acc = (tests or {}).get("stages", {}).get("acceptance") or {}
    really = {"passing": acc.get("passed"), "skipped": acc.get("skipped", 0), "failed": acc.get("failed", 0),
              "done_tickets": sum(1 for t in store.tickets_by_id().values() if t.state == "DONE"), "from_run": (tests or {}).get("run"), "at": (tests or {}).get("at")}

    # -- DORA, post-deploy only -------------------------------------------------------------
    deploys = sorted((e for e in evs if e["type"] == "staging_deployed"), key=_ts)
    troubles = sorted((e for e in evs if e["type"] in ("staging_failed", "staging_restarted")), key=_ts)
    failed_deploys = 0
    for i, d in enumerate(deploys):
        nxt = _ts(deploys[i + 1]) if i + 1 < len(deploys) else now
        if any(_ts(d) < _ts(t) < nxt for t in troubles):
            failed_deploys += 1
    restores = []
    for t in troubles:
        if t["type"] != "staging_failed":
            continue
        nxt = next((d for d in deploys if _ts(d) > _ts(t)), None)
        if nxt:
            restores.append(_ts(nxt) - _ts(t))
    leads = []
    for tid, seq in per_ticket.items():
        done = next((ts for ts, _, to in seq if to == "DONE"), None)
        if done is not None and tid in created:
            leads.append(done - created[tid])
    landed_by_commit = {e["commit"]: _ts(e) for e in landed_events}
    commit_to_deploy = [_ts(d) - landed_by_commit[d["commit"]] for d in deploys if d.get("commit") in landed_by_commit]
    dora = {"landing_per_day": landed["per_day"], "lead_time": _median(leads), "land_to_deploy": _median(commit_to_deploy),
            "deploys": len(deploys), "deploys_troubled": failed_deploys, "change_failure": round(failed_deploys / len(deploys), 2) if deploys else None,
            "restarts": sum(1 for t in troubles if t["type"] == "staging_restarted"), "staging_failed": sum(1 for t in troubles if t["type"] == "staging_failed"),
            "restore": _median(restores)}

    # -- stocks now ------------------------------------------------------------------------
    tk = store.tickets_by_id()
    ahead = git.get("ahead", {})
    wip = []
    for t in tk.values():
        if t.state in ("DONE", "CANCELLED") or not getattr(t, "branch", None):
            continue
        n = ahead.get(t.branch)
        if n is not None:
            wip.append({"ticket": t.id, "state": t.state, "commits": n})
    wip.sort(key=lambda w: -w["commits"])
    staging = store.runtime().get("staging") or {}
    docs = git.get("documents") or {}
    stocks = {
        "D": {"value": sum(1 for t in tk.values() if t.state in ("OPEN", "BLOCKED")), "estimator": "OPEN and BLOCKED tickets in the tracker now"},
        "W": {"value": sum(w["commits"] for w in wip), "tickets": len(wip), "detail": wip, "by_state": sum(1 for t in tk.values() if t.state in ("IN_PROGRESS", "READY_FOR_REVIEW", "IN_REVIEW", "REJECTED", "APPROVED", "MERGING")),
              "estimator": "commits ahead of main on each open ticket's branch (git rev-list); tickets in a working state shown beside it"},
        "K": {"value": sum(1 for t in tk.values() if t.state == "REJECTED"), "estimator": "tickets in REJECTED now"},
        "U": {"value": None, "estimable": False, "reason": "no post-landing discovery series yet: 0 staging failures and no bug tickets citing a landed commit in the window; the review's cycle time is not a discovery delay",
              "estimator": "not estimable"},
        "L": {"value": landed["count"], "estimator": f"gate_landed in {hours:g}h; size by first-parent diff", **landed},
        "A": {"value": really["passing"], "estimator": "acceptance tests passed in the last gate run that reflects main; skipped shown, never counted", **really},
        "B": {"value": 1 if staging.get("status") == "running" else 0, "build": staging.get("current_build_id"), "deployed_at": staging.get("deployed_at"),
              "last_health_at": staging.get("last_health_at"), "estimator": "the staging process state in the runtime store"},
        "T": {"value": sum(v.get("passed", 0) for v in (tests or {}).get("stages", {}).values()) if tests else None, "stages": (tests or {}).get("stages"),
              "estimator": "pytest summaries per stage of the last gate run that reflects main"},
        "R": {"value": docs.get("count"), "lines": docs.get("lines"), "lessons_decided": docs.get("lessons_decided"), "files": docs.get("files", []),
              "estimator": "agent-facing documents in the checkout: AGENTS.md, README, team and role docs, decided lessons"},
        "C": {"value": round(sum(by_activity.values()) / days, 1), "by_activity": {k: round(v / days, 1) for k, v in sorted(by_activity.items(), key=lambda kv: -kv[1])}, "turns": turn_count,
              "rework_share": round(by_activity.get("fix", 0.0) / worker_hours, 2) if worker_hours else None, "losses": losses,
              "estimator": "turn time per day by activity (session_started to session_settled); a worker turn on a ticket just returned from REJECTED is a fix"},
    }
    flows = {"start": pairs.get("OPEN>IN_PROGRESS", 0), "implement": ready, "review": review_back, "gate": gate["by"].get("defect", 0),
             "conflict": gate["by"].get("conflict", 0), "failure": gate["by"].get("timeout", 0) + gate["by"].get("start_failure", 0) + gate["by"].get("error", 0),
             "escape": dora["staging_failed"] + dora["restarts"], "fix": pairs.get("REJECTED>IN_PROGRESS", 0), "land": landed["count"], "deploy": len(deploys),
             "verify": len([r for r in runs if r.get("status") == "landed"]), "tests": None, "improve": None, "base": gate["by"].get("base_broken", 0), "precheck": None}
    return {"hours": hours, "stocks": stocks, "flows": flows, "inspections": inspections, "rounds": {"histogram": hist, "worst": worst, "bad_fixes": bad_fix, "fixes": fixes},
            "dora": dora, "losses": losses, "counts": counts, "git": bool(git)}
