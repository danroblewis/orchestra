# Causal discovery on time series (PCMCI+, Granger)

**Status:** done (offline baseline, measured 2026-10-20). **Verdict:** reject as a structure engine
and as a prior. On the graph alone, no causal-discovery method beats the leading strategies on the
Tests set or the kubernetes set. A plain t test on our own per-stock row regression beats all of
them. The one place they add anything is lagged effects through hidden stocks and dead time, and
only against the lag-1 strategies (matrix_v2, blockwise). `structures` already finds those edges.
LPCMCI's "hidden confounder" flags carry no signal.

## Why
The literature notes ([causal inference](literature/causal-inference.md) 2.2, playbook section 6)
argued that PCMCI and Granger add little over our per-stock regression. They are graph-only,
balancing loops break faithfulness, and they ignore conservation. The user asked for that claim to
be measured, not argued.

## Method
`scripts/causal_bench.py`. Each method gets exactly what a strategy gets: the measured levels and
measured inputs of a case's variant, through the ladder's loader (`sdlab.ladder.data.load`), and
never the truth. A gaps variant is interpolated onto its median step. Eras and injections are not
used. Each method returns directed edges "X affects Y's change" among the measured stocks and
inputs, with nothing allowed to point into an input.

- **PCMCI+** (Runge 2020): ParCorr, `tau_max` 3, `pc_alpha` 0.01. A lagged `-->` link counts as an
  edge. `pcmci_plus_c` also counts contemporaneous links: an oriented one in its direction, an
  unoriented one both ways.
- **PCMCI** (Runge et al. 2019): lagged links only, `tau_max` 3, alpha 0.01.
- **LPCMCI** (Gerhardus, Runge 2020): `tau_max` 2, alpha 0.01. Its lagged `-->` links count as edges,
  and its `<->` links count as hidden-confounder flags.
- **Granger, pairwise and conditional**: F tests on levels at lags 1-2, alpha 0.01. Pairwise uses
  Y's own lags plus X's. Conditional uses every variable's lags, with and without X's.
- **row_reg**: our own per-stock row regression used as a test. Each stock's change is regressed on
  every level and input one step earlier, with a test per coefficient at 0.01 (the same as
  conditional Granger at lag 1). This is a reference point, not a strategy.

Each method has a 120 s limit per cell; a run that hits it is counted as an error, not as an empty
graph. Tigramite is GPL-3.0, so it lives only in a scratch venv
(`/private/tmp/claude-501/-Users-daniellewis-orchestra/30b084ac-356e-4334-af44-251920c53fe1/scratchpad/cdvenv`).
It is never a dependency of sdlab and never vendored. The script imports it only inside the PCMCI
functions, so the file imports and the report runs in the project venv.

**The truth graph.** It comes from the truth's flows. Every stock or input that a flow's rate reads
(its scheduled rates, its effects, and the stocks an `expr` rate reads through the auxiliaries)
affects the change of every stock the flow drains, fills or uses up. Self-edges are dropped. Hidden
stocks are marginalised out (X -> hidden -> Y counts as X -> Y), because that is the graph a method
that sees only the measured series can find. A strategy's stored found flows (the result store,
latest result per cell, read-only) become a graph by the same rule, with any hidden stocks it
invented marginalised out too. Scores are precision, recall and F1, pooled over cells, plus the
mean F1 per cell. Paired differences in cell F1 come with 95% intervals from a bootstrap over cases,
since a case's variants are not independent. A cell where both graphs are empty counts F1 = 1.

**Cells.** Tests set (`leaderboard.kind_of` = tests: 278 cases including parametric draws) gives
1192 cells. Kubernetes 300-317 gives 82 cells. All variants are used: none and counts at both
lengths, plus meas, gaps, weekly, lag, outliers and bias where a case has them. The stored
strategies cover every Tests cell. On kubernetes they cover only 23-25 of the 82 cells, because the
watcher excludes `tag:kubernetes`; the other cells are "not run" for the strategies and are left
out of the paired comparisons. The store mixes strategy versions where the watcher had a backlog.

```sh
# scratch venv with tigramite (never the project's):
uv venv $SP/cdvenv && VIRTUAL_ENV=$SP/cdvenv uv pip install tigramite joblib -e .
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  $SP/cdvenv/bin/python scripts/causal_bench.py run --out $SP/cells.jsonl \
  --methods pcmci_plus,granger_pair,granger_cond,row_reg,lpcmci --jobs 4
... run --out $SP/cells_pcmci.jsonl --methods pcmci --jobs 4
uv run python scripts/causal_bench.py report $SP/cells.jsonl $SP/cells_pcmci.jsonl
```

The report was run on 2026-10-20 at 00:54 against the store at that time. A cell takes milliseconds
for Granger, a median of 0.03 s for PCMCI+, 0.2 s for PCMCI and 0.09 s for LPCMCI. The worst cells
hit the limit: LPCMCI 9 times (all kubernetes), PCMCI 2, PCMCI+ 1.

## Results

### Tests set, all 1192 cells (graph only)

| method | precision | recall | F1 (pooled) | mean cell F1 |
|---|---|---|---|---|
| PCMCI+ (lagged links) | 0.794 | 0.479 | 0.597 | 0.569 |
| PCMCI+ with contemporaneous links | 0.642 | 0.729 | 0.683 | 0.703 |
| PCMCI | 0.536 | 0.667 | 0.594 | 0.679 |
| LPCMCI | 0.860 | 0.371 | 0.518 | 0.423 |
| Granger, pairwise | 0.565 | 0.841 | 0.676 | 0.778 |
| Granger, conditional | 0.646 | 0.797 | 0.714 | 0.795 |
| row_reg (our regression, t test) | 0.760 | 0.881 | 0.816 | 0.847 |
| matrix_v2 (stored) | 0.934 | 0.864 | 0.898 | 0.878 |
| structures (stored) | **0.953** | **0.901** | **0.927** | **0.919** |
| kalman_lna (stored) | 0.952 | 0.871 | 0.910 | 0.891 |
| blockwise (stored) | 0.897 | 0.852 | 0.874 | 0.861 |

Paired cell F1 (method minus strategy, 1192 cells, 95% CI over cases). Every causal-discovery
method is worse than every strategy:

| method | vs matrix_v2 | vs structures | vs kalman_lna | vs blockwise |
|---|---|---|---|---|
| PCMCI+ | -0.241 [-0.277, -0.204] | -0.275 [-0.310, -0.239] | -0.253 | -0.225 |
| PCMCI+ with contemporaneous links | -0.154 [-0.182, -0.125] | -0.188 [-0.215, -0.159] | -0.166 | -0.138 |
| PCMCI | -0.182 [-0.211, -0.151] | -0.215 [-0.244, -0.187] | -0.194 | -0.166 |
| LPCMCI | -0.346 [-0.382, -0.311] | -0.380 [-0.419, -0.344] | -0.358 | -0.330 |
| Granger, pairwise | -0.098 [-0.122, -0.071] | -0.131 [-0.154, -0.108] | -0.110 | -0.082 |
| Granger, conditional | -0.085 [-0.108, -0.059] | -0.118 [-0.141, -0.096] | -0.097 | -0.069 [-0.093, -0.042] |
| row_reg | -0.032 [-0.052, -0.012] | -0.066 [-0.091, -0.040] | -0.044 | -0.016 [-0.035, +0.004] |

By noise (pooled F1). In the deterministic `none` cells, conditional-independence tests fail: every
level is an exact function of the past, so partial correlations are degenerate. With counts noise,
the regression-type tests get close to the strategies:

| | PCMCI+ | PCMCI | Granger, conditional | row_reg | matrix_v2 | structures | kalman_lna |
|---|---|---|---|---|---|---|---|
| none (524 cells) | 0.487 | 0.440 | 0.587 | 0.753 | 0.930 | 0.958 | 0.928 |
| counts (548 cells) | 0.669 | 0.773 | 0.852 | 0.882 | 0.868 | 0.901 | 0.883 |

### Kubernetes (300-317, 82 cells; strategies stored on 23-25)

| method | cells | precision | recall | F1 (pooled) | mean cell F1 |
|---|---|---|---|---|---|
| PCMCI+ | 82 (1 timeout) | 0.660 | 0.359 | 0.465 | 0.499 |
| PCMCI | 82 (2 timeouts) | 0.351 | 0.591 | 0.440 | 0.608 |
| LPCMCI | 82 (9 timeouts) | 0.770 | 0.326 | 0.458 | 0.445 |
| Granger, pairwise | 82 | 0.126 | 0.777 | 0.217 | 0.371 |
| Granger, conditional | 82 | 0.364 | 0.548 | 0.437 | 0.597 |
| row_reg | 82 | 0.378 | 0.648 | 0.478 | 0.687 |
| matrix_v2 | 24 | 0.897 | 0.559 | 0.689 | 0.783 |
| structures | 23 | 0.866 | 0.855 | 0.861 | 0.930 |
| kalman_lna | 23 | 0.831 | 0.831 | 0.831 | 0.917 |
| blockwise | 25 | 0.816 | 0.808 | 0.812 | 0.896 |

Paired on the cells the strategies ran: PCMCI+ is worse than structures by -0.488 [-0.623, -0.308],
PCMCI by -0.166 [-0.255, -0.082] and conditional Granger by -0.265 [-0.313, -0.203]. Against
matrix_v2, PCMCI is -0.024 [-0.125, +0.076] and conditional Granger -0.118 [-0.251, +0.065]: no
difference either way. Pairwise Granger is useless on the services (precision 0.13): almost every
pair tests significant, since the services share one traffic driver.

### Where it helps: lagged effects through hidden stocks and dead time

On the 90 Tests cells whose truth has a hidden stock, the multi-lag tests find the marginal edge
X -> (hidden) -> Y. The lag-1 strategies miss it:

| (paired cell F1, 90 cells) | vs matrix_v2 | vs blockwise | vs kalman_lna | vs structures |
|---|---|---|---|---|
| Granger, conditional (0.760) | **+0.186 [+0.061, +0.297]** | **+0.211 [+0.075, +0.320]** | +0.019 [-0.193, +0.227] | -0.130 [-0.236, -0.011] |
| PCMCI (0.679) | +0.106 [-0.055, +0.267] | +0.130 [-0.036, +0.283] | -0.062 | -0.211 [-0.327, -0.073] |
| row_reg (0.652) | +0.079 [+0.003, +0.178] | +0.103 [+0.030, +0.198] | -0.089 | -0.238 [-0.401, -0.060] |

The cases are 085-noisy-hidden-stock, 105-canonical-inventory-supply-line, 116 world3-pollution-full,
172-third-order-supply-line, 205/206 control-dead-time and 134-delayed-measured-input. There
conditional Granger or PCMCI reach mean F1 0.36-1.0 where matrix_v2 gets 0-0.5. `structures`, which
searches for hidden stocks and delays, already gets 0.71-1.0 on these and is the best method on the
hidden subset (0.890). A lag-2 Granger edge is therefore a cheap hint that a lag-1 strategy has
missed a delay. It is the same hint `structures`' hidden-stock search acts on, with physics.

### Where it fails
- **Deterministic runs (`none`):** PCMCI+ F1 0.49, PCMCI 0.44, against 0.93-0.96 for the strategies.
  Faithfulness and the CI tests break when there is no noise.
- **Low recall everywhere for PCMCI+/LPCMCI:** recall 0.48 and 0.37. Conditioning on lags and
  contemporaneous neighbours explains true links away in balancing loops. On loop cases PCMCI+ has
  precision 0.957 and recall 0.470. Counting its contemporaneous links raises recall to 0.73, but
  precision falls to 0.64.
- **Measured inputs (144 cells):** PCMCI+ recall 0.23 and F1 0.35, against 0.88 for row_reg and
  structures.
- **Eras and schedules (174 cells):** with no era information, every method's precision drops
  (Granger 0.53-0.63). The strategies use the announced eras and stay at 0.75-0.78.
- **Cases with no cross-stock edge (272 cells):** false edges from PCMCI 108, PCMCI+ with
  contemporaneous links 84, Granger 72-74, row_reg 43, PCMCI+ 18, LPCMCI 5, against 7-8 for
  structures, kalman_lna and matrix_v2.

### As a prior or check on the strategies' graphs
Keeping only the edges of a strategy that a method also finds always lowers F1. For structures on
Tests, F1 goes from 0.927 to 0.635 with PCMCI+, 0.771 with PCMCI, 0.860 with conditional Granger,
and 0.532 with LPCMCI. Adding the method's edges also always lowers it, to 0.723-0.905. The methods
confirm 13-53% of a strategy's false edges but also drop 7-60% of its true ones. LPCMCI is the
sharpest veto: it confirms 13% of structures' false edges, but only 40% of its true ones.

### LPCMCI's bidirected edges as hidden-stock hints

| cells | with a hidden stock | truly confounded pairs | flagged pairs | flagged and true | hidden-stock cells with a flag | other cells with a flag |
|---|---|---|---|---|---|---|
| 1265 | 99 | 4 | 455 | 0 | 13 of 99 (13%) | 249 of 1166 (21%) |

Most ladder hidden stocks are mediators (delay stages, X -> H -> Y), not common causes. LPCMCI
flags cells *without* a hidden stock more often than cells with one, and it found none of the 4 true
confounded pairs. As a hidden-stock detector it is noise.

## Verdict
The literature note's claim holds, now with numbers. Time-series causal discovery adds nothing to
the graph that the leading strategies find. Even our own row regression, used as a plain t test,
beats PCMCI+ by 0.22 pooled F1 on Tests. Conditional Granger is the best of the causal methods
(0.714 pooled F1, against 0.927 for structures). The only measured benefit is that multi-lag tests
recover delayed or hidden-mediated edges that lag-1 strategies (matrix_v2, blockwise) miss:
+0.19 / +0.21 paired cell F1 on the 90 hidden-stock cells. `structures` already finds those edges
better (+0.13 over conditional Granger), so the open idea is at most a lag-2 residual check inside
a lag-1 strategy, not a causal-discovery stage. LPCMCI's confounder flags are not a usable
hidden-stock hint. The interventional ideas (injections, eras) remain the causal ideas worth running:
[injection-response-judge](injection-response-judge.md), [injection-instruments](injection-instruments.md),
[invariant-rows](invariant-rows.md).

Not done: alpha and `tau_max` sweeps (one setting, alpha 0.01, chosen before any results), the GPDC
and CMI tests (nonlinear; much slower), VAR-LiNGAM, and the kubernetes cells the strategies have not
run (left out of the pairing as "not run").

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook section 6: in closed-loop, strongly forced systems Granger tests, transfer entropy and convergent cross mapping add little to the regression or point the wrong way (McCracken, Weigel 2014, Phys. Rev. E 90:062903; Sugihara et al. 2012, Science 338:496-500). Use only as a sanity baseline.
- [Causal inference](literature/causal-inference.md), section 2.2. Under causal sufficiency, no instantaneous effects and one graph over time, our row regression already *is* time-series causal discovery (Peters, Janzing, Schölkopf 2017; Eichler 2012; Eichler, Didelez 2010, Lifetime Data Anal. 16:3-32). PCMCI (Runge et al. 2019, Sci. Adv. 5:eaau4996), tsFCI (Entner, Hoyer 2010), SVAR-FCI and VAR-LiNGAM (Hyvärinen et al. 2010, JMLR 11:1709-1731) are graph-only, need faithfulness (which balancing loops break: Andersen 2013, Phil. Sci. 80:672-683), and ignore conservation. Keep them as an offline baseline. The one possible use is a latent-variable method (LPCMCI, tsFCI) flagging confounded pairs as a hint of a hidden stock or a shared unannounced inflow. The causal ideas worth running use injections and eras instead: [injection-response-judge](injection-response-judge.md), [injection-instruments](injection-instruments.md), [invariant-rows](invariant-rows.md), [probe-design](probe-design.md).
