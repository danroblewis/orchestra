# Proposal: Orchestra for the whole job

Status: draft, 2026-10-24. Nothing built.

Reads with:
- `docs/work-charter.md` — what is expected of me, and why;
- `docs/proposals/corporate-workflow.md` — code delivery through GitHub
  stacks and SAIL;
- `docs/proposals/teams-and-roles.md` — teams, spaces, jobs.

---

## 1. Why reorganise

Orchestra today is a code-delivery machine for one repository, with an
organisation of agents around it. The job in the charter is mostly not code
delivery. These assumptions break:

| Assumption today | Reality at work |
|---|---|
| A project is one git repository. | Work spans many repos, and much of it has no repo: Slack, PagerDuty, Jira, docs, flags, Jenkins. |
| A ticket is code, ending in a merge. | Most work items are docs, reviews of others' PRs, incidents, approvals, reports, and exercises. Each has its own flow. |
| Orchestra's only output is commits. | Most outputs are messages, comments, Jira tickets, docs, and slides, all **speaking as me**. |
| Orchestra reads nothing outside the repo. | Watching outside systems is half the job. |
| Responsibilities are markdown in a team record. | They must be **checkable**, so they can be tracked. |
| What got done is visible in git and the ticket store. | What got done must become **evidence** for managers. |
| Any model may see any repo file. | FedRAMP: data has classes, and models are cleared for some of them. |

## 2. The new shape

```
                         ┌──────────────────────────── Desk (one per person) ─────────────────────────────┐
  Slack  PagerDuty       │                                                                                │
  Jira   GitHub   ──►  Sources ──► filters (code) ──► events ──► Register (conditions)  ──► Morning brief  │
  Flags  Secrets         │                              │            │ false = to-do                       │
  Jenkins Calendar       │                              ▼            ▼                                     │
  Docs                   │                           Teams (one per domain, agents + tools)                │
                         │                              │ prepare                                          │
                         │                              ▼                                                  │
                         │        Work items (workflows as data) ──► Outbox ──(my approval)──► Actions ──► │──► Slack, Jira,
                         │                              │                                                  │    GitHub, Docs
                         │                              ▼                                                  │
                         │                           Ledger ──► weekly update, monthly slide, OKRs         │
                         │                                                                                │
                         │   Supervisor: the only agent I talk to                                         │
                         └──────────────┬─────────────────────────────────────────────────────────────────┘
                                        │ creates tickets in
                          Code projects (today's Orchestra, one per repo: tickets, workers, gate)
```

**The desk** is new. **Code projects** are today's Orchestra, nearly
unchanged.

## 3. The desk is a project without code

So that we reorganise rather than rewrite, the desk is an ordinary
Orchestra project whose repository is a private notes repo
(`~/work/desk`), not product code. Everything that already exists works
there unchanged:

- the Supervisor;
- teams, roles, and agents in `.orchestra/`;
- team spaces and their `tools/`;
- probes, the event log, scheduled and continuous agents, and the web UI.

Its git history becomes the history of my notes, drafts, and team
knowledge.

Code projects stay one per repository. The desk keeps a registry of them.
The desk Supervisor can ask a code project for work through
`orchestra api --project <key>` (create ticket, read status). A code
project's events are forwarded to the desk, so "my PR merged" reaches the
ledger.

What the desk adds is seven components, each behind a store or adapter as
AGENTS.md requires.

## 4. Components

### 4.1 Sources: reading outside systems

A source is an adapter that pulls records from one system, from a saved
cursor:

- Slack channels;
- PagerDuty incidents and on-call;
- Jira (the team instance and the FedRAMP instance);
- GitHub;
- the flag system;
- the secrets store;
- Jenkins;
- the calendar;
- the docs system.

- **Read-only.** A source never writes.
- **Each source has a data class** (section 4.8).
- **Records are stored locally** behind a store (`orchestra/store/`), with
  a search index. Agents and tools query the store, never the system
  directly. One API poll serves every consumer.
- **Filters are code.** A filter turns records into events:
  - a mention of me;
  - a thread in a watched channel matching my services;
  - an alert in my rotation;
  - a flag enabled in prod;
  - a secret expiring within 30 days;
  - a review requested of me.

  Filters live in the owning team's space as small programs. Most of what
  sources read never reaches a model.

### 4.2 The register: responsibilities as conditions

The charter's section 4 becomes data. A condition has:

- a name and a domain;
- a check: a probe command, or a query over source records and work
  items;
- a severity;
- an owning team;
- a remedy: which agent to wake, or which draft to prepare.

Probes already exist (`orchestra/probes.py`). The register adds the
domain, the owner, the remedy, and a **status board**: every condition, red
or green, with its evidence links. The red ones, ranked, are my to-do list.

Team responsibilities, which are markdown today, gain an optional
`checks:` list pointing at register conditions. A team's lead is woken
when one of its conditions goes red.

### 4.3 Work items with workflows as data

The ticket generalises into a **work item** with a `kind`. Each kind has a
**workflow**: states, which of them are waiting and which active, who acts
in each state, and what moves it on. An actor can be an agent role, me, an
external system, or a condition.

| Kind | Flow (abridged) |
|---|---|
| `code_change` | Today's ticket state machine, plus the stacks and SAIL flow from the corporate-workflow proposal. Lives in a code project. |
| `doc` | Problem Statement → Proposal → Design → in review (comments tracked) → approved → CCB → approved. |
| `ccb_ticket` | drafted → filed → in CCB → approved / changes requested. |
| `review` | Requested → brief prepared → I review → posted → follow-ups. |
| `alert` | Received → enriched (correlations, owners) → usefulness comment drafted → posted → linked to incident or closed. |
| `incident` | Declared (by me) → timeline building → resolved → postmortem item. |
| `postmortem` | Research → report drafted → reviewed → action items filed → tracked to closed. |
| `flag_ramp` | Pending → research brief → I decide → approved or rejected. |
| `prr` | Requested → checklist and evidence gathered → I review → findings → passed. |
| `exercise` | Scheduled → prepared → run → recorded. |
| `customer_ticket` | Assigned → understood → proposed commands explained → **I run** → response drafted → resolved. |
| `report` | Due → drafted from the ledger → I edit → delivered. |
| `check` | Run at a ref → report. |

This is the "loop as an event bus" topic in the teams proposal, made
concrete. The loop runs every workflow the same way: it delivers events to
whoever acts next, under capacity. The code workflow becomes the first
built-in, not the only one. Invariant 1 holds: only Orchestra moves a work
item, by applying its workflow's table to reports.

### 4.4 The outbox: nothing speaks as me unapproved

Agents never call an outside system's write API. They propose a typed
**action** (`slack_reply`, `jira_comment`, `jira_create`,
`gh_review_comment`, `gh_label`, `doc_comment`, ...). The action holds the
exact text and target, and the work item it serves.

- Every action kind has a policy: `draft` (wait for my approval) or
  `auto`.
- **Autonomy is earned, per kind.** Orchestra records whether I approved a
  draft unchanged, edited it, or discarded it. When a kind has a run of
  unedited approvals (say 20), the board offers to make it `auto`. One
  discard puts it back to `draft`. The alert-usefulness comment is the
  obvious first candidate.
- I approve from the UI. A phone-friendly page over the tunnel makes it
  practical.
- Every action taken is logged with what produced it. That is an audit
  trail, which FedRAMP will want.

### 4.5 The ledger: evidence builds itself

An append-only record of what was done, by me or for me:

- PR merged, review given, doc approved, CCB passed;
- alert commented, incident handled, exercise run;
- question answered, junior coached (I note it).

Each entry carries a link, a domain, its audience, and a one-line impact.

- Most entries come from events. Little needs writing by hand.
- Reports are scheduled agents that summarise the ledger: the weekly
  manager update, the monthly slide (through the docs/slides connector),
  quarterly OKR drafts, and performance-review material.

### 4.6 Knowledge tools: being fast and right

Programmatic tools, defined once in `orchestra/harness/tools.py` so every
agent can use them:

- **Code search** across every registered repo (`ripgrep` over local
  clones kept fresh).
- **Change timeline:** commits, deploys, flag changes, and config changes
  in a time window for a service, merged into one list. This is the core
  of "which recent change could have caused this".
- **Who:** on call for a service (PagerDuty), owners (CODEOWNERS, service
  catalogue).
- **Runbooks and past incidents,** searchable.

These serve me directly too: `orchestra ask "what changed in auth-svc in
the last 6h"` is a program, not a model call.

### 4.7 Cost

Usage is recorded per turn and attributed to team, work item, and register
condition.

- Each team has a weekly budget share; the desk has the overall brake.
- The board shows cost per responsibility. That is the number that says
  which agent to turn into a program next.

### 4.8 Compliance

- Every source carries a **data class** (e.g. `public-internal`,
  `team-internal`, `customer`, `fedramp-controlled`).
- Every model in config carries the classes it is **cleared for**.
- Orchestra refuses to put a record into a prompt for a model not cleared
  for its class. It records each refusal.
- Until the company's answers are in (charter, section 8), the clearance
  list is empty for everything but my own code and PRs.

## 5. Teams on the desk

Each charter domain becomes a team. Leads are continuous; most members are
`ad_hoc`, briefed per work item, so they cost nothing while idle.

| Team | Lead | Members (ad hoc unless noted) | Sources | Conditions it owns |
|---|---|---|---|---|
| Chief of staff | Supervisor | Brief writer (scheduled), Report writer (scheduled) | Register, ledger | Brief delivered; reports drafted on time |
| Delivery | (per code project: Coordinator, Pipeline Manager, workers, reviewers) | — | GitHub, Jira | PR age, cycle time, sprint pace |
| Stewardship | Review lead | Review pre-reader | GitHub | Review turnaround, weekly comment target |
| Documents | Docs lead | Writer, CCB clerk | Docs, Jira (FedRAMP) | Every design has a Problem Statement; CCB tickets before rollout |
| Awareness | Watch lead | Channel digester (scheduled) | Slack, PagerDuty, flags, secrets | Digest seen; mentions answered; secrets not expiring |
| Incidents | Incident lead | Alert enricher, Timeline builder, Postmortem writer | PagerDuty, Slack, Jira, change timeline | Alerts commented; action items progressing |
| Safety | Safety lead | Flag-ramp researcher, PRR assessor, DR planner | Flags, Jira, Jenkins | Ramps briefed; DR exercise monthly; Jenkins current |
| Support | Support lead | Ticket reader | FedRAMP Jira | Tickets within SLA; commands explained before I run them |
| Team lead | Team lead | Team tracker, Nudger | Jira, GitHub | Teammates' PRs and tickets fresh; updates ready |
| Improvement | Improvement lead | Impact analyst, Automation finder | Ledger, transcripts, costs | Ideas logged; this month's measurement done |

The **Automation finder** is how the system improves itself. It reads
transcripts, costs, and outbox edit rates, and proposes which agent step
should become a program. Those proposals become code tickets in the desk
repo or in Orchestra itself.

## 6. Changes to Orchestra's rules

To be stated in the commits that make them:

- **Invariant 1** extends from tickets to work items: only the loop applies
  workflow transitions.
- **Invariant 3** (one worktree per ticket) applies to `code_change` items
  only.
- **Invariant 7** gains one operator control: approving, editing, or
  discarding outbox actions. Humans still talk to agents only through the
  Supervisor.
- **New invariant: the outbox.** Nothing is sent to an outside system as me
  except an outbox action, under its kind's policy.
- **New invariant: data classes.** No record reaches a model not cleared
  for its class.
- **New invariant: never run.** No agent runs a command against
  production, customer, or FedRAMP systems. Agents explain and recommend.
- **New invariant: watching is code.** Sources and filters are programs;
  agents read only what filters pass.
- **SPEC.md** gains the desk, sources, register, workflows, outbox,
  ledger, and data classes. **Non-goals** drop "multiple repositories per
  project" in favour of "a desk with many code projects". Code projects
  remain single-repo.

## 7. Package layout additions

```
orchestra/
  sources/        # one adapter per system + filters runner
  actions/        # typed actions, outbox, policies, executors per system
  workflows/      # workflow definitions as data; code_change is built in
  register.py     # conditions, status board
  ledger.py       # evidence records and queries
  policy.py       # data classes, model clearances
  store/          # new stores: source records, work items, outbox, ledger, usage
```

Each system's fake (Slack, PagerDuty, Jira, GitHub, flags) goes in
`tests/e2e/`, as the harness fakes do.

## 8. Build order

Each step is picked to serve the next item in the charter's order of
attack, and nothing is built before it's needed.

1. **The desk as a project; ledger; usage metering.** Ledger fed by GitHub
   only (my PRs and reviews). Evidence starts accumulating.
2. **Register + morning brief,** with GitHub and Jira sources only. Mostly
   programs.
3. **Code delivery at work:** the corporate-workflow proposal, steps 1–2
   (single PRs off master, SAIL).
4. **Outbox,** with the first actions: review-nudge drafts and PR comments.
5. **Review pre-reader** (Stewardship).
6. **Data classes**, then **PagerDuty and Slack sources** once cleared.
   Alert enricher with drafted usefulness comments, and the change
   timeline tool.
7. **Workflows as data:** `doc`, `ccb_ticket`, `report`. Weekly update and
   monthly slide.
8. **Safety, Support, and Team-lead teams.**
9. **Stacks** (corporate-workflow steps 3–4), when a long-haul initiative
   needs them.
10. **Improvement team and prediction,** once the ledger and source
    history are deep enough.

## 9. Risks

- **Building a platform instead of doing the job.** Each step must remove
  hours from a named charter row within two weeks of starting, or it
  stops.
- **Over-trust.** An approval I give based on an agent's brief is still
  my approval. Briefs show their sources, so I can check them.
- **Compliance.** Step 6 waits on the company's answers. Steps 1–5 use
  only my own GitHub data.
- **Tone.** Drafted messages that sound generated hurt the identity they
  serve. Edit rates per action kind measure it.
- **One machine.** The desk runs on my work laptop. It must recover from
  sleep and restarts, as the loop already does after a crash.
