"""Orchestrator process (read-write).

The orchestrator is the "nervous system" of Orchestra. It owns all state
mutations (through the shared repositories) and drives the four AI agent layers
(Supervisor, Coordinator, Pipeline Manager, Workers) as persistent Pi sessions,
invoked via the Pi RPC protocol.

This process is separate from the web server so the web server can stay
read-only and update frequently against the persisted state.

Because the actual Pi harness invocation requires a running Pi CLI and model
provider, this orchestrator implements the full orchestration logic and
session-lifecycle plumbing, with a `mock` transport by default so the system
is end-to-end runnable and testable without a live Pi. The `rpc` transport
spawns `pi --mode rpc` processes.
"""

from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.models import Task, Milestone, Status, SessionLog
from shared.repositories.json_store import JsonStore
from shared.repositories.task_repository import TaskRepository
from shared.repositories.milestone_repository import MilestoneRepository
from shared.repositories.session_log_repository import SessionLogRepository


class Transport:
    """Interface for driving a Pi agent session.

    A real implementation uses the Pi RPC protocol. The mock implementation
    records prompts and returns canned responses so the orchestration logic can
    be exercised end-to-end.
    """

    def send(self, session_file: str, prompt: str) -> dict[str, Any]:
        raise NotImplementedError

    def read_last_assistant_text(self, session_file: str) -> str:
        raise NotImplementedError


class MockTransport(Transport):
    """Records what would be sent to Pi and returns deterministic responses."""

    def __init__(self):
        self.sent: list[dict[str, Any]] = []

    def send(self, session_file: str, prompt: str, system_prompt: str = "") -> dict[str, Any]:
        text = f"[mock] processed: {prompt}"
        entry = {"session_file": session_file, "prompt": prompt, "text": text, "ts": time.time()}
        self.sent.append(entry)
        # Echo back a structured response the orchestrator can parse.
        return {"role": "assistant", "text": text}

    def read_last_assistant_text(self, session_file: str) -> str:
        for entry in reversed(self.sent):
            if entry["session_file"] == session_file:
                return entry["text"]
        return ""


class RpcTransport(Transport):
    """Drives a real Pi session via the RPC protocol (pi --mode rpc)."""

    def __init__(self, pi_binary: str | None = None):
        self.pi_binary = pi_binary or os.environ.get("PI_BINARY", "pi")

    def send(self, session_file: str, prompt: str) -> dict[str, Any]:
        import subprocess

        proc = subprocess.Popen(
            [self.pi_binary, "--mode", "rpc", "--session", session_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        command = json.dumps({"id": "req-1", "type": "prompt", "message": prompt})
        out, err = proc.communicate(command + "\n", timeout=300)
        # Parse events from stdout to find agent_settled / response.
        result = {"raw": out}
        for line in out.splitlines():
            try:
                obj = json.loads(line)
                if obj.get("type") == "response":
                    result["response"] = obj
            except json.JSONDecodeError:
                continue
        return result

    def read_last_assistant_text(self, session_file: str) -> str:
        import subprocess

        proc = subprocess.run(
            [self.pi_binary, "--mode", "rpc", "--session", session_file, "--", "get_last_assistant_text"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.stdout.strip()


class Orchestrator:
    """Coordinates the four agent layers and owns all state."""

    LAYERS = ("supervisor", "coordinator", "pipeline-manager", "worker")

    def __init__(self, store: JsonStore, transport: Transport):
        self.tasks = TaskRepository(store)
        self.milestones = MilestoneRepository(store)
        self.session_logs = SessionLogRepository(store)
        self.transport = transport

    # --- session lifecycle ---------------------------------------------------

    def _ensure_session(self, name: str, layer: str) -> SessionLog:
        """Return the current session log for a named session, creating one."""
        existing = self.session_logs.by_name(name)
        if existing:
            existing.status = "running"
            return self.session_logs.save(existing)
        log = SessionLog(
            session_name=name,
            layer=layer,
            session_file_path=os.path.join("sessions", f"{name}.jsonl"),
            status="running",
        )
        return self.session_logs.save(log)

    def set_idle(self, name: str) -> None:
        log = self.session_logs.by_name(name)
        if log:
            log.status = "idle"
            self.session_logs.save(log)

    def drive(self, session_name: str, layer: str, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt to a named agent session and return assistant text.

        ``system_prompt`` is layered via the transport (``--append-system-prompt``);
        it is also persisted to the session log so the session can be resumed later.
        """
        log = self._ensure_session(session_name, layer)
        result = self.transport.send(log.session_file_path, prompt, system_prompt=system_prompt)
        text = self.transport.read_last_assistant_text(log.session_file_path)
        if text is None:
            text = json.dumps(result)
        # Persist the system prompt as an assistant preamble so a resumed session
        # still knows which layer it is.
        if system_prompt:
            self._write_session_entry(log.session_file_path, "assistant", f"[system] {system_prompt}")

        # Persist the exchange to the session log JSONL file so the web viewer
        # can render it. Each line is one entry (user or assistant).
        self._write_session_entry(log.session_file_path, "user", prompt)
        self._write_session_entry(log.session_file_path, "assistant", text)

        log.message_count += 2
        log.last_entry_id = "n/a"
        log.status = "idle"
        self.session_logs.save(log)
        return text

    @staticmethod
    def _write_session_entry(session_file_path: str, role: str, content: str) -> None:
        """Append a single entry to a session's JSONL log file."""
        import json as _json
        from datetime import datetime, UTC

        if not session_file_path:
            return
        # Resolve relative paths against the data directory.
        if not os.path.isabs(session_file_path):
            data_dir = os.environ.get(
                "ORCHESTRA_DATA_DIR",
                str(Path(__file__).resolve().parents[2] / "data"),
            )
            session_file_path = os.path.join(data_dir, session_file_path)
        # Ensure the parent directory exists.
        parent = os.path.dirname(session_file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        entry = {
            "type": "message",
            "role": role,
            "text": content,
            "ts": datetime.now(UTC).isoformat(),
        }
        with open(session_file_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry) + "\n")

    # --- task graph construction --------------------------------------------

    def create_milestone(self, name: str, order: int = 0) -> Milestone:
        m = Milestone(name=name, order=order)
        return self.milestones.save(m)

    def create_task(
        self,
        title: str,
        description: str = "",
        milestone_id: str | None = None,
        dependency_ids: list[str] | None = None,
        priority: int = 5,
        status: Status = Status.BACKLOG,
    ) -> Task:
        t = Task(
            title=title,
            description=description,
            milestone_id=milestone_id,
            dependency_ids=dependency_ids or [],
            priority=priority,
            status=status,
        )
        saved = self.tasks.save(t)

        # If the task belongs to a milestone, ensure the milestone knows about it.
        if milestone_id:
            milestone = self.milestones.find(milestone_id)
            if t.id not in milestone.task_ids:
                milestone.task_ids.append(t.id)
                self.milestones.save(milestone)
        return saved

    def mark_done(self, task_id: str) -> Task:
        t = self.tasks.find(task_id)
        t.status = Status.DONE
        return self.tasks.save(t)

    def assign_worker(self, task_id: str, worker_session_name: str) -> Task:
        t = self.tasks.find(task_id)
        t.status = Status.IN_PROGRESS
        t.assignee_session_id = worker_session_name
        return self.tasks.save(t)

    # --- high-level orchestration flows -------------------------------------

    def run_supervisor_request(self, user_request: str) -> str:
        """Translate a user request into coordinator + pipeline-manager actions.

        In the full system, the Supervisor agent (a Pi session) interprets the
        user request and produces structured follow-on work. For now we drive
        the Supervisor session and record its response, then fan out to the
        Coordinator and Pipeline Manager.
        """
        supervisor_text = self.drive(
            "supervisor",
            "supervisor",
            f"User request: {user_request}",
        )

        # Fan out: notify the Coordinator and Pipeline Manager of the new work.
        coordinator_text = self.drive(
            "coordinator",
            "coordinator",
            f"[from supervisor] New work pending: {user_request}",
        )
        pipeline_text = self.drive(
            "pipeline-manager",
            "pipeline-manager",
            f"[from supervisor] Monitor build pipeline for: {user_request}",
        )

        self.set_idle("supervisor")
        self.set_idle("coordinator")
        self.set_idle("pipeline-manager")

        return {
            "supervisor": supervisor_text,
            "coordinator": coordinator_text,
            "pipeline-manager": pipeline_text,
        }

    def run_worker(self, task_id: str, description: str) -> str:
        """Spawn or re-engage a worker session to implement a task."""
        t = self.tasks.find(task_id)
        worker_session = f"worker-{t.slug}" if hasattr(t, "slug") else f"worker-{t.id[:8]}"
        self.assign_worker(task_id, worker_session)

        result = self.drive(worker_session, "worker", f"Implement task: {t.title} -- {description}")
        self.set_idle(worker_session)
        return result


def build_store() -> JsonStore:
    data_dir = Path(os.environ.get("ORCHESTRA_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
    os.makedirs(data_dir, exist_ok=True)
    return JsonStore(data_dir / "orchestra.json")


def main():
    transport_cls = MockTransport
    if os.environ.get("ORCHESTRA_TRANSPORT", "mock") == "rpc":
        transport_cls = RpcTransport

    store = build_store()
    orch = Orchestrator(store, transport_cls())

    print("[orchestrator] Orchestrator running. Transport:", type(orch.transport).__name__)
    print("[orchestrator] Data dir:", os.environ.get("ORCHESTRA_DATA_DIR", "data/"))

    # Demonstrate the orchestration with a real use case if args are given.
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        ms = orch.create_milestone("Milestone 1", order=1)
        t1 = orch.create_task("Set up project scaffolding", milestone_id=ms.id, priority=1)
        t2 = orch.create_task("Implement core logic", milestone_id=ms.id, priority=2, dependency_ids=[t1.id])
        t3 = orch.create_task("Write tests", milestone_id=ms.id, priority=3, dependency_ids=[t2.id])
        orch.mark_done(t1.id)

        print("[orchestrator] Demo task graph created:")
        for t in orch.tasks.all():
            deps = ", ".join(t.dependency_ids) or "-"
            print(f"  [{t.status.value:9}] {t.title} (deps: {deps})")

        result = orch.run_supervisor_request("Add a new feature for user management")
        print("[orchestrator] Supervisor request dispatched to all layers.")

        print("[orchestrator] Next in queue:")
        for t in orch.tasks.next_in_queue():
            print(f"  -> {t.title}")


if __name__ == "__main__":
    main()
