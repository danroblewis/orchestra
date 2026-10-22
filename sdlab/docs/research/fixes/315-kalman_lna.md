# 315 (k8s-fan-out), kalman_lna, round 1 (2026-10-22, agent kalman-315-r1)

**Status: kalman_lna passes all four plan variants of 315 with no change to its code.** No fix was made or needed.

| variant | achievable? (`analyse`) | store at 20ed81c | confirm: pool job 338 at 20ed81c |
|---|---|---|---|
| none-short | yes (p 1.00) | PASS 12/12, complexity 25 = truth (#387104) | **PASS** |
| none-long | yes (p 1.00) | PASS 12/12, complexity 25 = truth (#387113) | **PASS** (114.6 s, mac) |
| counts-short | yes (p 1.00) | PASS 12/12, complexity 28 vs 25 (#387103) | **PASS** |
| counts-long | yes (p 1.00) | PASS 12/12, complexity 27 vs 25 (#387111) | **PASS** (110.3 s, mac) |

Commands (2026-10-22): `uv run sdlab-ladder analyse 315-k8s-fan-out --variant V` (all four achievable, every scored
part p 1.000); `uv run sdlab-ladder show 315-k8s-fan-out --strategy kalman_lna`; `uv run sdlab-ladder diff
315-k8s-fan-out --strategy kalman_lna --variant V` ("none" for the counts variants); `uv run sdlab-ladder submit
--strategies kalman_lna --cases 315-k8s-fan-out --variants none-short,none-long,counts-short,counts-long --priority 400
--by kalman-315-r1` (job 338), then `uv run sdlab-ladder job 338 --wait` ("4 done in 115.1 s: 4 pass").

Found model (none variants): the truth's twelve flows exactly. The fan-out is two links from `frontend_inflight`, one
into `catalog_queue` (0.3) and one into `cart_queue` (0.15), each on its queue's declared `estimate` side, and no link
between catalog and cart although they are nearly collinear on this run (`analyse` lists `cart_queue ~ catalog_queue`).
The declared-boundary handling (fix-ledger type 0) again keeps each link a link, as on 313 and 314.

## Fixes kept

None.

## Residue (passes, but not the simplest model)

Counting noise adds small extra terms, the same residue as 314's counts-long:
- counts-short: a move `frontend_inflight -> catalog_queue = 0.0021 x frontend_inflight` beside the link (0.2907
  instead of 0.3) and a second term `0.0147 x traffic` on that link (complexity 28 vs 25).
- counts-long: a move `cart_queue -> frontend_queue = 0.0101 x cart_queue` (complexity 27 vs 25).

Every scored part is within tolerance, so these are passes, but the extras cost complexity (rule 7). The general fix
proposed on 314 (a pruning test that drops a term whose error reduction is no larger than the noise's expected share:
an F-test or held-out check on the one-step rows) would remove them. Deferred with the noise round.
