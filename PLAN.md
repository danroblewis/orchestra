# Orchestra — Phase 3 Implementation Plan

**Goal**: Make Orchestra a real, installable multi-agent development orchestrator. It wraps the Pi
agent harness, drives four agent layers in **git worktrees** inside a target repo, enforces a
**verifier/review loop** with structured **ticket hygiene**, and is delivered as a **`uv` CLI**
with separable `run` / `web` commands. Orchestration state lives in `~/.orchestra/<project>/`,
decoupled from the target repo so it can later map to GitHub Issues / Jira via labels.

**Design principles (from design sessions)**:
- Orchestra drives the harness; it does **not** run in-process agents. Each layer is a persistent,
  resumable Pi session.
- The human talks **only** to the Supervisor. The Supervisor ↔ Coordinator + Pipeline Manager.
  Coordinator/Pipeline Manager ↔ Workers.
- Notifications via an in-process event bus; scheduling via the backend (Pi has no cron).
- Storage behind a Repository pattern (JSON now; Jira/Issues later).
- **Work agents are spawned by programmatic automation, never by the Coordinator** (no bottleneck).
- Each ticket = one git worktree. The Pipeline Manager owns merges + worktree cleanup.

---

## 0a. Phase 3c status: REAL RPC TRANSPORT + ORCHESTRATION LOOP — DONE (2026-10-10)

The real `pi --mode rpc` transport and the full worker→reviewer→merge loop are implemented and
**verified end-to-end against a live model** (`ornith-1.5-35b-a3b-q6k`):

- `orchestra/rpc_transport.py` — long-lived `RpcTransport`, one `pi` child per session file, single
  stdin/stdout pipe, `subscribe`→`prompt`→`agent_settled`→`get_last_assistant_text`, `--append-system-prompt`
  for role/context, `cwd=<repo>`. Reads the agent's final text from the **JSONL session log**
  (`_read_log_assistant_text`) rather than the RPC cursor, which was unreliable across multi-turn
  sessions.
- `orchestra/agents.py` — `spawn_worker` / `collect_worker` / `build_diff` / `spawn_reviewer`
  / `collect_reviewer`.
- `orchestra/cli.py::cmd_run` — pickup → spawn (bounded to 1) → collect → build diff + run repo
  tests → reviewer verdict → `apply_ticket_response` (reviewer overrides worker self-assessment →
  DONE only if `review.passed` and CI passes) → `merge_worktree` (FF) → cleanup.
- Fixed `Task.slug` property; `worktree_orchestrator.create_worktree` reclaims orphans from crashed
  runs; `reconcile` purges orphaned Orchestra worktrees/branches.
- **Live e2e result**: a seeded `Add a multiply function` ticket → worker added `multiply(a,b)` +
  test, committed; reviewer ran pytest (`2 passed`), judged `passed=True`; ticket → **done**;
  merged into `main`; worktree cleaned up. `orchestra tickets` shows `[done]`.
- Bug caught during e2e: `spawn`/`collect` must use the same **session file path** (not the bare
  session name) or the transport's per-session cache misses → empty text → false BLOCKED.
- **69 tests pass** (43 orchestra + 26 backend). Committed.

**Next: Phase 3d** — wire the web viewer's worktrees panel + finalize docs.

---

## 0. Current state (Phase 1–2, done)

- `backend/shared/` — models (`Task`, `Milestone`, `BuildOutput`, `SessionLog`, `Status`),
  JSON-backed Repository pattern (`JsonStore`, atomic writes).
- `backend/orchestrator/orchestrator.py` — `Transport` interface, `MockTransport`, `RpcTransport`,
  `Orchestrator` with `drive()`, `run_supervisor_request()`, `run_worker()`, CLI `main()` + `demo`.
- `backend/web/server.py` — read-only FastAPI viewer + cloudflared tunnel (persistent named tunnel
  `orchestra.dansproject.space`, reused across restarts).
- `backend/web/static/index.html` — vanilla-JS graph viewer.
- 26 tests passing. `data/` gitignored.

**Gaps Phase 3 fills** (verified by code survey):
- No git / worktree logic anywhere in `backend/`.
- `drive()` does **not** parse assistant JSON into task state; no verifier loop; no JSON ticket contract.
- No packaging (`pyproject.toml`), no config-file loading, no `~/.orchestra`, no CLI subcommands
  (only a `demo` arg).
- `SessionLog.cwd` field exists but is unused — the hook for a worktree path.
- `RpcTransport.send()` parses a `response` event but `drive()` actually reads via a separate
  `get_last_assistant_text` RPC call — both are real and usable.

---

## 1. Target architecture

```
   human
     │  (talks only to)
     ▼
 ┌─────────────┐   RPC (cwd = target repo)   ┌──────────────┐
 │   Supervisor │ ─────────────────────────▶ │  Coordinator  │  (task graph, planning)
 │  (Pi session)│                              └──────┬───────┘
 └──────┬───────┘                                     │ (task-graph state, no process spawn)
        │        RPC (cwd = target repo)               ▼
        ▼                                            ┌──────────────┐
 ┌─────────────┐   event bus (build fail / settled)  │Pipeline Mgr   │  merges + worktree cleanup
 │PipelineMgr  │◀────────────────────────────────────│  (Pi session) │
 └──────┬───────┘                                     └──────┬───────┘
        │  RPC (cwd = WORKTREE/<slug>)                     │
        ▼                                                  ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  Work trees (one per ticket). Each runs a Worker + Reviewer Pi     │
 │  session in its own worktree. Worker emits a JSON ticket response. │
 │  Reviewer = 2nd Pi session; merge pipeline = CI checks (tests).    │
 └──────────────────────────────────────────────────────────────────┘
        │
        ▼
 ~/.orchestra/<project-slug>/         ← orchestration state (decoupled from repo)
   ├── config.json                     base_branch, model, tools, prompt templates...
   ├── state/
   │   ├── tasks.json                  (task repository)
   │   ├── milestones.json
   │   ├── builds.json
   │   └── session_logs.json
   └── sessions/                       per-session JSONL logs
```

**Key fact**: Orchestra state is **outside** the target repo (`~/.orchestra/<project>/`). The repo
only **configures** Orchestra (via a config file Orchestra reads; e.g. labels to pick tickets).
Orchestra's own `data/` is now `~/.orchestra/<project>/state`, not `<repo>/data`.

---

## 2. Worktree model (the core mechanic)

**One worktree per ticket.** Worktrees are created by Orchestra automation, torn down by the
Pipeline Manager after a successful merge.

- Base branch default: `main`, **configurable** in `~/.orchestra/<project>/config.json` as
  `base_branch`.
- Worktree naming: `.orchestra-wt/<task-slug>` (inside the target repo, so `git worktree add`
  works normally). A manifest `.orchestra-wt/.manifest.json` records `slug → {task_id, branch,
  status}`.
- Status lifecycle of a worktree: `created → working → review → merged → removed`.
- Concurrency: a ticket is picked up by automation when its status is `BACKLOG` and all
  `dependency_ids` are `DONE` (same rule as `next_in_queue()`). Only one worktree per ticket.
- Cleanup safety: on startup, Orchestra reconciles orphaned worktrees (no matching ticket) and
  offers to remove them; the Pipeline Manager removes a worktree only after its branch is merged
  into `base_branch` **and** the merge build passes.

**Git operations** (a small `gitops` module) — thin wrappers around `git` CLI:
`init_worktree(task)`, `branch_exists`, `is_merged_into(base)`, `merge_branch`, `remove_worktree`.
All via `subprocess`, logged. No git Python lib dependency.

**Why worktrees and not just `--cwd`**: Pi's working folder is the process CWD. A worktree gives
the worker a real, isolated, branch-backed checkout so its file edits + commits live on the
ticket's branch, mergeable by the Pipeline Manager. Plain `--cwd` into the repo would dirty the
base checkout.

---

## 3. Ticket-hygiene contract (Worker ↔ Orchestra)

The Worker **must** return structured JSON in its final assistant message. Orchestra extracts it
from `get_last_assistant_text` and applies it to the task.

**Worker response schema** (final assistant message):
```json
{
  "task_id": "<uuid>",
  "state": "DONE | IN_PROGRESS | BLOCKED | FAILED",
  "summary": "what was changed and why",
  "blockers": ["human-readable blocker", "..."],
  "branch": "orchestra-<slug",
  "review": {"required": true, "passed": false, "reviewer": "reviewer-<slug>"},
  "ci": {"status": "pending | passed | failed", "tests_run": 12}
}
```
- `state: DONE` is **only** valid if `review.passed == true` and (if tests exist) `ci.status == "passed"`.
  Otherwise DONE is coerced to FAILED/BLOCKED by Orchestra. This enforces "don't assume it's done
  without verifying."
- `BLOCKED` carries `blockers`; the ticket stays out of the merge queue until unblocked.
- Partial work (`IN_PROGRESS`) is allowed — the branch persists, session is resumable.

**Reviewer**: a **second Pi session** (same worktree, separate session name `reviewer-<slug>`),
prompted to inspect the diff + run CI-relevant checks and return its own JSON verdict. This is the
"automated review pass = running unit tests" — the Reviewer is a Pi agent that can run the repo's
test suite and judge the diff. The **merge pipeline** then runs the *rest* of CI (lint, typecheck,
format, further gate checks) — also expressed as prompt-able checks or shell commands.

---

## 4. Prompt layering (tailored per layer)

Orchestra enriches each session's prompt. Two injection points:
1. **`--append-system-prompt`** at `pi` start (role + project context).
2. **The initial `prompt` message** (the specific task / request).

Tailored prompts:
- **Supervisor**: project context + the human's request. Produces planning output that the
  Coordinator consumes; it does **not** create tasks directly (it proposes; see §5).
- **Coordinator**: full task-graph snapshot (milestones, tasks, deps, statuses, in-flight
  worktrees). Helps plan work and resolve graph issues. **Never** spawns Pi processes.
- **Pipeline Manager**: base branch, active worktrees, merge queue, build results. Drives merges +
  cleanup.
- **Worker**: the single ticket (title, description, deps, acceptance criteria) + project
  conventions (read from repo config/AGENTS.md) + **explicit instructions to (a) work only in its
  worktree, (b) commit on its branch, (c) END with the JSON ticket response, (d) not assume it's
  done until the Reviewer + CI pass.** It *may* read other tickets but shouldn't act on them.
- **Reviewer**: the ticket + the worktree diff + instructions to run checks and return JSON verdict.

**Project context source**: Orchestra reads the target repo's `AGENTS.md` (auto-read by Pi, per
project invariants) and/or a project-provided `orchestra.json`/`pyproject` `[tool.orchestra]`
section for conventions, labels, task taxonomy. This is what "the repo configures Orchestra" means
concretely.

---

## 5. Orchestration loop (automation, not the Coordinator)

The **orchestrator loop** is a programmatic driver (not a Pi agent). It owns spawning workers and
managing the merge pipeline. The Coordinator only ever *mutates task-graph state* via the
repository; it never calls `pi`.

**Loop responsibilities**:
1. **Pickup**: repeatedly find tickets in `BACKLOG` with all deps `DONE` and no existing worktree;
   for each, create a worktree + worker session and spawn a Worker agent (async, bounded
   concurrency). *This is the anti-bottleneck: automation spawns workers, not the Coordinator.*
2. **Collect**: for each running worker, poll `get_last_assistant_text`; parse the JSON ticket
   response; validate & apply state; record a `SessionLog` + `BuildOutput` entry.
3. **Review + CI**: once a Worker reports ready, spawn the Reviewer session; run merge-pipeline CI
   checks.
4. **Merge + cleanup**: when review + CI pass, the Pipeline Manager merges the branch into
   `base_branch`, marks the task `DONE`, and removes the worktree.
5. **Notify**: publish build-failure / slow-build / agent-settled events on the in-process event
   bus; Supervisor surfaces them to the human.

**Concurrency**: a configurable `max_concurrent_workers` (default e.g. 3–5). Workers run as
background subprocesses (or threads) driven by the loop; the loop is the single coordinator of
spawn/collect/merge.

---

## 6. `~/.orchestra` layout + config

```
~/.orchestra/
  <project-slug>/                # slug = repo name, or a name from `orchestra init`
    config.json                  # base_branch, model, thinking, max_concurrent_workers,
                                 #   labels, prompt template paths, repo root
    state/
      tasks.json                 # task repository
      milestones.json
      builds.json
      session_logs.json
    sessions/                    # per-agent JSONL logs (supervisor, coordinator,
                                 #   pipeline-manager, worker-<slug>, reviewer-<slug>)
```

`config.json` example:
```json
{
  "repo_root": "/abs/path/to/target",
  "base_branch": "main",
  "model": "anthropic/claude-sonnet-...",
  "thinking_level": "medium",
  "max_concurrent_workers": 4,
  "labels": ["orchestra-managed"],
  "prompt_templates": {
    "worker": "path/to/worker-prompt.md",
    "reviewer": "path/to/reviewer-prompt.md"
  }
}
```
The repo *provides* config by (a) having an `AGENTS.md` Orchestra reads, and (b) optionally a
`[tool.orchestra]` table in its `pyproject.toml` or an `orchestra.json` at repo root that
`orchestra init`/`orchestra run` merges into `~/.orchestra/<slug>/config.json`.

**Slug resolution**: `orchestra run`/`orchestra web` run from the repo root (CWD). Slug = repo name
unless `--project` is given. Orchestra verifies it's inside a git repo; if not, it errors.

---

## 7. CLI (uv-installable)

`pyproject.toml` with a console-script entry point `orchestra`. Commands:

```
orchestra init                 # detect repo (CWD), write ~/.orchestra/<slug>/config.json
orchestra run                  # start the orchestrator loop (CWD = repo root)
orchestra web                  # start the read-only FastAPI viewer on the project's state
orchestra tickets [list|show|add|done]   # inspect/manage the task graph
orchestra worktrees            # list active worktrees / status
orchestra clean                # reconcile orphaned worktrees, offer removal
```

- `orchestra run` and `orchestra web` are **separate processes** sharing the same
  `~/.orchestra/<slug>/state/`. They communicate only through the persisted store (web is read-only).
- Both resolve the project from CWD; `--project <name>` / `--repo <path>` override.
- `orchestra run` supports `--transport {rpc,mock}` (mock for tests/demo) and `--once`
  (run one pickup/collect cycle then exit — for scripting/tests).
- The existing `demo` behavior moves to `orchestra demo`.

**Packaging**: `pyproject.toml` defines package `orchestra` mapping to `backend/`, dependencies
(`fastapi`, `uvicorn`, `pyyaml`), and entry point. `uv` for install/dev. No build step for the
vanilla-JS frontend; it stays under `backend/web/static/`.

---

## 8. Web viewer updates (Phase 3)

- `/api/state` gains `worktrees` (slug, branch, status, task_id) and `pending` (in-flight workers).
- Frontend shows a Worktrees panel + per-ticket review/CI status badges.
- Session modals already read JSONL — unchanged, now populated by real worker/reviewer sessions.

---

## 9. Phased build order

**Phase 3a — Foundations: packaging + `~/.orchestra` + gitops**
1. Add `pyproject.toml` (`uv`-installable, `orchestra` entry point). Verify `uv run orchestra --help`.
2. Add `orchestra/config.py` — project resolution from CWD, `~/.orchestra/<slug>/` layout,
   `config.json` load/save, slug derivation.
3. Add `orchestra/gitops.py` — `init_worktree`, `branch_exists`, `is_merged_into`, `merge_branch`,
   `remove_worktree`, manifest read/write. Pure subprocess wrappers; unit-testable against a temp
   git repo.
4. Tests: gitops against a throwaway `git init` repo (create branch, merge, remove).

**Phase 3b — Ticket contract + state application**
5. Add `orchestra/ticket_contract.py` — schema constants + `parse_ticket_response(text) -> dict`
   with validation (`validate` enforces DONE⇔review+ci).
6. Extend `Orchestrator` with `assign_worktree(task)`, `apply_ticket_response(task, parsed)`,
   `pick_ready_tickets()`. Wire into a new `orchestra/loop.py` driver.
7. Tests: contract parsing/validation; pick logic (deps DONE, no dup worktree).

**Phase 3c — Real RPC work in worktrees + verifier loop**
8. Rework `RpcTransport` / `drive` to (a) start `pi --mode rpc` with `cwd=<worktree>` and
   `--append-system-prompt` role text, (b) read the JSON response via `get_last_assistant_text`,
   (c) support `--fork` to re-engage a prior worker session.
9. Add `orchestra/agents.py` — `spawn_worker(task)`, `spawn_reviewer(task)`, `poll_worker(task)`,
   each producing the right prompt (§4) and driving the contract.
10. Implement the loop: pickup → spawn (bounded) → collect → review+CI → merge → cleanup.
11. Tests: with `MockTransport`, exercise a full pick→work→review→merge→cleanup cycle end to end
    (mock the git ops + `pi` calls, assert state transitions + worktree lifecycle).

**Phase 3d — CLI wiring + web updates**
12. Replace `main()` demo with argparse subcommands (`init`, `run`, `web`, `tickets`, `worktrees`,
    `clean`, `demo`). `run` launches the loop; `web` launches FastAPI on the project state.
13. Viewer: add worktrees/pending to `/api/state` + frontend panel.
14. Full test suite green; manual e2e against a scratch repo (real `pi` if available, else mock).

---

## 10. Risks / open decisions

- **Prompt schema strictness**: LLMs drift from the JSON contract. Mitigate with a tight prompt +
  regex/JSON extraction fallback + a "respond ONLY with JSON" instruction; coerce invalid responses
  to BLOCKED rather than crashing.
- **Concurrency safety on the store**: multiple worker subprocesses mutate state. The store is
  write-through via repositories; the loop should serialize state mutations (single loop process
  owns writes; workers only emit text). Keep writes in the loop thread, not subprocesses.
- **Worktree cleanup on crash**: orphaned worktrees from killed workers. Reconciliation on startup
  + Pipeline Manager cleanup; manifest tracks ownership.
- **Base branch config**: default `main`, overridable. `orchestra run` must verify the branch
  exists/checked out before creating worktrees.
- **Review cost**: a Reviewer Pi session per ticket is token-heavy. Acceptable for v1; can cache or
  gate on local test pass first to cut reviewer invocations later.
- **`pi` availability**: real RPC needs a working `pi` login/model. Keep `MockTransport` default for
  tests; `orchestra run` requires `--transport rpc` + a configured model.

---

## 11. Definition of done (Phase 3)

- `uv install`-able; `orchestra run` and `orchestra web` work as separate processes from a repo
  root; state in `~/.orchestra/<slug>/`.
- Each ticket gets its own worktree; workers return the JSON ticket contract; a Reviewer session +
  CI checks gate the merge; Pipeline Manager merges to `base_branch` and removes the worktree.
- Coordinator manages graph state but never spawns processes; workers are spawned by automation.
- Tests cover gitops, ticket contract, pick logic, and the full loop cycle with mocks.
