# Proposal: Teams and Roles, in four stages

Status: Stage 1 decided and being built, 2026-10-11. Stages 2 to 4 remain proposals.

## Decisions taken

- **Only Stage 1 is in scope now.** Roles and custom agents. Teams, jobs,
  catalogs, channels, and the library are not built until Stage 1 has earned
  them.
- **Roles are authored in conversation.** Creating a role is a brainstorming
  and requirements-gathering exercise between the human and the Supervisor:
  what the agent is for, what should wake it, what it may do, how it reports.
  When the human agrees to the plan, the Supervisor writes the role and its
  prompt. There is no form and no template picker in the UI.
- **Role storage is an interface, like tickets.** A `RoleStore` with one
  implementation to start: the project repository, under `.orchestra/roles/`,
  versioned with the code. Not `~/.orchestrator`. Later stores (an external git
  repository, GCS, Artifactory) implement the same interface, because roles are
  valuable and people will want them outside any one machine or repo.
- **The knowledge catalog is deferred, deliberately.** A catalog without a
  curation policy is a text dump. Its value comes from the coordinated
  behaviour of agents around it, scheduled curation and strongly worded
  directives, not from storage or tools. It returns when a team exists to
  curate it.

## Why stages

The full idea, teams of agents with leads, members, resources, permissions, and
cross-team channels, could absorb weeks and still miss the mark. The honest
answer to "what if this is a windmill" is to build it in stages where each stage
is useful on its own, each has a checkpoint that says whether it earned the
next one, and the first stage covers the one thing we are certain people want:
**their own long-running monitoring agents that receive events.**

| Stage | What it adds | Who needs it | Stop here if |
|---|---|---|---|
| 1. Custom agents | Roles defined as data: prompt, tools, events, schedule. Create, pause, restart, delete. | Everyone. "I want a Product Owner" or "I want a nightly auditor". | Nobody creates a second role, or created roles are ignored. |
| 2. Teams and jobs | A lead with members; non-code work as job tickets reviewed by the lead. | Anyone whose agent needs helpers: PO with a designer, PI with researchers. | Jobs produce results nobody reads. |
| 3. Catalogs, access, channels | Owned knowledge with read/write/decide permissions; role library shared across projects; cross-team channels. | Teams that make decisions other teams must trust. | Decisions do not change what gets built. |
| 4. Self-organizing teams | Leads request members; templates; rotation; reference teams (Pipeline, Product, Lab); impact metrics. | A project that runs for months. | The metrics say agents' decisions are not better than the human's. |

The vocabulary, fixed now so it stays stable across stages:

- **Role**: one kind of agent. Every role has two independent dials:
  - *session policy*: `resident` (one long-lived process that keeps memory and
    can be talked to) or `ephemeral` (a fresh session per wake-up);
  - *wake policy*: events, an interval, a daily time, or messages from its
    lead, in any combination.
  "Scheduled" and "long-lived" are not two kinds of agent; they are settings
  every agent has. A Product Owner is resident and woken daily and on
  landings; a researcher is ephemeral and woken only by a job; a monitor is
  resident and woken by events.
- **Team**: a group of roles with exactly one **lead**. The lead decides,
  delegates, owns the team's resources, grants its members access to them,
  and is the only member that talks outside the team.
- **Member**: a role in a team that is not the lead.
- **Job**: a unit of non-code work, executed by a member, reviewed by the lead.
- **Resources**: what a team owns and grants access to. Three distinct kinds:
  - *catalogs*: curated documents, with read, write, propose, and decide grants;
  - *data stores*: bulk data (captures, datasets) outside the repository and
    outside the catalog, referenced from catalog documents by URI, with the
    same grants;
  - *pages*: the team's view of its work, read-only against Orchestra's API.
  Other teams read decided documents by default; anything more is an explicit
  grant from the owning lead.
- **Channel**: an explicit, visible permission for two teams' leads to exchange
  messages. The default is the tree: members to their lead, leads to the
  Supervisor, the Supervisor to the human.
- **Supervisor**: the human's interface, above every lead.

Stage 1, which exists, is the degenerate case: single roles with the two dials,
no lead above them but the Supervisor, and no resources beyond tickets and the
event log. Teams add the lead, the members, the jobs, and the resources.

What exists today in these terms: an Engineering team whose lead is the
Coordinator and whose members are the per-ticket worker and reviewer, a
Pipeline team whose lead is the Pipeline Manager with no members yet, and the
Supervisor. All three are defined in Python.

---

## Stage 1: Custom agents

**Goal.** Anyone can add a long-running agent like the Coordinator or Pipeline
Manager without writing Python, and control it from the UI.

**A role is a record.** Stored in the project state as `roles.json` plus a
prompt file per role; built-in roles stay in code and can be overridden by a
record of the same name.

```json
{
  "name": "product_owner",
  "session_id": "product-owner",
  "description": "Keeps value propositions and user stories current; asks the Coordinator for tickets.",
  "prompt": "prompts/product_owner.md",
  "tools": ["tickets", "escalate"],
  "session": "resident",
  "wake_on": ["milestone_closed", "ticket_done"],
  "every": "24h",
  "at": "09:00",
  "paused": false,
  "source": "project"
}
```

**Wake policy.** `wake_on` is a list of event types from the existing event
log, so any event the loop already emits can wake a role: ticket created,
landed, blocked, gate failed, staging deployed, and so on. `every` and `at`
schedule wake-ups. A woken role gets the same wake-up prompt the Coordinator
gets today: why it was woken, the execution-health section, and the project
snapshot.

**Session policy.** `resident` keeps one Pi process alive for the life of
`orchestra run`; `ephemeral` starts a fresh session per wake-up and closes it,
which suits daily roles that need no memory and keeps context from growing.

**Tools.** Granted by the existing groups: `tickets`, `context`, `pipeline`,
`capacity`, `escalate`. Stage 1 adds one group, `events`, which lets a role
read the event log so a monitor can look back over what happened.

**Supervisor tools.** `create_role`, `update_role`, `delete_role`,
`restart_role`, `pause_role`, `resume_role`. The Supervisor writes the prompt
from a short template: who the role is, what it watches, what it may do, how
it reports. Deleting a role archives its sessions like a finished ticket.

**UI.** An **Agents** page listing every role, built-in or custom, with status,
last activity, next scheduled wake-up, and pause, restart, and delete controls.
Pause queues wake-ups instead of dropping them, so a resumed role catches up.
The dashboard's left column shows custom resident roles beneath the three
built-in ones.

**Done when.** A user creates a Product Owner from chat, it wakes daily and on
landings, it asks the Coordinator for tickets through `escalate`-style
messages, and the user pauses and deletes it from the UI.

**Checkpoint.** Does anyone create a second role, and does it change what gets
built? If created roles are ignored, stop here; the mechanism is cheap and
already covers the certain need.

---

## Stage 2: Teams and jobs

**Goal.** A role can have helpers, and helpers can do work that is not code.

**Teams.** `teams.json` names a lead, its members, the team's resources (at
this stage only a document directory; catalogs, data stores, and pages come in
Stage 3), and the team's capacity: how many member sessions may run at once,
separate from the engineering worker pool so a lab survey cannot starve code
work of the local model.

**Jobs are tickets.** Tickets gain `kind`: `code` is today's path through
worker, review, and the merge gate; `job` names the member role that executes
it. A job runs `OPEN → IN_PROGRESS → READY_FOR_REVIEW → IN_REVIEW → DONE` and
skips `APPROVED` and `MERGING`. Its reviewer is the team's lead unless the team
names a reviewer role. Its result is written where the job's brief says, at
this stage a plain document directory per team (`<state>/teams/<team>/docs/`),
which Stage 3 turns into catalogs.

Why tickets rather than a second queue: one task graph, one dependency model,
one burndown, and "the spectrum survey must finish before the decoder ticket
starts" is an ordinary dependency. The loop, slots, pause, stop, crash retry,
effective priority, and the drawers apply unchanged. The cost is that
`REJECTED` means "redo the research" for a job, which the prompts explain.

**Communication, the tree.** A member talks only to its lead; a lead talks to
its members and to the Supervisor. `send_to(role, note)` queues a wake-up and
the store rejects calls outside the tree with a message saying why. Leads do
not talk to each other yet; that is Stage 3.

**Done when.** A Lab team with a Principal Investigator lead and an ephemeral
researcher member runs a research job created by the PI, the PI reviews and
accepts the result, and a code ticket that depends on the job becomes ready.

**Checkpoint.** Do job results get read? Measure how often a job's document is
referenced by a later ticket or decision. If jobs are produced and never
consumed, stop before catalogs.

---

## Stage 3: Resources, access control, channels, and a role library

**Goal.** Teams own resources (catalogs, data stores, pages) that other teams
can trust, decisions are explicit, and roles are reusable across projects.

### Catalogs

A catalog is a named collection of markdown documents with frontmatter (id,
title, author role, status, tags, created, updated). Catalogs are grouped by
purpose under the team that owns them:

```
<state>/catalogs/
  product/            owned by the Product team
    value-propositions/
    user-stories/
    user-studies/
  design/             owned by the Product team, written by the designer
    decisions/
    components/
  research/           owned by the Lab
    findings/
    reference-surveys/
  pipeline/           owned by the Pipeline team
    gate-runs/  flaky-tests/
```

Each top-level catalog is its own git repository, so every change has a diff
and an author. Documents have a status: `draft`, `proposed`, `decided`,
`rejected`, `superseded`.

### Access control

Permissions are a matrix of role × catalog × action, stored in `teams.json`
and enforced in one place, the `orchestra api` layer that every tool goes
through, keyed by the `ORCHESTRA_ROLE` the loop set when it launched the agent.
Agents never see the matrix; a disallowed call fails and says who may do it.

| Action | Meaning | Default grant |
|---|---|---|
| read | list and read documents | every role, every catalog |
| write | create and edit `draft` documents | members of the owning team |
| propose | move a document to `proposed` | members of the owning team |
| decide | set `decided`, `rejected`, or `superseded` | the owning team's lead |
| grant | change the matrix for the team's catalogs | the owning team's lead |

A lead grants access to its members, for catalogs, data stores, and pages alike: "the designer may write to `design/`",
"the explorer may write to `product/user-studies/` but not read `design/`".
`decided` documents are the contract between teams: Engineering reads decided
design documents; the Lab reads decided user stories to know what to research.
Two catalogs are also code, acceptance tests and reference tests, and those
enter the merge gate only as code tickets through Engineering.

### Channels

Sometimes leads must talk to each other: the Product Owner to the Pipeline
Manager about a flaky acceptance test, the PI to the Coordinator about a survey
that changes a ticket's brief. A **channel** is an explicit grant between two
teams, created by the Supervisor or requested by a lead, that allows
`send_to` between their leads, and optionally between named members. The
default remains the tree; channels are the exceptions, and each one is listed
on the Teams page so the communication pattern is visible. Everything else
crosses teams through `decided` documents.

### Role library

Roles and teams should not be rebuilt per project. The library has three
sources, resolved in order:

1. **Project**: `<repo>/.orchestra/roles/` and `.orchestra/teams/`, versioned
   with the code, for roles specific to that codebase.
2. **User**: `~/.orchestrator/library/`, shared by every project on the machine.
3. **Built-in**: the roles shipped with Orchestra.

A role definition is portable because it names tool groups and event types
rather than project details; project specifics live in the role's prompt
template slots (product name, domain, catalogs). `orchestra role install
<name>` copies a library role into a project; `orchestra role export <name>`
does the reverse. Teams are packaged the same way, so a "Product team" or "Lab
team" can be installed into a new project in one step.

**Done when.** The Product Owner decides a user story, QA files acceptance-test
tickets that cite it, the gate runs them, and the same Product team installs
into a second project from the library.

**Checkpoint.** Do decided documents change tickets? Measure how many tickets
cite a decided document and how often a decision is superseded. If decisions
pile up without affecting work, do not build Stage 4.

---

## Stage 4: Self-organizing teams

**Goal.** Teams run for months with little human attention, and we can tell
whether they help.

- **Leads request members.** A lead may ask the Supervisor for a role to be
  added to its team, with a justification. The Supervisor decides, informed by
  the human. Leads grant their members access themselves.
- **Templates.** Role templates with slots, so the Supervisor instantiates a
  lead, specialist, job worker, reviewer, or explorer rather than writing a
  prompt from nothing.
- **Session rotation.** Resident roles rotate to a fresh session every N turns
  or days, writing a handover document to their catalog first, so memory
  survives but context does not grow without bound.
- **Reference teams.** Pipeline (gate events: a run over 2.5 times the median,
  bisection, flaky tests; a daily test run member that files tickets on
  failure), Product (owner, designer, explorer, user-study coordinator, QA),
  and Lab (PI, researchers, reference surveys turned into tests). Shipped as
  library teams.
- **Impact metrics.** On the Teams page: jobs completed, decisions made and
  cited, tickets that trace to a decision, time from decision to landing, and
  the human's overrides of agent decisions. These are the numbers that answer
  the windmill question.

**Checkpoint.** If the metrics say agent decisions are overridden more often
than they are kept, the right move is to scale back to Stages 1 to 3, which
remain useful on their own.

---

## Open topic: how a team shows its work

This is unresolved and is recorded here so it is not forgotten. It belongs to
Stage 2 or later, but it shapes what a team is for.

**The need.** A team that produces something other than code needs a place to
show it. The R&D lab in an earlier project built its own page: waterfall
diagrams of radio spectrum, a viewer for its analyses and discoveries. It was
dynamic and it was good. A Product team would want user stories, study
results, and design decisions laid out, not a list of catalog files. The
dashboard, ticket graph, and Agents page are Orchestra's views of Orchestra;
a team's output needs the team's own view.

**Two things not to do.**

- Not a page assembled from a fixed palette of pre-defined widgets. The work is
  too variable; a waterfall diagram is not a bar chart with different data.
- Not teams defined by custom HTML and JavaScript as a matter of course. That
  makes a team definition a web project, and makes the Supervisor or lead a
  front-end developer. Sometimes a team genuinely needs a custom page, and
  that must stay possible, but it should be the exception a team earns.

**Directions worth exploring.**

1. *Pages as a job output.* A team's lead can request a page as a job: a
   member writes a self-contained page under a team namespace, served by
   Orchestra at `/teams/<team>/...` with read access to that team's catalogs
   and data, reviewed by the lead like any job. The page is code, but team
   code, not Orchestra code, and not committed to the product repository.
2. *A small document-first default.* Every team gets a default view for free:
   its decided documents rendered as markdown, its findings as a list with
   tags and dates, its jobs with status. Markdown can embed images and simple
   charts a member generated. Most teams would never need more; the lab-style
   page would be the custom exception.
3. *Pages built against an API, not a database.* Whatever a team page is, it
   reads through Orchestra's API, so permissions and the catalog model are
   respected and a page cannot bypass a lead's decisions.

**Data that is not the catalog.** The lab recorded several gigabytes of radio
captures. That data is not a catalog document and does not belong in the
repository or under `~/.orchestrator`. A team needs a *data store* that is
distinct from its catalog: blob storage or a data warehouse, referenced from
catalog documents by URI, with the same read/write grants as catalogs. The
catalog describes and indexes; the data store holds. Which backends, how
retention works, and how a team page reads large data for display are all
open.

**Questions.**

- Does a team's page live with the team definition in the role library, so a
  Lab team installs with its viewer, or is a page always project-specific?
- Who may change a team's page: the lead only, or members through jobs the
  lead reviews?
- What does a page get for free from Orchestra: authentication, the API
  client, the catalog renderer, a chart helper?
- Where does team data go by default on a single machine, and how is it
  routed to blob storage when a project outgrows that?

---

## Open questions

1. **Stage 1 prompt authoring.** Free-form prompt from the Supervisor, or a
   template with slots from day one?
2. **Job results in Stage 2.** A plain document directory per team, or catalogs
   immediately with permissions deferred?
3. **Catalog location.** Under the project state, invisible to the code repo,
   or inside the repo under `.orchestra/catalogs/` where the gate's
   dirty-checkout rule applies?
4. **Decide semantics.** A status the lead sets, or a propose-then-decide flow
   with feedback, like code review?
5. **Channels.** Lead-to-lead only, or may a channel name specific members?
6. **Ephemeral versus resident for daily roles.** Memory versus context growth;
   Stage 4's rotation makes resident safe, but Stage 1 must pick a default.
7. **Library format.** A directory of JSON and markdown, or a Pi package so it
   can be published and versioned?
8. **Team pages and team data.** See the open topic above.

## Build order

Stage 1 first, as one piece of work. Then the Pipeline team's events and daily
run as the first Stage 2 use, since they are already required. Stages 3 and 4
only after their checkpoints.
