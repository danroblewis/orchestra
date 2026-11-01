# Machine design: the Supervisor declares, measures and drafts

Status: draft for review, 2026-11-01. Nothing built. Proposal 4 of `design-backwards.md` §7, for
the agents plugin (`~/orchestra-agents`). Written from `design-backwards-notes.md` §9 and §13, the
approved mockups (`mockups/README.md`, frames D1–D3 and E1–E3), D20 and D21. The core's side (the
declared layer, its states, its API and the pages) is proposal 2, `intended-model.md`, written at
the same time; this document is written against the shapes in the notes and the goal document,
and §9 lists what it needs from it.

## 1. Purpose

The owner talks; the Supervisor declares, measures, drafts and refines; the pages show the results.

- **The owner talks only to the Supervisor**, in the chat they already have (`AGENTS.md` rule 9).
  The owner rejected every other interface: "These are terrible. I don't want any of them. I want
  you to extend the Event Map page and the System Dynamics page." No chat on a page, no wizard, no
  new page.
- **The Supervisor does the work.** It declares stocks, effects, targets and machines in the
  core's declared layer; finds ways to measure what was declared and starts recording at once;
  drafts machines from a name and refines them while the owner talks; runs the refinement passes;
  records each machine's expected effect as a prediction. "These configurations are complicated
  and annoying. I don't want to do them. I want the Supervisor to set up my environment."
- **The pages draw it.** The Dynamics page shows a declared stock as a ghost with the ways to
  measure it (D1), the diff against the last version (D2), the expected pin (D3); the Machines page
  shows a drafted machine highlighted with its details (E1), the live diff as it is refined (E2),
  the Programmatic forms (E3). The Supervisor's reply says where to look, in a line or two; the
  detail is on the page.
- **Everything the Supervisor draws is a hypothesis** (`design-backwards.md` §3). An element the
  owner asked for by name is *added by you*; one the Supervisor drafted or inferred is *proposed by
  the Supervisor*. Both are unconfirmed until the owner confirms: "The user created one has
  precedence, but it's not real until the user confirms it."

Nothing here goes into Orchestra's core: the tools, the prompts, the drafts of agents and the
refinement passes are the agents plugin's (rule 1). The core keeps only the declarations, in the
domain-free shape P2 defines. A Universal Machine's declaration names no model and no prompt;
those live in the plugin's machine spec (§4).

## 2. The tools

A new tool group, `design`, the Supervisor's alone (checked in the handler, like `setup`; not a
group a custom role may be granted). Every tool:

- takes a `reason` (a sentence) and is refused without one;
- records provenance automatically: the host attaches the Supervisor's turn id and the owner's
  message that began the turn; the tool's optional `quote` must be a substring of that message
  (checked), so "from your message: …" on the page is never invented;
- writes only through the core's declaration API (P2) and `project.config_edit` (rule 10); it
  never opens `orchestra.toml`, the overlay or the model store;
- answers with what it recorded (ids) and where it shows ("Dynamics: Features, ghost beside DONE").

A tool call is a change on the page within a second (the page polls or listens; P2). No model call
happens inside a tool.

### 2.1 The Dynamics side (notes §13.1)

| tool | arguments | what it records | what the page shows |
|---|---|---|---|
| `declare_stock` | `name`, `description`, `unit?`, `beside?` (a discovered stock it belongs near, "where you said it belongs"), `quote?`, `reason` | a declared stock, origin owner when the owner named it, else Supervisor | D1: the ghost, "expected · declared by you · 2 min ago"; the Stocks table's Expected group, "no series yet" |
| `declare_effect` | as `declare_stock` | a declared effect (a measurable consequence nobody owns: latency, review backlog age) | as a stock, in the Effects group |
| `set_target` | `element`, one of `below`/`above`/`equals` with a `value`, `within?` (a window: "a first review under a day"), `reason` | a target on a declared or discovered stock or effect | the target line on the element; missed targets in the Changes panel |
| `propose_measurements` | `element`, `options`: list of {`label`, `kind` (`existing_series`, `script`, `scrape`, `source`, `counters`, `simulated`), `how` (one sentence), `series?`, `command?`, `url?`, `caveat?`}, `reason` | the options, in order, on the element (decision 2 of the goal: the plugin records, the core shows) | D1's "How to measure it": a, b, c, d with their kind badges and caveats |
| `add_instrument` | `element`, `option`, `name`, `kind` (`collect`, `scrape`, `source`), `script?` (its text), `path?` (default `.orchestra/instruments/<name>.sh`), `command?`, `url?`, `every`, `via` (`direct` or `ticket`), `simulated?`, `change?`, `reason` | the instrument, written and declared; the option marked chosen with the instrument's name, the script's path and commit | D1: "chosen", "recording since 20:27 · instrument features.acceptance · 3 points", the sparkline, the script and its `[[collect]]` entry |
| `mark_expected` | `element` (a discovered stock or flow), `on`, `note?`, `reason` | the expected mark (always drawn; a ghost when absent) | D3: the switch on, the gold pin; a ghost when a later version lacks it |
| `ignore` | `element`, `reason` | the suggested change marked seen and not wanted; it stays readable, never deleted ("We won't dismiss them entirely") | D2: the row leaves "+ stock" for the ignored list |

**How `propose_measurements` finds options.** The tool only records; the finding is the
Supervisor's research in the same turn, with tools it already has, in this order, stopping when it
has three or four honest options:

1. **The project's own store** (`list_metrics`, `read_series`): a series already recorded that
   counts the thing. If there is one, the option is `existing_series` and nothing needs to be
   added: discovery will relate it on its own (the self-association case, below).
2. **The repository** (its shell, read-only: `git ls-files`, the test tree, the build files, CI
   configuration): tests whose passing count the thing (acceptance, e2e, a JUnit or xUnit report),
   a build tool that can list it, a file that enumerates it. The option is a `script` that runs the
   tool and prints a count. Orchestra's ready-made `orchestra.instruments.test_reports` is
   preferred over a new script when it fits.
3. **What other plugins already count** (`check_setup`, `list_metrics` by prefix): the task
   system's counters by label, a bridge's Jira or GitHub series. The option is `counters`, with its
   caveat said plainly (D1's c: "counts what was planned as a feature, not what works").
4. **Another store** (`check_sources`, `source_schema`, `infer_source`, `find_balance`): a series
   in the company's Prometheus. The option is `source`.
5. **A simulated placeholder**, always last: a script that prints a slow ramp, so the rest of the
   loop can be exercised before the real measurement exists (owner: "they might add placeholder
   metrics, or simulated metrics, to make sure the rest of it works correctly"). Its series
   carries the label `simulated="true"` (P2 settles the mark), and the pages say so wherever it is
   drawn.

**`add_instrument`, step by step.** It is `try_collector`, the write, `set_collector` and
`read_instrument` made one act, so the owner's "it starts recording the metrics immediately to our
metrics database" is one tool call:

1. Try the command exactly as Orchestra would (`collect.round`); refuse with the trial's output if
   it fails, prints nothing parseable, or a line looks like a secret.
2. **`via: direct`** (the default): write the script under `.orchestra/instruments/` and commit it
   alone, with the reason, as the spec tools commit `.orchestra/machines/` (on the base branch when
   the checkout is on it and clean; otherwise written and left uncommitted, and the answer says
   so). **`via: ticket`**: when the script needs anything outside `.orchestra/instruments/` (a test
   runner flag, a change to the project's code), it is handed to the Coordinator as a ticket, and
   recording starts when it lands; the option shows "waiting on DEMO-35".
3. Declare the entry through `project.config_edit` (`[[collect]]`, `[[scrape]]`, or `[[sources]]`
   via the existing source checks), target `repo`, committed with the reason; the collector starts
   within seconds (SPEC §5.2).
4. Wait for the first round (`read_instrument`, up to 120 s) and record the first points on the
   option, so the drawer's sparkline is drawn before the owner writes again.

This amends orchestra-agents SPEC §10 on purpose: today "anything longer [than a one-liner] is a
script, which is code" and goes through a ticket. A **measurement script under
`.orchestra/instruments/`** becomes configuration the Supervisor writes, like its own spec, because
the owner wants recording in the same turn and "the Supervisor writes everything" (D21). The
guardrails: the trial must pass first, the script is at most 100 lines, no secrets, one commit
alone with its reason that the owner can revert, and the page shows the whole script. Code
anywhere else in the repository is still a worker's.

**The two cases the owner named.**

- *The series relates on its own.* "If the metrics that were added are related, they will show up
  in the System Dynamics model on their own. In that case, we don't need to do anything." The
  Supervisor binds nothing (rule 7: stocks are discovered). It says discovery will find it on its
  next run; on its next turn it reads the model (`read_model`, and discovery's "left out" list),
  and if the series was left out, says why in a line (too few points yet, no counter balances it).
- *Nobody measures it yet.* "The user needs to tell the Supervisor that and explain how we might
  instrument it, then the supervisor does its best and shows the results of the instrumentation
  scripts and the code." The Supervisor asks one question when the description is not enough,
  writes the script from what the owner said and what it read in the repository, tries it until it
  works, and records it with `add_instrument`. Its reply names the files it read and the first
  value; the script, its entry and the points are on the page (D1's drawer).

Choosing another option later is another `add_instrument`; the earlier instrument keeps recording
until the owner says to remove it (`remove_entry`), because a measurement is never removed to make
a signal go away (the fixed core).

### 2.2 The Machines side (notes §13.2)

| tool | arguments | what it records | what the page shows |
|---|---|---|---|
| `declare_machine` | `name`, `kind` (`universal`, `programmatic`), the common fields, the kind's fields (below), `origin` (`owner`, `supervisor`), `guesses` (the fields the Supervisor guessed), `quote?`, `reason` | a declared machine, unconfirmed, with every field | E1/E3: the dashed node, "unconfirmed", the details panel filled; its card first in the grid |
| `refine_machine` | `name`, `edits`: list of ops, `quote?`, `reason` | each edit as its own change, with its time and turn | E2: "+ added just now", "− removed", "changed just now", "rewritten just now"; links appear and fade without a reload |
| `declare_event` | `type`, `purpose` (one sentence), `family?`, `reason` | a declared event type with its purpose | the event node; the purpose in its tooltip |
| `declare_expected_effect` | `machine`, `effects`: list of {`element` (a stock, flow or effect, or a flow not yet seen as {from, to}), `direction` (`up`, `down`, `appears`, `unchanged`), `factor?`}, `horizon`, `reason` | the expected effect on the declaration; published as `orchestra.prediction.made` at confirm | E1's "Expected effect": Features ↑, DONE tickets ↑, gate rejections ↓, each linked to the Dynamics page; on Dynamics, drawn as expected changes |
| `confirm` | `element` (any unconfirmed element or proposal), `reason` | declared; for a machine, its implementation started (below) | the dashed outline and the tag go; the card reads as declared and unheard until it publishes |
| `discard` | `element`, `reason` | discarded, kept readable in the history | the node and its links leave the map |

**The common fields** (every kind): `title`, `description`, `tags`, `engagement`: `ad hoc` (woken
by an event or an offer), `continuous`, `scheduled` with a `schedule` ("daily at 00:00"), and for a
Programmatic Machine `external`.

**A Universal Machine's fields**: `invariants` (rules about the work), `steps` (the sequence of
operations, numbered), `receives` (event types, each with who it is from when known), `emits`
(event types, each with who it is for), `reads` (declared or discovered stocks and effects it may
read; never one it produces). Nothing in AI terms: "A Universal Machine is not described in AI
terms, it is described as an abstract machine with no clear implementation, just an interface for
what it is able to use."

**A Programmatic Machine's fields**, by mode, as E3 draws them:

| mode | fields |
|---|---|
| ad hoc | `command`; its invocation interface: `arguments` (each name, meaning, default), `environment` (each name, meaning, value when fixed), `stdin` (what it is, an example), `exit` (code → meaning) |
| continuous | `command`, run as a daemon; `protocol` (`http`, `graphql`, `grpc`, `other`); `send` (how it publishes, e.g. `POST /events`); `receive` (push, or poll with the call and its interval, e.g. `getTasks()` every 10 s) |
| external | no command; not managed by `orchestra run`; `source` (the name it publishes under, or the bridge that relays it); known only by its events or by the instruments attached to it (P5) |

**`refine_machine`'s edits**: `add_receive`, `remove_receive`, `add_emit`, `remove_emit`,
`set_engagement`, `set_field` (title, description, tags, a Programmatic field), `rewrite_steps`,
`add_invariant`, `remove_invariant`, `add_read`, `remove_read`, `set_kind`. They apply together or
not at all. On an unconfirmed machine they change the draft. On a declared (confirmed) one they are
recorded as a proposed change, which the owner confirms or discards like any other.

**Naming events.** When the Supervisor adds a receive or an emit it uses an existing event type
whenever one has the purpose, read from the map (`read_design`, below) and the bus (`read_events`):
the coordinator already listens for `work.requested`, so the Feature Count Improver emits that,
not a new `send_to_coordinator`. A new type goes in an existing family (`gate.*`, `work.*`) and
gets a declared purpose. When the owner's words name an event that differs from the existing one,
the reply says which name it used and why, in a line.

**`read_design`** (group `observe`): the intended model as the Supervisor needs it, in the
summary-first shape of the model tools: declared, proposed and observed elements, each machine's
fields and what was heard from it, each event type's declared and observed publishers and
listeners, open differences, recent changes. It reads through P2's API.

**What confirm does to a machine.** The page's confirm button is a declaration of observation
(goal decision 1); a click is recorded by the core and reaches the Supervisor as an event, which
wakes it; the owner can also say "confirm it". Either way the Supervisor then acts, because only
it changes the system:

- *Universal*: the drafted implementation (§4) is committed to `.orchestra/machines/<name>/`, the
  agent created (`create_agent` with its schedule or wake-ups), and the expected effect published
  as `orchestra.prediction.made` from the Supervisor, subject `machine:<name>`. When the agent's
  first turn starts, the Supervisor announces the change (`announce_change`), and the prediction is
  judged from then.
- *Programmatic, ad hoc or continuous*: the program is a worker's to write, through a ticket, unless
  it exists; when it does, `set_machine` adds the `[[machines]]` entry (E3: "Confirm adds it under
  `[[machines]]` through the Supervisor").
- *External*: nothing runs; the declaration waits to be heard or measured.

Until confirm, nothing runs and nothing is published: an unconfirmed machine costs nothing.

### 2.3 The worked example: the Feature Count Improver, message by message

The owner's scenario on the agents' demo. Each row is one chat turn.

| # | the owner says | the Supervisor calls | what is recorded | what the page shows |
|---|---|---|---|---|
| 1 | "I want a feedback loop where once per day an agent runs and tries to improve how many features get delivered per day. I think we need to start tracking features … I'm going to create a Features stock." | `declare_stock` (Features, beside DONE); `list_metrics` (nothing counts features); reads `tests/acceptance`, `tests/e2e`, the task system's counters; `propose_measurements` (a passing acceptance tests on main, b e2e tests, c tickets labelled `feature` reaching DONE, d simulated ramp); `add_instrument` (option a, `features.acceptance`, every 15 min, direct) | the declared stock, origin owner, with the quote; four options; a committed script and `[[collect]]` entry; the first point | D1: the ghost beside DONE; the drawer with the four options, a chosen and recording, the script and entry |
| 2 | (later, after discovery found the series as *acceptance tests passing*) "Yes, keep that one." | `mark_expected` (acceptance tests passing) | the expected mark | D2 then D3: the new stock with its pin; Features still a ghost, "waiting for a flow" |
| 3 | "Create a new Universal Machine called Feature Count Improver." | `read_design`, `read_events`, `read_model`; `declare_machine` (universal; receives `session.settled`, `task.reported`, both guesses; emits `work.requested` to the coordinator; reads Features and acceptance tests passing; five steps; three invariants; continuous; origin supervisor); `declare_expected_effect` (Features ↑, DONE ↑, gate rejections ↓, horizon 7 days) | the draft, every field, guesses marked; the expected effect | E1: the node highlighted, one-hop machines at .45, the rest shadowed; the panel filled |
| 4 | "I think the Feature Count Improver would watch the ticket queue for DONE and REJECTED tickets, and the Merge Gate … come up with ideas to remove those problems, then maybe communicate those ideas to the Coordinator." | `refine_machine`: `add_receive` `changes.requested`, `gate.rejected`, `gate.landed`; `remove_receive` `session.settled`, `task.reported`; `rewrite_steps` | five changes, each timed, with the quote | E2's receives: three "+ added just now", two struck through; new links green, removed ones fading |
| 5 | "I see this has a lot of high-throughput event triggers, maybe we should make this a scheduled task for 12am every day." | `refine_machine`: `set_engagement` scheduled, daily at 00:00; `rewrite_steps` (read the day's tickets and gate results at 00:00) | two changes | E2: "scheduled · daily at 00:00 · changed just now"; the node reads "scheduled · daily" |
| 6 | "Confirm it." (or the confirm click) | `confirm`; the implementation committed; `create_agent` (at 00:00, Haiku); `orchestra.prediction.made` | declared; the spec's commit; the prediction's id | the outline solid; the card "declared · not heard yet" |

The reply to each turn is two or three lines: what it did, with ids, and where to look ("the
Features drawer on Dynamics", "the Feature Count Improver on Machines"). In turn 4 it says that it
used `changes.requested` for "REJECTED tickets" and `gate.landed` for "DONE" because those are the
events the reviewer and the gate already publish. In turn 3 it says, unasked, what the machine would
cost as drafted (a turn on every settled session, a few dollars a day) — the owner's own objection
in turn 5 is the kind it should raise first.

## 3. The refinement passes

The owner: "An AI pass should probably [run] a few times, try to make sure no events have
publishers but no subscribers, make sure the purposes of events aren't duplicated, make sure that
events aren't excessively deduplicated and serving multiple distinct purposes, other refinement
things."

A Supervisor duty, `refine_map`, in its spec beside `keep_flow` (D20's mechanism). It wakes after a
run of design changes settles (no `design` tool call for five minutes) and on the review round when
the map changed since the last pass. Each round runs **at most three passes**; each pass reads the
map with the previous pass's proposals on it, and the round stops early when a pass proposes
nothing new. **It proposes, never declares**: every finding becomes a proposed change (origin
Supervisor, the darker shade), with the finding as its reason, for the owner to confirm or discard.

The checks, in the order they run:

1. **Emitted, never heard**: an event type with a declared or observed publisher and no listener.
   Proposes a listener among the declared machines whose steps use it, or removing the emit.
2. **Heard, never emitted**: a receive nobody publishes. Proposes the machine that should emit it,
   or an external machine (a bridge) to declare.
3. **One purpose, two names**: two event types whose purposes, publishers and listeners match
   (`ticket.done` beside `gate.landed`). Proposes keeping the one already observed on the bus.
4. **One name, several purposes** (deduplicated too far): an event type whose listeners each act on
   a different part of it, or whose purpose needs "or". Proposes a split into a family.
5. **No prediction**: a declared machine with no expected effect. The owner: "if we can't point to
   any prediction then we probably don't want the Machine in there at all." Proposes one, or asks.
6. **Engagement against load**: a scheduled or ad hoc machine woken by a busy event (hundreds a
   day). Proposes a schedule, as the owner did in turn 5.
7. **Loose ends of the Dynamics side**: a declared stock or effect with no instrument; a target on
   an element with no series; an expected element absent for three versions.

Passes cost turns, so they count against `review_usd_per_day`; a pass that finds nothing costs one
short turn. The duty is the Supervisor's for now; D20's signals decide whether it becomes a machine
of its own (`design-backwards.md` §4).

## 4. Drafting a Universal Machine

**The abstract description** (what the core stores; what E1 shows). From the name and whatever the
owner said, after reading the map, the model and the neighbours' descriptions:

- **Title and description**: what it achieves, in the work's terms, one or two sentences ("Finds
  why tickets are rejected or fail the gate and proposes work to remove those causes").
- **Invariants**: what must stay true of its work, each a line a reviewer can check ("never
  changes code itself; it proposes work"; "reads the Features series, never writes it").
- **Steps**: numbered, imperative, naming each event at the step that uses it.
- **Receives, emits, reads**: existing event types first (§2.2); every guess marked so the page
  tags it "a guess". A read is never a binding: the machine does not produce the metric it reads
  (notes §13.2; rule 7).
- **Expected effect**: at least one, or the reply says why none can be named yet.

**The implementation** (the plugin's, never the core's): a machine spec in D20's shape, drafted in
the agents' state directory (`~/.orchestrator/<key>/agents/drafts/<name>/`), outside the
repository, so a draft is "not official" and leaves nothing to clean up when discarded:
`machine.toml` (model `haiku`, D20's default for narrow machines; engagement and schedule; its
wake-ups from `receives`; its tool groups, the fewest the steps need), `role.md` (the description,
invariants and steps rewritten as instructions to an agent), and the events it may emit (the emit
tool restricted to its declared `emits`). Each refinement redrafts it. Confirm moves it into
`.orchestra/machines/<name>/` in one commit and creates the agent (§2.2). Refining the machine's
operation further (prompts, tools, research) is "a long conversation with the Supervisor"; the page
shows only the result.

**Towards a Programmatic Machine** (the ladder's rungs 7 and 8; `agent-first-machines.md`, the
ghost-machine path in `environment-and-ghost-machines.md` §3). When the agent's transcripts
repeat (the review round reads them: the same tool sequence for most wake-ups), the Supervisor
proposes a program with the same declared events: a `set_kind` proposal to Programmatic, with the
Universal description kept as the program's specification. The program is written on a ticket;
the agent stays as a second instance of the same machine (`feature-count-improver/fixer`, as the
coordinator is `agent ×1, program ×1` today), woken only for what the program hands it (an event
of the program's for a case it does not know). The fixer's turns a day are a series the model sees;
each case the fixer handles is reviewed as a candidate for the program, and the fixing shrinks.

## 5. Prompts and the guide

- **`prompts/design.md`** (new, part of the Supervisor's built-in prompt, after `operator.md`):
  the three states and the two origins; what each page draws after each tool; the order of work
  (declare, measure at once, then machines); how to find measurement options (§2.1); how to name
  events; how to draft a Universal Machine; that confirm and discard are the owner's; the cost line
  for every drafted machine.
- **`supervisor.md`**, a paragraph under "The system around you": designing the system is yours;
  the pages show it; your reply says where to look and never repeats the details panel.
- **`supervisor_core.md`**, one rule added to "What never changes": **never ask the owner to edit
  a file, write a config, or paste a snippet; if something must change, change it with your tools
  or say what you cannot do.** The owner: "If TOML is the interface for setting this up, it will
  be a miserable experience."
- **`guide.md`**, a section "Designing the system": the `design` tools, `.orchestra/instruments/`,
  `[agents] design_passes` (default 3), and that the passes spend the review budget.
- **A reference** (`read_guide agents design`): the field tables of §2.2 with one example each,
  read on demand, so the prompt stays short.

## 6. Costs and models

- The `design` tools make no model call; a design conversation costs the Supervisor's own turns.
- The live proof (A3) runs on **Haiku** on the agents' demo: the Supervisor's spec model set to
  `haiku` for that run (D20's default is Sonnet). Cap: **$10 for A3**, within the run's $30 for
  every live run (goal decision 4); the test stops at the cap and says so.
- Drafted Universal Machines default to Haiku. An unconfirmed machine never runs.
- The refinement passes: at most `design_passes` a round, within `review_usd_per_day`.
- Every drafted machine's reply states its expected turns a day and their cost on its model.

## 7. Acceptance tests

Each with the fake Claude (`tests/e2e/fake_claude.py`, scripted tool calls) unless marked live; the
core side is faked by P2's API on a temporary state directory.

1. Each `design` tool refuses a missing reason, a `quote` not in the owner's message, and any
   caller but the Supervisor; each answer names the ids recorded.
2. `declare_stock` records origin owner, the quote and the turn id; the stock is in P2's API as
   declared, unconfirmed, with no series. *(notes §13.4, line 1, the agent's half)*
3. In one Supervisor turn, `declare_stock` then `add_instrument` (direct) leaves a committed script
   under `.orchestra/instruments/`, a `[[collect]]` entry committed through `config_edit`, and at
   least one stored point, before the turn ends. *(§13.4, line 1)*
4. `propose_measurements` records the options in order with kind and caveat; recording or choosing
   an option changes no other element, no model version and no other instrument. *(§13.4, line 2)*
5. `add_instrument` with a script that fails its trial is refused with the trial's output, and
   nothing is written or declared; one with a secret-looking line is refused.
6. For a quantity nobody measures, the recorded option carries the script's text, its path, its
   commit and its first points. *(§13.4, line 3)*
7. When the new series already exists in the store, the Supervisor records an `existing_series`
   option, adds no instrument and declares no binding. *(§13.4, line 4)*
8. A simulated option's series carries the simulated mark. *(§13.4, line 7)*
9. `mark_expected` and `ignore` record their marks; `ignore` deletes nothing.
10. `declare_machine` records every field of §2.2 for each kind and mode, with guesses marked; a
    Universal declaration contains no model, prompt or tool name. *(§13.4, lines 8 and 12)*
11. `refine_machine` with five edits records five timed changes; a failing edit applies none. On a
    confirmed machine the same call records a proposal instead. *(§13.4, line 10)*
12. `set_engagement` to daily at 00:00 is recorded as one "changed" edit. *(§13.4, line 11)*
13. `declare_expected_effect` is recorded on the declaration and published as
    `orchestra.prediction.made` only at confirm, with subject `machine:<name>`; the change is
    announced at the agent's first turn. *(§13.4, line 13)*
14. A page click of confirm, arriving as the core's event, wakes the Supervisor, which commits the
    spec and creates the agent; discard leaves no file in the repository.
15. A refinement round over a map with an unheard emit, a duplicated purpose and an overloaded
    event proposes three changes and declares nothing; a second pass over the result proposes
    nothing new; the round stops at `design_passes`.
16. Nothing in the Supervisor's prompts asks the owner to edit a file; a scripted turn where the
    owner asks "what do I put in orchestra.toml?" ends with the change made by a tool, not a
    snippet. *(§13.4, line 14, the agent's half)*
17. **The scenario, fake Claude**: §2.3's six turns, scripted, on the agents' demo with `--dummy`
    machines; afterwards P2's API answers the D1 and E2 shapes of `mockups/fixtures/`.
18. **The scenario, live (A3)**: the same six messages to a Haiku Supervisor on the agents' demo;
    passes when the Features stock is declared and recording, the Feature Count Improver is
    drafted, refined by messages 4 and 5 and carries its expected effect; the pages show D1 and E2
    states (screenshots); the transcripts are saved under the state directory; cost under $10.

## 8. What this does not do

- No flows are declared on a machine's behalf. The owner left it open ("I don't know if we would
  want to put the flows in there first … or if we want to associate them later"); a predicted flow
  is an expected effect, judged later, and the association stays inferred (rule 6).
- No machine is split or merged here (D20's next phase).
- No workflow is declared (the Workflows plugin's `declare_workflow`, goal task W7).

## 9. Needs from P2

1. **The Python API** a plugin calls on `project` to declare, change, confirm and discard stocks,
   effects, targets, machines and event types, and to read them back; its errors.
2. **Provenance per element and per change**: origin (owner, Supervisor, inference), who, when, the
   turn id, the quoted message; per-field guess marks.
3. **Changes as records**: each edit timed, so the page can say "added just now"; how long "just
   now" lasts; proposed changes on a confirmed element, with confirm and discard by change id.
4. **The machine schema**: the exact field names of §2.2 for Universal and each Programmatic mode,
   and the `scheduled` engagement.
5. **Measurement options** stored on a declared stock or effect (decision 2), with the chosen
   option, its instrument, script path, commit and first points.
6. **How a declared stock meets a discovered one**: automatically from the chosen instrument's
   series, or only when the owner says so (D2 keeps Features a ghost beside *acceptance tests
   passing*). If the latter, a `match` operation this proposal would add a tool for.
7. **The simulated mark**: a label convention or a flag on the instrument.
8. **Expected and ignored marks** on discovered elements, with ids stable across versions.
9. **The events the core publishes** when the page's controls are clicked (confirm, discard, expect,
   ignore), so the Supervisor can wake on them; and the amendment of rule 9 that allows the clicks.
10. **Predictions about a machine**: an expectation kind for a flow that does not exist yet
    (`appears`) and for a stock with no series yet (`up` without a level), and how a prediction is
    tied to a declared machine for E1's "Expected effect".
11. **Read in summary shape** for `read_design`: declared against observed, open differences,
    recent changes.

## 10. Open questions

1. **Direct scripts.** Is a measurement script under `.orchestra/instruments/` configuration the
   Supervisor may commit (this proposal), or code that must go through a ticket when `work =
   "code"`? Direct is what makes "recording at once" possible.
2. **Which option is recorded first.** The owner's words ("it starts recording … immediately")
   suggest the Supervisor picks and records before the owner chooses; this proposal does that and
   lets the owner choose another. The alternative is to wait for the owner's choice.
3. **Rediscovery after a new instrument.** The Supervisor waits for the scheduled discovery. Should
   it be allowed to start one (an observation, like the page's button) so D2 comes sooner?
4. **The fixer's place.** A second instance of the same machine (this proposal) or a machine of its
   own with its own declaration?
5. **The prediction's horizon** for a machine that runs once a day: seven days is a guess; the
   judgement needs enough runs to see an effect.
