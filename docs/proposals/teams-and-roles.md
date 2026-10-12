# Proposal: Teams and Roles, in four stages

Status: Stage 1 built and checkpointed, 2026-10-11. Stage 2 core built the same
day: roles, agents, and teams as three stores, the loop running agents, prompts
assembled from roles plus responsibilities plus access, the Supervisor's design
guide and tools, the Agents page. Jobs, curated documents, votes, experiments,
and team pages are the rest of Stage 2 and remain to build. Stages 3 and 4
remain proposals.

## Decisions taken

- **Stage 1 is built.** Roles as data, created in conversation with the
  Supervisor, paused and deleted from the UI. The first project to use it
  (the automata game) got a Product Owner, a QA engineer, and the start of a
  developer-experience role from chat.
- **Stage 1 checkpoint, evaluated 2026-10-11: single agents do not accomplish
  much on their own.** A lone scheduled role can observe and file tickets, but
  it cannot delegate, it has nowhere to keep what it learns, and every piece of
  work it wants done has to go through the engineering pipeline as a code
  ticket. The Product Owner mostly reported "board healthy, nothing to do";
  the developer-experience role needs a reader of transcripts, a keeper of
  docs, and a builder of tools, which is three jobs. That is the case for
  teams, so Stage 2 is in scope.
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
- **No catalog system. A team owns a space in the repository instead.** The
  earlier plan had catalogs as a storage system with a permission matrix and a
  separate data store. The value we want comes from somewhere simpler: a team
  needs a place that is its own, where it keeps its notes, its documents, and
  the tools it builds for itself. In other settings that place is a wiki, or a
  chat channel where resident agents meet. Ours is a directory in the project
  repository, managed by the team, possibly kept out of git. Access is by
  directory, read-only or read-write, granted by the lead. The matrix is gone.
- **Documents must stay operative, and that is a mechanism, not a hope.** The
  recurring failure of research and documentation directories, including
  Orchestra's own `docs/`, is that files go stale, nobody reads them, and the
  directory becomes a graveyard that is too big to load and too old to trust.
  So the one part of the catalog idea that was right is kept and made
  central: a curated document has a lifecycle with a decide step, readers
  vote it up or down with a reason, the lead decides on that consensus, the
  whole live set is compacted on a schedule until it fits in a context window,
  and every live document must name what it affects. A document that affects
  nothing is retired. Teams that do not produce documents opt out; the
  lifecycle is per directory, not per team.

## Why stages

The full idea, teams of agents with leads, members, resources, permissions, and
cross-team channels, could absorb weeks and still miss the mark. The honest
answer to "what if this is a windmill" is to build it in stages where each stage
is useful on its own, each has a checkpoint that says whether it earned the
next one, and the first stage covers the one thing we are certain people want:
**their own long-running monitoring agents that receive events.**

| Stage | What it adds | Who needs it | Stop here if |
|---|---|---|---|
| 1. Custom agents | Roles defined as data: prompt, tools, events, schedule. Create, pause, restart, delete. | Everyone. "I want a Product Owner" or "I want a nightly auditor". | Nobody creates a second role, or created roles are ignored. *Passed: roles were created; they were limited, not ignored.* |
| 2. Teams, jobs, and team spaces | A lead with members; non-code work as job tickets reviewed by the lead; a directory per team that the team manages, with its own docs and tools. | Anyone whose agent needs helpers: a developer-experience lead with a retrospective reader and a tool builder; a PO with a designer. | Jobs produce results nobody reads, or team spaces rot. |
| 3. Access, channels, and a role library | Directory grants between teams; cross-team channels; roles and teams shared across projects. | Teams whose output other teams must trust. | Grants are never used beyond the defaults. |
| 4. Self-organizing teams | Leads request members; templates; rotation; reference teams (Pipeline, Product, DevEx, Lab); impact metrics. | A project that runs for months. | The metrics say agents' decisions are not better than the human's. |

The vocabulary, fixed now so it stays stable across stages. Stage 1 fused the
first two; Stage 2 separates them, because a description of what someone can
do and a running instance of someone doing it are different things.

- **Role**: a description of capability, written like a job description or
  the proud part of a resume: what this kind of agent is good at, how it
  works, what tools it needs, how it reports. A role has no runtime. It
  cannot be scheduled, cannot hold a session, and cannot receive a message.
  Roles are reusable across teams and projects.
- **Agent**: an instance of one or more roles, placed in a team. The agent is
  what runs. It has a name, a session policy, and a wake policy, and it is
  the thing that is paused, restarted, messaged, and shown on the Dashboard.
  There are three kinds, by how they are woken:
  - *continuous*: a resident session woken by events as they happen. The
    Coordinator and the Pipeline Manager are continuous agents.
  - *scheduled*: woken on an interval or at a daily time. The session may be
    resident, so it remembers, or ephemeral, so it starts clean. Team leads
    are the agents most often scheduled, because a lead's job is to check
    that its team's responsibilities are being met.
  - *ad hoc*: invoked once, with a brief, by its lead or by Orchestra, and
    closed when the brief is done. Workers and reviewers are ad hoc agents
    invoked by Orchestra per ticket; a lead invokes an ad hoc agent when it
    needs a one-off piece of work and no standing agent fits.
  An agent gets its responsibilities and its access from its team, and its
  skills from its roles. The Supervisor usually creates agents; a human may.
- **Team**: a group of agents, and optionally sub-teams, with exactly one
  **lead** agent. A team has three things of its own:
  - *responsibilities*: short, clearly written prompts stating what the team
    is responsible for keeping true. Not tasks; standing conditions. "Every
    reviewer rejection has a classified cause within an hour" is a
    responsibility. "Classify CA-30's rejection" is a job.
  - *access*: grants to directories, read or write, and to tool groups. The
    team's agents inherit them; the lead may narrow them per agent.
  - *space*: the directory the team owns, with its curated directories and
    its tools.
  A nested team has a parent team; its lead reports to the parent's lead and
  takes on a subset of the parent's responsibilities. The team's
  responsibilities are met by its agents and its sub-teams together, and the
  lead is accountable for that.
- **Member**: any agent in a team that is not the lead.
- **Job**: a unit of non-code work, executed by a member, reviewed by the lead.
- **Grant**: a directory, an agent or team, and `read` or `write`.
- **Curated directory**: a directory in a space whose documents have the
  lifecycle in Stage 2: statuses, votes, a token budget, and a required
  effect. Only curated directories are loaded into prompts.
- **Operative set**: the `active` documents of a curated directory, which is
  what gets loaded into the turns of the agents the directory is for, under
  a token cap so it always fits.
- **Channel**: an explicit, visible permission for two teams' leads to exchange
  messages. The default is the tree: members to their lead, leads to their
  parent's lead, top-level leads to the Supervisor, the Supervisor to the
  human.
- **Supervisor**: the human's interface, above every lead.

How a turn is assembled for an agent, in this order: its roles' prompts, its
team's responsibilities, a summary of its access, the operative sets it is
entitled to, and finally the wake-up or brief that caused the turn. The role
says how the agent works; the team says what it is for; the brief says what
to do now.

Stage 1, which exists, is the degenerate case: a custom role record is both a
role and a single agent of it, with the two dials and no team but the
Supervisor above it. Stage 2 splits the record into a role and an agent, and
today's custom roles migrate as one role plus one agent each.

What exists today in these terms: an Engineering team whose lead is the
Coordinator, whose members are the ad hoc worker and reviewer agents, and
whose responsibilities are the transition table; a Pipeline team whose lead is
the Pipeline Manager with no members yet; and the Supervisor. All three are
defined in Python.

---

## Stage 1: Custom agents (built)

**Goal.** Anyone can add a long-running agent like the Coordinator or Pipeline
Manager without writing Python, and control it from the UI.

**A role is a record.** `.orchestra/roles/<name>.json` plus `<name>.md` for the
prompt, in the project repository; built-in roles stay in code.

```json
{
  "name": "product_owner",
  "description": "Keeps value propositions and user stories current; asks the Coordinator for tickets.",
  "tools": ["tickets", "events", "escalate"],
  "session": "resident",
  "wake_on": ["milestone_closed", "ticket_transition:DONE"],
  "every": "45m",
  "created_by": "supervisor"
}
```

**Wake policy.** `wake_on` is a list of event types from the existing event
log, so any event the loop already emits can wake a role. `every` and `at`
schedule wake-ups. A woken role gets the same wake-up prompt the Coordinator
gets: why it was woken, the execution-health section, and the project snapshot.

**Session policy.** `resident` keeps one harness process alive for the life of
`orchestra run`; `ephemeral` starts a fresh session per wake-up and closes it.

**Tools.** Granted by group: `tickets`, `context`, `pipeline`, `capacity`,
`escalate`, `events`, `roles`.

**UI.** The Agents page shows what each role is: purpose, triggers, next
wake-up, session policy, tool names, who defined it, the prompt file, and the
full prompt. The Dashboard shows only live processes.

**What the checkpoint taught.**

- A role without helpers can only observe and file tickets. When its job needs
  reading long transcripts and also keeping a small set of documents current,
  one resident session cannot do both well: the transcripts crowd out the
  context the documentation work needs. The fix is two roles with one owner,
  which is a team.
- A role has nowhere to keep what it learns. The project context document is
  the Supervisor's, the workers do not read it, and agents may not write into
  the checkout. So a role that wants to maintain documentation for workers has
  to file a code ticket for every line, which nobody will do twice.
- Long design turns hit the wall-clock turn timeout. That is a loop problem,
  not a role problem, and is tracked separately: time out on silence, not
  duration.

---

## Stage 2: Teams, jobs, and team spaces

**Goal.** A role can have helpers, helpers can do work that is not code, and a
team has a place of its own to keep its work and its tools.

**Teams.** `.orchestra/teams/<team>.json` names the lead, the members, the
team's space, the grants the lead has made, and the team's capacity: how many
member sessions may run at once, separate from the engineering worker pool so a
documentation sweep cannot starve code work of the model.

```json
{
  "name": "devex",
  "description": "Keeps the implementation workers effective: accurate docs, good tools, lessons from rejections.",
  "lead": "environment_keeper",
  "members": ["retrospective", "toolsmith"],
  "tracked": false,
  "grants": [
    {"path": ".orchestra/teams/devex", "role": "retrospective", "access": "write"},
    {"path": ".orchestra/teams/devex/tools", "role": "toolsmith", "access": "write"},
    {"path": "automata", "role": "toolsmith", "access": "read"}
  ],
  "capacity": 2
}
```

**The team space.** A directory in the repository, by default
`.orchestra/teams/<team>/`. What goes in it is the lead's decision; a typical
layout is `docs/` for what the team maintains for others to read, `notes/` for
its own working memory and handovers, `reports/` for what it produces per
wake-up, and `tools/` for scripts and small command-line programs the team
writes for itself. The space is the team's wiki and its workbench in one
place, and the team is responsible for it the way a human team is responsible
for its Confluence space: accurate, current, and not too long.

- **Tracked or not.** A team decides whether its space is committed with the
  code (`tracked: true`, which makes it part of the product's history and
  visible to every worktree) or kept out of git (`tracked: false`, which adds
  the directory to `.gitignore` and keeps the space local to the machine). The
  default is untracked: a team's notes and half-built tools are not product
  code and should not pass through the merge gate. Documents a team wants
  workers to read go the other way, through a code ticket, which is the one
  path that lands in every worktree. A later store can sync an untracked space
  to a cloud bucket so it survives the machine; that is the same interface as
  the role store and is not built now.
- **Tools.** A team may write its own tools into `tools/` and they go on the
  `PATH` of every member session, so a team can grow a small command line of
  its own: a transcript summariser, a doc-budget checker, a conflict-overlap
  report. The toolsmith member exists to build these when the lead asks. Tools
  are the team's, not Orchestra's: Orchestra never depends on them and never
  ships them.
- **Budgets.** The lead sets a size budget on the documents it maintains for
  others, and Orchestra enforces it in the write path: a write that takes a
  file over its budget is refused with the current count, so adding a line
  means cutting one. This is the one piece of curation policy that is code.

**Curated documents.** A lead may mark a directory in its space as curated,
typically `docs/` for what the team maintains for others and `findings/` for
research results. Curation is the answer to directories that rot, and it has
four parts, all enforced by Orchestra rather than by prompts alone.

1. *Lifecycle with a decide step.* A curated document carries frontmatter:
   `status`, `affects`, `author`, `decided_by`, `reviewed_at`, `expires`. The
   statuses are `proposed`, `active`, `retired`, and `rejected`. A member
   writes a document as `proposed`; only the lead moves it to `active` or
   `rejected`, and a rejection carries a reason that the author sees on its
   next wake-up. `retired` is for documents that were true and no longer
   matter; `rejected` is for documents that were wrong or not worth the
   budget. Both leave the operative set but stay on disk, so the history is
   searchable and a rejected idea is not proposed again next week.
2. *Votes.* Any role that is given a document in its turn may call
   `vote(doc, up | down, reason)` once per turn: up when the document helped
   it do its work, down when it was wrong, stale, or in the way. Orchestra
   records the votes against the document, with the role, the ticket if any,
   and the reason. Votes are advice, not control: the lead decides, but the
   lead's wake-up shows every active document's score, its last upvote, and
   the reasons for its downvotes, so a document that is being ignored or
   contradicted is visible before it does damage. A document with no votes at
   all for a configured period is flagged as unread, which is the strongest
   signal that it is not operative.
3. *A token budget and scheduled compaction.* Each curated directory has a
   budget in tokens for its operative set, chosen so that the set fits in a
   worker's turn alongside the ticket; a few thousand tokens for worker-facing
   docs, more for a research team's findings. A write that would take the
   operative set over budget is refused with the current count. On a schedule
   the lead runs compaction: merge documents that overlap, cut the ones that
   say what a test now enforces, rewrite long explanations into rules with a
   pointer to the retired long form, and retire what has no upvotes and no
   effect. Compaction is a job the lead can delegate to a member, and its
   result is a diff the lead reviews.
4. *A required effect.* Every active document must say what it affects in
   `affects`: a role whose turns load it (`role:worker`), a gate check that
   enforces it (`gate:unit/doc-budget`), a ticket field it shapes
   (`ticket:verification`), or a tool that implements it (`tool:overlap-check`).
   Orchestra can verify the first three: the role exists and loads the
   directory, the check exists in `orchestra.toml`, the field is referenced
   by the Coordinator's prompt. A document whose effect cannot be verified is
   flagged on the lead's wake-up, and the honest outcome for most of them is
   that the document becomes a test or a tool and retires. That is the whole
   point: documentation that leads to nothing is retired, and documentation
   that leads to something eventually becomes the something.

How a document reaches a worker: a curated directory names the roles it is
for, and Orchestra loads its operative set into those roles' turns, workers
included, the way the project context is loaded for the Supervisor today.
That is what makes an untracked space useful to workers without a code ticket
per line: the docs travel in the prompt, not in the worktree. The budget is
what keeps that safe.

Teams opt in per directory. A lab that keeps raw captures and scratch
notebooks does not curate them; it curates `findings/`. A team that never
writes documents has no curated directory and none of this applies to it.

**Grants and enforcement.** Every member runs with its working directory set
to the team space and `ORCHESTRA_ROLE` set, as workers run in their worktree.
Orchestra's own file tools (the `space` tool group: list, read, write, append)
check the grants before acting and refuse with a message saying who may. The
harness's built-in file tools cannot be fenced the same way, so the second line
is the one that already exists: the checkout's dirty-tree check. A member that
writes outside its grants leaves the checkout dirty, Orchestra reverts the
change, notes it on the lead's next wake-up, and the lead is expected to fix
the member's brief. Reads outside the space are allowed by default: a team
that cannot read the code it is supporting is useless.

**Jobs are tickets.** Tickets gain `kind`: `code` is today's path through
worker, review, and the merge gate; `job` names the member role that executes
it and the team it belongs to. A job runs `OPEN → IN_PROGRESS →
READY_FOR_REVIEW → IN_REVIEW → DONE` and skips `APPROVED` and `MERGING`. Its
reviewer is the team's lead unless the team names a reviewer role. Its result
is written into the team space where the job's brief says.

Why tickets rather than a second queue: one task graph, one dependency model,
one burndown, and "the transcript analysis must finish before the docs ticket
is filed" is an ordinary dependency. The loop, capacity, pause, stop, crash
retry, effective priority, and the drawers apply unchanged. The cost is that
`REJECTED` means "redo the work" for a job, which the prompts explain.

**Communication, the tree.** A member talks only to its lead; a lead talks to
its members and to the Supervisor. `send_to(role, note)` queues a wake-up and
the store rejects calls outside the tree with a message saying why. Leads do
not talk to each other yet; that is Stage 3. The team space is the other
channel: a member's report lands in `reports/`, the lead reads it on its next
wake-up, and nothing needs to be said.

**The first team.** Developer Experience, on the automata project, because the
need is measured. Of the re-engagements on that project, 38 were timeouts, 15
were merge conflicts, and 4 were reviewer rejections, and all four rejections
were decisions a worker made early with too little context. The team:

- *environment_keeper*, lead, resident, daily. Reads the day's commits and
  landed tickets, keeps the curated `docs/` directory accurate and under its
  token budget, decides the retrospective's proposals, runs compaction, and
  reports to the Supervisor in a paragraph with the directory's vote summary.
- *retrospective*, member, ephemeral, woken by reviewer rejections and gate
  conflicts. Reads one transcript, classifies the cause (brief gap, knowledge
  gap, discipline gap, one-off), and writes a two-line `proposed` document
  into `docs/` with an `affects` line, or nothing.
- *toolsmith*, member, ephemeral, woken by jobs from the lead. Builds the
  team's tools: a doc-budget check, a file-overlap report across in-flight
  branches, a transcript digest.

### Experiments

Teams will run process experiments constantly: "workers would pass review
more often if their turn loaded this rule", "the gate would reject less if
batches were smaller". A research experiment is already a job whose result is
a finding. A process experiment needs a little more, because a change made "as
an experiment" with nothing enforcing the experiment is just a change.

The record is prose in the team's space, under a curated `experiments/`
directory, with four fields of frontmatter that Orchestra acts on:

```markdown
---
status: active                      # the usual lifecycle: proposed, active, retired, rejected
variant: docs/worker-rules.md@b     # what is varied: a document variant, a role prompt variant, a config value, or a tool on PATH
scope: {agents: [worker], fraction: 0.5}
metric: reviewer_rejections         # a per-ticket counter Orchestra already keeps
ends: 2026-10-25
---
# Plan-before-edit rule in the worker turn

Hypothesis: workers that write the three lists before editing get rejected
less. Expected effect: rejections per landed ticket from 0.4 to 0.2 over
twenty tickets. Smaller than that is no evidence.

## Log
2026-10-18: 6 tickets in each arm, 2 rejections in control, 1 in variant.
```

What Orchestra does with those four fields, and nothing else:

- *Assignment.* For the agents in scope, the given fraction of turns get the
  variant; the rest get the current version. The arm is recorded on the
  ticket, so the comparison is between tickets that actually ran under each.
- *Measurement.* A `metrics` tool returns the per-ticket counters for a
  window, grouped by arm: worker turns, reviewer rejections, gate send-backs,
  timeouts, time from start to landing. The agent does the comparison itself
  and writes it in the log. There is no statistics engine.
- *Reversion.* On the end date, unless the lead has decided `keep`, the
  variant is withdrawn and the experiment is marked `retired` with "expired
  undecided". `keep` makes the variant the active version of the document or
  prompt. This is the part prompts cannot be trusted with, and it is what
  makes it safe for agents to run experiments without a human watching.

The team's responsibilities carry the discipline: "every experiment has an
end date and a verdict, no verdict is later than its end date by more than a
day, and no two experiments vary the same thing at once". A team may also
require that any change to a worker-facing document above a size go through
an experiment first.

The caveat to put in every lead's prompt: at five or six landed tickets a
day, most experiments will not reach anything like significance in a week.
The lead states the effect it expects before starting; a result smaller than
that is "no evidence", not "it worked". Before-and-after comparisons are
allowed, with `scope: {fraction: 1.0}`, and are labelled observational in the
verdict. An agent that understands that distinction will make better
decisions than one told to test everything.

### Team pages

Every team gets a page at `/teams/<team>` for free, built from what Orchestra
already holds, so it needs no code from the team and is live:

- the responsibilities, each with the lead's last assessment (met, unmet, or
  not yet assessed) and when it was made;
- the agents, with kind, session policy, status, and next wake-up, and the
  sub-teams nested beneath with the same;
- the curated directories: each document with status, votes, last upvote,
  and whether its effect verifies; the operative set's size against budget;
- the experiments: arm sizes, the metric so far, and days to the end date;
- the tools, with their help text;
- the grants the team holds and has given, and its channels.

A top-level Teams page shows the tree, the channels between leads, and the
cross-team grants, so the organisation is visible in one place.

A custom page remains possible as the exception a team earns: a member writes
a self-contained page into the space as a job, the lead reviews it, and
Orchestra serves it under the team's path with read access to the space
through the API, so it cannot bypass a grant. The lab's spectrum viewer is
the kind of thing that needs this; a Product or DevEx team should never need
it. The two things not to do stand: no fixed palette of widgets, and no
custom HTML as the normal way to define a team.

### Worked example: a Product team with a nested QA team

This is what the files look like for a team the Supervisor would plausibly
design for the automata project, using the two custom roles that already
exist there. The point of writing it out is to see where the model creaks
before building it.

```
.orchestra/
  roles/
    product_owner.md          what a Product Owner is good at (exists today)
    qa_engineer.md            what a QA engineer is good at (exists today)
    e2e_author.md             writes a browser acceptance test from a ticket
    analyst.md                reads a transcript or a log and classifies a cause
  agents/
    po.json                   {"roles": ["product_owner"], "team": "product", "kind": "scheduled", "every": "6h", "session": "resident"}
    qa_lead.json              {"roles": ["qa_engineer"], "team": "product/qa", "kind": "scheduled", "every": "1d", "session": "resident"}
    flake_hunter.json         {"roles": ["analyst"], "team": "product/qa", "kind": "continuous", "wake_on": ["gate_rejected"], "session": "ephemeral"}
    e2e_writer.json           {"roles": ["e2e_author"], "team": "product/qa", "kind": "ad_hoc", "session": "ephemeral"}
  teams/
    product.json
    product.md                the Product responsibilities
    product/qa.json           nested: definitions sit under the parent's name
    product/qa.md
  spaces/                     working spaces, apart from the definitions so an
    product/                  untracked space never hides a tracked definition
      docs/                   curated, for: worker, reviewer, coordinator
        stories.md
        non-goals.md
      notes/
      tools/
      qa/                     a sub-team's space nests inside its parent's
        findings/             curated, for: qa_lead, po
        tools/
          flake-report        a script the flake_hunter wrote; on the QA agents' PATH
```

`teams/product.json`:

```json
{
  "name": "product",
  "lead": "po",
  "agents": ["po"],
  "teams": ["product/qa"],
  "tracked": false,
  "access": [
    {"path": "automata", "access": "read"},
    {"path": "tests", "access": "read"},
    {"tools": ["tickets", "events", "escalate"]}
  ],
  "curated": [{"path": "docs", "for": ["worker", "reviewer", "coordinator"], "budget_tokens": 2500}],
  "capacity": 1
}
```

`teams/product/responsibilities.md`:

```markdown
# Product team: what we keep true

1. Every open milestone states, in one paragraph in `docs/stories.md`, what a
   player can do when it closes and why they would want to.
2. The non-goals in `docs/non-goals.md` are current: nothing on the board
   contradicts them, and nothing in them is older than the last two milestones.
3. There are never fewer than ten OPEN tickets, and never more than thirty.
4. No milestone starts its second ticket before the QA team has a browser
   acceptance test planned for it.
```

`teams/product/qa.json` and its responsibilities:

```json
{
  "name": "product/qa",
  "parent": "product",
  "lead": "qa_lead",
  "agents": ["qa_lead", "flake_hunter", "e2e_writer"],
  "tracked": false,
  "access": [
    {"path": "tests/acceptance", "access": "read"},
    {"path": "/Users/daniellewis/.orchestrator/orchestra-automata-db8ce182/gate", "access": "read"},
    {"tools": ["tickets", "events", "pipeline", "escalate"]}
  ],
  "curated": [{"path": "findings", "for": ["qa_lead", "po"], "budget_tokens": 4000}],
  "capacity": 2
}
```

```markdown
# QA team: what we keep true

1. Every milestone has at least one browser acceptance test ticket filed
   before its second feature ticket starts. (Responsibility 4 of Product.)
2. Every gate rejection caused by an acceptance test has a finding in
   `findings/` within a day saying whether the test or the code was wrong.
3. A test that fails twice on unchanged code is quarantined by a ticket within
   a day, and the finding names it.
```

Reading it back, this is how the pieces fit:

- The QA lead is scheduled daily. On each wake-up its turn contains the
  `qa_engineer` role prompt, the QA responsibilities, the Product
  responsibilities above them (a nested lead sees its parent's), its access,
  the active `findings/`, and the wake-up: events since yesterday and the
  project snapshot. It checks each responsibility, and for each one not met
  it either files a ticket (a code ticket for a new e2e test, assigned to
  Engineering) or invokes an ad hoc agent (`e2e_writer` with a brief to draft
  the test plan into `findings/`).
- The flake hunter is continuous and ephemeral: every gate rejection wakes a
  fresh session that reads that run's log from the gate directory, writes a
  `proposed` finding, and exits. The QA lead decides it next morning.
- The Product Owner sees the QA lead's findings because `findings/` names
  `po` as a reader. It never talks to the flake hunter; the tree holds.
- Workers see `docs/stories.md` and `docs/non-goals.md` in every turn, under
  2,500 tokens, and vote on them. If the stories document is ignored for a
  week, the Product Owner's wake-up says so.
- The one tool, `flake-report`, was written by the flake hunter into the QA
  space after it found itself grepping the same gate logs three times. It is
  on the PATH of the three QA agents and of nobody else.

### What will happen when a Supervisor designs this

A prediction, written before building, so it can be checked afterwards.

1. **It will try to do it in one turn and time out.** The first brief on the
   automata project did exactly this. Team design is four creations in order
   (roles, agents, team, responsibilities), each a tool call with a long text
   argument, and a model that thinks before each one does not fit in a
   15-minute turn. Orchestra needs two things: the silence-based timeout, and
   a Supervisor prompt that says "one creation per turn, play back the plan
   first, build on agreement". The human should expect the design to take a
   short conversation, not a message.
2. **It will write responsibilities as task lists.** "Review the backlog
   weekly. File tickets for missing tests." Those are a lead's actions, not
   standing conditions, and a lead that reads them will do them whether or
   not they are needed. The fix is in the Supervisor's prompt with the
   example above: a responsibility is a sentence that can be true or false
   right now. Expect to send it back once.
3. **It will over-grant.** Every agent gets `tickets`, `events`, `pipeline`,
   and `escalate` because that is the list. The team-level grant makes this
   less harmful: the lead can narrow per agent later, and the first time the
   flake hunter files a ticket the lead should have filed, the lead will.
4. **It will create a standing agent for a one-off need.** A "test writer"
   that is scheduled weekly and has nothing to write most weeks. The ad hoc
   kind exists for this, and the Supervisor's prompt should say: if the work
   happens when the lead asks for it, it is ad hoc.
5. **It will reuse the existing roles well** because `list_roles` shows them
   and the prompts are decent. Expect `product_owner` and `qa_engineer` to be
   kept as roles and the two existing custom roles to migrate as the `po` and
   `qa_lead` agents without rewriting.
6. **The nested team will be the part it gets right first**, because the
   subset relation is natural: it will copy Product's responsibility 4 into
   QA's responsibility 1 almost verbatim, which is exactly what should
   happen.
7. **In the first week** the QA lead will find responsibility 1 unmet for
   every milestone and file one test ticket per milestone in a single
   wake-up, which is the right outcome and will briefly flood Engineering.
   The flake hunter will produce findings the QA lead rejects as "code was
   wrong, not the test" about half the time, which is also the right outcome
   and the first real use of the decide step. The Product Owner will keep
   writing "board healthy" until the stories document gets its first
   downvote from a worker, and that downvote is the first moment a document
   changes what an agent does. If that moment never comes, the operative-set
   idea has failed and we should know within a week.

**Done when.** The DevEx team runs for a week on the automata project: the
retrospective proposes lessons, the keeper decides them and workers' turns
load the active set, workers vote, at least one document retires because a
gate check replaced it, the toolsmith ships at least one tool the keeper
uses, and the re-engagement counts on the Dashboard go down.

**Checkpoint.** Does the operative set stay operative? Measure the share of
active documents with an upvote in the last week, the share whose effect
verifies, and whether the directory stays under budget without the human
touching it. If documents accumulate without votes or effects, the lifecycle
is not working and Stage 3 should wait.

---

## Stage 3: Access between teams, channels, and a role library

**Goal.** Teams can rely on each other's spaces, decisions between leads are
explicit, and roles are reusable across projects.

### Grants between teams

Stage 2 grants are inside a team. Stage 3 lets a lead grant another team's
role read or write access to a directory in its space: "Engineering's workers
may read `devex/docs`", "the Product Owner may write to `devex/notes/requests`".
Grants are stored on the owning team and listed on the Teams page, so who can
touch what is visible without reading JSON. Enforcement is the same as Stage 2:
Orchestra's file tools check; the dirty-tree check catches the rest.

Across teams, the contract is the operative set. Engineering's workers load
DevEx's active `docs/`; the Lab's active `findings/` are what the Product
Owner reads. A reader in another team votes like any other reader, and a
lead that sees its documents downvoted by another team has a reason to talk
to that team's lead, which is what channels are for. The decide step stays
with the owning lead; disagreement between leads goes to the Supervisor.

### Channels

Sometimes leads must talk to each other: the DevEx lead to the Coordinator
about two tickets that will conflict, the Product Owner to the Pipeline
Manager about a flaky acceptance test. A **channel** is an explicit grant
between two teams, created by the Supervisor or requested by a lead, that
allows `send_to` between their leads, and optionally between named members.
The default remains the tree; channels are the exceptions, and each one is
listed on the Teams page so the communication pattern is visible.

### Role library

Roles and teams should not be rebuilt per project. The library has three
sources, resolved in order:

1. **Project**: `<repo>/.orchestra/roles/` and `.orchestra/teams/`, versioned
   with the code, for roles specific to that codebase.
2. **User**: `~/.orchestrator/library/`, shared by every project on the machine.
3. **Built-in**: the roles shipped with Orchestra.

A role definition is portable because it names tool groups and event types
rather than project details; project specifics live in the role's prompt
template slots (product name, domain, the team's space). `orchestra role
install <name>` copies a library role into a project; `orchestra role export
<name>` does the reverse. Teams are packaged the same way, with their space
layout and tools, so a "DevEx team" can be installed into a new project in one
step and arrives with its tools.

**Done when.** The DevEx team installs into a second project from the library,
its lead grants Engineering read access to its docs, and the Coordinator acts
on a channel message from the DevEx lead.

**Checkpoint.** Are grants and channels used beyond the defaults, and does
anything cross teams that would not have crossed as a ticket? If not, Stage 4
is not needed.

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
  or days, writing a handover note into their space first, so memory survives
  but context does not grow without bound.
- **Space sync.** An untracked team space can be synced to a cloud store so it
  survives the machine and follows the team into another project. The same
  interface as the role store.
- **Reference teams.** Pipeline (gate events, bisection, flaky tests, a daily
  test run member), Product (owner, designer, explorer, QA), DevEx (keeper,
  retrospective, toolsmith), and Lab (PI, researchers). Shipped as library
  teams with their spaces and tools.
- **Impact metrics.** On the Teams page: jobs completed, documents active,
  retired, and rejected over time, votes per document, the share of active
  documents whose effect verifies, re-engagements per landed ticket over
  time, and the human's overrides of agent decisions. These are the numbers
  that answer the windmill question.

**Checkpoint.** If the metrics say agent decisions are overridden more often
than they are kept, the right move is to scale back to Stages 1 to 3, which
remain useful on their own.

---

## Open topic: how a team shows its work

The default team page and the custom-page exception are now Stage 2 items
(see "Team pages" above). What remains open is the data side, recorded here
so it is not forgotten.

**The need.** A team that produces something other than code needs a place to
show it. The R&D lab in an earlier project built its own page: waterfall
diagrams of radio spectrum, a viewer for its analyses and discoveries. It was
dynamic and it was good. A Product team would want user stories, study
results, and design decisions laid out, not a directory listing. The
dashboard, ticket graph, and Agents page are Orchestra's views of Orchestra;
a team's output needs the team's own view.

**Two things not to do.**

- Not a page assembled from a fixed palette of pre-defined widgets. The work is
  too variable; a waterfall diagram is not a bar chart with different data.
- Not teams defined by custom HTML and JavaScript as a matter of course. That
  makes a team definition a web project, and makes the Supervisor or lead a
  front-end developer. Sometimes a team genuinely needs a custom page, and
  that must stay possible, but it should be the exception a team earns.

**Data that is not the space.** The lab recorded several gigabytes of radio
captures. That does not belong in a repository directory, tracked or not. A
team that produces bulk data needs a store outside the repo, referenced from
its space by URI. Which backends, how retention works, and how a team page
reads large data for display are all open, and the Stage 4 space sync is the
natural place for it to appear.

---

## Open questions

1. **Space default.** Untracked by default is the proposal; is there a kind of
   team whose space should be tracked from the start (a Product team whose
   decisions should be in the product's history)?
2. **Writing docs for workers.** A team's untracked space is invisible to
   worktrees, so worker-facing docs must land through a code ticket. Is that
   friction acceptable, or should the keeper have a narrow write grant on a
   tracked directory such as `docs/agents/` that commits on the base branch
   when the checkout is clean, as the role store does today?
3. **Enforcement.** Grants are enforced by Orchestra's own file tools plus the
   dirty-tree check. Is that enough, or does a member need a sandboxed
   working directory with only its granted paths visible?
4. **Tools on PATH.** A team's tools are on the PATH of its member sessions.
   Should a team be able to offer a tool to another team, and is that a grant
   or a copy?
5. **Channels.** Lead-to-lead only, or may a channel name specific members?
6. **Library format.** A directory of JSON and markdown, or a package so it
   can be published and versioned, now that a team ships with tools?
7. **Vote weight.** One role, one vote per turn is the proposal. Should a
   worker's vote on a worker-facing doc count more than a reviewer's, and
   should a vote from a turn whose ticket was later rejected count at all?
8. **Budgets in tokens.** Tokens are the honest unit because the constraint is
   the context window, but the count depends on the model. Count with one
   fixed tokenizer and accept the error, or budget in characters and say so?
9. **Orchestra's own docs.** The same rot affects `docs/` in this repository.
   Should Orchestra's self-hosting project curate it with the same lifecycle,
   which would make Orchestra the first user of the mechanism?
10. **Experiment variants of config.** A document or prompt variant is
    per-turn. A config variant such as gate batch size is global while it is
    on, so its arm is a time window, not a fraction of turns. Is that worth
    supporting in the first version, or are document and prompt variants
    enough to start?
11. **Team data.** See the open topic above.

## Spec changes Stage 2 requires

Recorded here so the commit that builds Stage 2 updates `AGENTS.md` and
`SPEC.md` deliberately rather than by accident.

- Invariant 3 ("nothing is ever written inside the user's checkout except
  `orchestra.toml`") already has one exception in practice, `.orchestra/roles/`.
  Stage 2 widens it to `.orchestra/`: roles, teams, and team spaces, written
  only through Orchestra's stores and tools, never by the merge gate, and
  never by an agent's own file tools outside its grants.
- A new tool group, `space`, and a new store, `TeamStore`, with the same
  shape as `RoleStore`. The store owns the curated-document index: statuses,
  votes, budgets, and effect verification. Agents never edit frontmatter
  directly; `propose`, `decide`, `vote`, and `retire` are tools.
- Role turns gain a loaded-documents section: the operative sets of the
  curated directories that name the role, under their budgets, with document
  ids so a vote can refer to one.
- Roles split from agents: `.orchestra/roles/` keeps the role (prompt and
  tool needs); `.orchestra/agents/<name>.json` holds the instance (roles,
  team, kind, schedule, session policy). Stage 1 custom roles migrate as one
  role plus one agent each, and the Agents page lists agents, not roles.
- Teams: `.orchestra/teams/<team>.json` plus `<team>/responsibilities.md`;
  nested teams by `parent`. A turn is assembled as roles, then
  responsibilities (own and ancestors'), then access, then operative sets,
  then the brief.
- Tickets gain `kind` and, for jobs, `team` and `executor`. The transition
  table gains the job path.
- Member sessions get the team's `tools/` on `PATH` and their working
  directory set to the space.
- Experiments: the loop assigns variants per turn from the `scope` fraction,
  records the arm on the ticket, withdraws the variant on `ends` unless
  decided `keep`, and exposes a `metrics` tool grouping per-ticket counters
  by arm. Variants exist for curated documents, role prompts, config values,
  and tools on `PATH`.
- Team pages: `/teams` and `/teams/<team>` served from the team store, the
  agent registry, the curated index, and the experiment records; custom pages
  served from the space under the team's path through the API.

## Build order

Stage 2 as the next piece of work, driven by the DevEx team on the automata
project, because that team's need is measured and its first week is the
checkpoint. Stage 3 only after a second team wants to read the first team's
space. Stage 4 after a project has run for a month.
