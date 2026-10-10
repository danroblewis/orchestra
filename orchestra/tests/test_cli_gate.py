"""CLI-level tests for the merge-gate wiring: ``test-specs`` and ``gate`` subcommands.

Model-free (no real Pi). Real git uses a throwaway ``git init`` repo in ``tmp_path``
where needed, mirroring the pattern in ``backend/orchestrator/tests/test_merge_queue.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Make both the orchestra package and the backend importable.
ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
for p in (str(ROOT), str(BACKEND_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

@pytest.fixture()
def temp_repo() -> str:
    tmp = str(tempfile.mkdtemp())
    subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
    (Path(tmp) / "f.txt").write_text("x")
    subprocess.run(["git", "-C", tmp, "add", "."], check=True)
    subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
    yield tmp


@pytest.fixture(autouse=True)
def fake_home(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCHESTRA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ORCHESTRA_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _init(temp_repo: str, slug: str) -> None:
    from orchestra.cli import main

    assert main(["init", "--repo", temp_repo, "--base_branch", "main", "--slug", slug]) == 0


# --------------------------------------------------------------------------- #
# test-specs
# --------------------------------------------------------------------------- #

def test_test_specs_add_and_list(tmp_path):
    """Add a test spec, then list it -- assert label/command/group persisted."""

    from shared.models import TestSpecGroup
    from shared.repositories.json_store import JsonStore
    from shared.repositories.test_spec_repository import TestSpecRepository

    from shared.models import TestSpec

    store = JsonStore(tmp_path / "orchestra.json")
    repo = TestSpecRepository(store)

    spec = repo.save(TestSpec(label="unit", command="pytest tests/", group=TestSpecGroup.UNIT))
    assert spec.id

    all_specs = repo.all_ordered()
    assert len(all_specs) == 1
    loaded = all_specs[0]
    assert loaded.label == "unit"
    assert loaded.command == "pytest tests/"
    assert loaded.group.value == "unit"
    assert loaded.enabled is True


def test_test_specs_promote_flaky(tmp_path):
    """Seed specs + synthetic build results; promote flaky -> assert group becomes daily."""

    from shared.models import TestSpec, TestSpecGroup, BuildResult
    from shared.repositories.json_store import JsonStore
    from shared.repositories.test_spec_repository import TestSpecRepository
    from shared.repositories.build_result_repository import BuildResultRepository
    from orchestrator.pipeline_agent import PipelineAgent

    store = JsonStore(tmp_path / "orchestra.json")
    spec_repo = TestSpecRepository(store)
    br_repo = BuildResultRepository(store)

    a_id = "spec-a"
    b_id = "spec-b"
    spec_repo.save(TestSpec(id=a_id, label="alpha", command="pytest tests/", group=TestSpecGroup.UNIT))
    spec_repo.save(TestSpec(id=b_id, label="beta", command="pytest tests/", group=TestSpecGroup.UNIT))

    # Spec A: 5 runs, 1 fail -> flaky. Spec B: 4 runs, 4 fail -> always failing.
    for _ in range(4):
        br_repo.save(BuildResult(gate_id="g", branch_ids=["b"], test_ids=[a_id], status="passed"))
    br_repo.save(BuildResult(gate_id="g", branch_ids=["b"], test_ids=[a_id], status="failed"))
    for _ in range(4):
        br_repo.save(BuildResult(gate_id="g", branch_ids=["b"], test_ids=[b_id], status="failed"))

    from orchestrator.pipeline_agent import FlakyAssessment

    agent = PipelineAgent(test_spec_repo=spec_repo)
    assessments = [
        FlakyAssessment("spec-a", "alpha", runs=5, failures=1, flaky=True, promote_to_daily=True),
        FlakyAssessment("spec-b", "beta", runs=4, failures=4, flaky=False, promote_to_daily=False),
    ]
    promoted = agent.promote_flaky_to_daily(assessments, spec_repo)

    assert "spec-a" in promoted
    reloaded = spec_repo.find(a_id)
    assert reloaded.group.value == TestSpecGroup.DAILY.value
    assert reloaded.enabled is True


# --------------------------------------------------------------------------- #
# gate: branch discovery + engine runs
# --------------------------------------------------------------------------- #

def test_gate_discovery_branches_from_manifest(temp_repo):
    """Create a temp git repo + worktree manifest with an active worktree; assert
    branch discovery returns it."""

    from orchestra.gitops import Git, WorktreeManifest, WorktreeRecord
    from orchestra.cli import _discover_gate_branches

    git = Git(temp_repo)
    manifest = WorktreeManifest()
    manifest.upsert(WorktreeRecord(slug="t1", task_id="task-1", branch="orchestra-fix-one", path="/tmp/x", status="working"))
    manifest.upsert(WorktreeRecord(slug="t2", task_id="task-2", branch="orchestra-fix-two", path="/tmp/y", status="merged"))
    git.save_manifest(manifest)

    # Ensure the branches exist so branch_exists() passes.
    for br in ("orchestra-fix-one", "orchestra-fix-two"):
        subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "-b", br], check=True)

    # active_only=True -> only branches worked this run and now ready to gate
    # (merged/removed). The "working" one is still in progress.
    found_active = _discover_gate_branches(None, git, git.load_manifest(), active_only=True)
    assert set(found_active) == {"orchestra-fix-two"}

    # active_only=False -> every record, including in-progress worktrees.
    found_all = _discover_gate_branches(None, git, git.load_manifest(), active_only=False)
    assert set(found_all) == {"orchestra-fix-one", "orchestra-fix-two"}


def test_classify_fast_forward_branches(temp_repo):
    """A branch that is an ancestor of ``main`` (or equal to it) is fast-forward;
    a branch that has diverged (a committed change off its own base commit) is
    NOT fast-forward-mergeable and must be reported separately so the gate can
    drop it instead of aborting."""

    from orchestra.gitops import Git
    from orchestra.cli import _classify_fast_forward_branches

    git = Git(temp_repo)

    # All three branches start from the same base commit (the initial "init" commit).
    # ``already-merged`` is later fast-forwarded onto ``main``, so it ends up an
    # ancestor of the base. ``divergent-branch`` and ``feature-todo`` stay behind
    # at the base commit, so ``main`` has moved past them (diverged) -- they are
    # not fast-forward-mergeable onto the (now-advanced) base.

    # A divergent branch: a committed change off the shared base commit.
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "-b", "divergent-branch"])
    (Path(temp_repo) / "b.txt").write_text("b")
    subprocess.run(["git", "-C", temp_repo, "add", "."], check=True)
    subprocess.run(["git", "-C", temp_repo, "commit", "-q", "-m", "divergent-change"])

    # A normal in-progress feature branch off the same base commit.
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "main"])
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "-b", "feature-todo"])
    (Path(temp_repo) / "c.txt").write_text("c")
    subprocess.run(["git", "-C", temp_repo, "add", "."], check=True)
    subprocess.run(["git", "-C", temp_repo, "commit", "-q", "-m", "feature-change"])

    # ``already-merged``: create from the shared base, then fast-forward main
    # onto it so it becomes a full ancestor of the base branch.
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "main"])
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "-b", "already-merged"])
    (Path(temp_repo) / "a.txt").write_text("a")
    subprocess.run(["git", "-C", temp_repo, "add", "."], check=True)
    subprocess.run(["git", "-C", temp_repo, "commit", "-q", "-m", "merged-change"])
    subprocess.run(["git", "-C", temp_repo, "checkout", "-q", "main"])
    subprocess.run(["git", "-C", temp_repo, "merge", "--ff", "already-merged"], check=True)

    ff, non_ff = _classify_fast_forward_branches(
        git, ["already-merged", "divergent-branch", "feature-todo", "main"], "main"
    )

    # ``already-merged`` and ``main`` are ancestors of (or equal to) main.
    assert set(ff) == {"already-merged", "main"}
    # ``divergent-branch`` has diverged and ``feature-todo`` branched off before
    # the ff-merge, so neither can be fast-forwarded onto the base.
    assert non_ff == ["divergent-branch", "feature-todo"]


def test_gate_runs_and_reports_all_pass(tmp_path):
    """MergeGateEngine with a FakeRunner (all pass) + FakeGit -> gate.status == completed."""

    from orchestrator.merge_queue import MergeGateEngine, GitWorktreeAdapter

    git = FakeGit()
    runner = FakeRunner()

    from shared.models import TestSpec, TestSpecGroup
    from shared.repositories.json_store import JsonStore
    from shared.repositories.test_spec_repository import TestSpecRepository
    from shared.repositories.build_result_repository import BuildResultRepository

    store = JsonStore(Path(tmp_path) / "gate.json")
    specs = TestSpecRepository(store)
    specs.save(TestSpec(label="unit", group=TestSpecGroup.UNIT, command="pytest tests/"))
    specs.save(TestSpec(label="ci", group=TestSpecGroup.CI, command="pytest tests/ci/"))
    br = BuildResultRepository(store)

    # Pass FakeGit directly (not wrapped in GitWorktreeAdapter), mirroring the
    # merge_queue test helpers: the adapter's merge() calls Git._run(), which the
    # FakeGit does not implement. In production the real Git is wrapped; in tests
    # the FakeGit satisfies the engine's git interface directly.
    engine = MergeGateEngine(git, specs, br, base_branch="main", runner=runner)
    runner._engine = engine

    gate = engine.run_gate(["branch-0", "branch-1", "branch-2"])

    assert gate.status == "completed"
    assert len(gate.results) == 6  # 3 branches x 2 specs
    assert all(r.status == "passed" for r in gate.results)
    assert set(gate.merged_branch_ids) == {"branch-0", "branch-1", "branch-2"}


class FakeGit:
    """Mirror of the fake git helper from test_merge_queue.py."""

    def __init__(self):
        self.worktrees = {}
        self.worktree_branch = {}
        self.created = []
        self.merges = []
        self.removed = []
        self.current = None
        self._branches = set()

    def branch_exists(self, branch):
        return branch in self._branches or branch.startswith("orchestra-gate-")

    def create_worktree(self, branch, path):
        self._branches.add(branch)
        self.worktrees[path] = set()
        self.worktree_branch[path] = branch
        self.created.append((branch, path))
        self.current = path
        return path

    def checkout(self, name):
        self.current = self.worktree_branch.get(name) or None

    def merge(self, branch, base):
        if self.current is None:
            return False
        self.worktrees[self.current].add(branch)
        self.merges.append((branch, base))
        return True

    def merge_into_base(self, branch, base):
        self.merges.append((branch, base))
        return True

    def current_branch(self):
        if self.current is None:
            return ""
        return self.worktree_branch.get(self.current, "")

    def remove_worktree(self, path, branch=None):
        self.removed.append((path, branch or ""))
        self.worktrees.pop(path, None)
        self.worktree_branch.pop(path, None)
        if self.current == path:
            self.current = None


class FakeRunner:
    """Mirror of the fake runner helper from test_merge_queue.py."""

    def __init__(self):
        self.fail_commands = set()
        self.fail_when_branches_present = None
        self.fail_test_names = []
        self.calls = []
        self._engine = None

    def __call__(self, command, cwd, timeout=600):
        self.calls.append((command, cwd, timeout))
        eng = getattr(self, "_engine", None)
        merged = set(getattr(eng, "_active_wt", None).merged_branches or ()) if eng and getattr(eng, "_active_wt", None) else set()
        fail = False
        if self.fail_when_branches_present is not None and self.fail_when_branches_present(merged):
            fail = True
        if not fail:
            for sub in self.fail_commands:
                if sub in command:
                    fail = True
                    break
        import subprocess as _sub
        if fail:
            stdout = "".join(f"FAILED {name}\n" for name in self.fail_test_names)
            return _sub.CompletedProcess(args=command, returncode=1, stdout=stdout, stderr="")
        return _sub.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
