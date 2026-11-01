# Design a system backwards: the working notes

Status: working notes, 2026-10-31; raw material for proposals 2–5. The owner's words are quoted;
everything else is what was agreed in discussion and is open to the reviews.

These are the details behind `design-backwards.md`, kept so that the intended-model, workflows,
machine-design and instruments-on-machines proposals are written from this file and not from
memory. The proposal says what; this file says everything that was settled about how, and who
settled it. Each item is marked:

- **Owner:** the owner stated it.
- **Accepted:** proposed in discussion; the owner accepted it or did not object.

The conversation ran from the owner's "Ok. I need to be able to use this at work" to "Effects is
good" on 2026-10-31. Nothing here is built.

Contents:

1. [What the task system provided, and the generic form of each](#1-what-the-task-system-provided-and-the-generic-form-of-each)
2. [The workflow vocabulary, and nothing beyond it](#2-the-workflow-vocabulary-and-nothing-beyond-it)
3. [Items have no status](#3-items-have-no-status)
4. [The record](#4-the-record)
5. [Piles](#5-piles)
6. [The floor](#6-the-floor)
7. [Resources](#7-resources)
8. [What lives where](#8-what-lives-where)
9. [The outcomes-first loop and the map](#9-the-outcomes-first-loop-and-the-map)
10. [The examples and how they are tested](#10-the-examples-and-how-they-are-tested)
11. [Decisions of the last messages](#11-decisions-of-the-last-messages)
12. [Open items carried from before](#12-open-items-carried-from-before)

---

## 1. What the task system provided, and the generic form of each

**Owner:** "Was our tasking system incorrect? Did we implement the wrong thing? The tasking
system assumes there is a merge gate, and a closed loop between our agents doing work and merging
to the main branch and updating the staging environment. We implemented a minimal version of a
Continuous Integration pipeline. Maybe we were supposed to implement something else, the framework
that a CICD platform could be built on top of."

**Accepted:** the mechanisms were not wrong; the shape was. Nearly everything in the task system
is a generic piece of a workflow runtime, wired to one hard-coded workflow (OPEN → worker →
reviewer → merge gate → DONE, with `code` and `tasks` as two variants in the code). The inventory,
with the generic form of each:

| The task system today | What it is, generically | The generic form |
|---|---|---|
| A ticket with a state enum and `TRANSITIONS` hard-coded in `model.py` | An **item** going through a **workflow**: the current step, a version, history, notes | The steps come from a workflow definition, not the code (and then §3: no status field at all) |
| Roles with capacity; offers, claims, leases, heartbeats, "no zombies" | **Step assignment**: a step names a role; the runtime offers the step, records the first valid claim, keeps the lease, takes silent work back | The most valuable part; already domain-neutral in shape, only its names (`task.*`, "ticket") are specific |
| Dispatch: readiness (dependencies, milestones), priority, pickup pause | **Step scheduling** | Readiness becomes "the previous step is done and the item's dependencies are at step X" |
| Workspace: a folder or a git worktree, the pool, `worktree_setup`, `PREPARING` | A **resource** a step needs, claimed before the step and held across steps | Worktrees are one resource kind among others (§7) |
| The merge gate: run checks, merge, fast-forward, say why not | A **program step** with outcomes (landed, rejected, conflict, error) | A step kind: run a command, map its exit to an outcome. A SAIL check, a deploy, a flake check are the same kind |
| `review.requested`, `changes.requested`: machines handing the item to each other | A **transition published by the machine making it**, recorded by the runtime | Each workflow lists its hand-offs |
| Rejected work returns to the worker that did it; any worker after a timeout | **Rework**: a transition back to an earlier step, addressed to the instance that did it | A property of a transition: to the same instance, then anyone after N |
| External mode: `IN_EXTERNAL_REVIEW`, bridge events drive it, stale commits ignored | A **wait step**: done by a system Orchestra does not run; completion arrives as a bridge event matched by subject | A step kind: "wait for SAIL's check", "wait for the triage agent's comment", "wait for a review" |
| `task.attention_needed` at thresholds (N rejections, a stuck turn, base broken) | **Guards**: time and retry limits on a step that escalate to a planner role | Each step declares its own |
| Recurring tickets | **Items started by the clock** | "Start an instance of workflow W every weekday at 8" |
| Stacking (git-spice): branch on parent, restack, conflict back to the worker | A **dependency between items** plus a resource-maintenance step | The dependency is generic; the restack is a step kind of the code workflows |
| Staging deploy after landing | Another program step | A step in the definition |
| Operator controls: capacity, pause, kill | Runtime controls | Kept |
| Measures: tickets by state, time in state | **Items per pile, time per pile**: the stocks and flows discovery finds | Where the workflow meets the model (§5) |
| `[project] work = code / tasks` | Two hard-wired workflows | Gone; both become definitions |
| Probes | Conditions | Instruments, not the workflow's (already flagged in `docs/roadmap/story-placement.md` §7) |

**Owner's correction**, which governs this whole file: "We are not using what we have today. We
are replacing the Tasking system with something we should have written initially. We don't need
to keep anything from that. We hope to write a new system based on our learnings for it. Do not
let yourself be bound by the initial implementation of Tasking. It was only a prototype, we are
building the correct thing now - a Workflows system. Then, we will build a Tasking system that is
a naive implementation of it." And: "We are not piecing out the Tasking system. We want very
little of the original Tasking system, including its current data storage, to remain after we are
done." And: "Thankfully, our tasking system is already a separate plugin, so we can just not
include it to get rid of it."

So the table above is **the list of capabilities the new system must provide**, and nothing more.
No code, no store, no state enum and no transitions table is carried over. The task system can be
left out by not installing it.

**Owner:** the Workflows system "should be capable of handling any existing workflow, from any
company. Like some companies have Release Candidates and Release Candidate verification steps.
Some companies have multiple releases out. We might see a staged production rollout, we might see
customer-owned deployments. We might see multiple concurrent release branches that all need
hotfixes." And: "We can provide a system like Tasking for demo use, but we would expect people to
customize it for the workflows they actually experience at work."

## 2. The workflow vocabulary, and nothing beyond it

**Accepted.** A workflow is written in exactly these words, because they are the capabilities of
§1 and no more. Anything that needs logic is a machine (a program step or an agent step), never
an expression or a script in the definition. If a workflow cannot be written in this vocabulary,
that is a finding about the vocabulary, taken one case at a time.

| Word | Meaning |
|---|---|
| **item** | What one instance of the workflow is. The subject key on every event about it: a Jira ticket (for delivery, with its pull requests inside), a pull request (for team review), an alert (for on-call), a release candidate, a hotfix with a child item per release branch, a customer × release pair |
| **starts** | What begins an item: an event (a bridge's `jira.issue.assigned`, `github.pr.review_requested`, a PagerDuty alert), the clock (recurring), or a request (the Supervisor's "do this once") |
| **step** | One stage. Steps have the fields below |
| **who** | Who does the step: a **role** (a machine of any kind: an AI agent, a program, a person, each announcing the role), a **program** (a named command), an **outside system** (a wait: GitHub, SAIL, Jira, the triage agent), a **person** (the owner's own act; a machine may prepare it, never do it), or the **outbox** (a write as the owner, after approval) |
| **needs** | The resources the step claims before it starts and holds across hand-offs (§7) |
| **done-when** | What marks the step done: an event (with the item as subject), or a **metric condition** read from the metrics store ("the canary's error rate under 0.1% for 30 minutes") |
| **guards** | `within` (a time limit) and retry limits. A guard passed escalates to a planner role (the coordinator, the Supervisor), as `task.attention_needed` does today |
| **outcomes** | Where each result of the step leads: success → the next step, failure → an earlier one, a named outcome → a named step |
| **on** | An event that moves the item to a step whenever it arrives (`github.pr.changes_requested` → back to writing) |
| **rework** | A transition back to an earlier step is addressed to the instance that did that step; after the return timeout, to anyone of the role |
| **relations** | Items related to each other: a parent fans out into children (a hotfix into one item per release branch) and is done when all children are (fan-in). Dependencies between items |
| **lifecycle** | The retention policy for the item's record once closed (§4): per workflow |

**The two features the task system never had** (accepted, and the examples in §10 need them):

1. **Relations between items**: fan-out and fan-in, a parent done when its children are.
2. **Done-when as a metric condition**, not only an event. This is where instruments feed
   workflows directly, and where a staged rollout's "advance when the canary is healthy" lives.

**The delivery-through-SAIL example**, as the owner described it (owner: "maintaining a Jira
ticket; creating Github Pull Requests, with good descriptions, etc; monitoring the Pull Request
for test completion; sending messages to people to review my Pull Request; addressing feedback on
the Pull Request (in a loop until sufficient reviews); sending the pull request to their official
merge gate, with the SAIL label; monitoring the pull request to see if the SAIL action failed,
then addressing the failure"). Item: one Jira ticket. Starts: the ticket assigned to the owner.

| Step | Who | Done when | Guards and outcomes |
|---|---|---|---|
| keep the Jira ticket current | an agent drafts, the outbox sends (today: the owner) | a Jira transition or comment | runs alongside the rest |
| write | worker (an AI worker, or the owner) | `review.requested`, with the commit | needs a worktree |
| open the PR with a good description | person: the owner pushes and opens it; the worker drafted the description | `github.pr.opened` | within 1 day, else attention |
| ci | outside: GitHub, the bridge reports | `github.checks.completed` | success → review; failure → write (to the same worker) |
| review | outside: people | `github.pr.approved`, enough of them | on `github.pr.changes_requested` → write; within 1 working day, else the nudge (an agent drafts the message, the outbox sends it) |
| sail | outbox: adds the SAIL label, with the owner's approval | `github.pr.labeled` | |
| sail-check | outside: SAIL's action | its check result | success → done; failure → triage-failure |
| triage-failure | program: is the failure company-wide? | its verdict | company-wide → wait and retry; else → write |

This example is set aside for now (§11); it is here because it is the one that exercises every
word of the vocabulary. The owner's other two workflows of that message:

- **Team review.** "check for pull requests from my team; read them, understand them,
  contextualize them, give feedback as comments; approve the pull requests if warranted; make
  sure the pull requests get merged; if they have test failures, remind them to attempt to sail
  again. if there are failures, check if there are company-wide issues that are affecting them."
- **On-call.** "get an alert from pagerduty; do a quick impact analysis, search for correlated
  signals, check SLO's for worrying numbers; check logs for error rate change in any services,
  for evidence of an outage; disqualify an outage if possible; then wait for a triage-agent
  comment to be added to the pagerduty alert's jira ticket, review it, determine a course of
  action; perform the steps to fix the issue; consider updating a runbook."

The owner: "I have many more workflows, we've talked about them before, they are recorded
somewhere in our docs" (`docs/user-stories.md`, 21 stories; `docs/work-charter.md`).

**Configuration is never the interface** (owner): "I don't like the toml. I think this file will
become unreadable very quickly. If TOML is the interface for setting this up, it will be a
miserable experience. If you insist on using TOML, it can be as a persistence format, but it is
not the most reasonable format for something this complicated." So: the owner describes a
workflow in chat, the Supervisor writes it, a page draws it (steps, who does each, coverage, where
each item is now). What is on disk is persistence, read and written by programs, in whatever
format is easiest for them. The vocabulary above is kept; no syntax from the discussion is.

## 3. Items have no status

**Owner:** "While it's true that our items have transitions, I wonder if that's an artifact of
the old task-queueing system. Sometimes factories work in piles, where the pile is a pile of
similar things, a queue of items considered uniform or worth sorting into other piles. If they do
that, they may not have a 'status' for each item, they might track the properties and qualities
of the item and sort them that way. … a state machine doesn't necessarily have one variable
called `status` on it, it can be a combination of a `state` variable and some other labels, it can
be segments of a numeric field, and really a state machine can have a 'state' that is the
combination of all of its fields, that is still a state machine. The question isn't about whether
to reduce the state of an item to one `status` field, it's what we want to use with the status.
If we change a task's Jira Ticket ID, that could be a 'has Jira Ticket ID' event, or it could be
a 'jira ticket ID modified' event. The state transitions may be an overly reductive way to model
generic items. For instance, we could model the 'state' as a function of the task's variable
fields, and determine the properties as needed. We could define several state machines on top of
a Task, and use them for different things."

**Accepted**, and pushed further: an item is its facts. "Which step is it at" is a function
computed from the facts when needed, by a workflow. Facts come from events on the subject (the
bridge says the PR opened; the worker says review requested; the clock says the lease ran out)
and from fields machines set ("has a Jira key"). The record is the events; the state is a view.
This is the same rule as the rest of Orchestra: machines are known by what they publish, and
Orchestra reads what is observed.

Consequences:

- **Several state machines over one item.** The delivery workflow, the "Jira hygiene" condition,
  the ledger and the morning brief are each a different function over the same facts. None of
  them owns the item. A pull request is in the owner's delivery workflow and in the team's review
  workflow at once.
- **"Has a Jira key" versus "Jira key modified": both.** The event is the fact that something
  happened (modified, by whom, from what to what: the ledger wants it); "has a Jira key" is a
  predicate over the current fields (piles want it). Record the first, compute the second.
- **Gone:** the transitions table, the version bumps, the "cannot move X → Y" errors, the recovery
  states. The task system's `PREPARING` work of 2026-10-29 had all of these, and most of the task
  system's bugs were in them.
- **What replaces the guard** the transitions table gave: access. Which machine may publish which
  fact about an item; the session-token and role check that exists already.
- **Explainability.** When a page says "PROJ-123 is waiting for review", it must show which facts
  make it so, or nobody can debug it. An item's page folds its log live and shows the provenance
  of each field (§4).
- **Machines still act on something simple:** the floor's offer (§6), never the item's facts.

## 4. The record

**Owner:** "So you're asking the question of Conflict-Free Replicated Data Types, CRDT's, built
from an event log for every interaction, only viewable by combining all events. I like this idea,
it's actually a useful way to use CRDT's, and the presentation format is usually cached as a
snapshot and the cached version for that stage of the object is evicted when an event is added
before the most recent event. I don't know if we can use our Event Bus, because we have limited
retention. How would we handle the retention period, and how would we handle garbage collection?
If an Item leaves our system, if there's a 'delete' or 'archive' event emitted by it, we would
expect all of the events for it to be removed. If we do compaction for retention, we might
flatten the earliest messages to a static form. What's the plan? How much space does it usually
take to do this? How do we avoid long-lived items from costing too much?"

**Accepted**, all of the following.

**One log, totally ordered.** The bus is totally ordered, so there are no concurrent replicas to
merge: it is event sourcing with a single log, the easy case of a CRDT (every fold is
deterministic, snapshots never conflict). The folds are still written to be order-independent per
field: last-writer-wins by event time for a field, set union for notes and labels, counters add.
Then a late fact from a bridge (an older `time`) is appended in bus order and the fold gives the
same answer, so nothing is ever inserted before the most recent event and the eviction case the
owner described never arises. A view that needs time order sorts at view time.

**The bus is transport, never the record.** Retention is the broker's (Kafka's `retention.ms`,
Redis stream trimming); the file bus has no retention today and just grows (a separate fix: it
needs rotation). Rule 5 already puts a plugin's state in `~/.orchestrator/<key>/`. The
**recorder** follows the bus, keeps its offset across restarts, and copies each fact about an item
into that item's own log. After that, bus retention does not matter to items.

**What goes in an item's log: not everything with the item as subject.** Heartbeats
(`task.working`), session start and settle, model changes are lease signals and runtime noise,
not facts about the item; they stay on the bus only.

**Measured, 2026-10-31, on `~/.orchestrator/orchestra-sample-live-*` (a live run):** 406
events, 49 items (subjects), median 2 events per item, maximum 32; 120 to 500 bytes per event
(509 B average there; 122 B in a program-only run of 9,118 events). The largest class was
`task.working`, 63 of 406; then `task.accepted` 42, `session.started` 42, `session.settled` 42,
`orchestra.model.changed` 39, `review.requested` 21. With the noise excluded, about 10 facts per
ticket through the task system's loop, 3 to 5 KB per item. At a work pace of 30 items a week that
is under 10 MB a year. The disk goes elsewhere: the metrics store was 448 MB and worker artifacts
709 MB in those state directories.

**Snapshots, two levels:**

- A per-item snapshot keyed by `(item, log length)`, written by the recorder after each fold.
  Reading an item's page folds the log live anyway (kilobytes) and shows the provenance of each
  field; the snapshot serves lists.
- One index file of all snapshots, which is what piles query (§5). About a megabyte of JSON at a
  few thousand items; SQLite when it hurts, and nothing above it changes.

**Checkpoints for long-lived items.** An item with a Jira comment every hour for a year has 9,000
events and 4 MB: fine on disk, slow to fold. When a log passes N events or M days since its last
checkpoint, the recorder writes a checkpoint (the fold at offset k) and the live log becomes the
checkpoint plus the tail. The prefix moves to a compressed archive file beside it: audit is kept,
the hot path never reads it. The last few hundred events are never compacted, so recent history
stays explainable.

**Leaving the system: a lifecycle, not a delete.** A `closed` or `archived` fact starts it:

1. closed: the log is kept, the item is no longer indexed in open piles;
2. after N days: the log is compressed into the archive; the final snapshot is kept;
3. after M days: the archive is dropped; the final snapshot (a few hundred bytes) is kept for
   good.

The snapshot is the "flattened static form" the owner described, and it stays because the ledger
and the owner's yearly review need "what I did" long after the events are useless. A `delete`
fact skips to the end and removes the snapshot too. The policy is per workflow (a PagerDuty alert
item can be dropped in a week; a delivery item's snapshot is kept forever).

**What survives deletion.** The model never reads item logs: pile sizes are written to the
metrics store as series every tick (§5), so the system dynamics history is intact after items are
gone. The Machines page reads only bus envelopes, with the bus's own retention.

## 5. Piles

**Accepted**, from the owner's piles (§3). A **pile** is a named query over item snapshots: "has a
Jira key, no pull request, nobody holds it". Dispatch picks from a pile by priority. A pile's size
is written to the metrics store as a series every tick, which is what discovery already makes
stocks from: **piles are the stocks, and the moves between piles are the flows.** The workflow
does not declare the model; it is made of it. This keeps rules 6 and 7 (stocks are discovered; a
machine's link to a flow is an inferred hypothesis): the workflow proposes stocks by having piles,
and discovery confirms or refutes them.

## 6. The floor

**Owner:** "The most important thing that our Tasking system provided was a scheduler, the thing
that spawns the machines. The order of steps is important, but a huge thing that Tasking gives us
that nothing else gives us is the ability to actually launch and setup Machine instances. That's
the most important thing it does right now, because there is nothing else that does it, and if
nothing else does it then we would never have anything that does any actual work. I don't know if
the scheduler should be separated, or if it makes sense as part of a Workflow plugin."

**Accepted:**

- It is the only thing in the system that turns "work exists" into "a machine is doing it". Named
  **the floor**: capacity, leases, offers and claims, resources, taking back silent work,
  escalation.
- **Today's split is kept.** Two halves: one decides what is next and offers it, with the resource
  prepared (the task system's scheduler today); the other answers offers for its roles by starting
  a machine instance (the agents' host spawning a session with its token, prompt and environment;
  a program by running). The offer side must never know what a machine is made of.
- **The floor runs without any workflow.** The Supervisor saying "do this once", a recurring job,
  an alert: all are piles the floor can offer from. So it is built first, and workflows are a
  layer that produces piles for it.
- **One plugin to start**, with that boundary kept hard inside it (as the task system kept its
  scheduler in one module). Splitting into two plugins later is cheap if the boundary holds and
  expensive if it does not.
- **Out of the core** either way: the core's launcher keeps declared commands running and learns
  nothing about engagements (rule 1).

## 7. Resources

**Owner:** "I like the part about Resources. I don't know how to make it generic, but some part
of it will be user-configurable in the target repo."

**Accepted:** a resource **kind** is a name, a capacity, and three commands the target repository
provides: make one, reset one between uses, release one. The worktree pool is exactly that with
git commands and `worktree_setup`, and is the first kind. Others of the same shape: a staging
environment, a database snapshot, a rate-limited API budget, "one person's attention". The target
repository defines the kinds it has under `.orchestra/`; the floor knows only: claim before the
step, hold across hand-offs, free when the holder drops.

A correction made in discussion: **a Jira ticket or a pull request is not a resource.** Nothing is
scarce about it; it is a fact attached to the item. Resources are the scarce things, and that is
why they matter to the model: a pool is a capacity limit on a flow, the most ordinary structure in
system dynamics.

## 8. What lives where

**Owner:** "I want to talk about what goes in the user's repo, what comes from a plugin, and what
the refactor process would be like if someone wanted to move their Workflow from their target
repo into a plugin."

**Accepted.** The key decision: **a repository's `.orchestra/` folder and a plugin have the same
shape.** Both hold the same kinds of things; a plugin is that folder packaged. The core already
loads `.orchestra/plugins/` and `.orchestra/overrides/` by file (rule 10), so this extends a rule
we have.

| What | In the user's repository (`.orchestra/`) | From a plugin |
|---|---|---|
| **Workflows** | the company's: delivery through SAIL, RC verification, hotfix ports | reusable ones with parameters: "GitHub PR review", "staged rollout", the task-system demo loop |
| **Machines** | programs (scripts in the repository), agent roles (prompt, tools, what they listen for), person roles | the agent runtime, bridges, outbox, generic programs (a merge gate, a flake checker) |
| **Resources** | kinds with make/reset/release commands and capacity: worktrees, a staging env, a customer sandbox | the worktree pool as a ready-made kind |
| **Instruments** | collect scripts, series definitions (as today) | scrapers for known systems |
| **Intended model** | the outcomes the owner declared, with targets; the effects | none (it is always the owner's) |
| **Settings** | names, labels, channels, thresholds (`SAIL`, `#team-reviews`) | the schema of what a workflow needs filled in |

Company-private material that is not code (people, channels, tokens) stays in the owner config
outside the repository, as decided before: `~/work-desk` (D10, `docs/roadmap/story-placement.md`
§2.7), secrets in `~/.config` or the keychain.

**Promotion from a repository into a plugin** is packaging, never a rewrite:

1. **It starts in `.orchestra/`,** specific and private: the SAIL label is written in, the
   channel names are written in.
2. **It gets parameters.** When a second repository (or a colleague) wants it, the specific names
   become settings with a schema. The Supervisor can do this step: it is the operator.
3. **It becomes a package.** The folder moves into a plugin repository with a `pyproject`; the
   original repository keeps only the settings and any machines that are truly its own.
4. **It is shared.** Installed as an extra, like the plugins today; several repositories fill in
   their own settings.

Nothing in the workflow changes between steps 1 and 4 except where it is loaded from. **The drift
test:** if promotion needs a rewrite, the repository form and the plugin form have drifted.

## 9. The outcomes-first loop and the map

**Accepted**, the loop: declare outcomes → decompose into piles and moves → build machines, agent
first → observe → compare declared with observed; each difference is the next piece of work or a
correction to the declaration. The intended model is declared (origin: declared, rule 6's
"assumption until fitted"), the observed one discovered (rule 7).

**Owner**, the map as they want to use it, in order (quoted or close to it):

1. "A user would start by fabricating a system dynamics model, one that has no measurement for
   stocks yet. Then they might suggest some basic stocks they expect to see."
2. "After the system dynamics modeling, they would start the implementation. They have a few
   basic tools: the Universal Machine (AI agent), event names to emit and receive, and some
   tertiary systems."
3. "The user would probably have some idea of what machines they want, so they place them on the
   map, by name only. An AI agent can try filling out some prompt details for them based on the
   name, but not official."
4. "The AI agent might also suggest some event names, and take into consideration the existing
   event names and descriptions of other agents."
5. "As more Universal Machines are added, they get more detailed and specific. The AI agent that's
   helping craft this part can refine earlier agent prompts, tools, and event
   publishing/subscribing."
6. "This is effectively going to be like the Event Map screen, as the Machines get new events
   added to them, as publishing or subscribing, the event map should rerender and reorient itself
   like the existing Event Map does."
7. "The user might add real Machines as well, things that exist already. They might say 'postgres
   database', but if they have one then you know they have more than one. They might include
   Machines for things like Jenkins job pipelines. They might try to add a lot of these, and map
   their events." (Accepted reading: a name declares a kind; instances are learned from the
   labels of what is measured or heard.)
8. **Effects.** "Then the user would add some non-machine things, things that exist and can be
   measured but are the consequences of the system. We had said a while ago that a machine is
   something that emits metrics, but that would give us no way to model the thing we actually
   care about, the hidden measures that aren't part of what we think of when we say 'factory'. We
   want to account for things that are nebulous, maybe ephemeral, measurable consequences of the
   system at large. I don't know what to call them. They are not 'environment' the way we've been
   using it. It's something else." Proposed name **effects** (a machine does, an instrument
   measures, an effect is what happens to the system as a result; "conditions" and "outcomes" were
   taken); **owner, 2026-10-31: "Effects is good."** Examples: latency, error budget, the age of
   the review backlog, on-call load, customer trust, technical debt. Declared like stocks, with
   targets; an instrument is attached to each so discovery can find it.
9. "An AI pass should probably [run] a few times, try to make sure no events have publishers but
   no subscribers, make sure the purposes of events aren't duplicated, make sure that events
   aren't excessively deduplicated and serving multiple distinct purposes, other refinement
   things."
10. "When the AI adds these things, I would want it to be proposed as an option, like a slightly
    darker variant that can be clicked to solidify it on the map." (Accepted: three shades on one
    map: proposed by the AI, declared by the owner, observed from the bus and the metrics.)
11. "Once they have their intended event bus graph all mapped out, we get to the fun part. The
    Universal Machines can get refined naturally, based on the semantic information provided by
    the Event Graph. AI agents can define those things. If we get a feedback loop to improve the
    Universal Machines, we can really see some good automated benefit there."
12. "The existing Machines will need to be mapped, and this is where the fun part happens,
    because this is the integration step. Because the Machines aren't likely to emit their actual
    metrics, and because we would want to incorporate and model existing machines, we need to
    attach our measurement instruments to Machines. This is where we would do it."

**Owner, the whole:** "Design a system backwards. Start by declaring what you want, then declare
what effects you expect to see emergently, then declare what machines you want, then declare how
they are related and communicate, then implement them implicitly with Universal Machines, and
eventually refactor away the Universal Machines to Programmatic Machines with AI-fixers, then
reduce the amount of AI-fixing it needs. This is the dream. Monitor the system at all of those
levels, add Universal Machines to improve efficiency."

**Owner, on precedent:** "There have been workflow design programs in the past, but they didn't
have AI Agents that can do the work automatically, so this one might be more useful."

**Accepted, the invariants this touches** (for proposals 2 and 5): the map's declared layer is
hypotheses, like declared equations; a declared machine that never published shows as declared
and unheard, an observed machine nobody declared as unexpected. Attaching an instrument to a
declared machine is declared provenance (like today's `instrument=<name>` label): it never makes
the machine exist in the observed layer and never binds it to a flow (rules 2 and 7 as amended in
`design-backwards.md` §5). The intended model lives in the core, because the core already holds
declared equations and the comparison is domain-neutral; the workflows, machines and floor stay in
the plugin. Whether the map-drawing AI is a Supervisor duty or a machine of its own is open
(proposal 4).

## 10. The examples and how they are tested

**Owner:** "We want some examples of how people would actually use this, and we want them
tested."

**Accepted**, the seven examples in the vocabulary of §2:

| Workflow | Item | Piles (stocks) | Moves and who | What it needs |
|---|---|---|---|---|
| The owner's delivery through SAIL (set aside for now, §11) | Jira ticket | writing, PR open, CI, awaiting review, changes requested, labelled, in SAIL, failed SAIL, merged | a worker (agent) writes; the owner pushes; the bridge reports CI; people review; the outbox labels; a program triages a SAIL failure | outside waits, rework to the same instance, a guard on the review wait |
| Team PR review | pull request | requested of me, read, commented, approved, merged, stale | an agent reads and drafts; the owner approves; the outbox nudges | the same PR in two workflows |
| On-call | alert | new, analysed, disqualified, awaiting the triage comment, fixing, runbook check | programs: correlated signals, SLOs, log error rates; an agent: the course of action; the owner: the fix | a wait on an outside comment, metric conditions |
| Release-candidate verification | release candidate | cut, verifying, verified, rejected, released | a program cuts; verifier programs and agents; the release manager (a person) releases | a staging environment resource per RC |
| Hotfixes across release branches | hotfix, with a child per branch | pending, ported per branch, landed per branch, complete | a program ports; an agent resolves conflicts; people review each | fan-out and fan-in |
| Staged rollout | release | canary, 10%, 50%, 100%, rolled back | a program advances; done-when is a metric condition; rollback is an outcome | metric conditions, a guard per stage |
| Customer-owned deployments | customer × release | notified, scheduled, deployed, verified, overdue | the outbox notifies; the bridge sees the deployment; an agent chases | long outside waits, many items per release |

The task system's loop (write → review → gate → done) is one more row: the demo, on the same
runtime.

**How each is tested.** Each example is a tiny target repository with its own `.orchestra/`,
scripted machines on the dummy harness (no model, no network), fake bridges emitting the outside
events, and a test that runs it and checks three things:

1. the piles over time match the script;
2. discovery finds the declared stocks and flows (the model-acceptance workflow,
   `.claude/workflows`, already used for the use cases in `docs/roadmap/use-cases.md`);
3. the event map shows the declared machines and hand-offs.

The examples are the plugin's test suite and its documentation at once.

## 11. Decisions of the last messages

- **Owner:** "Effects is good." The name stands.
- **Owner:** "What you've described as the map, yes, we ignore SAIL for now and we work on the
  generic problem of workflow design." So the order is the intended model and the map first
  (proposals 2 and 5), then the record and the floor (3), then the design assistant (4), then the
  examples; the owner's own workflows (SAIL, team review, on-call) are set aside until the generic
  problem is solved.
- **Owner:** "You can put it in the core if you think that makes sense." The intended model goes
  in the core.
- **Owner:** "There have been workflow design programs in the past, but they didn't have AI Agents
  that can do the work automatically, so this one might be more useful."

## 12. Open items carried from before

Not part of this design; listed so they are not lost while the proposals are written:

- A hard block on agents pushing or merging (`git push`, `gh pr merge`): offered, not built. AI
  workers run with `--dangerously-skip-permissions` and the user's credentials; only the prompt
  says "do not push".
- The Supervisor's `check_setup` does not call each plugin's `Plugin.check`
  (`orchestra_agents/observe.py`).
- Orchestra without the `[sd]` extra crashes: `orchestra.sd.rediscover` imports numpy (since
  `8905a622`).
- Four core tests fail when the plugins are installed (the desk rejects the `desk.me` key).
- Pre-existing failures in the orchestra-agents suite: `test_review_round::test_a_stall_found_
  wakes_it_once_and_the_cap_stops_its_initiative` (a per-day budget around midnight UTC),
  `test_eras_e2e` (a timeout under full-suite load), `test_demo_e2e` (flaky, DEMO-4 taken by
  `worker/3`).
- The file bus has no rotation and grows without bound.
- Pushed and live, for the owner's use at work meanwhile: `[agents] tools_via = "bash"` (tools
  from the shell when the company's hook refuses MCP calls), the adopted worktrees and
  `worktree_setup`, the `PREPARING` state, the Core page's process logs. These belong to the
  prototype and are not carried into the new system by default.
