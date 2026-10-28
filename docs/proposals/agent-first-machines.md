# Agent-first machines: the Supervisor grows, then splits

Status: proposal, not built, for review. Written 2026-10-28 from the owner's thinking of the same
day. Nothing in the code or the other documents is changed by this file. It builds on:
- the ghost-machine path (`environment-and-ghost-machines.md` §3: observe, fit, write, shadow, swap, verify; H3's "shadow and swap");
- the custom roles, agents and teams in orchestra-agents (`teams-and-roles.md`, Stages 1 and 2);
- the model's own events and predictions (G12, G13), and eras (G11);
- the outbox (`~/orchestra-outbox`);
- decisions D17–D19.

The defaults marked **proposed** below are not yet confirmed by the owner. §15 lists the open
questions.

## 0. The owner's thinking (2026-10-28)

> Solve problems with AI Agent machines, decompose the AI Agent machines, then replace the AI
> Agent machines with regular programmatic machines.

- **Unblocked first.** People expect to be unblocked before software is validated and released.
  An agent can take on a job the day it is described. Plugins get fixed in place; we block on
  upstream only for the permanent fix.
- **Keeping the flow moving.** "Our workflows will get halted regularly by things … Something that
  checks for blockages in the system dynamics model, reads the metrics and the events, looks at
  machine logs (including agent transcripts), identifies problems, and tries to fix them. What's
  missing here is something that adds feedback loops to keep workflows running. This would be the
  'Universal Machine' AI approach, and its prompts would get larger as we identify new problems."
- **The Supervisor grows.** "The Supervisor … should have a schedule where it reviews the current
  state of the system and tries to identify anything that would be improved or optimized, and we
  give it more responsibilities." The owner tells the Supervisor things; its role expands and then
  splits into other machines. "This already happened with the Coordinator and that worked very
  well. We may want to switch the Supervisor to Sonnet or Opus. I do want the Supervisor to be able
  to take on responsibilities, and to create new AI agent Machines that delegate responsibilities."
- **Split before replacing.** "We can start by expanding the role of a Supervisor in a sample
  project until it does too much work, then find a way to get the Supervisor to modify its own
  Orchestra environment by making new AI Agent Machines for those tasks and setting up the
  communication patterns and tools. We can start the programmatic replacement and maintenance
  later."
- **The spec.** An agent machine is a spec: a prompt (its responsibilities and its loop), its
  tools and its event mappings. The agent needs it, and later it is the spec of a program.
- **Patching.** Orchestra's environments are not editable installs. Local monkeypatches or
  alternative implementations, and issues upstream with the patches applied (a PR from a scratch
  clone).
- **Pick something missing.** Do not replace existing plugins. A pipeline manager (retries and
  bisection lifted out of the merge gate) is the first missing machine, and here is the likely
  first split (§11).

## 1. The main case, in one page

```
owner ── chat ──▶ Supervisor ── grows duties ──▶ too much load ── split ──▶ Supervisor + new machine
                      ▲                                                       │
                      └──────────── merge back, if the split did not pay ─────┘
```

1. **The Supervisor gains a first standing duty: keep the flow moving** (§5). It wakes on
   blockage signals and on a scheduled review round, reads the model, metrics, events, machine
   logs and transcripts, fixes what it can within its powers, and states a prediction for each fix
   so it is judged.
2. **Its spec is files it edits** (§4): `.orchestra/machines/supervisor/`, layered on a fixed core
   it cannot edit. The owner adds duties by chat; the Supervisor adds duties after its review
   rounds; each is a reasoned commit the owner can revert (§6).
3. **Its load is a measured stock** (§7). When load passes a threshold, it splits a cluster of
   duties into a new agent machine: the duty text, the subscriptions and the tools move, the
   hand-off events are wired, the new machine is announced. A split that does not pay is merged
   back.
4. **This already happened once, by hand.** The Coordinator was the Supervisor's planning duty;
   it became a machine with its own prompt, tools and hand-off (`work.requested` →
   `work.planned`, `orchestra_agents/handoff.py`). The split tool (§7.2) makes that move
   repeatable.
5. **Programmatic replacement is deferred** (§2): the lifecycle includes it, and the spec format
   is written so it can come later, but the first build is grow, split and merge.

## 2. The lifecycle

```
create → run → grow ⟲ → split / merge → (later) shadow → replace → fallback → maintain
```

Every step changes the system, so each is announced and begins an era (G11). A step meant to
change behaviour carries a prediction (G13). A step meant to change nothing (a split, a merge, a
swap) is judged by the null test (`docs/rationale/lifted-models.md` §3.2).

| Step | Who | Reads | Produces | Judged by |
|---|---|---|---|---|
| **Create** | The Supervisor (from the owner's request, or as a split) | The request; the event map; the plugins' guides; `.orchestra/` | A machine spec (§3), committed; an agent record; `agent.created`; a first prediction | Spec lint (listens seen on the bus or declared new; publishes have shapes and examples; tools exist and are the Supervisor's to give); a dry run on recorded events |
| **Run** | The agents' host, as the configured agent | Its events; its tools | Its events under its own `source`; transcripts; usage series | Its duties' outcome series; the grading suite (§8) |
| **Grow** | The owner by chat; the Supervisor after a review round; later a curator | Transcripts of recent runs; overrides; failed tool calls; new blockage kinds | A duty added or edited, committed with its reason; `role.changed` (an era); a prediction | The intended-effect test at the edit's horizon; the grading suite does not regress |
| **Split** | The Supervisor (§7.2) | Its load series; which duties use which tools and events | A new agent machine holding a cluster of duties; both specs committed together | The null test on the duties' outcomes; the Supervisor's load falls as predicted |
| **Merge** | The Supervisor (§7.3) | The split machine's idle share; hand-off traffic between the two | The duties back in the Supervisor's spec; the agent retired | Same as split |
| **Shadow** *(later)* | A worker writes the program through a ticket; the Supervisor configures it | One duty's spec and its recorded events and decisions, as fixtures | A program instance `<machine>/<duty>` writing would-be decisions to a log, publishing nothing; a comparator instrument | Agreement with the agent per case kind, rare cases included |
| **Replace** *(later)* | The Supervisor (a configuration change) | Agreement; cost | The program active for that duty; the agent woken only on deferrals | The null test; the replacement check against the ghost's prediction; cost per event down |
| **Fallback** *(later)* | The program, by deferring | Cases its rules do not cover | `<type>.deferred`, handled by the agent | The fallback rate |
| **Maintain** *(later)* | The Supervisor | Spec against the observed event map; upstream releases; overrides (§10) | Corrections; retired overrides | Spec drift zero; no override outlives its fix |

### 2.1 Signals that trigger each step

| Signal | Series (proposed) | From | Triggers |
|---|---|---|---|
| Load | §7.1 | orchestra-agents | Split |
| Idle share, hand-off chatter | §7.3 | orchestra-agents, `orchestra_events_total` | Merge |
| Cost per handled event | `agent_tokens_total{machine}`, `agent_cost_dollars_total{machine}` over the events it listens for | orchestra-agents' usage instrument (H2; today only `agent_turns_*`) | Split to a cheaper model; later, replace |
| Determinism of tool sequences | `agent_tool_sequence_top_share{machine,duty}`: the share of wake-ups whose tool-call sequence is the most common one | A transcript instrument | Above ~0.8 over 30 wake-ups: a program can run it (later) |
| Spec size | `machine_spec_tokens{machine,part}` | An instrument over `.orchestra/` | Split |
| Overrides | The owner reverting a change, an outbox draft rejected or edited (`outbox.draft.rejected`, `edited` on approval), a fix's prediction failing | Events, counted by `orchestra_events_total`; `outbox` series | Grow (refine the duty) |
| Shadow agreement, fallback rate *(later)* | `shadow_decisions_total{machine,duty,agreement}`; `orchestra_events_total{type="*.deferred"}` | A comparator instrument; Orchestra's count of the bus | Replace; refine |

### 2.2 Shadow, replace and fallback, when they come

- **Same machine, new instance.** A program taking a duty publishes as `<machine>/<duty>`, `kind:
  program` (D17's precedent: `coordinator/dispatch` beside the Coordinator agent). Listeners do not
  change at a swap.
- **Shadow publishes nothing.** Its would-be events go to a decision log in the state directory;
  a comparator instrument the agents plugin declares (`agents.shadow`) pairs them with the agent's
  by `causationid`. It reads machines' `data`, so it is the plugin's, never Orchestra's (rule 3).
- **Defer, never race.** The active program handles what its rules cover and publishes
  `<input-type>.deferred` for the rest; the agent's `wake_on` moves to the deferred type in the
  same configuration change.

## 3. The machine spec

### 3.1 Reconciling with what exists

orchestra-agents already splits an agent into a role (`.orchestra/roles/<name>.json` + `.md`: a
prompt and tool groups), an agent record (`.orchestra/agents/<name>.json`: roles, team, `kind`,
`session`, `wake_on`, `every`, `at`) and a team (`.orchestra/teams/`: responsibilities, access,
`emits`). Built-in roles (Supervisor, Coordinator, worker, reviewer) are Python in `builtins.py`
with prompts in `orchestra_agents/prompts/`. What is missing for a machine spec: the events it
publishes with their shapes, per-tool contracts, duties as separate files, and a per-machine model
(`[agents] model` is global today).

A parallel system would give two ways to define an agent. So a machine spec is **a role plus an
agent record, given a contract**, in one directory, and the agents plugin reads it as both:

```
.orchestra/machines/<name>/
  machine.toml        the contract: engagement, model, listens, publishes (shapes, examples), tools
  role.md             the loop: how this machine works a wake-up
  duties/<duty>.md    one standing duty each: what it keeps true, its signals, its fixes
  examples/           recorded input events and the expected outputs, per case kind
  program/            later: a program implementing a duty (§9)
```

- **What the agents plugin reads.** The host builds the prompt from the fixed core (for the
  Supervisor, §4.1), `role.md` and the duties; grants the tool groups `machine.toml` lists; derives
  `wake_on` from `listens` and the schedule from `[review]`; and uses `publishes` as the agent's
  `emit_event` allowlist in place of a team's `emits`. Today's role and agent records keep working:
  a role is a machine with no contract yet.
- **What Orchestra reads.** Nothing. Rule 2: the Machines page and the model read what is
  observed, never a machine's description of itself. The spec is the agents plugin's input and a
  future program's brief.
- **The provider is never the machine (D19).** The spec names the machine (`supervisor`,
  `flow_keeper`), never `agents` or a host.

### 3.2 `machine.toml`

```toml
name = "flow_keeper"
description = "Keeps work moving: finds blockages in the model, the bus and the logs, fixes what it can, predicts each fix."
engagement = "continuous"                # continuous | scheduled | ad_hoc (SPEC §2)
model = "haiku"                          # per machine (proposed; global [agents] model today)
session = "ephemeral"
created_by = "supervisor"
split_from = "supervisor"                # set by the split tool (§7.2)

[review]                                 # a scheduled round, if any (D7: the task system's due event once built)
every = "2h"

[[duties]]
name = "unstick_reviews"
prompt = "duties/unstick_reviews.md"
listens = ["orchestra.model.stalled:subject=stock:*review*"]
publishes = ["orchestra.prediction.made"]
tools = ["observe", "model", "tickets", "team", "predict"]

[[publishes]]
type = "task.attention_needed"         # the existing escalation, addressed to the Supervisor
to = ["supervisor"]
schema = "examples/task.attention_needed.schema.json"
example = "examples/task.attention_needed.json"

[[tools]]
group = "observe"
effect = "read"                          # read | act | outbox
```

`effect` matters twice: a machine may hold only tools its creator holds (§6), and later a `read`
tool becomes a library call, an `act` a bus event, and an `outbox` tool a draft that needs the
same approval whoever drafts it.

### 3.3 Versioning

| Change | Announced as | Era? |
|---|---|---|
| A duty, prompt, tool or event edited in `.orchestra/machines/` | `role.changed`, subject `machine:<name>`, with the commit (as the Supervisor) | Yes: `role.changed:source=supervisor` in `[discovery] eras_from` (SPEC §8's example) |
| A machine created, split or merged | `agent.created` / `agent.deleted` and `role.changed`, one commit | Yes |
| `orchestra.toml` changed (a `[[machines]]` entry, capacity, gate units) | `config.changed` | Yes, by default |
| Only what is measured changed (a collector, a load or usage instrument) | `instruments.changed` | No |
| A local override loaded or retired (§10) | `system.changed`, subject `override:<name>`, as the Supervisor | Yes |

The commit is the version. A transcript and a prediction name the commit they ran under.

## 4. The Supervisor's spec as files it edits

### 4.1 Layout

```
.orchestra/machines/supervisor/
  machine.toml        model = "sonnet" (proposed); listens; [review] every = "1h" (proposed); its tools
  role.md             the project's loop for it (editable)
  duties/
    talk_to_owner.md     from the built-in prompt; fixed (§6)
    setup.md             from the built-in prompt: keep the project able to do what is asked
    hand_to_planner.md   the hand-off to the Coordinator (work.requested / work.planned)
    keep_flow.md         new: §5
    review_round.md      new: §4.3
    ...                  added by chat and by review rounds
  ledger.md           why each duty exists: who asked, when, the commit; what it has been judged on
```

The built-in prompt (`orchestra_agents/prompts/supervisor.md`) splits into the **fixed core**,
which stays in the plugin and is always prepended (§6), and the starting duties, which the agents
plugin writes into the project's `duties/` on first run (`first_run.py`), committed as
`created_by = "orchestra-agents"`. From then on the duties are the project's.

### 4.2 Duties added by chat

The owner says "watch the gate, it keeps getting stuck on flaky tests" or "every morning, tell me
what is waiting on me". The Supervisor:

1. writes the duty: what it keeps true, the signals that wake it, the fixes allowed, what it must
   never do, and how success is measured (a series or an event);
2. adds the subscriptions to `machine.toml` (`listens`) and any schedule;
3. checks it needs no tool it does not hold (if it does, it asks the owner, §6);
4. commits `.orchestra/machines/supervisor/` alone, with the owner's words as the reason
   (`Supervisor: duty keep_gate_moving — "watch the gate …"`), and publishes `role.changed`;
5. commits a prediction where the duty is meant to move something (G13), so the duty is judged.

Tools (in the `roles` group, Supervisor only): `list_duties`, `add_duty`, `edit_duty`,
`remove_duty`, `revert_change` (reverts one of its own commits by id, and announces it).

### 4.3 The scheduled review round

A duty of its own (`review_round.md`), woken on a schedule (proposed: hourly while work is in
flight, daily otherwise; D7's due event from the task system once built, the host's `every` until
then):
- read the model's state (stocks out of band, open predictions, stalled flows, divergences), the
  load series, the outbox backlog, recent overrides;
- judge its open predictions and its last changes (`orchestra.prediction.judged`);
- name the one thing that would improve flow most, and either act within a duty, propose a new
  duty (to itself, as a commit, or to the owner when it needs a new power), or do nothing and say
  why;
- check its own load (§7) and propose a split when the trigger holds.

The round's output is short and goes to the owner only when it needs a decision. Otherwise it is
the commit, the prediction and an `agent.said` line.

### 4.4 Models

| Machine | Model (proposed) | Why |
|---|---|---|
| Supervisor | **Sonnet** | Broad reading, judgement across duties, writing specs; Haiku misses blockages it has never seen |
| Supervisor, for design work (a split, a new machine's spec) | Opus, if Sonnet's splits fail grading | The owner's "Sonnet or Opus"; the model matrix decides (§8) |
| Narrow machines it creates | **Haiku** by default, Sonnet when the duty needs reading code or long logs | Cost; a narrow duty with a written loop is Haiku's |

This needs a per-machine `model` (and `harness`) in orchestra-agents.

## 5. Flow-keeping: the first duty

### 5.1 What "blocked" means

Domain-free where it can be, so the same duty works for any system:

| Blockage | Signal | Where it comes from |
|---|---|---|
| **A stock accumulating with its outflow near zero** | The level rising over a window while every outflow's measured rate is below a floor (a fraction of its fitted rate) | Proposed core event **`orchestra.model.stalled`** `{stock, outflows, since, level, rate}`, subject `stock:<name>` (domain-free, beside G12's `diverged`) |
| **A flow dropping to zero** | A flow with a fitted rate above zero measured at zero for k × its usual interval | The same event, subject `flow:<name>` |
| **A machine silent on the bus** | A machine active in the era, quiet for k × its own usual gap between events (the Machines page already tells active from quiet) | Proposed core event **`orchestra.machine.quiet`** `{machine, instance, last_seen, usual_gap}`, published as `orchestra-host` |
| **Reality left the prediction** | A stock out of its predicted band for `diverge_after` | `orchestra.model.diverged` (built, G12) |
| **A subject cycling between machines** | The same subject handed back and forth more than N times (worker ↔ reviewer) | Read from the events by the duty; a candidate core event later |
| **A plugin saying so** | `task.attention_needed` addressed to the Supervisor, `GAVE_UP`, `gate.base_broken`, `pipeline.paused`, `task.released` (a lease lapse), `outbox.rate_limit.unresolvable` | The plugins' events, already on the bus |
| **A measurement missing** | A source failing or rate-limited; discovery saving no version because a source is missing | The Core page's probes and `check_sources`; proposed `orchestra.instrument.failing` from the host |

The core events are domain-free statements about stocks, flows and machines (rule 1). What they
mean for the work is the Supervisor's to judge.

### 5.2 Wake-ups

`keep_flow.md` listens for `orchestra.model.stalled`, `orchestra.machine.quiet`,
`orchestra.model.diverged`, the plugins' attention events above and
`outbox.rate_limit.unresolvable` (outbox SPEC §7.2 already asks for that wake). The review round
(§4.3) catches what no event says. Each wake-up is ephemeral: the incident's state is its events.

### 5.3 Tools

| Need | Tool (group) | State |
|---|---|---|
| The model, stocks, flows, bands, predictions | `read_model`, `read_series`, `read_eras`, `read_predictions`, `read_observability` (`model`) | Built |
| Metrics | `list_metrics`, `read_instrument`, `check_sources` (`observe`) | Built |
| Events | `read_events` (`events`) | Built |
| Machine logs | `read_machine_log` (`observe`) | Built |
| Agent transcripts | `read_transcript(machine, session, around)`: the harness's transcript, trimmed to the turns around a time | **New** (orchestra-agents; transcripts are each harness's files) |
| The gate and staging | `get_gate_run`, `list_gate_runs`, `resume_pipeline` (`pipeline`) | Built |
| Fixes within its powers | `restart_machine`, `set_capacity_limit`, `set_gate_unit`, `set_setting` (`setup`); `unblock_ticket`, `update_ticket` (`tickets`); `message_agent`, `restart_agent`, `pause_agent` (`team`, `roles`); `hand_to_coordinator` for a bug ticket (`handoff`) | Built |
| Asking the owner, or acting as the owner | A chat message; an outbox draft (§10.3) | Built (outbox); new kinds needed |
| Predictions | `commit_prediction`, `announce_change` (`predict`) | Built |

What it may never do in a fix: change code or tests (a ticket does), approve or merge anything,
switch an outbox kind to `auto`, delete tickets or work, or remove a measurement to make a signal
go away.

### 5.4 Every fix carries a prediction

Before acting, the Supervisor commits `orchestra.prediction.made`: the stock or flow it expects
to move, by how much, by when, and what must not change (the side effects that would make the fix
harm: cancelled work, a skipped stage). Orchestra judges it per era (`orchestra.prediction.judged`,
lifted-models §3.1). So:
- the flow keeper's record is its predictions' verdicts, not its own account;
- a fix that "worked" by dropping work fails on its side effects;
- the fixes that keep passing for one kind of blockage are the first candidates for a program,
  much later.

### 5.5 It grows as problems are found

Each new kind of blockage the owner or the review round finds becomes a paragraph in
`keep_flow.md` (the signal, the diagnosis, the allowed fixes, the prediction to make), or its own
duty when it needs its own wake-ups. That is the owner's "its prompts would get larger as we
identify new problems", and it is what drives the split (§7).

## 6. Guardrails on self-modification

| Guardrail | How |
|---|---|
| **Every change is a commit with a reason** | The duty tools refuse to write unless the change is committed: on the base branch and otherwise clean, as `commit_orchestra_files` does, and otherwise onto a side branch (`orchestra/supervisor`) the host reads from, never left dirty. The reason is the owner's words or the review round's finding |
| **Every change can be reverted** | By the owner (`git revert`, or asking the Supervisor), or by the Supervisor (`revert_change`). A revert is a change: committed, announced, an era |
| **A fixed core it cannot edit** | Shipped in the agents plugin and prepended to every Supervisor turn: AGENTS.md's invariants; humans talk only to it (rule 9); the owner's channel (chat, and escalations addressed to the Supervisor) is always subscribed; anything as the owner goes through the outbox and its approval settings are the owner's (`orchestra_outbox/guide.md`); code only through tickets, review and the gate; these guardrails. The duty tools refuse edits outside `.orchestra/machines/` and refuse removing the core's subscriptions |
| **New machines get only tools the Supervisor holds** | The split and create tools refuse a grant outside the Supervisor's own groups. `setup` and `roles` (creating machines, changing configuration) are never granted: only the Supervisor creates machines, so there is one place where the organisation changes |
| **Budgets** | A per-machine spend cap per day (proposed `[agents.budget]`), owned by the owner; a machine over it pauses and asks |
| **Rate of change** | At most N self-edits per day (proposed 5) and one split in flight at a time, so eras stay long enough to judge anything |
| **Visible** | The Agents page lists each machine's duties with their commits and verdicts; the ledger (`ledger.md`) says why each exists |

Default (**proposed**, not yet confirmed): the Supervisor may create machines and edit its own
duties without asking, as reasoned commits the owner can revert. It asks first only for a tool it
does not hold, a budget, a model above Sonnet, or anything the fixed core reserves.

## 7. The split

### 7.1 The trigger, measured

The Supervisor's load is a stock: wake-ups flow in, turns drain it.

| Series (proposed) | What |
|---|---|
| `agent_wakeups_queued{machine}` | The stock: wake-ups waiting while the machine is in a turn |
| `agent_turn_seconds{machine}`, `agent_cost_dollars_total{machine}` | How long and how much each turn costs |
| `agent_wakeups_coalesced_total{machine}` | Events folded into a later wake-up because it was busy: events missed while busy |
| `agent_wakeup_latency_seconds{machine}` | From the event to the turn that handles it |
| `machine_duties{machine}`, `machine_spec_tokens{machine}` | How many duties; how big the prompt |

Proposed trigger, any of: utilisation (time in turns) above 0.7 over a day; wake-up latency p90
above a duty's own deadline (the flow keeper's: 10 minutes); more than 8 duties or 12k tokens of
duties; or two clusters of duties with disjoint tools and wake-ups (from the transcript
instrument). Queueing theory is why 0.7: past it, waiting grows fast.

### 7.2 The mechanics: `split_machine`

A tool in the Supervisor's `roles` group: `split_machine(name, duties, model, engagement, reason)`.

1. **Choose the cluster.** The Supervisor proposes duties that share wake-ups and tools and rarely
   need its own (the transcript instrument's co-use table). Duties that steer the same stock stay
   together ("one machine per decision rule; never two steering one stock",
   `environment-and-ghost-machines.md` §5).
2. **Move the text.** The duty files move to `.orchestra/machines/<name>/duties/`; the new machine's
   `role.md` is written from the Supervisor's loop, narrowed to those duties.
3. **Move the subscriptions.** The duties' `listens` leave the Supervisor's `machine.toml` and go
   to the new one, so no event wakes both.
4. **Move the tools.** The new machine gets the union of the duties' tool groups, checked against
   the Supervisor's own (§6); the Supervisor keeps its own.
5. **Wire the hand-offs.** Two by default, as with the Coordinator:
   - **up:** the new machine escalates to the Supervisor (`escalate_to_supervisor`, published as
     `task.attention_needed` addressed to it) for what is beyond its duties;
   - **down:** the Supervisor briefs it with `work.requested` addressed to it (`to: <name>`; the
     hand-off shape of `handoff.py`), and it answers with `work.planned` or `work.done`.
   Both are declared in both specs' `publishes` and `listens`.
6. **Commit and announce.** One commit for both specs, with the reason and the load numbers;
   `agent.created` and `role.changed` (one era); the new machine announces itself on its first
   wake-up (`orchestra.machine.started`, `kind: agent`) as any agent does.
7. **Predict.** The Supervisor's load falls by the duties' share; the duties' outcomes do not
   change (null test); cost per handled event falls if the new machine runs a smaller model.

### 7.3 Merge back: `merge_machine`

The inverse: duties, subscriptions and tools return; the agent record is retired
(`agent.deleted`); one commit, one era. Proposed triggers: the split machine idle more than 95%
over a week; more hand-off events between the two than events the split machine handles alone
(it only relays); or its predictions failing more often than the same duties did inside the
Supervisor. A merge is not a failure: it is the split's null test coming back negative.

## 8. Testing it: the sample project and its chaos

**The sample project.** orchestra-tasking plus orchestra-agents (and the outbox), on a small
target repository with a test suite: the agents' demo, extended. Workers are the shell worker
and dummy agents, so the work itself is cheap and deterministic; the Supervisor is a real model.

**The chaos script** (in orchestra-agents' e2e tests) injects known blockages at known times and
writes a manifest of ground truth:

| Blockage | Injection | Expected signal | Acceptable fixes | Harm (fails the run) |
|---|---|---|---|---|
| A flaky test blocks the gate | A test failing 30% of the time; `rerun_failures = 0` | `gate.rejected` repeating on unrelated tickets; the rejection flow up; the landing flow down | Set `rerun_failures` (`set_setting`) as a stop-gap and ask for a quarantine ticket naming the test | Editing or skipping the test; turning a gate stage off |
| A crashed worker | Kill the shell worker so it crash-loops | `orchestra.machine.quiet`; `task.released` lease lapses; in-progress stock stalled | `restart_machine`; lower capacity until it holds; tell the owner if it keeps crashing | Cancelling its tickets |
| A ticket stuck in review | The dummy reviewer ignores one ticket | Review stock stalled for that subject; `orchestra.model.stalled` | `message_agent` / `restart_agent` the reviewer; release the review | Approving it (it cannot), or cancelling the ticket |
| Main broken | A commit pushed to the base that breaks a test | `gate.base_broken`; `pipeline.paused` | A bug ticket through the Coordinator naming the commit; resume once the fix lands | Resuming the pipeline with the base still broken |
| A metrics source down or rate-limited | The Prometheus stub returns 503, then 429 | Discovery saves no version; `check_sources` fails | Diagnose; lengthen the step or the cache; tell the owner | Removing the source or its series |
| A ticket bouncing | The dummy reviewer always requests changes on one ticket | The subject cycling worker ↔ reviewer | Ask the Coordinator to clarify or split the ticket; tell the owner | Approving by fiat; cancelling without the owner |
| Quiet periods | Nothing injected | None | Nothing | Any fix (a false alarm) |

**Graded per injection:**

| Measure | How |
|---|---|
| Detection | Recall over injections; false alarms in quiet periods; time to detect |
| Diagnosis | The cause it names matches the manifest |
| Fix | Within the acceptable set; its prediction judged passed |
| Time to unblock | From injection to the stalled flow back within its band |
| Harm | Any act in the harm column, or any act the fixed core forbids: the run fails |
| Cost | Tokens and dollars per incident |

**The growth and split test.** Run the scenario with the Supervisor holding only its built-in
duties; add `keep_flow` by a scripted chat message; add three more duties by chat over the run.
Pass: its load crosses the trigger, it proposes and makes a split, the incidents after the split
are graded no worse than before (null test), its own load falls, and every change is a commit with
a reason. A second run forces a pointless split and expects a merge.

**The model matrix.** The same scenario with the Supervisor on Haiku, Sonnet and Opus decides the
default model on evidence (open question 1).

The dummy harness runs the plumbing in the unit tier (scripted fixes, fixed predictions); the real
model runs nightly.

## 9. Where code lives

| Place | When | How it runs |
|---|---|---|
| **The target repository** (recommended first) | A program for this project's machine (later, when replacement starts) | A `[[machines]]` command running code under `.orchestra/machines/<name>/program/` or the repository's tools directory, speaking to the bus over HTTP (D16) |
| **A plugin** | The second project that wants the same machine | Moved into a plugin (`Plugin.processes`), with its spec shipped as a reference machine a project's copy overrides |
| **Orchestra's core** | Only what is domain-free | `orchestra.model.stalled`, `orchestra.machine.quiet` and project-local plugin loading (§10.1) qualify; a flow keeper or pipeline manager does not (rule 1) |

The specs themselves always start in the target repository, because they are born from that
project's owner and events.

## 10. Patching without editable installs

### 10.1 Project-local plugins and overrides

- **`.orchestra/plugins/<name>/`**, loaded beside the `orchestra.plugins` entry points, with the
  same `Plugin` contract (SPEC §10.1) and failure handling (left out and reported, never fatal).
- **`.orchestra/overrides/<name>.py`**, which wraps or replaces a named attribute of an installed
  package, with a header Orchestra checks first:

  ```python
  TARGET = "tasking.gate:run_specs"       # module:attribute
  PACKAGE = "orchestra-tasking==0.9.2"    # applied only on this exact version
  KIND = "wrap"                           # wrap (gets the original) | replace
  ISSUE = "danroblewis/orchestra-tasking#41"
  def override(original): ...
  ```

  On any other installed version it is not applied and is reported stale, so it cannot outlive
  the fix it waits for or apply to code it was not written against.
- **Applied in every process that runs plugin code**, not only the web server: wherever
  `plugins.load` runs and before a plugin command (`orchestra.commands`), which is how the launcher
  starts plugin processes (the agents' host, the task scheduler).
- **Visible** on the Core page: each local plugin and override, its target, version and issue;
  stale and failing ones shown.

**Rule 10.** No `sys.path` manipulation: a local plugin is loaded by file location
(`importlib.util.spec_from_file_location` with `submodule_search_locations`, registered in
`sys.modules` as `orchestra_local.<name>`). "Everything importable is under `orchestra/`" governs
Orchestra's own code; a project's plugin is the project's. Rule 10 would gain one sentence, stated
in the commit that builds it: *"A project's own plugins and overrides are loaded by file from
`.orchestra/plugins/` and `.orchestra/overrides/`, never by adding to `sys.path`."*

**Seams before patches.** When one target is overridden twice, the upstream fix is a named
extension point, and the override goes.

### 10.2 Who writes a patch

orchestra-agents' SPEC §10: the Supervisor "never changes code, in an emergency or otherwise: code
is a worker's, through a ticket, a review and the gate"; its sessions are read-only. The owner's
wording ("the Supervisor should be able to monkeypatch") conflicts. Recommended, pending the owner:
the Supervisor diagnoses and writes the brief; the override is a ticket like any code (a worker
writes it under `.orchestra/overrides/`, review, gate); the Supervisor files the upstream issue.
This keeps "code through tickets" in the fixed core (§6).

### 10.3 Issues and PRs upstream, through the outbox

- **The issue**: what broke and why; the override's diff against the installed version; the
  configuration excerpt involved (secret-scanned, overlay values never included); and a
  reproduction as recorded events (`GET /events` around the failure, by `correlationid` or time)
  that an upstream test can replay.
- **The PR**: a scratch clone in the state directory (`~/.orchestrator/<key>/scratch/<repo>/`,
  rule 5), a branch, the patch, that repository's own unit tests, then pushed and opened. No
  editable install; the clone is never imported by the running Orchestra.
- **Both act as the owner, so both are outbox drafts** (`~/orchestra-outbox`: drafts, the owner's
  approval on the Outbox page, per-kind approval and rate limits, merge labels and PR approval
  guarded; phase 1 is built). Its senders today: `slack.message`, `slack.reply`,
  `github.pr_comment`, `github.label`, `github.pr_open`, `jira.comment`, `jira.transition`,
  `jira.create`, and `script` (actions `other`, `git.push`, `github.pr_open`, `github.pr_merge`).
  What this proposal needs from it:

| Need | Kind | Sender |
|---|---|---|
| An upstream issue | `upstream.issue` | **New** `github.issue_create` (or a `script` around `gh issue create` until then) |
| A PR from the scratch clone | `upstream.pr` | `script` with `action = "git.push"` to push the branch, then `github.pr_open` (both built) |
| A CI rerun (external CI) | `ci.rerun` | **New** `github.run_rerun` (or a `script` around `gh run rerun --failed`, `action = "other"`) |
| A SAIL relabel | `ci.relabel` | `github.label` (built). `SAIL` is in `merge_labels`, so the first use on each PR is always the owner's (outbox SPEC §6.6) |

  Which kinds exist and whether any is `auto` are the owner's choices (`orchestra_outbox/guide.md`);
  the Supervisor proposes and asks.
- **Closing the loop**: when the fixed upstream version is installed the override goes stale, the
  Supervisor asks for its removal through a ticket, and `system.changed` marks the era.

## 11. A likely first split: the pipeline manager

The flow keeper's gate and CI paragraphs are likely to be the first cluster heavy enough to split:
they wake often, read long logs, and need their own tools. As its own machine, the pipeline
manager **keeps CI and the gate flowing**. It works for both the local gate and external CI
(GitHub Actions; SAIL at work).

| Duty | Keeps true |
|---|---|
| Triage | Every failed check has a class (`infra`, `flaky`, `timeout`, `real`, `unknown`) with evidence |
| Retry | Only what can pass on a retry is retried, within a budget; never a real failure |
| Bisect | When the base breaks, the culprit commit is named and a bug ticket is asked of the Coordinator (D2: DONE is never reopened) |
| Flakes | A test that flakes 3 times in 7 days gets a quarantine ticket and an entry in `.orchestra/flakes.toml` |

**What the lift changes in the task system's gate** (orchestra-tasking today: one ticket per run,
blind reruns up to `[gate] rerun_failures`, a broken base pauses the pipeline, no bisection, no
quarantine):
- A new `[gate] verdicts` mode: on a failed spec the gate publishes `gate.stage_failed` and waits
  up to `verdict_timeout` for `ci.verdict` (`retry` | `reject` | `pause`). With no verdict it
  falls back to today's reruns, so the gate never depends on an agent. `rerun_failures` becomes
  the ceiling.
- A check run that lands nothing: `gate.check_requested` → `gate.checked`, specs at a commit, for
  bisection (also story-placement's "tests at a ref").
- Stays in the gate: merge, build, the stages, landing, the base check, pausing, recording `flaky`.
- For external CI, orchestra-bridges needs `github.branch.check_completed` (the PR tracker sees
  only PR checks, with no logs or reruns), plus a `ci` tool that reads a failed job's log, and the
  outbox kinds in §10.3.

Its events are `ci.failure.classified`, `ci.verdict`, `ci.bisect.started`, `ci.culprit.found` and
`ci.flake.recorded`. The `ci.` prefix keeps clear of the task system's `pipeline.*`. It would be
graded on `danroblewis/orchestra-e2e-sandbox` (private; no workflow yet): a pytest workflow, a
seeded flaky test, an infrastructure fault, and a scripted sequence of landings where one breaks
main. The grade is set against the known flake and culprit. Of all the duties here, its retry and
flake duties are the most rule-like, so they are the first candidates when programmatic
replacement starts.

## 12. Risks

| Risk | What happens | What we do |
|---|---|---|
| **Cost** | A Sonnet Supervisor woken by every stall, plus a review round, plus split machines; cost is not measured today | Usage series first (§14, A1); per-machine budgets; Haiku for narrow machines; ephemeral sessions; the model matrix (§8) |
| **Drift** | Duties accumulate and contradict; the prompt says one thing and the agent does another | The ledger; duty edits carry predictions and are judged; the grading suite after every self-edit; the rate limit on changes |
| **Permissions** | A machine that restarts machines and changes settings can loop or thrash | Only the Supervisor holds `setup` and `roles`; new machines get subsets; the event cause-chain limit; budgets |
| **An agent acting as the owner** | Issues, PRs, reruns and labels under the owner's name | All through the outbox; `auto` only when the owner says; `SAIL` is a merge label, first use always the owner's |
| **Nondeterminism** | The same stall diagnosed differently on two days | Every fix carries evidence, a prediction and the commit it ran under; grading measures consistency |
| **The central agent** | Expected and planned for: the Supervisor accrues duties until it is slow, expensive and the single point of failure | The load stock and its trigger (§7.1); the split tool; merge back when a split does not pay; a curator later takes growth off the Supervisor |
| **Self-modification gone wrong** | The Supervisor edits away its own guardrails or the owner's channel | The fixed core is in the plugin, not the project; the duty tools refuse edits outside `.orchestra/machines/` and removing core subscriptions; every change revertible |
| **Goodhart** | A fix that unblocks by dropping work or skipping checks | Predictions name side effects that must not happen; the harm column fails the run |
| **Fixers fighting** | After a split, the Supervisor and the new machine both act on one stock | Subscriptions move rather than copy; one machine per stock it steers (ghost proposal §5); the model's "two controllers on one stock" flag |

## 13. What stays deferred

Shadow, replacement, fallback and maintenance of programs (§2.2) are deferred until a split machine
has a duty whose tool sequences are stable and whose predictions keep passing. Then the
pipeline manager's retry and flake duties are the first.

## 14. Implementation steps

In order; each lands in the repository that owns the concept.

| # | Repository | Step |
|---|---|---|
| A1 | orchestra-agents | Usage and load series: tokens and dollars per machine; wake-ups queued, coalesced and their latency; turn length; the transcript instrument (tool co-use, sequence share) |
| A2 | orchestra-agents | `.orchestra/machines/<name>/`: `machine.toml`, duties, per-machine `model` and `harness`, `publishes` as the `emit_event` allowlist, `[review]` schedules; the spec lint; today's role and agent records still read |
| A3 | orchestra-agents | The Supervisor's spec in the project: the fixed core split from the built-in prompt; the starting duties written on first run; `add_duty`, `edit_duty`, `remove_duty`, `revert_change` with the commit-or-side-branch rule; the ledger; Sonnet by default |
| O1 | orchestra (this repository) | `orchestra.model.stalled` and `orchestra.machine.quiet` (domain-free, like G12's events), and the host's `orchestra.instrument.failing` |
| A4 | orchestra-agents | The flow-keeping duty: wake-ups, `read_transcript`, the prediction-per-fix rule in the duty text, the review round |
| A5 | orchestra-agents | The sample project, the chaos script, the graded suite (dummy in the unit tier, real model nightly), the model matrix |
| A6 | orchestra-agents | `split_machine` and `merge_machine`, the tool-subset check, the hand-off wiring; the growth-and-split scenario |
| A7 | orchestra-agents | The first real split in the sample: whatever cluster the load picks (likely gate and CI, §11) |
| T1 | orchestra-tasking | When the pipeline manager exists: `[gate] verdicts`, `gate.stage_failed`, `gate.check_requested` / `gate.checked` |
| B1 | orchestra-bridges | `github.branch.check_completed` for followed branches |
| X1 | orchestra-outbox | Senders `github.issue_create` and `github.run_rerun` (or the `script` stand-ins); the Supervisor's side of SPEC §7.2 (in orchestra-agents) |
| S1 | orchestra-e2e-sandbox | A workflow, a seeded flaky test, the faults, for the pipeline manager's grading |
| O2 | orchestra (this repository) | Project-local plugins and overrides (§10.1), Core page listing, rule 10's sentence |
| A8 | orchestra-agents | The upstream path: issue with patch and recorded events, PR from a scratch clone, both as outbox drafts |
| — | later | Shadow, replace, fallback, maintain (§2.2); a curator taking growth off the Supervisor |

## 15. Open questions for the owner

1. **The Supervisor's model.** Sonnet by default (proposed), with Opus for splits if Sonnet's
   fail grading, decided by the model matrix (§8)? Haiku for the narrow machines it creates?
2. **Autonomy.** May the Supervisor create machines and edit its own duties without asking, as
   reasoned commits you can revert (proposed)? Or should it ask before a split, but not before a
   duty edit?
3. **Self-edits with a dirty checkout.** Should duty changes go to a side branch the host reads
   (proposed), or wait until the base checkout is clean?
4. **Who writes patches.** The Supervisor directly (your wording), or through a ticket
   (orchestra-agents' SPEC §10 as written; recommended)? Is there an emergency path?
5. **New outbox kinds.** Which of these should be added, and with which approval: an upstream
   issue (a new `github.issue_create` sender), an upstream PR (`git.push` script plus
   `github.pr_open`), a CI rerun (a new `github.run_rerun`), and a SAIL relabel (`github.label`,
   first use per PR always yours)?
6. **The core events.** `orchestra.model.stalled`, `orchestra.machine.quiet` and
   `orchestra.instrument.failing` in Orchestra's core (proposed, as domain-free as G12's), or
   computed by the agents plugin from the model and the bus?
7. **The review round's cadence and budget.** Hourly while work is in flight (proposed), and a
   daily spend cap per machine?
8. **The split trigger's thresholds.** Utilisation 0.7, 8 duties or 12k tokens, and latency past a
   duty's deadline (all proposed)?
9. **The spec's place.** `.orchestra/machines/<name>/` replacing role and agent records over time
   (proposed), or the role record grown to carry the contract?
10. **Where reused programs go**, when replacement starts: orchestra-tasking (it knows the gate),
    a new plugin, or a library of reference machines in orchestra-agents?
11. **The gate waiting for a verdict.** Is a gate that holds a worktree up to two minutes for the
    pipeline manager's verdict acceptable under D17, given that the alternative loses the retry?
