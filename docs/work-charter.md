# Work charter: what I'm expected to do

Status: started 2026-10-24. A living document. Supersedes
`docs/work-survey.md`; its automation ladder is kept in section 6.

Companion: `docs/proposals/orchestra-for-the-whole-job.md` (how Orchestra
is reorganised to carry this).

---

## 1. Premise

The goal is not software quality for its own sake. The goal is what it
always was in a company of people:

- **meet the expectations** of the people who judge my work;
- **keep and grow my professional identity**: someone whose judgement is
  trusted, who knows what's happening, and who makes things safer and
  faster.

So every responsibility is described by:

- **who judges it** (the audience);
- **what they see** (the signal);
- **what must be mine** (the part that only counts if I do it).

Automation is chosen by those three things. It takes over work that
produces signal without needing me. It prepares me for the work that does
need me. It never quietly takes over the part that makes up my identity.

## 2. The shape of the job

Almost every responsibility below is a mix of five verbs:

| Verb | What it means | Who should do it |
|---|---|---|
| **Watch** | Know what's happening across Slack, PagerDuty, Jira, GitHub, flags, secrets, outages. | Programs filter; agents summarise. |
| **Prepare** | Research, correlate, draft: docs, reviews, reports, slides, answers. | Agents. |
| **Decide** | Approve, reject, judge safety, choose. | Me. |
| **Perform** | Persuade, present, coach, command an incident, speak in a meeting. | Me, well prepared. |
| **Record** | Leave evidence of what was done, where the audience will see it. | Programs. |

The job is mostly watching and preparing, and that's where the hours go.
What I'm judged on is deciding and performing, and it only counts if
there's a record. So the system's first jobs are:

1. watch everything so I don't have to;
2. prepare me before I decide or perform;
3. record everything so the evidence builds itself.

## 3. Domains

Each expectation belongs to one domain. A domain becomes a team in
Orchestra (see the companion proposal).

### A. Delivery: my own code

| Expectation | Audience | Signal |
|---|---|---|
| Many commits on master | Manager, upper management | Merged PR count |
| Normal PR procedure; reviews from relevant people | Peers, manager | PRs with real reviewers |
| Get people to review my PRs | Peers | Time to first review |
| Max 4 days from starting a ticket to merged | Manager | Cycle time |
| About 4 hours per sprint point | Manager | Points per sprint (20) |

**Mine:** the design choices, and the relationships with reviewers.

### B. Code stewardship: reviewing others

| Expectation | Audience | Signal |
|---|---|---|
| Review others' PRs, with a measurable number of comments | Peers, manager | Reviews and comments per week |
| My reviews prevent production bugs; high standards | Peers, incident history | Bugs traced to PRs I approved |
| Search the whole codebase quickly; know which recent commits could relate to an issue | Peers in incidents | Speed and accuracy in threads |

**Mine:** the verdict and the tone. Comments must be ones I'd stand
behind. Padding the count with weak comments damages the identity it is
meant to build.

### C. Documents and change control

| Expectation | Audience | Signal |
|---|---|---|
| Problem Statement before Proposal | Team, leads | Docs exist, in order |
| Proposals with comments and reviews from others | Peers, other teams | Comment count, approvals |
| Design Documents, reviewed | Peers, architects | Approvals |
| FedRAMP CCB approves my designs | CCB | Approval record |
| File FedRAMP Jira tickets for change announcements; get CCB approval | CCB, compliance | Tickets filed on time, approved |

**Mine:** the thinking, and persuading reviewers and the CCB.

### D. Operational awareness

| Expectation | Audience | Signal |
|---|---|---|
| Respond to Slack quickly and correctly | Everyone | Response time, correctness |
| Track about six channels, mine and other teams', some mirroring Jira, some not | Team, manager | Knowing the state of things when asked |
| Be aware of PagerDuty alerts | On-call peers | — |
| Be aware of every outage as it happens | Manager, incident leads | Showing up informed |
| Know which flags were recently enabled in prod and whether they correlate with alerts | Incident leads | Fast correlation |
| Watch for expiring secrets | Team | No expiry outages |
| Predict outages | Management | Outages caught early |

**Mine:** knowing it, and saying the right thing at the right time.

### E. Incidents and on-call

| Expectation | Audience | Signal |
|---|---|---|
| Perform all on-call duties | Team | Pages handled |
| On each alert, comment on its Jira ticket about the alert's usefulness | SRE leads | Every alert ticket commented |
| Decide whether an alert is part of an outage; start incident management | Incident process | Timely incidents |
| Run the incident process correctly | Incident leads, compliance | Process followed |
| Find the right people (e.g. who's on call for the failing service) | Incident | Fast escalation |
| After outages: research, postmortem report, action items | Management | Report quality, timeliness |
| Create postmortem tickets, do their work, including proposals reviewed by owning teams | Other teams, management | Action items closed |

**Mine:** incident command, the decision to declare, and the conclusions
in the postmortem.

### F. Production safety governance

| Expectation | Audience | Signal |
|---|---|---|
| Review and approve feature flag ramps, researching each implementation and schedule | Teams ramping, management | Ramps reviewed, no ramp incidents |
| Make sure teams use feature flags to protect production | Teams, management | Adoption |
| Production readiness reviews for teams entering production | Teams, management | PRRs done |
| Track ongoing work not covered by PRRs | Management | Nothing surprising in prod |
| Plan Jenkins upgrades | Team | Upgrades done safely |
| Prepare and run the monthly disaster-recovery exercise | Compliance, management | Exercise done and recorded |

**Mine:** approvals and safety judgements. My name is on them.

### G. Customer support (FedRAMP)

| Expectation | Audience | Signal |
|---|---|---|
| Read and understand customer bug tickets in FedRAMP Jira | Customers, support | Tickets moved |
| Run commands people ask for, with judgement on whether to | Support, compliance | Safe, correct actions |
| Find automation potential in bug resolution | Management | Proposals |

**Mine:** whether a command runs. An agent never runs a command against
production or customer systems. It explains what the command does,
checks it against the ticket, and recommends; I decide and run it.

### H. Team and leadership

| Expectation | Audience | Signal |
|---|---|---|
| Track team members' projects; updates ready for managers | Manager | Updates on hand |
| Keep teammates' Jira current and PRs from going stale | Manager | Board hygiene |
| Coach and teach junior engineers | Juniors, manager | Their growth |
| Quarterly OKR plans | Management | OKRs |
| Long-term planning; ideas for the SRE summit (two-year plan) | Upper management | Ideas adopted |
| Small improvements: ideas, measured impact, done, re-measured, presented | Management | Before/after numbers |
| Monthly slide of my projects' useful work for the upper-management meeting | Upper management | The slide |
| Find automation potential in alert resolution, inter-team communication, and more | Management | Proposals |

**Mine:** the ideas, presenting, coaching, and the relationships.

## 4. Keeping track: responsibilities as conditions

The answer to "how do I keep track of all this" is to write each
responsibility as a **condition that is true or false right now**, and let
programs check it. The set of false conditions is my to-do list. It's
built for me, and every condition links to the evidence.

Examples, one or more per domain:

| Domain | Condition | Checked by |
|---|---|---|
| A | No PR of mine has waited more than 1 working day for a first review without a nudge drafted. | GitHub probe |
| A | No ticket I started more than 3 days ago is unmerged without a plan. | Jira + GitHub probe |
| A | Points landed this sprint are on pace for 20. | Jira probe |
| B | Every review requested of me is answered within 1 working day. | GitHub probe |
| B | This week's review comments ≥ my target. | GitHub probe |
| C | Every design in progress has a Problem Statement doc. | Doc index |
| C | Every change shipping to FedRAMP prod has a CCB ticket, approved before rollout. | Jira probe |
| D | Every message mentioning me, or in my channels' watch topics, is answered or triaged within N hours. | Slack probe |
| D | No secret I own expires within 30 days without a ticket. | Secrets probe |
| D | I've seen a digest of each tracked channel today. | Digest record |
| E | Every PagerDuty alert ticket from my rotation has a usefulness comment. | Jira + PagerDuty probe |
| E | Every postmortem action item assigned to me has an owner, a date, and progress this week. | Jira probe |
| F | Every pending flag ramp awaiting my approval has a research brief. | Flag system probe |
| F | This month's DR exercise is scheduled, prepared, and (after the date) recorded. | Calendar + doc probe |
| F | Jenkins is within N versions of current, or an upgrade plan exists. | Jenkins probe |
| G | Every FedRAMP customer ticket assigned to me has a response within its SLA. | Jira probe |
| H | Manager update for this week is drafted by Thursday. | Ledger |
| H | Monthly slide is drafted 3 days before the meeting. | Calendar + ledger |
| H | No teammate PR is stale more than 3 days without a nudge drafted. | GitHub probe |

The register lives in Orchestra (companion proposal, section 4). This
table is its seed.

## 5. The operating rhythm

| When | What arrives | Built from |
|---|---|---|
| **Morning brief** (before standup) | False conditions, ranked. Overnight alerts and outages. Channel digests. PRs awaiting me. My PRs stuck. Flag ramps pending. Expiring secrets. Today's meetings with prep notes. | Probes + one cheap summarising pass |
| **Live** | Pages, outages, direct mentions, CCB deadlines. Nothing else interrupts. | Programs; agents only to enrich |
| **End of day** | What I did today, with links, written to the ledger. Tomorrow's top three. | Ledger |
| **Weekly** | Manager update draft. Team projects' status. Review stats. Sprint pace. | Ledger + probes |
| **Sprint** | Points landed. Cycle times. Next sprint's slicing proposal. | Jira + ledger |
| **Monthly** | The upper-management slide draft. DR exercise. Small-improvement impact numbers. | Ledger + measurements |
| **Quarterly** | OKR draft from the ledger, open themes, and incidents. Summit ideas file. | Ledger + idea log |

The **ledger** is the piece that turns work into identity. Every PR,
review, doc, approval, incident, answer, and exercise is recorded with a
link and a line of impact. Manager updates, slides, OKRs, and performance
reviews are then summaries of the ledger, not reconstructions from memory.

## 6. The automation ladder

| Level | Name | Who does it |
|---|---|---|
| L0 | Manual | Me |
| L1 | Ask | An agent, when I ask the Supervisor |
| L2 | Standing | An agent on a schedule or an event |
| L3 | Scripted | A program; an agent only on cases it doesn't know |
| L4 | Program | A program only |

**Climb to L3** when the agent's transcripts repeat, or a script could
check what the agent is paid to notice.

**Stay at L2** for work that is mostly writing or judgement.

**Watching is L3–L4 from day one.** Six Slack channels and PagerDuty read
by an LLM all day would spend the whole budget. Programs filter (mentions,
my services, keywords, severity). An agent reads only what passes, in
batches, on a cheap model.

## 7. Never without me

These stay with me at every level, because they are my responsibility,
not just my identity:

- **Running anything** against production, customer, or FedRAMP systems.
- **Approving:** flag ramps, PRRs, PRs, CCB items.
- **Declaring an incident,** and incident command.
- **Speaking as me** in Slack, Jira, GitHub, or docs. At first, everything
  goes through an outbox I approve. Later, per channel and per kind, some
  replies may go straight out (e.g. the alert-usefulness comment).
- **The conclusions** of a postmortem or a review.

## 8. Compliance boundary (must settle first)

This is a FedRAMP environment. Before any agent reads Slack, Jira,
PagerDuty, customer tickets, or logs:

- Which AI models and providers are authorised for which data? The
  answer may be "only a FedRAMP-authorised deployment" or "nothing
  customer-related".
- Which data is customer data or controlled, and may not leave the
  boundary at all?
- May a bot or agent post as me? Under its own identity? Not at all?
- Which API tokens can I get (Slack, PagerDuty, Jira, flag system,
  secrets, Jenkins), and who approves them?

Every source in Orchestra will carry a data class. Each model will carry
the classes it may see. Orchestra refuses to send data to a model not
cleared for it. Until these answers exist, start with sources that are
plainly allowed (my own GitHub PRs, public-to-the-company docs) and
programs that don't call a model at all.

## 9. Order of attack

Ranked by hours saved, visibility to management, and risk (lowest first):

1. **Ledger + morning brief, read-only.** Cheap, helps every domain, and
   builds evidence from day one.
2. **My PR pipeline** (domain A): one change per ticket off master, PR
   template, review nudges drafted, SAIL watching. Directly drives commits
   on master and cycle time.
3. **Review pre-reader** (domain B): for each review requested of me, a
   brief on what the change does, its risk, likely bugs, and related recent
   commits. I write the comments.
4. **Alert companion** (domain E): for each PagerDuty alert, a drafted
   usefulness comment plus correlation with recent deploys, flag changes,
   and commits. Also who's on call for the services involved.
5. **Pure programs** (L4): secret expiry, Jenkins version, flag ramps
   pending, stale team PRs and tickets. No model cost.
6. **Docs pipeline** (domain C): Problem Statement → Proposal → Design →
   CCB, with drafts from my notes, reviewer tracking, and CCB ticket
   filing drafts.
7. **Reports** (domain H): weekly update, monthly slide, OKR drafts from
   the ledger.
8. **Governance helpers** (domain F): flag-ramp research briefs, PRR
   checklists and evidence, DR exercise prep.
9. **Incident and postmortem helper:** timeline from Slack, PagerDuty, and
   deploys; draft report and action items.
10. **Prediction and automation-finding:** last. These need the ledger and
    history to exist first.

## 10. To fill in

- [ ] Anything missing from section 3. (You said there are many more.)
- [ ] The six-plus Slack channels, and what "tracking" means in each.
- [ ] Review comment target per week, if there is one.
- [ ] Tools in use: flag system, secrets store, incident tool, docs
      (Google Docs?), Jenkins instances.
- [ ] Compliance answers (section 8).
- [ ] Which items are judged formally (perf review) and which only
      informally. This decides what the ledger must capture.
