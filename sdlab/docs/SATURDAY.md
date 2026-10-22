# Saturday morning: the re-scores held back for the weekend

During the week the CPU pool runs only the top-5 climb (kubernetes 300-317, none/counts variants). Every
broad re-run and re-score waits for this run. Agents add to the list below instead of queuing these
themselves. How the backlog machinery works, and what to do when it misbehaves: docs/WEEKEND.md.

## Run it

```sh
cd ~/orchestra/sdlab
git log -1 --oneline sdlab                # the pool runs this commit: make sure it is the newest sdlab
sh scripts/backlog.sh start --all-cores   # 1. queues the kubernetes set first (priority 300), all strategies and variants
                                          # 2. turns the main line on: every other stale result, lowest priority
sh scripts/backlog.sh status              # the workers, the queue, the backlog
```

Then leave it. Re-check with `sh scripts/backlog.sh status` or https://sdlab.dansproject.space/ladder/pool.
When the queue is empty: `sh scripts/backlog.sh refresh` (the daemon also does this hourly).

To give the Mac back to agents afterwards: `sh scripts/backlog.sh start` (14 slots). To stop queuing: `sh scripts/backlog.sh stop`.

## What is waiting, and why

Sizes are from `uv run sdlab-ladder cost ... --stale` on 2026-10-21 (single-worker busy time; the pool has 49
slots with `--all-cores`, so divide by about 30-40 for wall time, with the slow realistic cases as the tail).

| # | what | why it is stale | size | queued by |
|---|---|---|---|---|
| 1 | **Kubernetes, every strategy, every variant** (incl. meas/noise) | the scorer changed twice on 2026-10-21: proven equivalence and "fits" (`aadd1a1`), hidden-stock credit (`198baf2`); plus the strategy fixes from the climb | 3,132 items, 66.5 h | `backlog.sh start` (priority 300) |
| 2 | **Everything else** (Tests, realistic, physics, noisy, canonical, real) | the same two scorer changes, plus the climb's strategy fixes; most items are re-scores of stored models (seconds), the rest re-runs | about 47,200 items, about 47 h | the main line |
|   | total | | 50,340 items, 113 h; about 3-6 h of wall time | |

On 2026-10-21 a kubernetes re-score (jobs 271, 272) was started by mistake during the climb and cancelled; the
about 4,200 results it finished are kept, the rest is item 1.

Items 306-317 allow 900 s each, so the kubernetes set has a long tail (the slowest: 311 counts-long
kalman_lna and engine_forms, 316 counts-long, 310 counts-long milp). Timeouts are recorded as timeouts.

## What to look at when it is done

| question | command or page |
|---|---|
| did anything regress on the rungs the top 5 had passed? | `uv run sdlab-ladder status --strategies combined2,milp,structures,kalman_lna,engine_forms` (the 300-317 rows) |
| what the new scorer flipped (pass, equivalent, fits, fail) | https://sdlab.dansproject.space/ladder?view=cases&set=kubernetes (teal `~` squares are "fits": not a pass) |
| the noise variants of the top 5, never worked on yet | `uv run sdlab-ladder diff 306,307,308,309,310 --summary --strategies roster:kubernetes --variants meas-short,meas-long` |
| the other strategies, for porting fixes (docs/research/fix-ledger.md) | https://sdlab.dansproject.space/ladder/leaderboard |

## Added during the week

Agents append rows here (what, why, the command if it is not covered by `backlog.sh start`, the cost
estimate) instead of submitting broad jobs to the pool.

- (none yet)
