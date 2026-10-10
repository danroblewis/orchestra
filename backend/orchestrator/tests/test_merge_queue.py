"""Engine tests for the merge gate (Phase 3d).

These exercise ``MergeGateEngine`` WITHOUT real git by injecting a fake ``runner``
and a fake ``git`` object. The runner decides pass/fail by consulting the set of
branches that the fake git has merged into the *current* worktree, which lets us
deterministically simulate "branch-3 introduces a failing test" and drive the
isolation + bisection logic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.models import BuildResult, TestSpec, TestSpecGroup  # noqa: E402
from shared.repositories.json_store import JsonStore  # noqa: E402
from shared.repositories.test_spec_repository import TestSpecRepository  # noqa: E402
from shared.repositories.build_result_repository import BuildResultRepository  # noqa: E402
from orchestrator.merge_queue import (  # noqa: E402
    MergeGateEngine,
    GitWorktreeAdapter,
    classify_build_results,
    Gate,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeGit:
    """A fake git helper that records the set of branches merged into each worktree.

    Each worktree (identified by a unique path) tracks which candidate branches
    have been merged into it. ``merge(branch, base)`` adds the branch to the
    current worktree's merged set and records the branch. This is what lets
    ``FakeRunner`` decide pass/fail based on which branches are present.
    """

    def __init__(self):
        # path -> set of merged branch names
        self.worktrees: dict[str, set[str]] = {}
        # path -> branch name of the worktree
        self.worktree_branch: dict[str, str] = {}
        # history
        self.created: list[tuple[str, str]] = []  # (branch, path)
        self.merges: list[tuple[str, str]] = []  # (branch, base)
        self.removed: list[tuple[str, str]] = []  # (path, branch)
        self.current: str | None = None
        self._branches: set[str] = set()

    def branch_exists(self, branch: str) -> bool:
        return branch in self._branches or branch.startswith("orchestra-gate-")

    def create_worktree(self, branch: str, path: str) -> str:
        self._branches.add(branch)
        self.worktrees[path] = set()
        self.worktree_branch[path] = branch
        self.created.append((branch, path))
        self.current = path
        return path

    def checkout(self, name: str) -> None:
        self.current = self.worktree_branch.get(name) or None

    def merge(self, branch: str, base: str) -> bool:
        if self.current is None:
            return False
        # A conflicting merge would return False; the fakes never conflict here.
        self.worktrees[self.current].add(branch)
        self.merges.append((branch, base))
        return True

    def merge_into_base(self, branch: str, base: str) -> bool:
        # The fakes model worktree merges; a real fast-forward onto the base
        # branch is not observable to the injected runner, so record it and
        # return success without needing a base-branch model.
        self.merges.append((branch, base))
        return True

    def current_branch(self) -> str:
        if self.current is None:
            return ""
        return self.worktree_branch.get(self.current, "")

    def remove_worktree(self, path: str, branch: str | None = None) -> None:
        self.removed.append((path, branch or ""))
        self.worktrees.pop(path, None)
        self.worktree_branch.pop(path, None)
        if self.current == path:
            self.current = None

    # -- helpers for the runner / tests --------------------------------------

    def merged_into_current(self) -> set[str]:
        """Branches merged into the currently-active worktree."""
        if self.current is None:
            return set()
        return set(self.worktrees.get(self.current, set()))


class FakeRunner:
    """Maps a command string to a returncode.

    By default every command passes (returncode 0). Callers can register:

    * ``fail_commands`` -- set of substrings that make the command fail.
    * ``fail_when_branches_present`` -- callable(set_of_merged_branches) -> bool,
      so the runner can fail based on which branches were merged into the
      current worktree (this is what simulates "branch-3 introduces a failure").
    * ``fail_test_names`` -- when set and the command fails, the produced logs
      contain ``FAILED <name>`` lines for each name, so the engine can parse
      ``failed_tests`` and build a ``-k`` isolation selector.

    Every invocation is recorded in ``calls`` as ``(command, cwd, timeout)``.
    """

    def __init__(self):
        self.fail_commands: set[str] = set()
        self.fail_when_branches_present = None
        self.fail_test_names: list[str] = []
        self.calls: list[tuple[str, str, int]] = []
        # Optional reference to the engine under test, so the runner can inspect
        # the exact set of branches merged into the *current* worktree
        # (engine._active_wt.merged_branches). This is how "branch-3 introduces a
        # failing test" is simulated deterministically.
        self._engine = None

    def record_fail_command(self, substring: str) -> None:
        self.fail_commands.add(substring)

    def _merged_into_current(self) -> set[str]:
        """Branches merged into the currently-active gate worktree.

        Prefers the engine's active worktree (authoritative per-worktree set);
        falls back to the fake git's own per-path tracking.
        """

        eng = getattr(self, "_engine", None)
        if eng is not None and getattr(eng, "_active_wt", None) is not None:
            return set(eng._active_wt.merged_branches)
        g = getattr(self, "_git", None)
        return g.merged_into_current() if g else set()

    def __call__(self, command: str, cwd: str, timeout: int = 600) -> subprocess.CompletedProcess:
        self.calls.append((command, cwd, timeout))

        merged = self._merged_into_current()

        fail = False
        if self.fail_when_branches_present is not None and self.fail_when_branches_present(merged):
            fail = True
        if not fail:
            for sub in self.fail_commands:
                if sub in command:
                    fail = True
                    break

        if fail:
            stdout = "".join(f"FAILED {name}\n" for name in self.fail_test_names)
            return subprocess.CompletedProcess(args=command, returncode=1, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")


def make_specs(tmp_path=None) -> TestSpecRepository:
    import tempfile

    path = str(Path(tempfile.mktemp(suffix=".json")))
    store = JsonStore(path)
    repo = TestSpecRepository(store)
    repo.save(TestSpec(label="unit", group=TestSpecGroup.UNIT, command="pytest tests/"))
    repo.save(TestSpec(label="ci", group=TestSpecGroup.CI, command="pytest tests/ci/"))
    return repo


def make_engine(git, runner, specs=None, base_branch="main") -> MergeGateEngine:
    import tempfile

    store = JsonStore(tempfile.mktemp(suffix=".json"))
    test_spec_repo = specs if specs is not None else make_specs()
    build_result_repo = BuildResultRepository(store)
    engine = MergeGateEngine(
        git, test_spec_repo, build_result_repo, base_branch=base_branch, runner=runner
    )
    # Let the FakeRunner inspect the exact merged-branch set of the active
    # worktree, which is how offenders are simulated deterministically.
    if isinstance(runner, FakeRunner):
        runner._engine = engine
    return engine


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_run_gate_all_pass():
    """3 branches, runner always passes -> gate completed, all branches merged,
    6 results (3 branches x 2 specs: unit+ci)."""

    git = FakeGit()
    runner = FakeRunner()
    engine = make_engine(git, runner, specs=make_specs())

    gate = engine.run_gate(["branch-0", "branch-1", "branch-2"])

    assert gate.status == "completed"
    # 3 branches x 2 specs (unit + ci)
    assert len(gate.results) == 6
    # Every spec's results passed.
    assert all(r.status == "passed" for r in gate.results)
    # All three branches were merged into the gate worktree.
    assert set(git.merged_into_current()) <= {"branch-0", "branch-1", "branch-2"}
    # The gate merged all three branches into base.
    assert set(gate.merged_branch_ids) == {"branch-0", "branch-1", "branch-2"}
    # One worktree was created for the gate.
    assert len(git.created) >= 1


def test_isolate_and_bisect_offender():
    """4 branches; runner fails only when branch-3 is in the merged set. Assert
    the engine bisects, isolates branch-3 as offender, and merges the other 3."""

    git = FakeGit()
    runner = FakeRunner()
    runner._git = git
    runner.fail_when_branches_present = lambda merged: "branch-3" in merged

    engine = make_engine(git, runner, specs=make_specs())

    gate = engine.run_gate(["branch-0", "branch-1", "branch-2", "branch-3"])

    assert gate.status == "completed"
    assert gate.bisection is not None
    assert gate.bisection.offender == "branch-3"
    assert "branch-3" in gate.dropped_branch_ids
    # The other three are proven safe and merged.
    assert set(gate.merged_branch_ids) == {"branch-0", "branch-1", "branch-2"}
    assert "branch-3" not in gate.merged_branch_ids


def _make_transient_engine():
    """Engine where the *initial* gate run fails but isolation passes.

    The runner fails exactly once -- on the first worktree built (the initial
    gate run) -- then always passes. This models a purely transient/environmental
    failure: re-running the same specs on a fresh worktree succeeds, so no branch
    is blamed.
    """

    git = FakeGit()

    class TransientRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self._git = git
            self._ran_once = False

        def __call__(self, command, cwd, timeout=600):
            self.calls.append((command, cwd, timeout))
            if self._ran_once:
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
            # First invocation only (the initial gate run) fails.
            self._ran_once = True
            return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="")

    runner = TransientRunner()
    engine = make_engine(git, runner, specs=make_specs())
    return engine, runner


def test_transient_failure_no_blame_rework():
    """Isolation re-run passes (filtered command) -> no branch blamed, completed,
    all branches merged."""

    engine, runner = _make_transient_engine()
    gate = engine.run_gate(["branch-0", "branch-1", "branch-2", "branch-3"])

    assert gate.status == "completed"
    assert gate.bisection is None  # no bisection needed
    assert gate.dropped_branch_ids == []
    assert set(gate.merged_branch_ids) == {"branch-0", "branch-1", "branch-2", "branch-3"}
    assert "transient" in gate.notes.lower()


def test_run_gate_isolation_uses_run_in_isolation():
    """When isolating, the command passed to the runner contains the spec's
    run_in_isolation selector (proves filterable commands are used)."""

    git = FakeGit()
    runner = FakeRunner()
    runner._git = git
    # Fail only when branch-3 is present, and report a failed test name so the
    # engine can build a -k isolation selector from it.
    runner.fail_when_branches_present = lambda merged: "branch-3" in merged
    runner.fail_test_names = ["test_branch3_breaks"]

    engine = make_engine(git, runner, specs=make_specs())
    engine.run_gate(["branch-0", "branch-1", "branch-2", "branch-3"])

    # During isolation/bisection the runner is called with filtered commands
    # (run_in_isolation inserts a -k selector). Verify at least one call contains
    # a "-k" selector, proving isolation used the filterable command form.
    isolation_calls = [c for (c, _cwd, _t) in runner.calls if "-k" in c]
    assert isolation_calls, "expected isolated commands to contain a -k selector"
    # The selector should reference the failed test name.
    assert any("test_branch3_breaks" in c for c in isolation_calls)


def test_drop_offender_and_rerun():
    """After an offender is dropped, re-running the gate on the remaining branches passes."""

    git = FakeGit()
    runner = FakeRunner()
    runner._git = git
    runner.fail_when_branches_present = lambda merged: "branch-3" in merged

    engine = make_engine(git, runner, specs=make_specs())

    gate = engine.run_gate(["branch-0", "branch-1", "branch-2", "branch-3"])
    assert gate.status == "completed"
    assert "branch-3" in gate.dropped_branch_ids

    # Re-run on the remaining branches; this should all pass.
    gate2 = engine.drop_offender_and_rerun(gate, base_branch="main")
    assert gate2.status == "completed"
    assert len(gate2.results) == 6  # 3 branches x 2 specs
    assert all(r.status == "passed" for r in gate2.results)
    assert "branch-3" not in gate2.branch_ids


def test_escalate_when_no_offender():
    """When bisection cannot isolate (predicate always fails), the gate escalates."""

    git = FakeGit()
    runner = FakeRunner()
    runner._git = git
    # Every subset fails -> bisection cannot prove anything safe -> escalate.
    runner.fail_when_branches_present = lambda merged: len(merged) >= 1

    engine = make_engine(git, runner, specs=make_specs())
    gate = engine.run_gate(["branch-0", "branch-1", "branch-2"])

    assert gate.status == "escalated"
    assert gate.notes


def test_classify_build_results():
    """Pure function: classify a list of build-result-like dicts/objects."""

    results = [
        BuildResult(branch_ids=["a"], status="passed"),
        BuildResult(branch_ids=["b"], status="passed"),
        BuildResult(branch_ids=["c"], status="failed", failed_tests=["t1"]),
        BuildResult(branch_ids=["d"], status="slow", duration_seconds=5.0),
        BuildResult(branch_ids=["e"], status="unknown"),
    ]

    report = classify_build_results(results)
    assert report["total"] == 5
    assert report["passed"] == 2
    assert report["failed"] == 1
    assert report["slow"] == 1
    assert report["unknown"] == 1
    assert report["slowest"] == 5.0
    assert report["failed_branch_combinations"] == [["c"]]

    # Accepts plain dicts too.
    dicts = [
        {"branch_ids": ["x"], "status": "passed", "duration_seconds": 1.0},
        {"branch_ids": ["y"], "status": "failed"},
    ]
    report2 = classify_build_results(dicts)
    assert report2["total"] == 2
    assert report2["passed"] == 1
    assert report2["failed"] == 1
    assert report2["failed_branch_combinations"] == [["y"]]


# --------------------------------------------------------------------------- #
# Real-git acceptance test (gated behind ORCHESTRA_ACCEPTANCE=1).
#
# Builds a throwaway git repo with a base branch and three feature branches, one
# of which introduces a failing test spec, and runs MergeGateEngine against the
# REAL orchestra.gitops.Git helper + a subprocess runner. This validates the
# production code path (GitWorktreeAdapter) that the fake-based tests skip over.
# --------------------------------------------------------------------------- #


def _make_real_repo() -> str:
    import tempfile

    d = tempfile.mkdtemp(prefix="orchestra-gate-")
    git = subprocess.run
    git(["git", "-C", d, "init", "-q"])
    git(["git", "-C", d, "config", "user.email", "t@t"])
    git(["git", "-C", d, "config", "user.name", "t"])
    git(["git", "-C", d, "checkout", "-q", "-b", "main"])
    (Path(d) / "base.txt").write_text("base")
    git(["git", "-C", d, "add", "."])
    git(["git", "-C", d, "commit", "-q", "-m", "base"])

    def feature(branch: str, filename: str, content: str) -> None:
        git(["git", "-C", d, "checkout", "-q", "main"])
        git(["git", "-C", d, "checkout", "-q", "-b", branch])
        (Path(d) / filename).write_text(content)
        git(["git", "-C", d, "add", "."])
        git(["git", "-C", d, "commit", "-q", "-m", branch])

    feature("branch-0", "a.txt", "a")
    feature("branch-1", "b.txt", "b")
    feature("branch-2", "c.txt", "c")
    return d


@pytest.mark.skipif(
    os.environ.get("ORCHESTRA_ACCEPTANCE") != "1",
    reason="real-git acceptance test; run with ORCHESTRA_ACCEPTANCE=1",
)
def test_merge_gate_real_git_end_to_end():
    git_repo = _make_real_repo()
    try:
        from orchestra.gitops import Git

        from shared.repositories.build_result_repository import BuildResultRepository

        base = "main"
        real_git = GitWorktreeAdapter(Git(git_repo))

        # The runner decides pass/fail from the exact set of branches merged into
        # the *current* worktree (engine._active_wt.merged_branches), so bisection
        # subsets are evaluated correctly. branch-2 is the offender.
        def runner(command: str, cwd: str, timeout: int = 600):
            import subprocess as _sub

            merged = set(getattr(engine, "_active_wt", None).merged_branches or ())
            rc = 0 if "branch-2" not in merged else 1
            return _sub.CompletedProcess(args=command, returncode=rc, stdout="", stderr="")

        store = JsonStore(Path(git_repo) / "gate.json")
        specs = TestSpecRepository(store)
        specs.save(TestSpec(label="unit", group=TestSpecGroup.UNIT, command="pytest tests/"))
        specs.save(TestSpec(label="ci", group=TestSpecGroup.CI, command="pytest tests/ci/"))
        br = BuildResultRepository(store)

        engine = MergeGateEngine(real_git, specs, br, base_branch=base, runner=runner)
        gate = engine.run_gate(["branch-0", "branch-1", "branch-2"], base_branch=base)

        assert gate.status == "completed"
        assert gate.bisection is not None
        assert gate.bisection.offender == "branch-2"
        assert "branch-2" in gate.dropped_branch_ids
        assert set(gate.merged_branch_ids) == {"branch-0", "branch-1"}
    finally:
        import shutil

        shutil.rmtree(git_repo, ignore_errors=True)
