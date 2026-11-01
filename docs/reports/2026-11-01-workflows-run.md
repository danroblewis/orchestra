# The Workflows run, 2026-11-01: report

The unattended run of [GOAL-2026-11-01-workflows.md](../roadmap/GOAL-2026-11-01-workflows.md),
run by [COORDINATOR.md](../roadmap/COORDINATOR.md). It started at 2026-11-01T04:41Z; this report
was written at about 11:10Z. The progress log in the goal document is the source of truth. Its
times stamped before the 06:12Z correction are wrong (section 9).

In short: the four proposals are reviewed and on `main`. The core has the intended model and the
Dynamics and Machines pages in the mocked states. The Supervisor has its design tools, the
integration flow and the floor, and the owner's scenario passed live on Haiku (A3b). The Workflows
plugin is a new private repository with the record, piles, the floor, definitions, pages, the task
loop and seven examples. The integration kits, four example pollers and `docs/INTEGRATING.md` are
done and passed a stranger test.

## 1. What was built, and where

**Core, `~/orchestra_2`** (GitHub danroblewis/orchestra). `main` is `c92d02fc` "Goal log: deflake
merged; report draft dispatched", 4 goal-log commits ahead of origin; the code is pushed up to
`b59f7ad1`. It holds the intended model in `orchestra/sd/intended/` (declared stocks, effects,
targets, machines and events, the expected set, three states, version diffs, provenance), the
Dynamics states D1 to D3, the Machines states E1 to E4, instruments on declared machines, collector
provenance and `pile` as a construction place, two rounds of discovery fixes, the four proposals
under `docs/proposals/`, `docs/INTEGRATING.md`, and UC-7..13, G17..G22 and D22..D40 in
`docs/roadmap/`. Rules 2 to 7 and 9 of `AGENTS.md` were amended in the proposals' wording.

**Agents, `~/orchestra-agents`.** `main` is `30a84fe`, the merge of A3b (`744ab7f`), pushed. New: the design tools, prompts and guide, the block on workers pushing or
merging, the host answering floor offers, `integrate_system` and `approve_integration`, the
workflow tools, the live scenario test, and the H1, H4 and H7 fixes.

**Workflows, `~/orchestra-workflows`** (new, private, https://github.com/danroblewis/orchestra-workflows).
`main` is `0851c41` "e2e: read the floor's state only once it has folded the bus; the first claim
is the holder", pushed. M4 and M5 are complete.

**Bridges, `~/orchestra-bridges`.** `main` is `44cb8f3` "Merge branch 'I5'", pushed. Kits in
`orchestra_bridges/kits/`, four example machines in `examples/integrations/`.

**Live demo, `~/orchestra-live-demo`** (not a git repository), behind orchestra.dansproject.space
on :8096. It runs the agents' demo with `--dummy` from two worktrees on branch `demo-live`: core
`~/orchestra-wt/demo` (`ab0cacaf`, with the UX review's round-1 fixes, not yet on `main`) and agents
`~/orchestra-agents-wt-demo` (`34e6823`). The login link is in `~/orchestra-live-demo/LOGIN.txt`.

<!-- PENDING: final core main commit and the push of its log commits -->
Pending at the time of writing: the push of the core's goal-log commits.

## 2. Status per task

| id | status | from the log |
|---|---|---|
| H1 | done | three agents failures fixed; target files 3× rc=0 |
| H2 | done | core starts without `[sd]` |
| H3 | done | core tests used a key the desk never had |
| H4 | done | `check_setup` calls `Plugin.check` |
| H5 | done | `ruff check` clean; no mass reformat |
| H6 | done with caveats | 17 worktrees removed; this run's own remain (section 8) |
| H7 | done | the agents host stops with its parent |
| P2 to P5 | done | the four proposals, panels to zero blocking |
| P6 | done | use cases, goals, decision rows |
| M1-mock | done | frames aligned; E4 added |
| C1 | done | layered review, 3 fix rounds |
| C2, C3 | done | D1 to D3 and E1 to E4 render from real page code |
| C4 | done | measured instances, `[intended] max_instances=50` |
| C5 | done with caveats | subtraction audit applied; UC-1..3 fail (section 6) |
| C6 | not done | file-bus rotation, "later, if time"; never dispatched |
| C7, C8 | done | collector provenance; API fields for A1 |
| C9 | done | the map draws only observed hand-offs |
| A1, A2 | done | design tools; prompts and guide |
| A3 | done with caveats | test written; no live run passed every turn |
| A3b | done | after fixes, one Haiku run passed all five turns for $0.19 |
| A5 | done with caveats | full-path `gh` or a pushurl still gets through |
| A6 | done | the host claims and finishes floor offers |
| W1 to W5 | done | skeleton, record, piles, floor, definitions |
| W6 | done with caveats | piles and flows found; loops short of UC-2's bar |
| W7 | done | pages and the Supervisor's workflow tools |
| X1 to X7 | done with caveats | all seven examples; vocabulary gaps; staged rollout's rollback loop not found |
| I1 | done | stranger test passed in 9 minutes |
| I2, I4, I5 | done | kits, four pollers, pointers |
| I3 | done | fake e2e and a live Haiku run passed |


## 3. Decisions made for the owner

From the goal document:

1. **Page controls and rule 9.** Expect, unexpect, ignore, and confirm/discard on a stock, effect
   or flow are observations recorded with provenance. The panel narrowed it: a machine's confirm,
   discard and kind switch are requests (`orchestra.intent.requested`) the Supervisor acts on. To
   reverse: route every click through the Supervisor (P2 notes it).
2. **"How to measure it"** comes from the Supervisor; the core proposes nothing.
3. **The intended model** is a declared layer (`dN`) in the model store, never in `orchestra.toml`.
4. **Live spend:** Haiku, under $30. A3 used Sonnet as its fallback, as P4's judge allowed.
5. **Pushing** every repository, the public core too, after green suites and a zero scan. Note:
   orchestra-desk is public on GitHub, though this decision calls it private.
6. **The new repository** is private.
7. **Tasking** is unchanged.

Added in the run, in the log's words where it gives them:

- No mass `ruff format` (H5): 265 files would change. Reversible by one commit.
- "The Dynamics page keeps working with an `sd_missing` note, not a 503" (H2).
- "The core must not learn machine-kind vocabulary (store an opaque spec; rule 2's kinds only)".
- "Dispatch stays `coordinator/dispatch` (D17)"; pile balances are by construction.
- The Supervisor writes to the state directory or overlay, never the base branch; unchosen options
  go to a draft namespace; data-class checks; A3 narrowed to D1+E2 with a Sonnet fallback.
- Simulated placeholders: "discovery reads them, every part fitted from them is marked `simulated`
  in the saved version, verdicts and targets skip those parts, and they disappear when the
  instrument expires". Reason: you wanted placeholders to exercise the rest.
- "Draft options use a core `draft`+`expires` instrument flag (discovery leaves them out)".
- "P3's Items/Piles/Workflows pages kept as the plugin's own read-only views (owner to confirm)".
- "The first machine draft is event-driven, the owner's message makes it daily"; "the '+ flow'
  rows keep expect/ignore".
- P3 deferred checkpoints and archive, lifecycle 2 to 3, DST, adoption, and a program host beyond
  a command. Reason: scope. They are designed, not built.
- "Keep Features as the narrative"; A3 and the demo use notes files from `repo_stats` and a
  machine that adds files, so the prediction is judged within the run. Reason: your remark that
  Features may be hard to test.
- "A polling relay publishes as the actor (person.<system>.<account> / bot.<system>), never as
  itself (D19)"; examples write to the overlay; bridges are checked before writing a poller.
- "Nothing scheduled before approval" (I3).
- "A model-acceptance case must use a detached clone, not a worktree".

P6 recorded them in `docs/roadmap/decisions.md`.

## 4. How to run each thing

**The live demo.** `~/orchestra-live-demo/restart.sh` stops what it started, syncs both
`demo-live` worktrees, starts the demo with `--dummy` on `PORT` (default 8096), re-adds the
tickets and re-seeds the declared layer. Log in with the link in `LOGIN.txt` beside it.
`start-copy.sh` and `stop-copy.sh` run private copies.

**The Supervisor design scenario.** In `~/orchestra-agents`, run
`ORCHESTRA_LIVE_DESIGN=rehearse uv run python -m pytest tests/live/test_design_live.py` for a free
run with no model. `ORCHESTRA_LIVE_DESIGN=1` runs it on Haiku; it needs a logged-in `claude`,
costs money, warms the demo for about 7 minutes and stops at its cap.

**The plugin examples.** Each folder in `~/orchestra-workflows/examples/` (task_loop,
delivery_sail, team_review, on_call, rc_verification, hotfix_branches, staged_rollout,
customer_deployments) has a `demo.sh` and a `README.md`. `examples/task_loop/demo.sh` starts a
fresh target and Orchestra on the first free port above 8100, prints a login link and stops on
Ctrl-C. Each README says what to look at.

**Integrations.** `~/orchestra_2/docs/INTEGRATING.md` is for your work coding tool with no other
context. In `~/orchestra-bridges`, `orchestra bridges scaffold` writes a machine from a kit and
`orchestra bridges integrations` lists the kits. The Supervisor's route is `integrate_system`,
then `approve_integration`.

**Review workflows.** `.claude/workflows/` in the core: `layered-review`, `model-acceptance`,
`ux-review`, `subtraction-audit`, `release-gate` (see `docs/roadmap/reviews.md`).

## 5. Suite results

The last green run per repository, as logged. `ruff check` was clean at every push.

| Repository | Commit | Result |
|---|---|---|
| core | `b59f7ad1` | unit 936 passed, rc=0 |
| core | `513a998d` | unit+metrics+sources 1079 passed, 25 skipped, rc=0 |
| agents | `30a84fe` | unit 533 passed, 1 skipped, rc=0 |
| agents | `80c115c` | full suite 408 passed, 2 skipped, rc=0, 19m44s |
| workflows | `0851c41` | 352 passed, rc=0 |
| bridges | `a89ea49` | 308 passed, rc=0 |

Known flaky until `0851c41`: two plugin floor e2e tests failed under load. Both were test bugs:
a `caught_up(floor)` helper now waits for the floor's offset to reach the end of the bus, and the
workflow test keeps the first claim per offer. Proven 20/20 under 8-suite load; floor code unchanged.

## 6. Model acceptance

Run on the C5 core, ten checks per use case.

- **UC-1 (bakery): 6/10, fails.** The first attempt never ran: the harness cut it at 2.5 of 60
  minutes, and a linked worktree shares the main checkout's state. The re-run on a clone scored 6/10
  again. Its earlier misses were fixed; two new misses were counter-merge bugs in discovery
  (customers waiting merged into the board's counters, inspections passed merged into picked up),
  fixed in `b59f7ad1` after a refuter's round. Still missing for lack of data: on-shelf changed only
  4 times, the rating is read by no flow (the D15 naming gap), and no lease expired in the window.
- **UC-2 (tasking programs): 6/10, fails.** Short windows: levels that never change within a 5 s
  step. Nothing spurious.
- **UC-3 (agents and a program): 4/10, fails.** Short windows, and one spurious stock balanced by
  a ticket flow, fixed by the second of two discovery fixes merged with C5.

The judges saw no regression from M2. Tasking's `create_ticket`
now requires a `milestone_id`. The working files are in the session scratchpad, which may not
persist.

<!-- PENDING: UC-1 re-score against core b59f7ad1 (score, remaining misses) -->
Pending at the time of writing: the UC-1 re-score against core `b59f7ad1`.

## 7. Live model spend

A3 $6.33 (Haiku with Sonnet fallback turns), A3b $0.19, I3 about $0.13. Total about $6.65,
approximate, well under the $30 cap. The UX personas used the `--dummy` demo.

## 8. Open findings and follow-ups

**Core.**
- The loop finder sees no cycle when a turn's end is fitted on the oldest item's age (W6).
- The event map overflows about 10 px at 390 px width.
- The Machines page marks only a refinement's last edit, so receives removed in the same
  refinement never show as removed. A fix is in progress on branch `refine-marks`.

<!-- PENDING: refine-marks outcome (the Machines page's refinement marks) -->
- A heard declared machine drew dashed under C3's styling (I4); check it after C9.
- "Whoever acts next" hand-offs draw coordinator to `bot.triage` via `attention.needed` (X34).
- `find_repo_root` resolves linked worktrees to the main repository; `use-cases.md` "Adding a
  case" should say to use a clone.
- `~/.orchestrator/projects.json` still lists the removed clone `~/orchestra-bakery-clone-UC1`.
- C6 (file-bus rotation) is not built.
- The UX round-1 fixes (`ab0cacaf`) are only on `demo-live`.

<!-- PENDING: UX review of the core pages (branch demo-live, round 2): findings and what was merged -->
Pending at the time of writing: the UX review of the core pages, round 2, on branch `demo-live`.

**Agents.**
- A3's failures (Haiku failed turns 1, 4, 6; Sonnet turn 1 twice: unoffered `repo_files`, events
  in the wrong field, a 360k-character `read_events`, no `link`, a level named as a flow,
  `add_duty`, UTC) were fixed in A3b: `propose_measurements` needs `list_metrics` first; events go
  in `receives` and must be heard or announced; `read_events` returns the newest 20 (at most 100)
  with counts; the Supervisor links the declared stock itself; effects and confirm accept only
  model flows; no time zone is guessed; a loop is a machine, not a duty.
- Still seen on Haiku in A3b: turn 1 declared an extra machine; it refused to link `repo_files`
  (it counts every tracked file, not notes files) and recorded its own instrument; turn 5's
  scheduling removed all the receives (the tool now warns); transcript redaction's email pattern
  turns flow ids containing `@` into `[email]`.
- A5's block is bypassed by a full-path `gh` or an explicit pushurl.

**Workflows.**
- Vocabulary gaps: data-field start filters, distinct reviewers, owner-only person steps,
  wait-then-retry, one step by two machines, an outcome straight to attention, fan-in steps needing
  a who, a program not told its step, related non-child items, person offers.
- The floor announces `coordinator/dispatch` even when a definition names another planner.
- A pass-on is withdrawn for capacity after its claim.
- `examples/demo_kit.py` and `examples/common.py` duplicate each other.
- `examples/task_loop/README.md` still describes the type-based map edge C9 removed.

**Bridges.** INTEGRATING.md's 60 s future-timestamp refusal comes from the stranger test and was
not re-verified.

**Tasking.** The scheduler has the parent leak H7 fixed in the agents host: after SIGKILL of
`orchestra run` it is reparented to pid 1. Not fixed; tasking is the prototype.

**Housekeeping.** Worktrees left: core `~/orchestra-wt/C1`, `C2`, `demo`; agents
`~/orchestra-agents-wt-A3`, `-A3b`, `-C5`, `-demo`; workflows `~/orchestra-workflows-wt-fix`,
`-wt-X34`; the clone `~/orchestra-bakery-clone-UC1b`. Keep both `demo` worktrees.

## 9. What the coordinator got wrong

- **It pushed a red suite.** The plugin's `main` went out at `063f5ef` with 2 failing tests. The
  background suite command echoed `tail`'s exit code, not pytest's. A fix agent repaired it
  (`bf6ecd7`, pushed after 331 passed). Since then the rc is read without a pipe.
- **It guessed the time.** Log lines stamped 05:40Z to 15:45Z were estimates, not the clock. The
  real start was 04:41Z and the correction came at 06:12Z. Those lines are in order but their
  times are wrong.
- **Your venv may have lost its plugins.** A `uv sync` may have removed the plugins from the venv
  that serves :8040. `~/orchestra_2/.venv` now holds only the core. Check that server and
  reinstall the plugins if they are missing.
- **A suite ran on a moving worktree.** The restate refuter checked out `main`'s two files in the
  restate worktree while the coordinator's suite ran there. That run was thrown away and the suite
  re-run on the fixed branch.
