"""Pure bisection tests for the merge gate engine.

This is the highest-value test in Phase 3d: it exhaustively verifies correctness
of ``bisect_branches`` for every candidate-set size from 2..8 and every possible
offender index, using an injected predicate that simply answers "does this
subset contain the offender branch?".

We also verify round efficiency (bounded by ``ceil(log2(n))``), the size-1
case, and the transient/no-blame path, plus ``merge_order_for_safe``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Make backend importable so `from orchestrator.merge_queue import ...` works,
# mirroring the sys.path insertion in orchestrator.py and the sibling tests.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from orchestrator.merge_queue import bisect_branches, merge_order_for_safe, BisectionResult


# --- Predicate helpers ------------------------------------------------------

def offender_predicate(offender: str):
    """Return an ``is_failing_fn`` that is True iff the subset contains ``offender``."""

    def _fn(subset: list[str]) -> bool:
        return offender in subset

    return _fn


def always_failing(_subset: list[str]) -> bool:
    return True


def always_passing(_subset: list[str]) -> bool:
    return False


# --- Exhaustive correctness over sizes 2..8 and every offender index --------

@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("offender_idx", [0, 1, 2, 3, 4, 5, 6, 7])
def test_isolates_the_true_offender(n: int, offender_idx: int):
    branches = [f"branch-{i}" for i in range(n)]

    # Indices beyond the set size simply cannot occur; skip those.
    if offender_idx >= n:
        pytest.skip("offender index not in set")

    offender = branches[offender_idx]
    result = bisect_branches(branches, offender_predicate(offender))

    # The reported offender must be the true culprit.
    assert result.offender == offender
    # The offender must be dropped (never merged).
    assert offender in result.dropped_branches
    assert offender not in result.merged_branches
    # No other branch may be wrongly blamed: everything dropped is the offender.
    assert set(result.dropped_branches) == {offender}
    # All non-offender branches are proven safe and merged.
    others = [b for b in branches if b != offender]
    assert set(others) == set(result.merged_branches)
    # candidate set preserved.
    assert result.candidate_branches == branches
    assert result.rounds >= 1


# --- Efficiency of rounds ---------------------------------------------------

@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
def test_rounds_are_efficient(n: int):
    branches = [f"branch-{i}" for i in range(n)]
    expected_rounds = math.ceil(math.log2(n))
    max_rounds = n  # never exceeds n

    for offender in branches:
        result = bisect_branches(branches, offender_predicate(offender))
        assert result.rounds <= max_rounds, f"rounds {result.rounds} exceeded n={n}"
        # Efficiency bound holds for the worst offender in this set.
        assert result.rounds <= expected_rounds + 1, (
            f"offender={offender} took {result.rounds} rounds; "
            f"ceil(log2({n}))={expected_rounds}"
        )


def test_rounds_match_log2_bound_exactly_for_powers_of_two():
    # For n = 2, 4, 8 the number of rounds is exactly ceil(log2(n)).
    for n in (2, 4, 8):
        branches = [f"branch-{i}" for i in range(n)]
        expected = math.ceil(math.log2(n))
        for offender in branches:
            result = bisect_branches(branches, offender_predicate(offender))
            assert result.rounds == expected, (
                f"n={n} offender={offender}: got {result.rounds} rounds, "
                f"expected {expected}"
            )


# --- Edge cases -------------------------------------------------------------

def test_size_one_failing_returns_offender():
    branches = ["only-branch"]
    result = bisect_branches(branches, offender_predicate("only-branch"))
    assert result.offender == "only-branch"
    assert result.dropped_branches == ["only-branch"]
    assert result.merged_branches == []
    assert result.rounds == 0


def test_size_one_passing_is_no_blame():
    branches = ["only-branch"]
    result = bisect_branches(branches, always_passing)
    assert result.offender is None
    assert result.merged_branches == ["only-branch"]
    assert result.dropped_branches == []
    assert result.rounds == 0


def test_no_blame_always_false():
    branches = [f"branch-{i}" for i in range(6)]
    result = bisect_branches(branches, always_passing)
    assert result.offender is None
    assert result.merged_branches == branches
    assert result.dropped_branches == []
    assert result.rounds == 0


def test_all_failing_predicate_still_isolates_single_branch():
    # With a predicate that always fails, BOTH halves always "fail", so no half
    # can ever be proven safe. The bisection descends the left side every time
    # and returns the first branch, and nothing else can be merged.
    branches = [f"branch-{i}" for i in range(6)]
    result = bisect_branches(branches, always_failing)
    assert result.offender == branches[0]
    assert result.dropped_branches == branches
    assert result.merged_branches == []


# --- Merge order ------------------------------------------------------------

def test_merge_order_for_safe_flattens_in_order():
    halves = [
        ["branch-0", "branch-1"],
        ["branch-2"],
        ["branch-3", "branch-4"],
    ]
    assert merge_order_for_safe(halves) == ["branch-0", "branch-1", "branch-2", "branch-3", "branch-4"]


def test_merge_order_for_safe_empty():
    assert merge_order_for_safe([]) == []


def test_merge_order_preserves_discovery_order():
    # The engine proves the largest safe halves first, so earlier elements of the
    # output correspond to larger/more-early-proven halves.
    branches = [f"branch-{i}" for i in range(8)]
    # Force the offender to be the last branch so the first half (size 4) is
    # proven safe first, then progressively smaller halves.
    result = bisect_branches(branches, offender_predicate("branch-7"))
    merged = result.merged_branches
    # First merge should be the size-4 first half.
    assert merged[:4] == ["branch-0", "branch-1", "branch-2", "branch-3"]
    assert result.offender == "branch-7"


def test_result_is_dataclass_instance():
    branches = ["a", "b"]
    result = bisect_branches(branches, offender_predicate("b"))
    assert isinstance(result, BisectionResult)
    assert result.candidate_branches == ["a", "b"]
