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

from dataclasses import dataclass, field
from typing import Callable


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
