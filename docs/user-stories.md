# User stories

Status: draft, 2026-10-24. Stories from my work, modelled as system dynamics processes.

- **Stories 1–3** are mine, as I described them.
- **Story 4 onward** are invented: what probably happens in an engineering department like mine,
  at time scales from minutes to quarters. Delete the ones that don't apply.

Each story becomes acceptance tests of two kinds:

- **Functional tests**, written Given/When/Then, to run against fakes of each company system
  (GitHub, Slack, Jira, SAIL, PagerDuty, flags, docs). Every outside system gets a fake that
  speaks its real protocol, as AGENTS.md already requires for harnesses. These are for the
  Orchestra implementation, which lives on another branch.
- **Model tests**, which run now against the SD models in `models/` (`node docs/models/check.mjs`).
  They check that a model reproduces what I know today (validity), and whether the design meets its
  targets (requirements). A requirement the design doesn't meet is reported as a **design gap**.

Companions:
- **`user-story-diagrams.md`**: every modelled story drawn, with charts of manual against designed.
- `models/README.md`: the models, assumptions and results.
- `rationale/`: why system dynamics.
- `work-charter.md`: the expectations these stories serve.

---

## How every story is modelled

**Three sides.** Every stock belongs to one side:

| Side | What it holds |
|---|---|
| **Ours** | What Orchestra owns and runs: our agents, programs, outbox, and my time. |
| **Company** | What the company's systems and people hold: PR checks, AI review, human review, SAIL, CCB, other teams. We observe these; we don't schedule them. |
| **Interface** | The stocks where work crosses: asks coming in, drafts waiting for my approval before they go out as me, pings. |

**Machines on flows:**

| Machine | Kind | What it does |
|---|---|---|
| `me` | person | My time |
| `analyst` | agent | Research, context, root cause |
| `drafter` | agent | Tickets, descriptions, messages. Everything it writes goes to my outbox. |
| `implementer` | agent | Code and fixes |
| `orchestra` | code | Probes, routing, pings, labels, pattern-matched triage |
| `environment` | — | The company and its people |

**Crossings.** Every flow that touches a company system is marked with what it crosses, and how:

| Class | Meaning | Examples |
|---|---|---|
| **Sense** | Read only | Check results, review threads, runbooks, flag history |
| **Speak** | Written as me | Slack, Jira, GitHub comments. Always through the outbox, until a kind of message earns autonomy. |
| **Act** | Programmatic writes | Push, open PR, add a label |
| **Human only** | Never done by any machine but me | A production command |

**Budget.** It's a stock that agent flows draw from. When it's empty, agent flows stop.

---

## Story 1: a simple task for another team

**As** an engineer whom other teams increasingly ask for small tasks, **I want** to spend only
the time it takes to collect the requirements, **so that** the task is still done thoroughly while
I do my own work.

**Timeline:** request to delivered in days. Today, many never get done.

**Model:** `models/story-1-simple-task.json` (22 stocks, 24 flows). Variants: `manual`, `rising`,
`manual-rising`, `better-first-pass`.

### The process

| # | Step | Side | Machine | Crosses |
|---|---|---|---|---|
| 1 | Someone asks | company → interface | environment | Slack or Jira in |
| 2 | Collect the requirements, in the conversation | interface | **me** | |
| 3 | Research the problem as stated; identify stakeholders; link to ongoing projects | ours | analyst | Sense: Jira, docs, Slack, code |
| 4 | Author a full ticket with requirements and completion criteria | ours | drafter → my approval | Speak: Jira |
| 5 | Implement on a branch | ours | implementer | |
| 6 | Run tests; internal AI review; a quarter go back for another pass | ours | implementer | |
| 7 | Write a thorough, concise PR description in the company format | ours | drafter, inside step 6 | |
| 8 | Approve and submit the PR | interface | **me** (approval) | Act: push, open PR |
| 9 | Company PR checks; failures fixed and pushed again | company ⇄ ours | environment; implementer | Sense: check logs; Act: push |
| 10 | Company AI review; comments addressed | company ⇄ ours | environment; implementer | Sense: PR comments; Act: push |
| 11 | Post for review in our channel and the owning teams' channels | interface | drafter → **me** | Speak: Slack |
| 12 | Ping reviewers about once a working day while they haven't reviewed | interface | orchestra | Speak: Slack (auto once earned) |
| 13 | Human review: approve, or request changes | company | environment | |
| 14 | Address comments; draft replies; I approve; push; re-request review. Loop until approved. | ours → interface | implementer → **me** | Sense: threads; Speak: replies; Act: push |
| 15 | Add the SAIL label | interface | **me** (one click), later orchestra | Act: label |
| 16 | SAIL: lands, or fails | company | environment | |
| 17 | Triage a SAIL failure: known flake gets a re-label; real failure goes to a fix | interface | orchestra; implementer | Sense: SAIL logs; Act: label |
| 18 | Draft the Jira comment and status change, and the message to the requester | ours | drafter | |
| 19 | Approve and send | interface | **me** | Speak: Jira, Slack (where the ask came from, or where they read) |

### Loops

- **Rework loops crossing the boundary:**
  - checks fail → fix → checks;
  - AI comments → fix → checks;
  - change requested → fix → checks → AI review → re-post → review;
  - SAIL fails → fix or re-label.

  Each round costs a company delay plus agent money. **Iterate inside, cross once:** the internal
  rework loop (step 6) is fast and cheap, while every boundary loop is slow and costly.
- **Ping loop:** pings speed reviewers up with diminishing returns, and fade.
- **Reciprocity (desk):** reviews I give build goodwill, which speeds reviews of my PRs (story 4).
- **Budget (desk):** agent flows drain the budget. When it binds, everything agent-driven slows.

### What stays mine

- Collecting requirements.
- Approving the ticket, the PR, each review post, each reply, and the close-out messages.
- The SAIL label, until it earns autonomy.
- Nothing is said or pushed as me without passing through my outbox.

### Functional acceptance tests

1. **Given** a Slack message asking me for a task, **when** I tell the Supervisor the
   requirements, **then** within one working hour a ticket draft is in my outbox with:
   - the problem restated;
   - stakeholders and the teams owning affected code (from CODEOWNERS and the service catalogue);
   - linked ongoing tickets or epics;
   - requirements;
   - completion criteria, each with how it will be verified.
2. **Given** an approved ticket, **when** implementation finishes, **then** before anything
   reaches GitHub:
   - the project's tests pass in the worktree;
   - an internal review has run and its findings are addressed;
   - a PR description in the company format is drafted, with the Jira key, summary, testing
     section from the real test output, and revert note.
3. **Given** I approve the PR draft, **then** the branch is pushed and the PR opened against the
   right base. **No other path pushes or opens PRs.**
4. **Given** PR checks fail, **then** the failure log goes to the same implementation session, a
   fix is pushed, and I'm not notified unless it fails three times.
5. **Given** the company's AI review posts comments, **then** each is addressed or answered, and the
   answers wait in my outbox.
6. **Given** checks and AI review pass, **then** a review-request post is drafted for our channel
   and for each channel owning affected code, and waits for my approval.
7. **Given** a PR is waiting for review, **then**:
   - a ping goes to the requested reviewers about once a working day;
   - pings stop at approval;
   - pings never exceed one per reviewer per day;
   - each ping until the template earns autonomy is an outbox item.
8. **Given** a reviewer requests changes, **then**:
   - all unresolved threads from that review are addressed in one round;
   - replies are drafted per thread;
   - after my approval, the fixes are pushed and the reviewer is re-requested and pinged.
9. **Given** the required approvals, **then** the SAIL label is offered to me as one click (later:
   added automatically).
10. **Given** SAIL fails:
    - **with a known flake pattern:** the label is re-applied, at most N times, with backoff;
    - **otherwise:** the log goes to the implementation session as a fix.
11. **Given** the PR lands, **then** a Jira comment, a status change, and a message to the requester
    (in the channel or DM the ask came from) are drafted and wait for my approval.
12. **Given** any step fails in a way no rule covers, **then** the request is BLOCKED with the
    reason and appears in my morning brief. **Nothing is silently dropped.**

### Model acceptance tests (`check.mjs`)

| Id | Kind | Test | Result |
|---|---|---|---|
| 1.1 | validity | Manual reproduces today: I'm fully busy, work piles up waiting for me, few requests finish | pass: busy 100%, waiting 4 → 22, 4 of 24 delivered |
| 1.2 | requirement | Designed: nothing piles up waiting for me | pass: 0.3 waiting |
| 1.3 | requirement | Designed: most requests delivered within four weeks | pass: 22 of 24 |
| 1.4 | requirement | Designed: at most one hour of my time per delivered request | pass: 0.94 h |
| 1.5 | requirement | Designed: at most $20 of agent work per delivered request | **gap: $22** |
| 1.6 | requirement | Designed: started to merged within 4 working days | **gap: 5.2 days; 90% of the wait is on the company's side** |
| 1.6b | info | Better first pass at each boundary | $16 per request, 4.3 days |
| 1.7 | requirement | At 10 requests a week, the design still keeps up; manual falls further behind | pass: 0.3 vs 39 waiting |

**What the model says.** Agents remove my overload: ten hours of my time per task becomes under one.
They don't remove the wait, because turnaround is set by the company's review and SAIL. The
four-day expectation is reachable only by fewer round trips across the boundary (better first
pass) and faster human review, not by faster agents. Making agent flows 10% faster changes nothing
in the leverage ranking.

---

## Story 2: a request to run a production command

**As** the engineer asked to run commands on production bastions, **I want** to know what a
command does, what it risks, who authorised it, why it's needed, and whether it repeats elsewhere
before I run it. **I also want** what I learn to become prevention, **so that** I run commands
safely and these requests become rarer.

**Timeline:** the run in hours. The prevention cycle in weeks.

**Model:** `models/story-2-prod-command.json` (15 stocks, 12 flows; twelve-week horizon). Variants:
`manual` (today's shortcut), `manual-thorough` (me doing it all properly).

### The process

| # | Step | Machine | Crosses |
|---|---|---|---|
| 1 | Someone asks me to run a command | environment | Slack or Jira in |
| 2 | Find related runbooks; explain what the command does, its impact and risk | analyst | Sense: runbooks, code, docs |
| 3 | Verify the chain of authority: approvals, change ticket, the requester's role | orchestra | Sense: Jira approvals, change tickets, org chart |
| 4 | Root cause and context. Is this tied to a customer support request? To a feature merged or ramped unsafely? A follow-up to a rollout? Will it need repeating manually in government and monthly-deployed environments? | analyst | Sense: customer Jira, flag history, deploys, release calendars |
| 5 | Read the brief and decide: run, decline, or redirect | **me** | |
| 6 | Run it | **me only, never a machine** | Human only: bastion |
| 7 | Log what happened and why, where the company sees it | drafter → **me** | Speak: Jira or Slack |
| 8 | File follow-up tickets for the other environments | drafter → **me** | Speak: Jira |
| 9 | Look for patterns across requests worth preventing | analyst | |
| 10 | Turn patterns into problem statements, then proposals, and present them to my managers and team | drafter + **me** | Speak: docs, Slack |
| 11 | The company reviews and adopts the prevention: policy or automation | environment | |

### Loops

**Prevention, a balancing loop with a long delay.** Adopted preventions lower the arrival rate of
these requests. Today the loop is open: nobody has time for steps 9–10, so it never closes.

### What stays mine

- The decision.
- **Running the command. Every variant of the model asserts this structurally.**
- Editing the proposals.

### Functional acceptance tests

1. **Given** a request to run a command, **when** it arrives, **then** within 30 minutes a brief is
   ready with:
   - what the command does, line by line;
   - related runbooks;
   - what it touches and its blast radius;
   - risks and how to undo it;
   - the authority chain, with links, and whether it's complete;
   - the context findings (customer ticket, recent flags or deploys, rollout follow-up, other
     environments).
2. **Given** an incomplete authority chain, **then** the brief says what's missing and drafts the
   question to the requester. The command isn't presented as ready.
3. **No agent tool can reach a bastion host.** A test asserts that no tool in the catalogue opens a
   session to production hosts.
4. **Given** I ran the command, **then** a log entry is drafted with the command, the reason, the
   authority, the outcome, and links, for my approval.
5. **Given** the command must repeat in other environments, **then** a follow-up ticket per
   environment is drafted.
6. **Given** two or more requests share a cause, **then** a problem-statement draft citing them
   appears in my weekly list for managers and the team.

### Model acceptance tests

| Id | Kind | Test | Result |
|---|---|---|---|
| 2.1 | validity | Only I run production commands, in every variant | pass |
| 2.2 | requirement | Full due diligence costs me under a quarter of doing it all myself | pass: 0.70 h vs 5.26 h (today's shortcut: 2.87 h, skipping root cause and prevention) |
| 2.3 | requirement | Prevention is adopted, and requests become rarer | pass: about 3 adopted in 12 weeks; 2.0 → 1.4 a week; today: none |
| 2.4 | requirement | Every repeat needed elsewhere becomes a ticket | pass: today about 4.5 are never filed |

---

## Story 3: a manager asks for status

**As** an engineer whose managers ask for project status assuming I remember it, **I want** a status
page that's already current, **so that** I can send it in minutes instead of redoing the research.

**Timeline:** the answer in minutes. Status drift in hours.

**Model:** `models/story-3-status-request.json`. Variant: `manual` (no status page).

### The process

- Projects move on: tickets, docs and threads change, and what I know goes stale.
- The analyst re-reads changed items and updates the status page. This is mostly sensing: a
  program detects changes, and the agent only summarises what changed.
- A manager asks. I send the page with a line of context, or do the research from scratch.

### Loops

**Staleness.** Drift fills the stale stock. Refresh drains it. My answering speed is an effect of
how stale it is.

### Functional acceptance tests

1. **Given** the projects and processes I track (a list I maintain), **then** a status page lists
   for each:
   - state;
   - last change;
   - owner;
   - next step;
   - blockers;
   - links to the tickets, docs and threads the state came from.
2. **Given** a ticket, doc or thread changes, **then** the affected entry is refreshed within one
   working hour, with the change noted.
3. **Given** a manager's question, **when** I ask the Supervisor, **then** a two-to-five line answer
   drafted from the page, with links, is ready in under five minutes.
4. **Given** an item nobody has touched for N days, **then** it's flagged as possibly stale at the
   source, not just in my page.

### Model acceptance tests

| Id | Kind | Test | Result |
|---|---|---|---|
| 3.1 | requirement | The status page stays current (at most 10 stale items) | pass: mean about 1 vs 56 |
| 3.2 | requirement | An answer costs me at most 15 minutes; manual at least an hour | pass: 0.21 h vs 1.72 h |

---

## Story 4 (invented): reviewing teammates' PRs

**As** a reviewer expected to review often and well, **I want** a brief before I read each change:
- what it does;
- where the risk is;
- likely bugs;
- related recent commits;
- whether the description matches the diff.

**So that** my reviews are fast, catch real problems, and build the goodwill that gets my own PRs
reviewed.

**Timeline:** within a working day.

**Model:** `models/story-4-reviews-given.json`, coupled to story 1 in the desk model.

**Stays mine:** the verdict and every comment's wording.

**Functional tests:**
- **Given** a review request, **then** a brief is ready within an hour.
- Comments I write are posted only on my approval.
- **No agent approves a PR.**

**Model tests:**

| Id | Kind | Test | Result |
|---|---|---|---|
| 4.1 | requirement | Requests don't pile up | pass |
| D.5 | info | Reciprocity | 22 vs 21 simple tasks delivered with and without reviews given: small at these assumptions |

---

## The desk: every story together

**Model:** assembled from the four stories by `check.mjs`. It shares my time, the agents and the
budget, plus the declared coupling in `models/desk.couplings.json`.

| Id | Kind | Test | Result |
|---|---|---|---|
| D.1 | validity | Manual: fully busy, work piles up waiting for me | pass: 9 → 55 waiting |
| D.2 | requirement | Designed: everything fits in my free time, with slack | pass: 46% busy |
| D.3 | validity | Agents can never spend more than the budget holds | pass |
| D.4 | requirement | Agent work fits the $120 weekly share | **gap: $150 a week wanted** |

**What the desk says.** Once agents carry the work, the binding constraint is the budget, not my
time. The levers are:
- cheaper steps (programs in place of agents);
- fewer boundary rounds;
- choosing which requests get the full treatment.

---

## Invented stories, not yet modelled

Each has its structure in a line or two, its crossings, and its acceptance criteria. Model files
come when a story is chosen for work.

### Story 5: a PagerDuty alert while on call (minutes)

**As** on-call, **I want** each alert enriched within a minute:
- recent deploys, flag changes and config changes for the service;
- who is on call for its dependencies;
- similar past alerts and their outcomes;
- a draft of the usefulness comment for the alert's Jira ticket.

**So that** I decide quickly whether it's an incident and keep the alert-quality record up.

- **Structure:** alerts → enriched (orchestra programs; analyst only for the summary) → decided
  (me) → incident or closed. The usefulness comment goes through my outbox.
- **Feedback loop:** comments on noisy alerts → alert tuning → fewer alerts.
- **Crossings:** Sense: PagerDuty, deploys, flags, on-call schedules. Speak: Jira comment.
- **Stays mine:** declaring an incident, and incident command.
- **Accept:**
  - an enriched alert view within 60 s of the page;
  - every alert ticket in my rotation has a usefulness comment draft within the shift;
  - the enrichment's change timeline is produced by a program, not a model call.

### Story 6: incident to postmortem to action items (one to three weeks)

**As** an incident participant, **I want** the timeline assembled from Slack, PagerDuty, deploys
and flags, a draft postmortem report with contributing factors, and action items filed with
owners, **so that** postmortems are complete and their items actually close.

- **Structure:**
  - timeline built → report drafted → reviewed (company) → actions filed → actions closed;
  - **latent risk** (open action items) is a stock in the target system;
  - actions needing proposals enter the Problem Statement → Proposal → Design cycle (story 11).
- **Crossings:** Sense: Slack, PagerDuty, deploys, flags. Speak: docs, Jira.
- **Stays mine:** the conclusions.
- **Accept:**
  - a timeline within a day of resolution, with every entry linked to its source;
  - each action item has an owner, a date, and weekly progress, or appears in my brief.

### Story 7: a feature-flag ramp to approve (one to two days)

**As** a ramp approver, **I want** a research brief per ramp:
- what the flag guards;
- its ramp schedule;
- the metrics watched and their current values;
- rollback;
- similar past ramps and their incidents;
- whether the code behind it is covered by tests.

**So that** my approval is informed, and fast enough not to block the team.

- **Structure:** ramps pending → briefed (analyst) → decided (me) → approved or rejected.
- **Coupling to the target system:** the change failure fraction falls as ramp review coverage
  rises.
- **Accept:**
  - a brief within two hours of the request;
  - every approval records what was checked.

### Story 8: a secret about to expire (weeks of lead time)

**As** an owner of services with secrets, **I want** expiry found by a program with 30 days' notice,
and the rotation carried as a simple task (story 1), **so that** nothing expires in production.

- **Structure:** a pure program probe (no model cost) → ticket → story 1 pipeline.
- **Crossings:** Sense: the secret store. Then story 1's.
- **Accept:**
  - no secret I own is within 30 days of expiry without a ticket;
  - the probe makes no model calls.

### Story 9: a long-haul project as stacked PRs (weeks to months)

**As** the lead on a large project, **I want** it to move as:
1. Problem Statement;
2. Proposal;
3. Design;
4. CCB approval;
5. a chain of small stacked PRs, each branched off the one before;
6. each kept rebased and retested by programs;
7. each landing through review and SAIL in turn.

**So that** reviewers see small, meaningful changes and the project keeps moving while early PRs
wait.

- **Structure:**
  - document stocks feed a stack;
  - each change is a stock chain (story 1's company side);
  - the restack and retest flows run on programs;
  - conflicts go to the implementer.
- **Loops:** freshness decay (master moves → stale → rebase → retest), and rework that climbs the
  stack.
- **Coupling:** human review capacity, and whether a push dismisses approvals (`proposals/corporate-workflow.md`).
- **Accept:**
  - every branch in a stack is rebased on its parent and green within N hours of the parent moving;
  - no unreviewed depth beyond the cap;
  - the squash commit is found from the merged PR and the next branch restacked onto it
    automatically.

### Story 10: a FedRAMP change announcement through CCB (days)

**As** the owner of a change to FedRAMP production, **I want** the change-management Jira ticket
drafted from the design and the PR, filed, and tracked to approval before rollout, **so that** no
change ships without CCB approval.

- **Structure:** draft → filed → in CCB (company) → approved, or changes requested → rollout
  allowed.
- **Accept:**
  - every rollout to FedRAMP is preceded by an approved CCB ticket. A probe checks it, and a missing
    approval blocks the rollout step in the plan;
  - the ticket draft cites the design and PRs.

### Story 11: Problem Statement → Proposal → Design, with reviewers (weeks)

**As** an engineer who must get documents reviewed before building, **I want**:
- drafts from my notes;
- reviewers chosen by ownership;
- comment threads tracked to resolution;
- reminders paced like story 1's pings.

**So that** documents get reviewed and approved without me chasing each one.

- **Structure:** drafted → in review (company) → comments → revised → approved. The same ping and
  reciprocity loops as PR review.
- **Accept:**
  - every open document shows its unresolved threads and who owes a response;
  - no document waits more than N days without a nudge drafted.

### Story 12: a FedRAMP customer bug ticket (SLA hours to days)

**As** an engineer assigned customer tickets, **I want** each one read, summarised, linked to known
issues and recent changes, and any requested commands explained as in story 2, **so that** I
respond within SLA and run only what's safe.

- **Accept:**
  - a summary and proposed response within one working hour;
  - requested commands go through story 2's brief;
  - customer data never reaches a model not cleared for it.

### Story 13: a Slack question about my code (hours)

**As** the owner of some code, **I want** an answer drafted from the code, its README and its
history, with links, **so that** I answer quickly and correctly.

- **Accept:**
  - a draft within 15 minutes of the question;
  - every claim links to code or docs;
  - answers to repeated questions are proposed as README additions.

### Story 14: teammates' stale PRs and Jira hygiene (daily)

**As** someone expected to keep the team's work moving, **I want** a daily list:
- teammates' PRs waiting more than N days for review, and by whom;
- tickets in progress with no activity;
- drafted nudges for each.

**So that** I nudge with one click instead of scouring boards.

- **Structure:** pure programs, plus drafts. Pairs with the goodwill loop: nudge, don't nag.
- **Accept:**
  - the list arrives every morning;
  - nudges go only on my approval;
  - at most one nudge per person per day.

### Story 15: the weekly update and the monthly slide (weekly, monthly)

**As** an engineer reporting to managers and upper management, **I want** the weekly update and
the monthly slide drafted from the ledger (what landed, what was reviewed, what was prevented,
with links), **so that** reporting takes minutes and shows the real work.

- **Accept:**
  - the draft is ready a day before it's due;
  - every claim links to evidence;
  - the slide shows this month's useful outcomes, not activity.

### Story 16: a port to a release branch (days)

**As** the owner of a change that must reach a release branch, **I want**:
- the landed squash commit cherry-picked onto a branch from the release branch;
- a PR opened through the company's port process (`arc port` or the PORT label, whichever does
  the work);
- conflicts handled by the implementer.

- **Accept:**
  - a port PR within an hour of the original landing;
  - its tests are the release branch's;
  - it's tracked to landed like story 1.

### Story 17: a check on a release branch (hours)

**As** someone asked to verify behaviour on a release branch, **I want** a detached worktree at
that ref, the requested checks run, and a report, with no branch and no PR.

- **Accept:**
  - the report has the commands, outputs and verdict;
  - the worktree is deleted afterwards;
  - nothing is pushed.

### Story 18: the monthly disaster-recovery exercise (monthly)

**As** the owner of the DR exercise, **I want** the plan drafted from last month's, the
prerequisites checked by probes, a checklist during the exercise, and the record filed after,
**so that** it happens every month and leaves evidence.

- **Accept:**
  - a plan two weeks ahead;
  - prerequisites checked a week ahead;
  - the record is filed within a day.

### Story 19: a small improvement with measured impact (weeks)

**As** an engineer expected to find and prove small improvements, **I want**:
1. the target metric's baseline measured;
2. the change made through story 1;
3. the metric remeasured over a stated horizon, with a verdict;
4. a slide.

**So that** improvements carry evidence, not anecdotes.

- **Structure:** the intended-effect test from `rationale/lifted-models.md`: predict, change, re-fit,
  judge.
- **Accept:** each improvement has a written prediction before work starts, and a verdict with
  numbers after.

### Story 20: the morning brief (daily)

**As** someone responsible for many standing conditions, **I want** one page each morning:
- the conditions that are false, ranked;
- overnight alerts and outages;
- what waits for my approval;
- my PRs stuck and why;
- reviews owed;
- deadlines.

**So that** I start the day knowing what needs me.

- **Accept:**
  - the brief is ready by a set time;
  - every item links to its source;
  - it's built mostly by programs, with one cheap summarising pass.

### Story 21: a junior engineer asks for help (hours)

**As** a mentor, **I want** context prepared for the conversation (their PR, the code, what they
tried), **so that** my time with them is about teaching. **The coaching is mine; the agent only
prepares.**

- **Accept:**
  - a context note within 15 minutes of the ask;
  - nothing is sent to the junior engineer by an agent.

---

## The interface: what crosses, and what we keep apart

Across every story, we cross into a small number of company systems:

| System | Sense (read) | Speak (as me, via outbox) | Act (programmatic) | Human only |
|---|---|---|---|---|
| GitHub | Checks, AI review comments, reviews, threads, merge state, merge commit | Review replies, my reviews | Push, open PR, label | Approving a PR |
| Slack | Asks, mentions, threads in watched channels | Posts, pings, answers, close-out messages | — | — |
| Jira | Tickets, approvals, customer tickets, CCB state | Tickets, comments, status changes | — | — |
| SAIL | Status, failure logs | — | Label, re-label | — |
| Docs | Docs, comments | Drafts, comments | — | — |
| PagerDuty, flags, deploys | Alerts, on-call schedules, flag and deploy history | — | — | Declaring incidents |
| Bastion hosts | — | — | — | **Every command** |

**Rules for keeping the two systems apart:**

1. **One adapter per company system,** and one probe per system that reads all of our items at
   once. No story talks to a company system directly.
2. **Company stocks are observed, never owned.** The model treats them as a delay and a split,
   fitted from history. We don't model their internals.
3. **Iterate inside, cross once.** Every crossing back costs a company delay. The model puts the
   value of fewer boundary rounds at about 27% of cost and 18% of cycle time (story 1, 1.6b).
4. **One outbox.** Everything said as me goes through it. Kinds of messages earn autonomy by a run
   of unedited approvals.
5. **Influence is declared.** Pings, goodwill and adopted prevention change company flows. They
   are listed in `models/desk.couplings.json` and in each story's effects, not hidden in code.

**The couplings we can't avoid, said plainly:**
- Human reviewers and the CCB set most of our cycle time.
- SAIL decides when code lands.
- Production commands need me.
- Other teams adopt or reject our prevention proposals.

The design's job isn't to remove these. It's to cross them as few times as possible, with the best
possible work, and to measure each one.
