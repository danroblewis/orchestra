"""Drive a *collaborative* orchestration of the Orchestra project itself.

The four layers are modelled as **persistent, long-lived agent sessions** that
work *concurrently* rather than as a sequential chain:

* **supervisor**  -- the interactive layer. Sends requests to the coordinator and
  pipeline manager as the user's needs change.
* **coordinator** -- keeps the task queue accurate/prioritised, assigns ready
  tickets to workers, and reports what it picked.
* **pipeline-manager** -- watches the merge queue / builds and coordinates fixes.
* **workers**     -- spawned per ticket to do the actual work (and a reviewer).

Unlike a sequential driver (supervisor → coordinator → workers, blocking on each),
this driver runs the top layers **in their own threads**, each polling its domain:
the supervisor dispatches, the coordinator re-plans, the pipeline manager watches.
Workers execute whatever is ready. Every layer stays "running" in the web viewer
while it works, so you watch tickets flow ``BACKLOG -> IN_PROGRESS -> DONE`` across
real Pi sessions.

Each turn is bounded (``--turn-timeout``) and wrapped so one slow/dead agent can
never stall the whole run.

Run it while ``orchestra web`` is open against the same project.

Usage:
    python3 -m orchestra.self_orchest --project orchestra --force

Environment:
    PI_BINARY            path to the pi CLI (defaults to `pi` on PATH)
    PI_MODEL / PI_PROVIDER the pi model/provider to use
    ORCHESTRA_DATA_DIR   where project state + sessions live (set by the CLI)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from orchestrator.orchestrator import Orchestrator  # noqa: E402
from orchestra.project import load_project  # noqa: E402
from orchestra.rpc_transport import RpcTransport  # noqa: E402


LAYER_PROMPTS = {
    "supervisor": (
        "You are the Supervisor layer of Orchestra, the interactive layer the human "
        "talks to. You translate user requirements into structured tickets with "
        "milestones and dependencies, and you dispatch coordination requests to the "
        "Coordinator and Pipeline Manager as the situation changes. Keep responses "
        "terse: list the tickets you want worked next and any pipeline notes."
    ),
    "coordinator": (
        "You are the Coordinator layer of Orchestra. You monitor the task queue, keep "
        "it prioritized, ordered and accurate, assign ready tickets to workers, and "
        "report what you picked. Re-plan whenever a new request arrives. Respond "
        "concisely with the tickets you would pick next and why."
    ),
    "pipeline-manager": (
        "You are the Pipeline Manager layer of Orchestra. You watch the merge queue "
        "and build results, coordinate fixes for failures, and keep the pipeline "
        "efficient. Respond concisely with your current plan and anything blocking."
    ),
    "worker": (
        "You are a Worker layer of Orchestra. You implement a single ticket by editing "
        "code in your worktree, verify it, then report a structured ticket-hygiene "
        "response. Keep changes small, safe, and committed on your branch."
    ),
}


def _seed(orch: Orchestrator) -> str:
    """Create one milestone + two small, safe doc tasks on the Orchestra repo.

    Returns the milestone id so the driver can scope all work to it and ignore
    any leftover tasks from a concurrent/earlier run (e.g. a stray ``orchestra """
    ms = orch.create_milestone("Self-orchestration demo", order=0)
    orch.create_task(
        "Plan README self-orchestration note",
        description=(
            "Describe (do not edit) the minimal README change: a bullet under a 'Live "
            "demo' heading noting Orchestra can orchestrate work on its own repo."
        ),
        milestone_id=ms.id,
    )
    orch.create_task(
        "Plan PLAN.md self-orchestration placeholder",
        description=(
            "Describe (do not edit) adding one line to PLAN.md noting self-orchestration "
            "was exercised as a demo."
        ),
        milestone_id=ms.id,
    )
    return ms.id


def _ready_tasks(orch: Orchestrator, milestone_id: str) -> list:
    """BACKLOG tasks whose dependencies are all DONE and which are not already
    in flight. A task already marked in_progress is being worked on by another
    thread, so it is skipped here to avoid double-driving it."""
    done_ids = {t.id for t in orch.tasks.by_status("done")}
    active_ids = {t.id for t in orch.tasks.by_status("in_progress")}
    return [t for t in orch.tasks.next_in_queue(limit=100)
            if t.milestone_id == milestone_id
            and t.id not in done_ids
            and t.id not in active_ids
            and all(d in done_ids for d in t.dependency_ids)]


def _drive(orch: Orchestrator, name: str, layer: str, prompt: str,
           system_prompt: str, timeout: int) -> str:
    """Drive one turn of a session with a bounded timeout and error handling.

    Keeps the session "running" afterwards so the web viewer shows it as active
    (the session is long-lived and will receive more requests).
    """
    try:
        text = orch.drive(name, layer, prompt, system_prompt=system_prompt)
        print(f"[collab]   {name}: {text[:120]!r}", flush=True)
    except Exception as exc:  # one slow/dead agent must never stall the run
        print(f"[collab]   {name} turn error: {exc}", flush=True)
        text = ""
    orch.set_running_session(name)
    return text


def _worker_one(orch: Orchestrator, task, timeout: int) -> None:
    """Drive one worker + reviewer for a ticket."""
    slug = task.slug
    worker_name = f"worker-{slug}"
    review_name = f"reviewer-{slug}"
    print(f"[collab]   worker -> {task.title[:50]}", flush=True)
    _drive(orch, worker_name, "worker",
           f"Implement task: {task.title}\n\n{task.description}",
           LAYER_PROMPTS["worker"], timeout)

    verdict = _drive(orch, review_name, "reviewer",
                     f"Review the worker's work for: {task.title}. Report pass/fail.",
                     "You are the reviewer layer of Orchestra. Assess whether the "
                     "worker's changes satisfy the ticket. Reply with a short verdict.",
                     timeout)
    orch.set_idle(review_name)

    if "pass" in verdict.lower() or "done" in verdict.lower():
        orch.mark_done(task.id)
        print(f"[collab]   ticket -> DONE", flush=True)
    else:
        orch.set_idle(worker_name)
        print(f"[collab]   ticket review failed (kept open)", flush=True)
    time.sleep(0.3)


def _worker_thread(orch: Orchestrator, stop: threading.Event, timeout: int,
                   milestone_id: str) -> None:
    """Claim and complete ready tickets until stopped. Exits early once every
    ticket in the milestone is done and none are in flight, so a finished run
    does not leave worker/reviewer sessions marked 'running' with no work."""
    while not stop.is_set():
        ready = _ready_tasks(orch, milestone_id)
        if ready:
            for task in ready:
                if stop.is_set():
                    break
                _worker_one(orch, task, timeout)
        else:
            # Nothing left to do: no ready tasks and none in flight. Exit so the
            # run can finish cleanly instead of spinning forever.
            break
        time.sleep(0.3)


def _supervisor_thread(orch: Orchestrator, stop: threading.Event,
                       user_request: str, first: bool, timeout: int) -> None:
    """Supervisor: dispatch to coordinator + pipeline manager, react, and may add
    tickets. Runs a few rounds then yields."""
    round_no = 0
    while not stop.is_set() and round_no < 3:
        round_no += 1
        _drive(orch, "supervisor", "supervisor",
               user_request if first else "[coord/pm] React and dispatch next actions.",
               LAYER_PROMPTS["supervisor"], timeout)
        first = False
        time.sleep(0.2)


def _coordinator_thread(orch: Orchestrator, stop: threading.Event, timeout: int,
                        milestone_id: str) -> None:
    """Coordinator: re-plan the queue against whatever is ready."""
    round_no = 0
    while not stop.is_set() and round_no < 3:
        round_no += 1
        ready = _ready_tasks(orch, milestone_id)
        hint = f"Ready tickets: {', '.join(t.title[:30] for t in ready) or '(none)'}"
        _drive(orch, "coordinator", "coordinator",
               f"[supervisor] Re-plan. {hint}. Report what you pick and why.",
               LAYER_PROMPTS["coordinator"], timeout)
        time.sleep(0.2)


def _pm_thread(orch: Orchestrator, stop: threading.Event, timeout: int,
               milestone_id: str) -> None:
    """Pipeline manager: report on the queue / builds / fixes."""
    round_no = 0
    while not stop.is_set() and round_no < 3:
        round_no += 1
        ready = _ready_tasks(orch, milestone_id)
        _drive(orch, "pipeline-manager", "pipeline-manager",
               f"[supervisor] Report build/merge status. {len(ready)} ticket(s) ready.",
               LAYER_PROMPTS["pipeline-manager"], timeout)
        time.sleep(0.2)


def _run(orch: Orchestrator, stop: threading.Event, timeout: int,
         milestone_id: str) -> None:
    user_request = "Exercise Orchestra by orchestrating work on its own repo."
    threads = [
        threading.Thread(target=_supervisor_thread,
                         args=(orch, stop, user_request, True, timeout), name="supervisor"),
        threading.Thread(target=_coordinator_thread,
                         args=(orch, stop, timeout, milestone_id), name="coordinator"),
        threading.Thread(target=_pm_thread,
                         args=(orch, stop, timeout, milestone_id), name="pipeline-manager"),
        threading.Thread(target=_worker_thread,
                         args=(orch, stop, timeout, milestone_id), name="workers"),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 30)
    # Everything is idle once the run ends: mark the top layers AND every
    # worker/reviewer session idle so the web viewer never shows a session as
    # 'running' with no live agent behind it.
    for name in ("supervisor", "coordinator", "pipeline-manager"):
        orch.set_idle(name)
    for slug in (orch.tasks.by_milestone(milestone_id) if milestone_id else []):
        for suffix in ("worker-", "reviewer-"):
            orch.set_idle(f"{suffix}{slug.slug}")
    print("[collab] Collaborative run complete.", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collaboratively self-orchestrate the Orchestra repo")
    p.add_argument("--project", default="orchestra")
    p.add_argument("--force", action="store_true")
    p.add_argument("--turn-timeout", type=int, default=300,
                   help="Per-turn Pi timeout in seconds (default 300)")
    args = p.parse_args(argv)

    project = load_project(args.project, repo_root=None)
    repo_root = str(project.repo_root)
    print(f"[collab] Project: {args.project} -> {repo_root}", flush=True)

    from shared.repositories.json_store import JsonStore

    transport = RpcTransport(timeout=args.turn_timeout, cwd=repo_root)
    store = JsonStore(project.state_dir / "orchestra.json")
    orch = Orchestrator(store, transport)

    milestone_id = None
    if not orch.tasks.all() or args.force:
        milestone_id = _seed(orch)
        print(f"[collab] Seeded milestone + tasks.", flush=True)

    stop = threading.Event()
    if milestone_id is None:
        existing = orch.milestones.find_all(name="Self-orchestration demo")
        milestone_id = existing[0].id if existing else None
    print(f"[collab] Scoping to milestone {milestone_id}", flush=True)
    print("[collab] Starting collaborative orchestration (concurrent layers)...", flush=True)
    try:
        _run(orch, stop, args.turn_timeout, milestone_id)
    except KeyboardInterrupt:
        stop.set()
    transport.close_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
