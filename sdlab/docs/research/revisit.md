# Revisiting past discovery ideas on the ladder

**Status:** done (2026-10-18/19). Strategy code at commit 2bbc025. Ladder numbers are from the result
store (`~/.cache/sdlab/ladder/results.sqlite`, latest result per case, variant and strategy) read at
2026-10-19 02:30 UTC, on cases 001-048 (the 472 cells of the ladder when this work started).
**Verdict:** one stack of four revisited ideas over lna (`lna_stack`) passes 381 of 472 cells
against lna's 340, with no cell lost, better fresh behaviour and a higher Occam score; adopt its
stages into `combined` (lna_levels, lna_pulses, lna_products with levels, the noise-free
conventions). Do not adopt `lna_loops`. No parked strategy has a win of its own left; 20
matrix-plus-one-mechanism strategies are dominated on the ladder and can be parked.

Strategies built here: `gap_prior`, `lna_loops`, `lna_pulses`, `lna_products`, `lna_levels`,
`lna_stack` (`sdlab/sdlab/discovery/strategies/<name>/`); tests `tests/test_ladder_revisit.py`.

## Why

Most ideas in [tries.md](tries.md) and the topic documents were judged on the old bench of 31
complex example models, where a model failed for several reasons at once, so one mechanism could
not show what it fixes. The ladder ([../LADDER.md](../LADDER.md)) isolates one feature per case.
An idea rejected on the bench may still win one rung there. Methods held back by the judge
(PySINDy, the numerical optimisers) were also not to be dismissed on the bench's word
(CLAUDE.md, rule 14).

## How it was run

- **Every strategy on the ladder, including the parked ones.** A full `uv run sdlab-ladder sync
  --strategies everything --jobs 8 --timeout 300` was started. It was stopped when the project
  rules changed during this work: one supervised watcher now re-runs stale results, and agents
  run only their own strategies. The non-parked strategies were left to the watcher. The watcher
  never runs the parked ones, so they were run by name (niced, `--jobs 3-4`, `--timeout 300`) on
  the cases they lacked, the parametric families 041-048 first. Coverage is therefore uneven, and
  the tables give it as "cells run". A cell a strategy has not run is "not run", never a fail.
  - The 10 parked strategies have 414 of the 472 cells; the 039/040 draws, simple chains that
    every leading strategy passes, were not run.
  - 20 older non-parked strategies have 290; the watcher had a backlog of about 15,000 items.
- **The board mixes versions.** Other agents changed lna, common_cause, effect_hats, censored,
  combined, shared discovery code and the scorer during this work.
  - Every change to `sdlab/discovery` makes every strategy stale.
  - The comparisons of the new strategies against lna pair the latest result of each. Those
    results all ran between 01:00 and 02:30 UTC on 2026-10-19.
- **Analysis labels.** These come from the ladder's own analysis (`sdlab/ladder/analysis.py`,
  read through `api.summary`). `unidentifiable`: only an equivalent model is possible from these
  data. `data-limited`: even an estimator at the Cramér-Rao bound meets the tolerance with p <
  0.5. `achievable`: otherwise. They are quoted from a read at about 01:40 UTC. At 02:30 the
  analysis returned no labels (being recomputed), so the table below has none.
- **Reproducing.** The tables come from two short scripts over `results.sqlite`:
  - a per-strategy table: cells run; passes; wins and losses against lna on the cells both ran;
    passes no leading strategy has; cells it alone passes; strategies that pass every cell it
    passes over at least 90% of its cells;
  - a paired comparison against lna.

  Leading strategies: lna, combined, common_cause, earned_pieces, censored, effect_hats,
  hidden_transit, held_out, matrix. The queries are short, and their logic is described here so
  they can be rewritten.

## Unique wins, cases 001-048

| strategy | cells run | pass | wins vs lna | losses vs lna | passes no leading strategy has | sole passer | dominated by | s/cell |
|---|---|---|---|---|---|---|---|---|
| combined | 472 | 412 | 74 | 2 | 011 n; 016 n; 021 all; 022 all; 047 #1,#4,#5,#8 n | 0 | - | 6.59 |
| **lna_stack** (new) | 472 | **381** | **41** | **0** | 017 cs, cl; 018 cs; 046 #2, #4, #5 cl | 3 | - | 3.50 |
| **gap_prior** (new) | 472 | 360 | 20 | 0 | - | 0 | lna_stack | 0.90 |
| **lna_levels** (new) | 472 | 350 | 10 | 0 | - | 0 | lna_stack | 0.95 |
| **lna_loops** (new) | 472 | 349 | 9 | 0 | 010 cs; 046 #1 cs, #2 cl, #3 cs/cl, #4 cs/cl, #5 cs/cl | 6 | - | 0.92 |
| **lna_pulses** (new) | 472 | 344 | 4 | 0 | - | 0 | lna_stack | 2.20 |
| lna | 472 | 340 | - | - | 045 #1 cs; 046 #8 cs | 0 | the new five | 1.21 |
| **lna_products** (new) | 472 | 340 | 0 | 0 | - | 0 | lna, ... | 3.08 |
| common_cause | 472 | 309 | 22 | 53 | - | 0 | combined | 1.77 |
| effect_hats | 472 | 295 | 19 | 64 | - | 0 | combined | 2.61 |
| earned_pieces | 472 | 291 | 7 | 56 | - | 0 | combined, common_cause | 0.99 |
| held_out | 472 | 280 | 6 | 66 | - | 0 | combined | 1.29 |
| censored | 472 | 273 | 21 | 88 | 024 cl | 1 | - | 0.98 |
| hidden_transit | 472 | 211 | 13 | 142 | - | 0 | combined | 0.94 |
| matrix | 472 | 203 | 5 | 142 | - | 0 | combined, effect_hats, hidden_transit | 0.50 |
| symbolic_anchor | 472 | 203 | 6 | 143 | - | 0 | combined, effect_hats | 0.63 |
| symbolic | 472 | 202 | 5 | 143 | - | 0 | combined, effect_hats, symbolic_anchor | 0.65 |
| held_out_blend *(parked)* | 414 | 177 | 5 | 117 | - | 0 | combined, effect_hats, lna_levels | 3.31 |
| numopt_bo *(parked)* | 414 | 173 | 7 | 123 | - | 0 | combined, lna_stack | 17.54 |
| numopt_cma *(parked)* | 414 | 172 | 7 | 124 | - | 0 | combined, lna_stack, numopt_bo | 5.03 |
| gradient *(parked)* | 414 | 171 | 5 | 123 | - | 0 | combined, effect_hats, held_out_blend | 4.15 |
| numopt_powell *(parked)* | 414 | 170 | 7 | 126 | - | 0 | combined, lna_stack, numopt_bo | 3.82 |
| numopt_nm *(parked)* | 414 | 169 | 7 | 127 | - | 0 | combined, lna_stack, numopt_bo | 4.35 |
| numopt_lbfgs *(parked)* | 414 | 152 | 6 | 143 | - | 0 | combined, lna_stack, numopt_bo | 4.55 |
| change_price | 290 | 140 | 3 | 70 | - | 0 | combined, common_cause, earned_pieces | 0.47 |
| periodic_inflows | 290 | 139 | 10 | 78 | - | 0 | combined | 0.66 |
| mass_balance | 294 | 134 | 5 | 78 | - | 0 | combined, hidden_transit, mass_balance_all | 0.69 |
| mass_balance_all | 290 | 133 | 4 | 78 | - | 0 | combined, hidden_transit, mass_balance | 1.80 |
| piece_proof | 290 | 133 | 4 | 78 | - | 0 | combined, common_cause, effect_hats | 0.51 |
| recession, floors, gated, gated_no_high, inflow_attribution, inflow_attribution_both, inflow_attribution_refine, latent_eras, paced_moves, row_crossover, starved_coflows, pieces_gate, output_error | 290 | 128-133 | 3 (048 #3, #5, #7 cl: matrix's own wins) | 77-82 | - | 0 | combined, common_cause, earned_pieces, ... | 0.5-1.2 |
| hidden_delays | 294 | 132 | 4 | 79 | - | 0 | combined, common_cause, effect_hats | 1.37 |
| impulses | 308 | 131 | 7 | 98 | - | 0 | combined, periodic_inflows | 2.05 |
| numopt_fd_profile *(parked)* | 414 | 130 | 5 | 164 | - | 0 | combined, effect_hats, held_out_blend | 3.67 |
| sindy | 290 | 110 | 6 | 103 | - | 0 | combined | 5.99 |
| numopt_fd_coarse *(parked)* | 414 | 109 | 6 | 186 | - | 0 | combined, lna_stack | 8.72 |
| numopt_fd *(parked)* | 414 | 107 | 5 | 187 | - | 0 | combined, effect_hats, held_out_blend | 3.32 |
| shared_noise | 290 | 86 | 13 | 134 | 007 n; 045 #1-#8 none-long | 10 | - | 0.52 |

(n = both noise-free variants, cs/cl = counts-short/long, ns/nl = none-short/long; "all" = all four.)

### What each unique winner does that lna does not

| strategy | wins over lna | what it does there |
|---|---|---|
| matrix and the 20 strategies built on it | 048 #3, #5, #7 cl (all); #1, #2 cs (some) | the matrix's own outside-inflow pieces. lna reads a square-wave inflow as growth or misplaces a step |
| common_cause | 032/034/035/038 n, 043 draws n, 033 c | exact ties between identical stocks; change places shared across stocks |
| censored | 024, 025; 047 #2, #3, #6, #7 n | floors and caps fitted as the engine steps them. In the four 047 draws the goal gap's floor binds, which makes the gap identifiable without noise |
| hidden_transit, mass_balance(_all) | 015, 026 (mass_balance: 015 cs, 026 cs) | an unmeasured stock, followed by a Kalman filter |
| effect_hats, sindy, symbolic(_anchor) | 017, 018 noise-free (effect_hats also 018 cl) | effect curves of a third stock (tent columns, a product library, symbolic search) |
| periodic_inflows, impulses | 021, 022 (all or some) | an outside inflow as a repeating profile; one-step pulses |
| numopt_bo/cma/nm/powell/lbfgs/fd_coarse (parked) | 016 n | the multi-step refit lands on the co-flow reading of a drain read by the moving stock (unidentifiable without noise; `gap_prior` now writes it that way by convention) |
| shared_noise | 007 n, 045 #1-#8 none-long | its noise-free tie-break picks the link over the move. These cells are unidentifiable (link vs move without noise), so this is a prior that happens to match these truths, not identification |
| sindy, common_cause, earned_pieces | 019 ns | announced eras on a short run |

**No strategy passes 35 cells.** Thirty-one of them are noise-free cells that the analysis labels
`unidentifiable`: link vs move (008, 045, 046 none), births vs deaths (009) and the loop branch
(010). The other four are noisy cells it labels `data-limited`: 016 cs, 045 #7 cs, and 046 #1 cl,
#2 cs, #7 cs. For these 35, an `equivalent` result is the best the data allow.

## Past ideas never tried on the ladder

These come from tries.md, IDEAS-WAVE4.md, PLAYBOOK.md and every topic document. Ideas that already
had a strategy were run on the ladder above. Those are the count likelihoods (`lna`), censored
floors (`censored`), effect columns (`effect_hats`), impulses, periodic inflows, latent eras,
recession drains, starved co-flows, row crossover, the judges, the optimisers, PySINDy, symbolic
regression, hidden stocks and mass balance. The rest, with the rungs they could address:

| idea (doc) | old-bench status | rungs it addresses | taken up here |
|---|---|---|---|
| identifiability: list the equivalent rewrites and choose by a declared preference ([identifiability](identifiability.md), [judge-ties](judge-ties.md)) | idea | 011/047 and 016 noise-free; 007/008/045/046 noise-free | `gap_prior` |
| bootstrap inclusion / complexity budget ([bayesian-structure](bayesian-structure.md), [complexity-budget](complexity-budget.md)) | idea | 046 noisy loops | `lna_loops` (the simplest form: keep the loop link at price 0) |
| pulses as their own input, under the counting likelihood ([impulse-inputs](impulse-inputs.md)) | "adopt behind the judge" on the bench; never tried with lna | 022 | `lna_pulses` |
| product terms (PySINDy) and effect columns, in the counting likelihood ([pysindy](pysindy.md), [effect-columns](effect-columns.md)) | PySINDy rejected as a strategy, with "carry the product terms forward" | 017/018 noisy | `lna_products` |
| regime models and inflow innovations: a stepping inflow as a few recurring levels ([regime-models](regime-models.md), [inflow-innovations](inflow-innovations.md)) | idea | 048/027/020 noisy, 017's square wave, 021 | `lna_levels` |
| delay deconvolution with state-space EM ([delay-deconvolution](delay-deconvolution.md), [state-space](state-space.md)) | idea | 015 counts-short | no (now passed by `mass_balance` and `combined`) |
| conserved totals and exact invariants ([conserved-totals](conserved-totals.md)) | idea | 034/035/038 noise-free | no (`common_cause` passes them) |
| structure search: beam, MCTS, GA ([structure-search](structure-search.md)) | unfinished | 046, 047 | no |
| AR rows ([ar-rows](ar-rows.md)) | idea | 015, 048 (bias) | no |
| FROLS, weak form, Koopman/DMD, causal discovery (PCMCI), online RLS, loop dominance, general equations | ideas | none of the failing rungs | no |
| simulation-based inference, LLM priors, LLM critic | idea / unfinished | noise-free ties | no (a learned or LLM prior would only replace `gap_prior`'s declared one) |
| experiment design, injection instruments, injection-response judge | ideas | 046, 015 (they need probes; only 023 injects) | no |

## What was built

The five new stages are separate packages on top of lna. Each imports lna's modules and copies
lna's `discover` (lna/run.py), adding one step. `lna_stack` imports the stages unchanged. A copy can
drift from lna as lna changes; see Recommendations. All are measured paired with lna (latest
results, cases 001-048). Fresh skill@20 is clipped at -100% per cell.

| strategy | pass (lna 340) | wins / losses | Occam (lna 0.861) | extra complexity (lna +1.53) | fresh skill@20 (lna 0.831) | cells with fresh skill@20 >10 points worse | s/cell |
|---|---|---|---|---|---|---|---|
| gap_prior | 360 | 20 / 0 | 0.870 | +1.40 | 0.857 | 0 | 0.90 |
| lna_loops | 349 | 9 / 0 | 0.834 | +1.94 | 0.826 | **19** (noisy chains, 040/043/032) | 0.92 |
| lna_pulses | 344 | 4 / 0 | 0.859 | +2.18 | 0.832 | 0 | 2.20 |
| lna_products | 340 | 0 / 0 | 0.866 | +1.50 | 0.838 | 0 | 3.08 |
| lna_levels | 350 | 10 / 0 | 0.897 | +1.51 | 0.866 | 1 (033 cl, both fail) | 0.95 |
| **lna_stack** | **381** | **41 / 0** | **0.895** | +2.94 | **0.913** | 0 | 3.50 |

### gap_prior: SD conventions for ties the data cannot break

This is lna, with a noise-free model's readings that are equal in the averages written the way SD
models write them.

- **Goal gaps.** A drain of b read by another stock a, beside b's single constant inflow, is
  written as b's goal-gap inflow `c - k a`. The matrix cuts a constant into pieces that differ only
  in rounding, and these are treated as one number.
- **Co-flows.** A drain of c read by a stock a that moves things on (a -> b) is written as a
  co-flow of that move.

With counting noise, lna's likelihood decides between the readings and its result stands. A rewrite
is kept only when it behaves as the original on the run (lna's judge). It is never made between
stocks whose levels are copies of each other. The first version rewrote the identical-twin cases
(034/035/038 noise-free); their in-sample skill then fell to -15,000%, so this rule was added.

Results: 20 wins (011 n, 016 n, all 16 of 047's noise-free cells), no losses. The analysis labels
011, 016 and 047 #1, #4, #5, #8 noise-free `unidentifiable`, so those 14 passes come from a
convention that matches the SD practice the cases follow, not from the data. The 047 #2, #3, #6, #7
noise-free cells are `achievable`: their gap's floor binds. `censored` also passes those four, and
reads the floor itself. (censored.md describes the same reading problem from the other side: "a
negative off-diagonal number is always read as an outflow".)

### lna_loops: loop-closing links kept rather than priced away

After lna's search, each link that would close a loop (outside -> a reading b, where a moves into
b) is offered back. It is kept whenever its maximum-likelihood number is above zero (price 0;
option `loop_price`).

- **Wins: 9** (046 counts, 010 cs). Six of them no other strategy passes.
- **They are not real gains.** The analysis labels these cells `data-limited` (p = 0.01-0.23): the
  link's standard error is as large as the link. The kept number passes because the scorer allows
  3 SE around the truth's own fit.
- **It costs behaviour on noisy chains.** A link read off a slow stock is confounded with the
  stock's constant inflow. On 19 noisy chain cells (040, 043, 032) the found model still passes,
  but its fresh skill@20 falls by more than 10 points. Example: 040 #6 counts-short falls from 98%
  to -29%.
- **No guard fixed this.** A guard on lna's in-sample judge was tried and dropped: the judge
  scores the harmful model better (0.97x) and rejects true links at random (ratios 0.995-1.01). An
  AIC price (1 instead of BIC's log T / 2) still keeps the harmful link on 040 #6.

Verdict: do not adopt. On 046 noisy cells, lna's `equivalent` is the honest answer. The idea that
remains is bootstrap inclusion probabilities, reported rather than decided.

### lna_pulses: pulses found first, lna on what they leave

The impulses strategy's detection (`impulses.find_pulses`) feeds lna instead of the matrix.

- **Steps:**
  1. Pulses are taken out of each step's change before lna's likelihood reads the moves.
  2. The pulses are measured again on lna's model.
  3. A pulse is kept when it stands 6 robust SDs clear and is a burst: at least a quarter of a
     typical step's movement. Without that size rule, the data's rounding made dozens of tiny
     pulses on noise-free chains.
  4. Pulses of one size, by a chi-square test at 1%, are pooled. A periodic burst is then measured
     n times better: on 022 counts-long, 20 single estimates spread ±20 around 300 and the
     scorer's window allows ±30.
- **Other rules:** noise-free runs have their inflows re-measured on the matrix's model.
  Announced injections and the two steps after one are never pulses.
- **Results:** 022 passes in all four variants (it was FFFF for lna). 022 none-short and
  counts-short were passed by no strategy before. No losses. Without a pulse, the result is lna's.

### lna_products: moves scaled by a third stock inside lna's likelihood

Virtual stocks `a x c / mean(c)` give lna product columns. After lna's search, each kept move and
outflow is offered scaled by each other stock. The product model must beat lna's BIC by log T,
which is the price of two numbers, because many products are offered. Measured gains: true
effects 41-335, spurious ones at most 1.7. Products are written as a linear effect, or as a table
effect when a plain flow between the same ends remains.

- **On its own: 0 wins and 0 losses.** On 017/018 counts the effect is found (error 0.4-3.8%).
  The case still fails, because C's unannounced square-wave inflow is read as growth plus a link
  (lna's weakness, below).
- **With lna_levels, in lna_stack:** 017 counts-short/long and 018 counts-short/long pass. That
  is the first pass of 017 counts and 018 counts-short by any strategy. The analysis labels them
  `data-limited` (p 0.03-0.36). The tolerance is met because the square wave is measured as two
  levels rather than per window, and the truth is two levels.

### lna_levels: outside inflows as a few recurring levels

From regime models and inflow innovations, neither ever built. After lna's search:

- **Levels.** A stock's inflow pieces are offered as K recurring levels, K from 1 to 4. Each level
  is a column that is 1 on its steps, fitted by lna's likelihood. A level's steps come either from
  1-D k-means of lna's pieces, or from switches found afresh by Viterbi, alternating with lna
  refits.
- **Scoring.** Every cut or switch is priced at log T. Fewer levels win within 2 BIC units.
- **Growth.** Self-growth (outside -> s reading s) is offered back as inflow pieces, but only
  where that inflow steps (3 pieces or more) and wins by the margin. A first version also replaced
  the births of 009, so the rule was added.
- **Guard.** lna's guard is applied to lna's own reading first. Where lna would keep the matrix's
  model, so does this. Without that rule, the regrouped model passed the guard on 033 counts-long
  where lna's did not, and its fresh skill fell from 86% to -11,960%.

Results: 10 wins (048 #1, #2, #3, #5, #7, #8 counts; 027 cl; 021 cs, cl), no losses. 048 is now
31 of its 32 cells; only 048 #5 counts-short fails, and no strategy passes it.
Fresh skill improves on 21 cells and is worse by more than 10 points on 1 (033 cl, where both
fail).

### lna_stack: the recommended stages in one model

lna_stack runs these stages in order:

1. Pulses out.
2. Product columns.
3. lna's search.
4. Products offered.
5. Growth offered back as pieces.
6. Levels.
7. On noise-free runs, gap_prior's conventions.

lna_loops is left out. Every stage is imported unchanged.

- **Results:** 381 of 472 against lna's 340. 41 wins, 0 losses.
- **Behaviour:** fresh skill@20 0.913 against 0.831, Occam 0.895 against 0.861, no cell more than
  10 points worse.
- **Complexity** is higher on average (+2.94 against +1.53), from pulse and level pieces.
- **Wins no leading strategy has:** 017 cs and cl, 018 cs, and 046 #2, #4, #5 counts-long. The
  046 links survive without the loop stage, because the levels re-cut the inflow they were
  confounded with.
- **Cost:** 3.5 s per cell, about 3x lna. On 033 counts-long (four stocks, twelve products) it
  took longer than 120 s once, under a load of about 110; the ladder runner's default timeout is
  120 s.

## Recommendations

**Unpark: none.** The parked strategies' only wins of their own on the ladder were 016 noise-free
(numopt_bo, cma, nm, powell, lbfgs, fd_coarse). `gap_prior`, `lna_stack` and `combined` now pass
those cells, so every parked strategy is dominated (table above). numopt_bo costs 17.5 s per cell.

**Retire, meaning park with this reason:**

- Parked strategies dominated everywhere: numopt_fd, numopt_fd_profile, numopt_fd_coarse,
  numopt_lbfgs, gradient, held_out_blend, which pass fewer cells than numopt_bo/cma and combined.
- The matrix-plus-one-mechanism strategies whose only wins over lna are the matrix's own 048
  draws, dominated by combined, common_cause and earned_pieces: change_price, floors, gated,
  gated_no_high, inflow_attribution, inflow_attribution_both, inflow_attribution_refine,
  pieces_gate, latent_eras, paced_moves, row_crossover, starved_coflows, recession, output_error,
  piece_proof, hidden_delays.
- mass_balance_all (dominated by mass_balance), symbolic (by symbolic_anchor), and impulses (by
  periodic_inflows, and lna_pulses on 022).

Two cautions:

1. These ran 290 of the 472 cells; the watcher will fill the rest.
2. The ladder has no rung for some of their mechanisms. Before parking, add one rung each:
   - a co-flow whose used stock runs dry (starved_coflows);
   - an unannounced regime in a coefficient (latent_eras);
   - quiet stretches with no inflow (recession).

**Keep:**

- **shared_noise.** It is the only strategy that passes 007 and 045 noise-free. That is a
  tie-break prior on unidentifiable cells, so its preference rule should be read and written down
  like gap_prior's.
- **mass_balance.** 015 and 026 counts-short.
- **periodic_inflows.** 021 noise-free.
- **sindy.** 017 noise-free and 019 none-short. It is dominated only by combined.

**Stages for `combined`, in order of value.** The simplest way is to add `lna_stack` as one more
specialist: each stage ran on 472 cells with no loss against lna. Otherwise:

1. **lna_levels.** It makes the specialist reading of stepping inflows reliable (048, 027, 021),
   and it is what turns 017/018 counts into passes.
2. **lna_pulses.** 022, the only strategy passing all four variants.
3. **lna_products, together with lna_levels.** 017/018 counts.
4. **gap_prior's conventions (goal gap, co-flow), with its behaviour check and collinearity
   guard.** combined's tie-break (fewer flows that read another stock) already does something
   similar, and combined passes 011 and 016 noise-free. Keep the two consistent.
5. **Not lna_loops.**

**For lna's owner.** Expose a hook in `lna.run.discover` (a `finish(cur, d)` called on the fitted
atoms before they are written as flows) and the Data it fitted. These stages could then plug in
without copying `discover`, and would not drift from lna.

**Next ideas.**

- **Bootstrap inclusion probabilities** for small loop links (046), reported, not decided.
- **Delay deconvolution** to seed hidden_transit on 015 counts-short.
- **A structure search judged on behaviour** for 046/047.
- **Rungs for the mechanisms above.** The ladder cannot test some strategies without them.
