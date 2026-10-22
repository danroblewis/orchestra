# 311 (k8s-node-pool): kalman_lna, round 2 check (2026-10-22, agent kalman_lna-311-r2)

**Status: kalman_lna passes every achievable variant of 311. No code change was needed this round; no fix was added.**
none-short and none-long PASS 26/26 at 082119d (pool job 300). counts-short and counts-long fail and are data-limited
on the OOM move, so they are not targets. The rung passes for kalman_lna.

## What I checked (commands rerunnable at HEAD c7352bb)

- `uv run sdlab-ladder show 311-k8s-node-pool --strategy kalman_lna --variant V` and
  `uv run sdlab-ladder diff 311-k8s-node-pool --strategy kalman_lna --variant V`:

  | variant | achievable? | result (code 082119d, job 300) | diff |
  |---|---|---|---|
  | none-short | yes | **PASS 26/26** (#386960) | none (28 unchanged) |
  | none-long | yes | **PASS 26/26** (#386962) | none (28 unchanged) |
  | counts-short | no: data-limited | FAIL 5/23 (#386961) | 4 removed, 5 added, 4 values wrong |
  | counts-long | no: data-limited | FAIL 17/23 (#386963) | 1 added, 2 values wrong, all in the OOM sub-model |

- The results are current: `runner.plan(['311-k8s-node-pool'], select_strategies('kalman_lna'), [the four variants],
  every_variant=True)` returns no items, so the case, strategy and score hashes all equal the stored rows'. 082119d is
  the last commit that touches `sdlab/discovery/strategies/kalman_lna`. Five commits came after it. None of them
  touches kalman_lna or a score hash: afb19cf (combined2), and four docs commits.
- `uv run sdlab-ladder analyse 311-k8s-node-pool --variant V` says "not analysed: a truth this analysis does not
  cover" for all four variants. So I judged the counts variants against the measured bound in `311-combined2.md`. The
  truth's OOM move, refitted by free-knot Poisson ML, is 15.4% off on counts-short and 17.2% off on counts-long. With
  the truth's own knots it is 16.4% and 6.5% off, and no method is given those knots. The tolerance is 10%, and no
  standard-error allowance is added. `311-milp.md` gets the same result with its kill-rate bound (P 0.25 / 0.36).
  Neither counts variant is a target.
- counts-long fails only in that sub-model. The OOM move is 20% off with a 2-point table, and mem's drain is
  0.0118 x mem + 127.6. That drain comes after the kill table, as on 310.

## Fixes

None new. The fixes that make 311 pass are recorded in `311-kalman_lna.md` (commit 082119d): capped move, hinge
reread, integrator threshold, weighted threshold refit, duplicate-switch guard, and budget. Each entry says how another
strategy can adopt it.

## Risks and not done

- **counts-short has a breakdown outside the OOM part** (not a target, but a robustness flag for the noise round).
  pending's creation is fitted as -1.5e12 x pending, and the row is balanced by -3.7e12 x oom_kills_total on mem and
  -3.1e11 x traffic on ready. These are huge cancelling coefficients on nearly collinear columns. As a result,
  `ready -> outside` (the floored deletion) and `outside -> cpu` are lost, and `desired <-> ready` links are invented.
  It looks like a missing guard on coefficient size or the condition number in rows.py's refits. A general guard
  would be: reject a refit whose coefficients exceed a multiple of the row's scale, or ridge-stabilise it. That belongs
  to the noise-variant round (deferred by the standing decisions). I did not change it here.
- No pool job this round: nothing was stale and no code changed, so a re-run would reproduce job 300's cells.
- Regression on earlier rungs is still untested (the plan: once, later).
