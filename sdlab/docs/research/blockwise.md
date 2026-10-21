# blockwise: discovery that scales to the Kubernetes models

**Status:** done (ladder, commit ea82c31; numbers from `uv run sdlab-ladder run --strategies blockwise --cases sd-k8s-small,sd-k8s-platform --jobs 1`, 2026-10-19, read from the store).
**Asked by:** the user (an SRE), for Kubernetes data ([k8s-model.md](k8s-model.md)): on sd-k8s-platform (227 measured stocks) every leader returned nothing or timed out.

## What it does (`sdlab/discovery/strategies/blockwise/`)

1. **Sums once** (`gram.py`). Every row's regression (a stock's change on the levels and inputs at the start of the step) shares the same columns, so `X X'`, `X dy'` and cumulative sums are computed once, on columns scaled to unit spread. An outside inflow in pieces is taken out with a correction from the pieces' sums, so no row touches the T-long series again. Stepwise BIC scores every candidate column with one matrix product (the Schur complement). While a row's own level is out, it is also tried paired with the best column beside it (a level fed by an input explains nothing alone: the change follows the gap between the two).
2. **Rows** (`rows.py`): the main line's row (an outside inflow that is none, constant, or in PELT pieces found on means of `T // 3000` steps).
3. **Stages.** Delayed copies of every other stock's level (`hidden.py`, delays 1 and 0.5) are columns too, positive only. A copy chosen in B's row is an unmeasured stage in front of B, such as a load balancer's queue. A one-step stage also carries the row's other terms, so a stock that turns over every step never has to lose more than it holds in one step (Euler sharing would otherwise cap it).
4. **Links reading** (`links.py`). What one stock's level does to another is a link (nothing is taken from the source), with each row's other terms written as one signed, floored flow. A stage takes from its source by a move only as far as the source's own drain allows and only within the same unit.
5. **Refinements** of the two best links candidates:
   - **floored rates** (`rows.hinge`): change = max(0, in) - max(0, out) on the row's own columns, which is what a horizontal pod autoscaler (HPA) does;
   - **ratios** (`ratios.py`): k x A / M is read as a flow k x A with a 1/M table effect, such as memory per request per pod.
6. **Judge** (`judge.py`): the candidate runs forward with the measured inputs. The main line's judge leaves the inputs out. The score is the error in the data's own units (which the goal's skill weighs) plus the error with every stock weighed alike.
7. **Blocks** (`blocks.py`): connected components of the chosen-column graph, with complete-linkage clusters of at most 12 stocks on 1 - |corr of changes|. Each block takes its rows from the candidate that predicts that block best, and the joined model is kept only if it is better as a whole.
8. **Budget:** 600 s by default. The best model so far is always returned. Below 15 measured stocks the main line (`sdlab/discovery/identify.py`) runs unchanged.

## Results (ladder, ea82c31, scorer ebf409)

| case, variant | skill@20 | @100 | fresh@20 | parts right / found (of) | discovery time | matrix |
|---|---|---|---|---|---|---|
| sd-k8s-small short (7 d) | **96.1%** | 99.3% | 96.0% | 25 / 47 (117) | 6.0 s | 58.2% @20, 67.5% @100; 23 / 49; 151 s |
| sd-k8s-small long (14 d) | **98.1%** | 99.4% | 97.7% | 27 / 62 (117) | 6.8 s | 87.2%, 97.6%; 19 / 49; 473 s |
| sd-k8s-platform short | **99.4%** | 99.9% | 99.4% | 207 / 282 (794) | 41 s | -337% (1,672 s, old scorer) |
| sd-k8s-platform long | **99.3%** | 99.7% | 99.3% | 202 / 315 (794) | 38 s | timeout (1,800 s) |

Matrix's parts are its stored flows scored again with the current scorer (no store writes).

**Memory:** discovery alone peaks at 2.2 GB on the platform's long run (`/usr/bin/time -l` on the strategy with the page data). The ladder worker peaked at 10.2 GB, almost all of it the harness loading every flow's counter and scoring.

**Standard tests:** the strategy differs from matrix only at 15 or more measured stocks. Outside the k8s cases, only part-galton-board (15) and part-ball-plant (32) are that large. On 001-012 and both particle cases (64 paired cells) every status equals matrix's.
- part-galton-board, skill@20: 70.4% long and 84.0% short (matrix 69.3% and 71.5%).
- part-ball-plant, skill@20: 54.8% long and 66.2% short (matrix 58.8% and 67.5%). This is slightly worse.
- Fresh skill on the particle cases is poor for both strategies.

**What it finds on the platform:** the call graph as stages, for example redis_cache_inflight = -1.0 x self + 1.0 x pricing's stage + 2.0 x catalog_api's stage. It also finds CPU from load and replicas, memory from load per pod, and HPA rows as floored rates.

## Limits

- **Effects:** throttling (ml-model-server, pricing) and OOM/scheduling tables are not modelled beyond 1/x ratios. They are the main misses, in both behaviour and parts.
- **HPA numbers:** the floored-rate numbers are biased by the measured levels being whole numbers, so they are found but not right.
- **Recall:** found parts rise (47-62 vs 49 on small; 282-315 on the platform), but right parts rise only modestly (25-27 vs 19-23).
- **Scaling further:** the cost per candidate is the judge's simulations (about 2-4 s on the platform) and the Gram matrix (columns are 3 x stocks: O(N^2 T)). X and its cumulative sums take 2 x 8 x N x T bytes, about 1 GB at 2,000 stocks for a week. Beyond that, the cumulative sums would need to be held only at piece boundaries, or in chunks.
- **Harness memory:** the 10-15 GB per worker is the harness keeping every flow's counter, not discovery.

**Verdict:** keep, and use it for large models driven by a measured input. Next: effect tables beyond ratios, and stages offered to `moves` candidates.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (own copy of matrix/boundary.py, wired into this
strategy's search): see [declared-boundary-six.md](declared-boundary-six.md) for the hooks and the paired results.
