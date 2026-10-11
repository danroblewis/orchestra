"""The orchestration loop: slots, ticks, workers, reviewers, gate, wake-ups. SPEC.md section 6."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from . import agents
from .config import Project
from .events import Events
from .gate import run_gate, run_specs
from .git import Git, GitError
from .model import ACTIVE, RECOVERY, Note, State, Ticket, is_ready
from .pi import PiProcess
from .store import Conflict, LocalStore, StoreError

PROJECT_AGENTS = ("coordinator", "pipeline_manager")


def log(msg: str) -> None:
    print(f"[orchestra {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Loop:
    def __init__(self, project: Project, store: LocalStore, events: Events):
        self.project = project
        self.store = store
        self.events = events
        self.git = Git(project.repo_root)
        self.cfg = project.config
        self.workers: dict[str, threading.Thread] = {}
        self.reviewers: dict[str, threading.Thread] = {}
        self.gate_thread: threading.Thread | None = None
        self.agent_threads: dict[str, threading.Thread] = {}
        self.agent_procs: dict[str, PiProcess] = {}
        self.stop = threading.Event()

    # -- lifecycle -------------------------------------------------------------

    def recover(self) -> None:
        for t in self.store.list_tickets():
            if t.state in ACTIVE:
                self.store.transition(t.id, t.version, RECOVERY[t.state])
                log(f"recovered {t.id}: {t.state} -> {RECOVERY[t.state]}")
        for s in self.store.sessions():
            if s.get("status") == "running":
                self.store.set_session(s["id"], status="idle")
        for p in self.project.gate_dir.glob("*"):
            self.git.worktree_remove(p)
        self.git.run("worktree", "prune", check=False)
        for b in self.git.run("branch", "--list", "orchestra/gate-*", check=False).stdout.split():
            self.git.branch_delete(b.strip("* "))

    def run(self, once: bool = False) -> None:
        self.recover()
        self.events.emit("loop_started")
        log(f"project {self.project.key} on {self.project.repo_root}; workers={self.cfg.workers} reviewers={self.cfg.reviewers}")
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception as e:  # keep the loop alive
                    log(f"tick error: {e!r}")
                if once and not self._busy():
                    break
                time.sleep(3)
        finally:
            for p in self.agent_procs.values():
                p.close()
            self.events.emit("loop_stopped")

    def _busy(self) -> bool:
        return any(t.is_alive() for t in [*self.workers.values(), *self.reviewers.values(),
                                           *self.agent_threads.values(), self.gate_thread] if t)

    # -- tick ------------------------------------------------------------------

    def tick(self) -> None:
        self.project.reload_config()
        self.cfg = self.project.config
        self._reap()
        tickets = self.store.tickets_by_id()
        milestones = self.store.milestones_by_id()
        ordered = sorted(tickets.values(), key=lambda t: (t.priority, t.state_since, t.id))

        # Review before pick: finished work lands before new work starts.
        for t in ordered:
            if t.state == State.READY_FOR_REVIEW and len(self.reviewers) < self.cfg.reviewers and t.id not in self.reviewers:
                self._spawn(self.reviewers, t.id, self._review, t)
        for t in ordered:
            if len(self.workers) >= self.cfg.workers:
                break
            if t.id in self.workers:
                continue
            if t.state == State.REJECTED or (t.state == State.OPEN and is_ready(t, tickets, milestones)):
                self._spawn(self.workers, t.id, self._work, t)
        if self.gate_thread is None and not self.store.pipeline().get("paused"):
            approved = [t for t in ordered if t.state == State.APPROVED]
            if approved:
                approved.sort(key=lambda t: t.state_since)
                self.gate_thread = threading.Thread(target=self._gate, args=([approved[0].id],), daemon=True)
                self.gate_thread.start()
        for t in ordered:
            if t.state == State.CANCELLED and self.store.worktree(t.id):
                self._drop_worktree(t)
        for target in PROJECT_AGENTS:
            if target not in self.agent_threads:
                reasons = [w["reason"] for w in self.store.drain_wakeups(target)]
                if reasons:
                    self._spawn(self.agent_threads, target, self._wake, target, reasons)

    def _reap(self) -> None:
        for d in (self.workers, self.reviewers, self.agent_threads):
            for k in [k for k, th in d.items() if not th.is_alive()]:
                d.pop(k)
        if self.gate_thread and not self.gate_thread.is_alive():
            self.gate_thread = None

    def _spawn(self, table: dict, key: str, fn, *args) -> None:
        th = threading.Thread(target=fn, args=args, daemon=True, name=key)
        table[key] = th
        th.start()

    # -- pi helpers ------------------------------------------------------------

    def _pi(self, session_id: str, role: str, cwd: Path, ticket_id: str = "") -> PiProcess:
        return PiProcess(
            session_id=session_id, session_dir=self.project.sessions_dir, cwd=cwd,
            system_prompt=agents.role_prompt(self.project, role),
            provider=self.cfg.provider, model=self.cfg.model, thinking=self.cfg.thinking,
            env={"ORCHESTRA_ROLE": role, "ORCHESTRA_REPO": str(self.project.repo_root), "ORCHESTRA_TICKET": ticket_id},
            log_path=self.project.logs_dir / "pi" / f"{session_id}.stderr.log",
        )

    def _session_running(self, sid: str, role: str, proc: PiProcess, ticket_id: str | None = None) -> None:
        try:
            proc.get_state()
        except Exception:
            pass
        self.store.set_session(sid, kind=role, status="running", ticket_id=ticket_id,
                               pi_session_file=proc.session_file, started_at=time.time(), last_text="")
        self.events.emit("session_started", session=sid, kind=role, ticket=ticket_id)

    def _session_idle(self, sid: str, text: str) -> None:
        self.store.set_session(sid, status="idle", last_text=(text or "")[-500:], settled_at=time.time())
        self.events.emit("session_settled", session=sid)

    def _prompt_with_retry(self, proc: PiProcess, ticket_id: str, task: str, nudge: str) -> tuple[dict | None, str, bool]:
        res = proc.prompt(task, self.cfg.turn_timeout, on_event=self._on_event(proc.session_id))
        report = self.store.pop_report(ticket_id)
        if report or res.timed_out or res.error:
            return report, res.text, res.timed_out or bool(res.error)
        res = proc.prompt(nudge, min(self.cfg.turn_timeout, 300), on_event=self._on_event(proc.session_id))
        return self.store.pop_report(ticket_id), res.text, res.timed_out or bool(res.error)

    def _on_event(self, sid: str):
        def fn(ev: dict) -> None:
            if ev.get("type") == "tool_execution_start":
                self.store.set_session(sid, last_text=f"tool: {ev.get('toolName') or ev.get('name', '?')}")
            elif ev.get("type") == "message_end" and ev.get("message", {}).get("role") == "assistant":
                content = ev["message"].get("content")
                if isinstance(content, list):
                    txt = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                    if txt.strip():
                        self.store.set_session(sid, last_text=txt.strip()[-500:])
        return fn

    # -- worker ----------------------------------------------------------------

    def _worktree(self, t: Ticket) -> tuple[Path, str]:
        branch = t.branch or f"orchestra/{t.id}-{t.slug}"
        path = self.project.worktrees_dir / t.id
        if not path.exists() or self.git.worktree_branch(path) != branch:
            self.git.worktree_remove(path)
            self.git.worktree_add(branch, path, self.cfg.base_branch)
        self.store.set_worktree(t.id, str(path), branch)
        return path, branch

    def _work(self, t: Ticket) -> None:
        sid = f"worker-{t.id}"
        try:
            path, branch = self._worktree(t)
            t = self.store.transition(t.id, t.version, State.IN_PROGRESS, branch=branch, worker_session=sid)
        except (Conflict, StoreError, GitError) as e:
            log(f"{t.id}: cannot start worker: {e}")
            return
        log(f"{t.id}: worker starting on {branch}")
        proc = self._pi(sid, "worker", path, t.id)
        text = ""
        try:
            self._session_running(sid, "worker", proc, t.id)
            unit_cmd = self.cfg.unit[0].command if self.cfg.unit else None
            report, text, failed = self._prompt_with_retry(
                proc, t.id, agents.worker_task(self.project, t, unit_cmd),
                "You stopped without reporting. Call `report_ticket` now: READY_FOR_REVIEW if your work is "
                "committed and tested, otherwise BLOCKED with the reason.")
        finally:
            proc.close()
            self._session_idle(sid, text)
        self._apply_worker_report(t.id, report, text, failed, path, branch)

    def _apply_worker_report(self, tid: str, report: dict | None, text: str, failed: bool,
                             path: Path, branch: str) -> None:
        t = self.store.get_ticket(tid)
        if t.state != State.IN_PROGRESS:
            return
        if report is None:
            reason = "worker timed out or crashed" if failed else "worker stopped without calling report_ticket"
            reason += f". Last message: {text[-600:]}" if text else "."
            self.store.add_note(tid, Note(author="orchestra", kind="blocker", text=reason))
            self.store.transition(tid, t.version, State.BLOCKED, blocked_reason=reason)
            self.store.add_wakeup("coordinator", f"{tid} BLOCKED: {reason[:200]}")
            log(f"{tid}: BLOCKED ({reason[:80]})")
            return
        self.store.add_note(tid, Note(author="worker", text=report.get("summary", "")))
        if report["state"] == "BLOCKED":
            self.store.transition(tid, t.version, State.BLOCKED, blocked_reason=report.get("blocked_reason"))
            self.store.add_wakeup("coordinator", f"{tid} BLOCKED by worker: {report.get('blocked_reason', '')[:200]}")
            log(f"{tid}: BLOCKED by worker")
            return
        # READY_FOR_REVIEW: make sure there is something to review.
        if self.git.run("status", "--porcelain", cwd=path, check=False).stdout.strip():
            self.git.run("add", "-A", cwd=path, check=False)
            self.git.run("commit", "-q", "-m", f"{tid}: commit remaining worker changes", cwd=path, check=False)
        head = self.git.rev_parse("HEAD", cwd=path)
        if head == self.git.rev_parse(self.cfg.base_branch) or self.git.is_ancestor(head, self.cfg.base_branch):
            reason = "worker reported READY_FOR_REVIEW but the branch has no commits beyond the base branch"
            self.store.add_note(tid, Note(author="orchestra", kind="blocker", text=reason))
            self.store.transition(tid, t.version, State.BLOCKED, blocked_reason=reason)
            self.store.add_wakeup("coordinator", f"{tid} BLOCKED: {reason}")
            return
        self.store.transition(tid, t.version, State.READY_FOR_REVIEW, reviewed_commit=head, feedback=None)
        log(f"{tid}: READY_FOR_REVIEW at {head[:10]}")

    # -- reviewer --------------------------------------------------------------

    def _review(self, t: Ticket) -> None:
        sid = f"reviewer-{t.id}"
        wt = self.store.worktree(t.id)
        if not wt:
            self.store.transition(t.id, t.version, State.IN_REVIEW)
            self._reject(t.id, "orchestra", "worktree missing at review time; please re-run", reviewer_text="")
            return
        path = Path(wt["path"])
        try:
            t = self.store.transition(t.id, t.version, State.IN_REVIEW, reviewer_session=sid)
        except (Conflict, StoreError) as e:
            log(f"{t.id}: cannot start review: {e}")
            return
        log(f"{t.id}: review starting")
        base = self.cfg.base_branch
        test_output = None
        if self.cfg.unit:
            ok, res = run_specs(self.cfg.unit, path, self.project.logs_dir / "review" / t.id, stage="unit")
            test_output = "\n".join(f"$ {r['command']}\n{r['tail']}\n[{r['status']}]" for r in res)
        commit = t.reviewed_commit or self.git.rev_parse("HEAD", cwd=path)
        diff = self.git.diff(base, commit, cwd=path)
        files = self.git.changed_files(base, commit, cwd=path)
        glog = self.git.log(base, commit, cwd=path)
        proc = self._pi(sid, "reviewer", path, t.id)
        text = ""
        try:
            self._session_running(sid, "reviewer", proc, t.id)
            report, text, failed = self._prompt_with_retry(
                proc, t.id, agents.reviewer_task(self.project, t, commit, diff, files, glog, test_output),
                "You stopped without a verdict. Call `report_review` now with APPROVED or REJECTED.")
        finally:
            proc.close()
            self._session_idle(sid, text)
        t = self.store.get_ticket(t.id)
        if t.state != State.IN_REVIEW:
            return
        if report is None:
            self._reject(t.id, "orchestra", "reviewer produced no verdict" + (" (timed out)" if failed else "") +
                         ". Re-check your work, make sure the diff is small and focused, and report again.", text)
            return
        self.store.add_note(t.id, Note(author="reviewer", kind="review",
                                       text=f"{report['verdict']}: {report.get('summary', '')}\n{report.get('feedback') or ''}"))
        if report["verdict"] == "APPROVED":
            self.store.transition(t.id, t.version, State.APPROVED, reviewed_commit=commit, feedback=None, rejected_by=None)
            log(f"{t.id}: APPROVED")
        else:
            self._reject(t.id, "reviewer", report.get("feedback") or report.get("summary", ""), text)

    def _reject(self, tid: str, by: str, feedback: str, reviewer_text: str) -> None:
        t = self.store.get_ticket(tid)
        rounds = t.review_rounds + 1
        self.store.transition(tid, t.version, State.REJECTED, rejected_by="reviewer" if by != "merge_gate" else by,
                              feedback=feedback, review_rounds=rounds)
        log(f"{tid}: REJECTED (round {rounds})")
        if rounds >= self.cfg.review_rounds_before_escalation:
            self.store.add_wakeup("coordinator", f"{tid} has been rejected {rounds} times; decide whether to narrow, split, or cancel it")

    # -- gate ------------------------------------------------------------------

    def _gate(self, ticket_ids: list[str]) -> None:
        try:
            for tid in ticket_ids:
                t = self.store.get_ticket(tid)
                self.store.transition(tid, t.version, State.MERGING)
            log(f"gate: {', '.join(ticket_ids)}")
            run = run_gate(self.project, self.store, self.events, ticket_ids)
            log(f"gate {run['id']}: {run['status']} {run.get('summary', '')}")
            if run["status"] == "landed":
                self.store.add_wakeup("coordinator", f"landed {', '.join(run['merged'])} on {self.cfg.base_branch}")
        except (Conflict, StoreError) as e:
            log(f"gate: {e}")

    def _drop_worktree(self, t: Ticket) -> None:
        wt = self.store.worktree(t.id)
        if wt:
            self.git.worktree_remove(Path(wt["path"]))
            self.store.remove_worktree(t.id)

    # -- project agents --------------------------------------------------------

    def _wake(self, target: str, reasons: list[str]) -> None:
        sid = target.replace("_", "-")
        proc = self.agent_procs.get(target)
        if proc is None or not proc.alive():
            proc = self._pi(sid, target, self.project.repo_root)
            self.agent_procs[target] = proc
        log(f"{sid}: waking ({len(reasons)} reason(s))")
        self._session_running(sid, target, proc)
        res = proc.prompt(agents.wake_task(target, reasons, self.store.snapshot()), self.cfg.turn_timeout,
                          on_event=self._on_event(sid))
        self._session_idle(sid, res.text)
        self.events.emit("agent_said", session=sid, summary=(res.text or "")[:500])
        log(f"{sid}: {(res.text or '(no text)')[:160]!r}")
