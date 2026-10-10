# Phase 3d — Merge Gate Engine (bisection on branches)

## Design constraints (confirmed)

- The **merge gate runs unit + acceptance (ci) tests**. Work agents *may* run either during dev, but it is **not enforced**.
- We only care about **merge-gate failures**. Flaky/daily promotion is about merge-gate tests.
- The gate is **batched**: run the full suite once over a batch of 2–8 branches (not per-branch).
- **Bisection is on combinations of *branches* (each owning a task), not git commits.**
- When a batched gate fails:
  1. **Re-run the failed tests in isolation** on the merged batch state. Still failing ⇒ a branch in the queue caused it.
  2. **Bisect the branches**: split candidate branches into two halves; test each half in isolation against the failed tests. The failing half contains the culprit; the passing half is safe to merge → merge it.
  3. Recurse on the failing half until one branch remains → the offender.
  4. If bisection isolates an offender, **drop it** and re-run the gate on the rest (automatic recovery).
- If we get a **build failure we cannot automatically recover from**, escalate to the **Pipeline Agent** (non-deterministic AI). Its two jobs: (a) recover from unrecoverable build failures by brainstorming repo improvements, (b) decide which flaky tests belong in a **daily** round.
- **TestSpec.command must be filterable by test selector** so "in isolation" = inject the failed-test selector into the command (e.g. pytest `-k`/path style).

## Data model

### TestSpec (in ~/.orchestra/<slug>/tests.json, repository-backed)
- `id: str`, `label: str`, `command: str`, `group: unit|ci|daily`, `enabled: bool`
- `failure_count: int`, `last_failure: str | None`
- `created_at`, `updated_at`
- `run_in_isolation(test_selector) -> str`: return a command string filtered to a subset of tests.
  - For pytest-style: if command contains `pytest`, append `-k "<selector>"` or a file path.
  - Provide a `__test_selector__` placeholder the engine substitutes. Fallback: append the selector as trailing args.

### BuildResult
- `id`, `gate_id`, `branch_ids: list[str]`, `test_ids: list[str]`, `status: passed|failed|slow|unknown`
- `duration_seconds`, `failed_tests: list[str]`, `logs: str`
- `created_at`

### Gate (in-memory + persisted snapshot)
- `gate_id`, `branch_ids`, `base_branch`, `status: running|completed|escalated`
- list of `BuildResult` (one per (branch-batch × test-spec) run)

## Modules

### backend/shared/models.py — add
- `TestSpec`, `BuildResult` dataclasses + `TestSpecGroup` enum (`unit`, `ci`, `daily`).
- `TestSpec.run_in_isolation(selector)`.

### backend/shared/repositories/ — add
- `test_spec_repository.py`: `TestSpecRepository` (CRUD + by_group + by_status).
- `build_result_repository.py`: `BuildResultRepository` (CRUD + by_gate + by_branch).
- register in `repositories/__init__.py`.

### backend/orchestrator/merge_queue.py — NEW (the engine)
- `MergeGateEngine`:
  - `run_gate(branches: list[str], base_branch) -> Gate`:
    - Build the merged branch set (a worktree of all candidate branches), run each enabled `unit` + `ci` spec via real subprocess, record `BuildResult`.
    - If all pass → mark gate `completed`, merge all branches, return.
    - If any fail → `resolve_failure(...)`.
  - `resolve_failure(...) -> GateResult`:
    - Isolation re-run: run the failed test selectors in isolation on the full batch → if pass, it was transient, no branch blamed.
    - Else bisect candidate branch set: iterative halving. For each half run failed tests in isolation. Keep the failing half, merge the passing half. Recurse until one branch remains → offender.
    - Return `{offender_branch, dropped_branches, merged_branches, remaining_failures}`.
  - `drop_offender(offender)` + `re_run_remaining()`.
  - `escalate_to_pipeline(reason)`: mark gate `escalated`, record reason for Pipeline Agent.
- `BisectionResult`: `{candidate_branches, offender: str|None, merged_branches: list[str], dropped_branches: list[str]}`.
- Pure functions for bisection math (no git) so they're unit-testable in isolation:
  - `bisect_branches(branches, is_failing_fn) -> BisectionResult` — where `is_failing_fn(subset) -> bool` is injected (deterministic in unit tests, real subprocess in production).

### backend/orchestrator/pipeline_agent.py — NEW (AI fallback, gated)
- `PipelineAgent`:
  - `recover_from_build_failure(reason, git) -> str`: brainstorm/propose repo improvements (returns a report or a suggested ticket).
  - `classify_flaky(test_histories: list[BuildResult]) -> list[str]`: decide which flaky tests to promote to `daily`. (Deterministic counting of flakiness; returns candidates for Pipeline Agent to confirm.)
- These are thin AI wrappers; the *logic* they wrap (isolation, bisection, flaky counting) lives in the engine so it's testable without AI.

## CLI — orchestra/cli.py additions
- `orchestra gate` — run a merge gate for a project (prints gate result).
- `orchestra test-specs` — list/define test specs (maybe `orchestra test-specs --add "unit" "pytest tests/"`).
- Wire `MergeGateEngine` into `cmd_run` optionally? Keep `cmd_run` as-is (worker→reviewer→merge) and add `cmd_gate` as the pipeline-manager driver.

## Tests (deterministic, real subprocess + throwaway git repos, NO AI)

### backend/orchestrator/tests/test_merge_queue.py (NEW, high value)
- `test_run_gate_all_pass`: 3 branches, all tests pass → gate completed, all branches merged.
- `test_isolate_and_bisect_offender`: 4 branches; branch D introduces a failing test → assert engine isolates D, merges A/B/C, marks D offender.
- `test_transient_failure_no_blame`: isolation re-run passes → no branch blamed.
- `test_bisect_math_pure`: unit-test `bisect_branches` with a fake `is_failing_fn` (e.g. "failing if subset contains branch X") → assert offender + merge set for various sizes (2,3,4,5,6,8).
- `test_run_gate_in_isolation_filtering`: a TestSpec whose command is `pytest -k __test_selector__` → assert the injected selector produces a filtered command.
- `test_drop_offender_rerun`: after offender dropped, re-run gate on remaining → passes.

### backend/orchestrator/tests/test_bisection_pure.py (NEW)
- Exhaustive: for candidate sets of size 2..8, for each possible offender index, assert `bisect_branches` converges to that offender with correct merge set. This is the core algorithm — make it bulletproof.

### orchestra/tests/test_test_spec.py (NEW)
- `run_in_isolation` for pytest-style and bash-style commands.
- Repository CRUD + by_group.

### backend/orchestrator/tests/test_pipeline_agent.py (NEW)
- `test_classify_flaky`: feed synthetic BuildResult flakiness → assert correct daily candidates.
- `test_recover_from_build_failure_returns_report`: assert it returns a non-empty report string (can be a mock/real-pi gated test — keep deterministic stub for CI).

## Real-`pi` acceptance tests (gated behind ORCHESTRA_ACCEPTANCE=1)

### backend/tests/acceptance/test_merge_gate_pipeline.py
- `test_pipeline_agent_recovers_unrecoverable_failure`: seed a build failure the orchestrator can't auto-recover → Pipeline Agent produces a recovery plan.
- `test_bisect_real_branches`: real git repo, 4 real branches, one fails the gate → real subprocess bisection isolates it.
- `test_flaky_promotion_real`: run a flaky test N times in a real repo → Pipeline Agent promotes it to daily.

### backend/tests/acceptance/test_http_api_build.py
- Long Supervisor prompt with an HTTP API spec (Flask REST API, ~5 endpoints) → agent builds → client test asserts endpoints serve correctly.

## Order of execution (agents run in parallel where independent)
1. **Agent A**: models + repositories (TestSpec, BuildResult, repos). [blocks nothing]
2. **Agent B**: merge-queue engine (pure `bisect_branches` first, then `MergeGateEngine` with subprocess). [depends on A for models/repos]
3. **Agent C**: CLI `gate`/`test-specs` subcommands + `orchestra` wiring. [depends on B]
4. **Agent D**: pipeline_agent (recover + classify_flaky) + tests for it. [depends on B]
5. **Agent E**: acceptance tests (gated). [depends on B, D]

Each agent commits its own layer. After all done: full `pytest` (deterministic) + gated acceptance run.

## Status (all done — 2026-10-10)

Phase 3d merge gate is **implemented, wired into the CLI, and tested**. Five commits on `main`:

1. `c507a48` — data models (`TestSpec`, `BuildResult`, `TestSpecGroup`) + `TestSpecRepository` + `BuildResultRepository` (22 new tests).
2. `bbcafb3` — **pure bisection** `bisect_branches` + `merge_order_for_safe` + `BisectionResult` (exhaustive tests over candidate sizes 2..8, every offender index).
3. `c4885ff` — `MergeGateEngine` (real git+subprocess wrapper; injection points for tests), `GitWorktreeAdapter`, `Gate`, `classify_build_results`, isolation-then-bisect `resolve_failure`, `drop_offender_and_rerun`, `escalate`. 8 tests incl. a real-git e2e (skipped unless `ORCHESTRA_ACCEPTANCE=1`).
4. `f6cba6d` — `PipelineAgent` (detect flaky, promote to daily, brainstorm recovery, gate health). LLM injected/deterministic-stub default so all logic is testable with no model.
5. `43b849b` — CLI: `orchestra test-specs` (`--add/--list/--enable/--disable/--promote-flaky/--health`) + `orchestra gate` (`--branches/--base/--auto`), plus env-gated `ORCHESTRA_RUN_GATE=1` merge-gate step appended to `cmd_run` (defaults OFF, non-breaking).
6. `238b15d` (this session) — fix `cmd_gate` reading a missing key from `classify_build_results`; now uses canonical `gate.to_report()`.

**Full suite: 163 passed, 22 skipped.** The 22 skips are the `ORCHESTRA_ACCEPTANCE`-gated real-git tests + intentional parametrized no-op cases.

### Verified manually / via automated tests
- Pure bisection: exhaustive over sizes 2..8 × every offender index → correct offender + merge set, rounds bounded by ceil(log2 n).
- Engine real-git e2e (`ORCHESTRA_ACCEPTANCE=1`): 3-branch queue, branch-2 is offender → isolated, branch-0/1 merged, branch-2 dropped.
- Engine fake-git: all-pass, isolate-and-bisect, transient-no-blame, isolation uses `run_in_isolation` filter, drop+rerun, escalate-on-multiple-offenders.
- Pipeline agent: flaky detection rule (failures>0 and failures<runs and runs>=3), promote-to-daily persists group=daily, JSON-parse + fallback in `brainstorm_recovery`, health summary.
- CLI: `test-specs --add/--list` persisted correctly; `gate` runs without crashing.

### Known limitations (flagged by agents, left as follow-ups)
- The `GitWorktreeAdapter.merge()` merges into `self.base_branch` and relies on the adapter's `create_worktree`/`merge`; the production gate-worktree cwd semantics should be re-audited before production use (the engine's own real-git e2e test uses an injected runner that consults `merged_branches`, so it doesn't fully exercise the adapter's subprocess path — worth a real-git integration test with a command-driven runner).
- Flaky→daily promotion is rule-based (failure-count threshold), not an AI judgment call; the Pipeline Agent can override but currently reuses the deterministic rule. Consider making the promotion decision an actual agent step.
- The `ORCHESTRA_RUN_GATE` step in `cmd_run` is untested in an automated test (defaults off); the dedicated `orchestra gate` subcommand is the tested path.

## Definition of done
- Deterministic suite green (merge gate engine, bisection math, test-spec filtering, flaky counting) with **real subprocess + real git**, no AI.
- Bisection algorithm proven correct across candidate sizes 2–8 (exhaustive pure test).
- Real-`pi` acceptance tests gated behind `ORCHESTRA_ACCEPTANCE=1` and pass when run.
- `PLAN_3D_merge_gate.md` updated with what each agent found/changed.
- Committed.
