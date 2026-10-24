# Proposal: Orchestra at work — initiatives, stacks, and external flows

Status: draft 2, 2026-10-24. Replaces draft 1, which assumed one PR per
ticket and one gate. Nothing built. Open questions are in section 15.

---

## 1. What we need

| # | Need |
|---|---|
| R1 | **Long-haul projects as chained PR stacks.** Each PR's branch is based on the branch of the PR before it, and each PR targets that parent branch. Not `ghstack` (one commit per PR); never that. |
| R2 | **Several projects at once**, each with its own stacks, moving independently. |
| R3 | **Ad hoc tasks**, usually one PR off `master`. |
| R4 | **A chosen starting ref.** Some work starts from a release branch. Some work is only a check or a test run, with no branch and no PR. |
| R5 | **Ports.** Work lands on `master` and is cherry-picked to a release branch through its own PR. There is also `arc port` and a `PORT` label automation, not yet understood. |
| R6 | **No merge to master by us.** The company's SAIL process lands PRs. Our "gate" is that every branch in a stack is fresh (rebased on its parent) and passes its tests. Every branch that changes for any reason is retested: its own edits, a parent update, or a rebase onto master. |
| R7 | **Tests beyond company CI.** Company PR checks don't cover everything. We add our own, including acceptance and performance tests that we don't want in PRs. Each project or task can say which tests it needs. |
| R8 | **Reviewable PR sizes.** One ticket may become several PRs in a stack. |
| R9 | **Clear boundaries with company systems.** For each company system (GitHub, SAIL, CI, Jira, ports): what interface we use, and which flows are theirs rather than ours. |
| R10 | **Cost.** $190/week, shared with side work. Code is better than AI wherever code can do the job. Scripts that call an agent only for cases they don't know are better still. |
| R11 | **Same agent structure.** Keep the Supervisor and Coordinator. The Pipeline Manager becomes the owner of many concurrent stacks: freshness, SAIL, and integration problems. |

## 2. The ideal, in one paragraph

Orchestra owns **intent and the shape of the branch graph**; the company
owns **review and landing**. Orchestra plans work into small changes and
arranges them into stacks. Workers write the code. A programmatic
**reconciler** keeps every branch rebased, pushed, and described. A shared
**verifier** proves every branch at the depth its position needs, and never
reruns a test whose answer it already knows. External services are watched
by probes, not agents. Agents are spent only on what needs judgement:
writing code, answering reviewers, resolving conflicts, and failures no
script recognises. The personal-project Orchestra of today becomes one
configuration of this design, where Orchestra itself is the reviewer and
the lander.

---

## 3. The model: splitting the ticket

Today a ticket is four things at once: intent, branch, review, and merge.
At work those come apart. A ticket may produce three PRs, or none.

| Entity | What it is | Today's equivalent |
|---|---|---|
| **Initiative** | A body of work with a goal: a long-haul project, or the standing "ad hoc" initiative. Has a base ref (default `master`), a Jira epic, a design doc, test policy, a priority, and a budget share. | Milestone, roughly |
| **Ticket** | Intent and acceptance, worked by one worker session. Kinds: `change` (writes code), `check` (runs or investigates, no code), `port` (brings landed changes to another ref). Carries `jira_key` and `points`. | Ticket |
| **Change** | One branch and one PR. The unit of review, verification, and landing. Has a parent: a base ref or another change. Sized under the line limit. | Ticket's branch |
| **Stack** | The changes that share a root on a base ref, linked by their parents. Usually a line; stored as a tree so a branch-off is possible, limited by policy. | Merge batch, roughly |
| **Verification** | One suite's result for one tree hash in one environment. Content-addressed, so it stays valid however the branch got there. | Gate run results |

```
Initiative "billing-v2"   base: master   epic: BILL-100
  Ticket BILL-101 (3 pts) ──► Change c1 ─┐
                          ──► Change c2 ─┤  Stack S1 (rooted on master)
  Ticket BILL-102 (2 pts) ──► Change c3 ─┘    master ← c1 ← c2 ← c3
  Ticket BILL-103 (1 pt)  ──► Change c4      Stack S2: master ← c4

Initiative "ad hoc"       base: master
  Ticket OPS-7 (check, ref release/24.10) ──► (no change; report)
  Ticket OPS-8 (port c1 → release/24.10)  ──► Change p1   release/24.10 ← p1
```

A ticket is `DONE` when all its changes have landed and any required ports
have landed. A `check` ticket is `DONE` when its report is filed.

---

## 4. Who owns which flow

| Flow | Owner | Orchestra's part |
|---|---|---|
| Planning, slicing, ordering | Orchestra (Supervisor, Coordinator) | All of it. |
| Writing code | Orchestra (worker) | All of it. |
| Pre-review | Orchestra (reviewer agent + checks) | Catch what humans would reject, before they see it. |
| Branch graph: rebase, push, retarget, PR text | Orchestra (reconciler, code only) | All of it. |
| Verification beyond CI | Orchestra (verifier, code only) | Runs suites locally, caches results, reports into the PR. |
| PR checks (CI) | Company | Read results; rerun where allowed; never duplicate. |
| Human review | Company (people) | Request reviewers, turn feedback into worker turns, post replies. |
| Landing (SAIL) | Company | Add the label when ready; watch; retry known failures; report the rest. |
| Ports (`arc port`, `PORT` label) | Company automation, if it fits | Trigger it, or cherry-pick and open the PR ourselves. Open question. |
| Tracking (Jira) | Company | Link keys; optionally mirror status. |
| Sprint accounting | You | Orchestra reports points landed per week. |

---

## 5. Adapters for company systems

Each company system sits behind an interface, with a fake in `tests/e2e/`
that speaks its protocol, as harnesses do now. The core never knows which
implementation it's talking to.

| Interface | Operations | Work implementation | Personal implementation |
|---|---|---|---|
| `CodeHost` | push branch (force-with-lease), open/update PR (base, title, body, draft/ready), request reviewers, read reviews + threads + merged state + merge commit, post reply | GitHub via `gh` | Local git, no PRs |
| `Landing` | request landing, observe status, fetch failure log, retry | `SAIL` label | Orchestra's batch gate (section 7 of SPEC.md) |
| `CI` | check results for a SHA, rerun | GitHub checks | None |
| `Tracker` | read issue, link, transition status | Jira | Orchestra's own store |
| `Porter` | port a landed commit to a ref | Cherry-pick + PR, or the `PORT` label | None |
| `Runner` | run a suite at a tree, return a result | Local processes | Same |

One GraphQL probe per interval reads every open Orchestra PR: reviews,
threads, labels, checks, base, and merged state. It turns differences
into events. No agent polls.

---

## 6. The reconciler

The branch graph is **desired state**: each change has a parent and a head
commit Orchestra has accepted. The reconciler compares that with reality
(local branches, remote branches, PRs) and performs mechanical actions until
they match. It is code, idempotent, and safe to rerun after a crash.

**Each change carries conditions,** recomputed every pass:

- `fresh`: the change's branch contains its parent's current head.
- `pushed`: the remote branch equals the local head.
- `described`: the PR exists, with the right base, title, and body.
- `verified`: every suite required at its position passed for its tree.
- `sized`: under the line limit.
- `approved`: by the required humans, on the current head.
- `conflict_free`: predicted against its parent and against `master`.

**Actions:**

- **Cascade.** When a change's head moves, rebase each child onto it, in
  order down the stack. Orchestra records every parent head it rebased
  onto, so the next rebase is always `git rebase --onto <new> <old>
  <child>`. Commit messages never have to be guessed.
- **Restack after landing.** When the bottom PR lands, read its merge
  commit from the code host. Rebase the next change onto it, retarget its
  PR to `master`, and push.
- **Refresh from master** happens on a policy, not on every master commit:
  - before the bottom change is put up for landing;
  - when `git merge-tree` (which needs no checkout) predicts a conflict, so
    it's resolved while small;
  - and on a maximum-age timer (default daily).
- **Debounce.** Wait for a quiet period after a burst of changes before
  cascading.
- **Conflicts.**
  - `git rerere` is on in every worktree, so a conflict resolved once is
    resolved automatically on every later rebase.
  - What remains goes to the change's worker session, with the conflict
    and both sides. Like gate conflicts today, it isn't a review round.
- **Approvals.** If the repository dismisses stale approvals on push,
  every rebase of an approved PR costs a human re-review. The reconciler
  then avoids rebasing approved changes unless landing requires it.
  Section 15 asks whether the repo does this.

---

## 7. Verification: a gate per branch

Every changed branch is tested. That's a lot of testing for one machine, so
the cost is cut four ways without skipping any branch.

1. **Results are keyed by tree hash.** A rebase that produces the same tree
   reruns nothing. This happens often: when a parent lands with nothing
   else on master in between, its child's restacked tree is identical.
2. **Company CI counts.** A suite marked `where = "ci:<check>"` is read from
   GitHub checks, not run locally. Pushes create draft PRs early, so CI
   tests a change while the internal reviewer reads it.
3. **Depth follows position.** Only the bottom change of a stack can land
   next. Only the tip contains the whole stack. So:
   - **every change:** company CI plus the fast local tier;
   - **bottom, before landing:** the full local tiers, including acceptance
     and performance;
   - **tip:** acceptance, as the integration test of the whole stack;
   - **nightly:** anything slow, per initiative.
4. **One shared queue,** ordered by closeness to landing: bottom before
   SAIL, then changes a human is waiting on, then tips, then the rest.
   Concurrency is a config value.

Acceptance and performance tests never go into the PR. Performance results
are compared with the same suite at the stack's root on master, and only
regressions past a threshold fail.

A failure goes back to the change's worker with the log. If the change
itself didn't move but its parent did, the note says so. That tells the
worker the cause is probably in the parent's change, not its own.

---

## 8. Change lifecycle

States cover review and landing. Conditions (section 6) cover everything
mechanical, so the state table stays small.

| State | Waiting for | Next |
|---|---|---|
| `DRAFTING` | Its worker (active: a live session owns it) | `PRE_REVIEW` |
| `PRE_REVIEW` | Internal reviewer (active) | `DRAFTING` (rejected), `IN_REVIEW` |
| `IN_REVIEW` | Humans. PR is ready for review. | `DRAFTING` (changes requested), `READY_TO_LAND` |
| `READY_TO_LAND` | Its turn: bottom of the stack, and fresh, verified, and approved | `LANDING` |
| `LANDING` | SAIL | `LANDED`, `READY_TO_LAND` (retryable failure), `DRAFTING` (code failure), `STUCK` (retries exhausted) |
| `LANDED` | (terminal) | |
| `STUCK` | Pipeline Manager | any earlier state |
| `ABANDONED` | (terminal) | |

- `IN_REVIEW`, `READY_TO_LAND`, and `LANDING` are waiting states, because
  no live process owns them. That keeps the no-zombies rule.
- Changes requested gathers every unresolved thread once a review is
  submitted, so the worker gets one turn per review, not one per comment.
- Children can be reviewed in parallel with their parents: each PR's base
  is its parent branch, so its diff is only its own work.
- Adding the `SAIL` label can be automatic, or wait for your click, per
  initiative.

---

## 9. Agents

| Agent | Role at work |
|---|---|
| **Supervisor** | Unchanged: the only agent you talk to. It creates initiatives with you (goal, base ref, Jira epic, test policy, priority) and keeps each initiative's design doc. A long-haul initiative opens with a design-doc change. |
| **Coordinator** | Plans each initiative into tickets and **slices tickets into planned changes**, each with a scope and a line budget. Decides stack shape: a separate stack where work is independent, a chain only where it isn't. Keeps unreviewed depth under the cap. Creates check and port tickets. Rebalances worker slots across initiatives. |
| **Pipeline Manager** | Owns every stack's health, not a merge queue. Woken only for exceptions the reconciler and verifier can't handle: SAIL failures with no known pattern, CI infrastructure trouble, a stack stuck too long, repeated conflicts. It fixes the case, then teaches the script (adds a SAIL pattern, a flaky-test rule, a tool in its team space), so the next one is code. |
| **Worker** | One session per ticket, building its planned changes in order, each on its own branch on top of the last. Moves on to the next change while earlier ones are in review. Handles review feedback, verification failures, and conflicts for its changes. |
| **Reviewer** | A pre-reviewer per change, on a cheap model. Its measure is fewer human review rounds. Checks the change against its slice, the size limit, the module README rule, and the PR text. |

Nothing an agent does touches a remote. Agents report; the reconciler acts.

---

## 10. Spending worker labour well

Worker turns are the main cost and the main output. The design keeps them
on work only a worker can do:

| Worker does | Code does |
|---|---|
| Write a planned change | Branch, rebase, push, retarget, PR body |
| Address a submitted review | Gather threads, post replies, re-request review |
| Fix a test failure in its change | Run, cache, and route tests; read CI |
| Resolve a new conflict | Predict conflicts; replay known resolutions (`rerere`) |
| One-line revert note for risky paths | Everything else in the PR template |

- **Pipelining.** The worker starts the next change while the previous one
  is in review. That's the point of stacks.
- **WIP caps.** A cap on unreviewed depth per stack (default 3), because a
  comment on change 1 can force rework in changes 2–5. A cap on open
  changes per initiative.
- **Planned slicing.** The Coordinator slices tickets before work starts.
  That's cheaper than splitting a finished 2,000-line branch.
- **Context reuse.** One session per ticket, resumed for every round, as
  today.
- **Budget.** Usage is recorded per turn, change, ticket, initiative, and
  week. A brake stops new worker turns when the week's limit is reached;
  turns already running finish. Each role gets its own model.
- **Metrics** that tell us if this works:
  - agent dollars per landed change and per point;
  - human review rounds per change;
  - time spent in each state;
  - tests run versus cache hits;
  - agent wake-ups the scripts could have handled.

---

## 11. Ad hoc work, checks, release branches, ports

- **Ad hoc:** a ticket in the standing "ad hoc" initiative. It's usually
  one change rooted on `master`, at a priority above long-haul work.
- **Check:** a ticket with `kind = check` and a ref. It runs in a detached
  worktree at that ref, with no branch and no PR. It runs the named suites
  or investigates as asked, and files a report as a note, plus a Jira
  comment if linked. The worktree is deleted when it's done.
- **Port:** a ticket with `kind = port`, a source change (once landed), and
  a target ref.
  - The porter cherry-picks the landed commit onto a new branch from the
    target, opens a PR against it, and verifies it with the target ref's
    suites.
  - A conflict goes to a worker.
  - If `arc port` or the `PORT` label does this already, the porter
    triggers it and watches instead.
- A ticket can say which ref its changes root on. Release branches only
  ever receive ports, which matches the company rule.

---

## 12. Configuration sketch

```toml
[codehost]
kind = "github"
remote = "origin"
pr_template = ".orchestra/pr_template.md"
draft_until_reviewed = true          # draft PR on first push; ready after pre-review

[landing]
kind = "label"
label = "SAIL"
auto = false                         # true: add the label when READY_TO_LAND
retries = 3
backoff = "30m"

[tracker]
kind = "jira"
mode = "link"                        # link | mirror

[limits]
change_lines = 800                   # excluding paths in limits.exclude
exclude = ["**/tests/**", "**/*.md", "**/generated/**"]
unreviewed_depth = 3
refresh_max_age = "24h"

[runner]
concurrency = 2

[[verify]]
name = "pr-checks"
where = "ci:build-and-test"          # read from GitHub checks
when = "every"

[[verify]]
name = "unit-fast"
where = "local"
command = "..."
when = "every"

[[verify]]
name = "acceptance"
where = "local"
command = "..."
when = ["bottom", "tip"]

[[verify]]
name = "perf"
where = "local"
command = "..."
when = "bottom"
baseline = "root"                    # compare against the stack's root on master
threshold = "5%"
```

Initiatives may override `[[verify]]`, `limits`, `landing.auto`, and the
base ref. Personal projects keep today's `[gate]`, which becomes
`[landing] kind = "orchestra"`.

---

## 13. Spec and invariant changes

To be made in the commit that implements them, as AGENTS.md requires:

- **Invariant 3.** One worktree per change, not per ticket. Check tickets
  get a detached worktree for their run.
- **Invariant 4.** Pushing, opening PRs, rebasing, and labelling are done
  only by the reconciler and the landing adapter, never by an agent. With
  an external `Landing`, Orchestra never writes the base branch at all.
- **Invariant 7.** Human PR reviews reach workers as review input, like
  gate feedback. They are not humans prompting agents.
- **Invariant 2.** External waits (`IN_REVIEW`, `READY_TO_LAND`,
  `LANDING`) are waiting states.
- **SPEC.md:**
  - section 2: initiatives, changes, verifications, and ticket kinds;
  - section 3: ticket states derived from their changes;
  - section 7: landing adapters, with today's gate as one;
  - section 8: adapters;
  - section 9: configuration.
- **Non-goals stay:** one repository per project, no production deploys.

---

## 14. Build order

Each step is usable on its own at work.

1. **Model and metering.** Changes and initiatives in the store; usage
   recording and the budget brake.
2. **One change per ticket, off master, with GitHub and SAIL.** Covers ad
   hoc work at once. Add the `CodeHost`, `Landing`, and `CI` adapters with
   fakes, the PR probe, the PR template, and replies in draft mode.
3. **The verifier.** Tree-hash cache, CI-as-suite, tiers by position, the
   shared queue.
4. **Stacks.** Planned slicing, the reconciler's cascade, restack after
   landing, refresh policy, `rerere`, WIP caps.
5. **Checks and ports.**
6. **Several initiatives at once:** fair scheduling and budget shares.
   (Steps 2–5 already work with one initiative.)
7. **SAIL triage teaching loop** and the Jira mirror, as exceptions show
   where they pay.

---

## 15. Open questions

Answers to these change the design.

1. **Does SAIL** require the PR to be up to date with master? Does it
   squash? How does it report failure: a check, a comment, a label
   removed?
2. **Does the repo dismiss stale approvals on push?** If yes, every rebase
   of an approved PR costs a human re-review, and refresh policy must avoid
   it.
3. **Does SAIL accept a PR whose base is another branch,** or must the
   bottom be retargeted to master first? (Assumed: retargeted first.)
4. **What do `arc port` and the `PORT` label actually do?**
5. **Are draft PRs acceptable** for running CI before human review?
6. **Which company checks run on every PR,** and how long do they take?
   This decides how much local testing is needed.
7. **Should replies to reviewers ever post on their own,** or always wait
   for your approval?
8. **How is Claude billed at work?** API spend or a subscription with
   limits? This changes what the budget measures.
9. **Does Jira status need to move** for sprint reporting, or is the key in
   the PR enough?
10. **One initiative per Jira epic,** or can one initiative span several?
