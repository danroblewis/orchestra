# Review: the hidden-stock oracle (commit c9b6072)

Status: independent review, 2026-10-18. Read-only on code; this file is the only change.

**Verdict: keep, with one change.** On the stored seeds the standard errors are honest, and the
4 changed cells are rightly passes. The rule is the same one the linear oracle uses (z = 3 SEs from
the truth). The shared filter does not bias the verdict, and wrong structures still fail. There is one
bug. On about 20% of fresh seeds of the short variants (13% on 026), the delay's SE comes out 5x too
small. The cause is a kink in the likelihood, and it makes the scorer *stricter*, never more lenient.
Taking the Hessian with a larger step fixes it, and the fix does not change the 4 cells.

## The 4 changed cells

Re-scored with `score.equations` on the stored found models (`sdlab.ladder.store.latest(...,
found=True)`), once with the hidden oracle and once with it replaced by a stub that has no SEs. The
"z" columns give |found - true| / SE. A part passes when z <= 3, or when it is within 10%.

| cell | before | after | the numbers that needed the SE (z) | verdict |
|---|---|---|---|---|
| hidden_transit 015 counts-short | fail | pass | B drain 0.2221 (1.9), inflow 21.56 (1.4); delay 10.6 within 10% | correct pass |
| mass_balance 015 counts-short | fail | pass | k_in 0.2253 (2.2), delay 11.26 (1.0), B drain 0.2318 (**2.7**), inflow 22.52 (2.3) | correct pass, close to the edge |
| mass_balance_all 015 counts-short | fail | pass | the same found model as mass_balance | correct pass, close to the edge |
| mass_balance 026 counts-short | fail | pass | k_in 0.2300 (**2.85**), delay 11.25 (1.2), B drain 0.2283 (2.7), inflow by window 11.33 / 34.55 / 11.18 (2.2 / 2.8 / 1.9) | correct pass, close to the edge |

The oracle's own fit on 015 counts-short (seed 15) gives k_in 0.2150, delay 10.54, B drain 0.2215
and inflow 21.50. hidden_transit's numbers match these to within 0.3%: hidden_transit *is* the
maximum-likelihood estimate on this run. Its 11% error on B's drain is in the data, not in the
method. This is invariant 4's "the data's limit", and the case invariant 5 allows.

On the stored seeds 15 and 26, H's start sits at its bound (0), so the kink below does not occur.
The SEs are identical with Hessian steps of 1e-4, 1e-3 and 1e-2, so the fix leaves all 4 cells as
they are.

## 1. Is the SE honest?

Monte Carlo: 300 fresh seeds (10000-10299) per case and variant. Each seed was simulated with the
case's true model through `sdlab.ladder.data.simulate`, then fitted three ways:

- the oracle (`hidden_oracle._fit`);
- **complete-data GLS** (my code): a regression of A's, H's and B's changes on the truth's structure,
  with H's recorded level known and iterated with the flows' Poisson covariance. It is an independent
  method with more information than any strategy has;
- **NLS without H** (my code): k_in and the inflow by OLS on A's row, then d, kb and H₀ by nonlinear
  least squares of B's change on H rebuilt from A's path. It is independent and consistent, but not
  efficient.

Columns: the standard deviation of the oracle's estimate across seeds ("MC sd"), its median SE, the
share of seeds where the truth lies within 3 and within 2 SEs, and the spread of the two independent
estimators.

| case / variant | number | MC sd | median SE | cover 3 SE | cover 2 SE | GLS with H, sd | NLS, sd |
|---|---|---|---|---|---|---|---|
| 015 short | k_in | 0.0113 | 0.0106 | 0.993 | 0.943 | 0.0092 | 0.027 |
| | B drain | 0.0111 | 0.0105 | 0.997 | 0.953 | 0.0098 | 0.027 |
| | delay | 1.40 | 1.28 | **0.865** | 0.798 | 0.47 | 2.20 |
| | inflow | — | — | 0.993 | 0.939 | | |
| 015 long | k_in | 0.0039 | 0.0042 | 1.000 | 0.963 | 0.0060 | 0.013 |
| | B drain | 0.0039 | 0.0042 | 1.000 | 0.970 | 0.0059 | 0.013 |
| | delay | 1.13 | 1.08 | 0.980 | 0.960 | 0.30 | 2.31 |
| 026 short | k_in | 0.0101 | 0.0100 | 0.993 | 0.939 | 0.0084 | 0.022 |
| | B drain | 0.0103 | 0.0101 | 1.000 | 0.953 | 0.0088 | 0.022 |
| | delay | 1.00 | 1.10 | **0.939** | 0.882 | 0.43 | 1.44 |
| | inflow (per window) | — | — | 0.997 | 0.949 | | |
| 026 long | k_in | 0.0041 | 0.0038 | 0.993 | 0.945 | 0.0031 | 0.008 |
| | B drain | 0.0041 | 0.0038 | 0.993 | 0.928 | 0.0032 | 0.008 |
| | delay | 0.39 | 0.42 | 0.990 | 0.948 | 0.16 | 0.51 |

- **k_in, B's drain and the inflow are honest.** Their SEs match the Monte Carlo spread, and 3 SEs
  cover the truth 99.3-100% of the time. The maximum-likelihood estimate is unbiased: the mean error
  is below 0.06 SE everywhere, and the delay on 026 short is off by +0.13 (0.13 SE). An unbiased
  estimate means the filter does not pull the centre of the tolerance towards a wrong value.
- **The size of the delay's SE is real.** Without H, the delay is poorly pinned down. The NLS spread
  is even larger (1.4-2.3), and only an estimator that sees H gets to about 0.3-0.5. On 015 long the
  run sits at its equilibrium after the first transient, so 2000 steps still leave an SE of about
  1.1. The Monte Carlo spread confirms this.
- **Bug: the delay's SE collapses on some seeds.** On 60 of 297 seeds of 015 short (39 of 297 on
  026 short, 8 of 299 on 015 long), SE(d) is about 0.002, against a typical 0.012. That is smaller
  than the SE you get when H is observed (0.005), which is impossible. These seeds account for 40 of
  the 44 non-covered seeds on 015 short.
  - **Cause.** H's start (m0) is free in these fits and lands at about 0.5. There, d·m0 ≈ 0.05, which
    is exactly `FLOOR` in `vp = max(d * max(m, 0), FLOOR)`, so the likelihood has a kink at the
    optimum. With `hstep = 1e-4`, the numerical Hessian measures the kink and not the curvature.
  - **Effect.** The SE changes with the step: 0.0021, 0.0058 and 0.0100 at steps 1e-4, 1e-3 and
    1e-2. With `hstep = 1e-2`, 3-SE coverage of the delay is 0.997 / 0.997 / 1.000 / 1.000 (015
    short / 015 long / 026 short / 026 long). The fits that previously failed with no oracle also
    mostly succeed (297→300, 291→298).
  - **Direction.** The bug only shrinks the allowance. The delay falls back to the 10% rule, so it
    can turn a pass into a fail and never a fail into a pass.

## 2. Does sharing the filter bias the verdict?

The oracle's estimate is never compared with the found model. Only its SE is used, and the
tolerance is centred on the true number. The only route to bias would be an SE inflated by a wrong
likelihood, and part 1 shows the SE matches the independent Monte Carlo spread. Below, deliberately
wrong found models are scored on the stored runs. Each is the truth with the hidden part replaced by
one `via` flow, and the result is shown new (old).

| found model | 015 short | 015 long | 026 short | 026 long |
|---|---|---|---|---|
| truth | pass (pass) | pass (pass) | pass (pass) | pass (pass) |
| delay 13 (+30%) | **pass** (fail) | **pass** (fail) | **pass** (fail) | fail |
| delay 7 (−30%) | **pass** (fail) | **pass** (fail) | **pass** (fail) | fail |
| delay 15 (+50%) | fail | fail | fail | fail |
| mirror (delay 5, B drain 0.1) | fail | fail | fail | fail |
| direct A → B, no hidden stock | fail | fail | fail | fail |
| hidden_transit's errors ×1 (k .216, delay 10.6, kb .222, inflow +7.8%) | pass (fail) | fail | pass (fail) | fail |
| the same errors ×1.5 | fail | fail | fail | fail |
| the same errors ×2 | fail | fail | fail | fail |
| the same errors, opposite sign | pass (fail) | fail | pass (fail) | fail |

- The mirror and the direct move fail on every variant. The mirror has the same mean response,
  because the transfer function is symmetric in d and kb, but it misses by 5 steps and its drain is
  off by 50%. The structure check is unchanged.
- A delay off by 30% now passes on 015 short and long and on 026 short. This is honest, not a leak.
  The truth's own maximum-likelihood delay has a Monte Carlo sd of 1.0-1.4 steps there, so a 3-step
  error is 2-3 sd. Even an estimator that sees H has a delay sd of 0.3-0.5. On 026 long (sd 0.39)
  the same error fails.
- Errors in hidden_transit's direction and errors in the opposite direction are treated the same.
  1.5x either fails. Nothing favours the direction the shared filter would produce.

## 3. Consistency with the linear oracle (`oracle.py`)

- **The same.** The rule is `max(rel x true, floor, z x SE)` with z = 3, centred on the truth, from
  the truth's own structure fitted on the same run, and only on noisy variants. The structure and
  spurious-part checks are untouched.
- **The delay.** It gets `max(rel x delay, z x SE)` with no floor term, which matches how the delay
  was scored before.
- **The SE estimate differs, in the stricter direction.** The linear oracle uses OLS SEs: residual
  variance with per-stock regressions, and an outflow's SE combined in quadrature. The hidden oracle
  uses the observed information of a Poisson-variance likelihood, which is the efficient estimator.
  If anything, its SEs are smaller than an OLS-style oracle's would be.
- **A known count scale.** It assumes a count scale of 1, unlike the linear oracle's estimated
  residual variance. That is correct for the engine's Poisson counts, and the coverage above confirms
  it. Overdispersed data would need the scale estimated, but the ladder has none.

## Changes recommended

1. **Make the Hessian robust to the `FLOOR` kink.** Use `hstep = 1e-2`, which is tested above and
   gives 99.7-100% coverage. Alternatives: hold H's start at its truth value, or smooth the floor
   (softplus). Changing the step changes the score hash and re-scores, but leaves the 4 cells and
   seeds 15/26 unchanged.
2. **Add a test** that fits about 50 fresh seeds of 015 counts-short and checks that the delay's
   3-SE coverage is at least 0.97 and that no SE(d) is below the complete-data SE. The current tests
   check the stored seed only. The commit's "SEs match over 30 seeds" compared the mean SE (1.11) with
   the sd (1.40), and that hides the 20% of seeds where the SE is 5x too small.
3. **Report the margins.** mass_balance's passes sit at z = 2.7-2.85 on several numbers at once. They
   are legitimate under the rule, but they are fragile. They also differ from the maximum-likelihood
   estimate by about 2 SEs, which is method error and not data limit, so the research doc should
   not call them "at the data's limit".

## How the numbers were made

Single-threaded (`OMP_NUM_THREADS=1 ...`), with code at c9b6072 and later (HEAD 40a0579). The scripts
are scratch files from this review session, not part of the repository:

- `mc.py <case> <variant> 300 10000`: Monte Carlo of the oracle, the complete-data GLS and the NLS.
  `an.py` summarises it.
- `hx/ho_copy.py`: a copy of `hidden_oracle.py` with the Hessian step as a parameter.
  `hx/probe.py` gives the SE against the step for chosen seeds, and `hx/mc2.py` gives the coverage
  at steps 1e-4 and 1e-2.
- `wrong.py`: the wrong-model scores and the re-score of the 4 cells with and without the oracle.
