# 317 (k8s-mesh-of-three), kalman_lna, round 1 (2026-10-22, agent kalman317)

**Status: kalman_lna does not pass 317. No variant passes.** One fix was kept (9d3ca8e). It takes 317 none-short from
17/76 to 38/76 parts in a local trace. Pool job 371 (9d3ca8e, all four variants) is **queued, not run**: the pool was
busy with the 20-item top-5 317 refresh (job 360, about 570 min left when I submitted). Its numbers are not here.
Follow it with `uv run sdlab-ladder job 371 --wait`.

| variant | achievable? (`analyse`) | before: pool job 365 at 64b5f36 | after (9d3ca8e) |
|---|---|---|---|
| none-short | yes ("hidden stock without noise: exact if identifiable") | FAIL 17/76, 913 s | **38/76 in a local trace** (rows stage on the cached pre-rows answer); job 371 not run |
| none-long | yes (same note) | FAIL 17/76, 1211 s (limit 1800) | 17/76 in a local trace (unchanged); job 371 not run |
| counts-short | not analysed ("a truth this analysis does not cover") | ERROR: numba `SystemError` in `oefit._sens`, which is the runner's SIGALRM landing inside numba, so in effect a timeout | not traced (the pre-rows stage ran for more than 60 min locally); job 371 not run |
| counts-long | not analysed (same note) | TIMEOUT (1800 s) | not traced (same); job 371 not run |

Commands (2026-10-22): `uv run sdlab-ladder analyse 317-k8s-mesh-of-three --variant V`; `uv run sdlab-ladder show|diff
317-k8s-mesh-of-three --strategy kalman_lna --variant V` (job 365's rows); `uv run sdlab-ladder job 365` ("4 done in
1998.5 s: 2 fail, 1 error, 1 timeout"). The local traces ran single-threaded at nice 19 on the Mac. One script cached
the answer before `rows.revise` (`_capmin.offer`, `_identify_linear`, `oefit.refit`, `_capmin.restore`), then ran
`rows.revise` and `tracker.revise` and scored the result with `score.score` and `diff_report`. The script is not
committed; it is in the session scratchpad as `trace.py`. The pre-rows stage took 299 s on none-short and 604 s on
none-long.

## Diagnosis (rule 4b)

- **The rows pass ran out of time before it read most rows. This was a method fault (a budget), not a data limit.**
  `rows.revise` reads every stock's row one at a time. For a row that misses and has an inflow side, it also tries a
  schedule, a hidden integrator and the 312 delayed inflow (`delayed.fit`). On 317 the delay fit alone took about 100
  s a row: it searches subsets of about 40 columns, where 312 has about 12. By catalog_mem, the 16th stock of 36, the
  600 s `TIME` was gone. The pass then returned the answer unchanged (`if time.monotonic() > deadline: return
  result`). That answer, from the Kalman search and oefit, has 17/76 parts. It has the queues, retries, errors and
  counters wrong, such as `catalog_retries -> outside 0.000001` and `+ catalog_queue -> cart_responses_total`, which
  a noise-free one-step row reads exactly.
- **After the fix, none-short.** The plain rows take 78 s. The rebuild then reads every queue, retry, response and
  error flow, the CPU rows and the calls. What is still missing (17 removed, 4 added):
  - each service's pod gap `desired - pending - ready` and delete `ready - desired`;
  - the OOM kill move with its effect table, and the leak (the hidden stock);
  - the mem drain, `0.164` against the true 0.5, because the leak is missing;
  - the autoscaler's delayed `provisioned` stage;
  - db_waiting's two query links.
  The first derived round found the OOM switch, `frontend_ready * max(0, frontend_mem - 480.00003)`, but it took 282
  s. That is past the rounds' share, so the round was undone. **Another method fault (time):** each derived round runs
  `_derived.search`, `_ratio_hidden` and `_capped` over 36 stocks. `_capped` judges 4 caps by refitting rows. 317
  needs about 10 such columns: 3 OOM switches, 3 per-pod memory ratios, 3 capped pod starts and the db cap.
- **none-long: the rows are right, but the rebuild drops them.** The plain rows take 396 s, and the derived rounds get
  no time. The rows do read the flows exactly. For example, `frontend_retries` reads `0.08 queue - 1.0 retries` with
  sse 1.7e-6, and its BIC is -38466 against the answer's -21117. But `_build` marks 20 of the 33 winning stocks
  "bad": they need a side the boundary lacks, even after `REPAIRS` = 3 rounds of refitting without those links. So
  only mem, nodes and a counter are rebuilt. I did not diagnose this further. Two places to look first: the repair
  rounds, which may not settle on a 36-stock mesh, and frontend_queue and frontend_inflight reading capmin's offered
  `MIN(frontend_queue, 103 catalog_ready)` (the wrong service's pods, collinear on this run).
- **counts-short and counts-long: the pre-rows stage overruns 1800 s.** This is the Kalman search plus oefit. In job
  365, counts-short died inside `oefit._sens` when the alarm fired, and counts-long timed out. Not worked on.
- **Not representable yet:** the pod start `min(0.5 p, max(0, 4 nodes - sum ready) * p / max(1, sum pending))`
  shares the room by the pending counts. rows' capped move reads `min(a X, max(0, B . z))` with up to 2 room
  readers. It has no share factor and cannot read a sum of 3 ready counts with one number. Even with time, the three
  `*_started` flows would be at best "fits".

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| **staged row budget** (new; type 10, a budget) | `rows.revise` reads every stock's **plain** row first (sparse linear, or linear plus one floored term). It then runs the derived-column rounds on those rows. They may use `TIME x (1 - RICH_SHARE)`. Last come the **richer** forms (schedule, hidden integrator, delayed inflow). They run only for rows above rounding with an inflow side, the worst-fitted first. The delay fit gets an even slice of what is left, at least `RICH_SLICE` = 20 s. `row(..., rich=)` and a `rich_ok` set gate the costly forms. Before, one slow form on the first rows starved the rest, and nothing was rebuilt. On 317 none-short: plain rows 78 s, 17 -> 38/76. | 9d3ca8e | Any per-row or per-stock search with a global wall clock (combined2 `hinge.py`, structures `floor.py`, milp `hinge.refine`/`effects`, engine_forms `reread.py`). Split it into a cheap pass over every stock, then the expensive forms by misfit with a per-item slice. A clock that runs out then costs only the expensive forms of the last items, never the cheap reading of all of them. |
| **derived columns scale with the model** (new) | `ROUNDS` switch or ratio columns and one capped move **for every 12 stocks**: `per = max(1, len(ids) // 12)`. A model of up to 23 stocks keeps 3 + 1, so 308-316 are unchanged. 317 (36 stocks) may take 9 + 3. On 317 the time limit still allows only about 1 round, so no part is counted to this yet. | 9d3ca8e | Wherever a strategy caps its number of nonlinear candidates or rounds by a constant (milp `effects.py`, combined2 `counted.py`, structures `counted.py`), scale the cap with the number of stocks, or let the BIC gate alone stop the search. |

Checks: `uv run pytest tests/test_kalman_lna_rows.py tests/test_kalman_lna_delayed.py tests/test_kalman_lna_derived.py
tests/test_kalman_lna_capped.py tests/test_kalman_lna_crossunit.py tests/test_isolation.py` (15 pass). For a regression
spot check I used `uv run sdlab-ladder run --strategies kalman_lna --cases 310-k8s-memory-oom,312-k8s-cluster-autoscaler
--variants none-short --local` ("2 pass", 23 s and 49 s). It used `--local` because the pool queue was hours deep (2.6
CPU-minutes, logged to `~/.sdlab/local-runs.log`).

Tried and not kept: refitting only the misfit rows after each derived column, in place of all rows. It saved no
measurable time: the round's cost is the candidate search itself, 282 s either way. It is reverted.

## What 317 needs next (for the next round, in order)

1. **Rebuild repair on a large mesh** (none-long): find why `_build` leaves 20 of 33 winning stocks "bad". Then let
   the rebuild keep the good stocks of a connected set rather than shrinking B by every bad stock.
2. **Derived-round speed**: score the `_capped` candidates only for pairs whose rows both miss and share a unit or a
   declared forced move, and memoise `_ratio_hidden`'s scan across rounds. Then the ~10 derived columns 317 needs
   fit in the budget.
3. **Pre-rows time on counts**: the Kalman search plus oefit overrun 1800 s. Give oefit a wall clock read from the
   runner's alarm (`deadline.outer_left`, already vendored) so the rows stage always gets its share.
4. **Shared-room pod start**: a cap column with a share factor, `min(a P, max(0, B . z) x P / max(1, sum P_i))`,
   where B . z may read a sum of same-unit stocks.

## Risks

- No regression run on earlier rungs (the plan: once, later). The staged budget changes the order of work on every
  case. Derived rounds now see plain rows only, not rows already carrying a schedule or integrator. 310 and 312
  none-short still pass locally. A case whose delay or integrator row used to shape the derived search may differ.
- none-long's discovery took 1211 s at 64b5f36 against the 1800 s limit. node2 is slower, so job 371 there may time
  out.
