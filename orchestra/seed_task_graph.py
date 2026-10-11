"""Seed the Orchestra task graph as the Supervisor would.

This is the Supervisor's job: translate the project vision into a structured
task graph — milestones, tasks, and dependency relationships — then hand it to
the Coordinator. The tasks themselves are implemented by the worker agents.

We build a realistic graph covering the UI, orchestration mechanics, persistence,
and self-hosting work identified for Orchestra. Dependencies express the natural
order things must be built in (e.g. you can't build the task-graph UI before the
task model is queryable, you can't self-host before the real transport is stable).

Run against a clean project state. Does NOT drive any agents — it only builds the
graph so the Coordinator can pick from it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from orchestrator.orchestrator import Orchestrator  # noqa: E402
from orchestra.rpc_transport import RpcTransport  # noqa: E402
from shared.models import Status  # noqa: E402
from shared.repositories.json_store import JsonStore  # noqa: E402


def build_graph(orch: Orchestrator) -> None:
    """Create all milestones and tasks with dependencies. Returns nothing;
    the graph is persisted via the orchestrator's repositories."""

    # ------------------------------------------------------------------
    # Milestone 1: Core orchestration mechanics
    # The four layers must work collaboratively and reliably before anything
    # on top of them makes sense.
    # ------------------------------------------------------------------
    ms_core = orch.create_milestone("Core orchestration mechanics", order=0)

    t_real_transport = orch.create_task(
        "Stabilize real Pi RPC transport for all layers",
        description=(
            "The supervisor and pipeline-manager layers currently time out or fall "
            "back to mock responses under concurrent load. Make `RpcTransport` in "
            "orchestra/rpc_transport.py reliably drive real Pi sessions for all four "
            "layers without mock fallback. Add logging so failures are visible. "
            "This is the foundation — everything else depends on real agents working."
        ),
        milestone_id=ms_core.id,
        priority=1,
    )
    t_store_threadsafe = orch.create_task(
        "Ensure JsonStore is thread-safe for concurrent layers",
        description=(
            "The four agent layers run in concurrent threads and share one JsonStore. "
            "Verify all reads/writes are serialized (lock or per-collection lock) so a "
            "layer finishing a turn never clobbers another layer's concurrent write. "
            "Add a concurrency test that spins up multiple writers and asserts no data "
            "loss."
        ),
        milestone_id=ms_core.id,
        priority=2,
        dependency_ids=[t_real_transport.id],
    )
    t_lifecycles = orch.create_task(
        "Define clear session lifecycles for each layer",
        description=(
            "Currently worker/reviewer sessions can get stuck 'running' with no live "
            "agent after a run ends. Define and implement clean lifecycles: when a "
            "layer finishes its work, its session must be marked idle (or removed from "
            "the active view). A session must never show 'running' with no process "
            "behind it. Document the lifecycle in the orchestrator."
        ),
        milestone_id=ms_core.id,
        priority=3,
        dependency_ids=[t_real_transport.id],
    )

    # ------------------------------------------------------------------
    # Milestone 2: Web UI — task management
    # The web viewer is the primary interface. Tasks are the core unit.
    # ------------------------------------------------------------------
    ms_ui_tasks = orch.create_milestone("Web UI: task management", order=1)

    t_task_graph_viz = orch.create_task(
        "Build task graph visualization",
        description=(
            "The spec calls for a directed-graph visualization of milestones -> tasks "
            "-> dependencies. Add a React Flow (or similar) canvas that renders the "
            "task graph: nodes are tasks (colored by status), edges are dependencies, "
            "milestones are grouped. Support zoom/pan and clicking a node to open the "
            "task detail modal. This is high-visibility — it's the 'look at the system "
            "working' surface."
        ),
        milestone_id=ms_ui_tasks.id,
        priority=1,
    )
    t_add_task_ui = orch.create_task(
        "Add task creation from the web UI",
        description=(
            "Users must be able to create a ticket directly from the web UI (title, "
            "description, priority, milestone, dependencies). Add a form/modal for it "
            "and an API endpoint (POST /api/tasks) that persists through the repo. "
            "A created task should appear immediately (or within the 2s refresh) and "
            "be eligible for the Coordinator to pick up."
        ),
        milestone_id=ms_ui_tasks.id,
        priority=2,
        dependency_ids=[t_task_graph_viz.id],
    )
    t_edit_task_ui = orch.create_task(
        "Edit task properties from the web UI",
        description=(
            "Allow editing an existing task's status, priority, description, and "
            "dependencies from the task detail modal. Changes must persist through the "
            "repository and reflect in the graph view. Deleting a task should be "
            "confirmed and clean up its dependencies."
        ),
        milestone_id=ms_ui_tasks.id,
        priority=3,
        dependency_ids=[t_add_task_ui.id],
    )

    # ------------------------------------------------------------------
    # Milestone 3: Web UI — agent/session visibility
    # Watch the agents work. This is where the 'alive' feeling comes from.
    # ------------------------------------------------------------------
    ms_ui_agents = orch.create_milestone("Web UI: agent visibility", order=2)

    t_agent_status = orch.create_task(
        "Refine agent cards to show ownership and last message",
        description=(
            "Agent cards should clearly show which agent is working on which ticket, "
            "its current status, and its last message. Completed reviewers/workers "
            "that are idle should not clutter the active view (filter or fold them "
            "into an expandable 'completed' section). The colored left-border "
            "indicating agent type must be consistent. Ensure a card never says "
            "'active' with no real work happening."
        ),
        milestone_id=ms_ui_agents.id,
        priority=1,
        dependency_ids=[t_lifecycles.id],
    )
    t_session_transcript = orch.create_task(
        "Improve session transcript view in agent modal",
        description=(
            "Clicking an agent opens a modal with its transcript. Make it scrollable, "
            "show timestamps, and distinguish user/system/assistant messages clearly. "
            "If the transcript is long, it should not block rendering. This is how you "
            "audit what an agent actually did."
        ),
        milestone_id=ms_ui_agents.id,
        priority=2,
        dependency_ids=[t_agent_status.id],
    )

    # ------------------------------------------------------------------
    # Milestone 4: Orchestration intelligence
    # Make the system actually manage work, not just simulate it.
    # ------------------------------------------------------------------
    ms_intel = orch.create_milestone("Orchestration intelligence", order=3)

    t_next_in_queue = orch.create_task(
        "Make 'Next in Queue' reflect real readiness",
        description=(
            "The 'Next in Queue' panel currently says 'Nothing ready yet' even when "
            "backlog tasks exist. Fix the readiness logic: a task is ready when all its "
            "dependencies are DONE and it is not already in progress. Surface the top "
            "3-5 ready tasks (by priority) so the human sees what's next."
        ),
        milestone_id=ms_intel.id,
        priority=1,
        dependency_ids=[t_store_threadsafe.id],
    )
    t_dependency_graph_live = orch.create_task(
        "Live-upgrade dependency graph when tasks change",
        description=(
            "When a new ticket is added or a dependency is set, the task graph "
            "visualization should update live without a full page reload. Wire the graph "
            "component to the same state feed that powers the task list so additions and "
            "status changes propagate."
        ),
        milestone_id=ms_intel.id,
        priority=2,
        dependency_ids=[t_task_graph_viz.id, t_edit_task_ui.id],
    )
    t_verifier_loop = orch.create_task(
        "Implement the verifier/review loop with structured responses",
        description=(
            "Workers must produce structured ticket-hygiene JSON (state, summary, "
            "blockers, review verdict, CI status) and the reviewer must actually check "
            "the work (for code tasks, run the repo's tests). A task is only DONE when "
            "the reviewer passes. Enforce this loop in the coordinator/worker flow and "
            "make failures visible in the UI."
        ),
        milestone_id=ms_intel.id,
        priority=3,
        dependency_ids=[t_real_transport.id, t_task_graph_viz.id],
    )

    # ------------------------------------------------------------------
    # Milestone 5: Self-hosting — Orchestra managing itself
    # The ambitious goal: use Orchestra to manage Orchestra's own dev cycle.
    # ------------------------------------------------------------------
    ms_self = orch.create_milestone("Self-hosting: Orchestra managing itself", order=4)

    t_real_transport_demo = orch.create_task(
        "Run a real self-orchestration against the Orchestra repo",
        description=(
            "Wire the real transport (from t_real_transport) into a driver that seeds "
            "a milestone of real, safe tasks against the Orchestra repo itself and "
            "drives them through the full supervisor -> coordinator -> worker -> "
            "reviewer loop with real Pi agents. This proves Orchestra can manage its "
            "own development. Start with doc-only tasks to de-risk, then expand."
        ),
        milestone_id=ms_self.id,
        priority=1,
        dependency_ids=[t_real_transport.id, t_lifecycles.id, t_verifier_loop.id],
    )
    t_state_decoupled = orch.create_task(
        "Confirm state is decoupled from the target repo",
        description=(
            "Orchestra's state (tasks, sessions, builds) must live in ~/.orchestra/"
            "<project>/, NOT in the repo being managed. Verify that self-hosting "
            "doesn't pollute the Orchestra repo with orchestration artifacts, and that "
            "the web server reads state from the project dir regardless of CWD."
        ),
        milestone_id=ms_self.id,
        priority=2,
        dependency_ids=[t_real_transport_demo.id],
    )
    t_multi_project = orch.create_task(
        "Support running multiple projects side by side",
        description=(
            "The web server and driver should support switching between projects "
            "(--project flag) without state collisions. Verify two projects can be "
            "seeded and viewed independently, each with its own state dir and tunnel "
            "metadata. This is needed if Orchestra is to manage multiple repos."
        ),
        milestone_id=ms_self.id,
        priority=3,
        dependency_ids=[t_state_decoupled.id],
    )

    # Print a summary of what was built.
    print(f"[supervisor] Seeded {len(orch.tasks.all())} tasks across "
          f"{len(orch.milestones.ordered())} milestones.")
    for m in orch.milestones.ordered():
        tasks = orch.tasks.by_milestone(m.id)
        print(f"  {m.name}: {len(tasks)} tasks")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Seed the Orchestra task graph")
    p.add_argument("--project", default="orchestra")
    p.add_argument("--force", action="store_true",
                   help="Seed even if tasks already exist (clears first)")
    args = p.parse_args()

    from orchestra.project import load_project  # noqa: E402

    project = load_project(args.project, repo_root=None)
    repo_root = str(project.repo_root)

    # If not force and there are already tasks, ask before rebuilding.
    _store = JsonStore(project.state_dir / "orchestra.json")
    from shared.repositories.task_repository import TaskRepository  # noqa: E402
    if TaskRepository(_store).all() and not args.force:
        print("[supervisor] Tasks already exist. Re-run with --force to rebuild.")
        return 0
    if args.force:
        # Clear existing state for a clean seed.
        import shutil  # noqa: E402
        store_file = project.state_dir / "orchestra.json"
        if store_file.exists():
            store_file.unlink()

    os.environ.setdefault("ORCHESTRA_DATA_DIR", str(project.state_dir))

    transport = RpcTransport(timeout=60, cwd=repo_root)
    store = JsonStore(project.state_dir / "orchestra.json")
    orch = Orchestrator(store, transport)

    build_graph(orch)
    print("[supervisor] Task graph ready for the Coordinator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
