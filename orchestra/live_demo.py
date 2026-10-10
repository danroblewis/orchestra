"""Live, step-by-step demo driver for Orchestra.

Unlike ``demo_driver.py`` (which drives all tickets to DONE as fast as possible),
this driver advances the task graph **one step at a time** so you can watch the
web viewer update as tickets move ``BACKLOG -> IN_PROGRESS -> DONE``.

Key difference: between steps we call ``orch.orch.set_running(...)`` for the
worker/coordinator sessions and *don't* immediately mark them idle, so a live
web refresh catches the session in the ``running`` state (an "active agent").
Between steps the driver sleeps so the web viewer (refreshing every ~2s) can
pick up the intermediate states.

Usage:
    python3 -m orchestra.live_demo --repo <path-to-repo>

Run it while the web viewer (``orchestra web``) is open against the same project
to watch the orchestration flow live.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Make backend/ importable (the orchestrator core + web server live there).
_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from orchestrator.orchestrator import Orchestrator, Transport  # noqa: E402
from orchestra.gitops import Git  # noqa: E402
from orchestra.project import load_project  # noqa: E402
from orchestra.worktree_orchestrator import WorktreeOrchestrator  # noqa: E402

from shared.models import Status  # noqa: E402


class RealisticMockTransport(Transport):
    """A mock transport that behaves like the real agent layers.

    Records every prompt (so the web viewer shows what was said) and returns
    structured responses the orchestrator can parse and apply.
    """

    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.sent: list[dict[str, Any]] = []
        self._turn = 0

    def _key(self, session_file: str) -> str:
        return str(session_file).split("/")[-1]

    def send(self, session_file: str, prompt: str, system_prompt: str = "") -> dict[str, Any]:
        self._turn += 1
        key = self._key(session_file)
        text = self._respond(key, prompt, system_prompt)
        self.sent.append({"session_file": key, "prompt": prompt, "system_prompt": system_prompt, "text": text, "turn": self._turn})
        return {"role": "assistant", "text": text}

    def read_last_assistant_text(self, session_file: str) -> str:
        key = self._key(session_file)
        for entry in reversed(self.sent):
            if entry["session_file"] == key:
                return entry["text"]
        return ""

    # -- layer-specific responses ---------------------------------------------

    def _respond(self, session_file: str, prompt: str, system_prompt: str) -> str:
        name = str(session_file).split("/")[-1]
        if name.startswith("supervisor"):
            return self._supervisor_response(prompt)
        if name.startswith("coordinator"):
            return self._coordinator_response(prompt)
        if name.startswith("pipeline-manager"):
            return self._pipeline_manager_response(prompt)
        if name.startswith("worker"):
            return self._worker_response(prompt)
        if name.startswith("reviewer"):
            return self._reviewer_response(prompt)
        return f"[mock] processed: {prompt[:80]}"

    def _supervisor_response(self, prompt: str) -> str:
        return json.dumps(
            {
                "task_id": "",
                "state": "IN_PROGRESS",
                "summary": "Interpreted the user request and handed the work to the Coordinator.",
                "blockers": [],
                "branch": "",
                "review": {"passed": True, "verdict": "n/a"},
                "ci": {"status": "passed"},
            }
        )

    def _coordinator_response(self, prompt: str) -> str:
        return json.dumps(
            {
                "task_id": "",
                "state": "IN_PROGRESS",
                "summary": "Planned the milestone breakdown and queued tickets in dependency order.",
                "blockers": [],
                "branch": "",
                "review": {"passed": True},
                "ci": {"status": "passed"},
            }
        )

    def _pipeline_manager_response(self, prompt: str) -> str:
        return json.dumps(
            {
                "task_id": "",
                "state": "IN_PROGRESS",
                "summary": "Watching the merge queue; no build failures to recover.",
                "blockers": [],
                "branch": "",
                "review": {"passed": True},
                "ci": {"status": "passed"},
            }
        )

    def _worker_response(self, prompt: str) -> str:
        task_id = _extract_task_id(prompt)
        branch = _extract_branch(prompt)
        summary = _summarize_change(prompt)
        return json.dumps(
            {
                "task_id": task_id,
                "state": "DONE",
                "summary": summary,
                "blockers": [],
                "branch": branch,
                "review": {"required": True, "passed": True, "reviewer": "reviewer"},
                "ci": {"status": "passed", "tests_run": 2},
            }
        )

    def _reviewer_response(self, prompt: str) -> str:
        task_id = _extract_task_id(prompt)
        branch = _extract_branch(prompt)
        return json.dumps(
            {
                "task_id": task_id,
                "state": "DONE",
                "summary": "Verified the changes address the task and the test suite passed.",
                "blockers": [],
                "branch": branch,
                "review": {"passed": True, "verdict": "Correct and complete."},
                "ci": {"status": "passed", "output": "2 passed"},
            }
        )


# --------------------------------------------------------------------------- #
# Prompt-parsing helpers so responses stay self-consistent.
# --------------------------------------------------------------------------- #

def _extract_task_id(prompt: str) -> str:
    m = prompt.split("``", 2)[1] if "``" in prompt else ""
    if m and not m.isdigit():
        m = "".join(ch for ch in m if ch.isdigit()) or m[:8]
    return m or "0"


def _extract_branch(prompt: str) -> str:
    for line in prompt.splitlines():
        if "branch ``" in line:
            parts = line.split("branch ``", 1)
            if len(parts) > 1:
                return parts[1].split("``")[0].strip()
    return ""


def _summarize_change(prompt: str) -> str:
    title_line = next((ln for ln in prompt.splitlines() if ln.startswith("Title:")), "the task")
    title = title_line.split(":", 1)[1].strip() if ":" in title_line else title_line
    return f"Implemented {title} on this branch; committed and verified against the test suite."


# --------------------------------------------------------------------------- #
# Task-graph seeding.
# --------------------------------------------------------------------------- #

def seed_blog_tasks(orch: WorktreeOrchestrator) -> None:
    m = orch.create_milestone("Blog MVP", order=1)

    t1 = orch.create_task("Scaffold blog project structure", description="Create src/ + tests/ dirs, a pyproject.toml, and an AGENTS.md describing conventions.", milestone_id=m.id, priority=5)
    t2 = orch.create_task("Implement post slugify helper", description="Add slugify() and render_post() in src/blog/core.py with unit tests.", milestone_id=m.id, priority=4, dependency_ids=[t1.id])
    t3 = orch.create_task("Add a post listing page", description="Add a view that lists posts sorted by title.", milestone_id=m.id, priority=3, dependency_ids=[t2.id])
    t4 = orch.create_task("Add an RSS feed", description="Render an RSS 2.0 feed of posts.", milestone_id=m.id, priority=2, dependency_ids=[t2.id])
    t5 = orch.create_task("Write integration test for the blog", description="Add an end-to-end test that builds a post and asserts the rendered HTML.", milestone_id=m.id, priority=1, dependency_ids=[t3.id, t4.id])


def run_demo(repo_path: str, quiet: bool = False, step_delay: float = 2.0) -> None:
    project = load_project("myblog", None)
    os.environ.setdefault("ORCHESTRA_DATA_DIR", str(project.state_dir))
    os.environ.setdefault("ORCHESTRA_HOME", str(project.state_root.parent))

    from shared.repositories.json_store import JsonStore

    store = JsonStore(project.state_dir / "orchestra.json")
    transport = RealisticMockTransport(str(project.repo_root))
    orch_core = Orchestrator(store, transport)
    git = Git(str(project.repo_root))
    orch = WorktreeOrchestrator(orch_core, git)

    print("[demo] Project:", project.slug, "->", project.repo_root)
    print("[demo] Transport:", type(transport).__name__)

    # 1) Seed the task graph.
    seed_blog_tasks(orch)
    tasks = orch.tasks.all()
    print(f"[demo] Seeded {len(tasks)} tickets:")
    for t in tasks:
        deps = ", ".join(t.dependency_ids) or "-"
        print(f"      [{t.status.value:9}] {t.title} (deps: {deps})")

    # 1b) Drive the Supervisor -> Coordinator -> Pipeline Manager layers.
    #     Keep the coordinator/pipeline-manager sessions *running* so the web
    #     viewer shows them as active agents until we explicitly settle them.
    print("[demo] Driving Supervisor layer...")
    orch.orch.run_supervisor_request(
        "Plan and build a minimal blog project: a slugify helper, an RSS feed, "
        "a post listing page, and an end-to-end integration test."
    )
    # Keep the top-layer sessions in a "running" state so they show as active.
    orch.orch.set_running_session("supervisor")
    orch.orch.set_running_session("coordinator")
    orch.orch.set_running_session("pipeline-manager")
    print("[demo] Supervisor/Coordinator/Pipeline Manager sessions marked active.")

    if not quiet:
        print("[demo] Watching... starting the worker loop.")

    # 2) Drive the worker -> reviewer -> merge loop, one ticket at a time,
    #    leaving the just-finished worktree's session visible between steps.
    while True:
        ready = orch.pick_ready()
        if not ready:
            break
        for task in ready:
            _drive_one_task(orch, task, transport, project)

    # 3) Final tally.
    tasks = orch.tasks.all()
    done = sum(1 for t in tasks if t.status == Status.DONE)
    print(f"[demo] Complete. {done}/{len(tasks)} tickets DONE.")
    for t in tasks:
        print(f"      [{t.status.value:9}] {t.title}")

    if not quiet:
        print("[demo] All tickets complete. The web viewer shows the finished graph.")


def _drive_one_task(orch: WorktreeOrchestrator, task, transport: Transport, project) -> None:
    from orchestra import agents

    print(f"[demo] Working ticket {task.title!r} [{task.id}]")

    # Mark the task in progress + assign a worker session, and keep the session
    # "running" so the web viewer shows an active agent during the step.
    session = f"worker-{task.slug}"
    print(f"[demo]   worker {session} -> running")
    orch.orch.set_running_session(session)

    rec = orch.create_worktree(task.id, task.slug)
    session_file = project.session_path(session)
    prompt = agents.spawn_worker(orch, task.to_dict(), rec.branch, rec.path, session_file, project=project)
    text = agents.collect_worker(orch, session_file)
    print(f"[demo]   worker finished reading response")

    # Keep the worker session "running" a moment so a live web refresh catches it
    # as an active agent (otherwise it flips to idle the instant it settles).
    orch.orch.set_running_session(session)
    time.sleep(1.2)

    # Build the diff and run the repo's tests for the reviewer.
    diff_info = agents.build_diff(orch.git, rec.branch, project.base_branch)
    review_session = f"reviewer-{task.slug}"
    review_session_file = project.session_path(review_session)
    print(f"[demo]   reviewer {review_session} -> running")
    orch.orch.set_running_session(review_session)
    agents.spawn_reviewer(orch, task.to_dict(), diff_info, review_session_file)
    verdict = agents.collect_reviewer(orch, review_session_file)
    print(f"[demo]   reviewer verdict passed={verdict.review.get('passed')}")

    # Keep the reviewer session "running" a moment for the same reason.
    orch.orch.set_running_session(review_session)
    time.sleep(0.8)

    # Apply the response, informed by the reviewer + CI.
    outcome = orch.apply_ticket_response(task.id, text, review=verdict)
    print(f"[demo]   ticket -> {outcome.task.status.value}")

    if outcome.response.state == "DONE":
        orch.merge_worktree(rec.slug, project.base_branch)
        orch.remove_worktree(rec.slug)
        print(f"[demo]   merged {rec.slug} into {project.base_branch} and cleaned up")
        # The worker/reviewer sessions for a completed ticket go idle.
        orch.orch.set_idle(session)
        orch.orch.set_idle(review_session)
    else:
        print(f"[demo]   not done; leaving worktree {rec.slug} in place")

    # Let the web viewer refresh between tickets so the user can watch progress.
    time.sleep(2.0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Orchestra live demo driver")
    parser.add_argument("--repo", default=None, help="path to the target repo (default: ~/.orchestra/myblog)")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--step-delay", type=float, default=2.0, help="seconds to wait between tickets")
    args = parser.parse_args(argv)

    if args.repo:
        from orchestra.project import list_projects

        target = Path(args.repo).resolve()
        project = None
        for p in list_projects():
            if Path(p.repo_root).resolve() == target:
                project = p
                break
        if project is None:
            raise SystemExit(f"No Orchestra project registered for repo {target}")
    else:
        project = load_project("myblog", None)

    run_demo(str(project.repo_root), quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
