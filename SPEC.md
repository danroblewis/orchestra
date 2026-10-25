# Orchestra Specification

Orchestra observes a system of **machines** and keeps a **system dynamics model** of it. A
machine is anything outside Orchestra that does something: a program, an AI agent, a service, a
team of people. Machines talk over Orchestra's **event bus** and write measurements to its
**metrics store**. From those measurements Orchestra builds and fits one model of the whole
system: stocks, flows, and the feedback loops between them, with each flow attributed to the
machines believed to cause it.

Its main use case is finding the feedback loops between a project's own domain and the processes
used to develop it: do our workflows and AI agents change the measures the project exists for?

This version is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host,
the agent driver and the web UI, with no machines of its own beyond the host. Task management, the
first package of machines, is being rebuilt on top of it (`docs/proposals/empty-orchestra.md`).
The old ticket tracker, loop and merge gate were removed on 2026-10-25; their history stays on the
bus and in model versions 1–4 of projects that used them.

This document is the design of what exists. `AGENTS.md` lists the rules that must not be broken;
`docs/proposals/` holds what is proposed and not yet built.

---

## 1. Principles

1. **System dynamics first.** Everything Orchestra does serves the model: what is measured, how
   stocks and flows relate, and which machines change them.
2. **Machines are outside Orchestra.** Orchestra can't guarantee what a machine does; it knows a
   machine only by what it observes: events on the bus and series in the metrics store.
3. **There is one system and one model.** Development and domain sit side by side. Large models
   are sliced for viewing with metadata, filters and graph algorithms, never split.
4. **Flows are observed, not proclaimed.** Equations are fitted or discovered from the measured
   history, and every equation records its origin. A machine's intended effect is a hypothesis.
5. **Stocks are discovered, not configured.** Collectors expose plain series; the model generator
   relates them.
6. **The core stays up.** The bus, the metrics store and the host are probed on their own, so the
   Core page works when the model or every machine is broken.

---

## 2. Machines and events

A **machine** is identified by the CloudEvents `source` it publishes under. It may publish to the
bus, listen to it, write metrics, all of these, or none (a machine that only changes measures
others write is still a machine). Orchestra's own machine is the **bootstrap host**,
`orchestra-host` (section 5).

Every event carries the **CloudEvents 1.0** envelope (`orchestra.events.envelope`):

| Field | What it is |
|---|---|
| `specversion` | `1.0` |
| `id` | Unique |
| `type` | e.g. `bread.baked`; Orchestra's own start with `orchestra.` |
| `source` | The machine that emitted it |
| `time` | RFC 3339, milliseconds |
| `subject` | Optional: what the event is about |
| `correlationid`, `causationid` | Optional extensions: the request it belongs to, the event that caused it |
| `data` | The payload. It belongs to the machines that use it; Orchestra never reads it |

Events written before the envelope (flat records with `ts`) stay readable; `event_time` and
`event_source` read either shape.

**Subscriptions.** Until the bus adapters provide subscriptions with leases
(`docs/proposals/empty-orchestra.md` §3), a machine reads the bus by offset and announces what it
listens for with an `orchestra.machine.subscribed` event (`data.types`). The Machines page draws
the graph of publishers, event types and listeners from what it observes.

---

## 3. The event bus

An append-only, replayable, ordered log per project (`orchestra/bus/`), behind the `EventBus`
interface: `append`, `read(since, limit)` → (events, end offset), `end`, `close`. Offsets are
integers counting events. The stream is named `orchestra.<project key>.events` and never shares a
topic with anyone else's.

| `[events] url` | Backend |
|---|---|
| `file` (default) | A JSONL file in the state directory |
| `redis://host:port/db` | Redis Streams (Lua-assigned integer offsets) |
| `amqp://user:pass@host:port/` | A RabbitMQ stream queue |
| `kafka://host:port` | One Kafka topic with one partition |

`ORCHESTRA_EVENTS_URL` overrides the file. One conformance suite (`tests/bus/`) runs against every
backend; server backends need their client library (`orchestra[bus-redis]`, `[bus-rabbitmq]`,
`[bus-kafka]`). `orchestra events copy --to URL` moves a log between backends.

---

## 4. Metrics, collectors and the model

### 4.1 The metrics store

Measured series (`orchestra/metrics/`): name plus labels, like Prometheus, each carrying a
`project` label. A JSONL file by default, or VictoriaMetrics (`[metrics] url =
"http://host:port"`, or `ORCHESTRA_METRICS_URL`). The interface: `write`, `raw`, `range`,
`latest`, `series`, `dump`, `delete`. A range carries the last value forward at each step. Machines
write their own series, labelled `machine=<id>` so they can be attributed. Names say what is
measured (`bakery_shelf_loaves`, `orchestra_events_total`); whether a series is a stock or a flow
is the model's business.

Queries are PromQL: VictoriaMetrics answers them itself (scoped with `extra_label=project=<key>`);
the file store uses `orchestra/metrics/promql.py`, a tested subset.

### 4.2 Collectors

Orchestra's own collector (`orchestra/collectors.py`) counts every event on the bus by type and
source: `orchestra_events_total{type, source}`. The host runs it live (section 5); `orchestra
metrics backfill` replays the whole log. Only the last value of a series at an instant is written,
because stores disagree on the order of points that share one.

### 4.3 The model

`orchestra/sd/`: stocks (each bound to a series), flows (each bound to a counter), equations
(each with its **origin**: `fitted`, `discovered` or `declared`, and its quality), machines
attributed to flows, and eras. There is **one model** per project; every change is saved as a new
version (`<state>/model/vNNNN.json`), the highest is current, and past versions stay readable.

**Fitting** (`sd/fit.py`): each flow's count per step is Poisson with mean `c × time`
(constant) or `k × the source stock's level × time` (proportional, the exact integral of the
level), fitted by maximum likelihood; the form with the higher likelihood is kept, with its
standard error and dispersion.

**Discovery** (`sd/discover.py`, `orchestra sd discover --minutes N`) builds the model from the
metrics store without being told what anything is:
1. every series is sampled onto a grid of steps;
2. a level is a **stock** when counters, added or subtracted, balance its changes
   (`Δlevel ≈ Σ inflows − Σ outflows`, R² ≥ 0.9). The counters are found by least squares on all
   counters, rounded to ±1, then a local search (change one coefficient, or swap one counter for
   another) with a penalty per counter;
3. a counter that leaves one stock and enters another is a **flow** between them; otherwise it
   comes from or goes to outside;
4. each flow's rate is fitted by maximum likelihood, choosing by AIC among constant, proportional
   to its source, and linear in any stock (`c + k × X`). A linear form on a stock other than the
   flow's source is an **influence**, the link that closes feedback loops. Forms are scored with
   the exact point-process likelihood (each event against the levels just before it), because
   counts per step favour spurious forms when a flow drains the level it depends on;
5. each flow is attributed to the machine named by its counter's `machine` (or, for event
   counters, `source`) label.

Everything else is **left out, with the reason** (did not change, no counters balance it, not
needed by any balance), recorded in the model version. Not yet: stocks no series measures,
delays, non-linear forms, eras. The bakery (`~/orchestra-bakery`, its own repository) is a toy
system it is tested on.

---

## 5. The bootstrap host

`orchestra run` starts Orchestra's own machine (`orchestra/host.py`). In an empty Orchestra it:
- registers itself in `<state>/runtime.json` and logs to `<state>/logs/orchestra-host.log`;
- publishes `orchestra.host.started` and `orchestra.host.stopped`;
- writes `orchestra_host_up{machine="orchestra-host"}` every interval;
- runs the event collector: replays the bus once at start, then follows it.

Hosting drivers and starting the machines that packages declare come later.

---

## 6. Agent harnesses (the agent driver)

Orchestra does not run models; a *harness* does. A harness is the product that turns a prompt
into an agent turn with tools: Pi, Claude Code, Codex. Orchestra talks to every harness through
one small interface (`orchestra/harness/base.py`) and knows nothing else about it:

- `Harness.start(spec)` opens a named, resumable session with a system prompt, a working
  directory, a model, and a set of Orchestra tool groups.
- `AgentSession.prompt(text, timeout, on_event)` runs one turn to completion and returns the
  final text. Events arrive in a **normalized vocabulary** (`turn_start`, `assistant_start`,
  `token`, `tool_start`, `tool_end`, `assistant_end`, `settled`).
- `AgentSession.session_file` is the harness's own transcript, the only one kept;
  `read_transcript` parses it into a common message list.
- `kill()` stops a turn; `close()` releases the session.

The project picks its harness in `orchestra.toml` (`[agents] harness = "pi" | "claude_code" |
"codex"`), with `model` in that harness's terms and `provider` for Pi only.

### 6.1 Orchestra's tools are data

Tools an agent uses to talk to Orchestra are defined once, as JSON-schema records in
`orchestra/harness/tools.py`, grouped by tool group. The catalogue is empty in an empty
Orchestra; the Supervisor's tools come back here. `orchestra tools --json` prints it.

### 6.2 Pi

One `pi --mode rpc` process per live session; the process is the session and stays resident
between turns. Launched with `--session-dir <state>/sessions --session-id <id> --provider <p>
--model <m> --append-system-prompt <role> --extension <orchestra/harness/pi_extension.ts>`. The
extension fetches the tool catalogue from `orchestra tools --json` at load and registers each
tool. One JSON command per line on stdin, events on stdout; `agent_settled` ends a turn; on
timeout Orchestra sends `abort`. Transcript: Pi's own JSONL session file.

### 6.3 Claude Code

No resident process: each turn is `claude -p` with the prompt on stdin, `--output-format
stream-json --include-partial-messages`, `--append-system-prompt-file <role>`, `--model <m>`,
`--dangerously-skip-permissions`, and `--mcp-config <per-session file> --strict-mcp-config`
pointing at Orchestra's MCP server (`python -m orchestra.harness.mcp`), which serves the tool
catalogue. The first turn passes `--session-id <uuid>`; later turns `--resume <uuid>`.
Transcript: Claude Code's own JSONL under its config directory (`projects/<cwd>/<uuid>.jsonl`).

### 6.4 Codex

No resident process: each turn is `codex exec --json` with the prompt on stdin (`-`), `--sandbox
danger-full-access -C <cwd> --skip-git-repo-check`, `-m <model>`, and `-c` overrides:
`mcp_servers.orchestra={...}` (the same MCP server, `required=true`) and
`developer_instructions="<role prompt>"`. Later turns are `codex exec ... resume <thread_id> -`.
Transcript: Codex's rollout under `$CODEX_HOME/sessions/`. Codex streams whole items, not tokens.
It presents MCP tools as a Responses API `namespace` tool, which only OpenAI's own API
understands.

### 6.5 Keeping context bounded

A session whose transcript has grown past `session_max_bytes` since it was last compacted is
compacted before its next turn: Pi summarises through its `compact` command; Claude Code is
started with `--autocompact` at `compact_tokens`; Codex sessions are rotated.

### 6.6 Adding a harness

Implement `Harness` and `AgentSession`, register the class in `orchestra/harness/__init__.py`,
and give the e2e suite a fake binary that speaks the harness's protocol (`tests/e2e/fake_pi.py`,
`fake_claude.py`, `fake_codex.py`).

---

## 7. Storage

```
~/.orchestrator/                 (ORCHESTRATOR_HOME overrides)
  projects.json                  repository root → project key
  <key>/
    project.json
    runtime.json                 the host's and the web server's process records
    events.jsonl                 the event log, when [events] url = "file"
    metrics.jsonl                the metrics, when [metrics] url = "file"
    model/vNNNN.json             the model's versions
    sessions/                    harness session files
    logs/orchestra-host.log
```

The project key is the repository directory's name plus a hash of its path. Nothing is written
inside the repository except `orchestra.toml`.

---

## 8. Configuration

`orchestra.toml` at the repository root (`orchestra init` writes a starter):

```toml
[events]
url = "file"            # or redis://, amqp://, kafka://
[metrics]
url = "file"            # or http://host:8428 (VictoriaMetrics)
[agents]                # the agent driver
harness = "pi"
provider = ""
model = ""
```

Unknown sections are ignored, so files written for older versions still load.

---

## 9. CLI

| Command | What it does |
|---|---|
| `orchestra init` | Register the repository and write `orchestra.toml` |
| `orchestra run` | Run the bootstrap host |
| `orchestra web [--port]` | Serve the web UI |
| `orchestra events info\|copy --to URL` | The event log |
| `orchestra metrics backfill\|series` | Replay the log into event counters; list series |
| `orchestra sd discover\|show\|fit\|versions` | The model: discover it from the metrics, show, refit, list versions |
| `orchestra tools [--json]` | The agent tool catalogue |

---

## 10. Web UI

Read-only for humans. Navigation: Dashboard, Machines, Dynamics, Core.

- **Dashboard:** the machines active on the bus; the host's CPU, GPU, memory and disk; a Core
  status strip.
- **Machines:** every machine seen on the bus, the event map (machines and the event types they
  publish and listen for), its feedback loops, and each machine's metrics.
- **Dynamics:** the model as a stock-and-flow network (stocks with their level, tank fill and
  sparkline; a valve per flow with its equation and machine; influences as dashed +/− links),
  its feedback loops marked balancing or reinforcing, the stocks' history, and drawers with each
  stock's and flow's history (a flow's observed rate against its equation's prediction). It shows
  the host's latest discovery and steps through saved versions.

Both graphs are drawn by one renderer (`static/netgraph.js`, a d3 force layout). Loops are
elementary cycles; clicking one highlights it. Pages read only the web server's background caches
(`web/background.py`) and the host's cached discovery, never the stores on request.
- **Core:** the host, the bus and the metrics store, each probed against its real backend within
  a time limit; explorers for the metrics (a catalogue and a PromQL editor) and the events (types,
  volumes, sources); logs. It imports only the bus, the metrics store and the runtime record.

---

## 11. Package layout

```
orchestra/
  cli.py  config.py  events.py  runtime.py  host.py  collectors.py
  bus/       file, redis_streams, rabbitmq_streams, kafka
  metrics/   file, victoria, promql
  sd/        model, store, fit, discover
  harness/   base, pi, claude_code, codex, mcp, tools, pi_extension.ts
  web/       app, core, core_explore, machines, dynamics, static/
tests/
  unit/  bus/  metrics/  e2e/ (harness fakes)  acceptance/
```
