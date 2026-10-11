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
from typing import Any, Sequence

# Ensure the backend root is importable (the orchestrator core lives in backend/).
_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from orchestrator.orchestrator import Orchestrator, MockTransport  # noqa: E402
from orchestra.rpc_transport import RpcTransport  # noqa: E402

from orchestra.gitops import Git, WorktreeManifest, WorktreeRecord  # noqa: E402
from orchestra.project import (  # noqa: E402
    find_repo_root,
    get_repo_slug,
    init_project,
    load_project,
    ProjectError,
    resolve_from_cwd,
)
from orchestra.worktree_orchestrator import WorktreeOrchestrator  # noqa: E402

from shared.models import TestSpec, TestSpecGroup  # noqa: E402
from shared.repositories.test_spec_repository import TestSpecRepository  # noqa: E402
from shared.repositories.build_result_repository import BuildResultRepository  # noqa: E402


def _seed_gate_test_specs(project) -> None:
    """Ensure the merge-gate test specs exist in the project state store.

    Idempotent: only writes when the ``test_specs`` collection is missing or
    empty, so an operator's custom specs are never clobbered. Guards the merge
    gate against a false "completed" pass after a state-store reset wipes it.
    """

    test_spec_repo, _ = _build_gate_store(project)
    if len(list(test_spec_repo.all_ordered())) > 0:
        return

    defaults = (
        ("unit", "python -m pytest backend/orchestrator/tests/ -q"),
        ("ci", "python -m pytest backend -q"),
    )
    for label, command in defaults:
        if test_spec_repo.find_all(label=label):
            continue
        new_spec = TestSpec(
            label=label,
            command=command,
            group=TestSpecGroup.UNIT,
            enabled=True,
        )
        test_spec_repo.save(new_spec)
    print(f"[orchestra] Seeded {len(defaults)} merge-gate test spec(s).")


def _build_gate_store(project) -> tuple:
    """Return ``(test_spec_repo, build_result_repo)`` from the project's state."""

    from shared.repositories.json_store import JsonStore

    store = JsonStore(project.state_dir / "orchestra.json")
    return (
        TestSpecRepository(store),
        BuildResultRepository(store),
    )


def _discover_gate_branches(project, git, manifest=None, active_only=True) -> list[str]:
    """Discover candidate branches to gate from the worktree manifest.

    Returns branch slugs for manifest records. When ``active_only`` is True only
    records whose status is merged/removed are returned (branches worked this run
    and now ready to gate); otherwise every record is returned.

    When the manifest has no records we fall back to any branch that currently
    exists as an Orchestra worktree on disk.
    """

    if manifest is None:
        manifest = git.load_manifest()

    branches: list[str] = []
    seen: set[str] = set()

    for rec in manifest.records:
        branch = rec.branch
        if not branch or branch in seen:
            continue
        # Skip worktrees whose branch no longer exists (e.g. cleaned up).
        if not git.branch_exists(branch):
            continue
        if active_only:
            if rec.status in ("merged", "removed"):
                branches.append(branch)
                seen.add(branch)
        else:
            branches.append(branch)
            seen.add(branch)

    return branches


def _make_gate_engine(project, git, test_spec_repo, build_result_repo, base_branch=None):
    """Build a :class:`MergeGateEngine` backed by the real git worktree adapter.

    The engine expects its ``git`` argument to expose ``create_worktree`` /
    ``checkout`` / ``merge`` / ``current_branch`` / ``branch_exists`` /
    ``remove_worktree`` / ``run``. :class:`GitWorktreeAdapter` adapts
    :class:`orchestra.gitops.Git` to that interface (adding ``merge``/``run`` on
    top of ``Git``'s existing helpers), so the production path and the test
    ``FakeGit`` path share one interface.
    """

    from orchestrator.merge_queue import MergeGateEngine, GitWorktreeAdapter

    base = base_branch or project.base_branch
    return MergeGateEngine(GitWorktreeAdapter(git), test_spec_repo, build_result_repo, base_branch=base)


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

    # The project state store (orchestra.json) is re-created on each orchestrator
    # run from the core collections (tasks/milestones/session_logs). That silently
    # drops the merge-gate ``test_specs`` collection, which would make the gate run
    # 0 tests and report a false "completed". Re-seed the canonical gate specs here
    # so the merge gate always has something to run, even after a state reset.
    _seed_gate_test_specs(project)

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

    # OPTIONAL merge-gate step. Off by default so the existing worker -> reviewer
    # -> merge behavior is 100% unchanged; set ORCHESTRA_RUN_GATE=1 to gate the
    # branches worked this run. Kept purely additive.
    if os.environ.get("ORCHESTRA_RUN_GATE") == "1":
        _run_gate_for_run(project, orch)

    return 0


def _run_gate_for_run(project, orch) -> None:
    """Run the merge gate over branches worked this run (env-gated, additive).

    Discards branches flagged as offenders and prints a warning. Never raises: a
    failed gate here must not crash the orchestrator.
    """

    try:
        git = Git(project.repo_root)
        manifest = git.load_manifest()
        branch_ids = _discover_gate_branches(project, git, manifest, active_only=False)
        if not branch_ids:
            print("[orchestra] Merge gate: no branches to gate this run.")
            return

        test_spec_repo, build_result_repo = _build_gate_store(project)
        engine = _make_gate_engine(project, git, test_spec_repo, build_result_repo)

        # Stale branches left behind by BLOCKED tickets often diverge from the
        # base branch, so ``git merge --no-ff`` against the base worktree is not
        # a fast-forward and raises MergeConflict, aborting the whole gate. Pre
        #-check each candidate: only branches that are fast-forward-mergeable
        # (already an ancestor of the base, or equal to it) are gated. The rest
        # are recorded as dropped so they no longer clog the merge gate.
        ff_branches, non_ff_branches = _classify_fast_forward_branches(git, branch_ids, project.base_branch)
        if non_ff_branches:
            print(
                f"[orchestra] Merge gate skipping non-fast-forward branches: "
                f"{', '.join(non_ff_branches)} (dropped)"
            )

        if not ff_branches:
            print("[orchestra] Merge gate: no fast-forward-mergeable branches to gate this run.")
            return None

        gate = engine.run_gate(ff_branches, project.base_branch)
        gate.dropped_branch_ids = list(set(gate.dropped_branch_ids) | set(non_ff_branches))

        if gate.dropped_branch_ids:
            print(
                f"[orchestra] Merge gate dropped offender branches: "
                f"{', '.join(gate.dropped_branch_ids)}"
            )
        elif gate.status == "escalated":
            print(f"[orchestra] Merge gate escalated: {gate.notes}")
        else:
            print(f"[orchestra] Merge gate completed for run: {', '.join(gate.merged_branch_ids)}")
    except Exception as exc:  # pragma: no cover - defensive, additive path
        print(f"[orchestra] Merge gate step skipped due to error: {exc}")
    return None


def _classify_fast_forward_branches(
    git: Any, branch_ids: Sequence[str], base_branch: str
) -> tuple[list[str], list[str]]:
    """Split ``branch_ids`` into fast-forward-mergeable vs non-fast-forward.

    A branch is fast-forward-mergeable into ``base_branch`` when it is already
    an ancestor of the base (nothing to do) or equal to it -- i.e. merging it
    onto the base is a clean fast-forward. A branch that has diverged from the
    base (the common case for stale branches left by BLOCKED tickets) is not
    fast-forwardable: ``git merge --no-ff`` against the base worktree would
    abort the gate. Those are returned in the second list so the caller can
    drop them instead of failing the whole merge gate.

    Returns ``(fast_forward_branches, non_fast_forward_branches)``.
    """

    if not base_branch or not git.branch_exists(base_branch):
        # Cannot assess fast-forward-ness; keep every branch in the gate rather
        # than silently dropping candidates.
        return list(branch_ids), []

    ff: list[str] = []
    non_ff: list[str] = []
    for branch in branch_ids:
        if not git.branch_exists(branch):
            continue
        if git.is_merged_into(branch, base_branch):
            ff.append(branch)
        else:
            non_ff.append(branch)
    return ff, non_ff


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


_GROUP_ORDER = {g: i for i, g in enumerate(["unit", "ci", "daily"])}


def cmd_test_specs(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    test_spec_repo, build_result_repo = _build_gate_store(project)

    # --health: gate health summary via the Pipeline Agent.
    if getattr(args, "health", False):
        from orchestrator.pipeline_agent import PipelineAgent

        agent = PipelineAgent(test_spec_repo, build_result_repo)
        summary = agent.summarize_gate_health(build_result_repo)
        print("[orchestra] Merge gate health")
        print(f"  total_runs:      {summary['total_runs']}")
        print(f"  overall_pass_rate: {summary['overall_pass_rate']}")
        print(f"  flaky_specs:     {summary['flaky_specs']}")
        print(f"  always_failing:  {summary['always_failing_specs']}")
        for s in summary["slowest_specs"][:5]:
            print(f"    slowest: {s['label']} ({s['max_duration_seconds']}s)")
        return 0

    # --promote-flaky / --daily-flaky: promote flaky unit/ci specs to daily.
    if getattr(args, "promote_flaky", False) or getattr(args, "daily_flaky", False):
        from orchestrator.pipeline_agent import PipelineAgent

        agent = PipelineAgent(test_spec_repo, build_result_repo)
        assessments = agent.detect_flaky_tests(build_result_repo)
        promoted = agent.promote_flaky_to_daily(assessments, test_spec_repo)
        if promoted:
            print(f"[orchestra] Promoted {len(promoted)} flaky spec(s) to daily: {', '.join(promoted)}")
        else:
            print("[orchestra] No flaky specs to promote.")
            for a in assessments:
                if a.flaky:
                    print(f"  flaky: {a.label} ({a.failures}/{a.runs} failures)")
        return 0

    # --enable / --disable by id.
    if getattr(args, "enable", None):
        spec = test_spec_repo.find(args.enable)
        spec.enabled = True
        test_spec_repo.save(spec)
        print(f"[orchestra] Enabled test spec {spec.id} ({spec.label})")
        return 0
    if getattr(args, "disable", None):
        spec = test_spec_repo.find(args.disable)
        spec.enabled = False
        test_spec_repo.save(spec)
        print(f"[orchestra] Disabled test spec {spec.id} ({spec.label})")
        return 0

    # --add <label> <command> [--group ...].
    if getattr(args, "add", None):
        label, command = args.add
        from shared.models import TestSpecGroup

        group = TestSpecGroup(args.group or "unit")
        new_spec = TestSpec(label=label, command=command, group=group)
        test_spec_repo.save(new_spec)
        print(f"[orchestra] Added test spec {new_spec.id!r} ({label!r}) group={group.value}: {command!r}")
        return 0

    # --list (default): show every spec with group, enabled status, failure_count.
    specs = test_spec_repo.all_ordered()
    print(f"[orchestra] Test specs ({len(specs)}):")
    if not specs:
        print("  (none -- add one with: orchestra test-specs --add <label> <command>)")
    for s in specs:
        flags = "enabled" if s.enabled else "disabled"
        print(f"  {s.id}  [{s.group.value:4}] {flags:8} fails={s.failure_count}  {s.label} :: {s.command}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    project, _ = _resolve_project(args)
    git = Git(project.repo_root)
    test_spec_repo, build_result_repo = _build_gate_store(project)
    engine = _make_gate_engine(project, git, test_spec_repo, build_result_repo)

    base = args.base or project.base_branch

    # Branch selection: explicit --branches wins, else discover from the manifest.
    if args.branches:
        branch_ids = [b.strip() for b in args.branches.split(",") if b.strip()]
    else:
        branch_ids = _discover_gate_branches(project, git, git.load_manifest(), active_only=False)

    if not branch_ids:
        print("[orchestra] No branches to gate. Pass --branches a,b,c or add worktrees to the manifest.")
        return 0

    print(f"[orchestra] Running merge gate on {len(branch_ids)} branch(es) against {base!r}: {', '.join(branch_ids)}")

    gate = engine.run_gate(branch_ids, base)

    # Canonical gate report: pass/fail counts + failed tests + bisection outcome.
    report = gate.to_report()
    print(f"[orchestra] Gate {gate.status.upper()}")
    print(
        f"  results: {report['total_results']} total, "
        f"{report['total_results'] - report['failed_results']} passed, "
        f"{report['failed_results']} failed"
    )
    if report["failed_tests"]:
        print(f"  failed tests: {', '.join(report['failed_tests'])}")

    # Bisection outcome (if the gate failed and was resolved).
    if gate.bisection is not None:
        b = gate.bisection
        print(f"  bisection rounds: {b.rounds}")
        print(f"  offender: {b.offender if b.offender else 'none'}")
        print(f"  merged safe: {', '.join(b.merged_branches) or '-'}")
        print(f"  dropped: {', '.join(b.dropped_branches) or '-'}")
    if gate.notes:
        print(f"  notes: {gate.notes}")

    # --auto: resolve failures automatically; escalate -> brainstorm recovery.
    if args.auto and gate.status != "completed":
        gate = engine.resolve_failure(gate, base)
        print(f"[orchestra] Auto-resolved gate -> {gate.status.upper()}")
        print(f"  merged safe: {', '.join(gate.merged_branch_ids) or '-'}")
        print(f"  dropped: {', '.join(gate.dropped_branch_ids) or '-'}")
        if gate.notes:
            print(f"  notes: {gate.notes}")
        if gate.status == "escalated":
            from orchestrator.pipeline_agent import PipelineAgent

            report = PipelineAgent().brainstorm_recovery(gate.notes, str(project.repo_root))
            print("[orchestra] Recovery brainstorm:")
            for finding in report.findings:
                print(f"  finding: {finding}")
            for suggestion in report.suggestions:
                print(f"  suggestion: {suggestion}")
            for ticket in report.proposed_tickets:
                print(f"  proposed ticket: {ticket}")

    # Final status.
    if gate.status == "escalated":
        print("[orchestra] Final status: ESCALATED -- Pipeline Agent takeover required.")
        return 1
    print("[orchestra] Final status: completed.")
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

    p_specs = sub.add_parser("test-specs", help="manage merge-test test specs")
    add_common(p_specs)
    p_specs.add_argument("--add", nargs=2, metavar=("LABEL", "COMMAND"), help="register a new test spec")
    p_specs.add_argument("--group", choices=["unit", "ci", "daily"], default="unit", help="test spec group (default: unit)")
    p_specs.add_argument("--list", action="store_true", help="list all test specs (default)")
    p_specs.add_argument("--enable", metavar="ID", help="enable a test spec by id")
    p_specs.add_argument("--disable", metavar="ID", help="disable a test spec by id")
    p_specs.add_argument("--promote-flaky", action="store_true", help="promote flaky unit/ci specs to the daily round")
    p_specs.add_argument("--daily-flaky", action="store_true", help="alias for --promote-flaky")
    p_specs.add_argument("--health", action="store_true", help="print merge-gate health summary")
    p_specs.set_defaults(func=cmd_test_specs)

    p_gate = sub.add_parser("gate", help="run the merge gate for pending branches")
    add_common(p_gate)
    p_gate.add_argument("--branches", metavar="A,B,C", help="explicit branch slugs/ids to gate (default: discover from manifest)")
    p_gate.add_argument("--base", metavar="BRANCH", help="base branch to gate against (default: project base)")
    p_gate.add_argument("--auto", action="store_true", help="auto-resolve failures (bisect + merge safe + drop offender)")
    p_gate.set_defaults(func=cmd_gate)

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
