# The Workflows run, 2026-11-01: report

The unattended run of [GOAL-2026-11-01-workflows.md](../roadmap/GOAL-2026-11-01-workflows.md),
run by [COORDINATOR.md](../roadmap/COORDINATOR.md). It started at 2026-11-01T04:41Z; this report
was written at about 11:10Z. The goal document's progress log is the source of truth; its
times before the 06:12Z correction are wrong.

In short: the four proposals are reviewed and on `main`. The core has the intended model and the
Dynamics and Machines pages in the mocked states. The Supervisor has its design tools, the
integration flow and the floor, and the owner's scenario passed live on Haiku (A3b). The Workflows
plugin is a new private repository with the record, piles, the floor, definitions, pages, the task
loop and seven examples. The integration kits, four example pollers and `docs/INTEGRATING.md` are
done and passed a stranger test.

## 1. What was built, and where

**Core, `~/orchestra_2`** (GitHub danroblewis/orchestra). `main` is pushed at `0320aecf` (code at `0d975c8c`),
with the UX review's three rounds and the refinement-marks fix. It holds
the intended model in `orchestra/sd/intended/` (declared stocks, effects,
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
on :8096. It runs the agents' demo with `--dummy` from worktrees on branch `demo-live` (core
`~/orchestra-wt/demo`, agents `~/orchestra-agents-wt-demo`); it was restarted on core `0d975c8c`
at about 12:00Z. The login link is in `~/orchestra-live-demo/LOGIN.txt`.

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
  ..., verdicts and targets skip those parts, and they disappear when the
  instrument expires". Reason: you wanted placeholders to exercise the rest.
- "Draft options use a core `draft`+`expires` instrument flag (discovery leaves them out)".
- "P3's Items/Piles/Workflows pages kept as the plugin's own read-only views (owner to confirm)".
- "The first machine draft is event-driven, the owner's message makes it daily"; "the '+ flow'
  rows keep expect/ignore".
- P3 deferred checkpoints and archive, lifecycle 2 to 3, DST, adoption, and a program host beyond
  a command. Reason: scope. They are designed, not built.
- "Keep Features as the narrative"; A3 and the demo use notes files from `repo_stats` and a
  machine that adds files, so the prediction is judged within the run. Reason: your remark.
- "A polling relay publishes as the actor (person.<system>.<account> / bot.<system>), never as
  itself (D19)"; bridges are checked before writing a poller.
- "Nothing scheduled before approval" (I3); "a model-acceptance case must use a detached clone".

P6 recorded them in `docs/roadmap/decisions.md`.

## 4. How to run each thing

**The live demo.** `~/orchestra-live-demo/restart.sh` stops what it started, syncs both
`demo-live` worktrees, starts the demo with `--dummy` on `PORT` (default 8096), re-adds the
tickets and re-seeds the declared layer. Log in with the link in `LOGIN.txt` beside it.

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
| core | `0d975c8c` | unit 948 passed, rc=0; screenshots 6 passed |
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

- **UC-1 (bakery): 9/10 on core `b59f7ad1`, still not a pass.** The first attempt never ran (the
  harness cut it at 2.5 minutes; a linked worktree shares the main checkout's state). A clone then
  scored 6/10, with two counter-merge bugs in discovery. The restate fix (`94e3f774`, `befc2638`,
  one refuter round) keeps a stock's own writer's counters after a merge, and stops a merge when a
  measured level is exactly one counter minus the other and moves a whole unit where they differ.
  The re-score (60 min, kalman_lna at 30 s) now finds customers waiting, inspecting to on shelf,
  on shelf, and a lease-expired flow baking to waiting. No regressions: six exact stocks, 16 flows,
  every origin fitted. The one miss: the rating is read by assigned, not by placed.
- **UC-2 (tasking programs): 6/10, fails.** Short windows: levels that never change within a 5 s
  step. Nothing spurious.
- **UC-3 (agents and a program): 4/10, fails.** Short windows, and one spurious stock balanced by
  a ticket flow, fixed by the second of two discovery fixes merged with C5.

The working files are in the session scratchpad, which may not
persist.

<!-- PENDING: UC-2 and UC-3 re-scores against core main -->
Pending at the time of writing: the UC-2 and UC-3 re-scores against core `main`.

## 7. Live model spend

A3 $6.33 (Haiku with Sonnet fallback turns), A3b $0.19, I3 about $0.13. Total about $6.65,
approximate, well under the $30 cap.

## 8. Open findings and follow-ups

**Core.**
- The loop finder sees no cycle when a turn's end is fitted on the oldest item's age (W6).
- The event map overflows about 10 px at 390 px width.
- Fixed: the Machines page now marks every edit of a refinement, not the last (`b8847702`).
- D3's screenshot 503 is the simulate endpoint without numpy/scipy: sync worktrees with
  `--extra sd` too (now in COORDINATOR.md, which also forbids syncing your main checkout).
- A heard declared machine drew dashed (I4); check it after C9.
- "Whoever acts next" hand-offs draw coordinator to `bot.triage` via `attention.needed` (X34).
- `find_repo_root` resolves linked worktrees to the main repository; `use-cases.md` "Adding a
  case" should say to use a clone.
- `~/.orchestrator/projects.json` still lists the removed clone `~/orchestra-bakery-clone-UC1`.
- C6 (file-bus rotation) is not built.
- UX review (C5's gate): two rounds (4 personas, 136 findings in round 1) and a third
  that found the final list already done. It changed drawers, honest liveness and counts, the
  declared layer's wording, keyboard and focus, the phone layout, and fits that show what they
  leave out. Quiet machines show counts, not rates. Round 3 fixed "Left out all 86" beside a
  10-stock model and two screenshot tests (merged as `0d975c8c`). Dropped as matching the approved
  design: "declared by you", the "100%?" labels, the stock level's type size, and the colours,
  which are yours to choose.

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
