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

### Live demo

- Orchestra can orchestrate its own development: it can plan and build features
  on the Orchestra repository itself (self-orchestration).

## Testing

```bash
cd backend
PYTHONPATH=. python3 -m pytest shared/tests tests -v
```

The test suite covers:
- Repository CRUD and dependency filtering (`shared/tests/`)
- Flat-file persistence round-trip (`shared/tests/test_persistence.py`)
- End-to-end orchestration flow + web-server read (`tests/test_end_to_end.py`)

### Merge gate

- The **merge gate** (`MergeGateEngine`) keeps candidate worktree branches safe to merge by **bisecting** them: it isolates which branches fail the test suite and separates the offenders from the safe work.
- Each candidate branch is tested in isolation; the failing subset is bisected (halved) repeatedly until a single offender is pinpointed, while the passing halves are verified mergeable.
- Offending branches are **dropped** and the gate recovers by re-running on the remaining branches, so a bad commit never blocks a safe merge.
- It runs **off by default**; set `ORCHESTRA_RUN_GATE=1` to gate the branches worked on in a run (the `orchestra gate` subcommand is the manual, always-tested path).

## Notes

- **Web server is read-only.** All state mutations go through the orchestrator
  process. The web server reads whatever the orchestrator has persisted, so it
  can update the viewer frequently without contention.
- **The orchestrator is a separate process.** This keeps the web server
  read-only and lets the two scales independently.
- **Cloudflared tunnel.** The web server runs an authenticated **named
  cloudflared tunnel** (`orchestra`, tied to the `cloudflared login` and the
  `dansproject.space` zone) instead of an ephemeral quick tunnel. This avoids
  the per-IP rate limit that quick tunnels hit under repeated use. The tunnel
  config is (re)written to `~/.cloudflared/orchestra.yaml` on startup with the
  current web port, the public URL is `https://orchestra.dansproject.space`,
  and it is exposed at `/api/tunnel`. A restart **reuses** the already-running
  tunnel when it is healthy, and only relaunches cloudflared when the public
  URL is unreachable while the local app is healthy (so a broken web app never
  triggers a needless tunnel restart). The tunnel DNS record must be valid in
  the Cloudflare zone for the public URL to resolve.
- **Storage is swappable.** The Repository pattern hides the flat JSON file
  behind a clean interface; swap in a database later without touching business
  logic.
