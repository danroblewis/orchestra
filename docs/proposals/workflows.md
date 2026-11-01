# Workflows: a plugin for any company's workflows

Status: reviewed, 2026-11-01 (panel round 1; judge's verdict round 2); aligned to intended-model.md
and machine-design.md as merged; coverage pass 2026-11-01. Nothing built. Proposal 3 of `design-backwards.md`
§7, from `design-backwards-notes.md` §1–§8, §10, §12; the owner's decisions are D21. It builds a
new private repository, `~/orchestra-workflows` (plugin `workflows`). Nothing is copied from
`~/orchestra-tasking`, whose SPEC was read as a list of capabilities only. The owner: "Do not let
yourself be bound by the initial implementation of Tasking. It was only a prototype, we are
building the correct thing now - a Workflows system."

**Invariants.** No rule of `AGENTS.md` is amended; the plugin obeys every rule from outside the
core. It asks the core for three changes, none a rule change: file bus rotation (§2.6, which the
plugin does not need) and two discovery inputs (§4.1). Where a note met a rule, the rule won and
the place says **(rule n)**. This run builds W1–W6 (§12); what is designed but built later is §12.1.

## 1. Purpose

A generic workflow system: "capable of handling any existing workflow, from any company. Like some
companies have Release Candidates and Release Candidate verification steps. Some companies have
multiple releases out. We might see a staged production rollout, we might see customer-owned
deployments. We might see multiple concurrent release branches that all need hotfixes." Three
parts, each usable without the next:

1. **The record** (§2): every fact about every item, in the item's own log, folded into snapshots.
2. **The floor** (§5): the only thing that turns "work exists" into "a machine is doing it".
3. **Workflows** (§7): definitions in a fixed vocabulary that turn facts into piles (§4) for the
   floor to offer from.

The task system's loop becomes the first example (§9), written fresh against the floor's contract.
The prototype is retired by not installing it: "our tasking system is already a separate plugin,
so we can just not include it to get rid of it." The two use different event names, so both may be
installed during the change-over, but a project runs its work through one. A naive task system for
demos comes later on top of Workflows, "and we would expect people to customize it for the
workflows they actually experience at work." The core learns no word of the plugin (rule 1); the
plugin declares no model (§4), never reads `orchestra.toml` itself (rule 10), and its pages are
read-only (rule 9).

## 2. The record

### 2.1 Items are logs of facts

An **item** is what one instance of a workflow is about, named by the CloudEvents `subject` of every
event about it: a Jira key, a pull request, an alert, a release candidate. The owner: "a CRDT ...
built from an event log for every interaction, only viewable by combining all events." An item's
record is its own log of **facts**: the events about it, copied whole from the bus in bus order.

An event is a fact about X when its `subject` is X and X is **known**: a workflow's `starts` matched
an event about X, an `item.requested` named X, or an `item.related` made X a child of a known item.
Events about unknown subjects are not recorded. The floor adds one fact that is not on the bus, a
metric reading (§7). **Not facts**, though their subject is the item: `offer.alive` (a lease signal;
the floor reads it from the bus), `session.*` and `agent.*` (a machine's runtime noise),
`orchestra.*` (Orchestra's own). The list is the plugin's, tested; a workflow cannot add to it. In
the live run of 2026-10-31 these were 186 of 406 events; what remained was about 10 facts per
ticket. The plugin reads the `data` of its own event types and of event types other packages publish
as a protocol (PLUGINS.md §7: the bridges' `github.*`, `jira.*`), only where a definition names a
field. The core still reads only the envelope (rule 3).

### 2.2 Folds are order-independent per field

The bus is one totally ordered log, so the record is event sourcing with one writer: every fold is
deterministic and snapshots never conflict. Each field's fold still ignores arrival order, so a
bridge's late fact (an older `time`, appended later) needs no insertion and evicts no snapshot:

| Part | Fold | Set by |
|---|---|---|
| **fields** (`jira_key`, `priority`) | last writer wins by event `time`, ties by `id` | `item.fact` `set` |
| **sets** (labels, notes, links) | add-wins: in when an add has no remove naming its id | `item.fact` `add` / `remove` |
| **counters** | sum | `item.fact` `count` |
| **seen** (per type: count, first and last time, last source, last id) | count, min, max | every fact's envelope |
| **relations** (parent, children, depends on) | add-wins set | `item.related` |
| **ended** (closed, archived, deleted) | set once; earliest `time` wins | `item.closed`, `.archived`, `.deleted` |

A view that needs time order (a timeline) sorts at view time; a workflow's position is the one
sequence view (§3). Every value keeps the id, source and time of the fact that set it.

### 2.3 Snapshots and the index

- **Per-item snapshot**, keyed by `(item, facts)`: `facts` counts the facts ever recorded for the
  item, not the live file's lines (a later checkpoint shortens those). A snapshot whose count is not
  the record's is folded again. An item's page folds its log live to show provenance; snapshots
  serve lists.
- **The index**: one file of every open item's summary (fields, sets, seen, relations, each
  workflow's position, holder and wait reason). Piles query it. About a megabyte of JSON at a few
  thousand items, rewritten atomically once per tick; SQLite when that hurts. A snapshot is the
  parts of §2.2, each value with its provenance, plus `at.<workflow>` {step, pile, since, wait}.

### 2.4 Closing, and what survives

An item is **closed** by an `item.closed` or `item.archived` fact, or when every workflow reading it
has reached an end step (no event says so: it would echo recorded facts). It leaves the open index
at once, so no open pile counts it; its log and snapshot stay. `item.deleted` removes both. The
owner asked "How do we avoid long-lived items from costing too much?": compression, the archive and
dropping after M days are designed in §12.1; at the measured sizes a year of closed items is under
10 MB without them. **What survives deletion:** the model never reads item logs; pile sizes and
moves are measured into the metrics store, and the move totals live in the recorder's state, so the
system dynamics history is intact after items are gone. The Machines page reads only bus envelopes.
**The budget, from the measured sizes.** Measured on 2026-10-31
(`~/.orchestrator/orchestra-sample-live-*`): 406 events, 49 items, median 2 events per item, maximum
32; 120 to 500 B per event (509 B in the live run, 122 B in a program-only run of 9,118 events);
about 10 facts and 3 to 5 KB per item without the noise. W2's tests hold the design to: a year at 30
items a week (1,560 × 10 × 500 B) under 10 MB; the index at 5,000 open items under 2 MB and
rewritten in under 100 ms; one item of 2,000 facts folded in under 50 ms; the 9,118-event run
recorded in under 5 s. The disk goes elsewhere (metrics 448 MB, worker artifacts 709 MB in those
directories). A Jira comment an hour for a year (9,000 facts, 4 MB) is fine on disk and slow to
fold; checkpoints answer it later.

### 2.5 The recorder

The recorder follows the bus with `Events.after(offset)` and copies each fact into its item's log.
It is infrastructure (rule 2): it publishes and announces nothing.

- **Exactly once, by event id.** The bus gives an offset per batch, not per event (`read` returns a
  list and the end; the file bus counts lines it cannot decode), so nothing keys on per-event
  offsets. `recorder.json` holds the offset applied up to, written after the logs it covers; each
  log line carries the `recorder.json` offset in force when it was written. After a crash the
  recorder reads again from the stored offset and skips a fact whose `id` is already among its
  item's lines written at or after that offset.
- **The bus changed under it.** When the bus's end is below the stored offset (a file bus
  replaced), or `start()` (§2.6, where it exists) is above it, the gap (offsets, time) is kept in
  `recorder.json`, printed by the `workflows.record` instrument and named on the Items page; the
  recorder reads on from the first held event and invents nothing.
- **Each tick:** read → append facts → fold touched items → count moves (§4.1) → write snapshots →
  write the offset → rewrite the index → close what closed.

```
~/.orchestrator/<key>/workflows/          (rule 5)
  recorder.json                  offset, gaps, move totals, the excluded-types version
  index.json                     open items' summaries
  items/<ab>/<sha1 of subject>/  log.jsonl, snapshot.json (the subject is inside, not in the name)
  floor.json                     offers, holders, leases, unit intents (§5.2)
  resources/<kind>.json          each unit: state, holder, setup hash (§6)
```

**The bus is transport, never the record.** Retention is the broker's; once a fact is copied it no
longer matters to items. Only the recorder reads the bus for item history, from 0 only to rebuild a
lost record. The logs are a copy of the one bus and split nothing (rule 4).

### 2.6 A core change to request: file bus rotation

The file bus has no rotation and grows without bound (notes §12). **The plugin works without it;
history is bounded by the item logs' retention.** The request is the goal document's core task C6
(later in this run's order):

*SPEC's bus section, replacing its sentence on the file bus:* "The file bus is a live segment,
`events.jsonl`, and sealed segments, `events.d/<base>.jsonl`, where `<base>` is the offset of the
segment's first event, zero-padded to twelve digits; `events.d/live.base` holds the live segment's
base. An offset is the number of events before a point in the whole stream, so a cursor stays valid
across rotations. When the live segment passes `[events] rotate_mb` it is sealed and a new one
begun; sealed segments older than `[events] keep_days`, or beyond `[events] keep_mb` in all, are
removed oldest first, never the live one. Appends and the rotation take an exclusive `flock` on
`events.lock`; reads take a shared one, so a reader sees a base with its segment. A file that
predates rotation is a live segment with base 0."

*The new method:* `EventBus.start() -> int`: "The offset of the first event the bus still holds: 0
until retention removes anything. `read(since)` with `since` below `start()` reads from `start()`;
a reader comparing the two knows it missed events, and how many." File: the oldest sealed
segment's base; Kafka: the partition's log start offset; Redis and RabbitMQ streams: what their
offset conversion gives the first entry still held, stated in each backend's docstring and checked
by a trimming test added to `tests/bus`.

*Settings and check:* `rotate_mb` (unset: no rotation, today's behaviour), `keep_mb`, `keep_days`
(unset: keep all). Refused: a non-positive value, `keep_mb` below `rotate_mb`, any of them with a
server bus URL. *Sealing, and writers without the lock:* `FileBus` opens the file for each append,
so a writer without the lock can reach a sealed segment only with a write already in flight at the
rename. Rotation renames the live segment under the exclusive lock, waits one second, counts its
lines and writes `events.d/<base>.lines`; readers trust that count. A sealed segment found longer
than its count (at the next rotation, or on start) is logged as a bus fault, and its extra lines are
re-appended to the live segment, where readers that already hold them skip them by id.

*Readers to change with it*, each reading from 0 and assuming the bus holds everything:
`orchestra/host.py` `_collect` (about l.132: `read(0)` then `backfill(replace=True)` rebuilds
`orchestra_events_total` from what is held, so retention would erase its history: persist the counts
before `start()` as a base); `orchestra/cli.py` (about l.85, `metrics backfill`: the same);
`orchestra/web/app.py` (about l.444) and `orchestra/web/core_explore.py` (about l.159: they show what
is held); `orchestra/endpoint/server.py` (about l.112: idempotency ids from `read(0,
limit=SEEN_MAX)`, correct while `SEEN_MAX` events are held); the agents' host's cursors (valid; must
treat `start()` above a cursor as a gap).

## 3. Items have no status

The owner: "we could model the 'state' as a function of the task's variable fields, and determine
the properties as needed. We could define several state machines on top of a Task, and use them for
different things." No `status` field, no transitions table, no version bump, no "cannot move X → Y",
and so none of the recovery states where the prototype's bugs lived. **Several workflows read one
item**: delivery, Jira hygiene, the ledger and the morning brief are functions over the same facts;
none owns the item. A pull request is in the owner's delivery workflow (as a child of the Jira
ticket, §7) and in the team's review workflow at once, each position under `at.<workflow>`.

**The position view** is the one sequence: "approved after the rework" depends on what came first.
It walks the item's facts **in log order** (the order the floor acted in) from the workflow's
`starts` fact: a step is entered by the fact that led to it; its done-when counts only later facts;
its outcome names the next step; an `on` fact moves it whenever it arrives; a step with no next is
an end. A late outside fact counts when it arrived (§13 q1). **Predicates and events: both.** "That
could be a 'has Jira Ticket ID' event, or it could be a 'jira ticket ID modified' event." The event
is the fact (who, when, from what to what: the ledger wants it); "has a Jira key" is a predicate
over the fields (piles want it).

**Explainability.** "PROJ-123 is waiting for review" must show which facts make it so. An item's
page folds the log live and shows per workflow the step and pile, the fact that entered it, the
done-when facts seen and awaited, each guard's clock and the wait reason (§4.1); per field, the fact
that set it; and the facts **not counted**, with why. **Access replaces the transitions guard.**
Every fact is recorded, but counts toward a step only from a source that may make it: for a role's
step, the instance holding its offer; for a program step, the program's instances; for an outside
wait, the bridge's sources (`github`, `person.*`); `item.fact`, `item.related` and the end facts
from any announced machine unless the workflow restricts a field. The outer gate stays the core's
(the endpoint's token, the agents' session check). Machines act on the floor's offer, never on the
item's facts.

## 4. Piles

A **pile** is a named query over the index: "has a Jira key, no pull request, nobody holds it".
Factories "work in piles, where the pile is a pile of similar things". Dispatch picks from a pile by
the `priority` field (1 soonest, 5 if unset), then the longest waiting.

### 4.1 Step piles: a partition, recorded by construction

Every step makes two piles, `<step>.waiting` and `<step>.held`; they **partition** the workflow's
open items. Attention is not a step: an item waiting for a planner stays in its pile with a wait
reason. An end is no pile. A **move** is a change of pile in one workflow: `<start>` → the first
waiting pile; waiting ↔ held on a claim or a take-back; one step's pile → the next on an outcome or
`on`; a pile → `<end>`. Each move is keyed by the id of the fact that caused it, so a re-fold counts
it once; totals live in `recorder.json`, survive closing and deleting, and never decrease.

The level and the moves come from one fold, so their balance is exact **by construction**: an R² of
1.000 is no evidence (`orchestra/sd/construction.py`). The structure is the definition's. The plugin
passes that provenance with its series, and discovery records each step pile as a stock
`by_construction`, with no R² and nil trust, as it does a source's counts of reporters. **The
model's evidence about a workflow is elsewhere:** the fitted rates of its moves, the loops it finds
(rework back to write; capacity limiting `write.held`), and agreement with an outside measurement of
the same quantity (a bridge's count of open pull requests).

`workflows.piles` (`Plugin.collectors`: a command printing Prometheus text from the index and
`recorder.json`, every 15 s by default whether or not anything changed) serves:

| Series | Kind | View |
|---|---|---|
| `workflow_pile_items{workflow, pile}`, step piles | gauge | `count` |
| `workflow_item_moves_total{workflow, from, to}` (piles, `<start>`, `<end>`) | counter | `starts` of `to`, `stops` of `from` |
| `workflow_pile_items{workflow, pile}`, declared piles | gauge | `aggregate`: no level candidate |
| `workflow_pile_oldest_seconds{workflow, pile}` | gauge | `age`: no level candidate |

Two discovery inputs are needed from the core (the goal document's task C7, with proposal 5): plugin collectors cannot pass
provenance today (only `[[sources]]` do, through `discover(provenance=)`), and `pile` is not in
`construction.PLACES`. Until both exist, discovery sees step piles as levels with an exact balance,
and §9's check expects that. The recorder and floor never write metrics directly (rules 2 and 7).

**Declared piles** are a conjunction of predicates of fixed forms, nothing else: at step S of W;
held or not; field F set, unset, or equal to a value; set L contains a value; type T seen or not; an
open child or an unmet dependency; open or closed. They overlap, so they carry the `aggregate` view,
are kept out of level candidates, and are shown on the Piles page only.

**Wait reasons.** The index keeps one per waiting item, with its fact and who acts next: **never
offered** (dispatch, next tick); **offered, unclaimed** (a machine of the role); **resting until T**
(dispatch, at T); **role at capacity** (the holders; the Supervisor, by capacity); **paused** (the
Supervisor); **no unit** of a kind (the holders; the Supervisor); **dependency** (the other item's
workflow); **attention raised** (the planner it names). Shown in the item's drawer and as a Piles
column, never as a series label.

## 5. The floor

### 5.1 What it does, and its boundary

The owner: "a huge thing that Tasking gives us that nothing else gives us is the ability to actually
launch and setup Machine instances ... if nothing else does it then we would never have anything
that does any actual work." The floor keeps **capacity** per role, makes **offers**, records the
first valid **claim**, keeps the **lease** by **heartbeats**, prepares and holds **resources**,
takes **silent work** back, and **escalates** to a planner role when a guard passes. **The split is
kept:** the offer side decides what is next and offers it with the resource prepared; the other side
answers offers by starting an instance: the agents' host a session (orchestra-agents SPEC §3: the
lowest free instance claims and reads its claim back before spending anything), the program host
(§5.3) a command, a person the desk. **The offer side never knows what a machine is made of.** **It
runs without any workflow**: the Supervisor's "do this once" (`item.requested` with a `role` and no
workflow: an item of one step), a recurring job (`every` an interval), an alert. So it is built
first (W4); workflows are a layer that produces piles for it (W5). **One plugin, a hard boundary
inside:** `record/`, `floor/`, `define/` and `programs/` meet only through stated APIs; `programs`
imports neither of the first two and speaks only the bus contract. A test enforces it, so splitting
the floor out later stays cheap. **Out of the core** (rule 1). **Probes** (the prototype's condition checks) are instruments, not
the floor's; a workflow reads them only as metric conditions (§7).

### 5.2 Offers, claims, leases, capacity

Each tick, after the recorder: (1) **follow the bus**: the first valid claim of an offer on the bus
holds it (a loser is told nothing and knows by reading); `offer.alive` extends the lease;
`offer.finished` ends the turn with its outcome as a fact. (2) **Take back**: an unclaimed offer is
withdrawn after its lease and the item rests (60 s, doubling, at most 15 min, cut short when a
machine listening for offers announces itself); a held offer with no heartbeat for its lease is
taken back ("no zombies"); rework addressed to one instance and unclaimed within `return_after`
goes to any instance. (3) **Guards**: a `within` or retry limit passed raises attention once per
guard per entry, or moves the item to the step the guard names. (4) **Conditions** (§7).
(5) **Offer**: per role under capacity and not paused, the best ready item of each waiting pile
whose `who` is that role, once its units are claimed and prepared, off the tick.

**Capacity** is `[workflows.roles.<role>] capacity`, read through `project.config`, changed by the
Supervisor with `project.config_edit` (rule 10). Unclaimed offers, held turns and **preparations**
count against it; a preparation past its timeout frees its unit and slot (reason "no unit").
**Pause**: `[workflows] paused`, or per role. **Times** are settings: `tick` 3 s, `heartbeat` 30 s,
`lease` 180 s, `return_after` 60 s; a lease not longer than heartbeat plus tick is refused. Stopping
a holder is a planner's `offer.withdraw_requested`, answered with `offer.withdrawn`: an act on the
bus, not a page button (rule 9). **Never beside the task system's scheduler.** Both would publish as `coordinator/dispatch`, so
`workflows.floor` refuses to run (logged once, said to the Supervisor by `Plugin.check`) while the
runtime record shows `tasks.scheduler` running for the same project. **No half-claimed units.** Before publishing `offer.made` the floor
writes the unit → offer intent to `floor.json`. On start it reconciles with the bus: an offer never
claimed is withdrawn and its unit freed; an intent with no offer on the bus is dropped and its unit
freed.

**Who the floor publishes as (D17).** The floor is never a source (rule 2; its publish refuses its
own name). As the owner decided in D17, **choosing what is offered next is the planner's dispatch**:
offers, withdrawals of unclaimed offers, answers to withdraw requests, one-off and `every` items,
and attention are published as `<planner>/dispatch`, the workflow's planner role's dispatch instance
(default `coordinator/dispatch`), announced by the floor with what it listens for and no package,
beside whatever else fills that role. Taking back a held turn is published as the role (`worker`,
its instance in the data). There is no `dispatch` or `schedule` machine of its own.

### 5.3 The program host

The other half for programs, behind the boundary: for each machine in `.orchestra/machines/` with
`kind: programmatic` and `managed: orchestra` (proposal 2's envelope) it announces the instances (`<name>/<n>`, kind program, ad hoc, `listens_for: [offer.made,
offer.withdrawn]`), claims offers for the role in `spec.role`, runs the command in the repository root with the
brief on stdin and `ORCHESTRA_OFFER`, `ORCHESTRA_ITEM`, `ORCHESTRA_REPO` and one
`ORCHESTRA_RESOURCE_<KIND>` per held unit, sends `offer.alive`, and finishes with the outcome its
exit code maps to in `spec.exit` (`0 → landed, 1 → rejected, 2 → conflict`, else `error`) and its output's tail as
summary. Nothing more in this run (§12.1). It publishes only as the program's instances.

### 5.4 The machine contract

A page in the plugin, `docs/machine-contract.md`, for a machine author in any language. The names
are new; no `task.*` name is reused. Every event of a turn has the item as `subject` and the offer
that opened it as `causationid`.

| Event | Published by | `data` |
|---|---|---|
| `offer.made` | `<planner>/dispatch`, or a holder passing on | `offer` (`<item>.<step>.<8 hex>`), `role`, `item`, `workflow`, `step`, `to` (an instance, for rework), `lease_s`, `brief`, `resources` [{kind, id, handle}], `outcomes`, `ends` |
| `offer.claimed` | the instance taking it | `offer` |
| `offer.alive` | the holder, every `heartbeat` | `offer`, `text` (one line) |
| `offer.finished` | the holder | `offer`, `outcome`, `summary`, `facts` (an `item.fact` body) |
| `offer.withdrawn` | dispatch, or the floor as the role | `offer`, `reason`, `instance` |
| `offer.withdraw_requested` | a planner | `offer`, `reason` |
| `item.requested` | a planner, a machine fanning out | `workflow` or `role`, `brief`, `parent`; subject: the new id |
| `item.fact` | any announced machine | `set` {field: value}, `add`/`remove` {set: [v]}, `count` {c: n} |
| `item.related` | any announced machine | `kind` (`parent`, `depends_on`), `other` |
| `item.closed`, `.archived`, `.deleted` | any announced machine | `reason` |
| `attention.needed` | `<planner>/dispatch` | `to`, `reason`, `workflow`, `step`, `guard` |

The page's sections, each with the exact call:

1. **Open the bus as yourself**: `Events.for_project(Project.find(os.environ["ORCHESTRA_REPO"]),
   source="worker/1")`, or the events endpoint (`ORCHESTRA_EVENTS_ENDPOINT`, `_TOKEN`). **Announce**
   `orchestra.machine.started` (kind, mode, `listens_for: [offer.made, offer.withdrawn]`, roles).
   **Follow from now**: start at `events.end()`, read on with `events.after(offset)`.
2. **Claim** an offer for your role (`to` absent or yours), then **read the bus from the offer to
   your claim**; if another valid claim came first you lost. Start nothing costly before this.
3. **Work** in the handed resources, from `ORCHESTRA_REPO`; `offer.alive` every `heartbeat`; claim
   only what you can do within the lease.
4. **Finish** with one of the offer's outcomes, each resource left committed and clean. **The BLOCKED
   rule:** work you cannot do finishes `blocked` with the reason in `summary`; never go silent,
   never finish `ready` with nothing done.
5. **Or pass on directly**: publish the next step's `offer.made` with `ends` naming your offer and
   the same resources. The floor records your offer finished with the outcome that leads to that
   step, and the new one as the step's offer if its `who` matches (the map draws worker →
   reviewer). A pass-on to a role at capacity is withdrawn by dispatch and offered again normally.
6. **Stop** when an `offer.withdrawn` names your offer or instance, whatever you read before.

The scripted worker and reviewer ship as reference machines (`python -m
orchestra_workflows.reference.worker`, `.reviewer`). The agents' host answering `offer.made` stays
in orchestra-agents (P4); until then the examples run on reference and scripted machines.

## 6. Resources

The owner: "I like the part about Resources. I don't know how to make it generic, but some part of
it will be user-configurable in the target repo." A **kind** is a name, a capacity, and three
commands the repository provides: **make**, **reset** between uses, **release**: a staging
environment, a database snapshot, a customer sandbox, an API budget, "one person's attention". The
floor knows only: **claim before the step, hold across hand-offs, free when the holder drops.** An
item keeps a unit while consecutive steps need its kind; it is freed when the item leaves them,
ends, or its holder is taken back. A pool is a capacity limit on a flow; the floor instrument
measures `floor_resources{kind, state}`. **A Jira ticket or a pull request is not a resource**:
nothing is scarce about it; it is a fact on the item. Commands run in the repository root with
`ORCHESTRA_RESOURCE_KIND`, `_ID` and the handle in the environment, each under a timeout; make
prints the handle; a non-zero exit is a broken unit, tried again after a back-off (1 min doubling,
at most 30) and said once to the planner.

**The worktree kind**, shipped with the plugin, as requirements learned from the prototype:

1. At most `capacity` worktrees in the state directory; a full pool is back-pressure ("no unit").
   **Make** works from the common git directory, a bare one included, fetching `origin/<base>` first.
2. **Reset** before each use: abort a merge or rebase, discard tracked changes, remove untracked
   files, keep ignored ones (caches) unless told otherwise, check out the item's branch. Not clean
   after it: broken.
3. **Release** detaches the worktree and the item's branch wherever else it is checked out.
4. **The work is on the branch**: a waiting item holds no worktree; a holder commits before passing
   on. Rework prefers the unit the item last used if free, never waiting for it.
5. **Setup**: the repository's command, once per unit made, before first use; success recorded by a
   hash of the command in `workflows/resources/`, so it reruns only when the command changes or the
   unit is remade, never on a reset. A failure leaves the unit unused.
6. **Off the loop**, counted against capacity (§5.2); a half-made unit is remade on start; a dirty
   unit is reset before reuse; units on disk the record does not know are reported, never deleted.

## 7. The vocabulary, and nothing beyond it

A workflow is written in exactly these words, the capabilities of notes §1 and no more. Anything that
needs logic is a machine, never an expression or a script in the definition. A milestone is a parent item
(its children the work) or a dependency on one. A workflow these words
cannot express is a finding about the vocabulary, taken one case at a time.

| Word | Meaning |
|---|---|
| **item** | what one instance is; the subject key |
| **starts** | an event type (`jira.issue.assigned`), the clock (`every` an interval), or a request (`item.requested`) |
| **step** | one stage, with the fields below |
| **who** | a **role** (any machine announcing it), a **program** (§5.3), an **outside** system (a wait: nothing offered), a **person** (`person: <name>`: offered with no lease, only `within`; a machine may prepare the act, never do it), or the **outbox** (a write as the owner, after approval) |
| **needs** | resource kinds claimed before the step, held across hand-offs |
| **done-when** | an event type about the item (or, `of children`, a child); optionally a `data` field equal to a value or to an item field (the head commit, so stale results do not count); optionally `count ≥ n`; or a **metric condition** |
| **guards** | `within` and retry limits (`rounds`); passed: attention, or a move to a named step |
| **outcomes** | each result → a step: success → the next, failure → an earlier one, a name → a named step; none: an end |
| **on** | an event or a metric condition that moves the item to a step whenever it happens |
| **rework** | a move back is offered `to` the instance that did the step; after `return_after`, to the role |
| **relations** | children (fan-out) and fan-in, `all` or `any` with an outcome set ("all ended `landed`", else a named outcome), optionally `within`; dependencies (not offered until the other item is at a named step or ended; a cycle raises attention) |
| **lifecycle** | the retention policy once closed (stages beyond the first later) |

**Relations** and **metric conditions** are the two words the prototype never had. This run builds
what example 1 needs plus the goal's two features with `all` fan-in; `any`, `count ≥ n`, the field
equalities and person offers are built with the examples that need them (§12.1).

**Metric conditions.** "Gauge G with labels L above (or below) a threshold for duration D": "the
canary's error rate under 0.1% for 30 minutes". Gauges only, no rates, read each tick from the
metrics store (rule 5). A **gap** (the latest point older than twice the scrape interval) resets D:
a missing series is never "below". An optional exit threshold gives an `on` hysteresis. It fires
once per entry into the step, and the floor writes a **recorder fact** into the item's log with no
bus event (source `metric:<series>`, the reading, the window, the time); the position view counts it
and the item's page names it. Reading a series never makes a machine of it (rule 7). **Relations.**
A machine fans out with `item.requested` per child, `parent` set (one port per release branch). A
link made after the fact is `item.related {kind: parent}` from a machine the workflow names
(`pr_linker` below hears `github.pr.opened` and links the PR to its ticket). A bridge's events stay
facts of their own subjects; a parent reads them only through `of children`.

**The SAIL delivery example** (set aside, notes §11, kept because it uses every word). Item: a Jira
ticket. Starts: `jira.issue.assigned` to the owner. Planner: `supervisor`. Keeping the ticket current
is a separate workflow, `jira-hygiene`, on the same item. Working hours for `within` come later.

| Step | Who | Needs | Done when | Guards, outcomes, on |
|---|---|---|---|---|
| write | role `worker` (an AI worker, or the owner) | worktree | `offer.finished` ready | blocked → attention |
| open the PR | `person: owner` (the worker drafted the text) | worktree | `github.pr.opened` of children | within 1 day, else attention |
| ci | outside: GitHub | | `github.checks.completed` of children, `head_sha` = item `commit` | success → review; failure → write |
| review | outside: people | | `github.pr.approved` of children, count ≥ 2 | on `github.pr.changes_requested` → write; within 1 day → nudge |
| nudge | role `nudger` drafts, the outbox sends | | `outbox.sent` | → review |
| sail | outbox: the SAIL label, after approval | | `github.pr.labeled` | |
| sail-check | outside: SAIL's action | | its check result | success → end; failure → triage-failure |
| triage-failure | program `sail_triage` | | `offer.finished` | company-wide → sail-check (rounds 3); else → write |

**Persistence, not interface.** "If TOML is the interface for setting this up, it will be a
miserable experience. If you insist on using TOML, it can be as a persistence format." Definitions
are JSON, written and read by programs; the owner tells the Supervisor, the Supervisor writes, the
Workflows page draws. The loader refuses unknown keys, unresolved step references, a reachable step
with no way out, and a lease not longer than heartbeat plus tick; one sentence per problem.

```
{"name": "task-loop", "planner": "coordinator", "starts": [{"request": true}], "steps": [{"name": "write",
  "who": {"role": "worker"}, "needs": ["worktree"], "done_when": {"event": "offer.finished"},
  "outcomes": {"ready": "review"}, "guards": {"within": "2h", "then": "attention"}}, ...], "piles": [...],
  "lifecycle": {"keep_final": true}, "settings": {"label": {"type": "string", "default": "SAIL"}}}
```

## 8. What lives where

**A repository's `.orchestra/` folder and a plugin have the same shape.** The Supervisor's default
root is the state directory (`~/.orchestrator/<key>/`, as machine-design.md §2.1 puts its writes),
because at work the base branch is protected; `.orchestra/` in the repository is the alternate root
when the repository can be pushed to, by pull request. Both hosts (this plugin's and the agents')
read both roots. A `machine.json` holds the implementation only; the declared layer (proposal 2) is
authoritative for what the map shows.

```
.orchestra/
  workflows/<name>/workflow.json   definitions
  machines/<id>/machine.json       proposal 2's envelope (id `^[a-z][a-z0-9_]{1,40}$`, `kind`,
                                   `managed`, `engagement.mode`, `spec`), one schema per kind (D20);
                                   each plugin reads only its own: this one `kind: programmatic`,
                                   `managed: orchestra`, `engagement.mode: ad hoc`, `spec` {command,
                                   role, exit: {code: outcome}}
  resources/<kind>/kind.json       capacity; make, reset, release (scripts beside it)
  instruments/                     collect scripts (as today)
  plugins/, overrides/             the core's, unchanged
```

The company's workflows, programs, roles and resource kinds live in `.orchestra/`; reusable
workflows with settings ("GitHub PR review", the task-loop demo), runtimes, bridges and the worktree
kind come from plugins, through this plugin's entry point `orchestra_workflows.packages` (a
directory of the same shape; the core's `Plugin` gains nothing). Settings' values (`SAIL`,
`#team-reviews`) are in `[workflows.settings.<workflow>]`, read and changed through `project.config`
and `config_edit` (rule 10), so the private overlay's values reach the workflow. The intended model
is the core's (proposal 2). People, channels and tokens stay in `~/work-desk` (D10) and the keychain.

**Promotion is packaging, never a rewrite:** (1) it starts in `.orchestra/`, specific and private;
(2) it gets parameters when a second repository wants it, names becoming `settings` (the Supervisor
does this); (3) the folder moves into a plugin repository with a `pyproject` and the entry point;
(4) it is shared as an extra, each repository filling its settings. **The drift test:** one example
loaded from `.orchestra/` and from a packaged copy with the same settings gives equal normalised
definitions and the same pile series on the same scripted run. **The Supervisor writes all of it**;
no human reads or writes these files (D21).

## 9. The examples, and how each is tested

"We want some examples of how people would actually use this, and we want them tested." Each is a
tiny target repository under `~/orchestra-workflows/examples/<name>/` with its own `.orchestra/`, a
README, scripted machines (programs, and agents on the dummy harness: no model, no network), fake
bridges publishing outside events on a script, and one test with three checks (examples 2–8 are
M5's, numbered X1–X7 there; they are the suite and the documentation at once; in M5 the 21 stories
of `docs/user-stories.md` are also run through the vocabulary, and a story it cannot express is a
vocabulary finding):

1. **piles over time** match the script (from the metrics store, at named moments);
2. **the model** (`model-acceptance`): step piles recorded `by_construction` (until the core's inputs
   exist, levels with an exact balance); the **expected loops** found (rework back to write; capacity
   limiting a held pile); the **forbidden list** held (no stock from `workflow_pile_oldest_seconds`,
   holds by role or capacity; no flow per instance; the domain series as a tally of events); and
   **a domain series**, a quantity the workflow changes rather than a count of its own piles (for
   example 1, the commits landed on the example repository's `main`, from a `[[collect]]`), whose
   inflow is the move that fills it (the gate's `landed` move);
3. **the event map** shows the declared machines and hand-offs, and no node, edge or source names the
   recorder, the floor or the program host.

| # | Workflow | Item | Piles | What it exercises |
|---|---|---|---|---|
| 1 | **the task loop** | a piece of work | write, review, gate (waiting, held) | offers, claims, leases, rework to the same instance, a worktree held write → gate, attention after 3 rejections |
| 2 | team PR review | pull request | requested, read, commented, approved, merged, stale | one PR in two workflows: two `from="<start>"` counters stay two flows; the Piles page never sums across workflows |
| 3 | on-call | alert | new, analysed, disqualified, awaiting triage comment, fixing, runbook | an outside wait on a comment, metric conditions |
| 4 | RC verification | release candidate | cut, verifying, verified, rejected, released | a staging-environment resource per RC |
| 5 | hotfixes across branches | hotfix, a child per branch | pending, ported, landed per branch, complete | fan-out and fan-in; children counted once, in their own workflow |
| 6 | staged rollout | release | canary, 10%, 50%, 100%, rolled back | metric done-whens, rollback as a metric `on`, a guard per stage |
| 7 | customer-owned deployments | customer × release | notified, scheduled, deployed, verified, overdue | long outside waits, many items per release |
| 8 | delivery through SAIL (§7) | Jira ticket | its steps | every word; set aside (notes §11) |

**The task loop, example 1.** write (role `worker`, needs a worktree; `ready` → review, `blocked` →
attention to `coordinator`); review (role `reviewer`, passed on by the worker; `approved` → gate,
`rejected` → write as rework; rounds 3 → attention); gate (program `merge_gate` in the example's
`.orchestra/machines/`, the repository's checks on a merge: 0 landed → end, 1 rejected and 2
conflict → write as rework, else attention). Starts: a request or `every`. One command runs it, for
the tests and W7's UX review: `uv run python -m orchestra_workflows demo task-loop`.

## 10. Pages and tools

These are the plugin's own views of its own record, as the task system's Tickets page was, and
add no page to the core; the owner's "no new page" (notes §13) was about the design map, so the
owner must confirm these three (the coordinator's default: keep). Read-only for humans (rule 9), in
Orchestra's frame, built in W7. **Items** (`/items`): the index,
filtered by workflow, pile, field; an item's drawer folds its log live (timeline, provenance, each
workflow's step and the facts that make it, the wait reason, facts not counted, offers, holders,
relations, resources, the recorder's gaps). **Piles** (`/piles`): sizes over time from the series
discovery reads, the oldest item, wait reasons as a column, never summed across workflows.
**Workflows** (`/workflows`): each definition drawn; **coverage** per role from the machines
observed claiming its offers, those only announcing it shown as "declared", a role with neither a
hole; open attention by planner with its age; the floor's offers, holders, leases and resources. No
button changes anything. The Supervisor's tools live in orchestra-agents. W7 adds
`declare_workflow`, importing the plugin's validated writer
(`orchestra_workflows.define.write(project, definition)`: the loader's checks, then an atomic write)
as an optional dependency; the rest (`start_item`, `set_capacity`, ...) come later (§12.1).

## 11. Packaging

`~/orchestra-workflows` (private, `danroblewis/orchestra-workflows`, after a secret scan), package
`orchestra_workflows`, plugin `workflows`. `pyproject.toml` as PLUGINS.md §9.2:
`"orchestra>=1.0.0a1,<1.0.0rc0"` by name and range, never a URL; `[tool.uv] override-dependencies`
with `orchestra[sd]` from GitHub for tests. The core gains the extra `workflows = ["orchestra-workflows
@ git+https://github.com/danroblewis/orchestra-workflows"]`. **Processes** (only when the project has
workflows, kinds or a `[workflows]` section): `workflows.floor` (recorder then floor; `stop_grace_s`
above a resource command's timeout) and `workflows.programs`, both `[sys.executable, "-m",
"orchestra_workflows", ...]`, following settings with `project.config_stamp()`. **Collectors**
(instruments, rule 7): `workflows.piles`, `workflows.floor` (offers, holds, take-backs, attention,
resources by kind and state), `workflows.record` (lag, bytes, gaps). **Machines**: placeholders for
the roles, programs and outside systems the workflows name and no machine has announced, never
overriding what is observed, saying nothing about flows (rule 2). **Pages, router** (reads only),
**`guide`** (modelling in the vocabulary, capacities, leases, the worktree kind, the owner's choices),
**`check`** (unknown keys, negative capacity, lease too short, settings their schema refuses).

## 12. Build order (M4), later, and acceptance tests

| Id | Delivers |
|---|---|
| W1 | Repository, `AGENTS.md` (the core's rules as they bind a plugin, the import boundary, no `task.*` names), `SPEC.md` from this proposal, registration, `docs/machine-contract.md`, a suite that runs |
| W2 | The record: exactly-once recorder, one live log per item, folds, snapshots, index, closing and deleting, gaps, excluded types; `workflows.record` |
| W3 | Piles: step piles and moves, declared piles, wait reasons; `workflows.piles` with its views |
| W4 | The floor without workflows: requests and `every` items, offers, claims, leases, capacity with preparations, take-backs, attention, withdraw requests, unit intents; the worktree kind; the program host; the reference machines |
| W5 | Definitions: loader (`.orchestra/` and packages), the vocabulary as §7 scopes it, the position view, `all` fan-in and dependencies, metric conditions, access |
| W6 | The task loop, example 1, with its one-command demo |
| W7 | The Items, Piles and Workflows pages; `declare_workflow` in orchestra-agents |

### 12.1 Later (M5 and after)

- **Checkpoints and the archive**: past 2,000 facts or 30 days since the last, a checkpoint (the fold
  up to fact k, **with each workflow's walker state**, so the position view resumes there), the
  prefix compressed beside the log, the last 300 facts never compacted; snapshots stay keyed by
  facts ever recorded.
- **Lifecycle stages 2–3**, per workflow: after N days (14) the log compressed and a final snapshot
  written; after M days (180) the archive dropped and the final snapshot (under 1 KB, the "flattened
  static form" the ledger and yearly review need) kept or not. An alert can go in a week; a delivery
  item's final snapshot is kept forever.
- **Calendar schedules** (an IANA zone through daylight saving, occurrence ids `<name>@<local due
  time>`, the latest missed one only, `if_open: skip`) and working hours. **Worktree adoption** (the
  owner's listed worktrees, never the root, adopted only if a reset loses nothing, else refused and
  said once; marked with the project's key in their git directory).
- **The program host beyond a command** (argument, environment and stdin interfaces; continuous
  programs, notes §13.2), and **the other words**: `any`, `count ≥ n`, field equalities, person offers
  (shown to the owner by orchestra-desk).
- **Stacking**: a `depends_on` between items plus a `restack` program step (rebase a branch on its
  parent's new head); a conflict is an outcome that goes to rework.
- **The Supervisor's other workflow tools** (`start_item`, `set_capacity`, ...), beyond W7's
  `declare_workflow`.

### 12.2 Acceptance tests, each a program's check

1. W1: the suite exits 0; `GET /api/plugins` lists `workflows`; an import test fails if `programs/`
   imports `record/` or `floor/`, or `record/` imports `floor/`.
2. W2: on the measured run's fixture (406 events, 49 items) exactly the non-excluded facts are
   recorded; no excluded type is in any log.
3. W2: 200 random permutations of an item's facts give equal fields, sets, counters, seen and ended;
   a fact with an older `time` appended after a newer one changes no field the newer set.
4. W2: killing the recorder at each point of its tick and restarting from `recorder.json` gives logs
   equal to an uninterrupted run; no event `id` twice in any log.
5. W2: a bus end below the stored offset gives one gap, printed by `workflows.record`, nothing
   invented; `item.closed` leaves the open index at once; `item.deleted` leaves nothing under `items/`.
6. W2: 1,560 items × 10 facts × 500 B under 10 MB, index rewrite under 100 ms; the 9,118-event run in
   under 5 s; a 2,000-fact fold under 50 ms.
7. W3: at each measurement of a scripted run, each step pile's gauge equals the index's count and its
   change equals moves in minus moves out; re-folding every item leaves every move total unchanged,
   and deleting an item lowers none.
8. W3: discovery records each step pile `by_construction` and each move counter as the flow between
   its piles (before the core's inputs: levels balanced exactly by them); declared piles and
   `workflow_pile_oldest_seconds` are no stock.
9. W3: each wait reason of §4.1 comes from a scripted case and names its fact.
10. W4: two instances claim one offer; one starts work; the floor records the first claim; the loser
    publishes nothing more. An unclaimed offer is withdrawn after its lease and offered again after
    the back-off; a silent holder is taken back within lease plus a tick, as its role.
11. W4: across 100 items a role's capacity, counting unclaimed offers and preparations, is never
    exceeded; a preparation past its timeout frees its unit and slot.
12. W4: a worktree is made from the fetched base, set up once, held across a pass-on from worker to
    reviewer (one path in both offers), freed on a take-back, reset before reuse, its branch detached
    on release; a full pool leaves the next offer waiting with "no unit".
13. W4: killing the floor before and after publishing an offer whose intent is written leaves, after
    restart, no unit held and no offer open without a claim.
14. W4: a role-only `item.requested` is offered, finished and closed; an `every` item is made once per
    interval across a restart.
15. W4: offers, withdrawals and attention are published as `coordinator/dispatch`, take-backs as the
    role; no source is the recorder's, floor's or program host's own, and none is a machine node.
16. W4: a machine written only from `docs/machine-contract.md`, committed as a fixture, completes ten
    offers.
17. W5: the loader refuses an unknown key, an expression, an unresolved reference, a reachable step
    with no way out, a lease too short; one sentence each.
18. W5: a two-step workflow end to end; rework returns to the instance that did the step, and to any
    after `return_after`; a pass-on to a role at capacity is withdrawn and offered again.
19. W5: three children with `all` fan-in: the parent is done when the third ends `landed`, and takes
    the named outcome when one does not; a dependency holds a step; a cycle raises attention.
20. W5: a metric condition is met only after holding for D; a gap resets it; a missing series never
    meets it; it fires once per entry; its `metric:<series>` fact is in the log, on no bus, and named
    on the item's page; a metric `on` moves the item.
21. W5: a done-when from a source without access is recorded, not counted, and listed as not counted;
    the drift test (§8) passes.
22. W6: ten items through the task loop on the reference machines, one rejection and one gate
    conflict; §9's three checks pass; the Machines page shows worker, reviewer, merge_gate and
    coordinator with the hand-offs worker → reviewer → merge_gate.
23. W7: every `POST`, `PUT` and `DELETE` under `/api/plugins/workflows` answers 405 (UX is W7's gate).

## 13. Open questions

Settled in round 1: dispatch (D17); stale completions and counts (words, §7); foreign data (a named
machine links it); how the Supervisor writes definitions (§10); person steps (no lease, `within`).
Open: (1) **log order** for the position view: a late outside fact counts when it arrived; right for
the ledger's "what happened"? (2) **the measuring interval**: does the Piles page want faster than
15 s? (3) **the program host's home**: here, or a plugin beside the agents' host? (4) **the file
bus's retention defaults**, once rotation exists.

Left to others: the declared layer and the machine envelope (proposal 2); the Supervisor's duties,
the `kind` key's other schemas, the agents' host answering `offer.made` (proposal 4); the desk
showing person offers (orchestra-desk, later); plugin collectors' provenance and `pile` as a place (core task C7, with proposal 5); file bus
rotation (core task C6, later);
notes §12's other open items (M0).
