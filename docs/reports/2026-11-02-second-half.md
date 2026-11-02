# The second half, 2026-11-02: report

The unattended run of [GOAL-2026-11-02-second-half.md](../roadmap/GOAL-2026-11-02-second-half.md),
run by [COORDINATOR.md](../roadmap/COORDINATOR.md), with product decisions taken by the owner proxy
([OWNER-PROXY.md](../roadmap/OWNER-PROXY.md)). Its first timed log line is 2026-11-01T17:08Z. This
draft was written at 2026-11-02T00:27Z and brought up to date with the log through 04:02Z (T6).
The goal's progress log is the source of truth. Where this draft and the log disagree, the log wins.

In short: the live delivery example ran the owner's day on the real SCRUM board and the private
repository four times (L1, T2-prep, T2, T2b), every outside write in the approved scope. The
Supervisor passed the design scenario on the live example on Haiku (L3). The Monday walkthrough
went from 7 pass, 2 misleading, 6 fail (T2) to 12, 2 and 2 (T2b, after T4). Its failures were
mostly the Supervisor's answers and the pages' account of who must act, not the delivery. T6 fixed
what T2b found and was on origin by 04:02Z. The release gate's verifier found agents, workflows and
bridges ready, and the core's fixes small: P1 was already fixed, and P2 and P4 were fixed in T6.
After eight more fix rounds, the ninth walkthrough (T2i) passed all 16 steps, on Haiku over bash
from the example's own start (Addendum 5). Two standing public demos now run: the delivery example
on the real SCRUM board, and the Slack queues example on fakes (Addendum 4).

## 1. Questions for the owner

Each is answerable in one sentence. Until you answer, the run uses the default in brackets.

The addenda raised these; the first two are answered.

- Answered: how much traffic may the SCRUM board take from the standing live demo? "the sprint
  board itself is low traffic" (Addendum 3).
- Answered: will you give a Slack bot token? "we will get a slack bot token, we wont post
  initially" (Addendum 3; question 9 below).
- Should the built-in worktree resource kind move out of the Workflows plugin's own code, so the
  item system carries no code-work concept? [it stays; see Addenda 2 and 3]
- Which stack provider first: GitHub PR stacks or git-spice? [none chosen]
- Where do the private company pull request templates live: the private overlay, the state
  directory, or `~/work-desk`? [none chosen]
- May a provider push an item's own branches from a program step, or does every push go through
  the Outbox? [every push through the Outbox]

### The goal's own questions

1. Which Jira Data Center project and board, and which GitHub repository, should Orchestra watch
   at work first? [none; the live example only]
2. Is your day "ticket assigned, branch, pull request, reviews, SAIL label, SAIL result, Slack
   thread told", and which step is wrong or missing? [as written]
3. Which page do you open first in the morning? [the Dashboard]
4. What are the three questions you will ask the Supervisor most, and what must each answer
   contain? [what is stuck and why; what needs me; what changed since yesterday]
5. Which writes to outside systems may Orchestra make at work, and which need your approval each
   time? [all need approval; none outside the live example]
6. Which distribution should QUICKSTART present to a colleague? [the core from GitHub with the
   plugins as extras]
7. Does the RabbitMQ test rig get its own repository? [no; it stays where it is]
8. D19: may a polling relay be a Workflows program, or does it stay a machine that publishes as
   the actors? [stays as is]
9. Will you give the Slack app's client id and secret for token refresh, or a bot token that does
   not rotate? [neither; Slack is disabled on expiry]
10. Which time zone and working hours do guards and schedules use? [ask in the chat; none guessed]
11. Do you confirm defaults D22 to D40 as a set, or which do you want to revisit? [standing]

### Escalated by the proxy (R1 E, R2 X, T3 Y)

Pages and names:
- E1. Should Agents stay in the navbar now that Machines shows the agents? Tickets leaves with the tasking plugin (your Q5 words). [Agents stays]
- E2. Should Core stay in the navbar, plumbing opened only when something breaks? [stays]
- X2. Would you object to the Outbox page, where drafts wait for your approval? [kept]
- E9. The hidden stock of items whose pull request waits for CI: what do you call it? [named by its neighbours]
- Y6. Items passing SAIL (sail_check → close_ticket): what do you call that quantity? [named from the step]
- Y4. The stock "agents working (supervisor)" counts the Supervisor's own turns: keep it, and what do you call it? [kept, marked by construction]
- E20. Rename `[[machines]]` to `[[processes]]` and merge the two kind vocabularies (program/agent/person/service vs universal/programmatic)? [unchanged]
- E24. Should the Items list mark rows moved since your last visit? [not built]

Who acts, and what may be sent without you:
- E3. Should the floor publish as itself (a dispatcher's name) rather than as `supervisor/dispatch`? Machines credited the Supervisor with 13 offers and 11 drafts on Monday. [stays; waits on you]
- E4/X7/X8/Y8. May a machine at work, without your approval each time, add or remove SAIL labels, move a ticket to Done, post a Slack nudge, approve a teammate's pull request, or run a fix step on production? [every one an Outbox draft; no approve sender exists]
- Y1. Would you object to the SAIL label, the Jira transition and the created ticket being sent with no approval on the test repository and board, which your "approval-always" decision does not allow? [as built, test scope only; `--scope board` makes each wait]
- Y3. May the Supervisor wake unasked on `attention.needed` and write to you, and start the Review Nudger on that attention without your words? [it writes; it starts nothing]
- Y9. Is the Outbox an actor (a machine on Machines, publishing as `outbox`) or your hand (publishing as your person id)? [unchanged, `[outbox] owner` set]
- Y10. Should the guard be the only judge of "waited too long", with the nudger's own 30-minute scan gone? [both stay]
- Y2. Would you object to `confirm` refusing a machine until its prediction is recorded? [no refusal]
- X3. Should the Supervisor start an item itself (`request_work`) rather than Supervisor → Coordinator → tickets? [as built: it starts items]
- X4/E16. Without tasking, should the Coordinator hand code work through a Workflows item, or should the agents' ticket-built team (roles, teams, the ticket path) go? [the gap stays documented]
- E15. Is the Supervisor part of Orchestra (rule 9) or a plugin's machine whose name no one else may use? [rule 9 as written]
- X5. A stale review at work: told to you on the Dashboard, to the reviewer, or in the chat? [Dashboard]
- E13. Who is "the requester" to tell in Slack: the Jira reporter by DM, or one channel? [no post until a bot token exists]
- E14. During a PagerDuty incident, should deliveries pause, or only SAIL triage consult it? [only triage]

The model:
- Y5. Does "SAILED per day ×1.2" mean more deliveries passing SAIL, or reviews waiting less? [recorded as said, on the sail_check → close_ticket flow]
- Y7. At work, does SAIL publish a check-result event, or only labels on the pull request? [the fake keeps `sail.check.completed`]
- X1. Would you object to a 0/1 "busy" level being left out as another stock's capacity, shown in that stock's drawer? [kept]
- X6. A count of agents busy on tickets in review: IN_REVIEW's capacity, or a stock of its own? [a stock]
- E10. Should a definition declare its piles and moves in the intended layer, so a mis-bound pile shows as a mismatch? [no]

At work:
- Y11. Would the MCP block stop Orchestra's local MCP server, and is `tools_via = "bash"` allowed instead? [bash; the walkthrough runs on it]
- E6/Y12. May a `gh` token or a Jira PAT sit in a mode-600 file, or must it come from a keychain or vault? [a mode-600 file, by reference; credentials stripped from agent sessions]
- Y13. May private repositories from a personal GitHub account be cloned onto the laptop, or must they be mirrored to GHE? [cloned]
- Y14. May the Outbox write labels, comments and transitions as you, or only through a service account? [as you]
- E7. Would managed Claude Code settings disable `--dangerously-skip-permissions`, and what is allowed instead? [unchanged]
- E8. Are github.com, PyPI and the Claude API reachable through the proxy, with a corporate CA injected? [documented in INTEGRATING]
- X9. Does Claude Code reach the model through api.anthropic.com, or Bedrock or Vertex? [api.anthropic.com]
- X10. May plugin pages fetch scripts from public CDNs? [no; vendored]
- E11. May ticket summaries and pull request URLs ride the bus, or ids only? [as today]
- E12. May GitHub and Jira push webhooks to Orchestra, or must it poll (5 minutes a hop)? [poll]
- E5. Should `orchestra-workflows` become public, since the install line fails for anyone else? [private]

Repository housekeeping (yours to decide; nothing changed):
- E17 (desk and outbox in the install line: stay), E18 (the events endpoint's second model API: stays), E19 (`Plugin.machines` placeholders: stay), E21 (the 74 unused SD Lab strategies: kept), E22 (the test-report instrument in the core: kept), E23 (`mockups/`, 14 MB: kept), X11 (rule 2's exceptions into SPEC: unchanged), 7 (the RabbitMQ rig's repository: stays).

## 2. What works, with the evidence

**The delivery on the real systems.** L1 (17:55Z) took three "[orchestra live test]" tickets on
SCRUM from assignment to a real pull request in `danroblewis/orchestra-live-delivery`, GitHub
Actions CI, a stand-in review, the SAIL label, the example's fake SAIL, a merge and the ticket
Done. One ticket (SCRUM-7) was rejected, triaged back, reworked and SAILED. No AI was spent.
T2-prep (22:22Z) ran it again with every write through the Outbox: SCRUM-14 to 16, pull requests
#12 to #14, one held review with the 30-minute guard firing once, one forced rejection triaged
`local` and reworked, 10 Outbox sends by configuration, no Slack post. T2 ran it a third time
(SCRUM-17 to 19, pull requests #15 to #17, all merged and Done, branches deleted).

**The Supervisor on the live example.** L2 (18:44Z) fixed the Haiku failures the first run left;
its second live run passed every turn ($0.12; both runs $0.25). L3 (20:10Z) passed all three
design turns on `delivery_live` in three Haiku runs ($0.21): a stock measured by the existing pile
series, the Review Nudger declared, scheduled and confirmed with a prediction, and "what needs me"
answered with the real ticket keys and pull request numbers. Its weakness: discovery found no
model in 20 minutes of two tickets, so the prediction's flow is an event type.

**The walkthrough's passing steps** are in section 3. In T2 the delivery steps (2 to 6, 12, 13)
passed on the real systems, including work started from the chat: `request_work` opened SCRUM-19
through the Outbox, then pull request #17, merged and Done.

**Model acceptance (S4).** At 1 s sampling, UC-2 scored 9/10 (was 8) on core `fa4e8acd`, and UC-3
9/10 (was 6) on `281922c0`. U1 scored UC-1 8/10 on `e9472164` with a snapshot whose replay
reproduces the model exactly (U4). Every remaining miss was named as data:

| case | score | the miss | why (the modeller's verdict) |
|---|---|---|---|
| UC-1 | 8/10 | the rating; an extra stock `bakery_chef_busy` | the bakery publishes its own demand formula, which `placed` reads (R² 0.87); the extra stock is a 0/1 flag, now a capacity of one (U5) |
| UC-2 | 9/10 | IN_REVIEW | its series was never non-zero in 2,115 one-second samples: the reviewer passes tickets in under a second |
| UC-3 | 9/10 | the coordinator's and Supervisor's levels; the attention loop | scripted turns last under a second; they need real agents' turns of seconds |

U5 (merged 19:32Z, refuted once, fixed) makes a 0/1 or 0..k level another stock's capacity: UC-1's
replay goes from 7 to 6 stocks, UC-2 and UC-3 are unchanged, and UC-1's expectation now accepts
the rating through the demand gauge (D15). A re-score of UC-1 after U5 is not recorded. The
passage fixes (18:30Z) and the R2 discovery rows (21:14Z) replayed identically on every snapshot.
No case is at 10/10, so done criterion 3 rests on the misses being named as data.

**Vocabulary (S3, 19:05Z).** V1, V2, V4, V7 and V8 are words the examples use; V3, V5, V6, V9 and
V10 are rulings in the plugin's SPEC §7.3.

## 3. The walkthrough, step by step

T2 ran 22:26Z to 00:02Z on the real Supervisor (Haiku, $0.37, 11 invocations), from a fresh
state. Evidence in the scratchpad under `reviews/T2/`: `run.md`, `answers.md`, `notes.md`,
`events.jsonl` (redacted), `raw/`, and 62 screenshots in `shots/`. The script is
[WALKTHROUGH-2026-11-02.md](../roadmap/WALKTHROUGH-2026-11-02.md). "T4 changes" lists the T3
judge's rows for each step; the last column is T2b's verdict on T4's code.

| # | step | T2 | what the proxy found | what T4 changes | T2b |
|---|---|---|---|---|---|
| 1 | First look, "What needs me?" | fail | Slack's disabled reason and the fakes are announced but not on the cards; the answer is silent on Slack; a task-system tool times out in every answer | core cards print announced notes; agents `list_machines` with notes; task-system parts gated on tasking; the walk's venv without tasking | pass |
| 2 | Two tickets assigned | pass | rows show no ticket summary | the title before the fields | pass |
| 3 | Branch and pull request | pass | none | none | pass |
| 4 | CI | pass | none | none | pass |
| 5 | Stand-in review | pass | none | none | pass |
| 6 | SAIL through the Outbox | pass, notes | the Outbox says "auto", not "approved by configuration"; approvals not under the owner's person id | Outbox wording and trail; `[outbox] owner` written | pass |
| 7 | Rejection, triage, rework | pass, misleading | every drawer time "Invalid Date"; reworked 0; label names missing | Invalid Date fixed already (b154435); reworked counts any return; labels on the timeline | pass |
| 8 | "What is stuck, and why?" | pass, misleading | the held review called a workflow bug; A's rejection left out | each wait names its exits (`for`); `read_events` by prefix and `since` | misleading |
| 9 | Stale review reaches the owner | fail | the Dashboard names GitHub as who must act; the Supervisor woke and told the owner to approve a PR GitHub refuses | one answer to "who must act"; wait exits; the guard key out of the wake text | pass |
| 10 | Review Nudger and ×1.2 | fail | nothing declared; "no metrics collected" with 152 series; the owner asked to restate | the core's no-model reason through `read_model`; the owner's earlier ask carried forward; the expectation recorded as waiting | fail |
| 11 | Nudge on B | fail | "which is B's?": the script's label | the reminder prompt; the script now names the PR (9fbcce41) | pass |
| 12 | SAILED, merged, Done | pass on Jira/GitHub | closed items under "no workflow", no outcome; Slack's reason not on its card | the floor publishes `item.closed`; cards print notes | pass |
| 13 | Delivery from the chat | pass | the closed item still holds a live review position | `item.closed` | pass |
| 14 | An incident | fail | the incident not named; merged tickets listed as waiting | `pagerduty.` prefix reads and a prompt line; state from this turn's tools only | misleading |
| 15 | "Before I go?" | pass | none | none | pass |
| 16 | "What changed since yesterday?" | fail | the rejection told wrongly; the 11 Outbox sends missing; UTC | `since`, oldest first; an Outbox read; times in the pages' zone; envelope times normalised | fail |

### What T4 landed

| repository | merged | what the log says landed |
|---|---|---|
| outbox | `a53a70a` | "approved by configuration"; the trail drafted · approved · sent with times; `Orchestra.when` everywhere |
| core | `3ae3e39f` | `sd/no_model.py`: the no-model read gives a text and a reason; announced notes on cards and dialogs; no machine percentage on a too-few flow; envelope time always UTC `…Z`; QUICKSTART names `delivery_live` |
| core | `12be615d` | the stall rule, after a refuter round: due = min(history average, fitted rate); no "resumed" while silent. UC-1 replay: 7 stalls and 5 resumes before, 2 and 2 after |
| agents | `ac51fb3` | 16 rows, relocked to core `3ae3e39f` |
| agents | `ff0a590` (row 9), `c77915a` (relock) | the wake text without the guard key; `list_items` and `explain_item` show `entered_on` and `ends_on` from the wait's `for`; `item.closed` in the contract copy; relocked to core `12be615d` and workflows `35b2b9c`, where `declare_workflow` gained the plugin's new `about` key (the one drift the relock found) |
| workflows | `35b2b9c`, relock `0166e5d` | `item.closed`; one who-must-act; `for` and `entered_on`; reworked; example settings including Data Center; `[outbox] owner`; `--supervisor`; notes on the card; title first; the timeline in words; `every` with `at`/`tz`; `about`; first free port; the login link in a mode-600 file; README credentials and proxy; the fake bridges exit with their parent |

The coordinator's T3 rows went into the script at 00:24Z (9fbcce41).

### T2b, the walkthrough on T4's code

T2b ran 01:59Z to 03:38Z on core `12be615d`, agents `c77915a`, workflows `0166e5d`, bridges
`14119cf` and outbox `a53a70a`, with `orchestra-tasking` not installed and tools over bash.
Evidence in the scratchpad under `reviews/T2b/`. It passed 12 steps (1 to 7, 9, 11 to 13, 15).
Two misled (8, 14) and two failed (10, 16). SCRUM-20 to 22 are Done and pull requests #18 to #20
merged.

The example's `--supervisor` starts, but it writes a role without `work` and has no option to
add it, so `request_work` (steps 11 and 13) would be missing. The run used the agents' launcher
`tests/live/delivery_live_run.py --via bash` instead.

What was still wrong:
- **8, misleading.** The Supervisor called `reviewer_stand_in` "quiet, needs restarting" while
  the harness held the review.
- **14, misleading.** It named the incident and called it fake. It also said delivery was not
  affected, though PSVC003 is SAIL's service and an item waited at SAIL.
- **10, fail.** The Review Nudger was declared and confirmed and ×1.2 published, all in one turn.
  But SAIL check results were left out of what the nudger listens for, and the Supervisor said it
  "runs at 09:00 PST" when it runs every 24 hours.
- **16, fail.** The rejection and the triage were left out. The Supervisor said "no stocks yet"
  while discovery had three.

New breaks it found:
- `/api/dynamics/model` returns 500 once a model exists, because an `inf` in the model is not
  JSON. Dynamics then shows "server is not answering", and step 16's model answer was wrong.
- `logs/web.log` prints the login token in clear.
- A `coordinator` placeholder card stays on Machines when tasking is not installed.

### T6, the fixes for T2b's findings

All merged and pushed by 04:02Z: core `fcea86e6`, agents `4cc1af6`, workflows `fb2b107`.

| repository | commits | what the log says landed |
|---|---|---|
| core | `1dfd2355` (T6-words, pushed as `f4a753f0`) | the gate's P2: plugin words out of core comments and one user-facing string |
| core | `e1895e87`, `3d0951da` (pushed as `fcea86e6`) | the `inf` came from `fit_flow`'s proportional form scoring −∞ when an event arrived while the stock read zero; it is now "not fitted" with its reason, and `orchestra/finite.py` turns any non-finite number into null for the store, the API and the events endpoint. The web banner's token is shown only on a terminal, with a redacting filter on the loggers |
| workflows | `27c14d4`, `8e27b9d` (pushed as `2281dd6`; relock `fb2b107`) | `--supervisor` gives `design,observe,model,events,workflows,work` by default, `--tools` changes it, and it refuses to start with `orchestra-tasking` importable unless `--allow-tasking`; the gate's P4: the README says bridges and outbox are public and names orchestra-agents |
| agents | `b1cb6f2`, `d23f95e`, `7dc18d9`, `e227f93`, `e66bab5` (pushed as `4cc1af6`) | no quiet flag or restart advice unless the host marked the machine gone quiet; the owner's named phrases matched to heard event types; `at`/`tz` on `every`; items waiting outside, per step; "what changed since" lists every event class and names what the read missed; `read_model` says "could not be read"; no `coordinator` placeholder without tasking |

Both demos were restarted on T6: the example as run16 (03:57Z, the no-model 404 as expected on a
fresh run); the live demo on core `a8752494` and agents `7ecdcf3` (04:04Z), with the main demo's
line in `~/url` rewritten and verified.

## 4. What does not work, and why

The T3 judge (00:24Z) found 47 rows, 19 must and 28 should (core 2/4, agents 8/8, workflows 7/12,
outbox 0/2, coordinator 2/2), summarised per step in section 3. Beyond the steps: the example's
repository, Jira project and URLs were hard-coded (Data Center and GHE need settings), and
`agents working (supervisor)` showed "trust 0.83 high" from a balance that holds by construction.
T4 merged all of them. T2b showed most working (steps 1, 7, 9 and 11 to pass); what it still found
went to T6. What remains:

**Open follow-ups** (from the log):
- Fixed in T5: the no-model paragraph printed its grouped reasons as raw keys ("live in only n of
  n steps while every counter was (21)"); core `c9235fb6` puts the groups in words (02:08Z).
- `delivery_sail` and two other examples still print the login token (still so at 03:57Z; the run
  logs are kept mode 600).
- A Data Center PAT is read from the file named `jira-cloud-token`.
- Fixed in T5: the workflows `dev` extra did not list `orchestra-bridges`, so 41 `delivery_live`
  tests skipped in the main checkout; plugin `6028710` adds it (02:07Z; 473 passed, 4 skipped
  without `orchestra_outbox`).
- The main demo's link in `~/url` once carried a stale token (401). It was rewritten from
  `LOGIN.txt` and verified (01:54Z).
- At T2b's step 16 the Supervisor never called `read_model`, so T6's `read_model` fix rests on a
  new prompt line (the implementor's caveat).
- The walkthrough has not been run a third time, so T6 is not verified live.

Known gaps the script names and does not pretend are solved: the review is a stand-in (one
GitHub account); no 09:00 schedule (the nudger runs at 00:00 UTC); each reminder waits for
approval; Slack is disabled (the token lacks channel-read; an `xoxb-` bot token is needed); two
tickets make no model and no verdict on ×1.2 (about 200 events per era are needed); no SLO, log or
alert source; polling, so a short job waits up to 25 minutes.

Not done or not recorded: L4 (the push block against a full-path `gh` and an explicit pushurl) is
open (20:21Z). L5 is done in L1's README; the token refresh how-to stands. B1 to B10 have no log
line under their ids; some of their substance came in other rows (B6's page names in the R1 agents
fixes; the phone layout in R1 and R2). F2 has no log line.

**F4, the first report.** It is complete. Its gate section is filled, and branch `report` is
merged into core main (`16739f95`, "Merge branch 'report': the first run's report, complete
(F4)"). It is at `docs/reports/2026-11-01-workflows-run.md`.

**The release gate** (workflow `w7b12cqig`, finished 03:43Z). It took 60 agents, 15 h and 14.7M
tokens. The subtraction audit found 186 findings. Each repository had two layered review rounds:

| repository | findings, round 1 / round 2 | commits |
|---|---|---|
| core | 51 / 51 | 29 + 29 |
| agents | 50 / 43 | 1 |
| workflows | 57 / 45 | 25 + 34 |

The gate branches had already been merged in F3 (agents `30d09a1`, workflows, bridges `69a4b43`).
The final verifier says agents, workflows and bridges are ready to push. For the core it says
"no, fixes are small":

- P1. 7 layout JS failures caused by `~/package.json`. Already fixed on main by the CommonJS pin.
- P2. Plugin words in core code: a user-facing "the Supervisor's confirm" in
  `predictions_report.py:71`, and pile, workflow, agent and ticket in comments
  (`predictions.py:10`, `capacity.py:19,134`, `collect/views.py:32`, `discover.py:180`,
  `instrument_series.py:5`, `sd-graph.js`, `instruments.html:101`).
- P3. `discover.py:184-189` names a series by its step and place labels. Reported as a design
  question; SPEC's views mechanism and D33 cover it.
- P4. The workflows README calls bridges and outbox private (on GitHub they are public) and never
  names orchestra-agents.
- P5. The tasking extra in the core's `pyproject.toml`.

Suites at the gate heads: core 1214 passed (plus 7 environment failures, P1), agents 697,
workflows 547, bridges 312. P2 and P4 were fixed in T6 (section 3). P3 stays a design question,
and P5 (the tasking extra) is not recorded as changed.

**What is next.** A third walkthrough (T2c) on T6 is running, and the live demo's move to the
Workflows `task_loop` example without tasking is being built on agents branch `demo-task-loop`;
their results will be an addendum.

## 5. Decisions taken, and by whom

**How the proxy resolves a disagreement** (OWNER-PROXY.md): the owner's cited words win over any
taste; when the owner's voice does not know, two or more of the other six agreeing win, with the
dissent recorded; a split, or one persona alone on a product question, goes to your list with a
default; a finding resting only on a proposal is dropped; anything on the never-list (a new page, a
human control outside rule 9, a plugin's domain in the core, money over the cap) is escalated, never
built.

**Rows won per persona** (the judges' "Per persona" tables):

| persona | R1 won / lost | R2 won / lost | T3 won / lost |
|---|---|---|---|
| a owner's voice | 10 / 1 | 8 / 0 | 15 / 2 |
| b SRE | 9 / 1 | 8 / 2 | 14 / 1 |
| c modeller | 7 / 0 | 9 / 0 | 9 / 0 |
| d information designer | 14 / 0 | 12 / 0 | 13 / 1 |
| e machine author | 11 / 0 | 14 / 0 | 17 / 3 |
| f architect | 6 / 6 | 11 / 0 | 4 / 3 held, 1 held on Y7 |
| g adopter at work | 9 / 1 | 12 / 0 | 12 / 0 |

R1 gave 25 rows to its implementors (8 must) and 24 escalations. R2 gave 53 (14 must) and 11 new
escalations. T3 gave 47 (19 must) and 14 new.

**Taken by the proxy, with the persona that carried it:**
- Pile stocks named for the workflow, the step and its place; hidden stocks "between A and B";
  piles on the Instruments page (N1, from your words at 17:45Z; a held R1 to them).
- Every write the example makes goes through an Outbox draft; K8 settled by moving writes out of
  the kits (e; O1).
- Scripts land in the owner's repository, credentials by file reference (e, g; B11a).
- QUICKSTART starts on the Workflows plugin's `task_loop`, with the Supervisor writing the first
  configuration (a; B11a).
- Vocabulary: V1, V2 and V4 small words; V5, V6, V9 and V10 no word (e, R1). S3 recorded all ten.
- Agent sessions get none of the host's credentials (g, R1).
- The Dashboard lists attention and person waits first (b, R1).
- The walkthrough's defaults (T1, b and a): a stale review reaches an Outbox draft approved each
  time; incidents do not pause deliveries; the Supervisor asks the time zone.
- T3: a's "propose receives from heard events" was refuted in code and became a wording should;
  d's drop of the stock note was overruled in part.

**Taken by the coordinator** (by "Who decides what"):
- The re-plan to the budget after your 18:00Z message, and the operating rule after 18:02Z: build
  milestones run without waiting, one implementor round per panel round, UI rows capped.
- Refuter rounds before every discovery merge: the passage fixes were sent back once ("do not
  merge", 18:21Z), U5 once, the R2 discovery rows once.
- U5, the capacity rule, dispatched from U1's finding (19:02Z).
- Merge order and re-locks; the workflows gate merged in a scratch worktree (22:10Z).
- A `package.json` with `type: commonjs` at the plugin's and the core's roots, after a new
  `~/package.json` made Node load the scripts as ESM (23:15Z).
- The delivery_sail acceptance on seed 5 (the S3 agent, 19:05Z).
- The example demo's login token pinned across restarts, at your request (18:48Z).
- The T3 coordinator rows applied to the script (9fbcce41).
- Left to you by an implementor: team → group (R2 core, 20:59Z).

## 6. How to run each thing

**The live delivery example.** In `~/orchestra-workflows`, `examples/delivery_live/demo.sh
--tickets 3` makes three test tickets assigned to you and prints a login link.
`--dry-run --tickets 3` does the same on fakes. `--cleanup` closes test tickets and pull requests
and deletes their branches. `--scope board` takes any SCRUM ticket assigned to you, and its close
waits for you on the Outbox page. The harness flags (`--hold-review`, `--release-review`,
`--incident open|resolve`, `--request "…"`) are in its README, "Run it". Credentials are files in
`~/.config/orchestra-bridges/`, mode 600.

**The walkthrough with the Supervisor.** Today it starts from the agents' launcher
`tests/live/delivery_live_run.py` with the role's tools `design,observe,model,events,workflows,work`,
`--via bash`, in a venv without `orchestra-tasking`; see the script's "The fresh state". T4 added
`demo.sh --supervisor` (workflows `35b2b9c`), but T2b found it gave no `request_work`. Since T6
(`2281dd6`) its default role includes `work`, `--tools` changes it, and it refuses to start when
tasking is installed unless `--allow-tasking`. It has not yet carried a walkthrough.

**Integrations.** `docs/INTEGRATING.md` and QUICKSTART in the core. `~/orchestra-bridges` is now
the library (B11): kits, fakes, templates and scaffold. `integrate_system` writes a collector into
your repository at `.orchestra/machines/<name>/`.

**The demos.** The core demo on :8096 and the delivery_sail example on :8101 ran every merged
change as of 21:29Z. Both now run T6: the example as run16 (03:57Z), the live demo on core
`a8752494` and agents `7ecdcf3` (04:04Z). Login links are in `~/url` (mode 600).

## 7. Live model spend

| task | model | spend |
|---|---|---|
| A3 (first run) | Haiku, some Sonnet | $6.33 |
| A3b (first run) | Haiku | $0.19 |
| I3 (first run) | Haiku | about $0.13 |
| L2 | Haiku, two runs | $0.25 |
| L3 | Haiku, three runs | $0.21 |
| T2 | Haiku, 11 invocations | $0.37 |
| T2b | Haiku, 10 invocations | $0.42 |

This run: $1.25. Both runs: about $7.9 (the log's figure), under the $30 cap. T4 spent $0: no Supervisor or agent harness ran
a model; its implementors and reviewers are the run's Opus subagents, outside the live-spend cap.
T6 spent $0 too (no Supervisor ran). L1 spent nothing on AI. T2-prep's spend is not recorded. Agent time is not recorded as a
total. The log gives durations only: T2 took 1 h 35 min, T2b 1 h 39 min (01:59Z to 03:38Z), and
the release gate 15 h over 60 agents.

## 8. Suite results

The last recorded result per repository, with `rc` read directly. Ruff was clean and the secret
scan 0 at each push.

| repository | commit | result |
|---|---|---|
| core | `12be615d` (T4) | 1102 passed, 2 skipped, rc=0 |
| core | `f4a753f0` (T6-words) | 1104 passed, 2 skipped, rc=0 |
| core | `fcea86e6` (T6) | 1111 passed, 2 skipped, rc=0 |
| core | R2 implementor's branch | screenshots 7, by the agent |
| agents | `c77915a` (T4) | 666 passed, rc=0 |
| agents | `4cc1af6` (T6) | 681 passed, rc=0 |
| workflows | `35b2b9c` (T4) | unit 477 passed rc=0; e2e 87 passed rc=0 (10.5 min) |
| workflows | `2281dd6` (T6) | rc=0 (474 passed on the branch) |
| workflows | `fb2b107` (T6 relock) | 474 passed, 4 skipped, rc=0 |
| bridges | `14119cf` | 172 passed, rc=0 (no T4 or T6 rows) |
| outbox | `a53a70a` (T4) | 99 passed, rc=0 |

At the gate heads (the verifier, 03:43Z): core 1214 passed with 7 environment failures, agents
697, workflows 547, bridges 312.

One red result was caught before a push: the plugin's re-lock to core `bbe7255a` failed 2 tests
on the `NetGeometry` split (20:02Z); the Items graph fix merged first.

## 9. What the coordinator got wrong

- **It wrote stamps ahead of the clock again.** Seven stamps were estimated and corrected at
  18:13Z, and one bridges stamp at 17:50Z. Since 18:13Z every stamp comes from `date -u`.
- **It wrote that a thing had happened before it had, three times.** At 18:41Z it logged the R1 core
  merge, which happened only at 18:42Z (the chain had stopped on a stale check). At 20:32Z it
  corrected the agents line before it: agents main was not pushed, 1 test had failed, and "the
  previous line was written from a template before the result was read". The push came at 20:36Z,
  after a re-lock and an rc of 0 read directly. At 00:28Z it logged the outbox as pushed; the push
  had been rejected (rc=1, origin had moved). The 00:29Z correction calls it "the third time this
  run" and sets the rule: a log line comes only after the push's rc is printed, in a separate
  command.
- **You had to remind it.** At 18:02Z you wrote "I am constantly needing to remind you of things
  and give feedback, these things should be handled automatically", and asked not to spend half
  the budget on small UI tweaks. Before that you had corrected the pile names (17:45Z) and asked
  whether the bridges were a library (17:52Z).
- **Its demos ran old code.** R1 found the :8096 demo on an agents worktree 34 commits behind
  main, with 0 stocks.
- **Its walkthrough venv had the task system.** The agents' `dev` extra brought tasking in, so T2
  showed a Tickets entry, a TASKS panel and twelve unanswered task queries. T3 made it a
  coordinator must, now in the script.
- **Restarts minted a new login token for about a minute** before the pin; you saw it change
  (19:10Z). `restart-example.sh` now writes the pinned token first.
- **Cleanup leaks.** An orphaned `fake_bridges.py` ran 5 h 30 from a plugin test (killed 00:10Z).

## Addendum, 2026-11-02 (after the owner's return)

**1. Your words, and what the coordinator got wrong.** You looked at the example demo's Dynamics
page at 04:19Z: "not very impressive. The names of the all the system dynamics stocks are weird,
most of the agents in the Event Map look like they both publish and subscribe to the same events.
These are bad things. I would have expected one of our reviewer steps to notice this. Most of the
agents in the event map are still marked 'unconfirmed', I would have expected those to be tested
somehow? Are there unconfirmed stocks as well? What does confirmed or unconfirmed even mean here?
If one of the demo apps is integrated with our sample Jira API and some sort of Slack or whatever,
that would be impressive." On :8101 the stocks were named "write (waiting) · delivery_sail" and
"git branch commits (main)", and the floor's offer events, which every role machine both publishes
and subscribes to, filled the map. Two of the faults were the coordinator's. It ran the
release gate with `skip=[ux, models]`. It also judged R2's naming row fixed from the code, without
looking at the page.

**2. What "unconfirmed" meant, and what the pages say now (D1).** "Unconfirmed" meant a machine
the Workflows plugin proposed from the definition and that was heard on the bus. Nothing confirmed
it, because no Supervisor runs in delivery_sail. D1 (04:49Z) changed three things:

- **Names.** Stocks now read "items waiting at write", "items waiting at review" and "commits on
  main". Flows read "start → write", "ci → write (sent back)", "review → sail" and "sail_check →
  end".
- **The Machines map.** A machine that exchanges event types both ways with two or more others is
  drawn as a hub. Its types fold into one thin `offer.*` line, and hand-offs are drawn machine to
  machine, "through supervisor". On task_loop that gives worker → reviewer → merge_gate.
- **States.** "Unconfirmed" is gone. A machine reads "heard · proposed by the workflows plugin",
  "declared, never heard" or "confirmed by <who>".

Limits: "waiting at", not "waiting for" (the core has no step words); `ci` stays lowercase;
hand-off arrows are labelled by event type, not step. D1 passed 1115
tests, rc=0, and is in core main `fc007dc9`. The plugins were relocked to core `a0ba8631`, and the
example runs it as run17 (04:53Z).

**3. The public demo without the task system.** At 04:56Z orchestra.dansproject.space switched to
the Workflows task_loop example. It runs from `~/orchestra-live-demo/restart-task-loop.sh` (agents
`demo-task-loop`, merged as `8dc2501`), makes 5 items every 300 s, and cannot import tasking. The
old `restart.sh` would reinstall tasking; `README-task-loop.md` beside it says so.

**4. The standing real-Jira demo (D2).** `delivery_live --standing` is built, merged and pushed
(workflows `a63cf56`, agents `2be2a8f`). It opens one test ticket every 2 h while fewer than 2 are
open, at most 12 a day. It keeps its counters across restarts, resumes, and pins its token. At the defaults, a day makes about 36 Jira writes,
about 12 pull requests and about 80 GitHub writes, plus one cleanup commit and 288 polls per poller.
The Supervisor pauses at a daily cap ($2 by default), with the reason on the Agents page; a turn
already running may go slightly over. A dry run on fakes passed. The real run waits for your word
on the board's traffic, and Slack still needs a bot token.

**5. T2c, the third walkthrough (on T6).** 12 steps passed (2 to 9, 11 to 14), 2 misled (1, 15)
and 2 failed (10, 16). The counts match T2b, on different steps. Step 8 is fixed: there is no
"quiet, restart" claim, and the unasked wake calls the hold deliberate. Step 14 is fixed: it says
it cannot tell the impact, where T2b said there was none. All three checks were good: no token in
`logs/web.log`, `/api/dynamics/model` gave 404 and then 200 and never 500, and there was no
coordinator card. The example's `--supervisor` started first time with the right role. Spend:
$0.47 over 11 Haiku calls, and about $8.4 for the run. SCRUM-23 to 25 are Done and pull requests
#21 to #23 merged.

New findings:
- At steps 1, 10 and 15 the Supervisor said the proposed machines and the nudger's program "don't
  run", and pointed at a Coordinator that does not exist.
- At step 10 the nudger listened for `github.pr.approved` and `changes_requested`, which never
  appear on the bus, so `check_nudger` fails.
- At step 16 it said "two were merged" when three were, said "the outbox will not send" when it
  was only idle, and left out the triage verdict and the model.
- On the Dynamics page, `erasBar()` breaks when a prediction exists but no era is recorded.

**6. In progress.** T8 fixes T2c's findings: core `T8-eras` for the eras bar, and agents
`T8-agents` for the Supervisor's wording, receives taken only from heard types, event tallies, the
idle Outbox and the model's state. [outcome pending] UX2 is a two-round ux-review on the example,
with its implementor on core branch `UX2`. [outcome pending]

**7. The test leak (T7).** `test_host_launch.py`'s fixture stopped hosts only at teardown, which
never runs when pytest is killed. `test_host_collect`, `test_endpoint_e2e`, `test_config_edit` and
three launcher tests leaked on timeouts. A spawn fixture with a reaper (`tests/unit/reap.py`) now
stops the process group. Merged and pushed as core `ff3876c7`: 1111 passed, 2 skipped, rc=0, and
no orphan after the suite.

## Addendum 2, 2026-11-02 (the UX round, four more walkthroughs)

**1. The walkthrough series.**

| run | pass / misleading / fail | fixed before it | what it found | spend |
|---|---|---|---|---|
| T2 | 7 / 2 / 6 | none | section 3 | $0.37 |
| T2b | 12 / 2 / 2 | T4 | the model API's 500, the token in `web.log`, the coordinator card | $0.42 |
| T2c | 12 / 2 / 2 | T6 | machines that "don't run", receives never heard, the eras bar | $0.47 |
| T2d | 12 / 0 / 4 | T8 | the T8 regression (steps 11 and 13); `offer.withdrawn` kept in receives (10); no model state (16) | $0.63 |
| T2e | 13 / 1 / 2 | T9, T10 | the re-proposal that wiped the owner's refinement (10); "runs on the schedule" (11); the prediction's state missing (16) | $0.74 |

The run's live model spend is now about $9.7, under the $30 cap. T2e passed steps 1 to 9 and 12
to 15. Step 11 misled: the reminder draft waited, was approved on the page and posted once on PR
#26, but the Supervisor said it "runs on the workflow's schedule, not right away" (it ran 2 s
later). Step 10 failed in a new way. Once `declare_workflow` succeeded, the Workflows plugin
retracted `review_nudger` and proposed it again 25 s later, wiping the owner's receives and the
09:00. The confirm then confirmed the bare proposal.

**The T8 regression.** Over bash, `declare_workflow`, `request_work`, `integrate_system`,
`add_instrument`, `switch_kind` and `read_transcript` answered "unknown tool". `tools_for()`
returned copied tool definitions, and `Caller.tool()` tested membership by object equality. No
unit test called a gated tool over bash, so the suite passed. T9 (agents `c20c75f`) finds a tool
by name and tests the six tools over bash and MCP. It also found that MCP calls had been broken
too; only the listing worked. So T2c's passing steps 10 to 13 ran before T8, and T8 was first
exercised live in T2d.

**2. The UX round (UX2).** A two-round ux-review on the example: 18 agents, 3.7 h. Round 1 fixed
"honest Dynamics and Machines pages" (`8dcd3ff4`). Round 2 brought like-for-like flow checks,
honest hidden stocks, one hung machine marking only itself, liveness by the machine's rhythm, the
phone's hand-off list, the map's fit and the kind control (`48b77b93`). It was not clean after
round 2: the last triage had 51 rows, and the implementor applied its musts and more. The rest of
the core shoulds are follow-ups.

UX2's merge conflicted with T8-eras in `dynamics.html`. An agent merged in the UX2 worktree,
keeping both sides (1143 passed, 2 skipped, rc=0; Node 95/95). It is in main as `f9d3be5a`.

**What the coordinator got wrong.** A log commit ran while that merge sat conflicted in the main
checkout, and `git commit -am` captured the conflict markers as `33c2bddc` (never pushed). The
coordinator reset main to origin. That also dropped every unpushed log line since the T8 core
push. It restored the log file from the dropped tip, found in the reflog, so no line was lost.
From then on, merges run only in worktrees.

The plugin's UX rows (UX2-plugin, 6 commits, plugin `c4b9ab8`):
- An outside system is declared as its bot and never lists what it publishes as received.
- Unclaimed offers show under who must act ("offered N×, unclaimed since …").
- A role's proposed kind and mode come from its machines.
- Step actors are named as the map names them.
- The Items page has a favicon and wider fields.

One row was skipped: per-role `listens_for`, because it would change the bus contract.

**3. The demos now.** The example runs as run19, with the UX2-plugin rows. The public demo runs
task_loop on core demo-live `5d6a3a4c` and agents demo-live `64998bf`.

**4. Your second question.** At 09:41Z you asked: "'item' is a generic idea, a 'task' is a type
of 'item'. These are being described as if all items are going to be tasks … Most types of
'items' I can think of won't have pull requests or continuous integration. We had set out to build
an abstract item system, and make tasks a subtype of it. Did we accomplish that, or are they
improperly entangled?"

What the check found:
- The steps `write`, `open_pr` and `ci` are delivery_sail's own. The plugin's vocabulary has no
  task concept. on_call (analyse → decide → runbook), staged_rollout (canary → ten → fifty →
  hundred) and rc_verification (cut → checks → release) are items with no pull request.
- It is entangled in three places. The built-in worktree resource kind sits in the plugin's own
  code (about 55 mentions). The scripted reference worker uses worktrees. `guide.md`'s examples
  lead with tickets and pull requests.
- A definition cannot say what its items are (no noun), so every stock reads "items".

T11 adds a noun per definition and makes the guide's examples lead with a workflow that is not
code. Moving the worktree kind is your call: it is now the third question at the top of this
report.

**5. T11.** Workflows: a re-proposal merges into a declaration the owner refined, and never
retracts and re-proposes it; the item noun; the guide. Agents: a request runs now, and the
schedule is the daily run; the zone answer sets `tz`; the since answer carries the prediction's
state and the Outbox's running state, with the model line last. [outcome pending]

## Addendum 3, 2026-11-02 (the owner's answers, Slack queues, the focus, six walkthroughs)

**1. The sixth walkthrough (T2f).**

| run | pass / misleading / fail | fixed before it | spend |
|---|---|---|---|
| T2e | 13 / 1 / 2 | T9, T10 | $0.74 |
| T2f | 15 / 0 / 1 | T11 | $0.63 |

T11 fixed three things. Step 10 now holds the six event types, the 09:00 and the confirm, with no
retract and re-propose. The zone is taken ("09:00 America/Los_Angeles"). Step 11 says "running
now" and posts one comment on #29 after the page approval. Stocks now carry the definition's noun:
"deliveries waiting at review". Step 16 now gives the prediction's state and the right Outbox
state, but three things are still wrong: it leaves out what waits on you, it credits the model
change to the declaration instead of discovery, and it does not end on the model line. T2f also
found that `tz` never reaches the declared machine, because the repository's copy overrides the
one `declare_workflow` writes. The run's live spend is about $10.3, under the $30 cap.

**2. Your four answers (10:36Z), and what each started.**

*Board traffic.* "the sprint board itself is low traffic, but there are very many jira tickets i
need to track, like Production Readiness Review tickets for meetings I conduct and User Filed Bug
tickets … I am SRE, so it's good to track a lot of stuff." The standing `delivery_live` demo is
starting now, at one test ticket every 4 h and at most 6 a day, on :8105, with a public tunnel.

*Slack.* "we will get a slack bot token, we wont post initially, we will do a lot of work with
reading things in slack threads … I have to monitor about 5 channels every day and make sure they
have a little green checkmark on them … That is a very important thing I want to measure, our
effective secondary task queues in Slack."
- The bridges' Slack kit (`aff4dec`) relays threads as `slack.thread.started`, `replied`,
  `checked` and `unchecked`, with per-channel cursors. Its scopes are exactly `channels:history`
  and `channels:read` (plus `groups:*` for private channels). Nothing posts.
- The `slack_queues` example (workflows `33192ba`) makes threads into items across five channels,
  with response policies as settings. Its Dynamics page shows three stocks: threads waiting at
  `awaiting_reply`, at `late` and at `awaiting_check`. The scripted day ended with 5 late, 5
  unchecked and 20 closed.

*Worktrees.* "the worktrees may be part of an SCM or VCS library, but i dont know where it should
go or what interface it should have … I know we need either github pr stacks or git-spice for
pull requests." `docs/proposals/scm-providers.md` (core `739b729f`, 2,352 words) proposes an
orchestra-scm library shaped like bridges. It has providers for a plain branch and pull request,
GitHub PR stacks, git-spice and trunk, a provider interface as bus events, company PR templates,
and a migration from `needs: worktree`. Its three questions are now at the top of the owner's
list.

*Workflows on the pages.* "the proper solution is to show a sub-graph of the event graph or
system dynamics model -- the parts that refer to the workflow … They are like feedback loops,
they deserve to be shown on their own, but they are inherently interconnected to the whole
system." The core's `Orchestra.focus` (core `1da9e43c`) shows a sub-graph of the one model, with
named stubs at its edge, chips above both diagrams, and the focus kept in the URL hash. The Event
Map is taller: it fills 600 to 1100 px. Each workflow definition offers its machines, event types
and pile stocks as a chip (workflows `8178151`).

At 10:40Z you added: "I will hit Reset every time." Both diagrams now open in the Reset state.
They re-run Reset when the structure changes, but never mid-drag or on a plain refresh.

**3. Three contract drifts found only by relocks.**
- The plugin's new `about` key was missing from the agents' `declare_workflow` schema (01:53Z).
- So was the `items` key (10:03Z).
- The agents edited `machine.toml` in a scaffolded kit, while the bridges' scaffold has written
  `poller.toml` since `368ff7d`. 24 tests in `test_integrate.py` failed. The agents now use the
  bridges' `machinefile.locate`, with a test pinning both layouts (agents `ea52a35`).

The coordinator's rule since 10:03Z: a plugin agent that changes a contract names the change, and
the other side's row goes in the same round.

**4. T12.** Agents: step 16's three misses. Workflows: the `at`/`tz` edit lands in the copy that
wins. [outcome pending]

## Addendum 4, 2026-11-02 (the standing demo, Slack queues public, eight walkthroughs)

**1. The seventh and eighth walkthroughs.**

| run | pass / misleading / fail | fixed before it | the failing step | spend |
|---|---|---|---|---|
| T2f | 15 / 0 / 1 | T11 | 16 | $0.63 |
| T2g | 15 / 0 / 1 | T12 | 16 | $0.64 |
| T2h | 15 / 0 / 1 | T13 | 10 | $0.71 |

T12 fixed step 16's three misses from T2f. The answer now closes with the model line, taken
verbatim from the version's record. It credits the change to discovery, and it has a "waits on
you" section. But T2g's answer dropped the prediction's state and the triage verdict, and got
times and counts wrong: pull requests #33 and #34 "opened 04:57" when it was 04:16, "all three
merged 05:12" when one was, and "2 opened/2 closed" when three were Done. Every one of those facts
was in the tool's answer. The error was Haiku's synthesis.

T13 (agents `9bb7d5c`) renders the whole "what changed since" answer in the tool, with times in
the pages' zone, and the prompt relays it verbatim and never guesses at a cause. In T2h, step 16
passed for the first time. The reply was the tool's digest character for character (3,681
characters), and every fact checked against the bus. Its "waiting on you" missed the Supervisor's
own open question. Steps 8, 9 and 15 carried no guessed causes.

T2h failed step 10 in a new way. The example git-ignores `.orchestra/`, so T12's rule read the
repository's copy of the definition as "untracked" and refused both writes. The Supervisor asked
the owner which copy to use, a question the script's owner never answers, so no 09:00 was
declared.

The run's live spend is about $11.6, under the $30 cap.

**2. Two new public demos.** Both links are in `~/url`.

- **The standing delivery demo on the real SCRUM board** runs on :8105 behind a quick tunnel. It
  opens a test ticket every 4 h, with at most 2 open and 6 a day, and writes only within the
  approved scope. Its Supervisor runs on Haiku over bash, capped at $2 a day. Its first start
  failed: `--supervisor` needs `orchestra_agents` in the plugin's venv, and the script installs
  nothing. So it runs from a dedicated worktree, `~/orchestra-workflows-wt-standing`, with the
  agents and the outbox installed.
- **The Slack queues example** runs on fakes on :8606 behind a quick tunnel, with a scripted day
  every 30 minutes.

A walkthrough now owns the board while it runs. The coordinator pauses the standing demo first
(`standing/stop.sh`, state kept) and resumes it after (`--resume`). Otherwise the walkthrough's
`--cleanup` would close the standing demo's tickets. Once that happened, and it was allowed: the
first T2g cleanup closed the paused demo's SCRUM-34 and pull request #32.

**3. Contracts and the script.** The third contract drift (`poller.toml` against `machine.toml`)
and the same-round rule for schema rows are in Addendum 3. Nothing has drifted since. The
walkthrough's step 10 now reflects the scheduler. The declared 09:00 really runs, because the
scheduler honours `at`. `tz` may wait as a pending revision for your confirm.

**4. T14.** Workflows: a git-ignored repository copy is the live one and is written without
refusal. Agents: every unanswered Supervisor question goes into "waiting on you". [outcome pending]

**5. Where this leaves the walkthrough.** Two runs in a row passed 15 of 16 steps. The last
failure moved from step 16 to step 10, a different step each time, so no one step
keeps failing. Two things are structural. The walkthrough has
never run overnight: step 16 has always been asked after a short quiet period, not the next morning. And the
answer that passed step 16 is text the tool rendered, not Haiku's own synthesis. The small model
relays a digest well, but on this evidence it cannot yet be trusted to summarise a day by itself.

## Addendum 5, 2026-11-02 (the walkthrough at 16 of 16)

**1. The series.**

| run | pass / misleading / fail | fixed before it | what it found | spend |
|---|---|---|---|---|
| T2 | 7 / 2 / 6 | none | section 3 | $0.37 |
| T2b | 12 / 2 / 2 | T4 | the model API's 500 on an `inf`, the token in `web.log`, the coordinator card | $0.42 |
| T2c | 12 / 2 / 2 | T6 | machines that "don't run", receives never heard, the eras bar | $0.47 |
| T2d | 12 / 0 / 4 | T8 | the gated tools "unknown" (T8's regression) | $0.63 |
| T2e | 13 / 1 / 2 | T9, T10 | the re-proposal wiping the owner's refinement; "runs on the schedule" | $0.74 |
| T2f | 15 / 0 / 1 | T11 | `tz` never reaching the declared machine; step 16's three misses | $0.63 |
| T2g | 15 / 0 / 1 | T12 | Haiku's synthesis misstating step 16's facts | $0.64 |
| T2h | 15 / 0 / 1 | T13 | the git-ignored repository copy refused (step 10) | $0.71 |
| T2i | 16 / 0 / 0 | T14 | two small gaps outside the pass rules (below) | $0.60 |

The run's live model spend is about $12.2, under the $30 cap.

**2. T14 and what is left.** T14 writes a git-ignored repository copy, or one with no git, and
says so (workflows `3f6ad34`). A tracked, clean copy is written too. An edited or untracked copy is
still refused, with the one thing to do named. In the agents (`cc7afc5`), a numbered choice list
counts as a question, open until the owner names a choice or its subject. In T2i, step 10 wrote
the git-ignored copy and said so. It asked the zone, wrote America/Los_Angeles, and passed
`check_nudger` twice. The scheduled run started at 17:00Z, which is 09:00 PST. Step 11 passed on
the first call. Step 16 was the digest verbatim (3,825 characters), and every fact matched the
bus, GitHub, Jira and model v3. There were no guessed causes, no token in the logs, and the model
API always answered 200.

Open follow-ups, both outside the pass rules:
- Step 10's answer no longer says that reminders wait for approval. Step 11's answer does.
- The declared machine shows 09:00 without the zone. The zone lives only in the definition, and
  no revision is pending.

**3. What the series proved, and what it did not.** It proved that every step of the owner's day
passes on Haiku, over bash, from the example's own start (`--supervisor`, first attempt), on the
real SCRUM board and the private repository. It did not prove the morning after. No walkthrough has
run overnight: T2i's step 16 came after 22 minutes alone. Step 16 also passes because the tool
writes the answer and Haiku relays it, not because Haiku summarises the day. The standing delivery
demo is the overnight run. The next check is one question to its Supervisor the next morning:
"What changed since yesterday?"
