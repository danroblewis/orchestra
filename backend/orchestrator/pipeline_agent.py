"""Pipeline Agent (non-AI logic layer for Phase 3d).

This module holds the *deterministic* logic that the real Pipeline Agent (a Pi
session) wraps. It has two jobs:

1. Detect flaky merge-gate tests and decide which to promote to a ``daily``
   test round (flaky tests should not block merges but should still run).
2. Produce a recovery report when the merge gate hits an unrecoverable build
   failure and automatic recovery (bisection) cannot resolve it.

The LLM is an injected dependency (``llm: Callable[[str], str]``) so all of the
flaky-detection, promotion, JSON-parsing/fallback and health-summary logic is
fully unit-testable without hitting a real model. Only the ``brainstorm_recovery``
"real model" path uses the injected callable, and it degrades gracefully to a
canned report when the model output cannot be parsed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from shared.models import BuildResult, TestSpec, TestSpecGroup


# Minimum gate runs observed before we trust a flaky signal. A test that failed
# once out of 2 runs is not enough evidence; three or more is.
_MIN_RUNS_FOR_FLAKY = 3


# Marker stored in a TestSpec's ``notes`` when the Pipeline Agent has promoted it
# to the daily round so we do not re-promote it on a later pass.
_PROMOTED_TO_DAILY_NOTE = "promoted_to_daily"


@dataclass
class FlakyAssessment:
    """Flakiness assessment for a single TestSpec over its gate history."""

    test_id: str
    label: str
    runs: int  # total gate runs observed for this spec
    failures: int  # times it failed
    flaky: bool  # failures > 0 and failures < runs (not always failing/passing)
    promote_to_daily: bool  # Pipeline Agent's decision


@dataclass
class RecoveryReport:
    """Recovery report produced when the merge gate fails unrecoverably."""

    reason: str
    findings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    proposed_tickets: list[str] = field(default_factory=list)


def _default_llm(prompt: str) -> str:
    """Deterministic stub used when no LLM is injected.

    Returns a canned JSON report so the module is runnable end-to-end and the
    ``brainstorm_recovery`` logic can be exercised without a real model.
    """

    return json.dumps(
        {
            "findings": [
                "Merge gate failed unrecoverably; automatic bisection could not isolate the offender.",
            ],
            "suggestions": [
                "Split the monolithic unit command into per-package shims so a failing package reruns in isolation.",
                "Add a test-time cache warmup step to avoid cold-start flakiness on the gate.",
            ],
            "proposed_tickets": [
                "Speed up merge gate: shard unit tests per package",
                "Add flaky-test isolation shim for the slow acceptance suite",
            ],
        }
    )


class PipelineAgent:
    """Deterministic Pipeline Agent logic wrapping flaky detection + recovery."""

    def __init__(
        self,
        test_spec_repo=None,
        build_result_repo=None,
        llm: Optional[Callable[[str], str]] = None,
    ):
        # Repos are optional: the repo-backed methods accept them explicitly,
        # but constructors may also hold a default so a Pi session can call
        # them with no arguments.
        self.test_spec_repo = test_spec_repo
        self.build_result_repo = build_result_repo
        self.llm = llm or _default_llm

    # --- 1. flaky detection --------------------------------------------------

    @staticmethod
    def _group_results_by_spec(results: list[BuildResult]) -> dict[str, list[BuildResult]]:
        """Group build results by the test spec id they exercised.

        A single BuildResult is per-(batch x gate) and lists the test specs it
        ran via ``test_ids``. We bucket each result under every spec it touched
        so we can measure how often each spec passed/failed across all gates.
        """

        grouped: dict[str, list[BuildResult]] = {}
        for r in results:
            for spec_id in r.test_ids:
                grouped.setdefault(spec_id, []).append(r)
        return grouped

    def detect_flaky_tests(self, build_result_repo) -> list[FlakyAssessment]:
        """Assess each enabled unit/ci TestSpec for flakiness.

        For every spec we count total runs and failures across all observed
        build results. A spec is ``flaky`` when:
          * it has failed at least once (``failures > 0``),
          * it has also passed at least once (``failures < runs``),
          * and we have enough samples (``runs >= _MIN_RUNS_FOR_FLAKY``).

        ``promote_to_daily`` mirrors ``flaky``: the baseline rule is that any
        detected-flaky spec should move out of the blocking merge-gate round and
        into the non-blocking daily round.

        Results are sorted by ``failures`` descending (worst offenders first).
        """

        specs = build_result_repo.enabled()
        spec_by_id = {s.id: s for s in specs}

        # Only consider specs that are unit/ci (the merge-gate rounds). Daily
        # specs already live in the non-blocking round.
        gate_groups = {TestSpecGroup.UNIT.value, TestSpecGroup.CI.value}

        all_results = build_result_repo.find_all()
        grouped = self._group_results_by_spec(all_results)

        assessments: list[FlakyAssessment] = []
        for spec_id, spec in spec_by_id.items():
            if spec.group.value not in gate_groups:
                continue

            runs_results = grouped.get(spec_id, [])
            runs = len(runs_results)
            failures = sum(1 for r in runs_results if r.status == "failed")

            flaky = (
                failures > 0
                and failures < runs
                and runs >= _MIN_RUNS_FOR_FLAKY
            )
            assessments.append(
                FlakyAssessment(
                    test_id=spec_id,
                    label=spec.label,
                    runs=runs,
                    failures=failures,
                    flaky=flaky,
                    promote_to_daily=flaky,
                )
            )

        assessments.sort(key=lambda a: (-a.failures, a.label))
        return assessments

    # --- 2. promotion --------------------------------------------------------

    def promote_flaky_to_daily(
        self,
        assessments: list[FlakyAssessment],
        test_spec_repo=None,
    ) -> list[str]:
        """Promote flaky specs to the daily round and persist them.

        For each assessment with ``promote_to_daily=True`` the corresponding
        TestSpec's ``group`` is set to DAILY (it stays enabled), a marker is
        written to ``notes`` so it will not be re-promoted, and the change is
        saved. Returns the list of promoted spec ids.
        """

        repo = test_spec_repo or self.test_spec_repo
        promoted: list[str] = []

        for a in assessments:
            if not a.promote_to_daily:
                continue
            spec = repo.find(a.test_id)
            if spec.group.value == TestSpecGroup.DAILY.value:
                # Already promoted; leave the marker as-is and skip re-saving.
                continue
            spec.group = TestSpecGroup.DAILY
            existing_notes = (spec.notes or "").strip()
            marker = f" {_PROMOTED_TO_DAILY_NOTE}"
            if existing_notes:
                spec.notes = f"{existing_notes}{marker}"
            else:
                spec.notes = marker.strip()
            repo.save(spec)
            promoted.append(spec.id)

        return promoted

    # --- 3. recovery brainstorm ---------------------------------------------

    def brainstorm_recovery(self, reason: str, git_repo: str | None = None) -> RecoveryReport:
        """Brainstorm improvements/recovery for an unrecoverable gate failure.

        Delegates the "creative" brainstorm to the injected LLM (a Pi session in
        production). The response is expected to be JSON with keys ``findings``,
        ``suggestions`` and ``proposed_tickets``. If the LLM output cannot be
        parsed, we fall back to a deterministic triage report.
        """

        prompt = (
            "Orchestra Pipeline Agent: a merge gate failed unrecoverably. "
            f"Reason: {reason}."
            + (f" Target repository: {git_repo}." if git_repo else "")
            + " Brainstorm improvements to the target repo's codebase to speed up "
            "the merge gate and tests, and to recover. Respond as JSON with keys: "
            "findings (list), suggestions (list of concrete repo changes), "
            "proposed_tickets (list of Task titles)."
        )

        try:
            raw = self.llm(prompt)
            data = json.loads(raw)
            report = RecoveryReport(
                reason=reason,
                findings=list(data.get("findings", [])),
                suggestions=list(data.get("suggestions", [])),
                proposed_tickets=list(data.get("proposed_tickets", [])),
            )
            if not report.findings:
                report.findings = [reason]
            return report
        except (json.JSONDecodeError, TypeError, AttributeError):
            return RecoveryReport(
                reason=reason,
                findings=[reason],
                suggestions=["Investigate manually"],
                proposed_tickets=[f"Triage merge gate failure: {reason}"],
            )

    # --- 4. gate health summary ---------------------------------------------

    def summarize_gate_health(self, build_result_repo) -> dict:
        """Aggregate merge-gate health for the web viewer / logs.

        Returns a dict with:
          * total_runs: number of build results observed
          * overall_pass_rate: fraction (0..1) of runs that passed
          * flaky_specs: count of flaky unit/ci specs
          * always_failing_specs: count of specs that always failed (regressions)
          * slowest_specs: specs sorted by their max recorded duration (desc)
        """

        specs = build_result_repo.enabled()
        spec_by_id = {s.id: s for s in specs}
        all_results = build_result_repo.find_all()

        total_runs = len(all_results)
        passed = sum(1 for r in all_results if r.status == "passed")
        pass_rate = (passed / total_runs) if total_runs else 0.0

        grouped = self._group_results_by_spec(all_results)

        flaky_count = 0
        always_failing_count = 0
        slowest: list[dict] = []

        for spec_id, spec in spec_by_id.items():
            if spec.group.value not in (TestSpecGroup.UNIT.value, TestSpecGroup.CI.value):
                continue

            runs_results = grouped.get(spec_id, [])
            runs = len(runs_results)
            failures = sum(1 for r in runs_results if r.status == "failed")

            flaky = failures > 0 and failures < runs and runs >= _MIN_RUNS_FOR_FLAKY
            if flaky:
                flaky_count += 1
            if runs > 0 and failures == runs:
                always_failing_count += 1

            durations = [r.duration_seconds for r in runs_results if r.duration_seconds]
            if durations:
                slowest.append(
                    {
                        "test_id": spec_id,
                        "label": spec.label,
                        "max_duration_seconds": max(durations),
                    }
                )
        slowest.sort(key=lambda d: d["max_duration_seconds"], reverse=True)

        return {
            "total_runs": total_runs,
            "overall_pass_rate": round(pass_rate, 4),
            "flaky_specs": flaky_count,
            "always_failing_specs": always_failing_count,
            "slowest_specs": slowest,
        }
