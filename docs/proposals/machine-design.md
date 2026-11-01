# Machine design: the Supervisor declares, measures and drafts

Status: reviewed, 2026-11-01 (panel round 1, judge's verdict round 2); aligned to
intended-model.md round 2. Nothing built. Proposal 4 of
`design-backwards.md` §7, for the agents plugin (`~/orchestra-agents`). Written from
`design-backwards-notes.md` §9 and §13, the approved mockups (`mockups/README.md`, D1–D3,
E1–E3), D20 and D21. The core's side (the declared layer, its API, the pages) is proposal 2,
`intended-model.md`; §10 states the shapes this document assumes from it.

## 1. Purpose

The owner talks; the Supervisor declares, measures, drafts and refines; the pages show the results.

- **The owner talks only to the Supervisor**, in the chat they already have (`AGENTS.md` rule 9).
  The owner rejected every other interface: "These are terrible. I don't want any of them. I want
  you to extend the Event Map page and the System Dynamics page." No chat on a page, no wizard, no
  new page. The panels on the pages are read-only indicators of the declaration; the only page
  controls are expect, ignore, confirm, discard and the Universal | Programmatic switch (§2.4).
- **The Supervisor does the work.** It declares stocks, effects, targets and machines; finds ways
  to measure what was declared and starts recording at once; drafts machines and refines them while
  the owner talks; runs the refinement passes; records each machine's expected effect. "These
  configurations are complicated and annoying. I don't want to do them. I want the Supervisor to
  set up my environment."
- **The pages draw it.** The reply says where to look in a line or two; the detail is on the page.
- **Everything drawn is a hypothesis** (`design-backwards.md` §3). An element the owner named is
  *added by you* (origin owner), with the Supervisor's additions to it marked as guesses; one the
  Supervisor drafted or inferred unasked is *proposed by the Supervisor*. A machine stays
  unconfirmed until the owner confirms: "The user created one has precedence, but it's not real
  until the user confirms it."

**What the core holds.** D21 amends rules 2 and 7 when the integration step is built
(`design-backwards.md` §5); until then nothing here changes a core invariant. The core stores the
declarations' fields opaquely: it draws them and never interprets them. `universal` is a kind of
abstract machine, not "agent" under another name: a Universal declaration names no model, prompt
or tool. The prompts, the drafts of agents, the refinement passes and every tool below are the
agents plugin's (rule 1).

## 2. The tools

A new tool group, `design`, the Supervisor's alone (checked in the handler, like `setup`). Every
tool takes a `reason` (refused without one); records provenance automatically (the host attaches
the turn id and the owner's message that began the turn; an optional `quote` must be a substring of
that message, so "from your message: …" is never invented); writes only through P2's API and
`project.config_edit` (rule 10); and answers with the ids recorded and where they show. No tool
calls a model.

### 2.1 Where writes go

At work the base branch is protected, so nothing in this proposal commits to it by default:

| what | where, by default | on the owner's say-so |
|---|---|---|
| a measurement script | `~/.orchestrator/<key>/agents/instruments/<name>.sh` | the repository, through a pull request drafted in the outbox for the owner to approve |
| its `[[collect]]` / `[[scrape]]` / `[[sources]]` entry | `config_edit`, target `overlay` | target `repo`, in the same pull request |
| a confirmed Universal Machine's spec | `~/.orchestrator/<key>/agents/machines/<name>/`; the host loads specs from there as well as `.orchestra/machines/` | `.orchestra/machines/<name>/`, by pull request |
| a draft implementation | `~/.orchestrator/<key>/agents/drafts/<name>/` | — |

The script and its entry are written as one act and removed as one (`remove_entry` removes the
script with its entry). This amends, on purpose, and the commit that builds it says so:
orchestra-agents **AGENTS.md rule 10** ("new code is a worker's"): a measurement script of at most
100 lines is configuration the Supervisor writes; **SPEC §10** (today anything longer than a
one-liner goes through a ticket); **SPEC §7 and AGENTS.md rule 9**, which gain the
`instruments/`, `machines/` and `drafts/` state paths. Any other code is still a worker's: a script
that needs a change in the project (a test runner flag) is handed to the Coordinator
(`hand_to_coordinator`, which publishes `work.requested`; the Supervisor makes no tickets).

### 2.2 The Dynamics side (notes §13.1)

| tool | arguments | records | page |
|---|---|---|---|
| `declare_stock` | `name`, `description`, `unit?`, `near?`, `quote?`, `reason` | a declared stock | D1: the ghost; the Expected group, "no series yet". "Where you said it belongs" only when the `quote` names the place; otherwise "placed by the Supervisor" |
| `declare_effect` | as `declare_stock` | a declared effect (a measurable consequence nobody owns) | as a stock |
| `set_target` | `element`, `op` (`below`, `above`, `within`), `value`, `hi?`, `over`, `reason` | a target | met, missed or unknown on the element |
| `propose_measurements` | `element`, `options`: [{`label`, `kind` (`existing_series`, `script`, `scrape`, `source`, `counters`, `simulated`), `how`, `cost`, `caveat?`, `clearance`}], `reason` | the options, in order | D1's "How to measure it" |
| `add_instrument` | `element`, `option`, `name`, `kind` (`collect`, `scrape`, `source`), `script?`, `command?`, `url?`, `every`, `simulated?`, `change?`, `reason` | the instrument, recording into the draft namespace; the option marked recording | D1: "recording since 20:27 · instrument features.acceptance · 3 points", the sparkline, the script and its entry |
| `keep_instrument` | `name`, `reason` | the instrument out of the draft namespace into the store | the option "chosen"; discovery may now read it |
| `match` | `declared`, `discovered`, `reason` | a manual binding, origin `declared` | the declared stock drawn as the discovered one, "an assumption" |
| `mark_expected` / `ignore` | `element`, `on?`, `note?`, `reason` | the mark | D3's pin; the D2 row leaves the list |
| `rediscover` | `reason` | a discovery started (an observation, like the page's button) | a new version |

**How options are found.** `propose_measurements` only records; the finding is the Supervisor's
research in the same turn, in this order, stopping at three or four honest options:

1. **The store** (`list_metrics`, `read_series`): a series already recorded. Option
   `existing_series`; nothing is added, and discovery relates it on its own.
2. **The repository** (read-only): a report the project already produces. For tests, prefer
   Orchestra's `orchestra.instruments.test_reports` reading the JUnit report CI publishes for the
   base branch. **Never run a suite in the working tree as a collector**: a round has a 10 s
   default timeout, and the working tree is whatever branch the owner has checked out.
3. **What other plugins count** (`check_setup`, `list_metrics` by prefix): the task system's
   counters by label. Option `counters`, with its caveat (D1's c: "counts what was planned as a
   feature, not what works").
4. **Another store or a company system** (`check_sources`, `source_schema`, `infer_source`): a
   series in the company's Prometheus, Jenkins, Jira, GitHub at work.
5. **A simulated placeholder**, always last (owner: "they might add placeholder metrics, or
   simulated metrics, to make sure the rest of it works correctly").

Every option states its `cost`: how long a round takes, what it reads, and for a store its request
rate against that store's limit (`orchestra/sources/limits.py`).

**Company systems.** Before any option reads Jira, GitHub at work, a Prometheus, Jenkins or another
company system, `propose_measurements` checks the source's data class against what the Supervisor's
model may see (`docs/work-charter.md` §8). An option that is not cleared is recorded with
`clearance: needs approval` and nothing reads it; until data classes exist, every company source is
recorded so. Credentials are named only by environment variable (`bearer_env`), set in the overlay
and supplied out of band; no value is ever written, shown or asked for in the chat.

**`add_instrument`, step by step**: refuse if the script is over 100 lines or a line looks like a
secret; try it exactly as Orchestra would (`try_collector`), refusing with the trial's output if it
fails or prints nothing parseable; write the script and its entry (§2.1) with the draft flag; wait
for the first round (`read_instrument`, up to 120 s) and record the first points on the option, so
the sparkline is drawn before the owner writes again. A `source` option has no "recording since":
it is read in place at each discovery, and the option shows what the preview read.

**The draft namespace.** The owner's words, "it starts recording the metrics immediately", and
the rule that a measurement is never removed to quiet a signal, meet here. The option the
Supervisor picks first records at once, into a **draft namespace** that expires (24 h by default)
and that discovery does not read. It moves into the store when the owner keeps it
(`keep_instrument`, on the owner's word or their expect click). Options the owner did not choose
expire with their drafts, script and entry. A **simulated** instrument's entry carries
`simulated = true` (P2 §6.3): discovery reads its series like any other, every part fitted from
them is marked `simulated` in the saved version, a prediction verdict never counts one, and they
disappear when the instrument expires, once a real option records: a ramp is not a measurement, so
the never-remove rule does not protect it.

**The two cases the owner named.**

- *The series relates on its own.* "If the metrics that were added are related, they will show up
  in the System Dynamics model on their own. In that case, we don't need to do anything." The
  Supervisor binds nothing (rule 7). Once the instrument is kept and has points, it may start a
  discovery (`rediscover`), and on its next turn reads the model and discovery's "left out" list,
  saying in a line why a series was left out if it was. A count of passing tests is usually found
  as a level with a net flow, not with named inflows; the reply says so rather than promising
  flows.
- *Nobody measures it yet.* "The user needs to tell the Supervisor that and explain how we might
  instrument it, then the supervisor does its best and shows the results of the instrumentation
  scripts and the code." The Supervisor asks one question when the description is not enough,
  writes the script from what the owner said and what it read, tries it until it works, and
  records it. The reply names the files it read and the first value; the script, its entry and
  the points are in D1's drawer.

**Matching.** When discovery finds the measured quantity under its own name (D2: *acceptance tests
passing* while Features stays a ghost), the owner may say they are the same. `match` records a
manual binding with origin `declared`: drawn as an assumption until fitted (rules 6 and 7). It
never renames the discovered stock and never makes discovery find anything.

### 2.3 The Machines side (notes §13.2)

| tool | arguments | records | page |
|---|---|---|---|
| `declare_machine` | `name`, `kind`, the common fields, the kind's fields, `guesses`, `quote?`, `reason` | a proposed machine, origin owner when the owner named it | E1/E3: the dashed node, "unconfirmed", the panel filled; guesses tagged |
| `refine_machine` | `name`, `edits`, `quote?`, `reason` | each edit with its previous value | E2's "+ added just now", "− removed", "changed just now · was continuous" |
| `declare_event` | `type`, `purpose`, `reason` | a declared event type | the event node, its purpose |
| `declare_expected_effect` | `machine`, `expect` (SPEC's kinds, §2.5), `horizon`, `reason` | a draft prediction on the declaration | E1's "Expected effect" |
| `confirm` / `discard` | `element`, `reason` | declared, or discarded and kept in history | the outline solid, or the node gone |

**The fields.** Names follow the agents' pattern, `^[a-z][a-z0-9_]{1,40}$`; the title "Feature
Count Improver" becomes `feature_count_improver`, which is also its bus `source`.

- **Common**: `title`, `description`, `tags`; `managed` (`orchestra`: started and kept by
  `orchestra run` or the agents' host; `external`: runs elsewhere, known by its events or by the
  instruments attached to it); `engagement` (`ad hoc`, `continuous`, `scheduled` with `at`,
  `tz` and `missed`: `skip` or `run once`); `receives`; `emits`. `managed` and `engagement` are
  separate axes, so a nightly Jenkins job is `external`, `scheduled`.
- **Universal**: `invariants`, `steps` (numbered), `reads` (stocks and effects it may read; never
  one it produces). "A Universal Machine is not described in AI terms."
- **Programmatic**, by engagement: *ad hoc*: `command` or, for an external one, `trigger` (a
  remote call that starts it: a Jenkins job's URL), and the interface: `arguments`, `environment`,
  `stdin`, `exit`; *continuous*: `command` (a daemon), `protocol` (`http`, `graphql`, `grpc`,
  `other`), `send`, `receive` (push, or a poll with its call and interval, `getTasks()` every
  10 s); *external* adds `source`: the relayed actor whose events it is (`bot.jira`), never the
  bridge that relays them (rule 2, D19).

**`refine_machine`'s edits**: `add_receive`, `remove_receive`, `add_emit`, `remove_emit`,
`set_engagement`, `set_field`, `rewrite_steps`, `add_invariant`, `remove_invariant`, `add_read`,
`remove_read`, `set_kind`. All apply or none. On a confirmed machine they are recorded as a
proposed change the owner confirms or discards.

**Naming events.** Use an existing type whenever one has the purpose (`read_design`, `read_events`).
A new type goes in an existing family and gets a declared purpose. When no observed event has the
purpose (at work: a Jira transition, the company gate), the Supervisor declares the external
machine that would publish it, under the relayed actor's source, marked "not heard yet"; it never
invents an event type with no publisher. When the owner's words name an event differently, the
reply says which name it used and why.

**`read_design`** (group `observe`): P2's summary read: declared, proposed and observed elements,
each machine's fields and what was heard from it, each event type's publishers and listeners on
both layers, open differences, recent changes.

### 2.4 Confirm, discard and the person's request

The page's controls are of two kinds (P2 §6.2). **Observations** (expect, unexpect and ignore on a
discovered part; confirm and discard on a stock, effect or flow) are recorded by the core and
announced as `orchestra.intent.changed`; the Supervisor reads them and acts on any that need it
(`keep_instrument` after an expect). **Requests** (confirm and discard on a machine or a pending
change on one, and the Universal | Programmatic switch) are published as
`orchestra.intent.requested` with source `owner` (the person), never the core's; the core changes
nothing on the click. The Supervisor wakes on a request and calls `confirm`, `discard` or
`refine_machine` (`set_kind`) itself, with the request's id in the provenance. "Confirm it" in the
chat takes the same path. What confirm then does:

- *Universal*: the draft implementation moves to the state directory's `machines/` (§2.1); the
  Supervisor creates its role (`create_role`) and then its agent (`create_agent`, with its schedule
  or wake-ups); it publishes the expected effect (§2.5).
- *Programmatic, managed by Orchestra*: the program is a worker's to write unless it exists; when
  it does, `set_machine` adds the `[[machines]]` entry (overlay by default).
- *External*: nothing runs; the declaration waits to be heard or measured.

Until confirm nothing runs and nothing is published: an unconfirmed machine costs nothing.

### 2.5 Expected effect as a prediction

Written in SPEC's `expect` kinds (`orchestra/sd/predictions.py`): a flow's `factor`, a flow that
`appears` (`from`, `to`), a stock `below` or `above`. **Rates, not cumulative stocks**: the Feature
Count Improver expects the DONE inflow at `factor 1.2` and the gate's rejection flow at `factor
0.8`, and a flow that `appears` from outside into the coordinator's queue, counted by its own
`work.improvement_proposed` events (`from: null`, `to:` the coordinator's queue stock). A stock with no series yet (Features before it
is matched) is not predicted on: the draft waits, and the panel says "waits for a series".

At confirm, the Supervisor pre-allocates the id of the `system.changed` event that will announce
the machine's start and puts it in the prediction as `data.change`; it publishes
`orchestra.prediction.made` as `supervisor` through `events.py` (also when the host runs the call),
subject `machine:<name>`; when the agent's first turn starts it publishes that `system.changed`,
which always begins an era (besides `[discovery] eras_from`). The **horizon** is sized from the
runs needed to see an effect (a daily machine: at least three runs, so three days) and discovery's
minimum points for an era, whichever is longer. Another era beginning first (any `config.changed`
does) judges it at once as `interrupted`, with what the rules would say from that as `partial`; the
Supervisor then commits a fresh prediction for the remainder, with the new change.

### 2.6 The worked example: the Feature Count Improver

The owner's scenario on the agents' demo, one chat turn per row.

| # | the owner says | the Supervisor calls | the page shows |
|---|---|---|---|
| 1 | "I want a feedback loop where once per day an agent runs and tries to improve how many features get delivered per day. I think we need to start tracking features … I'm going to create a Features stock." | `declare_stock` (Features; placed by the Supervisor beside DONE); `list_metrics`, reads `tests/acceptance` and the CI configuration; `propose_measurements` (a passing acceptance tests on main from CI's JUnit report, b e2e tests the same way, c tickets labelled `feature` reaching DONE, d simulated ramp); `add_instrument` (a, `features.acceptance`, every 15 min) | D1: the ghost; the drawer, a recording into the draft |
| 2 | "Keep the acceptance tests one." Later, after discovery: "Yes, that's Features." | `keep_instrument`; `rediscover`; then `match` (Features ↔ acceptance tests passing) or `mark_expected` | D2, then D3 |
| 3 | "Create a new Universal Machine called Feature Count Improver." | `read_design`, `read_events`, `read_model`; `declare_machine` (`feature_count_improver`, origin owner; scheduled daily from turn 1's "once per day", time a guess; receives `session.settled`, `task.reported`, guesses; emits `work.improvement_proposed`, new, to the coordinator; reads Features and acceptance tests passing; five steps; three invariants); `declare_expected_effect` | E1 |
| 4 | "I think the Feature Count Improver would watch the ticket queue for DONE and REJECTED tickets, and the Merge Gate … then maybe communicate those ideas to the Coordinator." | `refine_machine`, six edits: add `changes.requested`, `gate.rejected`, `gate.landed`; remove `session.settled`, `task.reported`; `rewrite_steps` | E2's receives |
| 5 | "I see this has a lot of high-throughput event triggers, maybe we should make this a scheduled task for 12am every day." | `refine_machine`: `set_engagement` at 00:00, `tz` the owner's; `rewrite_steps` | E2's engagement |
| 6 | "Confirm it." (or the click) | `confirm`; `create_role`, `create_agent` (at 00:00, Haiku); the prediction | the outline solid; "declared · not heard yet" |

Each reply is two or three lines: what it did, with ids, and where to look. In turn 3 it states the
cost as drafted and that `work.improvement_proposed` has no listener yet (the refinement pass will
propose the coordinator; `work.requested` is the Supervisor's own hand-off and is not reused). In
turn 4 it says it used `changes.requested` for "REJECTED tickets" and `gate.landed` for "DONE"
because those are what the reviewer and the gate already publish.

**Where this differs from the frames.** D1's "as the Supervisor wrote them on DEMO-35" becomes
"written by the Supervisor · <state path>"; "waiting on DEMO-35" stays only for a script handed to
the Coordinator. D1's chosen option is "recording · draft" until kept. E1 shows the improver
continuous with `work.requested`; here it is scheduled from turn 1 and emits its own type, so E2's
"was continuous" reads "was daily, time a guess".

## 3. The refinement passes

The owner: "An AI pass should probably [run] a few times, try to make sure no events have
publishers but no subscribers, make sure the purposes of events aren't duplicated, make sure that
events aren't excessively deduplicated and serving multiple distinct purposes, other refinement
things."

A Supervisor duty, `refine_map`, in its spec beside `keep_flow` (D20). It wakes on the review round
when the map changed since its last pass, and on the owner's confirm or discard request (`orchestra.intent.requested`). A round
runs at most `design_passes` passes (default 3), each reading the map with the previous pass's
findings on it, and stops when a pass finds nothing new. **It proposes, never declares**: the
round's findings are batched into one proposal, each with its reason, for the owner to confirm or
discard. The checks:

1. **Emitted, never heard**: proposes a listener among the declared machines whose steps use it, or
   removing the emit.
2. **Heard, never emitted**: proposes the machine that should emit it, or an external machine under
   the relayed actor's source (§2.3); never an event type with no publisher.
3. **One purpose, two names**: proposes keeping the one already observed on the bus.
4. **One name, several purposes**: an event whose listeners each act on a different part of it, or
   whose purpose needs "or"; proposes a split into a family.
5. **No prediction**: "if we can't point to any prediction then we probably don't want the Machine
   in there at all." Proposes one, or asks.
6. **Engagement against load**: a machine woken by a busy event; proposes a schedule, as the owner
   did in turn 5.
7. **Loose ends**: a declared stock with no instrument; a target with no series; a draft about to
   expire unkept; an expected element absent for three versions.

The passes spend `review_usd_per_day`. D20's signals decide whether this duty becomes a machine of
its own (`design-backwards.md` §4).

## 4. Drafting a Universal Machine

**The abstract description** (what the core stores; E1's panel), from the name and the owner's
words, after reading the map, the model and the neighbours' descriptions: a **title** and a
**description** of what it achieves in the work's terms; **invariants**, each a line a reviewer can
check ("never changes code itself; it proposes work"); numbered **steps** naming each event where it
is used; **receives**, **emits** and **reads** (§2.3), every guess marked; at least one **expected
effect**, or the reply says why none can be named.

**The implementation** (the plugin's alone), drafted in `drafts/<name>/` (§2.1), so a draft is "not
official" and a discard leaves nothing: `machine.toml` (model `haiku`, D20's default for narrow
machines; engagement and schedule; wake-ups from `receives`; the fewest tool groups the steps
need), `role.md` (the description, invariants and steps as instructions), and an emit tool
restricted to its declared `emits`. Each refinement redrafts it. Refining its operation further is
"a long conversation with the Supervisor"; the page shows only the result.

**Towards a Programmatic Machine** (the ladder's rungs 7–8; `agent-first-machines.md`; the
ghost-machine path, `environment-and-ghost-machines.md` §3). When the agent's transcripts repeat
(the review round reads them), the Supervisor proposes `set_kind` to Programmatic with the same
events, the Universal description kept as the program's specification. The program is written on
a ticket; the agent stays as a second instance, `feature_count_improver/fixer` (as the coordinator
is `agent ×1, program ×1` today), woken only for cases the program hands it. The fixer's turns a day
are a series the model sees, and each case it handles is a candidate for the program.

## 5. Prompts and the guide

- **`prompts/design.md`** (new, after `operator.md`): the states and origins; what each page draws
  after each tool; the order of work (declare, measure at once, then machines); where options come
  from and the clearance check; naming events; drafting; confirm and discard are the owner's; the
  cost line for every drafted machine.
- **`supervisor.md`**: designing the system is yours; the pages show it; the reply says where to
  look and never repeats the panel.
- **`supervisor_core.md`**, under "What never changes": **never ask the owner to edit a file, write
  configuration, or paste a snippet; change it with your tools or say what you cannot do.** The
  owner: "If TOML is the interface for setting this up, it will be a miserable experience."
- **`guide.md`**, "Designing the system": the `design` tools, the state paths, the draft namespace
  and its expiry, `[agents] design_passes`, and the passes' budget. The field tables of §2.3 are a
  reference section read on demand.

## 6. Costs and models

The `design` tools call no model. Drafted Universal Machines default to Haiku; an unconfirmed one
never runs; every drafted machine's reply states its turns a day and their cost. The passes are
capped by `design_passes` and `review_usd_per_day`. The live proof (A3) runs the Supervisor on
**Haiku** with a narrowed tool set (§7, test 19), falling back to Sonnet if Haiku fails, within
**$10** (inside the run's $30, goal decision 4); the test stops at the cap and says so.

## 7. Acceptance tests

With the fake Claude (`tests/e2e/fake_claude.py`) unless marked otherwise.

1. Each `design` tool refuses a missing reason, a `quote` not in the owner's message, and any
   caller but the Supervisor; each answer names the ids recorded.
2. `declare_stock` records origin owner, the quote and the turn; "where you said it belongs" only
   when the quote names the place.
3. **Against a real empty Orchestra** (`scripts/acceptance_target.py`, with the agents plugin): in
   one Supervisor turn, `declare_stock` then `add_instrument` leaves the script at the state path,
   its entry in the overlay, at least one stored point in the draft namespace, and no commit on the
   base branch. *(notes §13.4, line 1)*
4. Recording or choosing an option changes no other element, no model version and no other
   instrument. *(§13.4, line 2)*
5. `add_instrument` refuses a script over 100 lines, a secret-looking line, and a failing trial
   (with its output); nothing is written.
6. For a quantity nobody measures, the option carries the script's text, its state path and its
   first points. *(§13.4, line 3)*
7. An existing related series gets an `existing_series` option, no instrument and no binding.
   *(§13.4, line 4)*
8. A simulated instrument's entry carries `simulated = true`; every part discovery fits from its
   series is marked `simulated` in the saved version and is not counted in a prediction verdict;
   once a real option records, the entry is removed and the next version has no simulated part.
   *(§13.4, line 7)*
9. An unkept draft expires with its script and entry; `keep_instrument` moves it into the store,
   and discovery reads it after; a simulated draft that expires leaves no part in the next
   version.
10. An option reading a company system not cleared for the model is recorded `needs approval` and
    nothing reads it; no credential value appears in any tool answer, file or transcript.
11. `match` records a binding with origin `declared`; the discovered stock keeps its name.
12. `declare_machine` records every field of §2.3 for each kind, `managed` and engagement, with
    guesses marked; a Universal declaration contains no model, prompt or tool name; a title becomes
    a valid name. *(§13.4, lines 8 and 12)*
13. `refine_machine` with six edits records six changes with previous values; a failing edit
    applies none; on a confirmed machine it records a proposal. *(§13.4, lines 10 and 11)*
14. Expected effect: written in SPEC's kinds; no edit on a stock without a series; published only at
    confirm, as `supervisor`, subject `machine:<name>`, `data.change` equal to the id of the
    `system.changed` published at the agent's first turn; horizon at least three runs; an
    interrupting era leads to a fresh prediction. *(§13.4, line 13)*
15. An `orchestra.intent.requested` confirm from `owner` wakes the Supervisor, which calls `confirm`, creates the role, then
    the agent, with its spec at the state path and nothing committed; discard leaves no file
    anywhere but the history.
16. A refinement round over a map with an unheard emit, a duplicated purpose and an overloaded event
    produces one proposal with three findings and declares nothing; a second pass adds nothing; the
    round stops at `design_passes`.
17. No prompt, guide or reply in the scripted runs contains "edit orchestra.toml", "add this to",
    "paste", "put this in", "run this command" or a fenced TOML block addressed to the owner; asked
    "what do I put in orchestra.toml?", the Supervisor makes the change with a tool. *(§13.4, line
    14, the agent's half)*
18. **The scenario, fake Claude**: §2.6's six turns on the agents' demo with `--dummy` machines and
    fixtures with seeded model history; P2's API then answers the D1, D2, D3 and E2 shapes of
    `mockups/fixtures/`. Run again with `[agents] tools_via = "bash"`.
19. **The scenario, live (A3)**: turns 1, 3, 4 and 5 to a Supervisor on Haiku (Sonnet on failure)
    with only the `design` tools, `list_metrics`, `read_series`, `read_model`, `read_events` and
    `read_design`. Passes on P2's API: Features declared with at least one point; the improver's
    receives are `changes.requested`, `gate.rejected`, `gate.landed` after turn 4 and its engagement
    scheduled at 00:00 after turn 5; its expected effect present. Tool-call errors are reported;
    transcripts saved under the state directory; screenshots of D1 and E2 kept as evidence; cost
    under $10.

## 8. What this does not do

No flows are declared on a machine's behalf: the owner left it open ("I don't know if we would want
to put the flows in there first … or if we want to associate them later"), so a predicted flow is an
expected effect, judged later, and the association stays inferred (rule 6). No machine is split or
merged (D20's next phase). No workflow is declared (goal task W7).

## 9. Open questions

1. **The draft's expiry.** 24 h is a guess: long enough for the owner to look the next day.
2. **Data classes** do not exist yet, so every company source is "needs approval" until the owner
   says what each model may see.
3. **The fixer's place**: a second instance of the same machine (this proposal) or a machine of its
   own.

## 10. Needs from P2

Read against P2's draft of 2026-11-01 (round 1); each line is the shape assumed here.

1. **The API**: `project.intended.apply(ops, provenance)` with provenance `{author, via, source,
   turn, message, quote}` and `guessed` fields per op; `design()` for `read_design`.
2. **Instrument flags**: an instrument option or entry with `draft` (series kept in a draft
   namespace discovery does not read, with an expiry) and a `keep` that moves a draft into the
   store (P2 round 2 has no draft namespace yet); `simulated = true` as P2 §6.3 defines it. Also: a `[[collect]]`
   command may name a script in the state directory.
3. **The person's request event** for page controls: assumed type `orchestra.intent.requested`,
   source `owner`, data `{control, part, id, change, from}`, for confirm and discard on a machine
   and the kind switch; the core records nothing on such a click. Observations (expect, ignore)
   are recorded and announced as `orchestra.intent.changed`. P2 states the rule 3 exception and
   the rule 9 wording.
4. **Match** as `link {id, found_as}` recorded as a manual binding with origin `declared`, drawn as
   an assumption; never a rename.
5. **Change records with the previous value and the reason**, per edit (E2's "was continuous").
6. **The machine schema**: `kind` `universal` | `programmatic`; `managed` `orchestra` | `external`;
   `engagement` with `at`, `tz`, `missed`; `trigger` for an external ad hoc machine; ids in the
   agents' name pattern (P2's examples use `feature-count-improver`).
7. **Predictions on a declared machine**: `set_expected_effect` and `record_prediction`; the panel's
   "waits for a series" for an edit on an unmatched stock.
8. **The two origin shades** (added by you, proposed by the Supervisor) and guess tags.
9. **Measurement options** with `cost`, `clearance` and the draft state, via `record_measurement`.
