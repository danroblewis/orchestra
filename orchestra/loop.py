"""The orchestration loop: slots, ticks, workers, reviewers, gate, wake-ups. SPEC.md section 6."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from . import agents
from .config import Project
from .events import Events
from .gate import run_gate, run_specs
from .git import Git, GitError
from .model import ACTIVE, RECOVERY, Note, State, Ticket, effective_priorities, is_ready
from .control import ControlServer
from .harness import AgentSession, SessionSpec, get_harness
from .staging import Staging
from .store import Conflict, LocalStore, StoreError

from .agents.roles import ROLES, resident_roles
from .roles import RoleDef, all_roles, due_at, parse_interval

# Built-in resident roles; custom roles are loaded from the role store each tick.
PROJECT_AGENTS = tuple(r.name for r in resident_roles() if r.name != "supervisor")
RESIDENT_AGENTS = tuple(r.name for r in resident_roles())


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
        self.agent_procs: dict[str, AgentSession] = {}
        self.harness = get_harness(self.cfg.harness)
        self.stop = threading.Event()
        self.staging = Staging(project, store, events)
        self.control: ControlServer | None = None
        self._events_offset = 0
        self._started_at = time.time()
        self._last_scheduled: dict[str, float] = {}
        self.live_procs: dict[str, AgentSession] = {}   # session id -> session, while a turn runs
        self.killed: set[str] = set()                # ticket ids whose agent the operator stopped
        self.roles: dict[str, RoleDef] = {}          # all roles (built-in + custom), refreshed each tick
        self._last_token_write: dict[str, float] = {}
        self._events_tail = self.events.read(0, limit=1)[1]   # only events after startup can wake roles

    # -- lifecycle -------------------------------------------------------------

    def recover(self) -> None:
        for t in self.store.list_tickets():
            if t.state in ACTIVE:
                self.store.transition(t.id, t.version, RECOVERY[t.state])
                log(f"recovered {t.id}: {t.state} -> {RECOVERY[t.state]}")
        for s in self.store.sessions():
            self.store.set_session(s["id"], status="idle", pid=None)
        # A gate run that was in flight when the previous loop died never finished;
        # mark it so the dashboard does not show it as running forever.
        for run in self.store.gate_runs():
            if run.get("status") == "running":
                run["status"] = "aborted"
                run["summary"] = "orchestrator restarted during the run"
                run["finished_at"] = run.get("finished_at") or __import__("orchestra.model", fromlist=["now"]).now()
                self.store.save_gate_run(run)
        for p in self.project.gate_dir.glob("*"):
            self.git.worktree_remove(p)
        self.git.run("worktree", "prune", check=False)
        for b in self.git.run("branch", "--list", "orchestra/gate-*", check=False).stdout.split():
            self.git.branch_delete(b.strip("* "))

    def run(self, once: bool = False) -> None:
        # SIGTERM/SIGINT stop the loop cleanly so resident Pi processes are closed,
        # not orphaned, and the control port is released.
        import signal

        def _stop(_sig, _frame):
            self.stop.set()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _stop)
            except ValueError:  # not the main thread (tests)
                pass
        self.recover()
        self.events.emit("loop_started")
        log(f"project {self.project.key} on {self.project.repo_root}; workers={self.cfg.workers} reviewers={self.cfg.reviewers}")
        self._start_project_agents()
        self._start_control()
        paused = self.store.pipeline()
        if paused.get("paused"):
            self.store.add_wakeup("pipeline_manager", f"the pipeline is still paused after a restart: {paused.get('reason')}. "
                                  "Diagnose, fix what you can or escalate, then call resume_pipeline.")
        # Staging survives loop restarts; only bring it back if its process is gone.
        if self.cfg.staging_configured and self.staging.state().get("current_build_id"):
            threading.Thread(target=self.staging.ensure_running, daemon=True, name="staging").start()
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
            if self.control:
                self.control.stop()
            for name, p in self.agent_procs.items():
                p.close()
                self.store.set_session(ROLES[name].session_id, status="idle", pid=None)
            # Only drop the control record if it is ours: a replacement loop may already
            # have registered while this one was shutting down.
            self.store._mutate_runtime(lambda d: d.pop("control", None)
                                       if (d.get("control") or {}).get("pid") == os.getpid() else None)
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
        cap = self.store.capacity()
        eff = effective_priorities(tickets, self.cfg.aging_days_per_level)
        ordered = sorted(tickets.values(), key=lambda t: (eff.get(t.id, {}).get("effective", t.priority), t.created_at, t.id))

        self._service_kills()
        paused = self.store.pickup_paused()
        # Review before pick: finished work lands before new work starts.
        for t in ordered:
            if t.state == State.READY_FOR_REVIEW and len(self.reviewers) < cap["reviewers"] and t.id not in self.reviewers:
                self._spawn(self.reviewers, t.id, self._review, t)
        for t in ordered:
            if paused or len(self.workers) >= cap["workers"]:
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
        self.staging.ensure_running()
        self._refresh_roles()
        self._schedule_wakeups()
        self._wake_on_events()
        for target in list(self.roles):
            if target == "supervisor" and self.agent_procs.get("supervisor") is None:
                continue
            if target not in self.agent_threads:
                st = self.store.role_state(target)
                if st.get("paused") or st.get("deleted"):
                    continue  # wake-ups stay queued until resumed
                reasons = list(dict.fromkeys(w["reason"] for w in self.store.drain_wakeups(target)))
                if reasons:
                    self._spawn(self.agent_threads, target, self._wake, target, reasons)

    def _refresh_roles(self) -> None:
        """Reload roles from the store; start resident processes for new ones, close
        processes for roles that were deleted, paused, or asked to restart."""
        try:
            roles = all_roles(self.project)
        except Exception as e:
            log(f"roles: could not load custom roles: {e}")
            return
        for name in list(self.agent_procs):
            st = self.store.role_state(name)
            gone = name not in roles or st.get("deleted")
            if gone or st.get("restart_requested") or st.get("paused"):
                if name in self.agent_threads:
                    continue  # let the current turn finish first
                proc = self.agent_procs.pop(name)
                proc.close()
                self.store.set_session(roles[name].session_id if name in roles else name.replace("_", "-"), status="idle", pid=None)
                if st.get("restart_requested"):
                    self.store.set_role_state(name, restart_requested=False)
                    log(f"{name}: session restarted by request")
        for name, role in roles.items():
            if name == "supervisor" or name in self.agent_procs or not role.resident:
                continue
            st = self.store.role_state(name)
            if st.get("paused") or st.get("deleted"):
                continue
            if name in ROLES and name not in ("coordinator", "pipeline_manager"):
                continue
            self._start_resident(name, role)
        self.roles = roles

    def _start_resident(self, name: str, role: RoleDef) -> None:
        try:
            proc = self._session_for(role, role.session_id)
            proc.open()
            self.agent_procs[name] = proc
            self.store.set_session(role.session_id, kind=name, status="idle", pid=self._pid(proc),
                                   session_file=proc.session_file, harness=proc.harness_name)
            log(f"{role.session_id}: session resident ({self.harness.name})")
        except Exception as e:
            log(f"{role.session_id}: could not start: {e}")

    def _session_for(self, role: RoleDef, session_id: str) -> AgentSession:
        return self._open_session(session_id, role.name, role.name, tuple(role.tools), self.project.repo_root)

    def _open_session(self, session_id: str, role: str, prompt_stem: str, tools: tuple[str, ...], cwd: Path,
                      ticket_id: str = "") -> AgentSession:
        """Start a session on the configured harness. Which product runs the agent is
        invisible past this point: the loop only sees the AgentSession interface."""
        return self.harness.start(SessionSpec(
            session_id=session_id, session_dir=self.project.sessions_dir, cwd=cwd,
            system_prompt=agents.role_prompt(self.project, prompt_stem), role=role, tool_groups=tools,
            env={"ORCHESTRA_ROLE": role, "ORCHESTRA_REPO": str(self.project.repo_root), "ORCHESTRA_TICKET": ticket_id},
            log_path=self.project.logs_dir / "agents" / f"{session_id}.stderr.log",
            model=self.cfg.model, provider=self.cfg.provider, thinking=self.cfg.thinking, ticket_id=ticket_id))

    @staticmethod
    def _pid(proc: AgentSession) -> int:
        """The process that proves the session is alive: the harness's own when it keeps one
        (Pi), otherwise this loop, which is what holds the session open."""
        return proc.pid or os.getpid()

    def _wake_on_events(self) -> None:
        """Match new events against every role's wake_on list and queue wake-ups."""
        evs, self._events_tail = self.events.read(self._events_tail, limit=5000)
        for ev in evs:
            for name, role in self.roles.items():
                if name == "supervisor" or not role.wake_on or not role.matches_event(ev):
                    continue
                bits = [f"{k}={ev[k]}" for k in ("ticket", "milestone", "from", "to", "gate_run", "reason", "by") if ev.get(k)]
                self.store.add_wakeup(name, f"event {ev['type']}" + (" " + " ".join(str(b) for b in bits) if bits else ""))

    def _schedule_wakeups(self) -> None:
        """Queue a wake-up for roles whose interval has elapsed or whose daily time has come."""
        now_t = time.time()
        for name, role in self.roles.items():
            st = self.store.role_state(name)
            if st.get("paused") or st.get("deleted"):
                continue
            if role.every:
                secs = parse_interval(role.every)
                last = self._last_scheduled.get(name, self._started_at)
                if now_t - last >= secs:
                    self._last_scheduled[name] = now_t
                    self.store.add_wakeup(name, f"scheduled check-in (every {role.every})")
            if role.at and due_at(role.at, st.get("last_at_fire"), now_t):
                self.store.set_role_state(name, last_at_fire=now_t)
                self.store.add_wakeup(name, f"scheduled daily session ({role.at})")

    def _service_kills(self) -> None:
        """Stop the worker or reviewer process for each ticket the operator asked to kill.
        The thread that owns it sees the process exit and resets the ticket (see
        _apply_worker_report / _review), without counting it as a crash."""
        for tid in self.store.take_kill_requests():
            for sid in (f"worker-{tid}", f"reviewer-{tid}"):
                proc = self.live_procs.get(sid)
                if proc and proc.alive():
                    self.killed.add(tid)
                    log(f"{tid}: {sid} stopped by operator")
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    self.events.emit("agent_killed", ticket=tid, session=sid)

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

    def _session(self, session_id: str, role: str, cwd: Path, ticket_id: str = "") -> AgentSession:
        spec = ROLES[role]
        return self._open_session(session_id, role, spec.prompt, tuple(spec.tools), cwd, ticket_id)

    def _session_running(self, sid: str, role: str, proc: AgentSession, ticket_id: str | None = None) -> None:
        self.live_procs[sid] = proc
        try:
            proc.open()
        except Exception:
            pass
        self.store.set_session(sid, kind=role, status="running", ticket_id=ticket_id, pid=self._pid(proc),
                               session_file=proc.session_file, harness=proc.harness_name, started_at=time.time(), last_text="",
                               last_output_at=None, phase="prompting", phase_since=time.time(),
                               last_token_at=None, tool_name=None)
        self.events.emit("session_started", session=sid, kind=role, ticket=ticket_id)

    def _session_idle(self, sid: str, text: str, resident: bool = False) -> None:
        proc = self.live_procs.pop(sid, None) if not resident else self._proc_for(sid)
        fields = {} if resident else {"pid": None}
        if proc is not None and proc.session_file:
            fields["session_file"] = proc.session_file   # some harnesses only name the transcript after the first turn
        self.store.set_session(sid, status="idle", last_text=(text or "")[-500:], settled_at=time.time(), phase="idle", tool_name=None,
                               **fields)
        self.events.emit("session_settled", session=sid)

    def _proc_for(self, sid: str) -> AgentSession | None:
        if sid in self.live_procs:
            return self.live_procs[sid]
        return next((p for p in self.agent_procs.values() if p.session_id == sid), None)

    def _prompt_with_retry(self, proc: AgentSession, ticket_id: str, task: str, nudge: str) -> tuple[dict | None, str, bool]:
        res = proc.prompt(task, self.cfg.turn_timeout, on_event=self._on_event(proc.session_id))
        report = self.store.pop_report(ticket_id)
        if report or res.timed_out or res.error:
            return report, res.text, res.timed_out or bool(res.error)
        res = proc.prompt(nudge, min(self.cfg.turn_timeout, 300), on_event=self._on_event(proc.session_id))
        return self.store.pop_report(ticket_id), res.text, res.timed_out or bool(res.error)

    def _on_event(self, sid: str):
        """Translate a session's normalized event stream into the phase the UI shows: waiting
        for the model, generating, or inside a tool. Nothing here is harness-specific."""
        def fn(ev: dict) -> None:
            t = ev.get("type")
            now_t = time.time()
            if t == "turn_start":
                self.store.set_session(sid, phase="prompting", phase_since=now_t, tool_name=None)
            elif t == "assistant_start":
                self.store.set_session(sid, phase="generating", phase_since=now_t, last_token_at=now_t)
            elif t == "token":
                # Many small events while tokens stream; a timestamp write every few seconds is enough.
                st = self._last_token_write.get(sid, 0)
                if now_t - st > 3:
                    self._last_token_write[sid] = now_t
                    self.store.set_session(sid, phase="generating", last_token_at=now_t, last_output_at=now_t)
            elif t == "tool_start":
                name = ev.get("name", "?")
                self.store.set_session(sid, phase="tool", phase_since=now_t, tool_name=name, last_output_at=now_t,
                                       last_text=f"tool: {name}")
            elif t == "tool_end":
                self.store.set_session(sid, phase="prompting", phase_since=now_t, tool_name=None, last_output_at=now_t)
            elif t == "assistant_end":
                fields = {"last_output_at": now_t, "last_token_at": now_t}
                txt = (ev.get("text") or "").strip()
                if txt:
                    fields["last_text"] = txt[-500:]
                self.store.set_session(sid, **fields)
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
            t = self.store.transition(t.id, t.version, State.IN_PROGRESS, branch=branch, worker_session=sid,
                                      worker_turns=t.worker_turns + 1)
        except (Conflict, StoreError, GitError) as e:
            log(f"{t.id}: cannot start worker: {e}")
            return
        log(f"{t.id}: worker starting on {branch}")
        proc = self._session(sid, "worker", path, t.id)
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
        if tid in self.killed:
            self.killed.discard(tid)
            self.store.add_note(tid, Note(author="orchestra", kind="note", text="worker stopped by the operator; ticket reset to OPEN"))
            self.store.transition(tid, t.version, State.OPEN, feedback="Your previous turn was stopped by the operator. Check `git status` and `git log`, then continue from where you left off and report.")
            log(f"{tid}: reset to OPEN after operator stop")
            return
        if report is None and self.stop.is_set():
            # The orchestrator is shutting down (restart or redeploy): that is not the
            # worker's fault, so reset without counting a crash.
            self.store.add_note(tid, Note(author="orchestra", kind="note", text="orchestrator shut down during this turn; ticket reset to OPEN"))
            self.store.transition(tid, t.version, State.OPEN, feedback="Your previous turn was interrupted by an orchestrator restart. Check `git status` and `git log`, continue from where you left off, then report.")
            return
        if report is None:
            # Count only the trailing run of crash notes, so an unblock or any other note
            # resets the budget instead of a ticket carrying old crashes forever.
            crashes = 1 if failed else 0
            for n in reversed(self.store.notes(tid)):
                if n.get("kind") != "crash":
                    break
                crashes += 1
            if failed and crashes <= 2:
                # The worker process died or timed out (often an orchestrator restart). That is
                # not a decision for a human: keep the session and branch, retry from OPEN.
                self.store.add_note(tid, Note(author="orchestra", kind="crash",
                                              text=f"worker process ended without reporting (attempt {crashes}); retrying from its session"))
                self.store.transition(tid, t.version, State.OPEN, feedback="Your previous turn ended unexpectedly. Check `git status` and `git log`, continue from where you left off, then report.")
                log(f"{tid}: worker died; back to OPEN for retry ({crashes})")
                return
            reason = ("the worker process died or timed out repeatedly" if failed else "worker stopped without calling report_ticket")
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
        proc = self._session(sid, "reviewer", path, t.id)
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
        if t.id in self.killed:
            self.killed.discard(t.id)
            self.store.add_note(t.id, Note(author="orchestra", kind="note", text="reviewer stopped by the operator; review will be redone"))
            self.store.transition(t.id, t.version, State.READY_FOR_REVIEW)
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
                              feedback=feedback, review_rounds=rounds, reviewer_rejections=t.reviewer_rejections + 1)
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
        for f in self.store.purge_ticket_sessions(t.id):
            Path(f).unlink(missing_ok=True)

    # -- project agents --------------------------------------------------------

    def _start_project_agents(self) -> None:
        """Start the resident supervisor, coordinator, and pipeline-manager sessions up
        front so they live for the life of `orchestra run`."""
        for target in RESIDENT_AGENTS:
            sid = ROLES[target].session_id
            try:
                proc = self._session(sid, target, self.project.repo_root)
                proc.open()
                self.agent_procs[target] = proc
                self.store.set_session(sid, kind=target, status="idle", pid=self._pid(proc),
                                       session_file=proc.session_file, harness=proc.harness_name)
                log(f"{sid}: session resident ({self.harness.name})")
            except Exception as e:
                log(f"{sid}: could not start: {e}")

    def _start_control(self) -> None:
        port = int(self.cfg.raw.get("agents", {}).get("control_port", 8010))
        try:
            self.control = ControlServer(port, self.prompt_supervisor)
            self.control.start()
            self.store._mutate_runtime(lambda d: d.__setitem__("control", {"port": port, "pid": os.getpid()}))
            log(f"control endpoint on 127.0.0.1:{port} (orchestra chat attaches here)")
        except OSError as e:
            log(f"control endpoint unavailable on port {port}: {e}")

    def prompt_supervisor(self, message: str, emit) -> dict:
        """One supervisor turn on the resident session, with the event digest prefix."""
        proc = self.agent_procs.get("supervisor")
        if proc is None or not proc.alive():
            proc = self._session("supervisor", "supervisor", self.project.repo_root)
            proc.open()
            self.agent_procs["supervisor"] = proc
        new, self._events_offset = self.events.read(self._events_offset)
        new = [e for e in new if e["type"] not in ("session_started", "session_settled")]
        prefix = agents.supervisor_context(self.store.snapshot(), new, self.project)
        self._session_running("supervisor", "supervisor", proc)

        def on_event(ev: dict) -> None:
            self._on_event("supervisor")(ev)
            if ev.get("type") in ("tool_start", "assistant_end"):
                emit(ev)

        res = proc.prompt(prefix + message, self.cfg.turn_timeout, on_event=on_event)
        self._session_idle("supervisor", res.text, resident=True)
        return {"text": res.text, "error": res.error, "timed_out": res.timed_out}

    def _wake(self, target: str, reasons: list[str]) -> None:
        role = self.roles.get(target)
        if role is None:
            return
        sid = role.session_id
        ephemeral = not role.resident
        if ephemeral:
            sid = f"{role.session_id}-{time.strftime('%Y%m%d-%H%M%S')}"
            proc = self._session_for(role, sid)
        else:
            proc = self.agent_procs.get(target)
            if proc is None or not proc.alive():
                proc = self._session_for(role, sid) if target not in ROLES else self._session(sid, target, self.project.repo_root)
                self.agent_procs[target] = proc
        self.store.set_role_state(target, last_woken=time.time())
        log(f"{sid}: waking ({len(reasons)} reason(s))")
        self._session_running(sid, target, proc)
        task = agents.wake_task(target, reasons, self.store.snapshot())
        if target == "supervisor":
            task = ("[Orchestra: escalation from another agent; the human is not present for this turn. "
                    "Act with your tools if you can, otherwise leave a note the human will see.]\n\n"
                    + agents.supervisor_context(self.store.snapshot(), [], self.project) + task)
        res = proc.prompt(task, self.cfg.turn_timeout, on_event=self._on_event(sid))
        self._session_idle(sid, res.text, resident=not ephemeral)
        if ephemeral:
            proc.close()
        self.events.emit("agent_said", session=sid, summary=(res.text or "")[:500])
        log(f"{sid}: {(res.text or '(no text)')[:160]!r}")
