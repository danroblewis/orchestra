# The Monday walkthrough (S7, T1)

Status: the script for T2, written 2026-11-01 by the SRE on Monday and the owner's voice
([OWNER-PROXY.md](OWNER-PROXY.md) personas b and a). The day is the owner's delivery (Q6:
design-backwards-notes.md 116-121) and on-call (Q6: 141-145), run on `examples/delivery_live` in
`~/orchestra-workflows` with the Supervisor beside it. No question in
[GOAL-2026-11-02-second-half.md](GOAL-2026-11-02-second-half.md) "Questions for the owner" has been
answered, so every bracketed default stands; where the script uses one it says "default Qn".

The SRE plays the owner. The owner talks only in the Supervisor's chat; the pages are for looking.
The coordinator starts the run (the recipe below) and plays the harness (a hold on one review, one
fake incident, both `demo.sh` controls on the run's `--dir`); it never types in a page or edits a
file once the clock starts. The owner's one page act is approving the nudger's reminder on the
Outbox page (step 11).

## The fresh state

**Wiped before the run:** any earlier run directory and its `home/` (Orchestra's state, the bus,
the metrics, the declared layer, the Supervisor's sessions); the outbox's state; the kits' caches.
`demo.sh --cleanup` first: it closes test tickets still open (label `orchestra-live-test` only),
closes test pull requests still open and deletes their branches.

**Kept:** the repository `danroblewis/orchestra-live-delivery` (main and its three labels, `SAIL`,
`SAILED`, `REJECTED`); the SCRUM board with its earlier, Done test tickets; the plugins at their
pushed mains; the credential files.

**Credential files** (in `~/.config/orchestra-bridges/`, mode 600, read by the programs, never
printed): `jira-cloud-token`, `jira-cloud-email`, `github-token`; `slack-token` optional (today it
is an `xoxe.` app configuration token, so Slack must show as disabled with that reason); a
logged-in `claude` and `gh`.

**Start:** the agents' launcher `tests/live/delivery_live_run.py`, with the role's tools
`design,observe,model,events,workflows,work` (`work` holds `request_work`; L3's role lacks it) and
without L3's forced Slack-off, so the Slack card states its own reason. The launcher passes what
follows its `--` to `examples/delivery_live/demo.sh`:
`-- --tickets 2 --reject-first 1 --reject-rate 0 --hold-review 2 --port 83xx --dir <run>`.
This gives exactly one rejection (the first pull request at SAIL, ticket A) and holds the second
pull request's review (ticket B) for 40 minutes or until released.

**Ports:** the web on the first free port in 8300-8319; the outbox and the fakes take any free
port (the example's `port = 0`); nothing on the never-list (8096, 8101, 8157, 8173).

**Spend:** Haiku only, $10 for the whole run, $5 per attempt (the launcher's
`ORCHESTRA_LIVE_CAP_USD=5`); the run stops at the cap and the report says so.

**Evidence:** the chat transcript, the redacted bus (`demo.py --transcript`), and a screenshot of
each page named in a step at 1440 and 390 px, under the scratchpad.

## Timing

Jira and GitHub are polled every 5 minutes; that is the floor. "One poll" below means up to 5
minutes, and a step that waits on one says so. The fake PagerDuty is polled every minute. The
Supervisor's answer is budgeted at 90 seconds. A ticket with no rejection takes about five polls
(25 to 30 minutes); a rejection adds four more. The day's clock budget is 3 hours to step 15.

## The two tickets

Ticket A goes through with the one rejection. Ticket B's stand-in review is held by the harness
(`--hold-review 2`), so its review goes stale past the 30-minute guard.

## The steps

**1. Monday, first look.**
(a) The owner opens the Dashboard (default Q3) and says: "What needs me?"
(b) Nothing yet. The machines announce: `worker/1`, `worker/2`, `reviewer_stand_in`, `sail`
(fake), `sail_triage`, `supervisor/dispatch`, `outbox`, the fake PagerDuty's actors, `slack_notify`.
(c) Dashboard: an empty "needs me" list with its reason (nothing waiting on you). Machines: the
above, `sail` and the PagerDuty actors marked fake, `slack_notify` disabled with its reason. No
poller, floor or program host as a machine.
(d) The answer: nothing needs you; nothing is stuck; Slack is disabled and why (the token is an
app configuration token, not a bot token).
(e) 90 s.
(f) Pass: the answer names no ticket and states Slack's reason in the card's words; the Machines
page shows no infrastructure process.

**2. Two tickets assigned on SCRUM.**
(a) Nothing; the launcher creates and assigns A and B, "[orchestra live test]", to the owner.
(b) `jira.issue.assigned` from `person.jira.<accountId>`, one per ticket, then the floor's
`offer.made` to a worker. No earlier Done ticket is relayed as assigned.
(c) Items: A and B at `write`, each with its ticket key and summary. Machines: the owner on Jira
handing to `supervisor/dispatch` and a worker.
(e) One Jira poll.
(f) Pass: exactly two items, keyed by the two new tickets; any third item is the Done-replay gap
and fails the step.

**3. The worker's branch and pull request.**
(a) Nothing.
(b) Each worker pushes a branch and writes the pull request's title and body naming the ticket;
the outbox opens the pull request (`live.pr_open`, approved by configuration) and the worker links
it, so the item gains the facts `commit`, `number` and `pull`; `github.pr.opened` from
`person.github.<login>`.
(c) Items: A and B at `ci`, the pull request as a link. Machines: the workers and the owner on
GitHub.
(e) The push takes seconds; `github.pr.opened` waits one GitHub poll.
(f) Pass: two real pull requests, one per ticket, each description naming its ticket key; the
GitHub poller relays no earlier pull request.

**4. CI.**
(b) GitHub Actions runs; `github.checks.completed` from `bot.github.github-actions` with the
item's `head_sha`, outcome `success`.
(c) Items: A and B at `review`.
(e) One GitHub poll.
(f) Pass: each item moved on the check of its own commit.

**5. The stand-in review.**
(b) For A, `reviewer_stand_in` submits a `COMMENT` review; `github.pr.commented`. B is
held: no review.
(c) Items: A at `sail`; B at `review`, waiting on reviewers, with the time it has waited.
(e) One GitHub poll.
(f) Pass: A moves, B does not.

**6. The SAIL label through the Outbox.**
(b) The floor drafts `live.sail` for A's pull request; the outbox approves it by configuration
(the test repository only) and adds `SAIL` as the owner; `outbox.sent`; the step ends `sent`.
(c) Outbox: A's draft, "approved by configuration", sent, with the target pull request. Items:
A at `sail_check`.
(e) Seconds, no poll.
(f) Pass: the label is on the real pull request and the Outbox page shows the draft before it
shows it sent; no SAIL write appears on the bus except the outbox's.

**7. SAIL's result: a rejection, triage, rework.**
(b) The fake `sail` labels A `REJECTED` (forced by `--reject-first 1`); `github.pr.labeled` relayed; the floor runs
`sail_triage`, which asks the fake PagerDuty for an incident on the SAIL runners' service (none)
and exits `local`; A returns to `write`; the worker pushes a rework; `github.pr.synchronize` takes
A to `ci`, then `review`, `sail`, `sail_check` again.
(c) Items: A's timeline shows `REJECTED`, triage's verdict `local` and its sentence, and
"reworked". Machines: `sail` (fake) and `sail_triage` acted.
(e) Four GitHub polls for the round.
(f) Pass: the timeline shows the outcome and the verdict, not only the step names.

**8. Mid-morning: "what is stuck and why".**
(a) The owner: "What is stuck, and why?"
(b) The Supervisor reads `list_items` and `explain_item`; nothing is written.
(c) Dashboard: B, waiting on reviewers, with the time.
(d) The answer, item by item: A with its ticket key, pull request number, its step and the
rejection that sent it back; B with its key and number, waiting on review since its local time.
(e) 90 s.
(f) Pass: every open item named with its key and pull request number, none invented, each with a
reason (the L3 judge's `check_answer`).

**9. A stale review.**
(b) B's `review` guard (30 minutes) fires `attention.needed`; `slack_notify` would draft a line,
but Slack is disabled.
(c) Dashboard: B in "needs me" with the owner (not `supervisor (planner)`) as who must act and the
guard's reason. Items: the guard shown on B's timeline.
(e) 30 minutes from step 5; no poll.
(f) Pass: B appears in the Dashboard's list with the owner as who acts.

**10. The nudger and an expectation.**
(a) The owner, in L3's words: "Create a machine called Review Nudger: when a pull request has
waited too long for its review or for SAIL, it reminds the reviewer. It should listen for the GitHub
pull request events and the SAIL check results on the bus. Make it a scheduled task for 9am every
day. Then confirm it. I expect SAILED per day ×1.2." The coordinator's words for Q6 (notes 118)
and Q13.
(b) The machine declared (receives heard on the bus), scheduled 09:00, confirmed; `orchestra.prediction.made` from `supervisor`, factor 1.2.
(c) Machines: Review Nudger "declared, never heard". Dynamics: the expected change drawn beside
the model, as a hypothesis.
(d) The answer says the declared 09:00 is not what runs: the program behind it is the
`review_nudger` workflow, run daily at 00:00 UTC and on
request, since no calendar time is supported yet (SPEC §12.1); it asks which time zone the owner
means for a later 09:00 (default Q10: ask, guess none); says each reminder is a comment drafted to
the Outbox that waits for the owner's approval; gives the prediction's id and when it is judged.
(e) 90 s. The SRE answers the zone question: "This machine's clock."
(f) Pass: L3's `check_nudger`; and the answer does not claim the nudger runs at 09:00.

**11. The nudge, and B released.**
(a) The owner: "Remind the reviewer on B's pull request."
(b) The Supervisor calls `request_work` on `review_nudger`, the brief naming B's ticket. The
program `review_nudger/1` finds the item waiting longest at `review` or `sail_check` (past 30
minutes; the one the brief names first) and exits `found`; `remind` drafts a comment on B's pull request
(`live.nudge`, `approval = "always"`). The owner approves it on the Outbox page; the outbox posts
it; `outbox.sent`. The coordinator then releases the hold
(`demo.sh --release-review --dir <run>`); B goes through `review`, `sail`, `sail_check`.
(c) Outbox: the draft waiting, then sent. Machines: `review_nudger/1` beside the declared nudger.
(d) The answer names B's pull request and says the reminder waits for the owner's approval (default for R2's "who should a stale review reach?").
(e) 90 s; the approval as fast as the owner; then three GitHub polls for B.
(f) Pass: one comment on B's real pull request, sent only after the owner's approval; the
Supervisor never claims it was sent before `outbox.sent`.

**12. SAILED, merged, ticket Done, requester told.**
(b) The fake labels A (then B) `SAILED`, squash-merges and deletes the branch; the floor drafts
`live.close_ticket`; the outbox approves it by configuration (the test label) and the script moves
the ticket to Done; `outbox.sent`; the item ends `closed`. `slack_notify` drafts nothing (disabled).
(c) Items: A closed, last step `close_ticket`, outcome shown. Outbox: the close draft, approved by
configuration, sent. Machines: `slack_notify` disabled with its reason.
(e) Two GitHub polls; the close in seconds; the Jira transition seen on the next Jira poll.
(f) Pass: A's pull request merged with `SAIL` and `SAILED`, ticket A Done on the board, and either
a Slack line posted (bot token) or the card's stated reason (done criterion 1).

**13. A second piece of work, from the chat.**
(a) The owner: "Start another delivery: add a line to greeting.txt saying good morning."
(b) `request_work` publishes `item.requested` as `owner`, `via: supervisor`, quoting the message;
`has_ticket` finds none, so `create_ticket` drafts `live.create_ticket` and the outbox (approved by
configuration) opens an "[orchestra live test]" ticket on SCRUM assigned to the owner; then the
floor offers it to a worker and steps 3 to 7 and 12 follow.
(c) Items: the new item at `write`, its brief the owner's sentence, its ticket the one opened.
Outbox: the ticket's draft, approved by configuration, sent.
(d) The answer names the item's id, its Items link, and that `explain_item` follows it.
(e) 90 s, then as step 3.
(f) Pass: one item, its request from `owner`, one new ticket (no second item from that ticket's
assignment); the item ends `closed` with its ticket Done.

**14. An incident.**
PagerDuty is a fake: the kits' FakePagerDuty on this machine, polled every minute by
`pagerduty_fake`, which relays `pagerduty.incident.<status>` as `bot.pagerduty_fake` and
`person.pagerduty_fake.<user>`, announced as fake. It pages no phone.
(a) The harness opens a high-urgency incident on the SAIL runners' service (`PSVC003`):
`demo.sh --incident open --dir <run>`. The owner,
as the on-call begins (Q6, notes 141): "I got a PagerDuty alert. Is my delivery work affected?
What is the impact?"
(b) `pagerduty.incident.triggered`; any SAIL rejection while it is open is triaged
`company_wide` and labelled again; nothing pauses (default for R1's "does an incident pause
deliveries?").
(c) Machines: `bot.pagerduty_fake`, marked fake, acted. Items: any item at `sail`/`sail_check`.
(d) The answer names the incident's id and service, says it is the fake, names the items at SAIL
that a company-wide failure would hold, and does not invent an impact analysis it has no data for
(no SLO or log source is connected).
(e) One PagerDuty poll (1 minute), 90 s for the answer. The harness resolves it after:
`demo.sh --incident resolve --dir <run>`.
(f) Pass: the incident named and called fake; no claim about SLOs or logs; any rejection during it
triaged `company_wide`.

**15. End of the day.**
(a) The owner: "What needs me before I go?"
(d) Every open item and what it waits on; the nudger's question still open.
(f) Pass: as step 8. The run is left going overnight; discovery runs on its schedule.

**16. The morning after.**
(a) Tuesday, the owner opens the Dashboard and says: "What changed since yesterday?"
(c) Dashboard: what needs the owner now. Dynamics: the piles as stocks named for the workflow
and the step (`delivery_live` review waiting, and so on) if discovery found a model; otherwise
"no model yet" and why. The prediction shown waiting, with its judging date.
(d) The answer, in local times: items finished (keys, merged pull requests), the rejection and its
triage, the incident opened and resolved, what the outbox sent, the item started from the chat,
what waits on the owner now, and the prediction's state.
(e) 90 s.
(f) Pass: every one of those, checked against the bus, with none invented; a Dynamics page that
draws no stock must say why.

## Known gaps the script does not pretend are solved

- **The review is a stand-in.** One GitHub account: GitHub refuses an author's approval, so a
  comment review stands in and `review_state = "commented"`.
- **No 09:00 schedule yet.** The nudger runs every 24 hours at 00:00 UTC and on request.
- **Each reminder needs the owner's approval** on the Outbox page (`live.nudge` is `"always"`).
- **Slack is disabled.** The token lacks channel-read permission (an `xoxe.` token); nothing
  posts until an `xoxb-` bot token exists (default Q9: disabled).
- **The Jira poller must not replay Done tickets** (L3 saw it). Step 2 fails if it recurs.
- **The GitHub poller must not replay history** (L3 saw it). Step 3 fails if it recurs.
- **No model within 20 minutes of two tickets.** L3's prediction names an event type, not a flow;
  step 16's stocks rest on the overnight run.
- **The fake CI takes 15 seconds** in a dry run.
- **A request's ticket is left out of the Jira poller's scope** (the label
  `orchestra-live-requested`), so its assignment never starts a second item.
- **No SLO, log or alert source** is connected, so the on-call's impact analysis cannot be done.
- **Polling, not webhooks:** a short job waits up to 25 minutes.

## Evidence

A live run on 2026-11-01 passed for SCRUM-14, SCRUM-15 and SCRUM-16 (pull requests #12, #13 and
#14): one held review, with the 30-minute guard firing once; one forced rejection, triaged `local`
and reworked; 10 Outbox sends. Transcript: `~/orchestra-workflows`,
`examples/delivery_live/transcripts/2026-11-01-outbox/`.
