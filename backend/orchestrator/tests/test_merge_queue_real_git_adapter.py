"""Real-git integration test for the production merge-gate code path.

The engine's main test suite injects a fake ``runner`` and a fake ``git`` object,
so the *production* adapter path -- ``GitWorktreeAdapter`` calling real
``git`` + running specs via a real subprocess -- is never exercised. This test
closes that gap: it builds a real throwaway git repo, drives
``MergeGateEngine`` with the real :class:`orchestra.gitops.Git` adapter and the
real default subprocess runner (``python3 -m pytest``), and asserts that a
branch which genuinely breaks a committed test is isolated by real bisection,
the safe branches are merged into ``main``, and the offender is dropped.

This validates the exact code a human runs when they invoke ``orchestra gate``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _make_real_repo() -> str:
    """Create a throwaway git repo on ``main`` with four feature branches.

    ``feat-good-1/2/3`` each add a passing test; ``feat-bad`` adds a test that
    fails. All four live on top of the same base commit so they merge cleanly.
    Returns the repo path.
    """

    d = subprocess.run(["mktemp", "-d"], check=True, capture_output=True, text=True).stdout.strip()
    _git("init", "-q", d)
    _git("-C", d, "config", "user.email", "t@t")
    _git("-C", d, "config", "user.name", "t")
    _git("-C", d, "checkout", "-q", "-b", "main")

    # Base commit: a passing test the gate will run.
    (Path(d) / "test_app.py").write_text("def test_base():\n    assert True\n")
    _git("-C", d, "add", ".")
    _git("-C", d, "commit", "-q", "-m", "base")

    def feature(branch: str, body: str) -> None:
        # Each feature writes its *own* ``test_*.py`` file. pytest's default
        # glob collects every ``test_*.py`` so the appended test runs on the
        # gate. Separate files mean the branches never edit the same file, so
        # they merge cumulatively without conflicts.
        _git("-C", d, "checkout", "-q", "main")
        _git("-C", d, "checkout", "-q", "-b", branch)
        (Path(d) / f"test_{branch}.py").write_text(body)
        _git("-C", d, "add", ".")
        _git("-C", d, "commit", "-q", "-m", branch)

    good = "def test_good_1():\n    assert 1 + 1 == 2\n"
    feature("feat-good-1", good)
    feature("feat-good-2", good.replace("_1", "_2"))
    feature("feat-good-3", good.replace("_1", "_3"))
    # The offender: a test that always fails. pytest collects test_<branch>.py,
    # so this assertion flips the gate red exactly when feat-bad is merged in.
    feature(
        "feat-bad",
        "def test_boom():\n    assert False, 'intentional failure'\n",
    )
    _git("-C", d, "checkout", "-q", "main")
    return d


@pytest.mark.skipif(
    os.environ.get("ORCHESTRA_ACCEPTANCE") != "1",
    reason="real-git adapter integration test; run with ORCHESTRA_ACCEPTANCE=1",
)
def test_real_git_adapter_isolates_offender_with_real_pytest():
    """End-to-end: real git adapter + real subprocess runner + real pytest."""

    git_repo = _make_real_repo()
    try:
        from orchestra.gitops import Git
        from orchestrator.merge_queue import MergeGateEngine, GitWorktreeAdapter

        from shared.repositories.build_result_repository import BuildResultRepository
        from shared.repositories.test_spec_repository import TestSpecRepository
        from shared.models import TestSpec, TestSpecGroup

        base = "main"
        # The production adapter over the real Git helper.
        real_git = GitWorktreeAdapter(Git(git_repo))
        from shared.repositories.json_store import JsonStore

        store = JsonStore(Path(git_repo) / "gate.json")
        specs = TestSpecRepository(store)
        # Run the whole test module. pytest's default selector runs every
        # ``test_*`` in ``test_app.py``; the offender flips this to fail.
        specs.save(TestSpec(label="unit", group=TestSpecGroup.UNIT, command="python3 -m pytest -q"))
        br = BuildResultRepository(store)

        engine = MergeGateEngine(real_git, specs, br, base_branch=base)
        gate = engine.run_gate(
            ["feat-good-1", "feat-good-2", "feat-good-3", "feat-bad"], base_branch=base
        )

        # The engine must isolate the offending branch.
        assert gate.status == "completed", gate.notes
        assert gate.bisection is not None
        assert gate.bisection.offender == "feat-bad"
        assert "feat-bad" in set(gate.dropped_branch_ids)
        # The three safe branches were merged into main.
        assert set(gate.merged_branch_ids) == {"feat-good-1", "feat-good-2", "feat-good-3"}

        # And they are actually fast-forwarded onto the base branch now.
        assert real_git.branch_exists("feat-good-1")
        merged = subprocess.run(
            ["git", "-C", git_repo, "merge-base", "--is-ancestor", "feat-good-1", "main"],
            capture_output=True,
        ).returncode
        assert merged == 0, "feat-good-1 should have been fast-forwarded onto main"
    finally:
        shutil.rmtree(git_repo, ignore_errors=True)


@pytest.mark.skipif(
    os.environ.get("ORCHESTRA_ACCEPTANCE") != "1",
    reason="real-git adapter integration test; run with ORCHESTRA_ACCEPTANCE=1",
)
def test_real_git_adapter_all_pass_merges_everything():
    """When every branch passes, the whole batch is merged and no offender found."""

    git_repo = _make_real_repo()
    try:
        from orchestra.gitops import Git
        from orchestrator.merge_queue import MergeGateEngine, GitWorktreeAdapter

        from shared.repositories.json_store import JsonStore
        from shared.repositories.test_spec_repository import TestSpecRepository
        from shared.repositories.build_result_repository import BuildResultRepository
        from shared.models import TestSpec, TestSpecGroup

        base = "main"
        real_git = GitWorktreeAdapter(Git(git_repo))
        store = JsonStore(Path(git_repo) / "gate.json")
        specs = TestSpecRepository(store)
        specs.save(TestSpec(label="unit", group=TestSpecGroup.UNIT, command="python3 -m pytest -q"))
        br = BuildResultRepository(store)
        engine = MergeGateEngine(real_git, specs, br, base_branch=base)

        # Only the three good branches -> everything passes.
        gate = engine.run_gate(
            ["feat-good-1", "feat-good-2", "feat-good-3"], base_branch=base
        )

        assert gate.status == "completed"
        assert gate.bisection is None
        assert set(gate.merged_branch_ids) == {"feat-good-1", "feat-good-2", "feat-good-3"}
        assert gate.dropped_branch_ids == []
    finally:
        shutil.rmtree(git_repo, ignore_errors=True)
