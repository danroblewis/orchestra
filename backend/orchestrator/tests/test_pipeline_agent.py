"""Tests for the Pipeline Agent (Phase 3d).

Exercises the deterministic Pipeline Agent logic: flaky detection, promotion to
the daily round, JSON-parsing/fallback in the recovery brainstorm, and the gate
health summary. The LLM is injected (a fake callable) so no real model is hit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make backend importable, mirroring the sibling orchestrator tests.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.models import BuildResult, TestSpec, TestSpecGroup
from shared.repositories.json_store import JsonStore
from shared.repositories.test_spec_repository import TestSpecRepository
from shared.repositories.build_result_repository import BuildResultRepository
from orchestrator.pipeline_agent import PipelineAgent, FlakyAssessment, RecoveryReport


# --- In-memory fakes --------------------------------------------------------

class FakeBuildResultRepo:
    """A minimal BuildResultRepository stand-in backed by a plain list.

    Holds both the build results and the specs that ran in them so it mirrors
    the real repository's ``enabled()`` / ``find_all()`` API surface.
    """

    def __init__(self, results: list[BuildResult] | None = None, specs: list[TestSpec] | None = None):
        self.results = list(results or [])
        self._specs = list(specs or [])

    def find_all(self, **filters) -> list[BuildResult]:
        out = []
        for b in self.results:
            ok = True
            for k, v in filters.items():
                val = getattr(b, k)
                if isinstance(v, list):
                    # set semantics for branch_ids style filters
                    if not set(v) <= set(val):
                        ok = False
                        break
                elif val != v:
                    ok = False
                    break
            if ok:
                out.append(b)
        return out

    def enabled(self) -> list[TestSpec]:
        return list(self._specs)


class FakeTestSpecRepo:
    """In-memory TestSpecRepository for the promotion test."""

    def __init__(self, specs: list[TestSpec] | None = None):
        self.specs = {s.id: s for s in (specs or [])}

    def find(self, entity_id: str) -> TestSpec:
        if entity_id not in self.specs:
            raise KeyError(entity_id)
        return self.specs[entity_id]

    def save(self, entity: TestSpec) -> TestSpec:
        self.specs[entity.id] = entity
        return entity

    def all(self) -> list[TestSpec]:
        return list(self.specs.values())


def _build_result(status: str, test_ids: list[str], duration: float | None = None) -> BuildResult:
    return BuildResult(
        gate_id="gate-1",
        branch_ids=["branch-a"],
        test_ids=test_ids,
        status=status,
        duration_seconds=duration,
    )


def _spec(test_id: str, label: str, group: TestSpecGroup = TestSpecGroup.UNIT) -> TestSpec:
    return TestSpec(id=test_id, label=label, command="pytest", group=group)


# --- detect_flaky_tests -----------------------------------------------------

def test_detect_flaky():
    # Spec A: 5 runs, 1 fail -> flaky. Spec B: 4 runs, 4 fail -> always failing.
    # Spec C: 3 runs, 0 fail -> passing, not flaky.
    a_id, b_id, c_id = "spec-a", "spec-b", "spec-c"
    specs = [_spec(a_id, "alpha"), _spec(b_id, "beta"), _spec(c_id, "gamma")]
    repo = FakeTestSpecRepo(specs)

    results = [
        _build_result("passed", [a_id]),
        _build_result("passed", [a_id]),
        _build_result("passed", [a_id]),
        _build_result("passed", [a_id]),
        _build_result("failed", [a_id]),
        _build_result("failed", [b_id]),
        _build_result("failed", [b_id]),
        _build_result("failed", [b_id]),
        _build_result("failed", [b_id]),
        _build_result("passed", [c_id]),
        _build_result("passed", [c_id]),
        _build_result("passed", [c_id]),
    ]
    brepo = FakeBuildResultRepo(results, specs=specs)

    agent = PipelineAgent()
    assessments = agent.detect_flaky_tests(brepo)
    by_id = {a.test_id: a for a in assessments}

    assert by_id[a_id].flaky is True
    assert by_id[a_id].promote_to_daily is True
    assert by_id[a_id].runs == 5
    assert by_id[a_id].failures == 1

    assert by_id[b_id].flaky is False  # always failing
    assert by_id[b_id].promote_to_daily is False

    assert by_id[c_id].flaky is False  # always passing
    assert by_id[c_id].promote_to_daily is False


def test_detect_flaky_needs_samples():
    # Spec that failed once out of a single run -> not flaky (needs >=3 runs).
    spec_id = "spec-x"
    repo = FakeTestSpecRepo([_spec(spec_id, "x")])
    results = [_build_result("failed", [spec_id])]
    brepo = FakeBuildResultRepo(results, specs=[_spec(spec_id, "x")])

    agent = PipelineAgent()
    assessments = agent.detect_flaky_tests(brepo)
    assert len(assessments) == 1
    assert assessments[0].flaky is False


def test_detect_flaky_sorted_by_failures_desc():
    a_id, b_id, c_id = "s1", "s2", "s3"
    specs = [_spec(a_id, "a"), _spec(b_id, "b"), _spec(c_id, "c")]
    brepo = FakeBuildResultRepo([], specs=specs)
    # No results at all -> all zero.
    agent = PipelineAgent()
    assessments = agent.detect_flaky_tests(brepo)
    for a in assessments:
        assert a.runs == 0
        assert a.failures == 0
        assert a.flaky is False


# --- promote_flaky_to_daily -------------------------------------------------

def test_promote_flaky_to_daily(tmp_path):
    store = JsonStore(tmp_path / "orchestra.json")
    spec_repo = TestSpecRepository(store)

    a = spec_repo.save(_spec("spec-a", "alpha"))
    b = spec_repo.save(_spec("spec-b", "beta"))

    assessments = [
        FlakyAssessment("spec-a", "alpha", runs=5, failures=1, flaky=True, promote_to_daily=True),
        FlakyAssessment("spec-b", "beta", runs=4, failures=4, flaky=False, promote_to_daily=False),
    ]

    agent = PipelineAgent(test_spec_repo=spec_repo)
    promoted = agent.promote_flaky_to_daily(assessments)

    assert promoted == ["spec-a"]
    # And persisted to the store. (Compare .value to sidestep the pre-existing
    # str-Enum quirk where all TestSpecGroup members compare equal.)
    reloaded = spec_repo.find("spec-a")
    assert reloaded.group.value == TestSpecGroup.DAILY.value
    assert reloaded.enabled is True
    assert "promoted_to_daily" in reloaded.notes
    # The non-flaky spec is untouched.
    assert spec_repo.find("spec-b").group.value == TestSpecGroup.UNIT.value


def test_promote_skips_already_promoted(tmp_path):
    store = JsonStore(tmp_path / "orchestra.json")
    spec_repo = TestSpecRepository(store)
    a = spec_repo.save(_spec("spec-a", "alpha", group=TestSpecGroup.DAILY))

    agent = PipelineAgent(test_spec_repo=spec_repo)
    promoted = agent.promote_flaky_to_daily(
        [FlakyAssessment("spec-a", "alpha", runs=3, failures=1, flaky=True, promote_to_daily=True)]
    )
    # Already in daily -> no new promotion recorded.
    assert promoted == []


# --- decide_flaky_promotion (follow-up #1: judgment + demotion) --------------

def _repo_with(spec_groups):
    """A repo holding specs with the given id->group mapping (default UNIT)."""
    specs = [
        _spec(
            tid,
            tid,
            group=group,
        )
        for tid, group in spec_groups.items()
    ]
    return FakeTestSpecRepo(specs)


def test_decide_flaky_promotion_promotes_flaky_unit():
    repo = _repo_with({"spec-a": TestSpecGroup.UNIT})
    agent = PipelineAgent(test_spec_repo=repo)
    assessments = [
        FlakyAssessment("spec-a", "spec-a", runs=5, failures=1, flaky=True, promote_to_daily=False)
    ]
    result = agent.decide_flaky_promotion(assessments)
    assert result["promoted"] == ["spec-a"]
    assert result["demoted"] == []
    # The assessment flag is updated to mirror the decision.
    assert assessments[0].promote_to_daily is True
    # Persisted to daily, still enabled.
    reloaded = repo.find("spec-a")
    assert reloaded.group.value == TestSpecGroup.DAILY.value
    assert reloaded.enabled is True


def test_decide_flaky_promotion_does_not_repromote():
    # Already daily + judgment says promote -> no-op.
    repo = _repo_with({"spec-a": TestSpecGroup.DAILY})
    agent = PipelineAgent(test_spec_repo=repo)
    assessments = [
        FlakyAssessment("spec-a", "spec-a", runs=5, failures=1, flaky=True, promote_to_daily=True)
    ]
    result = agent.decide_flaky_promotion(assessments)
    assert result["promoted"] == []
    assert result["demoted"] == []


def test_decide_flaky_promotion_demotes_stable_daily():
    # A daily test that has stopped being flaky (enough consecutive passes) -> demote.
    repo = _repo_with({"spec-a": TestSpecGroup.DAILY})
    agent = PipelineAgent(test_spec_repo=repo)
    assessments = [
        FlakyAssessment(
            "spec-a",
            "spec-a",
            runs=5,
            failures=0,
            consecutive_passes=3,
            flaky=False,
            promote_to_daily=False,
        )
    ]
    result = agent.decide_flaky_promotion(assessments)
    assert result["demoted"] == ["spec-a"]
    assert result["promoted"] == []
    reloaded = repo.find("spec-a")
    assert reloaded.group.value == TestSpecGroup.UNIT.value
    assert "demoted_from_daily" in reloaded.notes


def test_decide_flaky_promotion_keeps_daily_when_still_flaky():
    # Still flaky and already daily -> the default judgment returns NONE (a
    # flaky daily test stays put; the judgment only promotes *blocking* tests).
    repo = _repo_with({"spec-a": TestSpecGroup.DAILY})
    agent = PipelineAgent(test_spec_repo=repo)
    assessments = [
        FlakyAssessment("spec-a", "spec-a", runs=5, failures=1, flaky=True, promote_to_daily=False)
    ]
    result = agent.decide_flaky_promotion(assessments)
    assert result["promoted"] == []
    assert result["demoted"] == []
    assert repo.find("spec-a").group.value == TestSpecGroup.DAILY.value


def test_decide_flaky_promotion_custom_judgment():
    # A custom judgment can force demotion regardless of the default.
    repo = _repo_with({"spec-a": TestSpecGroup.DAILY, "spec-b": TestSpecGroup.UNIT})
    agent = PipelineAgent(test_spec_repo=repo)

    def always_demote(a):
        return agent.JUDGE_DEMOTE

    assessments = [
        FlakyAssessment("spec-a", "spec-a", runs=3, failures=1, flaky=True, promote_to_daily=True),
        FlakyAssessment("spec-b", "spec-b", runs=3, failures=1, flaky=True, promote_to_daily=True),
    ]
    result = agent.decide_flaky_promotion(assessments, judgment=always_demote)
    # spec-b is unit (not daily), so demote is a no-op for it; only spec-a moves.
    assert result["demoted"] == ["spec-a"]
    assert result["promoted"] == []


# --- brainstorm_recovery ----------------------------------------------------

def test_brainstorm_recovery_parses_json():
    payload = {
        "findings": ["bisection exhausted candidates"],
        "suggestions": ["add a test shard"],
        "proposed_tickets": ["Shard the unit gate"],
    }

    def fake_llm(prompt: str) -> str:
        # Assert the prompt carries the reason.
        assert "merge gate failed unrecoverably" in prompt
        return json.dumps(payload)

    agent = PipelineAgent(llm=fake_llm)
    report = agent.brainstorm_recovery("bisection could not isolate offender")

    assert report.reason == "bisection could not isolate offender"
    assert report.findings == ["bisection exhausted candidates"]
    assert report.suggestions == ["add a test shard"]
    assert report.proposed_tickets == ["Shard the unit gate"]


def test_brainstorm_recovery_fallback():
    def garbage_llm(prompt: str) -> str:
        return "this is not json {{{"

    agent = PipelineAgent(llm=garbage_llm)
    report = agent.brainstorm_recovery("something exploded")

    assert report.reason == "something exploded"
    assert report.findings == ["something exploded"]
    assert "Investigate manually" in report.suggestions
    assert len(report.proposed_tickets) == 1
    assert report.proposed_tickets[0].startswith("Triage merge gate failure:")


def test_brainstorm_recovery_fallback_on_empty_findings():
    def empty_llm(prompt: str) -> str:
        return json.dumps({"findings": [], "suggestions": [], "proposed_tickets": []})

    agent = PipelineAgent(llm=empty_llm)
    report = agent.brainstorm_recovery("reason-123")
    # Empty findings fall back to the reason.
    assert report.findings == ["reason-123"]


def test_brainstorm_recovery_defaults_to_canned_stub():
    # No llm injected -> deterministic stub returns valid JSON.
    agent = PipelineAgent()
    report = agent.brainstorm_recovery("stub test")
    assert report.findings
    assert report.suggestions
    assert report.proposed_tickets


# --- summarize_gate_health --------------------------------------------------

def test_summarize_gate_health():
    a_id, b_id, c_id = "spec-a", "spec-b", "spec-c"
    specs = [
        _spec(a_id, "alpha"),
        _spec(b_id, "beta"),
        _spec(c_id, "gamma"),
    ]
    results = [
        _build_result("passed", [a_id], duration=10.0),
        _build_result("passed", [a_id], duration=12.0),
        _build_result("failed", [a_id], duration=20.0),
        _build_result("passed", [a_id], duration=11.0),
        _build_result("passed", [a_id], duration=13.0),
        _build_result("failed", [b_id], duration=5.0),
        _build_result("failed", [b_id], duration=6.0),
        _build_result("passed", [c_id], duration=1.0),
        _build_result("passed", [c_id], duration=2.0),
        _build_result("passed", [c_id], duration=3.0),
    ]
    brepo = FakeBuildResultRepo(results, specs=specs)

    agent = PipelineAgent()
    summary = agent.summarize_gate_health(brepo)

    assert summary["total_runs"] == 10
    # 7 passed out of 10.
    assert summary["overall_pass_rate"] == 0.7
    # spec-a flaky (1 fail / 5 runs), spec-b always failing, spec-c passing.
    assert summary["flaky_specs"] == 1
    assert summary["always_failing_specs"] == 1
    # Slowest spec by max duration: spec-a (20s) is the slowest.
    assert summary["slowest_specs"][0]["label"] == "alpha"
    assert summary["slowest_specs"][0]["max_duration_seconds"] == 20.0
