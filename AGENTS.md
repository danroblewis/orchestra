# Rules for working on Orchestra

Read `SPEC.md` first. It is the design. This file is the short list of rules
that must not be broken without updating the spec and saying so in the commit.

## Invariants

These replaced the old task system's invariants on 2026-10-25, when the ticket
tracker, loop and merge gate were removed (`docs/proposals/empty-orchestra.md`).

1. **Orchestra knows no tickets and no tasks.** It has an event bus, a metrics
   store, a system dynamics model, a bootstrap host and drivers. What machines
   do and what their events mean is theirs. Never add a domain concept (ticket,
   task, build) to the core.
2. **Machines are outside Orchestra, and known only by observation.** A
   machine is its CloudEvents `source` (`<machine>/<instance>` for one of
   several instances), the events it publishes and listens for, how it says it
   is engaged (continuous, scheduled, ad hoc), and the series it writes. The Machines page, the collectors and the
   model read what is observed, never a machine's description of itself.
3. **Every event carries the CloudEvents envelope.** `orchestra.events`
   writes it; Orchestra reads the envelope and never the `data` payload, which
   belongs to the machines that use it.
4. **There is one system and one model.** Never split topics, models or views
   per package or per domain. Packages and metadata label; they never
   separate. The model changes by new versions; past versions stay readable.
5. **State lives in `~/.orchestrator/<key>/`, except the event log and the
   metrics, which live in the configured bus and metrics store.** Events go
   through `orchestra.events.Events` over an `orchestra.bus.EventBus`; metrics
   through `orchestra.metrics.MetricsStore`; the model through
   `orchestra.sd.store.ModelStore`; process records through
   `orchestra.runtime`. Nothing else touches a backend or those files
   directly. Orchestra's streams are named `orchestra.<key>.events` and never
   share a topic with anyone else's.
6. **Every equation records its origin** (fitted, discovered, or declared).
   A declared equation is an assumption until it is fitted. A machine's
   attribution to a flow is a hypothesis.
7. **Stocks are discovered, not configured.** Collectors expose plain series
   named for what they measure; the model generator decides what is a stock or
   a flow. Manual bindings are the exception.
8. **The core stays up.** `web/core.py` and `web/core_explore.py` import only
   the bus, the metrics store and the runtime record, and probe each under a
   time limit, so the Core page works when the model or every machine is
   broken.
9. **Humans talk only to the Supervisor.** The web UI and CLI are read-only
   for humans, except for observations: rediscovering the model (the Dynamics
   page's button, `orchestra sd discover`) re-reads the metrics and may save a
   model version, and changes no machine. The Supervisor is being rebuilt;
   until it returns, there is no human path that changes the system.
10. **The harness's session file is the only transcript.** Do not write a
    parallel log of agent messages; `orchestra.harness.read_transcript` parses
    whichever harness wrote it.
11. **One package, no path hacks.** Everything importable is under
    `orchestra/`. No `sys.path` manipulation. `orchestra/sdlab` is SD Lab's
    discovery research brought in as it was benchmarked (imports rewritten,
    nothing else; see its README): change it only deliberately, say so in the
    commit, and keep it out of lint. Machines and test systems live in
    their own repositories (the bakery: `~/orchestra-bakery`) and use Orchestra
    as a library, like any other program would; nothing in this repository is
    an example system.

## Harness rules

- **Nothing outside `orchestra/harness/` knows which product runs an agent.**
  The loop, CLI, web app, and store use `AgentSession`, normalized events,
  and `read_transcript`. A harness-specific branch anywhere else is a bug.
- **Orchestra's tools are defined once**, in `orchestra/harness/tools.py`.
  The Pi extension and the MCP server both read that catalogue; never add a
  tool to one harness only.
- **Every harness has a fake** in `tests/e2e/` that speaks its real protocol.

## Harness facts the code depends on

- Pi: no MCP, no inbound HTTP, no scheduler; tools via the extension. `pi
  --mode rpc` reads one JSON command per line on stdin and writes events on
  stdout; `agent_settled` is the completion signal; `message_end` with
  `role: assistant` is the final message. Sessions are JSONL files placed by
  `--session-dir`/`--session-id`. Docs:
  `~/.pi/agent/install/releases/<version>/node_modules/@earendil-works/pi-coding-agent/docs/`.
- Claude Code: `claude -p` is one turn per process; `--output-format
  stream-json` gives `system/init`, `stream_event`, `assistant`, `user`
  (tool results), `result`. `--session-id` names a new session,
  `--resume <uuid>` continues it from the same cwd. Transcripts live under
  `$CLAUDE_CONFIG_DIR` (default `~/.claude`) at `projects/<cwd with / as
  ->/<uuid>.jsonl`. Tools come from MCP servers in `--mcp-config`; MCP
  tools are deferred behind `ToolSearch`, which the model calls itself.
- Codex: `codex exec --json` is one turn per process; the prompt is `-` on
  stdin (a positional prompt with an open stdin hangs on "Reading additional
  input from stdin"). Events: `thread.started` (carries the thread id),
  `turn.started`, `item.started`/`item.completed` (whole items, no token
  stream), `turn.completed`, `turn.failed`, `error`. Global flags go before
  `resume <thread_id>`. Config comes from `-c key=<TOML value>`; MCP servers
  are `mcp_servers.<name>={command, args, env, required}`; the role prompt
  is `developer_instructions`. Rollouts live under `$CODEX_HOME/sessions/`
  (`response_item` lines hold the messages and function calls, `event_msg`
  `McpToolCall` items hold MCP calls). MCP tools reach the model as a
  `namespace` tool, which only OpenAI's own API understands.

## Conventions

- Python 3.12+, `uv` for everything, `pytest` for tests (run with `uv run
  python -m pytest`), `ruff` for lint and format.
- `tests/unit` is fast and pure. `tests/bus` and `tests/metrics` are
  conformance suites run against every backend (the server ones opt in by
  environment variable; see `tests/bus/README.md`). `tests/e2e` holds the
  harness fakes. `tests/acceptance` runs against an empty Orchestra started by
  `scripts/acceptance_target.py` and skips unless `ORCHESTRA_TARGET_URL` is
  set.
- Keep modules small and single-purpose. If a file needs a section divider
  comment, it should be two files.
