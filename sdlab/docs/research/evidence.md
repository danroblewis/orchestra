# Evidence beside the pass: reasons to believe a found model is right

**Status:** built (2026-10-20). Six checks plus a confidence score, computed offline beside the
ladder's pass. The commits are `f496610` (push test), `0994163` (Kalman bound and likelihood),
`65a51c8` (NO-TRUTH checks), `08c0ebd` (evidence report, confidence model, `sdlab-ladder evidence`),
`d029e73` (review fixes: folds by family, missing agreement is missing) and `241e48e` (adversarial
fixes: the checks stop calling correct models wrong). `score.py` is unchanged, so the score hash and
every status are the same as before. Not yet shown in the UI.

## Why
The user (2026-10-20): a pass should mean there is a reason to expect the model is correct. That could
be several reports, ideally with a confidence score. The user also noted a cost. The per-number
tolerance was widened (up to max(10%, 3 SE), and wider on some cells) so that strategies could pass.
If a pass also had to meet every new check, it would fail as often as before and more. More failures
only help if agents can use the diagnosis to fix the strategy.

So the checks are **evidence, not gates**. Each check reports what it found. When it finds a problem,
it says what kind of wrong it points to: a missing or spurious path, a wrong sign, a drain too fast,
a common attenuation factor, or a limit of the data. The confidence score grades results and gates
nothing.

## The checks
Truth-side checks are scoring: they may use the truth. NO-TRUTH checks see only the discovery view
(the measured stocks, `t`, levels, eras, injections and inputs). Every NO-TRUTH call goes through
`notruth_core.check_view`, and a test bans those modules from importing anything that reads the truth.

| check | module | uses the truth | what it asks | what a failure diagnoses |
|---|---|---|---|---|
| **push test** (impulse and frequency response) | `pushes.py` | yes | Push the truth and the found model the same way and compare the responses of every measured stock | missing path, spurious path, wrong sign, a path too strong or too weak, a drain too fast or too slow (τ found vs true) |
| **Kalman bound** | `consistency.py` `bound_check` | yes | Is each number within 3 Cramér-Rao SEs of the truth (`noise_oracle._Kalman.se`), and does the joint chi-square pass? | method error, the run's draw (the truth's own refit is as far off), missing or spurious term, unidentified, a common factor (every number about ×F), re-parameterisation |
| **likelihood ratio** | `consistency.py` `likelihood_check` | yes (the truth's noise model) | Is the found model rejected against the truth's structure refitted on the same data? | rejected and where (which stock, a level offset or a slow error, which input the errors follow), cannot tell apart, fits better than the truth can (pieces placed on noise) |
| **residuals** | `notruth.py` | **NO-TRUTH** | Are the Kalman innovations white, unbiased and unrelated to inputs and injections? | "an inflow into X is understated", "the misfit follows input u: its push is understated", drift that tracks a level |
| **invariance** | `notruth.py` | **NO-TRUTH** | Refit the numbers per era, half and quarter. Are they stable? | "drifts steadily", "trades off against X: one of the flows is likely extra" |
| **held-out** | `notruth.py` | **NO-TRUTH** | Refit on the first 70%, then forecast the rest at 1, 5 and 20 steps against persistence | the model does not carry to new data |
| **agreement** | `notruth.py` | **NO-TRUTH** | Do the other distinct models on the cell make the same predictions and push responses? | disagreement with the best other model (consensus, not correctness) |

Existing evidence is reused, not rebuilt: **long run** (`longrun.py`, error far out and runaway) and
**strict** (`strict.py`, numbers about as good as the truth's own refits allow). Both are read from
their caches.

### Push test (`pushes.py`): the impulse-response idea, on the models
This is the model-side form of [injection-response-judge.md](injection-response-judge.md). Both models
run in the environment of the run's last step, held still. That means the truth's schedule as it
stands then, each input at its mean, and the truth's outside constant inflows given to the found
model. Both start from the truth's recorded end state, run until it settles. The battery is:
- an impulse into each measured stock (0.25 × its range; out of the stock when it sits at the top of
  its range);
- on each measured input and each outside inflow into a measured stock, a one-step **spike**, a
  **step** and **sines** at 0.25, 1 and 4 × 2πτ.

A response is the pushed run minus the unpushed run, per unit pushed. A comparison agrees when the
footprint (which stocks respond, above 1% of the push's largest true response) and the sign match.
The error must also be within tolerance: the relative 2-norm of the curves within 10% for impulses and
steps, and gain within 10% and phase within 10° for sines. `--reference K` refits the truth's own
structure on K runs (`strict.refit`), and each tolerance becomes max(fixed, 3 × the refits' rms
error). That is how "agrees within the data's limits" is reached. **agree** (the share of comparisons
that agree) is the graded score. Pushes that take the truth outside its recorded range are marked
`outside_data` and called extrapolations.

This answers the user's question about spikes in the inputs: **yes, but on the models, not on the
data.** Spikes, steps and sines go into every input and inflow of both the truth and the found model.
They test causal paths without asking discovery to see them. Designed probes in the *data*
([probe-design.md](probe-design.md)) and local projections that estimate the response from the data's
announced injections are still not built (see What to build next).

### Kalman bound and likelihood (`consistency.py`): the Kalman bound idea
`Cell(case, variant)` builds the truth's Kalman model of the run discovery saw (`noise_kf.model`, or
`clean_view` for counts, as `strict.refit` does). The **bound** compares each of the scorer's parts
with its joint Cramér-Rao SE. The joint chi-square is taken in the truth extended by the found model's
extra terms. Without that, a model that trades a true number for an extra term looks wrongly rejected:
on 301 counts-short, p moved from 1e-40 to 0.21 with it. Noise-free data use a 0.1% floor and have no
joint test. The **likelihood** is LR = 2 × (ll of the truth refitted − ll of the found model), both
under the truth's noise model. A model is rejected when LR > χ²₀.₉₉(df). The p value is the check's
own confidence. Bias variants fit the found model's bias too. On cells where the noise model rejects
the truth itself (floors, 220's two-way flow, 088#6 meas-long), a model is rejected only when it is
also worse than the true numbers (`noise_model_misfit`).

### Not covered
- The consistency checks do not cover truths with effects, co-flows, delays, MIN, switches,
  expressions or sub-steps. The likelihood also does not cover a found model with its own hidden stock
  or a non-linear flow.
- The push test does not cover real, physics or particle cases (there is no truth to push), or hidden
  stocks (they are never pushed or compared).

## The report and the confidence model
`uv run sdlab-ladder evidence [--strategies S] [--cases C] [--variants V] [--jobs ≤3] [--reference 3]`
fills `$SDLAB_LADDER_CACHE/evidence.sqlite` (per result and evidence code hash; agreement is also keyed
by the cell's result ids). It prints one line per result and then the confidence report. A report
holds `existing` (status, strict, extra complexity, long run), `truth` (pushes, bound, likelihood),
`notruth` (four checks) and `scores`. Python: `evidence.reports(rows)`; the model is in
`evidence_confidence.py`.

**The label "right"** is the AND of three components (each True, False or unknown):
- **structure**: recall 1 with no spurious part, or an equivalent the likelihood does not reject;
- **pushes**: the push verdict is not "differs";
- **numbers**: the bound is ok, or the likelihood does not reject.

**The confidence score** is P(right) from a logistic regression on 9 **NO-TRUTH** features: the four
verdicts, −log p of residuals and invariance, held-out skill, the share of other models that agree,
and agreement with the best other. One row per distinct model per cell. The out-of-fold folds are
grouped by case family (draws 045#1..#8 are one group). So the score could be computed on a real case,
where there is no truth.

### Calibration
| set | AUC | Brier (base rate) | within passes | notes |
|---|---|---|---|---|
| counts-short training set, 57 cases, 901 models, out of fold | 0.81 | 0.164 (0.223) | 0.68 | top bins overconfident: 0.86 predicted, 0.75 observed |
| Tests sample, refitted, 2543 models, 261 cases, out of fold by family | 0.87 | 0.142 (0.250) | 0.77 | 0.6–0.8 bin 0.71 predicted, 0.63 observed |
| **truly held out**: the counts-short model on the Tests sample's other variants | 0.66 | 0.374 (0.250) | 0.45 | ranking partly carries over, calibration does not |
| … noise-free cells only | 0.86 | — | — | predicts 0.03 where 69% are right: residuals reject nearly every model on noise-free data |
| … counts-long / other noisy | 0.79 / 0.75 | 0.191 / 0.151 | — | |
| kubernetes 300–303, out of fold (129 models, 4 cases) | 0.88 | 0.064 (0.187) | — | |

For reference, the scorer's pass used as a 0/1 score has AUC 0.88–0.91 against the label. Part of
that is circular, because the label shares structure with the score. The confidence score is useful
for **ranking within a variant family** and needs per-family calibration before its numbers can be
read as probabilities. The strongest features are `agree_share` (single-feature AUC 0.85 on the
sample) and `agree_best` (0.77). They measure **consensus between strategies, not correctness**, and
many strategies share code.

## Results
### Kubernetes 300–303 (46 roster:kubernetes strategies, 20 cells, 919 passes and 1 fail)
| check | passes with a problem |
|---|---|
| push mismatch | 119 (303 meas-long 45, meas-short 46, 301 counts-short 25, 3 others) |
| likelihood rejects | 117 of the 551 it covers (303 meas 91, 302 counts-long 22) |
| outside the Kalman bound | 135 (303 meas 91, 302 counts-long 28, 301 counts-short 6, 303 counts-short 6) |
| long-run error above strict's reference | 130 (303 meas 91, 301 counts-short 29; no hard fails) |

- **The evidence supports 775 of the 919 passes (84%)** by the label, and 144 not. 761 pass every
  check that covers them, but only 393 are covered by all four.
- Every pass on the none-* cells and on 300 is right. The single fail (odefit, 303 meas-long) fails
  every check.
- **303 meas-long and meas-short: all 91 passes have every number about ×0.93 of the truth.** For
  example, lna finds 0.926 / 0.555 / 0.462 against 1 / 0.6 / 0.5, with z −35 to −42, LR ≈ 2500 on
  df 3, and push agreement 0.74. The truth's own Kalman refit on the same run is not off this way.
  Diagnosis: method error, common factor. This is errors-in-variables attenuation from regressing on
  noisy levels, which the wide per-number tolerance accepts. The NO-TRUTH residual check finds it too,
  without the truth: it contradicts every sampled model on 303 meas-short ("an inflow into
  responses_total is understated"). effect_hats and inflow_effects are the worst (×0.78, agreement
  0.38).
- **301 counts-short: 31 of 46 passes push "differs", but the likelihood cannot tell any of them from
  the truth.** 19 agree on 92% (one sine gain about 18% off). That is a data limit that 3 reference
  refits do not widen enough, not a method error.
- **302 counts-long: 22 passes are rejected by the likelihood with 100% push agreement.** Their numbers
  are off by 0.5–0.7%, with z 3.9–5.7.
- **301 none-short: shared_noise's "equivalent" (a link plus a drain instead of a move) agrees on
  100%.** Pushes on measured stocks cannot tell these two apart.

### Tests sample (300 cells on 261 cases, every variant except counts-short; 13,799 results)
| status (n) | push mismatch | likelihood rejects (of covered) | bound out (of covered) | long-run problem (of covered) | label right / wrong / unknown |
|---|---|---|---|---|---|
| pass (6505) | 272 | 77 / 2430 | 140 / 6344 | 267 / 4917 | 6084 / 260 / 161 |
| equivalent (1940) | 441 | 19 / 533 | 1562 / 1754 (expected: other parameters) | 0 | 1336 / 418 / 186 |
| fail (5354) | 5185 | 1523 / 2481 | 3569 / 3586 | 345 / 5170 | 47 / 3539 / 1768 |

- **The evidence supports 96% of known-label passes (6084 of 6344).** Of the 260 wrong ones, 218 are
  wrong by pushes alone.
- **Real spurious paths that the scorer passes:** 58 passes have a wrong footprint. On 042#2
  counts-long, matrix_v2 and a group of 6 have B2 rising 0.87–0.90 per unit after a step in A1's
  inflow, where the truth's B2 does not move. The step stays inside the data.
- **Slow-drain gains:** 044#7 (42 passes), 039#4 (30) and 060 (25) counts-long have steady-state gains
  1.13–1.29× the truth's. Long run flags them, but the likelihood cannot tell them apart.
- **Possible scorer false negatives:** 47 fails (16 distinct models in 7 cells) look right on every
  check. They are 18–46% off on a number that the data cannot pin down (085 bias-short, 048#2
  counts-long, 011 and 083 links, 086 bias-short). The "numbers" label is lenient (bound ok OR not
  rejected), so most of these count as right only because the likelihood cannot tell.
- **The push label gates too hard.** Of the 272 push mismatches among passes, 181 are cases where the
  likelihood cannot tell the model from the truth (138 of them also inside the bound), and only 4 are
  rejected. This is the user's point: push agreement is better read as a graded score than as a gate.

## Reviews
- **Leakage audit (`d029e73`).** No feature reads the truth, the case id, hidden stocks or the
  variant, and the stored flows are the strategies' own output. Two bugs were fixed:
  1. The folds were grouped by case, so draws of one parametric family landed on both sides of a fold.
     They are now grouped by family. AUC barely moved, but one calibration bin worsened (0.69 → 0.63
     observed).
  2. A cell re-run after the fill had its agreement counted as neutral 0.5 values. It is now left out
     as missing.

  Not fixed: the agreement features measure consensus, and `notruth.py`'s thresholds were tuned on
  counts-short.
- **Adversarial review (`241e48e`).** It found seven ways the checks called correct models (the truth
  itself) wrong, and fixed them:
  - bias variants: the found model's bias is now fitted;
  - weekly refits that ended below the true numbers;
  - cells where the noise model rejects the truth itself;
  - unidentified numbers counted against the model;
  - two negligible responses judged by their ratio;
  - a stock pushed above its range;
  - extrapolated pushes, now marked.

  On 74 cells, 14 passes' push "differs" became agrees, 14 bounds became ok and 16 likelihood
  rejections went away. Nothing became newly wrong. The review searched for clean passes that are
  causally wrong but called right, and found none. It used 4× pushes, downward impulses and operating
  points at 1/3 and 2/3 of the run, on 303 models. Only 016-coflow changed at 4× size (a
  non-linearity). The remaining issues are in `noise_kf.py`: two-way flows give a negative Q, floors
  are treated as linear, and meas is miscalibrated at 088#6.

## Limits
- **One operating point.** The push test compares responses at the run's last step, settled. MIN,
  floors and switches are probed only in the regime that holds there. For non-linear models only the
  fixed push sizes are measured.
- **Only measured stocks are compared.** A move is indistinguishable from a link plus a drain when
  both stocks are measured. Hidden stocks are not pushed.
- **Fixed tolerances are not calibrated.** These are 10%, 10° and the 1% footprint. The reference
  uses 3 refits, which is too few to widen them where the data are weak.
- **The noise-free bound floor of 0.1% is a choice, not a measurement.** It flags a 0.37% error on
  043#7 none-short.
- **Consistency coverage is linear only** (see Not covered). 90 of 991 training models and many of the
  sample's fails have an unknown label.
- **The confidence model is calibrated on counts-short only.** It does not transfer to noise-free
  data. Its strongest features are consensus. Logistic coefficients are not monotone.
- **Strict is read only.** Cells without a strict reference show "pending".
- **Results are on the cells listed** (counts-short training set, 300 sampled Tests cells, 300–303),
  not on the whole ladder. The run's outputs are in the session scratchpad
  (`evall/k8s.json`, `evall/tests.json`), under evidence code hash a9b3ba06f5d5034c; `241e48e` changed
  the hash since, so the cache is stale.

## What to build next
1. **UI.**
   - On the result page, show the evidence panel: the verdict of each check, the diagnosis sentences,
     the push table (true vs found responses, footprint) and the confidence score.
   - On the case page, show per cell how many passes the evidence supports and the common diagnoses
     (for example "every number ×0.93").
   - The summary carries `evidence` and `confidence` beside `strict`, read from the cache as strict
     is.
   - The integration step has to pass `agree_in_range` and `outside_data` from pushes, and
     `noise_model_misfit` and `bias` from the likelihood, into the report.
2. **The kubernetes competition's reports.** Each round's report lists, per strategy, the passes the
   evidence does not support and the diagnosis. Example: the 303 meas attenuation, ×0.93 on every
   number, is one errors-in-variables fix away from 91 better passes. Rank strategies by push
   agreement and confidence, not only by pass.
3. **A graded "supported pass".** Use push agreement ≥ some share, or footprint_ok, together with
   "not rejected by the likelihood". Use more reference refits (strict uses 1+6). Then a pass with
   evidence is a label agents can aim at without the cliff the user warned about.
4. **Recalibrate per variant family** (noise-free, counts, meas and the rest), for example with
   isotonic regression. Handle noise-free residuals separately.
5. **Data-side impulse responses.** Local projections on announced injections
   ([injection-response-judge.md](injection-response-judge.md)'s responses.py) are not built. They need
   probed variants (`--probes K`), and with them a probed variant gives a model-free response table.
6. **Designed spikes in the data** ([probe-design.md](probe-design.md)): new variants with chosen
   input spikes, so that a discovery run can see the causal paths the push test checks. These need
   case or variant changes and the user's approval (invariant 2).
7. Extend the bound and likelihood to effects, co-flows and found hidden stocks (an extended Kalman
   filter), and fix `noise_kf`'s two-way Q.
