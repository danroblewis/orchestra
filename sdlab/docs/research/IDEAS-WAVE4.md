# Wave 4: new hypotheses for discovery

Written 2026-10-17. Context: on benchmark v2.1 the main line meets the goal on only 12-17 of 62 runs.
Every wave 1-2 mechanism (hidden stocks, floors, shared noise, PySINDy products, symbolic-regression
effects) found real structure but was let down by the acceptance step or the judge. Wave 3 is now
running: bench instrumentation, the procedural generator, the behaviour-consistency gate and a
piece-proof judge. So are structure search, gradient descent and numerical optimisation from wave 2.

This document lists everything brainstormed for wave 4, selects the ideas **not already covered** by a
done, running or documented topic (or that take a genuinely different route), and gives each one a
ready-to-run brief. Each selected idea also has its own topic document in this folder.

**Inputs.**
- The goal, loop and experiment log; every topic document; the playbook; the six literature reports;
  the tools survey.
- The code: `identify.py`, `matrix.py`, `regression.py`, `changes.py`, `flows.py`, `simulate.py`,
  `sdtruth.py`, `grade.py`.
- A per-example failure analysis made for this document (below).

**Failure analysis.**
- The main line was run on 19 failing runs (scripts in the session scratchpad, not in the repository).
  For each run it printed the chosen model's flows and graded *every* candidate next to its judge
  error.
- A census of the truth models was made (`truth.model.json`): rate forms, `uses`, effects, hidden
  stocks, unannounced changes to internal flows, short pulses, and exact invariants among the measured
  levels.
- The truth was used only to study failures. Nothing proposed here lets discovery see it.

---

## 1. What the failing runs show

| Pattern (evidence from v2.1 runs) | Where | Covered so far? |
|---|---|---|
| **A used stock runs dry and caps a flow.** The source queue piles up 7-14 times its level (print-shop mono_queue 400 -> 5590; bakery orders 86 -> 677; cloud-credits queued 18 -> 146). The source's fitted drain collapses (bakery 0.005 + link 0.057 vs 0.5; print-shop 0.008 + link 0.078 vs 0.5; cloud-credits 0.16 vs 0.3), pieces fill the gap (print-shop long: 1362), and the model runs away when fed true inflows (skill@20 -1170%, -529%, -859%). | bakery, print-shop, cloud-credits, kanban, restaurant, clinic-doses, brewery, hospital, moderation | No. count-likelihoods reads `per` from shared noise but keeps the starved steps in the fit; censored-floors censors a stock's *own* outflows only. |
| **An internal flow's equation changes without being announced.** Day/night posting rates; season open/closed launch goals; restock times 10 -> 60 -> 40. Pieces absorb the constant part, never the coefficient. On sd-moderation every candidate predicts the data worse than persistence (judge 3.2 default, 6.6 long); fishery default 1.4. | 14 of 31 truths (moderation, fishery, bakery, print-shop, farm-soil, saas, university, manufacturing, orders, supply, ci, brewery, emergency, learning-curve) | No. regime-models covers the outside inflow only. |
| **Inflow pieces everywhere, on periodic schedules.** Hundreds of pieces (print-shop long 1362, ev-fleet default 294, support-tiers 103) while every schedule repeats with a fixed period (daily 24, weekly 7, sprints of 14). | all; strongest in ev-fleet, emergency, hospital, moderation, clinic, kanban | Partly: inflow-innovations and complexity-budget change how changes are found and counted; none uses periodicity. |
| **Pulses**: 1-step deliveries and 3-6-step bursts, which the 5-step minimum piece cannot hold. The drain absorbs them instead (clinic doses drain 0.41 and "expired -> doses" link 2.26; truth 0.02). | clinic-doses, kanban, support-tiers, university, moderation | No (the outlier taxonomy is in the signals report only). |
| **Moves paced by a third stock**, read as an outflow to outside plus a link ("flagged drains faster when moderators is high 1.387" + "None -> removed, link from moderators 0.676"); gaps on another stock read as outflows ("on_order drains faster when shelf is high"). | support-tiers, moderation, fishery, ev-fleet, housing, restaurant, supply, university, webshop, manufacturing | Only as the reaction-networks stub. |
| **Hidden delays read as an outflow to outside plus pieces into the receiver** (cloud-credits: running -> outside 0.44 vs 0.25 into postproc; results gets 36 pieces). | 20 of 31 truths have a hidden stock | hidden-stocks (grid, done) and delay-deconvolution (kernel); not via mass balance. |
| **The best candidate exists but is not picked, often by a hair.** emergency default: chosen judge 0.396 grades 5%, per-era candidates at 0.401 grade 73-75%. clinic-doses long: 0.526 grades -347%, 0.536 grades -77%. bakery default: constant inflows grade 27% vs -1170% chosen. | emergency, clinic-doses, bakery, kanban, learning-curve, pipeline | Piece-proof judge (running) attacks one cause; ties and per-stock choices are not covered. |
| **Exact invariants** (fishery boats in port + at sea = 40) make columns collinear, which yields cancelling outside flows and links read off the wrong member. | fishery, ev-fleet | identifiability (generic) only. |
| **Stretches with no inflow** (doors closed, off season, six days in seven without a delivery), where drains could be read off recessions. | restaurant, farm-soil, clinic-doses, kanban, fishery, emergency | No. |

---

## 2. Ranked selection (by expected value)

| Rank | Slug | Hypothesis in one sentence | Targets | Cost |
|---|---|---|---|---|
| 1 | [starved-coflows](starved-coflows.md) | Co-flow examples run away because the source row is fitted through stretches where the used stock is dry; masking those stretches and declaring `uses` (which the simulator caps) recovers the flow. | bakery, print-shop, cloud-credits, clinic-doses, kanban, restaurant, brewery, hospital, moderation | medium |
| 2 | [latent-eras](latent-eras.md) | Unannounced changes to internal coefficients recur, can be found as regimes in local coefficient estimates, and the era machinery then fits them as it fits announced eras. | moderation, fishery, bakery, print-shop, farm-soil, university, manufacturing, orders, supply, saas, ci, emergency | medium-large |
| 3 | [periodic-inflows](periodic-inflows.md) | Outside inflows as one period's profile repeated (plus a slow level) have few parameters, cannot absorb non-periodic dynamics, and can forecast held-out blocks. | ev-fleet, emergency, hospital, moderation, clinic-doses, kanban, restaurant, print-shop, support-tiers, services | medium |
| 4 | [row-crossover](row-crossover.md) | Picking each stock's row from the 16 candidates (greedy swaps judged on the whole model) reaches combinations no single candidate has. | bakery, clinic-doses long, pipeline default, emergency, learning-curve | small |
| 5 | [impulse-inputs](impulse-inputs.md) | One-step pulses and short bursts detected jointly with the row (Chen-Liu) stop deliveries being absorbed by drains. | clinic-doses, kanban, support-tiers, university, moderation | small-medium |
| 6 | [mass-balance-hidden](mass-balance-hidden.md) | A hidden delay's level is the cumulative gap between a stock's found loss to outside and another's found pieces; reconstructed and checked for stationarity, it becomes a stock. | cloud-credits, sawmill, learning-curve, webshop, restaurant, fishery, kanban, ev-fleet, housing, support-tiers | medium |
| 7 | [paced-moves](paced-moves.md) | Reading the matrix as stoichiometry x rate laws turns "outflow + link" pairs into moves paced by a third stock, and outflows into gap inflows, with one shared, conserved coefficient. | support-tiers, moderation, fishery, ev-fleet, housing, restaurant, supply, university, webshop | small-medium |
| 8 | [recession-drains](recession-drains.md) | Drains fitted on quiet stretches (no inflow), with the inflow then inverted with the drains fixed, avoid the drain/pieces confounding. | pipeline default, restaurant, farm-soil, clinic-doses, kanban, fishery, emergency | small |
| 9 | [llm-critic](llm-critic.md) | An LLM shown the found model, names, units and residual diagnostics proposes typed edits; our fitter and judge verify each. | print-shop, support-tiers, moderation, fishery, housing, ev-fleet | medium |
| 10 | [judge-ties](judge-ties.md) | Candidates within one bootstrap standard error of the best are tied; picking the simplest of the tie set avoids chance wins. | emergency, clinic-doses long, kanban, webshop | small |
| 11 | [conserved-totals](conserved-totals.md) | Exact invariants among same-unit stocks mark closed subsystems: no outside flows, one redundant column, a declared representation. | fishery, ev-fleet | small |
| 12 | [persistence-fallback](persistence-fallback.md) | Where the chosen model is worse than persistence on the data itself, silencing or shrinking the failing rows bounds the damage. | moderation, fishery, restaurant @100 | small |
| 13 | [ar-rows](ar-rows.md) | Rows fitted with an AR noise model (feasible GLS) remove the closed-loop bias that coloured residuals put into drains. | hidden-stock receivers; services | small |
| 14 | [era-instruments](era-instruments.md) | Announced era switches upstream are strong instruments for downstream drains biased by pieces. | era examples with pieces | small-medium |
| 15 | [evolve-discovery](evolve-discovery.md) | LLM-guided evolution of one rule-heavy module at a time, scored on generated models, searches alternatives faster than hand loops. | all | large |

**Suggested wave 4 (in parallel):**
- 1, 2, 3, 4, 5, 6 and 7 as independent strategies, each with its mechanism test.
- 8 and 10 as small add-ons.
- 9 as a probe on 6 runs before any bench.
- 15 waits for the generator.

Each is measured against `--baseline v2.1`, with bench instrumentation's columns as they become
available. Pairs worth testing together afterwards: 1 with count-likelihoods (`per` from covariance);
2 with 3 (day/night regimes are periodic); 3 with 5 (periodic pulses); 4 with the piece-proof judge;
6 with the behaviour gate.

---

## 3. Briefs (selected ideas, in rank order)

### 1. starved-coflows: co-flows found where the used stock runs dry

**Hypothesis.**
- In the co-flow examples the used stock runs dry for stretches: about 10% of steps for bakery flour
  and 15% for cloud-credits credits; for print-shop, toner near 30 g and paper at 64-108 sheets while
  the supplier is late.
- While it is dry, the engine scales the flow to what the used stock holds, so the source queue piles
  up and its row, fitted through both regimes, gets a drain a fraction of the truth.
- Inflow pieces absorb what is left, and the uncapped model runs away when fed the true inflows.
- Because `simulate.Model` and the grader already cap any flow that declares `uses`, finding the
  `uses` and fitting on unstarved steps should both remove the runaway and recover the drain.

Evidence (v2.1 runs, found vs truth):

| run | found | truth | skill@20 |
|---|---|---|---|
| bakery default | orders -> shelf 0.0046 + link 0.057 | 0.5 | -1170% |
| print-shop default | mono_queue -> done 0.008 + link 0.078 | 0.5 | -529% |
| cloud-credits default | queued -> running 0.16 | 0.3 | -859% |

The census finds starvation in 9 examples.

**Change.**
- Strategy `starved_coflows`, module `discovery/starvation.py`, using `matrix.identify_one`'s rows.
- Steps:
  1. Candidate co-flows are cross terms "C drains faster when A is high" in a row of any unit.
  2. C's starved steps are those where C's start-of-step level is below what that term takes in one
     step.
  3. Accept a candidate only if A's residual is positive on C-starved steps.
  4. Refit A's row and its receivers' rows with those steps masked.
  5. Estimate `per` on unstarved steps as C's loss over the flow's fitted amount (a flow-rate column).
  6. Emit the move with `uses`, drop the cross term, and enter the result as a candidate.

**Mechanism test** (`tests/test_strategy_starved_coflows.py`, `synth.generate`):
- Model: orders (inflow 40) -> shelf at 0.5 x orders, using 0.5 flour per unit. Shelf drains 0.25.
  Flour is restocked by a gap (goal 600, time 10), switched unannounced to time 60 for 60 steps of
  each 250. 1000 steps.
- Baseline: orders' drain below 0.25 and skill@20 below 0.
- Strategy: k within 0.05, `per` within 0.1, skill@20 above 0.9.
- Controls: fast restock (flour never below 200) gives the matrix result within 0.01. A real outflow
  of C driven by A without starvation gets no `uses`.

**Target examples.** bakery, print-shop, cloud-credits (both lengths), clinic-doses, kanban,
restaurant @100, brewery, hospital, moderation.

**Expected effect.** The largest tail gain on the board: three to four runs from -500%..-1170% to
positive. Mean skill@20 +10 to +20 points (each run clipped at -100%), and a few runs newly meeting
the goal.

**Dependencies and risks.**
- Starved stretches often coincide with unannounced restock-time changes (latent-eras), and pieces
  can still absorb the pile-up, so test it behind the piece-proof judge.
- Masking 10-15% of steps costs data on short runs.
- `per` and k are jointly identified only on unstarved steps.
- Complements count-likelihoods, which reads `per` from covariance.

**Cost.** Medium. One module plus a reading step; about 20% more run time.

### 2. latent-eras: unannounced eras found as recurring regimes

**Hypothesis.** 14 truths change an internal flow's equation without announcing it (census). Pieces
absorb only the constant part of such a change. Local coefficient estimates show the switches
directly, and once labelled, the era machinery already handles them: on v1 it took sd-eras long from
-1748% to 50% and sd-fishery default from 27% to 97%. On sd-moderation every candidate is worse than
persistence on the data (judge error 3.2 default, 6.6 long); on sd-fishery default, 1.4.

**Change.**
- Strategy `latent_eras`, module `discovery/regimes.py`.
- Steps:
  1. Per row, compute windowed or Kalman-smoothed time-varying coefficients on the chosen columns.
  2. Fit a Markov-switching regression with K = 2-3 regimes, choosing K and the switch count by BIC.
  3. Share regimes across rows whose switch times coincide.
  4. Append them to `opts["eras"]` as synthetic labelled eras and run with `split_eras`.
- A regime must recur (at least 3 switches each way) and must change a coefficient, not only the
  constant.

**Mechanism test.**
- Model: creators (inflow 20, drain 0.008) -> screening by a link that switches between k = 0.1 and
  k = 0.03 every 12 steps, unannounced; screening -> published 0.5; 2000 steps.
- Baseline: skill@20 below 0.5.
- Strategy: two regimes, switch times within 1 step, k within 0.01, skill@20 above 0.9.
- Controls: an outside-inflow change alone gets no regime; an unchanging model gets K = 1.

**Target examples.** moderation, fishery, bakery, print-shop, farm-soil @100, emergency, university,
manufacturing default, orders, supply, saas, ci.

**Expected effect.** moderation and fishery from below 0 to above 50%; elsewhere better drains where
pieces now absorb coefficient changes. +5 to +10 points of mean skill.

**Dependencies and risks.**
- Regimes fitted to noise replay their own run, as pieces do. Watch the fresh-run gap: the fresh run
  shares the schedule, so recurrence and sharing are the guard, not the fresh grade.
- Pieces compete with regimes, so detect on rows with coarse pieces.
- Combine with periodic-inflows: the phase can label day/night regimes.

**Cost.** Medium-large.

### 3. periodic-inflows: outside inflows as a repeating profile

**Hypothesis.** Every schedule repeats with a fixed period, yet the main line pays one free value per
piece over the whole run (print-shop long 1362 pieces). A profile shared across periods has a fixed,
small parameter count. It cannot follow non-periodic internal dynamics (playbook convergence 6), and it
forecasts held-out blocks, removing the reason the held-out judge failed.

**Change.**
- Strategy `periodic_inflows`, module `discovery/periodic.py`.
- Steps:
  1. Detect a period per row and pooled across rows (periodogram or autocorrelation, 2 to T/3).
  2. Fit the profile by PELT on the phase-folded residual, plus a slow component at a high price.
  3. Fit profile segments as columns jointly with the levels.
  4. Accept the profile by BIC against pieces, counting values and cut positions.
  5. Write the result as ordinary `inflow` segments.

**Mechanism test.**
- Model: chain a -> b -> c, with a's intake on a 24-step day profile (4 / 12 / 9) varying ±20% from
  day to day; 2000 steps.
- Baseline: a gets more than 100 pieces, and b gets chance pieces.
- Strategy: period 24, a's drain within 0.02, no inflow into b or c, skill@20 at least the baseline's.
- Control: random-time intake changes give no period and the matrix result.

**Target examples.** ev-fleet, emergency, hospital, moderation, clinic-doses, kanban, restaurant,
print-shop, support-tiers, services.

**Expected effect.** Inflow load falls sharply and drains get better: +3 to +8 points of mean skill.
It also enables an inflow-conditioned held-out judge that can actually forecast.

**Dependencies and risks.**
- Profiles that vary between periods (ev-fleet morning peaks of 181 vs 223) need the slow component or
  a per-period scale.
- Long periods give little sharing on default runs (every 720 on a 1440-step run).
- The generator must include aperiodic inputs, so that this is shown to be a prior, not a benchmark
  artefact.

**Cost.** Medium.

### 4. row-crossover: the model assembled row by row

**Hypothesis.** The 16 candidates make global choices, but stocks need different ones:
- bakery default: the constant-inflows candidate grades 26.6%, the chosen one -1170%;
- clinic-doses long: changing-inflow candidates grade -77% to -109%, the chosen one -347%;
- pipeline default: the receiver's row holds the right move.

A greedy per-stock swap among existing rows reaches better combinations at the cost of a few dozen
judge calls ("choose the inflow form per stock by behaviour", change-price open ideas).

**Change.**
- Strategy `row_crossover`.
- Steps:
  1. Keep every variant's rows.
  2. Assemble mixtures, re-running `conserve` and `read_flows` on each.
  3. Start from the judge's pick and visit stocks in order of their partial-model error.
  4. For each stock, try every other variant's row, keeping a swap if the judge improves by 2%
     relative. Two sweeps.

**Mechanism test.**
- Model: two independent subsystems, one needing changing inflows (intake changing every 30 steps)
  and one needing a constant inflow (slow drain absorbed by pieces).
- Baseline: the best whole candidate is right on one subsystem only.
- Strategy: skill@20 above either candidate's.
- Control: when one candidate is right everywhere, no swap.

**Target examples.** bakery default, clinic-doses long, pipeline default, emergency default,
learning-curve default.

**Expected effect.** +3 to +6 points of mean skill, concentrated in a few large swings. It also gives
a cheap measure of how much per-stock choice is worth (the coverage view of I1).

**Dependencies and risks.** More choices give flexible rows more chances to fool the in-data judge, so
run it with the piece-proof judge. Mixed rows need conservation re-applied. Overlaps the running
structure search's GA only in spirit: no new generator is needed.

**Cost.** Small.

### 5. impulse-inputs: pulses as their own input kind

**Hypothesis.** 1-step deliveries and 3-6-step bursts cannot be pieces: the minimum piece is 5 steps.
They are absorbed by drains (clinic-doses default: doses drain 0.41 and an "expired -> doses" link of
2.26; truth: expire 0.02; skill@20 -602%, long -347%). Detecting outliers jointly with re-estimation
classifies pulse vs burst vs level shift.

**Change.**
- Strategy `impulses`, with a joint detector beside `changes.pelt`.
- Steps:
  1. Estimate a robust scale (MAD of successive differences).
  2. Iterate: take the largest standardised candidate, classify it (1-step, 2-6-step, level shift),
     add it as an indicator column, and refit the row.
  3. Stop at about sqrt(2 log T) robust SDs, then run PELT on what the pulses leave.
- Pool pulses at the same phase of a period, and cap the count by the budget.

**Mechanism test.**
- Model: doses receive 450 every 7th step, expire at 0.02, and are used at 0.2 x waiting.
- Baseline: drain above 0.2 and skill@20 below 0.
- Strategy: pulse recall at least 95%, at most 2 false pulses, drain within 0.005, skill@20 above 0.9.
- Controls: counting noise around a constant intake gives no pulses in 2000 steps; a level shift
  becomes a piece.

**Target examples.** clinic-doses, kanban, support-tiers default, university, moderation.

**Expected effect.** clinic-doses from deeply negative to positive; kanban and support-tiers better.
+3 to +6 points of mean skill.

**Dependencies and risks.** Pulses into stocks the truth does not feed still replay their own run.
The grader replaces fed inflows, so the gain is in the drains. Heavy-tailed counting noise from large
flows needs a robust threshold.

**Cost.** Small-medium.

### 6. mass-balance-hidden: hidden stocks reconstructed from the unit's balance

**Hypothesis.** 20 of 31 truths have a hidden stock, mostly a same-unit delay. The main line finds it
as an outflow to outside from A plus pieces into B (cloud-credits default: running -> outside 0.44,
truth 0.25 into postproc; results has 36 pieces). The cumulative difference between the two is the
hidden level (by conservation). Its drain follows from Little's law, and a false pairing reveals itself
by drifting, which is a check in-sample fit cannot game.

**Change.**
- Strategy `mass_balance`, module `discovery/balance.py`.
- Steps:
  1. List candidate pairs (A's outside outflow, B's pieces, same unit).
  2. Form H = cumsum(alpha x k_A x A - u_B), with alpha fitted so that H does not drift.
  3. Reject H if it is not stationary or goes below 0 by more than noise.
  4. Add H as a column of B and as a stock with its own row.
  5. Accept by the judge with B's pieces held at their means, behind the behaviour gate.
  6. Output an unmeasured stock with inferred levels (grader extension from `exp/hidden-delays`).

**Mechanism test.**
- Model: a -> h -> b (h unmeasured, 0.2 and 0.1), with a's inflow changing 3 times; also an Erlang-2
  variant.
- Expect: corr(H, true h) above 0.95, rates within 0.02, skill@20 above 0.9 (matrix: -25%).
- Controls: a true outflow plus an unrelated true inflow gives a drifting H that is rejected; a
  population-like model gets no hidden stock.

**Target examples.** cloud-credits, sawmill, learning-curve, webshop, restaurant @100, fishery, kanban,
ev-fleet, housing, support-tiers, ci, recycling, saas.

**Expected effect.** Parts +1 per hidden stock found, and skill where the receiver's pieces were
absorbing the delay. +3 to +6 points of mean skill.

**Dependencies and risks.**
- Needs the hidden-stock grader extension.
- Needs pieces in B: if constant-inflow candidates win, there is nothing to pair (run it on every
  candidate).
- Parallel hidden paths are not separable.

**Cost.** Medium.

### 7. paced-moves: moves paced by a third stock

**Hypothesis.** Reading each negative cross term as an outflow to outside, and each positive one as a
link, misrepresents moves whose rate reads another stock (9 truths) and gaps on another stock. Pairing
matched entries of one unit into a single move with a linear rate in any stocks (stoichiometry x rate
law), and refitting the pair with one shared coefficient, gives the true form. That form conserves
material and behaves correctly when the source empties or a floor binds.

**Change.**
- Strategy `paced_moves`, module `discovery/stoich.py`.
- Steps:
  1. Match entries per driver column, for the same unit, within 2 SE.
  2. Form linear-rate moves, constants included (goal gaps on the destination).
  3. Read negative cross terms plus a positive constant as one linear inflow.
  4. Refit jointly with an equality constraint.
  5. Put both readings before the judge.

**Mechanism test.**
- Model: tier2 (inflow 10) -> resolved at 0.5 x agents, with agents varying 10-30 and tier2 emptying
  at times.
- Baseline: outflow plus link.
- Strategy: one move, k within 0.03, parts +1, and skill@20 at least baseline + 0.1 on runs where
  tier2 empties.
- Gap variant: on_order inflow max(0, 110 - 0.2 x shelf), with shelf above 550 a third of the time.
- Control: a real paced outflow plus an unrelated link with a different coefficient is not merged.

**Target examples.** support-tiers, moderation, fishery, ev-fleet, housing, restaurant, supply,
university, webshop, manufacturing.

**Expected effect.** Parts +1 to +4 per example; skill where sources empty or floors bind. Modest in
mean skill (+1 to +4 points), large in structural correctness.

**Dependencies and risks.**
- A spurious match between unrelated terms of similar size. Mitigations: SE test, shared-noise
  covariance check, and the judge.
- Collinear drivers (see conserved-totals).

**Cost.** Small-medium.

### 8. recession-drains: drains read off quiet stretches

**Hypothesis.** The drain and the outside inflow are confounded, and pieces bias the drain (pipeline
default: inbox 0.11 vs 0.3; skill@100 -178%). Where the inflow is off, the level's free decay
identifies the drain with no inflow model. Fixing the drain and then inverting for the inflow avoids
the bias (Kirchner 2009).

**Change.**
- Strategy `recession`.
- Steps:
  1. Mark quiet steps per row: lowest piece values indistinguishable from 0, or runs of falls.
  2. Fit the level coefficients on quiet steps if there are at least 5 per coefficient and the result
     differs from the full fit by more than 2 SE.
  3. Estimate the pieces on all steps with those coefficients fixed; never refit the levels on the
     pieces.
  4. Enter the result as a candidate.

**Mechanism test.**
- Model: an on/off intake (9 per step for 20 steps, then 0 for 20, varied), inbox -> working 0.3,
  working drain 0.2; 600 steps.
- Baseline: inbox drain off by more than 0.05.
- Strategy: within 0.02, skill@100 at least 0.9.
- Control: an intake that never stops gives the matrix result.

**Target examples.** pipeline default, restaurant @100, farm-soil @100, clinic-doses, kanban, fishery,
emergency.

**Expected effect.** +1 to +4 points of mean skill, mainly at @100.

**Dependencies and risks.** Quiet detection is circular with pieces. "Quiet" may be low but nonzero,
which biases the drain down. Rows without quiet steps are unchanged.

**Cost.** Small.

### 9. llm-critic: an LLM proposes structural edits, the judge verifies them

**Hypothesis.** The worst structural errors are legible to anyone who reads the found model with its
stocks' names and units ("customers drains faster when new_tickets is high", "done drains faster when
toner is high"). A model shown the flows, names, units, groups, per-row residual statistics and
per-stock judge errors can propose typed edits that our fitter refits and our judge accepts or rejects.
Discovery may see names; it never sees the truth. Generate broadly, verify strictly (FunSearch, LLM-SR).

**Change.**
- Strategy `llm_critic`. `discovery/critic.py` builds a JSON prompt and calls a Claude model at
  temperature 0, with responses cached by prompt hash so runs repeat exactly.
- Edits in a fixed schema: redirect, merge into a paced move, add a hidden stock, add `uses`, add an
  effect, change an inflow form.
- `discovery/edits.py` applies an edit and refits the numbers with the columns fixed. At most 3 rounds.
- The bench reports the critic with names and with names scrambled.

**Mechanism test.** Offline, with a recorded response: on the paced-move synthetic model the merge
edit is proposed and gives the move. Control: on a correct model every edit is rejected by the judge.
Plus unit tests of the edit applier.

**Target examples.** print-shop, support-tiers, moderation, fishery, housing long, ev-fleet.

**Expected effect.** Uncertain. A probe on 6 runs first decides whether it is worth a full bench.

**Dependencies and risks.**
- API cost per bench run, and reproducibility (cache).
- Names carry semantics: report the scrambled-names gap.
- The judge can still be fooled by edits (piece-proof judge).
- Edits never bypass the fitter or the judge.

**Cost.** Medium.

### 10. judge-ties: tied candidates told apart by simplicity

**Hypothesis.** The judge's differences between candidates are often within its sampling noise while
their grades differ widely:
- emergency default: 0.396 vs 0.401, grading 5% vs 73-75%;
- clinic-doses long: 0.526 vs 0.536, grading -347% vs -77%.

A one-standard-error rule over a block bootstrap of the judge's starts picks the simplest tied
candidate.

**Change.**
- Strategy `judge_ties`; `behaviour_error` also returns each start's error.
- Use a moving-block bootstrap (blocks of 5 starts). The tie set is everything within 1 SE of the
  best; pick fewest pieces, then fewest flows, then fewest era columns.
- Variant: re-judge the tie set with 160 starts. Gate the pick with the behaviour gate.

**Mechanism test.** On the held-out-judge trap, the trap leads by less than 1 SE, and the strategy
picks the true candidate. Control: when the true candidate leads by more than 3 SE, nothing changes.

**Target examples.** emergency default, clinic-doses long, kanban default, webshop-stock.

**Expected effect.** +1 to +3 points of mean skill; fewer coin-flip picks.

**Dependencies and risks.** Simplicity favours constant-inflow candidates, which can run away, hence
the gate.

**Cost.** Small.

### 11. conserved-totals: closed subsystems

**Hypothesis.** Exact invariants (fishery: in_port + at_sea = 40) make the levels collinear with the
constant. The stepwise search then picks equivalent columns arbitrarily, and the reading invents
cancelling outside flows (fishery default: "None -> in_port 3.873" and "at_sea -> None 3.873"; "None ->
adults, link from in_port 3.346"; "landed drains faster when in_port is high 2.79"). Detecting
invariants gives free structure and a declared representation.

**Change.**
- Strategy `invariants`.
- Steps:
  1. Find exact invariants per unit (SVD of the step changes); near-invariants with a hidden member
     from cointegration.
  2. For closed groups: no outside flows, and one redundant column removed.
  3. Rewrite terms into the preferred form (the source's level first).

**Mechanism test.**
- Model: in_port <-> at_sea (launch 0.3 x in_port, return 0.25 x at_sea), with adults -> landed at
  4 x at_sea.
- Strategy: no cancelling flows, catch read on at_sea, parts +2.
- Control: a group with an outside inflow gets no invariant.

**Target examples.** fishery, ev-fleet; closed loops in generated models.

**Expected effect.** Parts on two examples; a small skill gain. Mostly protects against a whole class
of generated models.

**Dependencies and risks.** Near-invariants with hidden members may be only approximate.

**Cost.** Small.

### 12. persistence-fallback: do no harm where the model is known bad

**Hypothesis.** When every candidate predicts the data worse than persistence (moderation 3.2 and 6.6,
fishery default 1.4), the chosen model is known bad before grading. Silencing or shrinking its failing
rows (per-stock partial-model test) bounds the damage near 0 on those stocks. This is shrinkage towards
the null forecast, as in forecast combination.

**Change.**
- Strategy `fallback`. After the judge, run the partial-model test on stocks whose error is above 1.
- For each failing stock, either remove its non-conserving terms or scale its rates by lambda (a grid,
  chosen by the judge), and keep the change if the judge improves.
- Report the silenced stocks.

**Mechanism test.** A model with a day/night switching link that the matrix cannot represent. Baseline:
judge above 1. Strategy: judge at most 1, and that stock's skill at least 0. Control: a correct model
is unchanged.

**Target examples.** moderation, fishery default, restaurant @100.

**Expected effect.** +1 to +3 points of mean skill (tail only); no new runs meeting the goal. A
stopgap that also makes failures visible.

**Dependencies and risks.** Hides failures unless reported; overlaps the behaviour gate in purpose,
not in mechanism.

**Cost.** Small.

### 13. ar-rows: rows fitted with their noise model

**Hypothesis.** Unmodelled hidden stocks leave AR residuals, which bias drains in closed loops. Direct
prediction-error methods are consistent only with the right noise model (Forssell and Ljung 1999).
Cochrane-Orcutt per row removes that bias, and the AR coefficient flags hidden stocks.

**Change.**
- An option `ar_rows`. After each pass, fit AR(p) (p by BIC, at most 3) to the residual within
  pieces, filter y, X and the piece indicators, and refit. Iterate twice.
- Report the AR coefficients.

**Mechanism test.** a -> h -> b with h hidden. Baseline: b's drain biased. Strategy: within 0.02.
Control: no hidden stock gives AR near 0 and no change.

**Target examples.** Receiver rows in cloud-credits, sawmill, kanban, learning-curve; services.

**Expected effect.** +0 to +2 points of mean skill; a diagnostic for ideas 6 and 2.

**Dependencies and risks.** Filtering with pieces is fiddly, and the bias may move into the pieces.

**Cost.** Small.

### 14. era-instruments: announced eras as instruments

**Hypothesis.** Drain bias comes from pieces competing with the drain (playbook C3). Announced switches
upstream move a downstream stock's level independently of its own unannounced inflow, so they are
strong instruments where eras exist. The earlier IV failed on weak instruments (second differences;
pipeline inbox 29.0).

**Change.**
- Strategy `era_iv`: 2SLS with instruments [era indicators x upstream levels; levels at t-2 to t-5],
  used only if the first-stage F is above 10.
- If the IV drain differs from the fitted one by more than 2 SE, re-measure the pieces with the drain
  fixed, and enter the result as a candidate.

**Mechanism test.** a -> b; an announced era switches a's drain (0.2 -> 0.4); b has an unannounced
changing inflow and a drain of 0.25. Baseline: biased by more than 0.04. IV: within 0.02. Control: no
eras, no change.

**Target examples.** restaurant, clinic-doses, ci, support-tiers, sawmill, learning-curve, eras long,
university, housing.

**Expected effect.** Small and uncertain (+0 to +2 points of mean skill).

**Dependencies and risks.** Eras that change the row's own coefficient are regressors, not
instruments. Weak instruments on short runs.

**Cost.** Small-medium.

### 15. evolve-discovery: LLM-guided evolution of discovery modules

**Hypothesis.** Hand-run loops limit progress. Evolving one rule-heavy module at a time (`read_flows`,
`conserve`, the inflow-form decision), scored on generated models, searches alternatives faster.

**Change.**
- An offline harness `tests/evolve/`: a population of module variants, mutated by an LLM given the
  module, the scores and the failure classes.
- Evaluate on 50-200 generated development models, select on the validation pool, and score the 31
  examples once.
- Winners then go through the normal experiment process.

**Mechanism test.** A planted bug (`pelt` minimum piece 50) is fixed within N generations; held-out
generated models are reported at every generation.

**Target examples.** All.

**Expected effect.** Unknown; potentially large over many generations.

**Dependencies and risks.**
- Requires the procedural generator (running); without it this overfits the 31 by construction.
- Compute cost; code that people cannot read.

**Cost.** Large.

---

## 4. Everything brainstormed

S = selected (rank). Otherwise the reason it was not selected, and where it lives.

| # | Idea | Status here |
|---|---|---|
| 1 | Co-flows found from starvation regimes; source rows fitted on unstarved steps | S1 [starved-coflows](starved-coflows.md) |
| 2 | Flow-rate columns for cross-unit losses (a loss in C proportional to an existing flow's rate, not to a level) | folded into S1 |
| 3 | Unannounced internal regimes found and fed to the era machinery | S2 [latent-eras](latent-eras.md) |
| 4 | Time-varying-coefficient (Kalman-smoothed, S-map) regression as a universal detector of regimes, effects and caps | folded into S2 as its detection step; effects side covered by effect-columns and symbolic-regression |
| 5 | Periodic inflow profiles | S3 [periodic-inflows](periodic-inflows.md) |
| 6 | Pulses and bursts (outlier taxonomy) | S5 [impulse-inputs](impulse-inputs.md) |
| 7 | Per-stock row recombination across candidates | S4 [row-crossover](row-crossover.md) |
| 8 | Hidden stocks from cumulative mass-balance gaps | S6 [mass-balance-hidden](mass-balance-hidden.md) |
| 9 | Moves paced by a third stock; the matrix read as stoichiometry x rates; gap inflows on another stock | S7 [paced-moves](paced-moves.md) |
| 10 | Drains from recession (quiet) stretches, inflows by inversion | S8 [recession-drains](recession-drains.md) |
| 11 | LLM structural critic with typed edits, verified by the judge | S9 [llm-critic](llm-critic.md) |
| 12 | One-standard-error rule over a bootstrapped judge | S10 [judge-ties](judge-ties.md) |
| 13 | Exact invariants and closed subsystems | S11 [conserved-totals](conserved-totals.md) |
| 14 | Persistence fallback / shrinkage of failing rows | S12 [persistence-fallback](persistence-fallback.md) |
| 15 | AR noise model per row (Cochrane-Orcutt, ARMAX) | S13 [ar-rows](ar-rows.md) |
| 16 | Era switches as instruments | S14 [era-instruments](era-instruments.md) |
| 17 | LLM-guided evolution of discovery modules on generated models | S15 [evolve-discovery](evolve-discovery.md) |
| 18 | Output-only (transmissibility) judge: compare the found model's transfer function from A's level to B's with the empirical cross-spectrum ratio, which does not depend on the unknown input | not selected: [partial-model-simulation](partial-model-simulation.md) is its time-domain form, and piece-proof judging is running |
| 19 | One-step fitting through the simulator's floors, caps and sharing (Gauss-Newton at horizon 1) | covered by [gradient-descent](gradient-descent.md) and [numerical-optimisation](numerical-optimisation.md) (running) |
| 20 | Outside inflow as a random-walk latent state (unobserved-components Kalman smoother) | overlaps [inflow-innovations](inflow-innovations.md), [regime-models](regime-models.md), [state-space](state-space.md) |
| 21 | Exogeneity test on pieces (pieces must not be predictable from the system's state) | covered by inflow-innovations' pieces-track-levels guard |
| 22 | Direct multi-step regression (k-step equation error) | covered by [output-error](output-error.md) (multiple shooting) |
| 23 | Model averaging / stacking of candidates | the result must be one model; row-crossover takes the useful part |
| 24 | Degree prior (at most a few cross terms per row) | covered by [complexity-budget](complexity-budget.md) |
| 25 | Coefficient bounds (fractions leaving at most 1 per step; Metzler sign pattern) | covered by [joint-constrained-fit](joint-constrained-fit.md) and the behaviour gate |
| 26 | Graphical lasso / partial coherence to prune spurious cross terms | stepwise BIC is already conditional; low expected value |
| 27 | Era boundaries as natural experiments (step responses) | covered by [inflow-conditioned-judge](inflow-conditioned-judge.md)'s era hold-out |
| 28 | `final` stocks as flow meters (their change measures their inflows exactly) | the matrix already fits final rows; little left to gain |
| 29 | Harmonic phase maps and group delays along chains | deferred in the playbook (section 4.3); revisit after periodic-inflows |
| 30 | Hankel order counting before hidden-stock search | in [delay-deconvolution](delay-deconvolution.md) |
| 31 | Amortised / GNN proposer trained on generated models | [simulation-based-inference](simulation-based-inference.md); needs the generator |
| 32 | MCMC / reversible-jump over structures | [bayesian-structure](bayesian-structure.md) |
| 33 | Higher moments (Poisson skewness) for a move's direction | [shared-noise](shared-noise.md) open ideas |
| 34 | Split-half structural stability | [bayesian-structure](bayesian-structure.md) (stability selection) |
| 35 | Timescale separation: identify fast stocks first, slow stocks given them | speculative; no failing run points to it |
| 36 | SD time-constant priors (rules of thumb on plausible delays) | weak evidence; better as a library constraint ([process-library](process-library.md)) |
| 37 | Active perturbation of live runs to separate tied structures | [experiment-design](experiment-design.md) |
| 38 | Names and units as priors | [llm-priors](llm-priors.md) (the critic, S9, differs: it sees the fit) |

---

## 5. Notes for whoever runs these

- Everything here is a strategy beside `matrix`, with its own mechanism test and a control, measured
  with `--baseline v2.1`, and recorded in DISCOVERY-EXPERIMENTS.md and its topic document.
- The truth census and the failure analysis used `truth.model.json` only to understand failures. No
  strategy may read it, and none of the briefs needs it.
- Several ideas (1, 2, 3, 5, 6) add flexibility that an in-sample judge can be fooled by. Measure them
  with the piece-proof judge and the behaviour gate once those report, and read the fresh-run column:
  a gain that disappears on the fresh run is replay, not structure.
