"""Pure bisection engine for the batched merge gate (Phase 3d).

When the batched merge gate FAILS, the Pipeline Manager needs to find *which*
branch in the batch is responsible. It bisects the candidate *branches* (not
git commits) and proves the safe ones are clean so they can be merged while the
offender is dropped.

The algorithm is intentionally pure: the only input it needs is an injected
predicate ``is_failing_fn(subset_of_branches) -> bool``. The engine (see the
Pipeline Manager) wraps this predicate with real subprocess/git calls to run the
failed tests in isolation. Keeping this module free of git/subprocess makes it
fully unit-testable in isolation.

How bisection works
--------------------
Given a set of candidate branches and a predicate that answers "does this
subset still reproduce the failure?":

* If the whole set passes, the failure was transient -- no blame, everything is
  merged.
* Otherwise split the set into two halves (the first half is ``ceil(n/2)``).
  * If the first half fails, the offender is inside it. Keep bisecting there.
  * Otherwise the first half is proven clean -- it is safe to merge -- and we
    recurse into the second half.
* Recurse until a single branch remains; that branch is the offender.

Branches proven safe are appended to ``merged_branches`` in the order they were
discovered (largest safe halves first), which is a sensible merge order.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence


# --- Pure bisection engine (Phase 3d) -------------------------------------
# bisect_branches / merge_order_for_safe / BisectionResult live below.
# The imperative merge-gate engine (MergeGateEngine, Gate, classify_build_results)
# is appended at the end of this file.



@dataclass
class BisectionResult:
    """Outcome of bisecting a batch to isolate a failing branch.

    Attributes:
        candidate_branches: The original candidate set that was bisected.
        offender: The single branch that caused the failure, or ``None`` if the
            failure could not be attributed to any branch (transient/passing).
        merged_branches: Branches proven safe and merged, in merge order.
        dropped_branches: Branches removed from the queue (offenders), excluding
            any already-merged branches.
        rounds: How many bisection rounds were needed.
    """

    candidate_branches: list[str]
    offender: str | None
    merged_branches: list[str] = field(default_factory=list)
    dropped_branches: list[str] = field(default_factory=list)
    rounds: int = 0


def merge_order_for_safe(halves_proven_safe: list[list[str]]) -> list[str]:
    """Flatten the safe halves into a single ordered merge list.

    The engine passes the halves it proved safe, in the order it proved them,
    and this returns the flattened branch list to fast-forward / merge.
    """

    merged: list[str] = []
    for half in halves_proven_safe:
        merged.extend(half)
    return merged


def bisect_branches(
    branches: list[str], is_failing_fn: Callable[[list[str]], bool]
) -> BisectionResult:
    """Bisect candidate branches to isolate the branch causing a failure.

    Args:
        branches: The candidate branches in the failing batch (2-8 in practice,
            but any length >= 1 is handled).
        is_failing_fn: Predicate that reports whether re-running the failed tests
            against a subset of branches still reproduces the failure. Pure and
            injected so the algorithm is unit-testable without git/subprocess.

    Returns:
        A :class:`BisectionResult` describing the offender and the safe branches
        to merge.
    """

    # Transient / no-blame path: the full batch passes the failed tests.
    if not is_failing_fn(list(branches)):
        return BisectionResult(
            candidate_branches=list(branches),
            offender=None,
            merged_branches=list(branches),
            dropped_branches=[],
            rounds=0,
        )

    # Mutable accumulator for halves proven safe, in discovery order. This both
    # drives the merge order and counts as rounds when a safe half is resolved.
    halves_proven_safe: list[list[str]] = []
    rounds = 0

    def _recurse(candidate: list[str]) -> str | None:
        """Recurse on the failing candidate set; returns the offender branch."""

        nonlocal rounds

        # Base case: a single candidate is the offender.
        if len(candidate) == 1:
            return candidate[0]

        # First half is ceil(n/2); second half is the remainder.
        mid = (len(candidate) + 1) // 2
        first_half = candidate[:mid]
        second_half = candidate[mid:]

        first_failing = is_failing_fn(first_half)

        # If only one half is failing, the other half is proven safe to merge.
        # (The predicate is monotone: any subset of a failing set that is itself
        # failing also fails; a passing half therefore contains no offender.)
        if not first_failing and is_failing_fn(second_half):
            halves_proven_safe.append(first_half)
            rounds += 1
            return _recurse(second_half)
        if first_failing and not is_failing_fn(second_half):
            halves_proven_safe.append(second_half)
            rounds += 1
            return _recurse(first_half)

        # Both halves fail: the offender could be in either, so we cannot prove
        # either side safe. Descend into the first half to keep narrowing.
        return _recurse(first_half)

    offender = _recurse(list(branches))

    merged_branches = merge_order_for_safe(halves_proven_safe)

    # Offenders are everything not proven safe. In the single-offender case
    # this is just the offender; the helper stays general for reuse.
    merged_set = set(merged_branches)
    dropped_branches = [b for b in branches if b not in merged_set]

    return BisectionResult(
        candidate_branches=list(branches),
        offender=offender,
        merged_branches=merged_branches,
        dropped_branches=dropped_branches,
        rounds=rounds,
    )


# --------------------------------------------------------------------------- #
# Imperative merge-gate engine (git + subprocess wrapper around bisect_branches).
# --------------------------------------------------------------------------- #

# Make `shared.*` importable when this module is imported directly (mirrors the
# sys.path insertion in orchestrator.py and the sibling tests).
if __package__ in (None, ""):
    _backend = Path(__file__).resolve().parents[1]
    if str(_backend) not in sys.path:
        sys.path.insert(0, str(_backend))

try:
    from shared.models import BuildResult, TestSpec, TestSpecGroup  # noqa: E402
except Exception:  # pragma: no cover - models always present in the repo
    BuildResult = TestSpec = TestSpecGroup = None


DEFAULT_GATE_TIMEOUT = 600
_GROUP_ORDER = {"unit": 0, "ci": 1, "daily": 2}


@dataclass
class Gate:
    """In-memory result of running (and, if needed, resolving) a merge gate.

    Attributes:
        gate_id: Unique id for this gate run.
        base_branch: Branch the candidate branches were tested against.
        branch_ids: The candidate branches the gate started with.
        status: ``"running"`` | ``"completed"`` | ``"escalated"``.
        results: One :class:`BuildResult` per (test-spec run).
        bisection: The :class:`BisectionResult` if a bisection was performed.
        notes: Human-readable status notes (transient failure, escalation reason).
        merged_branch_ids: Branches proven safe and merged into ``base_branch``.
        dropped_branch_ids: Offending branches dropped from the batch.
    """

    gate_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    base_branch: str = "main"
    branch_ids: list[str] = field(default_factory=list)
    status: str = "running"
    results: list[Any] = field(default_factory=list)
    bisection: Any = None
    notes: str = ""
    merged_branch_ids: list[str] = field(default_factory=list)
    dropped_branch_ids: list[str] = field(default_factory=list)

    # -- reporting helpers ---------------------------------------------------

    @property
    def failed_results(self) -> list[Any]:
        return [r for r in self.results if getattr(r, "status", None) == "failed"]

    @property
    def failed_tests(self) -> list[str]:
        """Union of ``failed_tests`` across all results, de-duplicated, ordered."""
        seen: list[str] = []
        seen_set: set[str] = set()
        for r in self.results:
            for t in getattr(r, "failed_tests", []) or []:
                if t not in seen_set:
                    seen_set.add(t)
                    seen.append(t)
        return seen

    def to_report(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "base_branch": self.base_branch,
            "branch_ids": list(self.branch_ids),
            "status": self.status,
            "notes": self.notes,
            "merged_branches": list(self.merged_branch_ids),
            "dropped_branches": list(self.dropped_branch_ids),
            "total_results": len(self.results),
            "failed_results": len(self.failed_results),
            "failed_tests": self.failed_tests,
            "bisection": None if self.bisection is None else {
                "offender": self.bisection.offender,
                "merged_branches": list(self.bisection.merged_branches),
                "dropped_branches": list(self.bisection.dropped_branches),
                "rounds": self.bisection.rounds,
            },
        }


def _get(r: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dataclass-like object or a plain dict."""

    if isinstance(r, dict):
        return r.get(key, default)
    return getattr(r, key, default)


def classify_build_results(results: Iterable[Any]) -> dict[str, Any]:
    """Pure reporting helper over a collection of BuildResult-like objects.

    Accepts either :class:`BuildResult` instances or plain dicts.

    Returns:
        ``{total, passed, failed, slow, unknown, duration_seconds, slowest,
        failed_branch_combinations}`` where ``failed_branch_combinations`` is the
        list of ``branch_ids`` from every result whose status is ``failed``.
    """

    total = passed = failed = slow = unknown = 0
    total_duration = 0.0
    slowest = 0.0
    failed_branch_combinations: list[list[str]] = []

    for r in results:
        status = _get(r, "status") or "unknown"
        dur = _get(r, "duration_seconds") or 0
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = 0.0

        total += 1
        total_duration += dur
        if dur > slowest:
            slowest = dur

        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1
            failed_branch_combinations.append(list(_get(r, "branch_ids", []) or []))
        elif status == "slow":
            slow += 1
        else:
            unknown += 1

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "slow": slow,
        "unknown": unknown,
        "duration_seconds": total_duration,
        "slowest": slowest,
        "failed_branch_combinations": failed_branch_combinations,
    }


class MergeConflict(Exception):
    """Raised when a branch cannot be merged into the base (conflict)."""


class GitWorktreeAdapter:
    """Production adapter that maps the engine's git interface onto the real
    :class:`orchestra.gitops.Git` helper.

    The existing ``Git`` class (gitops.py) provides ``create_worktree``,
    ``current_branch``, ``branch_exists`` and ``remove_worktree``, but it lacks
    the two methods the engine needs for the gate loop:

    * ``merge(branch, base) -> bool`` -- fast-forward ``branch`` onto ``base``
      (returns ``False`` on a conflict / non-fast-forward).
    * ``run(cmd, cwd, timeout) -> CompletedProcess`` -- run a shell command.

    This adapter adds both on top of the real ``Git`` without modifying it, so
    the engine runs against real git in production and against :class:`FakeGit`
    in tests through the exact same interface.

    NOTE (git-helper limitation): the real ``Git.create_worktree`` does
    ``git worktree add -b <branch> <path> HEAD``, which creates a *new* branch
    checked out at HEAD -- it does not check out an arbitrary existing branch
    like ``main``. For the gate this means the gate worktree starts at the base
    branch's HEAD only if the repo's checked-out branch *is* the base; otherwise
    callers should pass a branch that already exists. ``merge`` below performs a
    real ``git merge --no-ff`` and treats a non-zero return code (conflict) as
    ``False`` so the engine can surface it as a bisection failure.
    """

    def __init__(self, real_git: Any):
        self._git = real_git
        # The worktree directory that the next merge() operates against.
        # ``Git._run`` is hardcoded to the base repo, so merges (and the checkout
        # that precedes them) must run with ``-C <worktree>`` instead.
        self._current_worktree: str | None = None

    def create_worktree(self, branch: str, path: str) -> str:
        result = str(self._git.create_worktree(branch, Path(path)))
        self._current_worktree = result
        return result

    def checkout(self, name: str) -> None:
        # ``Git`` has no checkout-by-name; fall back to the current branch if the
        # worktree is already checked out. Merges do not require a checkout.
        self._git.current_branch()

    def merge(self, branch: str, base: str) -> bool:
        """Fast-forward ``branch`` into the current worktree (already at ``base``).

        Runs the merge *inside the worktree* (``-C <worktree path>``) because the
        base ``Git._run`` is pinned to the repo root and would otherwise merge
        into the wrong working directory. Returns ``False`` on a conflict /
        non-fast-forward.
        """

        import subprocess

        wt = self._current_worktree
        if not wt:
            return False
        # The worktree was created at ``HEAD`` (the base commit) by
        # ``create_worktree`` and is already checked out there; we only need the
        # merge. (Checking out ``base`` again would fail when the base branch is
        # already checked out in the repo, which is the common case.)
        proc = subprocess.run(
            ["git", "-C", wt, "merge", "--no-ff", branch],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def merge_into_base(self, branch: str, base: str) -> bool:
        """Merge ``branch`` into the real ``base`` branch of the repo (not a
        worktree). This is used by ``_complete_gate`` to fast-forward proven-safe
        candidate branches onto the base branch once the gate resolves -- it must
        run in the repo root, unlike :meth:`merge` which operates in the active
        gate worktree.
        """

        import subprocess

        proc = subprocess.run(
            ["git", "-C", str(self._git.repo_root), "merge", "--no-ff", branch],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def current_branch(self) -> str:
        return self._git.current_branch()

    def branch_exists(self, branch: str) -> bool:
        return self._git.branch_exists(branch)

    def remove_worktree(self, path: str, branch: str | None = None) -> None:
        self._git.remove_worktree(Path(path), branch)

    def run(self, cmd: str, cwd: str, timeout: int) -> Any:
        """Run a shell ``cmd`` in ``cwd`` (used only when a caller wants git itself
        to invoke a process; the gate's test specs go through the ``runner``).
        Delegates to subprocess since ``Git._run`` is a thin ``git``-only wrapper."""

        import subprocess

        return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)


class GateWorktree:
    """A single throwaway git worktree used to test a set of candidate branches.

    The gate funnels *all* git/subprocess side effects through this object so the
    engine body stays simple and both production and tests share one path. A
    worktree is created fresh on ``base`` with exactly ``merge_branches`` merged
    in, then used to run commands; :meth:`cleanup` tears it down.
    """

    def __init__(
        self,
        git: Any,
        runner: Callable[[str, str, int], Any],
        gate_id: str,
        base_branch: str,
    ):
        self.git = git
        self.runner = runner
        self.gate_id = gate_id
        self.base_branch = base_branch
        self.cwd: str | None = None
        # Branches merged into THIS worktree (self.cwd). Populated by merge();
        # the injected runner consults this (via the engine's active-worktree
        # reference) to decide pass/fail based on the merged branch set.
        self.merged_branches: set[str] = set()

    # -- path helpers --------------------------------------------------------

    def worktree_name(self) -> str:
        return f"orchestra-gate-{self.gate_id}"

    def worktree_path(self) -> str:
        return str(Path(".orchestra-gates") / self.gate_id)

    # -- merge ---------------------------------------------------------------

    def merge(self, merge_branches: Sequence[str]) -> None:
        """Create/reset the worktree at ``base`` with ``merge_branches`` merged in.

        The worktree starts clean on ``base``; each branch is then merged in
        sequence. A conflicting / non-fast-forward merge raises :class:`MergeConflict`
        so the engine can treat it as a bisection failure to reason about.
        """

        name = self.worktree_name()
        path = self.worktree_path()

        # Start clean: remove any leftover worktree from a prior run.
        if self.git.branch_exists(name):
            self.git.remove_worktree(path, name)

        self.git.create_worktree(name, path)
        self.cwd = path
        self.merged_branches = set()  # reset for this fresh worktree

        for branch in merge_branches:
            ok = self.git.merge(branch, self.base_branch)
            if not ok:
                raise MergeConflict(f"could not merge branch {branch} into {self.base_branch}")
            self.merged_branches.add(branch)

    # -- run -----------------------------------------------------------------

    def run(self, command: str, timeout: int = DEFAULT_GATE_TIMEOUT) -> Any:
        if self.cwd is None:
            raise RuntimeError("worktree not initialised; call merge() first")
        return self.runner(command, self.cwd, timeout)

    # -- teardown ------------------------------------------------------------

    def cleanup(self) -> None:
        path = self.worktree_path()
        name = self.worktree_name()
        try:
            self.git.remove_worktree(path, name)
        except Exception:
            # Best-effort cleanup; a leftover worktree is not fatal.
            pass

    def default_runner(self, command: str, timeout: int = DEFAULT_GATE_TIMEOUT) -> Any:
        """Run a spec command against this worktree via the injected runner."""

        return self.runner(command, self.cwd, timeout)


def _default_runner(command: str, cwd: str, timeout: int = DEFAULT_GATE_TIMEOUT) -> subprocess.CompletedProcess:
    """Run ``command`` in ``cwd`` via subprocess (production default)."""

    return subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _status_from_returncode(proc: Any) -> tuple[str, list[str], str]:
    """Derive ``(status, failed_tests, logs)`` from a CompletedProcess.

    ``status`` is ``"failed"`` for a non-zero return code, else ``"passed"``.
    ``failed_tests`` is parsed best-effort from the logs; if nothing recognizable
    is found it is left empty and the caller may rely on isolation re-runs.

    pytest exit code ``5`` means "no tests were collected / all deselected" (for
    example an isolation ``-k`` selector that matched nothing). That is *not* a
    real test failure -- it means the run could not reproduce the thing we were
    looking for -- so it is reported as ``"passed"`` rather than ``"failed"``.
    """

    logs = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode == 0 or proc.returncode == 5:
        return "passed", [], logs

    failed = _parse_pytest_failures(logs)
    if not failed:
        failed = _parse_explicit_failures(logs)
    return "failed", failed, logs


def _parse_explicit_failures(logs: str) -> list[str]:
    """Parse explicitly reported failed tests from logs (e.g. 'FAILED test_x')."""
    failed: list[str] = []
    for line in logs.splitlines():
        s = line.strip()
        for prefix in ("FAILED ", "FAIL "):
            if s.startswith(prefix):
                rest = s[len(prefix):].strip()
                name = rest.split()[0] if rest else ""
                if name and name not in failed:
                    failed.append(name)
    return failed


def _parse_pytest_failures(logs: str) -> list[str]:
    """Parse ``short test summary info:: test_x FAILED`` lines from pytest logs."""
    failed: list[str] = []
    capture = False
    for line in logs.splitlines():
        s = line.strip()
        if s.startswith("short test summary info"):
            capture = True
            continue
        if capture:
            if not s:
                break
            if " FAILED" in s:
                name = s.split(" FAILED")[0].strip()
                if name and name not in failed:
                    failed.append(name)
    return failed


class MergeGateEngine:
    """Runs a batched merge gate and, on failure, isolates the offending branch.

    Args:
        git: A git helper exposing ``create_worktree(branch, path)``,
            ``checkout(name)``, ``merge(branch, base)->bool``, ``current_branch()``,
            ``branch_exists(name)``, ``remove_worktree(path, branch)`` and
            ``run(cmd, cwd, timeout)``.
        test_spec_repo: A repository of :class:`TestSpec` objects.
        build_result_repo: A repository of :class:`BuildResult` objects.
        base_branch: Default base branch for gates.
        runner: Optional ``(command, cwd, timeout) -> CompletedProcess`` callable.
            Injected for tests; defaults to a subprocess-based runner.
        timeout: Default per-spec timeout (seconds).
    """

    def __init__(
        self,
        git: Any,
        test_spec_repo: Any,
        build_result_repo: Any,
        base_branch: str = "main",
        runner: Callable[[str, str, int], Any] | None = None,
        timeout: int = DEFAULT_GATE_TIMEOUT,
    ):
        self.git = git
        self.test_spec_repo = test_spec_repo
        self.build_result_repo = build_result_repo
        self.base_branch = base_branch
        self.runner = runner or _default_runner
        self.timeout = timeout
        # Bookkeeping for the single worktree active during a gate run.
        self._active_cwd: str | None = None
        self._active_gate_id: str | None = None
        # Reference to the active GateWorktree so the injected runner can inspect
        # the exact set of branches merged into the current worktree.
        self._active_wt: GateWorktree | None = None

    # -- public API ----------------------------------------------------------

    def run_gate(self, branch_ids: Sequence[str], base_branch: str | None = None) -> Gate:
        """Run the merge gate over ``branch_ids`` against ``base_branch``.

        For every enabled ``unit`` + ``ci`` spec, runs it against a worktree built
        from each candidate branch (branch merged into ``base``) and records a
        :class:`BuildResult` per (branch x spec). If every run passes the gate is
        marked ``completed`` and all branches are fast-forwarded into the base. If
        any run fails, :meth:`resolve_failure` is invoked.
        """

        base = base_branch or self.base_branch
        branch_ids = list(branch_ids)
        gate = Gate(gate_id=uuid.uuid4().hex, base_branch=base, branch_ids=branch_ids)
        gate.status = "running"

        specs = self._specs_for_gate()

        # Build the merged gate state: a worktree per candidate branch, each
        # branch merged into ``base``. Running each spec against each branch gives
        # a per-(branch, spec) BuildResult, which is what resolve_failure bisects
        # on. The worktree is reused (branches accumulate) so a later branch's run
        # also reflects the earlier ones -- the merged batch grows as we go.
        merged_so_far: list[str] = []
        main_wt: GateWorktree | None = None
        try:
            main_wt = GateWorktree(self.git, self.runner, gate.gate_id, base)
            main_wt.merge([])  # create the base worktree (clean slate)
            self._active_cwd = main_wt.cwd
            self._active_gate_id = gate.gate_id
            self._active_wt = main_wt

            for branch in branch_ids:
                merged_so_far.append(branch)
                # Rebuild the worktree with the cumulative merged branch set so the
                # runner sees everything merged up to and including this branch.
                main_wt.cleanup()
                main_wt.merge(merged_so_far)
                self._active_cwd = main_wt.cwd
                self._active_wt = main_wt

                for spec in specs:
                    proc = self.runner(spec.command, main_wt.cwd, self.timeout)
                    status, failed_tests, logs = _status_from_returncode(proc)
                    result = BuildResult(
                        gate_id=gate.gate_id,
                        branch_ids=[branch],
                        test_ids=[spec.id],
                        status=status,
                        duration_seconds=0.0,
                        failed_tests=failed_tests,
                        logs=logs,
                    )
                    self.build_result_repo.save(result)
                    gate.results.append(result)

            if not gate.failed_results:
                self._complete_gate(gate, branch_ids)
            else:
                gate = self.resolve_failure(gate, base)
        finally:
            self._active_cwd = None
            self._active_gate_id = None
            self._active_wt = None
            if main_wt is not None:
                main_wt.cleanup()

        return gate

    def resolve_failure(self, gate: Gate, base_branch: str) -> Gate:
        """Resolve a failing gate by isolation first, then bisection.

        1. Gather the union of ``failed_tests`` across the gate's results. If
           there are none we cannot isolate by test -> escalate.
        2. Re-run those failed tests in isolation on a fresh worktree with ALL
           candidate branches merged. If they pass, the failure was
           transient/environmental -> mark the gate completed, blame no branch,
           merge everything.
        3. Otherwise bisect the candidate branches to isolate the offender, merge
           the proven-safe branches, drop the offender.
        4. If bisection cannot isolate a single offender, escalate.
        """

        base = base_branch

        # The union of failed test names across the gate's results. May be empty
        # when the runner reports a failure but not which test (e.g. no parseable
        # logs). In that case we still isolate/bisect using the specs' full
        # commands (empty selector), because a failed *spec* is enough signal.
        failed_tests = gate.failed_tests

        # Step 2: isolation re-run on the full batch. If the failed specs pass
        # in isolation the failure was transient/environmental -> no blame.
        if self._isolation_passes(gate, base, failed_tests):
            gate.status = "completed"
            gate.notes = (
                "transient/environmental failure: failed spec(s) passed in "
                "isolation on the full batch; no branch blamed."
                + (f" (failed tests: {', '.join(failed_tests)})" if failed_tests else "")
            )
            self._complete_gate(gate, gate.branch_ids)
            return gate

        # Step 3: bisection to isolate the offending branch.
        result = self._bisect(gate, base, failed_tests)
        gate.bisection = result
        gate.dropped_branch_ids = list(result.dropped_branches)

        # Escalate when we cannot produce a safe resolution: either the pure
        # bisection returned no offender, or it proved nothing mergeable (every
        # candidate dropped, more than one candidate) -- i.e. multiple offenders
        # or an unisolatable failure that the Pipeline Agent must take over.
        if result.offender is None or (
            len(gate.branch_ids) > 1 and not result.merged_branches
        ):
            return self.escalate(
                gate,
                "bisection could not isolate a single offender "
                "(possible multiple offenders or unisolatable failure)",
            )

        gate.merged_branch_ids = list(result.merged_branches)
        # Physically fast-forward the proven-safe branches onto the base branch.
        self._complete_gate(gate, result.merged_branches)
        gate.notes = (
            f"isolated offender {result.offender!r}; merged "
            f"{len(result.merged_branches)} safe branch(es), dropped "
            f"{result.dropped_branches}."
        )
        return gate

    def drop_offender_and_rerun(self, gate: Gate, base_branch: str | None = None) -> Gate:
        """Re-run the gate on the remaining (non-dropped) branches.

        Uses the bisection recorded on ``gate`` to compute the reduced branch set.
        Returns a brand-new :class:`Gate`.
        """

        base = base_branch or gate.base_branch
        remaining = [b for b in gate.branch_ids if b not in set(gate.dropped_branch_ids)]
        return self.run_gate(remaining, base)

    def escalate(self, gate: Gate, reason: str) -> Gate:
        """Mark the gate escalated with a reason for the Pipeline Agent."""

        gate.status = "escalated"
        gate.notes = reason
        return gate

    # -- internal: specs -----------------------------------------------------

    def _specs_for_gate(self) -> list:
        """Enabled unit + ci specs, ordered (unit, then ci, by label)."""

        specs: list = []
        for group in (TestSpecGroup.UNIT, TestSpecGroup.CI):
            specs.extend(self.test_spec_repo.by_group(group))
        enabled = [s for s in specs if s.enabled]
        return sorted(enabled, key=lambda s: (_GROUP_ORDER.get(s.group.value, 99), s.label))

    # -- internal: worktree cwd bookkeeping ----------------------------------

    @contextmanager
    def _active_worktree(self, merge_branches: Sequence[str], base_branch: str, gate_id: str | None = None):
        """Run a block with a single active gate worktree (checkout + merge).

        Sets ``self._active_cwd`` so the injected runner receives a real cwd.
        """

        wt = GateWorktree(self.git, self.runner, gate_id or self._active_gate_id or "isol", base_branch)
        wt.merge(merge_branches)
        prev_cwd = self._active_cwd
        prev_gate = self._active_gate_id
        prev_wt = self._active_wt
        self._active_cwd = wt.cwd
        self._active_gate_id = wt.gate_id
        self._active_wt = wt
        try:
            yield wt
        finally:
            self._active_cwd = prev_cwd
            self._active_gate_id = prev_gate
            self._active_wt = prev_wt
            wt.cleanup()

    # -- internal: merge / cleanup -------------------------------------------

    def _complete_gate(self, gate: Gate, branch_ids: Sequence[str]) -> None:
        """Fast-forward every candidate branch into the base branch."""

        for branch in branch_ids:
            # Merge onto the real base branch of the repo (not a worktree).
            self.git.merge_into_base(branch, gate.base_branch)
        gate.merged_branch_ids = list(branch_ids)
        gate.status = "completed"

    # -- internal: isolation -------------------------------------------------

    def _isolation_passes(self, gate: Gate, base_branch: str, failed_tests: list[str]) -> bool:
        """Re-run the failed tests in isolation on the full merged batch.

        Returns ``True`` if they all pass (transient/environmental failure).
        """

        selectors = self._selectors_for_tests(gate, failed_tests)
        specs = self._specs_for_gate()
        if not specs or not selectors:
            return False

        with self._active_worktree(gate.branch_ids, base_branch, gate.gate_id):
            for spec in specs:
                selector = selectors.get(spec.id, "")
                command = spec.run_in_isolation(selector) if selector else spec.command
                proc = self.runner(command, self._active_cwd, self.timeout)
                if not self._is_clean_run(proc):
                    return False
            return True

    def _selectors_for_tests(self, gate: Gate, failed_tests: list[str]) -> dict[str, str]:
        """Map spec.id -> failed-test selector to run that spec in isolation.

        Heuristic: attribute each failed test to the spec whose label it contains;
        a spec with no matching label gets *all* failed tests (a safe superset for
        a ``-k`` expression). This keeps isolation re-runs focused while never
        missing a test the spec might own.
        """

        selectors: dict[str, str] = {}
        # pytest reports failures as ``file.py::test_name``. A ``-k`` expression
        # matches test *names*, not file paths, so isolate on the node-id (after
        # ``::``) which is a plain identifier and safe as a ``-k`` keyword.
        clean = [t.split("::")[-1] for t in failed_tests]
        for spec in self._specs_for_gate():
            matched = [t for t in clean if spec.label and spec.label in t]
            # A ``-k`` expression is an OR of keyword substrings; join the
            # matched node-ids so ``run_in_isolation`` receives a string, not a
            # list. Falls back to *all* failed node-ids when the label matches
            # nothing (a safe superset for the spec).
            selectors[spec.id] = " or ".join(matched or clean)
        return selectors

    @staticmethod
    def _is_reproducing_failure(proc: Any) -> bool:
        """True if a spec run reproduces the failing test(s).

        A real failure (non-zero exit) reproduces. pytest exit code ``5`` (no
        tests collected / all deselected) means the isolation selector matched
        nothing -- we therefore cannot attribute the failure to this run, so it
        does *not* reproduce. Any other non-zero code is a genuine failure.
        """

        rc = getattr(proc, "returncode", 0)
        return rc != 0 and rc != 5

    def _is_clean_run(self, proc: Any) -> bool:
        """A run that does not reproduce the failure (pass or no-tests-collected)."""

        return not self._is_reproducing_failure(proc)

    # -- internal: bisection -------------------------------------------------

    def _bisect(self, gate: Gate, base_branch: str, failed_tests: list[str]) -> Any:
        """Run ``bisect_branches`` over the gate's candidate branches.

        ``is_failing_fn(subset)`` builds a fresh worktree merging only the subset
        and runs the failed tests in isolation, reporting whether they fail.
        """

        from orchestrator.merge_queue import bisect_branches

        candidates = list(gate.branch_ids)

        def is_failing_fn(subset: Sequence[str]) -> bool:
            return self._subset_reproduces_failure(subset, base_branch, failed_tests)

        return bisect_branches(candidates, is_failing_fn)

    def _subset_reproduces_failure(self, subset: Sequence[str], base_branch: str, failed_tests: list[str]) -> bool:
        """Build a worktree with only ``subset`` merged and run the failed tests."""

        selectors = self._selectors_for_tests(None, failed_tests)
        specs = self._specs_for_gate()
        if not specs or not selectors:
            return False

        with self._active_worktree(list(subset), base_branch, self._active_gate_id or "bisect"):
            for spec in specs:
                selector = selectors.get(spec.id, "")
                command = spec.run_in_isolation(selector) if selector else spec.command
                proc = self.runner(command, self._active_cwd, self.timeout)
                if self._is_reproducing_failure(proc):
                    return True
            return False
