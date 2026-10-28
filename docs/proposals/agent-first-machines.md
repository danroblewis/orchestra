# Agent-first machines: solve with an agent, decompose it, replace it with programs

Status: proposal, not built, for review. Written 2026-10-28 from the owner's thinking of the same
day. Nothing in the code or the other documents is changed by this file. It builds on the
ghost-machine path (`environment-and-ghost-machines.md` §3: observe, fit, write, shadow, swap,
verify; H3's "shadow and swap" in `docs/roadmap/README.md`), on the custom roles that exist in
orchestra-agents (`teams-and-roles.md`, Stage 1 and 2), on G10 (a pipeline-manager agent) and G15
(a self-improving worker kind), and on decisions D17–D19.

## 0. The owner's thinking (2026-10-28)

> Solve problems with AI Agent machines, decompose the AI Agent machines, then replace the AI
> Agent machines with regular programmatic machines.

- **Unblocked first, validated later.** People expect to be unblocked before software is validated
  and released. An agent can do a job the day it is described; a program cannot. Plugins are fixed
  in place, and we block on upstream only for the permanent fix.
- **The spec.** Setting up an agent machine is writing a spec for a machine: a prompt (its
  responsibilities and its loop), its tools, and its event mappings. The agent needs them, and
  they are also the spec of the program that later replaces it. The Supervisor creates and
  prepares the agent; a separate agent may take that over later.
- **Refining and decomposing stay AI work.** An agent (probably the Supervisor) reads the agent's
  logs after many runs and expands and refines the prompt, tools and events. When the spec gets
  too big, it splits it into prompt files and groups of tools and events, one per responsibility.
  Eventually the pieces are small and explicit enough to be replaced by programs.
- **Patching what cannot be edited.** Orchestra's environments are not editable installs. The
  Supervisor should be able to monkeypatch or write alternative implementations locally, and file
  issues upstream with the description and the patches it applied (a PR is possible from a
  separate scratch clone).
- **Do not replace what exists; pick something missing.** The first case is a **pipeline
  manager** that lifts retries and bisection out of the merge gate.
- **Open:** where the replacing program is written: the target repository, its own plugin, or
  upstream.

## 1. The lifecycle

```
create → run → refine ⟲ → decompose → shadow → replace → (fallback, always) → maintain
```

Each step is a change to the system, so each spec edit, decomposition and swap is announced and
begins an era (G11), and each one that is meant to change behaviour carries a prediction (G13).
A step that is meant to change nothing (a decomposition, a swap) is judged by the null test
(`docs/rationale/lifted-models.md` §3.2).

| Step | Who | Reads | Produces | Judged by |
|---|---|---|---|---|
| **Create** | The Supervisor, from the owner's request | The request; the event map (what is already on the bus); the plugins' guides; the target's `.orchestra/` | The spec (§2), committed; an agent record that runs it; `role.created` / `agent.created`; a first prediction | Spec lint (every `listens` type is seen on the bus or declared new; every `publishes` type has a shape and an example; every tool exists); a dry run on recorded events (replay of the last N matching events, publishing nothing) |
| **Run** | The agents' host, as the configured agent | The events it listens for; its tools | Its events, under its own `source`; transcripts; usage series | The responsibility's own outcome series (for the pipeline manager: reruns wasted, time to culprit); its grading suite where one exists (§5.5) |
| **Refine** | The Supervisor now; a curator agent later (G15's curator, generalised) | Transcripts of the last N runs; the runs the owner or another machine overrode; tool-sequence statistics; failed tool calls | A spec edit (prompt, a tool added, an event added or reshaped), committed with its reason; `role.changed` (an era); a prediction | The intended-effect test at the edit's horizon; the grading suite does not regress |
| **Decompose** | The Supervisor | The spec's size; which tools and events each kind of wake-up uses | The spec split into responsibilities (§2.3), each with its own prompt file, tool subset and event subset; still one agent | The null test: outcome series unchanged across the era boundary, within the measured false-change rate |
| **Shadow** | A worker writes the program through a ticket (review, gate); the Supervisor configures it | One responsibility's spec; its recorded events and the agent's decisions on them, as fixtures | A program instance `<machine>/<responsibility>` running in shadow: it reads the same events and writes its would-be decisions to its own log, publishing nothing; an instrument compares | Agreement with the agent per case kind, over at least N cases including the rare ones; disagreements read by the Supervisor |
| **Replace** | The Supervisor (a configuration change) | The shadow's agreement and cost | The program active for that responsibility; the agent woken only for what the program defers (§1.2); `config.changed` (an era) | The null test on the outcome series, the replacement check against the ghost's prediction (`environment-and-ghost-machines.md` §4.4), and cost per event down |
| **Fallback** | The program, by deferring; the agent, by handling the deferral | Cases the program's rules do not cover | `<type>.deferred` events, handled by the agent | The fallback rate, watched; a rising rate is a refine trigger for the program (new rule) or the spec (a case nobody described) |
| **Maintain** | The Supervisor | Spec against what is observed (listens and publishes); upstream releases; overrides (§4) | Spec corrections; retired overrides; a retired agent when the fallback rate stays at zero | Spec drift is zero; no override outlives the upstream fix |

### 1.1 The signals that trigger each step

Each should be a series, read by the Supervisor's `observe` and `model` tools, so a step is taken
because a number moved, not because someone remembered.

| Signal | Series (proposed) | From | Triggers |
|---|---|---|---|
| Agent cost per handled event | `agent_tokens_total{machine,kind}`, `agent_cost_dollars_total{machine}` over `orchestra_events_total{type}` the machine listens for | orchestra-agents' usage instrument (H2: not built; today only `agent_turns_*`) | Decompose or replace when cost per event is high and the work looks rule-like |
| Determinism of tool sequences | `agent_tool_sequences_distinct{machine,trigger}`, `agent_tool_sequence_top_share{machine,trigger}` (share of wake-ups whose tool-call sequence is the most common one) | A transcript instrument in orchestra-agents | A responsibility whose top share is above ~0.8 over 30 wake-ups is a loop a program can run: replace |
| Spec size | `machine_spec_tokens{machine,part}` | An instrument over `.orchestra/` | Above a budget (say 4k tokens for one prompt file): decompose |
| Disjoint usage | Tool and event co-use per trigger, from the same transcript instrument | As above | Two clusters of triggers that use disjoint tools: split there |
| Override rate | Overrides of the machine's decisions by the owner or another machine (a later `ci.verdict` contradicting an earlier one, a ticket reopened as a bug, an outbox edit) | Events, counted by `orchestra_events_total` and the outbox's own instrument | Refine |
| Shadow agreement | `shadow_decisions_total{machine,responsibility,agreement}` | The comparator instrument (§1.2) | Replace when agreement holds across case kinds |
| Fallback rate | `orchestra_events_total{type="<x>.deferred"}` over the responsibility's input events | Orchestra's count of the bus, already there | Refine the program; or move the case back to the agent |
| Spec drift | Types the machine publishes that its spec does not declare, and declared listens never seen | A lint over the event map and the spec | Maintain |

### 1.2 Shadow, replace and fallback on the bus

- **The machine stays the same machine.** A program that takes over a responsibility publishes as
  an instance of the same machine, `<machine>/<responsibility>` (`pipeline_manager/retry`),
  announcing `kind: program`. This is D17's precedent: `coordinator/dispatch` is a program
  instance of the coordinator machine beside the Coordinator agent, and the Machines page shows
  `agent ×1, program ×1`. Listeners and the event map do not change at a swap.
- **Shadow publishes nothing.** A shadow instance announces itself (`mode` as usual, plus
  `shadow: true` passed on to the package's card) and writes its would-be events to a decision
  log in the state directory (`~/.orchestrator/<key>/machines/<machine>/shadow/<responsibility>.jsonl`),
  each naming the input event it answers. A comparator, an instrument the agents plugin declares
  (`agents.shadow`), pairs them with what the agent published for the same input (by
  `causationid`) and writes `shadow_decisions_total`. It reads the machines' `data`, so it is the
  plugin's, never Orchestra's (rule 3).
- **Defer, never race.** When the program is active, it is first: it handles what its rules cover
  and, for anything else, publishes `<input-type>.deferred` (or a responsibility-specific type
  such as `ci.failure.deferred`) with the input as `causationid`. The agent's `wake_on` changes
  from the input type to the deferred type in the same configuration change. Two machines never
  answer one event.

## 2. The machine spec

### 2.1 Reconciling with what exists

orchestra-agents already has the pieces, split by what they are for (`teams-and-roles.md`,
`orchestra_agents/roles.py`, `org.py`):

| Exists | Holds | Missing for a machine spec |
|---|---|---|
| `.orchestra/roles/<name>.json` + `.md` | A job description: the prompt, tool groups, `created_by` | Responsibilities as separate files; per-tool contracts |
| `.orchestra/agents/<name>.json` | What runs: roles, team, `kind` (continuous, scheduled, ad hoc), `session`, `wake_on`, `every`, `at` | The events it publishes, with shapes |
| `.orchestra/teams/<name>.json` + `.md` | Responsibilities, access, `emits` (the custom types its agents may raise) | Per-machine rather than per-team publishes |

A new parallel tree would give two ways to define an agent. So the spec is **the existing role
plus an agent record, given a contract**: the contract is the part a program must honour, and it
lives beside the role, not inside the agents' records, because it outlives the agent.

```
.orchestra/
  machines/
    pipeline_manager/
      machine.toml          the contract: name, engagement, listens, publishes (shapes, examples), tools
      role.md               the loop and the standing responsibilities (the prompt's spine)
      responsibilities/     after decomposition: one prompt file per responsibility
        triage.md
        retry.md
        bisect.md
        flakes.md
      examples/             recorded input events and the expected output events, per case kind
      program/              when a program implements a responsibility (§3), its code or a pointer
  agents/
    pipeline_manager.json   {"machine": "pipeline_manager", "kind": "continuous", "session": "ephemeral"}
```

- **What the agents plugin reads.** An agent record may name a `machine` instead of `roles`. The
  host then builds the role from `role.md` (plus the responsibilities that are still the agent's),
  grants the tool groups `machine.toml` lists, derives `wake_on` from `listens` (minus what a
  program has taken over, plus its deferrals), and uses `publishes` as the agent's `emit_event`
  allowlist in place of a team's `emits`. Today's roles keep working unchanged: a role is a
  machine with no contract yet (Stage 1's "degenerate case" again).
- **What Orchestra reads.** Nothing. Rule 2: the Machines page and the model read what is observed,
  never a machine's description of itself. The spec is the agents plugin's input and a program's
  brief; the spec-drift lint compares it with the observed event map from outside the core.
- **The provider is never the machine (D19).** The spec names the machine (`pipeline_manager`),
  never `agents` or a host. Whatever runs it (the agents' host, a `[[machines]]` command) publishes
  only as the machine and its instances.

### 2.2 `machine.toml`

```toml
name = "pipeline_manager"
description = "Decides what a failed check means, retries only what is worth it, names the commit that broke the base, and asks for flaky tests to be quarantined."
engagement = "continuous"            # continuous | scheduled | ad_hoc (SPEC §2's modes)
spec_version = 3                     # bumped by every edit; the commit is the real version

[[listens]]
type = "gate.stage_failed"           # §5.3
from = "merge_gate"
why = "a local gate stage failed and awaits a verdict"

[[publishes]]
type = "ci.verdict"
to = ["merge_gate"]
schema = "examples/ci.verdict.schema.json"
example = "examples/ci.verdict.retry.json"

[[tools]]
name = "read_check_log"
group = "ci"                          # an orchestra-agents tool group
effect = "read"                       # read | act | outbox
inputs = { check = "gate run id + spec, or a GitHub check run id" }
returns = "the failing part of the log, at most 400 lines"
```

Each tool's `effect` matters for replacement: a `read` tool becomes a library call, an `act` is a
bus event the program publishes, and an `outbox` tool is an act as the owner (§4.4), which needs the
same approval whoever calls it.

### 2.3 Decomposition inside the spec

A responsibility is a slice of the contract with its own prompt file:

```toml
[[responsibilities]]
name = "retry"
prompt = "responsibilities/retry.md"
listens = ["ci.failure.classified"]
publishes = ["ci.verdict"]
tools = ["read_retry_budget"]
implemented_by = "agent"             # agent | program | shadow
```

Splitting a responsibility out is a commit that changes no behaviour (null test). It is also where
the "one machine per decision rule" heuristic (`environment-and-ghost-machines.md` §5) is applied:
if two responsibilities steer the same stock towards different goals, they stay in one machine; if
they scale differently or would have different owners, they become separate machines with their
own contracts.

### 2.4 Versioning

| Change | Announced as | Era? |
|---|---|---|
| Prompt, responsibility, tool or event edit in `.orchestra/machines/` | `role.changed` (the agents plugin, as the Supervisor), subject `machine:<name>`, with the commit | Yes: `role.changed:source=supervisor` is in `[discovery] eras_from` (SPEC §8 example) |
| A responsibility switched agent → shadow → program | `config.changed` (the `[[machines]]` entry, the agent record) | Yes, by default |
| An instrument added to watch the machine (shadow comparator, usage) | `instruments.changed` | No: what is measured changed, not the system |
| A local override loaded or retired (§4) | `system.changed`, subject `override:<name>`, published by the Supervisor | Yes |

The commit is the version; `spec_version` only makes the transcript and the prediction say which
spec they ran under.

## 3. Where the program's code lives

| Place | When | How it runs |
|---|---|---|
| **The target repository** (recommended first) | A responsibility of this project's machine | A `[[machines]]` command in `orchestra.toml` running code under `.orchestra/machines/<name>/program/` (or wherever the repository keeps its tools), speaking to the bus over HTTP (D16: no Orchestra import needed) |
| **A plugin** | The second project that wants the same machine | The program moves into a plugin and is declared there (`Plugin.processes`); the spec moves with it as the plugin's shipped machine spec, which a project's copy overrides |
| **Orchestra's core** | Only what is domain-free | Nothing in this proposal qualifies except loading project-local plugins and overrides (§4.1). The pipeline manager knows gates and tests: never core (rule 1) |

The target repository first, because the spec is born there, the program is tested against that
project's recorded events, and it lands through that project's review and gate. A plugin when it
is reused, because two copies drift. The pipeline manager is likely to be reused by every project
the owner runs, so §7 plans its move early; which plugin is open question 2.

## 4. Patching without editable installs

### 4.1 Project-local plugins and overrides

Orchestra and its plugins are installed as packages; the Supervisor cannot edit them. What
Orchestra would need:

- **`.orchestra/plugins/<name>/`** loaded beside the `orchestra.plugins` entry points, with the
  same `Plugin` contract (SPEC §10.1) and the same failure handling (left out and reported, never
  fatal).
- **`.orchestra/overrides/<name>.py`**: a module that wraps or replaces a named attribute of an
  installed package, with a header Orchestra checks before applying it:

  ```python
  TARGET = "tasking.gate:run_specs"       # module:attribute
  PACKAGE = "orchestra-tasking==0.9.2"    # applied only on this exact version
  KIND = "wrap"                           # wrap (gets the original) | replace
  ISSUE = "danroblewis/orchestra-tasking#41"
  def override(original): ...
  ```

  On a different installed version it is not applied and is reported stale, so an override cannot
  outlive the fix it waits for, nor silently apply to code it was not written against.
- **Applied in every process that runs plugin code**, not only the web server: the agents' host and
  the task scheduler are separate processes. Orchestra applies overrides wherever it loads plugins
  (`plugins.load`) and before calling a plugin command (`orchestra.commands`), which is how the
  launcher starts plugin processes.
- **Visible.** The Core page lists loaded local plugins and overrides with their targets, versions
  and issues; a stale or failing one is shown, not hidden.

**Rule 10.** "No `sys.path` manipulation" holds: a local plugin is loaded by file location
(`importlib.util.spec_from_file_location` with `submodule_search_locations`, registered in
`sys.modules` under `orchestra_local.<name>`), and `sys.path` is never touched. "Everything
importable is under `orchestra/`" is about Orchestra's own code; a project's plugin is the
project's. Rule 10 would gain one sentence, stated in the commit that builds it: *"A project's own
plugins and overrides are loaded by file from `.orchestra/plugins/` and `.orchestra/overrides/`,
never by adding to `sys.path`."*

**Seams before patches.** A monkeypatch is the escape hatch. When the same target is overridden
twice, the upstream fix is a named extension point (a hook a plugin declares and a project's plugin
fills), and the override goes.

### 4.2 Who writes a patch

orchestra-agents' SPEC §10 says the Supervisor "never changes code, in an emergency or otherwise:
code is a worker's, through a ticket, a review and the gate", and its sessions are read-only. The
owner's 2026-10-28 wording ("the Supervisor should be able to monkeypatch") conflicts with it.
Recommendation, pending the owner (open question 4): the Supervisor diagnoses and writes the
brief, the patch is a ticket like any code (a worker writes it under `.orchestra/overrides/`, a
reviewer reviews it, the gate lands it), and the Supervisor files the upstream issue. A truly
blocking case may get an emergency path later, with the owner's approval in the outbox.

### 4.3 Issues and PRs upstream

- **The issue** carries: what broke and why; the override's diff against the installed version;
  the configuration excerpt involved (secret-scanned, overlay values never included); and a
  **reproduction as recorded events**: the slice of the bus around the failure (`GET /events`,
  filtered by `correlationid` or time), which a test in the upstream repository can replay.
- **The PR**, when the fix is clear: a scratch clone in the state directory
  (`~/.orchestrator/<key>/scratch/<repo>/`, rule 5), a branch, the patch applied, that repository's
  own unit tests run, then pushed and opened. No editable install is involved; the clone is never
  imported by the running Orchestra.
- **Both act as the owner** (their GitHub identity), so both go through the outbox: kinds
  `github.open_issue` and `github.open_pr`, approved by the owner per kind, earning `auto` on the
  owner's own repositories by a run of unedited approvals (the owner's rule that outbound acts are
  human-approved by configuration; story-placement §5). The outbox is not built anywhere today (orchestra-bridges ARCHITECTURE §10:
  "Proposed, not built"); this proposal depends on it.
- **Closing the loop.** When the upstream release carrying the fix is installed, the override goes
  stale (§4.1), the Supervisor removes it through a ticket, and `system.changed` marks the era.

## 5. The worked example: a pipeline manager

### 5.1 Why this one

Nothing does it today (orchestra-tasking at `d9134de`): the gate lands one ticket per run, reruns
a failed spec blindly up to `[gate] rerun_failures` times in the same worktree, pauses the
pipeline and tells the Supervisor when the base itself fails, and nothing bisects or quarantines.
External mode (`[gate] mode = "external"`) reruns nothing at all: a failing check sends the work
back to the worker. It is G10, it replaces no plugin, and the model already measures what it should
move: `tasks_gate_reruns_total`, `tasks_gate_flaky_stages_total`, `tests_flaky{kind}` (G14), and
the gate's rejection flow, whose flaky share and bisection rate lifted-models §4 names as levers.

### 5.2 Responsibilities

| Responsibility | Standing condition it keeps true |
|---|---|
| **Triage** | Every failed check has a class (`infra`, `flaky`, `timeout`, `real`, `unknown`) with its evidence, within 2 minutes |
| **Retry** | A failure is retried only when its class says a retry can pass, within a budget per run; a real failure is never retried |
| **Bisect** | When the base branch breaks, the commit that broke it is named within K checks, and the Coordinator is asked for a bug ticket for it (D2: DONE is never reopened) |
| **Flakes** | A test that flakes N times in a window is asked to be quarantined (a ticket via the Coordinator) and is listed in `.orchestra/flakes.toml` (story-placement §5 item 13) |

It works for both gates: the local gate (orchestra-tasking runs the specs) and external CI
(GitHub Actions on the sandbox; SAIL at work, label-driven).

### 5.3 What the lift changes in the task system's gate

| Stays in the gate (a stage, a program) | Moves to the pipeline manager (a judgement) |
|---|---|
| Merge, build, run the specs, land, push, staging | Whether a failed spec is worth rerunning |
| The retry *ceiling* (`rerun_failures` becomes the most the gate will ever rerun) and recording `flaky` | Which failure is infra, flaky, a timeout or real |
| The base check after a failure, and pausing the pipeline on a broken base | Finding which commit broke the base, and asking for its ticket |
| Running specs at a given commit when asked (new: a check run that lands nothing) | Choosing which commits to check during a bisection |
| `gate.rejected` and the hand-back to the worker (merge_gate → coordinator → worker, D17) | The reason in that rejection, when the verdict is `reject` |

The gate gains one mode, `[gate] verdicts = "pipeline_manager"`, off by default:

1. A spec fails. The gate publishes **`gate.stage_failed`** `{gate_run, ticket, stage, spec, attempt, returncode, duration, log}` (as `merge_gate`, cause the run's `gate.started`) and waits up to `[gate] verdict_timeout` (default 120 s), holding the worktree.
2. A **`ci.verdict`** `{gate_run, spec, attempt, verdict: "retry" | "reject" | "pause", class, reason}` naming the stage failure as `causationid` decides: `retry` reruns the spec (never past `rerun_failures`); `reject` rejects with the verdict's reason added to the feedback; `pause` treats it as an infrastructure failure (pipeline paused, ticket stays `APPROVED`, as for a broken base).
3. No verdict in time: today's behaviour (blind reruns up to the ceiling). The gate never depends on an agent being up.
4. **`gate.check_requested`** `{check, commit, specs}` (from the pipeline manager) runs the named specs at a commit in a scratch worktree and answers **`gate.checked`** `{check, commit, results: [{spec, status, returncode, log}]}`, landing nothing. This is the bisection primitive; it is also story-placement's "tests at a ref" (item 12).

External mode needs one thing the bridges do not give: CI on the base branch. The PR tracker sees
check runs on pull requests only (`github.pr.check_completed`, no workflow runs, no logs, no
reruns). Bisection on external CI needs `github.branch.check_completed` (the same fields, for a
followed branch's head) in orchestra-bridges, a `ci` tool that reads a failed job's log (`gh run
view --log-failed`), and outbox kinds to act: `github.rerun_failed_jobs`, `github.dispatch_workflow`
(run a workflow at a commit), and for SAIL `github.label` (re-label, at most N times with backoff,
story-placement story 17).

### 5.4 The spec in full

`.orchestra/machines/pipeline_manager/role.md`:

```markdown
You are the pipeline manager. You keep the path from an approved change to a green base branch
short and honest. You do not write code, change tests or edit configuration; you decide, ask and
record.

Your responsibilities:
1. Triage. When a check fails, read its log and say what kind of failure it is: infra (the runner,
   network, a service the tests need, out of disk), timeout (killed for time with no assertion
   failed), flaky (this test has both passed and failed on the same code; see its history and
   .orchestra/flakes.toml), real (an assertion or an error the change could cause), or unknown.
   Give the evidence: the log lines, the history, the pattern matched. Publish ci.failure.classified.
2. Retry. Retry infra, timeout and known-flaky failures, within the run's budget; never retry real
   ones; retry an unknown once. For the local gate answer with ci.verdict; for external CI request
   the rerun through the outbox. Say why in every verdict.
3. Bisect. When the base branch fails (gate.base_broken, or a failing check on the base), find
   the last commit that passed and check commits between it and the head by halving
   (gate.check_requested, or a workflow run at a commit through the outbox). A flaky result during
   bisection is checked again before it counts. When you have the culprit, publish ci.culprit.found
   and ask the Coordinator for a bug ticket naming the commit, the failing check and the log.
4. Flakes. Keep count of each test's flakes (ci.flake.recorded). When one flakes 3 times in 7 days,
   ask the Coordinator for a ticket to quarantine it and add it to .orchestra/flakes.toml.

Your loop, for every wake-up: read the event that woke you; read what you need with your tools;
decide; publish exactly the events your contract lists; stop. Keep no memory outside the bus and
your space: your earlier verdicts, bisections and counts are events you can read back.

When you cannot decide, say so: publish the verdict "reject" with class "unknown" for the local
gate, or escalate to the Supervisor. Never guess "flaky" to get a change landed.
```

`machine.toml` (abridged to the contract):

| Listens | From | Why |
|---|---|---|
| `gate.stage_failed` | `merge_gate` | A local stage failed; a verdict is awaited |
| `gate.base_broken` | `merge_gate` | The local base fails alone: bisect |
| `gate.checked` | `merge_gate` | A bisection step's result |
| `gate.landed` | `merge_gate` | `flaky` in its data: count the flake; and a green base ends a bisection |
| `github.pr.check_completed` | `bot.<app>` | A failing check on a pull request (external CI) |
| `github.branch.check_completed` | `bot.<app>` | A check on the base branch (new in bridges) |
| `github.pr.labelled` | the pipeline's account | A failing label such as `SAIL-failed` |

| Publishes | To | Data | Example |
|---|---|---|---|
| `ci.failure.classified` | (record; read by retry and flakes) | `check` (a gate run + spec, or a check run id), `subject` (ticket or `repo#pull` or `branch@sha`), `class`, `confidence` (0–1), `evidence` (lines, history, pattern), `test` (when one test is named) | `{"check": "g-3fa1:unit:tests", "class": "flaky", "confidence": 0.8, "test": "tests/test_net.py::test_retry", "evidence": ["failed 2 of last 10 runs on unchanged code"]}` |
| `ci.verdict` | `merge_gate` | `gate_run`, `spec`, `attempt`, `verdict`, `class`, `reason` | `{"gate_run": "3fa1c2d9e0", "spec": "unit:tests", "attempt": 1, "verdict": "retry", "class": "flaky", "reason": "test_retry is a known flake; budget 1 of 2"}` |
| `gate.check_requested` | `merge_gate` | `check`, `commit`, `specs` | `{"check": "b-7c2:4", "commit": "a1b2c3d", "specs": ["unit:tests"]}` |
| `ci.bisect.started` | (record) | `bisect`, `branch`, `good`, `bad`, `commits` | `{"bisect": "b-7c2", "branch": "main", "good": "0f0e...", "bad": "9a8b...", "commits": 7}` |
| `ci.culprit.found` | (record; the Coordinator reads it in the request) | `bisect`, `commit`, `check`, `steps`, `confidence` | `{"bisect": "b-7c2", "commit": "5d6e7f0", "check": "unit:tests", "steps": 3, "confidence": 0.95}` |
| `ci.flake.recorded` | (record) | `test`, `check`, `count_7d` | `{"test": "tests/test_net.py::test_retry", "count_7d": 3}` |
| `work.requested` | `coordinator` | the existing hand-off shape `{request, requirements, context, to: "coordinator", by}` | a bug ticket for the culprit, or a quarantine ticket |
| `ci.failure.deferred` | the agent instance (after a swap) | the input event as `causationid` | (§1.2) |

All under the machine's own source, `pipeline_manager`, and later its program instances
(`pipeline_manager/retry`, `/flakes`, `/bisect`). The `ci.` prefix keeps clear of the task
system's own `pipeline.paused` and `pipeline.resume_requested`.

| Tools | Group | Effect |
|---|---|---|
| `get_gate_run`, `list_gate_runs` | `pipeline` (exists) | read |
| `read_check_log` (gate log, or a GitHub job's failed log) | `ci` (new) | read |
| `test_history` (a test's outcomes over the last N runs, from the gate's reports and `tests_*` series) | `ci` (new) | read |
| `read_series`, `read_model` | `model` (exists) | read |
| `read_events` (its own earlier verdicts, bisections and counts) | `events` (exists) | read |
| `emit_event`, limited to the contract's publishes | `events` (exists) | act |
| `request_work` (to the Coordinator; `hand_to_coordinator` generalised beyond the Supervisor) | `handoff` | act |
| `rerun_failed_jobs`, `dispatch_workflow`, `set_label` | `outbox` (new) | outbox |

Engagement: continuous, with an ephemeral session per wake-up. A bisection's state is its events
(`ci.bisect.started`, `gate.check_requested`, `gate.checked`), not a resident session's memory:
that is what makes it replaceable.

### 5.5 How it is tested

**The sandbox.** `danroblewis/orchestra-e2e-sandbox` (private; today a README, `runs/` and
`sandbox.txt`, no workflow) gets:
- a small Python package with a test suite, and a GitHub Actions workflow on `push` and
  `pull_request` that runs pytest with a JUnit report as an artifact;
- `test_sometimes` that fails with a seeded probability (30%), the deliberate flake;
- an infrastructure fault that a scenario switches on (a step that fails on a network call), and
  a test that hangs past the job's timeout;
- a **scenario script** in orchestra-agents' e2e tests that makes a sequence of landings (L1..L8)
  as the owner, with a manifest of ground truth: L3 touches the flaky test's file without changing
  it, L5 breaks a function a later test uses, L6 and L7 land on the broken base.

**Two runs of the same scenario.** Local gate: the sandbox cloned as the target, tasking's demo
workers landing the eight changes through the gate with `verdicts = "pipeline_manager"`. External
CI: the same changes as pull requests, merged by the script, the PR and branch bridges following.

**Graded against the manifest**, as a suite in orchestra-agents (opt-in, like the existing e2e):

| Measure | Pass |
|---|---|
| Classification of each failure | Every injected flake `flaky` or `unknown`, never `real`; L5's failure `real`; the infra fault `infra`; the hang `timeout` |
| Retries | No retry of L5's failure; every flake retried within budget and landed |
| Culprit | `ci.culprit.found` names L5's commit, within ⌈log₂ 8⌉ + 2 checks |
| Quarantine | One `work.requested` for `test_sometimes` once it passed its threshold, none for any other test |
| Cost | Tokens and dollars per handled event recorded (H2's usage series) |

The same suite runs with the dummy harness (scripted rules, deterministic, free) in the unit tier,
and with a real model nightly; the real run's grade is the machine's score across refines.

### 5.6 The decomposition it would likely go through

| Order | Responsibility | Why then | Program |
|---|---|---|---|
| 1 | **Retry** | A table once the class is given: class × attempts × budget → verdict. Its tool sequence is fixed from the start | A rule table, `pipeline_manager/retry`, listening to `ci.failure.classified` |
| 2 | **Flakes** | Counting `ci.flake.recorded` in a window and asking at a threshold | A counter with a threshold, `pipeline_manager/flakes` |
| 3 | **Bisect** | The search is an algorithm; the agent's part is handling flaky steps and odd histories (merges, reverts). Once those cases are written down it is a program | `pipeline_manager/bisect`, deferring merge commits and repeated flaky steps |
| 4 | **Triage** | Reading logs is the agent's real work. Patterns the agent finds (infra signatures, timeouts) become `.orchestra/flakes.toml` and an infra pattern file, and a program classifies what matches | `pipeline_manager/triage` for matched patterns; the agent keeps `unknown` and anything new |

The machine probably ends as programs plus an agent woken only for unmatched failures: the
fallback rate is the measure of how much judgement the job really needs.

### 5.7 What it should do to the model

Its creation is a change with a prediction (G13): the gate's reruns per run fall, the rejection
flow's flaky share falls towards zero, landings per day are unchanged or rise, and after a base
break the time to a named culprit is bounded. These are the intended-effect test of its first era;
each swap afterwards is a null test on the same series.

## 6. Risks

| Risk | What happens | What we do |
|---|---|---|
| **Cost** | An agent per failed check, on a busy CI, spends real money; cost is not measured today | H2's usage series first (§7 step A1); a per-machine budget and a brake; the dummy harness for the unit tier; decompose the cheap rule-like parts first |
| **Drift** | Refines accumulate; the prompt says one thing and the agent does another; the spec and the bus disagree | Spec-drift lint; refines carry predictions and are judged; the grading suite runs after every refine |
| **Permissions** | A machine that can rerun CI, relabel and file tickets can loop or flood | Retry ceiling stays in the gate; outbox per-kind limits; `emit_event` limited to the contract; the existing cause-chain depth limit |
| **An agent acting as the owner** | Issues, PRs, reruns and labels go out under the owner's name | Everything through the outbox; `auto` only by a record of unedited approvals; company systems (SAIL) stay human-approved until the owner says otherwise (D10) |
| **Nondeterminism** | The same failure classified differently on two days; a verdict that cannot be reproduced | Every verdict carries evidence and the spec version; the grading suite measures consistency; deterministic parts move to programs first |
| **The central agent** | Expected: the Supervisor creates, refines, decomposes, patches and files issues, and becomes the one place everything goes; the pipeline manager grows into "everything about CI" | Planned for: the curator role takes refine and decompose off the Supervisor once two machines exist; spec size and disjoint-usage triggers split machines; one machine per decision rule; the Supervisor configures and briefs, it does not run machines' work |
| **Goodhart** | Retrying more lands more but hides real failures | The verdict must not optimise landings: `real` misclassified as `flaky` is the graded failure that matters most, and every landing marked flaky is still counted (G14) |
| **The fallback becomes the system** | The program defers so often that the agent is still doing the job, at the cost of both | The fallback rate is a series; above a threshold the swap is undone (a configuration change, an era) |

## 7. Implementation steps

In order; each step lands in the repository that owns the concept.

| # | Repository | Step |
|---|---|---|
| A1 | orchestra-agents | Usage as series: tokens and dollars per machine and trigger (H2); the transcript instrument for tool-sequence determinism |
| A2 | orchestra-agents | `.orchestra/machines/<name>/`: `machine.toml` parsed; an agent record may name a `machine`; `wake_on` from `listens`; `emit_event` limited to `publishes`; responsibilities assembled into the prompt; the spec lint; `role.changed` with subject `machine:<name>` |
| T1 | orchestra-tasking | `[gate] verdicts`: `gate.stage_failed`, waiting for `ci.verdict` with `verdict_timeout`, the fallback to today's reruns; `gate.check_requested` / `gate.checked` (specs at a commit, no landing) |
| A3 | orchestra-agents | The `ci` tool group (`read_check_log`, `test_history`); `request_work` for any machine granted `handoff` |
| S1 | orchestra-e2e-sandbox | The package, the workflow, the flaky test, the infra and timeout faults |
| A4 | orchestra-agents | The pipeline manager's spec (§5.4) in the agents' demo and the sandbox target; the graded scenario suite, dummy and real; local gate first |
| B1 | orchestra-bridges | `github.branch.check_completed` for followed branches |
| O1 | the outbox (its plugin, not yet placed) | Kinds `github.rerun_failed_jobs`, `github.dispatch_workflow`, `github.label`, `github.open_issue`, `github.open_pr`, with per-kind approval |
| A5 | orchestra-agents | The external-CI half of the scenario; the SAIL variant (label) behind owner config |
| A6 | orchestra-agents | Shadow and replace: a `[[machines]]` program instance with `shadow = true`, the decision log, the `agents.shadow` comparator instrument, deferral types; the first swap (retry) and its null test |
| O2 | orchestra (this repository) | Project-local plugins and overrides (§4.1): loading by file, version pinning, application in plugin processes, the Core page listing; rule 10's sentence |
| A7 | orchestra-agents | The Supervisor's upstream path: issue with patch and recorded events, PR from a scratch clone, both through the outbox |
| A8 | orchestra-agents | The curator role taking refine and decompose off the Supervisor (G15, generalised) |

O2 and A7 do not block the pipeline manager; they are needed the first time a plugin's behaviour
blocks a project.

## 8. Open questions for the owner

1. **The spec's place.** `.orchestra/machines/<name>/` beside the existing `roles/` and `agents/`
   (recommended), or the role record grown to carry the contract?
2. **Where the pipeline manager's programs go when reused:** orchestra-tasking (it knows the
   gate), a new `orchestra-pipeline` plugin, or orchestra-agents' library of reference machines?
3. **The gate waiting for a verdict.** Is a gate that holds a worktree for up to two minutes for
   another machine's judgement acceptable, given D17 (the task system is the record, not the hub)?
   The alternative is the pipeline manager acting after a rejection, which loses the retry.
4. **Who writes patches.** The Supervisor directly (the owner's wording), or through a ticket
   (orchestra-agents' SPEC §10 as written)? An emergency path?
5. **The outbox's home and its first kinds.** It blocks external CI reruns, SAIL relabels,
   issues and PRs.
6. **SAIL.** May the pipeline manager ever relabel at work without approval, and how is a SAIL
   log fetched (story 17 says unknown, probably a private company plugin)?
7. **Thresholds** the owner wants as defaults: retry budget per run, flakes before quarantine
   (3 in 7 days proposed), the tool-sequence share that triggers a replacement (0.8 proposed).
8. **Who may refine.** The Supervisor only, or may a machine's spec be refined by a curator agent
   without the Supervisor in the loop?
