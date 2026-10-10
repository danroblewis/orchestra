"""The ``orchestra`` command line interface.

Subcommands (v1):

- ``orchestra init`` -- register the current repo as an Orchestra project and
  create ``~/.orchestra/<slug>/`` state.
- ``orchestra run`` -- drive the orchestration loop (pickup -> spawn -> collect
  -> review/merge -> cleanup).
- ``orchestra web`` -- start the read-only web viewer.
- ``orchestra tickets`` -- list tickets in the task graph.
- ``orchestra worktrees`` -- list Orchestra-managed worktrees.
- ``orchestra clean`` -- remove leftover Orchestra worktrees on disk.

The CLI resolves the project from the current working directory (assumed to be
the repo root) or from ``--project``/``--repo`` overrides.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure the backend root is importable (the orchestrator core lives in backend/).
_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from orchestrator.orchestrator import Orchestrator, MockTransport  # noqa: E402
from orchestra.rpc_transport import RpcTransport  # noqa: E402

from orchestra.gitops import Git  # noqa: E402
from orchestra.project import (  # noqa: E402
    find_repo_root,
    get_repo_slug,
    init_project,
    load_project,
    ProjectError,
    resolve_from_cwd,
)
from orchestra.worktree_orchestrator import WorktreeOrchestrator  # noqa: E402


def _resolve_project(args: argparse.Namespace):
    """Return ``(project, repo_root_path_string)`` for ``--project`` or CWD."""
    project_arg = getattr(args, "project", None)
    if project_arg:
        project = load_project(project_arg, None)
        repo_root = project.config.get("repo_root")
        return project, str(repo_root) if repo_root else str(project.repo_root)

    # Otherwise, resolve from the current working directory (repo root).
    cwd = Path.cwd()
    repo_root = find_repo_root(cwd)
    project = resolve_from_cwd(repo_root)
    return project, str(project.repo_root)


def _build_orchestrator(project) -> WorktreeOrchestrator:
    os.environ.setdefault("ORCHESTRA_HOME", str(project.state_root.parent))
    os.environ.setdefault("ORCHESTRA_DATA_DIR", str(project.state_dir))

    from shared.repositories.json_store import JsonStore

    store = JsonStore(project.state_dir / "orchestra.json")

    transport: Transport
    if os.environ.get("ORCHESTRA_TRANSPORT", "mock") == "rpc":
        pi_binary = os.environ.get("PI_BINARY", "pi")
        transport = RpcTransport(pi_binary=pi_binary, cwd=project.repo_root)
    else:
        transport = MockTransport()

    orchestrator = Orchestrator(store, transport)
    git = Git(project.repo_root)
    manifest = git.load_manifest()
    return WorktreeOrchestrator(orchestrator, git, manifest)


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    repo = args.repo or str(Path.cwd())
    project = init_project(
        repo,
        slug=args.slug,
        base_branch=args.base_branch,
        model=args.model,
    )
    print(f"[orchestra] Initialized project {project.slug!r} at {project.state_root}")
    print(f"[orchestra] Config: {project.config_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    orch = _build_orchestrator(project)
    print(f"[orchestra] Running in project {project.slug!r}")

    # Reconcile stale worktrees first (from a crashed run).
    cleaned = orch.reconcile()
    if cleaned:
        print(f"[orchestra] Reconciled stale worktrees: {', '.join(cleaned)}")

    picked = orch.pick_ready()
    print(f"[orchestra] Ready to start: {len(picked)} ticket(s)")
    for t in picked:
        print(f"  -> {t.title} [{t.id}]")

    from orchestra import agents

    transport = orch.orch.transport
    if transport is None:
        print("[orchestra] No transport configured; set ORCHESTRA_TRANSPORT=rpc and a Pi model.")
        return 1

    # Drive up to N ready tickets through the full worker -> reviewer -> merge loop.
    max_tickets = min(len(picked), 1)
    for task in picked[:max_tickets]:
        print(f"[orchestra] Working ticket: {task.title} [{task.id}]")
        rec = orch.create_worktree(task.id, task.slug)
        print(f"[orchestra] Worker branch {rec.branch} at {rec.path}")

        # 1) Spawn the worker inside the worktree and let it do the work.
        session = f"worker-{rec.slug}"
        session_file = project.session_path(session)
        prompt = agents.spawn_worker(
            orch, task.to_dict(), rec.branch, rec.path, session_file, project=project
        )
        text = agents.collect_worker(orch, session_file)
        print(f"[orchestra] Worker finished; state={rec.branch} -> reading response")

        # 2) Build the diff and run the repo's tests; pass them to the reviewer.
        diff_info = agents.build_diff(orch.git, rec.branch, project.base_branch)
        review_session = f"reviewer-{rec.slug}"
        review_session_file = project.session_path(review_session)
        agents.spawn_reviewer(
            orch, task.to_dict(), diff_info, review_session_file
        )
        verdict = agents.collect_reviewer(orch, review_session_file)
        print(f"[orchestra] Reviewer verdict: passed={verdict.review.get('passed')}")

        # 3) Apply the worker response, informed by the reviewer + CI.
        outcome = orch.apply_ticket_response(task.id, text, review=verdict)
        print(f"[orchestra] Ticket state after apply: {outcome.task.status.value}")

        if outcome.response.state == "DONE":
            orch.merge_worktree(rec.slug, project.base_branch)
            orch.remove_worktree(rec.slug)
            print(f"[orchestra] Merged and cleaned up {rec.slug}")
        else:
            print(f"[orchestra] Ticket not done; leaving worktree {rec.slug} in place")
        transport.close(session)
        transport.close(review_session)
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    project, cwd = _resolve_project(args)
    os.environ.setdefault("ORCHESTRA_DATA_DIR", str(project.state_dir))
    os.environ.setdefault("ORCHESTRA_HOME", str(project.state_root.parent))

    # Import the backend web server module and start it.
    sys.path.insert(0, str(_BACKEND_ROOT))
    from web.server import run_server  # noqa: E402

    print(f"[orchestra] Starting web viewer for project {project.slug!r} on port {args.port}")
    return run_server(web_port=args.port, tunnel=args.tunnel)


def cmd_tickets(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    orch = _build_orchestrator(project)
    print(f"[orchestra] Tickets in project {project.slug!r}:")
    for t in orch.tasks.all():
        deps = ", ".join(t.dependency_ids) or "-"
        print(f"  [{t.status.value:9}] {t.title} (deps: {deps})")
    return 0


def cmd_worktrees(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    orch = _build_orchestrator(project)
    active = orch.active_worktrees()
    if not active:
        print("[orchestra] No active worktrees.")
        return 0
    for r in active:
        print(f"  {r.slug:20} {r.branch:24} {r.status} ({r.path})")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    orch = _build_orchestrator(project)
    cleaned = orch.reconcile()
    print(f"[orchestra] Removed {len(cleaned)} stale worktree(s): {', '.join(cleaned) or '-'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestra", description="Orchestra orchestration CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser):
        p.add_argument("--project", help="project slug under ~/.orchestra")
        p.add_argument("--repo", help="path to repo root")
        p.add_argument("--force", action="store_true", help="re-initialize if already exists")

    p_init = sub.add_parser("init", help="register this repo as an Orchestra project")
    add_common(p_init)
    p_init.add_argument("--base_branch", default="main", help="base branch to merge into")
    p_init.add_argument("--model", default=None, help="Pi model to use for workers")
    p_init.add_argument("--slug", default=None, help="explicit project slug")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="run the orchestration loop")
    add_common(p_run)
    p_run.set_defaults(func=cmd_run)

    p_web = sub.add_parser("web", help="start the read-only web viewer")
    add_common(p_web)
    p_web.add_argument("--port", type=int, default=8000, help="port to listen on")
    p_web.add_argument("--tunnel", action="store_true", help="start a cloudflared tunnel")
    p_web.set_defaults(func=cmd_web)

    p_tix = sub.add_parser("tickets", help="list tickets")
    add_common(p_tix)
    p_tix.set_defaults(func=cmd_tickets)

    p_wt = sub.add_parser("worktrees", help="list active worktrees")
    add_common(p_wt)
    p_wt.set_defaults(func=cmd_worktrees)

    p_clean = sub.add_parser("clean", help="remove stale Orchestra worktrees")
    add_common(p_clean)
    p_clean.set_defaults(func=cmd_clean)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Some handlers need repo/project resolution before running.
    if args.command != "init" and not getattr(args, "force", False):
        try:
            _resolve_project(args)
        except ProjectError as exc:
            print(f"[orchestra] Error: {exc}")
            return 2

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
