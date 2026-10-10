# Invariants — Orchestra

These are the fixed rules and design decisions for the Orchestra project. **Read this file first** before making any design or architecture decisions. Invariants should not be changed silently — if an invariant must change, it should be called out explicitly and this file updated to reflect the new decision.

## What Orchestra Is

Orchestra is a multi-layer, AI-driven software development workflow orchestrator. It coordinates AI agents that plan and build software. The user interacts with exactly one layer; everything below is managed programmatically.

## The Agent Architecture

The system has four functional layers, each implemented as an **AI agent running on the Pi harness** (not as a plain Python class):

1. **Worker** — implements features/tasks. Lowest layer. Directly does the coding work.
2. **Coordinator** — monitors the task queue, keeps it accurate/prioritized/ordered, ensures tasks are being worked on. Receives requests from the Supervisor. Spawns/engages Worker agents.
3. **Pipeline Manager** — watches the merge queue, coordinates fixes for test failures (unit + acceptance). Directly spawns work agents to fix issues (may re-engage agents from their original dev sessions). Notified on build failures and longer-than-average build times. Maintains a quick, efficient merge pipeline.
4. **Supervisor** — the interactive layer the human talks to. Translates user requirements, requests, observations, and project goals into tasks for the Coordinator and Pipeline Manager. Communicates system state back to the human.

### Communication rules (STRICT)
- The **human user talks ONLY to the Supervisor**. The user never talks directly to Coordinator, Pipeline Manager, or Workers.
- The **Supervisor talks to the Coordinator and the Pipeline Manager** directly.
- The **Coordinator and Pipeline Manager talk to each other** and to Workers.
- Workers do NOT talk to the user.

## Each Layer = A Persistent Pi Session

Each of the four layers is a **separate, persistent, resumable Pi agent session** (a JSONL session file with a stable name). The orchestrator drives these sessions over the Pi RPC protocol (`pi --mode rpc`), sending prompts / steers / follow-ups and listening for `agent_settled`.

- Supervisor session: `supervisor`
- Coordinator session: `coordinator`
- Pipeline Manager session: `pipeline-manager`
- Worker sessions: `worker-<slug>` (one per feature/task), optionally forked from a parent to re-engage prior dev work.

Sessions must be resumable: an agent should be restartable from its session log. Prior work should be forkable/resumable so a worker can be re-engaged from its original development session.

## Persistence

- **Storage: a flat JSON file.** The code MUST follow a **Repository pattern** so the underlying storage can be swapped later (e.g. for a real database). Repositories are the only layer that touch storage.
- What is stored:
  - Full **Task objects** (tickets), grouped into **Milestones**.
  - **Merge queue build output** (tracked per task).
  - **Agent session logs** (retained so sessions can be restarted).
  - Aggregate data for queries: ticket status, dependencies, build results — used for rendering, display, and analysis (e.g. "which tickets come next").

## Task Model

- Tasks are called **tickets**.
- Tickets are **grouped into milestones**.
- Tickets form a **directed graph of dependencies** (built iteratively as the Supervisor and Coordinator agents work). A task may depend on other tasks.
- Milestones are ordered groupings of tasks.
- The graph is NOT fully known up front — it is constructed and refined incrementally over time by the Supervisor + Coordinator.

## Notifications & Scheduling

- Preferred notification mechanism: **Pi extensions/plugins** if they serve the cross-process need.
- Fallback: **tmux sessions** with manual text injection and reading data from sessions.
- In practice, cross-layer notification between separate Pi processes is handled by the **FastAPI backend** acting as the nervous system: an in-process **event bus** (pub/sub) delivers notifications (build failure, build slow, agent settled, etc.). Build failures and slow builds are detected and published to this bus.
- **Scheduled periodic jobs** (e.g. the Pipeline Manager's build-time watchdog) are handled by the backend scheduler (not natively by Pi — Pi has no built-in timer). A job or notification mechanism can serve the same purpose.

## Tech Stack

- **Backend**: Python + FastAPI.
- **Frontend**: TypeScript + React.
- **Frontend graph**: A directed-graph visualization of milestones → tasks → dependencies (spec'd iteratively). Recommended: React Flow or similar.
- **AI harness**: Pi (all four layers are Pi sessions).

## Orchestration Responsibilities

The FastAPI backend is the "nervous system":
- **Persistence** via the Repository pattern (JSON-backed, swappable).
- **Session lifecycle**: start, drive (RPC prompt/steer/follow_up), resume, and shut down each layer's Pi session.
- **Event bus**: publish/subscribe notifications so the Pipeline Manager reacts to build failures / slow builds, and the Supervisor reacts to system-state changes.
- **Scheduled jobs**: periodic tasks like the build-time watchdog.
- **API surface**: serves the frontend (REST + WebSocket for live state).

## Pi Harness Constraints (confirmed via docs)

These are hard facts about the Pi harness that shape implementation:

- **No MCP support** anywhere. Custom tools must use `pi.registerTool()` (extensions) or `customTools` (SDK). Do not design around MCP servers.
- **No inbound HTTP/webhook**. Notifications *into* a Pi session come only via the RPC control channel (`prompt`/`steer`/`follow_up`) or the file-watch injection pattern (`fs.watch` a trigger file → `pi.sendMessage(..., {triggerTurn:true})`, see `examples/extensions/file-trigger.ts`).
- **No native scheduler/cron**. Periodic jobs must be layered externally (the FastAPI backend scheduler). An extension *can* start `setInterval` from a `session_start` handler but there is no built-in job system.
- **Session history is externally readable** via RPC `get_entries` (has a `since` cursor — entry id as durable cursor, works across client restarts), `get_messages`, `get_tree`, `get_last_assistant_text`. The raw JSONL file can also be parsed directly.
- **External text injection into a running session** is well-supported via RPC `prompt`/`steer`/`follow_up` (with `streamingBehavior: "steer"` / `"followUp"`), or the file-watch pattern.
- **Agents have full tool access** (read, bash, edit, write, grep, find, ls, powershell) and can be spawned as separate `pi --mode json --no-session` child processes (see the `subagent` extension example) — this is the existing pattern for one agent spawning another.
- Extensions run with the host process's OS permissions; load only trusted sources.
- `agent_settled` event marks end of automatic work for a run (the completion signal we will use).

## Design Principles

- The task/dependency graph is spec'd **iteratively**, not all at once.
- Keep the layering strict: never let the frontend or user bypass the Supervisor to reach lower layers.
- Storage is an implementation detail hidden behind repositories — never let business logic touch raw JSON directly.
- Every agent action that mutates the task graph / milestone / build state must be persisted through a repository so the frontend and other agents see consistent state.
