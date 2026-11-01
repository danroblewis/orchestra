# Workflows: a plugin for any company's workflows

Status: draft for review, 2026-11-01. Nothing built. Proposal 3 of `design-backwards.md` §7,
written from `design-backwards-notes.md` §1–§8, §10 and §12; the owner's decisions are D21 in
`docs/roadmap/decisions.md`. It builds a new private repository, `~/orchestra-workflows`
(plugin `workflows`). Nothing is copied from `~/orchestra-tasking`: its SPEC was read as a list of
capabilities only. The owner: "Do not let yourself be bound by the initial implementation of
Tasking. It was only a prototype, we are building the correct thing now - a Workflows system."

**Invariants.** This proposal amends no rule of `AGENTS.md`. The plugin obeys every rule from
outside the core; §2.9 asks the core for one change (file bus rotation), which keeps rule 5 as it
is and changes the bus interface by one method. Where a note conflicts with a rule, the rule wins
and the place is marked **(rule n)**.

Contents: 1 Purpose · 2 The record · 3 Items have no status · 4 Piles · 5 The floor · 6 Resources ·
7 The vocabulary · 8 What lives where · 9 The examples · 10 Pages and tools · 11 Packaging ·
12 Build order and acceptance tests · 13 Open questions.

---

## 1. Purpose

A generic workflow system: "capable of handling any existing workflow, from any company. Like some
companies have Release Candidates and Release Candidate verification steps. Some companies have
multiple releases out. We might see a staged production rollout, we might see customer-owned
deployments. We might see multiple concurrent release branches that all need hotfixes."

Three parts, each usable without the next:

1. **The record** (§2): every fact about every item, in the item's own log, folded into snapshots.
2. **The floor** (§5): the only thing that turns "work exists" into "a machine is doing it":
   offers, claims, leases, capacity, resources, taking back silent work, escalation.
3. **Workflows** (§7): definitions, in a fixed vocabulary, that turn facts into piles (§4) for the
   floor to offer from.

The task system's loop (write → review → gate → done) becomes the first example (§9), written
fresh against the floor's contract. The prototype is retired by not installing it: "our tasking
system is already a separate plugin, so we can just not include it to get rid of it." The two
speak different event names (§5.6), so both may be installed during the change-over, but one
project should run its work through one of them. A naive task system for demos is written later
on top of Workflows, "and we would expect people to customize it for the workflows they actually
experience at work."

What the plugin is not: it is no part of the core (rule 1); the core learns no word of it. It
declares no model: piles are proposed stocks that discovery confirms or refutes (§4). It never
reads `orchestra.toml` itself (rule 10). Its pages are read-only (rule 9; §10).

## 2. The record

### 2.1 Items are logs of facts

An **item** is what one instance of a workflow is about, named by the CloudEvents `subject` of
every event about it: a Jira key, a pull request, an alert, a release candidate. The owner: "a
CRDT ... built from an event log for every interaction, only viewable by combining all events."
An item's record is its own log of **facts**: the events about it, copied whole (envelope and
`data`) from the bus in bus order, each with the bus offset it was read at.

An event is a fact about item X when its `subject` is X and X is **known**: some workflow's
`starts` matched an event about X (§7), an `item.requested` named X, or a relation fact made X a
child of a known item (§7.3). Events about unknown subjects are not recorded: the record holds
items, not the bus.

**Not facts**, and never written to an item's log, though their subject is the item:

| Excluded | Why |
|---|---|
| `offer.alive` (the floor's heartbeat, §5.3) | a lease signal; the floor reads it from the bus |
| `session.*`, `agent.*` (the agents' host's session signals) | runtime noise of a machine, not of the item |
| `orchestra.*` (model changes, process events, announcements) | Orchestra's own; never about an item |

The list is the plugin's, stated in its SPEC and tested; a workflow cannot add to it. In the
live run of 2026-10-31 these were 186 of 406 events (`task.working` 63, `session.started` 42,
`session.settled` 42, `orchestra.model.changed` 39); what remained was about 10 facts per ticket.

Reading foreign `data`: the plugin may read the `data` of its own event types and of event types
other packages publish as a protocol (PLUGINS.md §7: the bridges' `github.*`, `jira.*`). It keeps
every fact whole, and reads `data` only where a definition names it (§7.2); the core still reads
only the envelope (rule 3).

### 2.2 Folds are order-independent per field

The bus is one totally ordered log, so the record is event sourcing with a single writer: every
fold is deterministic and snapshots never conflict. The folds are still written so that each
field's answer does not depend on arrival order, so that a bridge's late fact (an older `time`,
appended later) needs no insertion and no eviction of any snapshot:

| Part of the snapshot | Fold | Set by |
|---|---|---|
| **fields** (`jira_key`, `priority`, `pr`) | last writer wins by event `time`, ties broken by event `id` | `item.fact` `set` (§5.6) |
| **sets** (labels, notes, links) | add-wins set: an element is in when an add has no remove that names that add's event id | `item.fact` `add` / `remove` |
| **counters** (rework rounds, nudges sent) | sum | `item.fact` `count` |
| **seen** (per event type: count, first and last time, last source, last id) | count and min/max | every fact, by its envelope |
| **relations** (parent, children, depends on) | add-wins set | `item.related` |
| **ended** (closed, archived, deleted) | set once; the earliest `time` wins | `item.closed`, `item.archived`, `item.deleted` |

A view that needs time order (a timeline on the item's page) sorts at view time. Where a
workflow's position is computed, §3.2 says why that one view walks the log in log order.

Every value keeps its provenance: the event id, source and time that set it. The item's page
shows it beside the value (§3.4).

### 2.3 Snapshots and the index

- **Per-item snapshot**, keyed by `(item, log length)`: written by the recorder after each fold.
  A snapshot whose length is not the log's length is stale and is folded again from the log (or
  from the checkpoint, §2.4). Reading one item's page folds its log live (kilobytes) anyway, so
  the page can show provenance; the snapshot serves lists.
- **The index**: one file of every open item's snapshot summary (fields, sets, seen, relations,
  each workflow's position, the floor's holder, the piles it is in). Piles query it (§4). About a
  megabyte of JSON at a few thousand items, rewritten atomically once per tick, never per event.
  SQLite when that hurts; nothing above the index changes.

```
snapshot.json  {"item": "PROJ-123", "length": 14, "bus_offset": 90211,
                "fields": {"jira_key": {"value": "PROJ-123", "id": "…", "source": "jira", "time": "…"}},
                "sets": {...}, "counters": {...}, "seen": {"github.pr.opened": {"count": 1, ...}},
                "relations": {...}, "ended": null,
                "at": {"delivery": {"step": "review", "since": "<event id>", "held_by": null}}}
```

### 2.4 Checkpoints and the archive

An item with a Jira comment every hour for a year has about 9,000 facts and 4 MB: fine on disk,
slow to fold. When a log passes **2,000 facts** or **30 days** since its last checkpoint, the
recorder writes a **checkpoint** (the fold up to position k), moves the log's prefix to a
compressed archive file beside it, and rewrites the live log as the tail. The last **300 facts**
are never compacted, so recent history stays explainable. The archive keeps the audit; the hot
path never reads it. The thresholds are settings of the plugin with these defaults.

### 2.5 The lifecycle: leaving the system

The owner: "If an Item leaves our system, if there's a 'delete' or 'archive' event emitted by it,
we would expect all of the events for it to be removed. If we do compaction for retention, we
might flatten the earliest messages to a static form."

An item is **closed** when an `item.closed` or `item.archived` fact arrives, or when every
workflow that reads it has reached an end step (§3.2; no event says so: that would be an echo of
facts already recorded). Then, by the policy of the workflow that keeps it longest:

1. **closed**: the log is kept; the item leaves the index's open set, so no open pile counts it;
2. after **N days** (default 14): the log is compressed into the archive; the final snapshot is
   written to `final/`;
3. after **M days** (default 180): the archive is dropped; the final snapshot (a few hundred
   bytes) is kept for good. It is the "flattened static form", kept because the ledger and the
   owner's yearly review need "what I did" long after the facts are useless.

An `item.deleted` fact skips to the end and removes the final snapshot too. The policy is per
workflow (`lifecycle`, §7): a PagerDuty alert can be dropped in a week; a delivery item's final
snapshot is kept forever.

**What survives deletion.** The model never reads item logs: pile sizes are measured into the
metrics store (§4), so the system dynamics history is intact after items are gone. The Machines
page reads only bus envelopes, with the bus's own retention.

### 2.6 The budget, from the measured sizes

Measured on 2026-10-31 (`~/.orchestrator/orchestra-sample-live-*`): 406 events, 49 items, median
2 events per item, maximum 32; 120 to 500 bytes per event (509 B average in the live run, 122 B
in a program-only run of 9,118 events); about 10 facts per item once the noise is out, 3 to 5 KB
per item. The design is held to these, and W2's tests use them as fixtures:

| Budget | Value |
|---|---|
| Record of a year at 30 items a week (1,560 items × 10 facts × 500 B) | under 10 MB live and archive together |
| Index at 5,000 open items | under 2 MB; rewritten in under 100 ms |
| Folding one item's live log (≤ 2,300 facts after a checkpoint) for its page | under 50 ms |
| Recorder throughput on the file bus | at least 2,000 events a second (the 9,118-event run in under 5 s) |
| Final snapshot | under 1 KB each |

For comparison the disk goes elsewhere: the metrics store was 448 MB and worker artifacts 709 MB
in those state directories.

### 2.7 The recorder

The recorder follows the bus (`Events.after(offset)`) and copies each fact into its item's log.
It is infrastructure, never a machine (rule 2): it publishes nothing and announces nothing.

- **Its offset survives restarts.** `recorder.json` holds the bus offset it has applied up to,
  written after the item logs it covers. A crash between the two re-reads a few events; each
  item's snapshot holds the bus offset of its last fact, so a fact at or before it is skipped.
  At-least-once reading, exactly-once recording.
- **The bus changed under it.** When the bus's end is below the stored offset (a file bus
  replaced) or its first held offset is above it (rotation or broker retention passed it, §2.9),
  the recorder records the gap (offsets and time) in `recorder.json`, reads on from the first
  held event, counts it in `workflow_record_gaps_total`, and the Items page says which items may
  miss facts. It never guesses the missing facts.
- **Order of work per tick:** read the bus → append facts → fold the touched items → write their
  snapshots → write the offset → rewrite the index → apply the lifecycle.

Everything lives in the state directory (rule 5):

```
~/.orchestrator/<key>/workflows/
  recorder.json                  offset, gaps, the excluded-types version
  index.json                     open items' summaries (index.sqlite later)
  items/<ab>/<sha1 of subject>/  one directory per item; the subject is inside, not in the name
    log.jsonl                    live facts (the tail after a checkpoint)
    snapshot.json                keyed by log length
    checkpoint.json              the fold up to position k
    archive-<k>.jsonl.gz         the compacted prefix
  final/<ab>/<sha1>.json         final snapshots of closed items
  floor.json                     offers, holders, leases, the clock's last occurrences (§5)
  resources/<kind>.json          each unit of each kind: state, holder, last setup
```

### 2.8 The bus is transport, never the record

Retention is the broker's (Kafka's `retention.ms`, Redis stream trimming). Once the recorder has
copied a fact, bus retention no longer matters to items. Nothing in the plugin reads past item
state from the bus except the recorder, and the recorder reads from offset 0 only to rebuild a
lost record while the bus still holds it. The per-item logs are a copy of the one bus, kept by
the plugin; they split nothing (rule 4): every fact was published on the project's one stream.

### 2.9 A core change to request: file bus rotation

The file bus has no rotation and grows without bound (notes §12). Its offsets are line numbers,
and every reader (the web's indexes, the agents' host, the recorder) holds them as cursors. The
request to the core, as its own task in `~/orchestra_2`:

- **Segments, global offsets.** `events.jsonl` stays the live segment. When it passes
  `[events] rotate_mb` (default 64), it is renamed to `events.d/<base>.jsonl`, where `<base>` is
  the offset of its first event, zero-padded; `events.d/live.base` records the live segment's
  base. An offset keeps its meaning (the number of events before a point in the whole stream),
  so every cursor held today stays valid. An existing unrotated file is a live segment with base 0.
- **A lock.** Appends and the rotation take an exclusive `flock` on `events.lock`, so no append
  lands in a segment after it was sealed. Appends stay one write of one line.
- **Retention.** `[events] keep_mb` / `keep_days` drop the oldest sealed segments, never the live
  one. Sealed segments may be gzipped.
- **One new method, `EventBus.start()`:** the offset of the first event still held (the oldest
  segment's base; Kafka's log start offset; for Redis and RabbitMQ, whatever their backends'
  offsets mean after trimming). `read(since)` with `since` below `start()` reads from `start()`;
  a reader compares the two to know it missed events. The bus conformance suite (`tests/bus`)
  gains a trimming test for every backend.
- `end()` becomes cheap: the live base plus the live segment's lines.

This changes `orchestra/bus/` and SPEC's bus section, not a rule. The recorder works without it
(the file grows, as today) and uses `start()` when it exists.

## 3. Items have no status

### 3.1 State is a function of facts

The owner: "we could model the 'state' as a function of the task's variable fields, and determine
the properties as needed. We could define several state machines on top of a Task, and use them
for different things." There is no `status` field, no transitions table, no version bump and no
"cannot move X → Y" error, and so none of the recovery states where the prototype's bugs lived.
"Which step is it at" is computed from the facts by a workflow, when needed.

**Several workflows read one item.** The delivery workflow, a "Jira hygiene" condition, the
ledger and the morning brief are each a function over the same facts; none owns the item. A pull
request is in the owner's delivery workflow (as a child of the Jira ticket, §7.3) and in the
team's review workflow at once; each records its own position under `at.<workflow>`.

### 3.2 The position view

A workflow's position on an item is the one view that is a sequence: rework loops back, and "the
review was approved after the rework" depends on which came first. It is computed by walking the
item's facts **in log order** (the bus order, which is the order the floor itself acted in), from
the workflow's `starts` fact: each step is entered by the fact that led to it; it is done by its
done-when (§7) counted only from facts after it was entered; its outcome names the next step; an
`on` fact moves it whenever it arrives. A step with no next is an end. Log order rather than event
time, so the floor and the view never disagree about what happened when; a late outside fact
counts when it arrived (§13 q2).

### 3.3 Predicates and events: both

"If we change a task's Jira Ticket ID, that could be a 'has Jira Ticket ID' event, or it could be
a 'jira ticket ID modified' event." Both: the event is the fact (who changed it, when, from what
to what: the ledger wants it); "has a Jira key" is a predicate over the current fields (piles
want it). Record the first, compute the second.

### 3.4 Explainability

"PROJ-123 is waiting for review" must show which facts make it so, or nobody can debug it. An
item's page folds the log live and shows, for each workflow: the step, the fact that entered it,
the done-when facts seen since and those still awaited, each guard's clock; for each field its
value and the event that set it; for each pile it is in, the predicate and the fact that satisfies
it; and the facts **not counted**, with why (from a source with no access to that step, §3.5).

### 3.5 Access replaces the transitions guard

The transitions table guarded the state; nothing does now except **access**: which machine may
make which fact count. Every fact is recorded (the log is what happened), but a fact counts
toward a step only when its source may make it:

- for a role's step, the instance holding the step's offer (§5.2);
- for a program step, the program's instances;
- for an outside wait, the sources the bridge publishes as (for example `github`, `person.*`);
- `item.fact`, `item.related` and the end facts, from any announced machine, unless the workflow
  restricts a field to named sources.

The outer gate stays the core's: who may publish at all (the events endpoint's token, the agents'
session token and role check). Machines still act on something simple: the floor's offer, never
the item's facts.

## 4. Piles

A **pile** is a named query over item snapshots in the index: "has a Jira key, no pull request,
nobody holds it". Factories "work in piles, where the pile is a pile of similar things, a queue of
items considered uniform or worth sorting into other piles."

- **Step piles, without declaring them.** Every step of every workflow makes two piles:
  `<workflow>.<step>.waiting` (at the step, nobody holds it) and `<workflow>.<step>.held`. These
  partition the workflow's open items.
- **Declared piles** are a conjunction of predicates of fixed forms, and nothing else: at step S
  of workflow W; held or not held; field F set, unset, or equal to a value; set L contains a
  value; event type T seen or not seen; related (has an open child, a dependency not yet done);
  open or closed. No expressions (§7).
- **Dispatch picks by priority**: from a step's waiting pile, the item with the lowest `priority`
  field (1 soonest, 5 if unset), then the longest in the pile.

**Pile sizes are series** (rules 6 and 7). The recorder and the floor are infrastructure and never
write metrics directly (rule 2). The plugin declares an instrument, `workflows.piles`
(`Plugin.collectors`, a command printing the Prometheus text format from the index), run on the
plugin's measuring interval (15 s by default) whether or not anything changed:

| Series | Kind | Why discovery needs it |
|---|---|---|
| `workflow_pile_items{workflow, pile}` | gauge | the level |
| `workflow_item_moves_total{workflow, from, to}` | counter | between step piles: an outflow of `from` and an inflow of `to`, so discovery connects them (`from="start"` and `to="end"` for the edges of the workflow) |
| `workflow_pile_entered_total{workflow, pile}`, `workflow_pile_left_total{workflow, pile}` | counters | for declared piles, which overlap and so have no `from`/`to` |
| `workflow_pile_seconds_total{workflow, pile}` | counter | time spent by items that left: mean time in pile = this ÷ left |
| `workflow_pile_oldest_seconds{workflow, pile}` | gauge | the age of the oldest waiting item (a guard's input, an effect's candidate) |

The moves are counted by the recorder when a fold changes an item's piles, kept in the record,
and printed by the instrument. So **piles are the stocks and the moves between them are the
flows**, found by discovery's conservation balance like any other. The workflow does not declare
the model; it is made of it. A pile discovery refutes is a finding about the workflow, not a
failure of discovery.

## 5. The floor

The owner: "a huge thing that Tasking gives us that nothing else gives us is the ability to
actually launch and setup Machine instances. That's the most important thing it does right now,
because there is nothing else that does it, and if nothing else does it then we would never have
anything that does any actual work."

### 5.1 What it does, and its boundary

The floor keeps **capacity** per role, makes **offers**, records the first valid **claim**, keeps
the **lease** by **heartbeats**, prepares and holds **resources** (§6), takes **silent work** back,
and **escalates** to a planner role when a guard is passed.

**Today's split is kept.** The offer side decides what is next and offers it with the resource
prepared; the other side answers offers for its roles by starting a machine instance: the agents'
host by starting a session with its token, prompt and environment (orchestra-agents SPEC §3: it
takes the offer as the lowest free instance of the role, claims it, reads its claim back before
spending anything); the plugin's program host (§5.5) by running a command; a person through the
desk and the bridges. **The offer side never knows what a machine is made of.**

**It runs without any workflow.** The Supervisor's "do this once" (`item.requested` with a `role`
and no workflow: an item with one step), a recurring job (a schedule, §5.4), an alert: each is a
pile the floor offers from. So it is built first (W4), and workflows are a layer that produces
piles for it (W5).

**One plugin, a hard boundary inside.** The record (`record/`), the floor (`floor/`), the
definitions (`define/`) and the program host (`programs/`) are packages that import each other
only through stated APIs: `floor` reads the record through its query API; `programs` imports
neither and speaks only the bus contract, as an outside machine would. A test enforces the
imports. Splitting the floor into its own plugin later is then cheap.

**Out of the core.** The core's launcher keeps the plugin's processes running and learns nothing
about engagements (rule 1).

### 5.2 Offers, claims, leases

Each tick (default 3 s), after the recorder:

1. **Follow the bus**: the first valid claim of an offer on the bus holds it (the bus's order
   decides a race; a loser is told nothing and knows by reading); a heartbeat extends the lease;
   an `offer.finished` ends the turn and its outcome is a fact on the item.
2. **Take back**: an offer nobody claimed within its lease is withdrawn and the item rests before
   it is offered again (60 s, doubling, at most 15 min, cut short when a machine that listens for
   offers announces itself); a held offer with no heartbeat for its lease is taken back as a
   crash ("no zombies"); rework addressed to one instance and not claimed within the return
   timeout goes to any instance of the role.
3. **Guards**: a `within` passed or a retry limit reached raises attention to the workflow's
   planner role (default `supervisor`), once per guard per entry into the step, or moves the item
   to the step the guard names.
4. **Conditions**: metric done-whens (§7.2) are read from the metrics store.
5. **Offer**: for each role under its capacity and not paused, the best ready item of each step
   pile whose `who` is that role, once its resources are claimed and prepared (off the tick: a
   preparation never blocks the loop).

**Capacity** is per role, `[workflows.roles.<role>] capacity` in the configuration, read through
`project.config` and changed by the Supervisor with `project.config_edit` (rule 10). Every offer
not yet claimed and every held turn counts against it. **Pause** is `[workflows] paused` or per
role. Stopping one holder is a planner's request on the bus (`offer.withdraw_requested`), which
the floor answers with `offer.withdrawn`: an observable act, not a page button (rule 9).

A machine accepts only what it can do within the lease, and stops what it started when an
`offer.withdrawn` names its offer or instance.

### 5.3 Who the floor publishes as

The floor is never a source (rule 2; its publish refuses its own name). It publishes as the
machine whose responsibility it implements:

| Act | Published as |
|---|---|
| offering, withdrawing an unclaimed offer, a condition met, an answer to a withdraw request | `dispatch/<workflow>`, an instance of one `dispatch` machine (kind program, continuous), announced by the floor with what it listens for; one-off and scheduled items use `dispatch/floor` |
| taking back a held turn | the role whose turn it was (`worker`), `instance` in the data |
| attention on a step | the role whose step it is; for a wait, `dispatch/<workflow>` |
| a schedule's start | `schedule/<name>` (kind program, scheduled), announced at its first occurrence |

Whether dispatch should be an instance of the workflow's planner instead (the prototype's
`coordinator/dispatch`) is §13 q1.

### 5.4 Starts by the clock

A schedule ("start an instance of W every weekday at 8") is a wall-clock time in an IANA zone,
following daylight saving: a skipped time is due when the clock reaches it, a doubled time once.
Each occurrence has an id `<name>@<local due time>` kept in `floor.json`, so a restart or a
second tick never makes it twice; after downtime only the latest missed occurrence is made, marked
late; `if_open: skip` (the default) makes nothing while the previous occurrence's item is open.
Requirements learned from the prototype's recurring tickets; the syntax is the definition's (§7).

### 5.5 The program host

The other half for programs, inside the plugin but behind the boundary: for each program machine
in `.orchestra/machines/` (§8) it announces the machine's instances (`<name>/<n>`, kind program,
mode ad hoc, `listens_for: [offer.made, offer.withdrawn]`), claims offers for the program's role,
runs the command in the offered resource with the brief on stdin and `ORCHESTRA_OFFER`,
`ORCHESTRA_ITEM` and one `ORCHESTRA_RESOURCE_<KIND>` per held resource in its environment, sends
`offer.alive` while it runs, and finishes with the outcome its exit code maps to (the machine's
own table: `0 → landed, 1 → rejected, 2 → conflict`, anything else `error`) and its output's tail
as the summary. It is infrastructure: it publishes only as the program's instances. The merge
gate, a SAIL failure triage and a flake check are program machines of this kind.

### 5.6 The machine contract

A page in the plugin (`docs/machine-contract.md`) that a machine author follows, program or agent,
in any language (over `orchestra.events.Events` or the events endpoint). The event names are new;
none of the prototype's `task.*` names is reused.

| Event | Published by | `data` |
|---|---|---|
| `offer.made` | `dispatch/<workflow>`, or a holder passing its work on (below) | `offer` (`<item>.<step>.<8 hex>`), `role`, `item`, `workflow`, `step`, `to` (an instance, for rework), `lease_s`, `brief` (the item's fields and the step's text), `resources` [{kind, id, handle}], `outcomes` (the names the step accepts), `ends` (the offer this one ends, when passed on) |
| `offer.claimed` | the instance taking it | `offer` |
| `offer.alive` | the holder, at least every 30 s | `offer`, `text` (what it is doing, one line) |
| `offer.finished` | the holder | `offer`, `outcome` (one of the offer's), `summary`, `facts` (an `item.fact` body, applied with it) |
| `offer.withdrawn` | dispatch, or the floor as the role | `offer`, `reason`, `instance` |
| `offer.withdraw_requested` | a planner | `offer`, `reason` |
| `item.requested` | a planner, a machine fanning out | `workflow` or `role`, `brief`, `parent`; the subject is the new item's id, chosen by the requester |
| `item.fact` | any announced machine | `set` {field: value}, `add` / `remove` {set: [values]}, `count` {counter: n} |
| `item.related` | any announced machine | `kind` (`parent`, `depends_on`), `other` |
| `item.closed`, `item.archived`, `item.deleted` | any announced machine | `reason` |
| `condition.met` | `dispatch/<workflow>` | `workflow`, `step`, `series`, `value`, `held_s` |
| `attention.needed` | as §5.3 | `to` (the planner role), `reason`, `workflow`, `step`, `guard` |

Every event of a turn has the item as `subject` and the offer that opened the turn as
`causationid`. What a machine does, step by step:

1. **Announce** (`orchestra.machine.started`): its kind, mode, and `listens_for: [offer.made,
   offer.withdrawn]` (with the roles it fills in its announcement, passed to its card).
2. **Hear an offer** for a role it fills (`to` absent, or its own instance).
3. **Claim** it (`offer.claimed`), then **read the bus from the offer to its claim**: if another
   valid claim came first, it lost; start nothing that costs (tokens, a build) before this.
4. **Work** in the resources handed to it; send `offer.alive` at least every 30 s.
5. **Finish** with one outcome (`offer.finished`), leaving each resource at a committed, clean
   state, since the next step starts there. Or **pass the work on directly**: publish the next
   step's `offer.made` itself with `ends` naming its own offer and the same resources (a worker
   asking its reviewers), which the floor records as that step's offer if the step's `who` matches;
   the event map then draws worker → reviewer with no dispatch between.
6. **Stop** when an `offer.withdrawn` names its offer or instance, whatever it read before.

A machine never publishes as the floor and never tells the floor a state; the floor and the
workflows compute states from these acts. The agents' host answering `offer.made` is the agents'
half of the floor and stays in orchestra-agents; until it is written, the examples run on
scripted machines (§9).

## 6. Resources

The owner: "I like the part about Resources. I don't know how to make it generic, but some part of
it will be user-configurable in the target repo."

A resource **kind** is a name, a capacity, and three commands the target repository provides:
**make** one, **reset** one between uses, **release** one. Others of the same shape: a staging
environment, a database snapshot, a customer sandbox, a rate-limited API budget, "one person's
attention". The floor knows only: **claim before the step, hold across hand-offs, free when the
holder drops**. A step's `needs` names kinds; an item keeps a held unit from one step to the next
while the next step needs the same kind, and the unit is freed when the item leaves those steps,
ends, or its holder is taken back. A pool is a capacity limit on a flow, the most ordinary
structure in system dynamics; `floor_resources{kind, state}` (free, held, preparing, waiting,
broken) is measured by the plugin's floor instrument.

**A Jira ticket or a pull request is not a resource.** Nothing is scarce about it; it is a fact on
the item.

Commands run in the repository root with `ORCHESTRA_RESOURCE_KIND`, `ORCHESTRA_RESOURCE_ID` and the
unit's handle in the environment, under a timeout per command; make prints the handle (a path, a
URL); a non-zero exit is a failed unit, tried again after a back-off (1 min doubling, at most 30),
and said once to the planner role.

**The worktree kind, first.** It ships with the plugin as a ready-made kind (git commands as its
make, reset and release) and takes the repository's settings. Its requirements, learned from the
prototype's pool, adoption and setup:

1. A pool of at most `capacity` worktrees in the state directory; never one beyond it. A full pool
   is back-pressure: the step waits and the waiting count is measured; it asks no one.
2. **Reset** before each use: abort an unfinished merge or rebase, discard tracked changes, remove
   untracked files, keep ignored ones (caches: the reason to reuse) unless told otherwise, check
   out the item's branch (made from the base when new). A unit not clean after a reset is broken
   and not used.
3. **The work is on the branch, not in the worktree**: a waiting item holds no worktree; a holder
   commits before passing work on.
4. **Rework prefers the unit the item last used** if it is free; a preference, never a wait.
5. **Adoption** of worktrees the owner already has, listed in the settings: only worktrees of the
   project's repository, never the project root; adopted only if a reset would lose nothing (no
   uncommitted or untracked unignored file, no operation in progress); otherwise refused, recorded
   with what was in it, said once to the planner, looked at again at most once a minute. An
   adopted unit is marked in its git directory (never its working tree) with the project's key;
   one marked by another project is refused.
6. **Setup**: the repository's command run once per unit made or adopted, before its first use,
   recorded by a hash of the command in the unit's git directory, so it runs again only when the
   command changes or the unit is made again, never on a reset. A failure leaves the unit unused.
7. **Preparation off the loop**: making, adopting and setting up run in workers of the floor; the
   tick waits at most two seconds for them and offers what finished on a later tick. Shutdown ends
   setups under way; a half-made unit is made again on start.
8. A crash never leaves a unit held: a holder taken back frees it, and a dirty unit is reset
   before its next use. Units on disk the record does not know are reported, never deleted.

## 7. The vocabulary, and nothing beyond it

### 7.1 The words

A workflow is written in exactly these words, because they are the capabilities of notes §1 and
no more. Anything that needs logic is a machine (a program step or an agent step), never an
expression or a script in the definition. A workflow that cannot be written in them is a finding
about the vocabulary, taken one case at a time.

| Word | Meaning |
|---|---|
| **item** | what one instance is; the subject key: a Jira ticket (with its pull requests as children), a pull request, an alert, a release candidate, a hotfix with a child per release branch, a customer × release pair |
| **starts** | what begins an item: an event type (a bridge's `jira.issue.assigned`), the clock (a schedule, §5.4), or a request (`item.requested` naming the workflow) |
| **step** | one stage, with the fields below |
| **who** | a **role** (any machine announcing it fills the role), a **program** (a program machine, §5.5), an **outside** system (a wait: nothing is offered), a **person** (the owner's own act; a machine may prepare it, never do it), or the **outbox** (a write as the owner, after approval) |
| **needs** | the resource kinds claimed before the step and held across hand-offs (§6) |
| **done-when** | an event type with the item (or, with `of children`, a child) as subject, optionally a value of one named `data` field (`outcome`, `conclusion`); or a **metric condition** (§7.2) |
| **guards** | `within` (a duration, optionally in working hours) and retry limits (`rounds`); passed, it raises attention to the planner role or moves the item to a named step |
| **outcomes** | where each result leads: success → the next step, failure → an earlier one, a named outcome → a named step; a step with none is an end |
| **on** | an event that moves the item to a step whenever it arrives (`github.pr.changes_requested` → write) |
| **rework** | a move back to an earlier step is offered `to` the instance that did that step; after the return timeout (default 60 s), to anyone of the role |
| **relations** | children (fan-out; the parent's step done when all children are at an end: fan-in) and dependencies (a step not offered until the other item is at a named step or ended) |
| **lifecycle** | the retention policy once closed (§2.5): compress after, drop after, keep the final snapshot or not |

Two words the prototype never had, both needed by the examples: **relations** and **metric
conditions**.

### 7.2 Metric conditions

A done-when may be "series S with labels L is above or below a threshold for duration D": "the
canary's error rate under 0.1% for 30 minutes". The floor reads it each tick from the metrics
store (`orchestra.metrics`, rule 5) and, when it has held for D, publishes `condition.met` as
`dispatch/<workflow>`; that fact is what the position view counts, so the item's page shows which
reading made the step done. A series missing for longer than D is not "below": the condition
waits and the guard runs. This is where instruments feed workflows directly, and where a staged
rollout's "advance when the canary is healthy" lives. Reading a series never makes a machine of it
(rule 7).

### 7.3 Relations

A machine fans out by publishing `item.requested` for each child with `parent` set (the hotfix's
port program, one child per release branch); the recorder records the relation on both logs. A
link made after the fact (a pull request opened for a Jira ticket) is `item.related {kind:
parent}`. A child's facts stay in the child's log; a parent's step reads them only through
`of children` and fan-in.

### 7.4 The SAIL delivery example as the step table

Set aside for now (notes §11), but kept here because it exercises every word. Item: a Jira ticket.
Starts: `jira.issue.assigned` to the owner. Planner: `supervisor`. Lifecycle: keep the final
snapshot forever.

| Step | Who | Needs | Done when | Guards, outcomes, on |
|---|---|---|---|---|
| keep the Jira ticket current | role `jira-keeper` (an agent drafts), the outbox sends | | `jira.issue.updated` | a parallel child item, so it runs alongside the rest |
| write | role `worker` (an AI worker, or the owner) | worktree | `offer.finished` ready, with the commit | blocked → attention |
| open the PR | person: the owner pushes and opens it; the worker drafted the description | worktree | `github.pr.opened` (the PR becomes a child) | within 1 day, else attention |
| ci | outside: GitHub, via the bridge | | `github.checks.completed` of children, `conclusion` | success → review; failure → write (rework) |
| review | outside: people | | `github.pr.approved` of children, enough of them | on `github.pr.changes_requested` → write; within 1 working day → nudge |
| nudge | role `nudger` (an agent drafts the message), the outbox sends | | `outbox.sent` | → review |
| sail | outbox: adds the SAIL label, after the owner's approval | | `github.pr.labeled` | |
| sail-check | outside: SAIL's action | | its check result | success → end; failure → triage-failure |
| triage-failure | program `sail-triage` | | `offer.finished` | company-wide → sail-check (wait and retry, rounds 3); otherwise → write |

"Enough of them" (a count of approvals) is the one place the table strains the vocabulary: §13 q4.

### 7.5 Persistence, not interface

The owner: "If TOML is the interface for setting this up, it will be a miserable experience. If you
insist on using TOML, it can be as a persistence format." A definition on disk is JSON, written and
read by programs; the owner describes the workflow to the Supervisor, the Supervisor writes it,
the Workflows page draws it. The shape, for programs only:

```
.orchestra/workflows/task-loop/workflow.json
{"name": "task-loop", "item": "a piece of work", "planner": "coordinator",
 "starts": [{"request": true}],
 "steps": [{"name": "write", "who": {"role": "worker"}, "needs": ["worktree"],
            "done_when": {"event": "offer.finished"},
            "outcomes": {"ready": "review", "blocked": "@attention"},
            "guards": {"within": "2h"}}, ...],
 "piles": [{"name": "unowned", "where": [{"field_unset": "owner"}, {"held": false}]}],
 "lifecycle": {"compress_after": "14d", "drop_after": "180d", "keep_final": true},
 "settings": {"label": {"type": "string", "default": "SAIL"}}}
```

The loader refuses any key it does not know, any step reference that does not resolve, and any
reachable step with no way out; it reports one sentence per problem.

## 8. What lives where

**A repository's `.orchestra/` folder and a plugin have the same shape.** The core already loads
`.orchestra/plugins/` and `.orchestra/overrides/` by file (rule 10); this extends a rule we have.

```
.orchestra/                      (in the target repository; a plugin package holds the same folders)
  workflows/<name>/workflow.json   definitions (§7.5)
  machines/<name>/machine.json     program machines: command, interface (args, env, stdin),
                                   outcomes by exit code, role, instances; scripts beside it
  resources/<kind>/kind.json       capacity; make, reset, release commands (scripts beside it)
  instruments/                     collect scripts the project's [[collect]] entries name (as today)
  plugins/, overrides/             the core's, unchanged
```

| What | In `.orchestra/` | From a plugin |
|---|---|---|
| Workflows | the company's: delivery through SAIL, RC verification, hotfix ports | reusable, with settings: "GitHub PR review", "staged rollout", the task-loop demo |
| Machines | programs (scripts in the repository); agent roles (the agents plugin's own folder); person roles | the agent runtime, bridges, outbox, generic programs (a merge gate, a flake checker) |
| Resources | kinds with commands and capacity | the worktree kind |
| Instruments | collect scripts, series definitions | scrapers for known systems |
| Intended model | none here: it is the core's, declared through the Supervisor (proposal 2) | none |
| Settings | the values: `SAIL`, `#team-reviews`, thresholds, in `[workflows.settings.<workflow>]` of the configuration | the schema of what a workflow needs filled in (`settings` in the definition) |

A plugin offers workflows by an entry point of the Workflows plugin's own
(`orchestra_workflows.packages`, naming a directory of the same shape), so the core's `Plugin`
gains nothing. Settings are read through `project.config` and changed with `project.config_edit`
(rule 10), so a value in the owner's private overlay reaches the workflow. Company-private
material that is not code (people, channels, tokens) stays outside the repository: `~/work-desk`
(D10), secrets in `~/.config` or the keychain.

**Promotion is packaging, never a rewrite:**

1. **It starts in `.orchestra/`**, specific and private: the SAIL label and the channel are written
   in.
2. **It gets parameters** when a second repository or a colleague wants it: the specific names
   become `settings` with a schema, their values move to the configuration. The Supervisor does
   this step.
3. **It becomes a package**: the folder moves into a plugin repository with a `pyproject` and the
   entry point; the original repository keeps its settings and the machines that are its own.
4. **It is shared**: installed as an extra; each repository fills in its own settings.

**The drift test** (in the plugin's suite): one example workflow is loaded from a repository's
`.orchestra/` and from a packaged copy with the same settings; the two normalised definitions must
be equal and the same scripted run must produce the same pile series. If promotion needs a
rewrite, the two forms have drifted.

**The Supervisor writes all of it.** No human reads or writes these files; the pages draw them.
Configuration is never the interface (D21).

## 9. The examples, and how each is tested

"We want some examples of how people would actually use this, and we want them tested." Each is a
tiny target repository under `~/orchestra-workflows/examples/<name>/` with its own `.orchestra/`,
scripted machines (programs, and agents on the agents' dummy harness: no model, no network), fake
bridges that publish the outside events on a script, and one test with three checks:

1. **the piles over time** match the script (from the metrics store, at named moments);
2. **discovery finds the declared stocks and flows** (the `model-acceptance` workflow);
3. **the event map shows the declared machines and hand-offs** (`/api/machines`), and no node, edge
   or source names the recorder, the floor or the program host.

| # | Workflow | Item | Piles | Who | What it exercises |
|---|---|---|---|---|---|
| 1 | **the task loop** (the demo) | a piece of work | write, review, gate, done; waiting and held of each | worker and reviewer roles (scripted), the `merge-gate` program | offers, claims, leases, rework to the same instance, the worktree held write → review → gate, attention after 3 rejections |
| 2 | team PR review | pull request | requested of me, read, commented, approved, merged, stale | an agent reads and drafts; the owner approves; the outbox nudges | the same PR in two workflows |
| 3 | on-call | alert | new, analysed, disqualified, awaiting the triage comment, fixing, runbook check | programs (correlated signals, SLOs, log error rates); an agent (the course of action); the owner (the fix) | an outside wait on a comment, metric conditions, a 7-day lifecycle |
| 4 | release-candidate verification | release candidate | cut, verifying, verified, rejected, released | a program cuts; verifier programs and agents; the release manager | a staging-environment resource per RC |
| 5 | hotfixes across release branches | hotfix, a child per branch | pending, ported, landed per branch, complete | a program ports; an agent resolves conflicts; people review | fan-out and fan-in |
| 6 | staged rollout | release | canary, 10%, 50%, 100%, rolled back | a program advances; rollback is an outcome | metric conditions, a guard per stage |
| 7 | customer-owned deployments | customer × release | notified, scheduled, deployed, verified, overdue | the outbox notifies; the bridge sees the deployment; an agent chases | long outside waits, many items per release |
| 8 | the owner's delivery through SAIL (§7.4) | Jira ticket | as its steps | as §7.4 | every word; set aside until the generic problem is solved (notes §11) |

The goal document's M5 numbers them X1–X7 in its own order (delivery first); the table above is
the order of building. The examples are the plugin's test suite and its documentation at once.

**The task loop as example 1.** Steps: write (role `worker`, needs a worktree; `ready` → review,
`blocked` → attention to `coordinator`), review (role `reviewer`, the worker passes it on directly;
`approved` → gate, `rejected` → write as rework; rounds 3 → attention), gate (program `merge-gate`
from the example's `.orchestra/machines/`, running the repository's checks on a merge: exit 0
landed → end, 1 rejected and 2 conflict → write as rework, else error → attention). Starts: a
request, or a schedule. The scripted worker and reviewer are new programs written against §5.6,
as the prototype's demo had a shell worker and a check reviewer written against its own contract.

## 10. Pages and tools

Pages, read-only for humans (rule 9), in Orchestra's frame:

- **Items** (`/items`): the index, filtered by workflow, pile, field; an item's drawer folds its
  log live: the timeline, each field with its provenance, each workflow's step and the facts that
  make it (§3.4), the facts not counted, its offers and holders, its relations, its resources.
  Gaps the recorder recorded are shown.
- **Piles** (`/piles`): each workflow's piles with their sizes over time (from the metrics store,
  the same series discovery reads), the oldest item, what waits on capacity or a resource.
- **Workflows** (`/workflows`): each definition drawn (steps, who does each, needs, guards,
  outcomes), its **coverage** (for each role, whether a machine announcing that it fills it is on
  the bus; a role with none is a hole), and where each item is now.
- The floor's live state (offers, holders, leases, resources by kind) is a panel of the Workflows
  page, not a page of its own.

No button changes anything. Every change goes through the Supervisor.

The Supervisor's tools live in orchestra-agents (W7 adds the first): `declare_workflow` and
`change_workflow` (write a definition, validated by the plugin's loader before it is written),
`declare_resource_kind`, `declare_program_machine`, `declare_pile`, `start_item` ("do this once"),
`schedule_item`, `set_capacity` and `pause` (through `project.config_edit`), `withdraw_offer` (the
bus request), `parameterize_workflow` (promotion step 2), `explain_item` (the facts behind an
item's state, for the chat). The plugin's `guide.md` tells the Supervisor how to choose (§11).

## 11. Packaging

- **Repository** `~/orchestra-workflows` (private, `danroblewis/orchestra-workflows`, created after
  a secret scan of its first commit); package `orchestra_workflows`; plugin and entry point name
  `workflows`.
- **`pyproject.toml`** as PLUGINS.md §9.2: `dependencies = ["orchestra>=1.0.0a1,<1.0.0rc0", ...]`
  (by name and range only, never a URL); `[tool.uv] override-dependencies` naming Orchestra from
  GitHub, with the dev extras' (`orchestra[sd]`) for discovery in tests; developing against a
  local checkout with `uv run --with-editable`.
- **The extra in the core**: `workflows = ["orchestra-workflows @ git+https://github.com/danroblewis/orchestra-workflows"]`
  in `~/orchestra_2`'s `[project.optional-dependencies]`, beside `tasking` and `agents`.
- **Processes** (`Plugin.processes`), only when the project has workflows, resource kinds or a
  `[workflows]` section: `workflows.floor` (the recorder, then the floor, in one loop, with
  `stop_grace_s` longer than a resource command's timeout) and `workflows.programs` (the program
  host), both `[sys.executable, "-m", "orchestra_workflows", ...]`, following their settings with
  `project.config_stamp()`.
- **Collectors** (`Plugin.collectors`): `workflows.piles` (§4), `workflows.floor` (offers open,
  holds, take-backs by reason, attention by guard, resources by kind and state), `workflows.record`
  (recorder lag in events, bytes live, archived and final, gaps). Instruments, not machines (rule 7).
- **Machines** (`Plugin.machines`): placeholders for `dispatch` and for each role, program and
  outside system the loaded workflows name and no machine has announced yet, so the Machines page
  shows the holes before anything runs. They never override what is observed and say nothing about
  flows (rule 2).
- **Pages, router, static** for §10; the router only reads.
- **`guide`**: how to model a workflow in the vocabulary, when a step is a program, an agent or a
  person, how to choose capacities, leases and lifecycles, the worktree kind's settings, which
  choices are the owner's (anything acting as the owner goes through the outbox).
- **`check`**: refuses a bad `[workflows]` section (unknown keys, a capacity below 0, a role named
  by no workflow) and a settings value a definition's schema refuses.

## 12. Build order (M4) and acceptance tests

| Id | Delivers |
|---|---|
| W1 | The repository: `pyproject`, `AGENTS.md` (the core's rules as they bind a plugin, plus: the four packages and their import boundary; no `task.*` names), `SPEC.md` from this proposal, the plugin registration, `docs/machine-contract.md`, an empty suite that runs |
| W2 | The record: the recorder, per-item logs, folds, snapshots, the index, checkpoints, the archive, the lifecycle, gaps; the excluded types; the `workflows.record` instrument |
| W3 | Piles: step piles and declared piles over the index; the move counters; the `workflows.piles` instrument |
| W4 | The floor, with no workflow: one-off and scheduled items, offers, claims, leases, capacity, take-backs, attention, withdraw requests; resources and the worktree kind; the program host; the contract page tested by a machine written only from it |
| W5 | Definitions: the loader for `.orchestra/workflows/` and for packages, the vocabulary and nothing more, the position view, relations, metric conditions, access |
| W6 | The task loop as example 1 in `examples/task-loop/`, on scripted machines |
| W7 | The Items, Piles and Workflows pages; `declare_workflow` in orchestra-agents |

Acceptance tests, each a program's check (pytest unless said):

1. W1: `uv run python -m pytest` exits 0; with the plugin installed, `GET /api/plugins` lists
   `workflows` with no error.
2. W1: an import test fails if `programs/` imports `record/` or `floor/`, or `record/` imports
   `floor/`.
3. W2: for every fixture of the measured run (406 events, 49 items), the recorder writes exactly
   the facts that are not excluded; no `offer.alive`, `session.*`, `agent.*` or `orchestra.*`
   event is in any item log.
4. W2: **order independence**: for 200 random permutations of an item's facts, the fields, sets,
   counters, seen and ended parts of the fold are equal.
5. W2: **a late fact**: a fact with an older `time` appended after a newer one changes no field
   the newer set, and no snapshot is rewritten except the one at the new length.
6. W2: **restart**: killing the recorder at each of the five points of its tick and starting it
   again yields item logs equal to an uninterrupted run, with no fact twice.
7. W2: a bus whose `start()` passed the recorder's offset produces one recorded gap, the count in
   `workflow_record_gaps_total`, and no invented fact.
8. W2: a log of 9,000 facts is checkpointed; its live log holds at most 2,300 facts and at least
   the last 300; folding checkpoint plus tail equals folding the whole; the page fold is under
   50 ms.
9. W2: the lifecycle on a fake clock: closed → off the open index at once; compressed and final
   snapshot written after 14 days; archive gone and final snapshot kept after 180; `item.deleted`
   leaves nothing in `items/` or `final/`.
10. W2: the year budget: 1,560 synthetic items of 10 facts of 500 B produce a record under 10 MB
    and an index rewrite under 100 ms; the 9,118-event run is recorded in under 5 s.
11. W3: on a scripted run, `workflow_pile_items` equals the count of index items matching each
    pile at each measurement, and the move counters balance each step pile's level exactly.
12. W3: **model**: discovery over the scripted run finds each step pile of the task loop as a stock
    and each `workflow_item_moves_total{from,to}` as a flow between them.
13. W4: two scripted instances claim one offer; exactly one starts work; the floor records the
    first claim on the bus; the loser publishes nothing more about it.
14. W4: an offer nobody claims is withdrawn after its lease and offered again after the back-off;
    a holder that stops sending `offer.alive` is taken back within lease + one tick, published as
    its role with its instance.
15. W4: a role's capacity is never exceeded across 100 items, counting unclaimed offers.
16. W4: a worktree is made, set up once, held across a hand-off from `worker` to `reviewer` (the
    same path in both offers), freed when the reviewer's holder is taken back, and reset before
    the next use; a pool at capacity leaves the next offer waiting, measured, with no attention.
17. W4: an adopted worktree with an uncommitted change is refused, said once to the planner, never
    reset.
18. W4: `item.requested` with a `role` and no workflow is offered, finished, and closed; a schedule
    makes one occurrence per due time across a restart and a daylight-saving change.
19. W4: no event on the bus has the recorder's, the floor's or the program host's own name as its
    source, and none of them is a node of `/api/machines`.
20. W4: a machine written by a separate agent from `docs/machine-contract.md` alone completes ten
    offers.
21. W5: the loader refuses each of: an unknown key, an expression in any field, a step reference
    that does not resolve, a reachable step with no way out; one sentence each.
22. W5: a two-step workflow end to end; a rework returns to the instance that did the step, and to
    any instance after the return timeout.
23. W5: fan-out of three children and fan-in: the parent's step is done exactly when the third
    child ends; a dependency holds an item's step until the other item is at the named step.
24. W5: a metric condition is met only after the series has held for its duration; a missing
    series never meets it; the item's page names the `condition.met` fact.
25. W5: a done-when event from a source without access is in the log, is not counted, and is
    listed on the item's page as not counted.
26. W5: the drift test (§8).
27. W6: the task loop runs ten items to the end on the dummy harness, with one rejection and one
    gate conflict; the three checks of §9 pass; the Machines page shows worker, reviewer,
    merge-gate and dispatch with the hand-offs worker → reviewer → merge-gate.
28. W7: the UX review on the example's demo; no page route accepts a write (every `POST`, `PUT`,
    `DELETE` under `/api/plugins/workflows` answers 405).

## 13. Open questions

1. **Dispatch's identity.** `dispatch/<workflow>` as instances of one `dispatch` machine, or an
   instance of the workflow's planner (`coordinator/dispatch`, as the prototype decided under
   D17)? The first keeps the map honest about a program choosing work; the second keeps "choosing
   what is next is the planner's".
2. **Log order for the position view.** A late outside fact counts when it arrived, not when it
   happened. Right for the floor; is it right for the ledger's account of "what happened"?
3. **Stale completions.** "Counted only after the step was entered" removes most stale CI results;
   a result for an older commit that arrives after a rework is not removed. Matching on a named
   `data` field equal to an item field (the head commit) would be a new word.
4. **Counts in done-when** ("enough approvals"): a counter threshold is a new word; a program step
   that judges it keeps the vocabulary but adds a machine.
5. **Mapping foreign data into fields.** Today only `item.fact` sets fields, and other packages'
   data is read only by name in a done-when. Should a definition map a bridge event's field
   (`github.pr.opened` → `pr`) into an item field, or should bridges publish `item.fact`?
6. **How the Supervisor writes definitions**: by importing the plugin's validated writer (a
   dependency from orchestra-agents on orchestra-workflows, optional), or by a request on the bus
   that the plugin answers.
7. **The measuring interval**: 15 s is plenty for discovery; a guard on pile age reads the record,
   not the series. Is a faster interval wanted for the Piles page?
8. **The program host's home.** Inside the plugin behind the boundary, or a plugin of its own
   beside the agents' host from the start?
9. **The bus retention policy** of the file bus once rotation exists: keep days or size, and the
   default.
10. **Person steps.** Whether the floor offers a person step at all (to the desk, which shows it to
    the owner), or only waits for the bridge's fact of the owner's act.

Left to other proposals: the intended model and the pages' declared layer (proposal 2); the
Supervisor's design duties and refinement passes (proposal 4); attaching instruments to declared
machines (proposal 5); the open items of notes §12 other than rotation are M0's tasks.
