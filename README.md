# Orchestra

A multi-layer, AI-driven software development workflow orchestrator. Orchestra
coordinates AI agents that plan and build software. The user interacts with
exactly one layer; everything below is managed programmatically.

See [`AGENTS.md`](./AGENTS.md) for the fixed project invariants — read it first.
See [`PLAN.md`](./PLAN.md) for the phased implementation plan.

## Architecture

```
        ┌─────────────────────────┐
        │      HUMAN USER         │   user talks ONLY to the Supervisor
        └────────────┬────────────┘
                     │
        ┌───────────────────────────────────────────────────┐
        │                  FASTAPI BACKEND                    │
        │  (nervous system: persistence, event bus,         │
        │   session lifecycle, scheduling, API)             │
        │                                                     │
        │   ┌────────────── Repository pattern (JSON) ─────┐ │
        │   │ Task · Milestone · BuildOutput · SessionLog   │ │
        │   └───────────────────────────────────────────────┘ │
        │                                                     │
        │   ┌────────── PiAgentRunner (RPC subprocess) ─────┐ │
        │   │ Drives the four AI agent layers as persistent  │ │
        │   │ Pi sessions over the Pi RPC protocol.          │ │
        │   └───────────────────────────────────────────────┘ │
        └──────────────────────────┬──────────────────────────┘
                                     │
        ┌────────────────────────────▼──────────────────────────┐
        │ SUPERVISOR (Pi) — talks to the human                   │
        ├──────────────────┬────────────────────────────────────┤
        │ COORDINATOR (Pi) │  PIPELINE MGR (Pi)                  │
        │ (task graph)     │  (merge queue, build fixes)         │
        └──────────────────┬────────────────────────────────────┘
                          │ spawns worker sessions
        ┌─────────────────▼───────────────────┐
        │   WORKER (Pi) x N — implement tasks  │
        └──────────────────────────────────────┘
```

The four layers are **separate persistent Pi agent sessions**, driven over the
Pi RPC protocol by the FastAPI backend, which is the "nervous system"
(persistence, session lifecycle, event bus, scheduling, API).

## Backend layout

```
backend/
  shared/              # Used by both processes — models + repositories
    models.py          # Task / Milestone / BuildOutput / SessionLog
    repositories/      # Repository pattern with a flat-JSON implementation
  orchestrator/        # READ-WRITE process — owns state, drives agents
    orchestrator.py    # Orchestration logic + session lifecycle
  web/                 # READ-ONLY process — serves the web viewer
    server.py          # FastAPI server + cloudflared tunnel
    static/index.html  # Frontend UI
  tests/               # End-to-end tests
```

## Running

```bash
# Run the orchestrator demo (creates a task graph + dispatches a request)
cd backend
PYTHONPATH=. python3 orchestrator/orchestrator.py demo

# Start the read-only web viewer (spins up a cloudflared tunnel)
cd backend
WEB_PORT=8000 python3 web/server.py
```

Then open the printed cloudflared URL (or `http://127.0.0.1:8000`).

## Testing

```bash
cd backend
PYTHONPATH=. python3 -m pytest shared/tests tests -v
```

The test suite covers:
- Repository CRUD and dependency filtering (`shared/tests/`)
- Flat-file persistence round-trip (`shared/tests/test_persistence.py`)
- End-to-end orchestration flow + web-server read (`tests/test_end_to_end.py`)

## Notes

- **Web server is read-only.** All state mutations go through the orchestrator
  process. The web server reads whatever the orchestrator has persisted, so it
  can update the viewer frequently without contention.
- **The orchestrator is a separate process.** This keeps the web server
  read-only and lets the two scales independently.
- **Cloudflared tunnel.** The web server starts a `cloudflared` tunnel on
  startup if one is not already running, and exposes the public URL at
  `/api/tunnel`.
- **Storage is swappable.** The Repository pattern hides the flat JSON file
  behind a clean interface; swap in a database later without touching business
  logic.
