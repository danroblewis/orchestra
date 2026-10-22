# 315 (k8s-fan-out): milp, round 1

Status (2026-10-22, code d44d014; pool job 339, all four items on the Mac): **all four variants pass 12/12**
after one fix commit. Before (store, code 20ed81c, results #387105/#387109/#387119/#387122): PPPF.

| variant      | achievable? (`analyse`) | before (20ed81c)                 | round 1 (d44d014, job 339) |
|--------------|-------------------------|----------------------------------|----------------------------|
| none-short   | yes (p 1.000 per part)  | PASS                             | **PASS 12/12** (20.7 s)    |
| none-long    | yes (p 1.000)           | PASS                             | **PASS 12/12** (43.4 s)    |
| counts-short | yes (p 1.000)           | PASS                             | **PASS 12/12** (175.0 s)   |
| counts-long  | yes (p 1.000)           | FAIL 11/12 (339.9 s)             | **PASS 12/12** (365.2 s)   |

Commands: `uv run sdlab-ladder job 339`, `uv run sdlab-ladder diff 315-k8s-fan-out --strategy milp --variant V`
(each variant at d44d014: "none", 12 unchanged), `uv run sdlab-ladder show 315-k8s-fan-out --strategy milp --variant counts-long`
(complexity 25 vs 25, 1.00x; `outside -> cart_queue = 0.15 x frontend_inflight`, error 0.0%).

## The failure (counts-long, before)

`diff`: `outside -> cart_queue = 0.0351 x traffic + 0.129 x frontend_inflight + 0.00798 x catalog_responses_total
- 0.0159 x cart_responses_total` (the link 14% low, three extra terms). A trace of the passes (scratch script running
`_identify_program`, then each `_after_program` pass) showed the **program stage itself** returned it; no post pass
changed it.

Diagnosis (method fault, not data): counts is Poisson flows on exact levels, so with the true reader in the span an
extra term gains only by chance. Row-alone weighted least squares gives traffic t = 1.7 (train) and 0.1 (fresh). Yet
milp's own BIC kept it. Two causes:

1. **The counts weights were bent by the cancelling terms.** `Structure.gross()` (the amount moved per stock, which
   sets the Poisson scale sqrt(gross)) added `|amount|` **per part**. The two counter terms each move ~1830 a step and
   cancel, so cart_queue's gross was huge and nearly flat. Its weights then stopped tracking the real Poisson scatter,
   and under those weights the counters plus traffic beat the plain link. Recomputing the BIC with the gross of the
   model without the counters made the plain link best by 4.8 (train) and 7.5 (fresh).
2. **Prune's one-at-a-time search could not leave the counter pair.** With per-flow gross, the plain link is best by
   10.1, but dropping either counter alone costs BIC (the other's drift is left unexplained). Only dropping both
   together helps.

## Fixes kept (commit d44d014, `milp/refit.py`)

| type | mechanism | how another strategy adopts it |
|---|---|---|
| **net-gross** (counts weighting) | `Structure.gross()` sums a flow's parts (terms, pieces, eras, MIN) per (src, dst) **before** taking the size, so terms of one flow that cancel move nothing in the counts scale | any strategy that weights counts rows by sqrt(amount moved) (combined2/structures `counts` weights, kalman_lna's Poisson scale): compute the scale from the net flow amount, never from the sum of term magnitudes |
| **pair-drop** (search) | `refit.pair_drops`: prune also tries dropping two plain terms of one flow at once (first-improvement, inside the same work budget) | any backward-elimination or prune: add the joint deletion of each pair of readers on one flow beside the single deletions; cheap (flows have few readers) |

Both are general: neither names a stock, a counter, or a case. Run cost is unchanged (counts-long 340 -> 365 s, of
the 1800 s limit; the Mac rather than node2).

## For the regression run

- net-gross changes the counts weights wherever a flow has several terms with opposite signs (gap flows `c - k x level`,
  `neg` parts, signed pieces). Check 309 (gap flows) and 310-312 counts variants, where milp has multi-term declared
  sides.
- pair-drop can only remove parts when BIC improves, so it should simplify or leave models alone; it adds refits to
  prune (bounded by PRUNE_WORK, so it cannot time out, but it can make a prune stop earlier on large models: check
  310/312 none-long, which hit the budget before).
- The other strategies' 315 counts failures (`diff 315-k8s-fan-out --summary`: `outside -> cart_queue` extra terms on
  `catalog_responses_total`/`cart_responses_total` in 10-12 strategies) look like the same cancelling-counter pair.
  pair-drop is the likely port for them.
