# Implementation Plan — Orchestra

A multi-layer, AI-driven software development workflow orchestrator. Four AI agent
layers (Worker, Coordinator, Pipeline Manager, Supervisor) run on the Pi harness and are
driven by a FastAPI backend. A React/TypeScript frontend visualizes the milestone→task
dependency graph and lets the human talk to the Supervisor.

> See `.pi/invariants.md` for the fixed rules and design decisions. Read it first.

---

## Architecture Summary

```
        ┌─────────────────────────┐
        │      HUMAN USER         │   user talks ONLY to the Supervisor
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │      SUPERVISOR (Pi)    │   requirements ↔ system state
        └────────────┬────────────┘
                     │  (via backend event bus + RPC)
        ┌────────────┼────────────┐
        │            │            │
  ┌─────▼─────┐ ┌─────▼──────────┐
  │COORDINATOR│ │  PIPELINE MGR  │  spawn/engage workers, watch merge queue
  │   (Pi)    │ │    (Pi)        │
  └─────┬─────┘ └─────┬──────────┘
        │             │
        └──────┬──────┘   spawn worker sessions
     ┌─────────▼─────────┐
     │   WORKER (Pi) x N │   implement features
     └───────────────────┘
```

The four layers are **separate persistent Pi agent sessions**, driven over the Pi RPC
protocol by the FastAPI backend, which is the "nervous system" (persistence, session
lifecycle, event bus, scheduling, API).

---

## Design Decisions (confirmed)

1. **Agents as Pi sessions** — each layer is a named, resumable Pi JSONL session driven via RPC, not an in-process object.
2. **Notifications via in-process event bus** in the backend (language-agnostic, handles cross-process + scheduling). Pi extension handlers are considered only if they cleanly serve an intra-session need.
3. **Scheduling via backend** (APScheduler) for periodic jobs like the build-time watchdog.
4. **Frontend graph via React Flow** for directed milestone→task→dependency visualization.
5. **JSON flat-file storage behind a Repository pattern**, so the store can be swapped later.

---

## Phase 1 — Foundations (persistence + backend API)

Goal: a working FastAPI backend with swappable JSON storage and a REST API for tasks/milestones.

Files:
```
orchestra/
  backend/
    app/
      __init__.py
      main.py                 # FastAPI app, mounts API routers
      config.py               # paths (data dir, sessions dir, model config)
      models/
        __init__.py
        task.py                # Task / Ticket model (id, title, description,
                               #   status, dependencies[], milestoneId, priority, ...
      repositories/
        __init__.py
        base.py                # Repository ABC (find, find_all, save, delete, query)
        json_store.py          # low-level read/write of a JSON file (atomic)
        task_repository.py     # Task <-> JSON
        milestone_repository.py# Milestone <-> JSON
        build_output_repository.py
        session_log_repository.py
      schemas/
        task.py                # Pydantic request/response schemas
      api/
        __init__.py
        tasks.py               # CRUD + list by milestone/status
        milestones.py          # CRUD + list tasks within a milestone
    tests/
      test_task_repository.py
      test_api_tasks.py
  data/                        # runtime JSON store (gitignored)
```

Key points:
- `base.Repository` defines `find`, `find_all`, `save`, `delete`, and a `query(**filters)` method.
- `json_store.JsonStore` writes one JSON document per collection atomically (write temp + rename).
- Task model includes: `id`, `title`, `description`, `status` (backlog/in-progress/done/blocked/failed), `dependencyIds[]`, `milestoneId`, `priority`, `assigneeSessionId` (worker session), `createdAt`, `updatedAt`.
- Milestone model: `id`, `name`, `order`, `taskIds[]` or reference from Task.milestoneId.

Acceptance: unit tests pass for repository CRUD + dependency filtering; REST endpoints return correct task graphs.

---

## Phase 2 — Frontend graph visualization

Goal: React/TypeScript app showing the milestone→task dependency graph + a state panel.

Files:
```
  frontend/
    package.json
    index.html
    vite.config.ts
    src/
      main.tsx
      api/client.ts            # fetch wrapper to FastAPI
      components/
        TaskGraph.tsx          # React Flow graph: nodes = tasks/milestones, edges = deps
        MilestoneLane.tsx      # optional lane per milestone
        TaskNode.tsx           # node rendering by status
        TaskPanel.tsx          # detail pane for selected task
      types.ts
```

Key points:
- React Flow for the directed graph. Milestones as groups/lanes; tasks as nodes; edges = dependencies.
- Color/label nodes by status.
- Read "what's next" aggregation from a backend endpoint (e.g. tasks whose dependencies are all done, sorted by priority).

Acceptance: graph loads from live backend data; adding a task/milestone updates the graph.

---

## Phase 3 — Pi session orchestration

Goal: drive the four agent layers as real Pi sessions over RPC.

Files:
```
  backend/app/
    pi/
      __init__.py
      rpc_client.py            # wrapper around `pi --mode rpc --session <file>`:
                               #   prompt, steer, follow_up, wait_idle, get_messages,
                               #   get_entries, set_session_name, dispose
      agent_session.py         # lifecycle for one layer:
                               #   start/resume/drive/wait/shutdown; attach system prompt
      agents.py                # high-level facade: Supervisor, Coordinator,
                               #   PipelineManager, Worker — each owns an AgentSession
      events.py                # in-process event bus (pub/sub)
      config.yaml (or .env)    # model/provider, pi binary path, session dir
```

Key points:
- Each layer gets a named session file under the sessions dir; `set_session_name` for readability.
- The orchestrator injects each agent's role/system-prompt via a prompt template (`.pi/agent/prompts/<role>.md`).
- The event bus delivers notifications (see Phase 4).
- Worker sessions may be forked from a parent session to re-engage prior dev work.

Acceptance: backend can start the Supervisor session, send it a prompt, and receive a structured response.

---

## Phase 4 — Pipeline manager + notifications

Goal: build-output tracking, build-failure/slow-build notifications, watchdog job.

Files:
```
  backend/app/
    build/
      build_service.py         # records merge-queue build output per task,
                               #   computes build status, detects failures/slow builds
    jobs/
      watchdog.py              # APScheduler job: flags tasks whose build time
                               #   exceeds average → publish build_slow event
    events/topics.py           # named event types: BUILD_FAILURE, BUILD_SLOW,
                               #   AGENT_SETTLED, TASK_STATUS_CHANGED, ...
```

Key points:
- `BuildOutput` stored via `build_output_repository` (taskId, startedAt, finishedAt, status, logs, duration).
- Pipeline Manager agent is notified via the event bus and reacts by spawning/re-engaging worker sessions.
- "Longer-than-average build time" computed from historical durations for a task/type.

Acceptance: a recorded slow build publishes `build_slow`; the pipeline manager session is driven to act.

---

## Phase 5 — Cooperative task-graph construction + state sync

Goal: Supervisor + Coordinator iteratively build the dependency graph; frontend shows live state.

Files:
```
  backend/app/
    orchestration/
      supervisor_flow.py       # translates user reqs → messages to Coordinator/PipelineMgr
      coordinator_flow.py      # turns reqs → task graph (tasks, deps, milestones, priorities)
      graph_aggregation.py     # "what's next", per-milestone rollups, analysis queries
  backend/app/api/
    graph.py                   # full graph payload (milestones, tasks, edges)
    websocket.py               # live state pushes (event bus → frontend)
  frontend/components/
    SupervisorChat.tsx         # human ↔ supervisor chat
    MilestoneDashboard.tsx     # aggregate views
```

Key points:
- Supervisor/Coordinator mutations to the graph go through repositories so the frontend and other agents see consistent state.
- WebSocket pushes surface agent_settled / task_status_changed events in real time.

Acceptance: the human can describe a feature; the Supervisor + Coordinator materialize tasks + dependencies in the graph, visible in the frontend.

---

## Ordering & Rationale

Start at **Phase 1** — everything depends on a stable, tested storage + API layer.
Phase 2 in parallel with Phase 1 (different language, same data contract).
Phase 3 is the crux: it turns the design into *real* Pi agents.
Phases 4–5 add the pipeline intelligence and the cooperative graph.

## First Build (this session)

Begin with **Phase 1**: scaffold `backend/app`, implement the Repository pattern with a
JSON store, define the Task/Milestone models, add FastAPI routers, and write unit tests
for repository CRUD and dependency filtering plus the task REST endpoints.
