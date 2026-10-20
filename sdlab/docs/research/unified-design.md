# One algorithm for every case: the unified design

Status: **design, not built.** Nothing here has a ladder result yet. The first thing to build is the
objective test (section 7). No search code is written until that test has been run and read.

## 1. The goal and what this document settles

The user's goal: one algorithm that works on every case and uses the same principles for every system.
The algorithm must not pick a specialist by input type. A "combined" strategy that chooses which
specialist's model to keep is a configuration file and does not meet the goal. Any decision to change
method has to come from the same evidence at every decision point.

The agreed plan has four parts:

1. one model class that contains every mechanism;
2. one data model, in which the character of the noise is estimated and never switched;
3. one objective that makes every local decision;
4. one search.

Before any search is written, we test the objective itself. On every set, does the TRUE model score
better than every wrong stored model? That test tells objective failures apart from search failures.

Four designs were written and three judges scored them. They were: a state-space likelihood with a
two-part price, Fisher-quantised description length, Laplace Bayesian evidence, and a prequential
forecast score. Two judges chose the state-space likelihood design as the backbone because it is the
most testable and the most feasible. The third chose description length, whose large-T limit is the
same objective. This document uses the state-space likelihood as the backbone and adds the grafts the
judges agreed on:

- From description length:
  - every report is scored as the probability of its quantisation bin;
  - the price and tie table is pre-registered and versioned;
  - a "fit failure" class.
- From Bayesian evidence:
  - exact counting codes for change points;
  - unit-equivalence checks before any number is read;
  - prior-sensitivity reporting.
- From the predictive design:
  - a latent jump state as a mechanism for unannounced change;
  - a multi-horizon arm on the runaway rows;
  - the saddlepoint small-count code;
  - the sigma-point filter as the global fallback.

All three judges rejected one idea: the **boundedness prior**, a penalty on runaway predicted behaviour.
It is a behaviour gate presented as a prior. It is not used anywhere.

Words used with one meaning throughout:

| Term | Meaning |
| --- | --- |
| cell | one (case, variant) pair. |
| report | one scalar reported value y_i of one stock at one time. N is the number of reports in a cell. |
| discovery view | exactly what `runner.discover` passes to a strategy: `page_stocks(model)`, `t`, `levels`, eras (when there is more than one), injections and inputs. Nothing else. |
| model M | a structure (stocks, flows, rate forms, schedules, observation choices) with numbered parameter slots θ. |
| noise character η | the continuous noise numbers of section 3. Every fit estimates them. They are never a structural choice. |
| J(M) | the one objective (section 4), in nats. Lower is better. |
| ε | the tie band of J, set in the code table (section 4.4). |

## 2. The model class

There is one family: a stochastic stock-and-flow graph with parameter slots. The engine's JSON schema
is extended so that every number becomes a slot. The truth (`cases.truth_model`, laid out by
`skill.truth_by_time`), every stored found model and every search candidate load through one front end
into the same representation.

### 2.1 Stocks

Each stock has these flags:

- **measured** or **hidden**;
- **signed** (no floor at 0);
- **max** or **max_net** (a ceiling).

A hidden stock's start level is a parameter. Delays, smooths, trends, transit pairs and Erlang chains
are not separate mechanisms. They are chains of hidden stocks of order n with delay d and a shared rate
n/d, exactly as `caseformat` compiles them.

A hysteresis switch is a hidden 0/1 state with two thresholds. It is in the class so that truths which
use one can be scored. The search proposes switches last.

### 2.2 Flows

Each flow f has from and to (a stock or outside), giving a stoichiometry column v_f:

- a **move** has −1 at the source and +1 at the destination;
- a **link** or **inflow** has +1 at the destination only;
- an **exit** has −1 at the source only;
- a **co-flow** (`uses`) adds −per at the used stock, and per is a number;
- **ratio** scales the destination entry.

A flow can be marked **two_way**, which makes its rate signed and unfloored.

### 2.3 Rates

```
r_f(x, u, t; θ) = s_f(t) · B_f(x, u; θ) · Π_e E_e(C_e; θ)
```

**B_f, the base.** B_f is a sparse sum of terms from one grammar. Every number in it is a slot:

- `1`
- level `x_j`
- input `u_k`
- product `x_a·x_c`
- `sqrt(x_j)`
- hinge `max(0, a·z − c)`, which covers gaps and floored goal gaps
- `MIN(branch_a, branch_b)` of two linear branches

The legacy forms are all special cases of this sum: constant, proportional, gap `c − k·x`, linear and
available.

**E_e, an effect.** E_e is a piecewise-linear tent ("hat") table with K knots on a reader C_e, which is
a level, an input or a named auxiliary. K = 2 is a linear effect. The table is linear in its knot
values, so for fixed knot positions an effect adds columns to a linear design.

**s_f(t), the schedule.** s_f(t) is piecewise constant in time. With one segment of value 1 it costs
nothing. Any coefficient can carry a schedule, not only an outside inflow. That one mechanism replaces
eras, `byTime`, inflow pieces, drifting drains and unannounced steps or pulses. Announced eras fix the
cut positions. Unannounced cut positions are part of the structure and are priced (section 4.3).

**Latent rate state (an alternative to a schedule).** A coefficient may instead be multiplied by a
hidden state s(t) that follows a local level with jumps:

```
s_t = s_{t−1} + η_t
```

Each step, η_t comes from one of two components:

- no jump, with variance σ_s²;
- a jump, with probability π and variance σ_j².

When π → 0 and σ_s → 0, the state reduces to a constant. This mechanism lets pieces and feedback
compete for the same variance (section 8, R3). The model class contains it from the start. The
objective test decides whether the search should propose it.

### 2.4 Engine semantics

These are not mechanisms the search chooses. They are the step function itself, and every candidate,
including the truth, is stepped through it in the engine's order:

```
injection → inputs → aux → switches → rates → noise → floor share → ceiling share → flow(id) → move
```

- Outflows share proportionally what the stock holds (the floor).
- Inflows share the room left below a ceiling.
- `flow(id)` is allowed one level deep, as in the engine.
- dt < 1 truths are stepped with their own sub-steps. The sub-step count n ∈ {1, 2, 4} is a model
  attribute.

### 2.5 Representation and compiler

A vectorised compiler of the restricted `sdtruth_expr` AST works over states × sigma points. It returns
the flow amounts, ∂amounts/∂x and ∂amounts/∂θ:

- analytically for the linear and tent subset;
- by finite differences elsewhere.

Linear forms keep the canonical fast path, so the `kalman_lna/kf.py` kernels apply unchanged. That path
is the transition matrix A_k = I + Σ θ v e'. The compiler and the filter are vendored into a new
strategy package, `sdlab/discovery/strategies/unified/`. Each vendored file records where it came from
and at which commit (invariant 11). Nothing outside that package is imported except the pinned shared
discovery library.

A truth or a stored model that the front end cannot translate is marked **not expressible**. That mark
is itself a test result (class C in section 7.5) and is never a silent skip.

## 3. The data model

Every set uses one generative story. There is no `is_counts` flag, no noise check, no
measurement-error gate, no zero-share rule and no R/ρ switch.

### 3.1 Process

At each step or sub-step, the amount moved by flow f is

```
a_f = cut( r_f·dt + ε_f )
```

The noise ε has this covariance:

```
Var(ε) = φ · V diag(r·dt) V'                  counting, scaled by dispersion
       − β · Σ_src (v v') / x_src             binomial/multinomial split from one source
       + diag(τ_s)                           extra per-stock shock variance
       + latent-state noise                  when a latent rate state is present
```

| Number | Meaning | Values |
| --- | --- | --- |
| φ ≥ 0 | dispersion | 1 is Poisson counting; above 1 is overdispersed; near 0 is noise-free |
| β ∈ [0, 1] | split weight from `master_eq` | 0 is Poisson; 1 is particle splitting |
| τ_s ≥ 0 | per-stock variance for unmodelled input or misfit | one per measured stock, one pooled for hidden stocks |

A two-way flow contributes its gross exchange, |r⁺| + |r⁻|, to the counting term (Skellam). Noise can
therefore identify an exchange that cancels in the mean.

φ scales the counting term but keeps its shape, V diag(r) V'. So even with φ free, the correlation
pattern still tells a move from a link plus a drain. Only the absolute size of the noise stops
identifying flow size.

### 3.2 Floors

The floor censors the amount. The predictive distribution of a stock with a binding floor keeps a
probability mass at the floor (section 4.1). The mean is the engine's shared cut amount, and the
variance is that of the cut amount, not the uncut one.

### 3.3 Observation

Each report is

```
y_i = s_r · obs(x)_i + b_r + v_i
```

`obs(x)_i` is one of:

- `x(t_i − ℓ)`;
- the mean of x over a span w ending at t_i − ℓ (an accumulator state).

The observation noise is

```
v_i ~ Student-t_ν( 0, q_r²/12 + α_r + ρ_r²·x² )
```

| Number | Meaning | Values |
| --- | --- | --- |
| q_r | the stock's quantum: 1 for integers, the rounding step otherwise | estimated from the data as `quantum()` does; fixed, not fitted |
| α_r | absolute measurement variance | ≥ 0 |
| ρ_r² | relative measurement variance | ≥ 0 |
| ν | shared tail weight | ν → ∞ is Gaussian; small ν absorbs gross errors |
| s_r | scale | 1 unless conservation pins it |
| b_r | bias | 0 unless conservation pins it |
| ℓ | lag | 0 to 8 |
| w | span | 1 or 7 |

A small ν replaces detecting and dropping gross errors. Student-t is implemented as a scale mixture,
with one weight per report inside the filter, so the filter stays Kalman-shaped.

s, b, ℓ and w are **observation choices**, priced like structure (section 4.3).

Uneven reporting times are grid steps with no update.

### 3.4 The noise character is estimated

**η = (φ, β, τ_s, α_r, ρ_r², ν)** is estimated by every fit of every candidate, from data each time. No
decision anywhere turns a component on or off. Every candidate on a cell has the same η slots, so the
price of η is the same for every candidate and cancels in every comparison.

Each fitted number has a lower bound:

- the variances (τ_s, α, ρ²) at 0;
- φ at 0;
- β inside [0, 1].

The kinds of data that the current strategies switch between are regions of η:

| Data | Region of η |
| --- | --- |
| exact counted levels | α, ρ² → 0 and φ ≈ 1. With every stock reported at every step, the filter's likelihood is `lna`'s one-step LNA. |
| noise-free engine runs | φ, τ, α → 0. Only the quantum floor q²/12 is left, and the filter becomes output error with a filtered start. |
| measurement noise (meas, twins, physics) | α and ρ² carry the noise; φ·counting is small. |
| particles | β > 0. |
| overdispersion | φ > 1. |

`odefit`'s R/ρ signature becomes a check after the fit that the estimated split is plausible. It is not
a switch.

### 3.5 Starts

- **Measured stocks** start from a diffuse prior centred on the first report. That gives the same
  constant for every model with the same measured stocks.
- **Hidden stocks** start at a priced parameter with a finite variance.
- **Accumulators and lag buffers** start at their first implied value.

### 3.6 The filter: one fixed approximation

**Default (code table v1).** The default is an iterated extended Kalman filter, linearised around a
reference path. The reference path is the RTS-smoothed mean, refreshed after each refit. This is
`kalman_lna`'s outer loop, generalised from linear A_k to the compiler's Jacobian.

**Fallback.** The fallback is a sigma-point (unscented) filter run on the vectorised engine step, so no
Jacobian has to pass through floors, MIN, hinges or tables.

**Rule.** Exactly one of the two is used for every model and every cell within a code-table version. The
objective test decides which (section 7.7). It never decides per case.

**Referee, never an objective.** A particle filter is kept only as a referee of the approximation
(section 7.5, class P).

## 4. The one objective

### 4.1 Definition

```
J(M) = min_{θ, η} [ D(y | M, θ, η) ] + P_num(M) + P_struct(M)
```

All terms are in nats.

**D, the data code.** D is the prequential (one-step-ahead) code of the reports under the filter:

```
D = − Σ_i ln P( y_i ∈ [y_i − q_r/2, y_i + q_r/2] | y_{<i}, M, θ, η )
```

Each report is scored as the probability of its **quantisation bin** under the filter's predictive
distribution, never as a density. That puts integer, rounded and continuous data on one measure. It
also makes a discrete small-count term comparable with a Gaussian one on the same series.

- The predictive is the filter's Gaussian, or a Student-t through the scale mixture, convolved with the
  observation noise.
- Where the floor can bind, the predictive includes a censoring mass, P(desired outflow ≥ level), at
  the floor.
- **Code table v1:** the Gaussian bin probability with censoring mass, for every report.
- **Arm A-sp (section 7.7):** a saddlepoint bin probability of the increment, for every report. It
  uses the Poisson cumulant generating functions of the flows that touch the stock, scaled by φ,
  censored at the floor and convolved with the observation noise. It tends to the Gaussian as counts
  grow, so it is a better approximation everywhere, not a branch. If it wins, it replaces the v1 code
  for every report in the next version.

**P_num, the price of continuous numbers.**

```
P_num = Σ_j ½ ln N_j
```

The sum runs over every structural number j: flow coefficients, knot values, schedule segment values,
latent-state numbers (π, σ_s, σ_j), hidden-stock starts, co-flow `per`, s_r and b_r when freed, and
profiled shape parameters (knot positions, d, hinge thresholds).

N_j is the number of reports of the stocks whose one-step mean depends on number j. For a flow, that is
the reports of its from, to and `uses` stocks. For an observation number, it is the reports of its own
stock. A number on one stock's row is therefore not priced by the length of the other rows.

η is priced the same way, but its price is equal for every candidate, so it never decides anything.

**P_struct, the price of discrete choices.** P_struct is a fixed prefix code over the structure
(section 4.3).

### 4.2 The fit

(θ, η) minimise D by Fisher scoring with forward-sensitivity gradients. Box constraints are handled by
log and logit transforms. Shape parameters are profiled by 1-D searches. The fit runs from warm starts
and refreshes the reference path between scoring rounds until J changes by less than 0.01 nat.

"Converged" means both of these hold:

- the gradient norm in the transformed coordinates is below 1e-4·N;
- two restarts agree to within ε.

### 4.3 Code table v1: the structure code

This table, like everything else in section 4, is committed **before** the objective test runs. Any
later change is a new version, re-run on every set. The table is never tuned to the suite.

S is the number of stocks (measured plus hidden), U the number of inputs, T the number of steps, and
γ(n) the Elias-γ length of n in nats, (2⌊log₂ n⌋ + 1)·ln 2.

| Choice | Code length (nats) |
| --- | --- |
| number of flows F | γ(F + 1) |
| each flow: endpoints | ln((S + 1)²) |
| each flow: two_way flag | ln 2 |
| each base term: kind (7 kinds in the grammar) | ln 7 |
| each base term: each reader | ln(S + U) |
| number of base terms per flow, n_b | γ(n_b) |
| each effect: reader | ln(S + U + number of auxiliaries) |
| each effect: knot count K | γ(K − 1) |
| each co-flow `uses` | ln S |
| number of hidden stocks H | γ(H + 1) |
| each hidden chain: order n | γ(n) |
| which coefficients carry a schedule | ln(number of coefficients + 1) per scheduled coefficient |
| each unannounced schedule with m cuts | γ(m + 1) + ln C(T − 1, m) |
| each announced schedule | 0 for places (they are given); its values are in P_num |
| each latent rate state | ln(number of coefficients) |
| observation choices per stock, when not the default | ln 9 (lag), ln 2 (span), ln 2 each (scale freed, bias freed) |
| sub-step count | ln 3 |

ln C(T − 1, m) is the exact counting code for where m cuts fall. Together with ½ ln N per segment value,
it is close to the evidence-backed mBIC price per cut, about 1.5 ln T.

**Arm A-pp (section 7.7)** replaces "best cuts plus counting code" with exact product-partition
marginalisation over cut positions (Fearnhead 2006) on rows that are conditionally linear-Gaussian given
the reference path.

### 4.4 Ties

Two models whose J differ by less than **ε = 0.5 nat** (code table v1) are tied by the data. A fixed
lexicographic order then decides:

1. fewer continuous numbers;
2. fewer flows that read a stock other than their source;
3. the canonical form:
   - move over link + drain;
   - gap over inflow + drain;
   - drain + table over a free own-level curve;
   - kin = kA in the transit mirror;
   - a schedule over a latent state when both fit equally.

This order is a declared prior, since equivalent forms are unidentified. Results report a tie as "tie,
convention chose", never as identification.

### 4.5 Corners the objective must reproduce

These are unit checks on the implementation (section 7.2). They are not claims to be read off results.

| Corner | Must equal |
| --- | --- |
| α = ρ² = 0, ν = ∞, every stock reported every step, linear forms | `sdlab.ladder.fisher.TruthParams.nll` for the truth, and `kalman_lna`'s `nll_grad`, up to the bin constant ln q per report |
| φ = τ = 0, diffuse start | `odefit.compare.output_error` on the same flows (as a ranking; constants differ) |
| β > 0, φ = 1 | `master_eq`'s split likelihood on its stirred-chamber cells |

### 4.6 What is not in the objective

None of these choose anything:

- a multi-step behaviour judge;
- a held-out ratio;
- a whiteness gate;
- a dispersion gate;
- margins (2 ln T, 4 ln 2T, 10 ln T);
- a boundedness prior.

Multi-step error, held-out error, innovation dispersion and Ljung-Box statistics are reported beside J
as diagnostics only.

If a diagnostic shows a systematic fault, the fix is a change to the data model or the class in a new
code-table version, applied to every cell. An example of such a fault is the truth's own innovations
failing whiteness on a set.

## 5. Local decisions

Every decision has the same form. A move M → M′ changes the model locally, and it is accepted if and
only if **J(M′) < J(M) − ε**. No family has its own margin, and adds and removals are treated alike.

A move is one of these:

- add, remove or rewrite one flow or one base term;
- add or remove an effect, or change its K or reader;
- add or remove a schedule cut on any coefficient, or a latent rate state;
- insert or remove a hidden stock or chain (n, d profiled);
- add a co-flow;
- toggle two_way;
- change an observation choice (lag, span, scale, bias);
- swap an alias pair.

The alias pairs are:

- link + drain ↔ move;
- outflow ↔ gap;
- own-level curve ↔ drain + table;
- the transit mirror;
- affine move ↔ inflow + drain;
- plain ↔ bilinear;
- pieces ↔ latent state ↔ effect.

Questions that are separate rules today become ordinary moves or plain estimates:

- **Is this stock counted or measured?** Not a move. η is re-estimated in every fit.
- **Pieces or dynamics?** Schedule and flow moves on the same J.
- **Move, link or exit?** The stoichiometry column changes the covariance, so the data code sees it.

"Local" describes the proposal, not the evaluation. M′ is always refitted jointly, starting from M's θ
and running a few Fisher-scoring steps with one refresh of the reference path. No base model is ever
frozen.

## 6. The search (outline; built only after section 7 passes)

0. **Read the discovery view.** Estimate the quanta q_r, the report grid, and candidate lags and spans.
1. **Starts** (a beam of 2 to 4).
   - (a) A lean model: each measured stock has a constant inflow and an own drain, with η free.
   - (b) A sparse linear superset over measured pairs, screened with Gram statistics and pruned by
     Wald.
   - (c) The conservation-tied form of (b): moves for matched loss and gain pairs.
2. **Main loop.**
   - Build one ranked list of every candidate move from every family. There is no per-family pass.
   - Rank adds by the score (Lagrange multiplier) estimate of the gain, ½ g′F⁻¹g, minus the price of
     the move. Rank removals by Wald, ½ θ²/var, minus the price saved. Both come from the current
     fit's forward sensitivities.
   - Refit the top k exactly, and accept the best move that lowers J by more than ε.
   - After each accepted move:
     - re-test every flow for removal and rewrite;
     - refit everything jointly;
     - refresh the reference path.
   - A tabu list of recently reversed moves prevents ping-pong.
3. **Composite moves.** A move can be an addition paired with the removals it makes redundant. The
   removals are the terms whose Wald statistic collapses once the addition is in, for example inserting
   a hidden stage and dropping the receiver's constant.
4. **Stop and write out.** Stop when no move lowers J. Apply the tie order and write found-model JSON.
5. **Scale.**
   - Up to about 15 to 20 states: a dense filter.
   - Larger graphs: screen moves with a localised filter (stocks within graph distance 2 of the move,
     with the others' smoothed paths as inputs). Decompose into connected or weakly coupled blocks,
     and compute J per block and sum it. Verify the full J on accepted moves.
   - These are approximations of the same J, and are reported as such.
   - The budget is anytime: the result is the best J so far.

## 7. The objective test (to build now)

### 7.1 Question and output

**The question.** On each set: when the truth and every stored wrong model are fitted by the same J
from the discovery view, does the truth have the lowest J? Where it does not, is that the objective's
fault, or the approximation's, the class's, the fit's or the data's?

**The output.** The test produces:

- a table per set;
- a list of every objective failure with its case, ΔJ and the mechanism of the winner;
- a cache, so that every number can be rerun (invariant 8).

**What gets built:**

- the evaluator package, `sdlab/discovery/strategies/unified/`, containing the front end, compiler,
  filter, fit and J, but no `identify` search yet;
- a study script, `tests/study_unified_objective.py`, modelled on `tests/study_rescore.py` and the
  `sanity()` in `tests/test_ladder_combined.py`.

Only the study script reads truths. The evaluator never imports `sdlab/ladder`.

Results go to a study cache keyed by (case, variant, candidate hash, code-table version), never to the
ladder store. The script runs single-threaded per process, in a pool of at most 4 workers, with a time
cap per cell. Timeouts are reported as **not run**. The script stops its pool before it exits.

### 7.2 Unit-equivalence checks (before any result is read)

All of these must pass on the cells they apply to:

1. **Engine replica.** Compiled noise-free runs of every truth reproduce `Truth.run` to within
   rounding. This includes dt < 1 (cases 113 and 114), switches (case 225) and `flow(id)`.
2. **α = 0 corner.** On all-measured linear truths at α = 0, D minus the bin constant equals
   `TruthParams.nll` and `kf.nll_grad` at the same θ.
3. **Q = 0 corner.** It ranks candidates as `odefit.compare.output_error` does.
4. **Leakage guard.** An assertion in the loader checks that the evaluator receives only the discovery
   view. It never sees `all_levels`, counters, clean levels or the observation record.

### 7.3 Inputs per cell

For each cell (cid, v):

1. `c = cases.load(cid)` and `tm = cases.truth_model(c, v)`.
2. `d = data.load(c, v)`, or the real-data loader for `real` cases. The discovery view is built exactly
   as `runner.discover` builds it.
3. **The truth T.** T is `skill.truth_by_time(tm, d["t"])` in found layout, with its byTime segments as
   announced or unannounced schedules as the case states. It uses `sim.mark` for 2d features and is
   stepped at its own dt (and also through `substep.per_step`; both are recorded). Where the cell has
   no exact truth, a proxy is used:
   - physics: the fitted SD reference model;
   - particles: the mean-field model on exact tiers;
   - real twins: the published model.
4. **Stored candidates.** These are the rows of `store.latest(case=cid, variant=v, found=True)` that
   have flows.
   - Drop error and timeout rows.
   - Deduplicate by the canonical JSON of the flow list. The strategy names are kept as labels only.
   - Re-score any row whose `score_hash` is stale with `score.equations`, so its label is current.
   - Status `fail` is **wrong**. `pass` and `equivalent` are **right**.
5. **Hard negatives.** These are `analysis.alternatives(tm, measured)`: structures with no more numbers
   than the truth that make the same mean change. Each is labelled right or wrong by `score.equations`.
   They test whether the noise identifies what the mean cannot.
6. **Cell label.** The cell's identifiability label comes from `analysis.analyse(cid, v)`: achievable,
   data-limited, unidentifiable or not analysed.

### 7.4 Fitting on equal terms

Every candidate's structure is held fixed, and (θ, η) is refitted under J.

| Fit | Starts |
| --- | --- |
| **T₀** | the truth at its written θ0 with only η fitted |
| **T\*** | the truth refitted from θ0 and from 4 starts perturbed by ±30%; keep the lowest J |
| **W\*** | each candidate refitted from its stored numbers and from the lean start (section 6, step 1a); keep the lower J |

- Stored pieces keep their cut positions as structure. Their values are refitted, and both their values
  and their places are priced as in section 4.3.
- Hidden stocks of found models get fitted starts. The filter replaces `inferred_levels`, which is not
  stored.

For every fit, record:

- J, D, P_num and P_struct;
- η̂;
- the convergence flag;
- the diagnostics of section 4.6.

### 7.5 What "truth scores best" means, and the labels

For each candidate W, let Δ_W = J(W\*) − J(T\*). A positive Δ_W means the truth is better.

**Sanity block.** This is run first on T. If it fails, the cell is labelled **S (data-model failure)**.
Its other labels are still computed, but they are flagged and are not read as objective results. The
checks are:

- J(T\*) ≤ J(T₀);
- T\* beats the truth with every number scaled by ±10% and by ±30% (each refitted in η only);
- η̂ on T is plausible for the variant:
  - counts: φ ∈ [0.7, 1.4], α and τ near 0;
  - meas and twins: α and ρ² within a factor of 2 of the generator's values, and φ·counting small;
  - none: every variance at its floor;
  - particles: β > 0 where splitting is real;
- T's standardised innovations have dispersion z ≤ 3 and Ljung-Box z ≤ 3.

**Per wrong candidate W.** The first label that applies is used:

| Label | Condition |
| --- | --- |
| **OK** | Δ_W > ε |
| **X (now right)** | after re-scoring, W is pass or equivalent. Its \|Δ\| is reported in the right group. |
| **TIE** | \|Δ_W\| ≤ ε. Subtype "known" if W is one of `alternatives` or the cell is unidentifiable, else "unexplained". |
| **F (fit failure)** | Δ_W < −ε, and T\* failed to converge or its restarts disagree by more than ε. Also when Δ_W < −ε and J(W\*) refitted from T's numbers shows that the optimiser, not the objective, decided. |
| **L (data-limited)** | Δ_W < −ε and the cell is data-limited or unidentifiable by `analysis.analyse` |
| **C (class-coverage gap)** | T is not expressible in the front end, for example switches or deep `flow(id)`. These cells are counted apart and are not objective results. |
| **P (approximation failure)** | Δ_W < −ε on a cell with at most 4 states, and a particle filter reverses the order. The particle filter is bootstrap or auxiliary, with 10⁴ particles and 3 seeds, at the filter-fitted (θ, η) plus a short particle-filter polish of θ. The fault is then the filter, not the definition of J. |
| **E (objective failure)** | everything else |

Every E records:

- ΔJ split into its D, P_num and P_struct parts. A loss decided by price alone (D favours T) is
  subtype **E-price**.
- What W has that T lacks:
  - extra pieces;
  - a self-reinforcing reading;
  - shrunk rates;
  - a spurious link;
  - a noise component absorbing structure (τ_s or φ).

**Per cell.** The cell takes the worst label of its wrong candidates, in the order
E > P > F > S > L > TIE > OK. C cells are reported alone.

**Per set.** Report:

- the share of achievable, non-C cells labelled OK or TIE-known;
- counts per label;
- the distribution of min_W Δ_W;
- the rank of the truth;
- for right candidates, the distribution of |J(R) − J(T)|.

For comparison only, the same table is computed with today's one-step BIC (`combined`'s judge and
`kalman_lna`'s criterion).

**Real series** (tag `real`, the variant that is not a twin) have no truth. Report the rank correlation
between J and each stored model's held-out prequential score on the held-out suffix.

### 7.6 Order of work

| Phase | Cells | Why |
| --- | --- | --- |
| **P0, pilot on named rows** | 056 counts; sd-eras counts-long; 080 bias-short; sd-population, sd-webshop-stock, sd-hidden-chain; 009, 045, 046 (expected ties); 010 and 016 counts-short (expected data-limited); 033, the `master_eq` stirred chambers, 085 (expected OK: these were search failures); 088#2; the `odefit` spring meas-short | each row has a documented expectation |
| **P1** | all-measured linear truths, counts and none variants | the α = 0 corner, on today's kernels |
| **P2** | `tag:noisy` and the `noise.py` variants (meas, gaps, weekly, lag, outliers, bias) | |
| **P3** | truths with hidden stocks | |
| **P4** | effects, co-flows, products, 2d | |
| **P5** | realistic (sd-k8s-small; sd-k8s-platform last), physics, particles, real twins, real | |

What the named rows expect:

- **sd-eras counts-long.** Under one-step BIC the true model scored 185,233 against a spurious loop's
  184,697.
- **sd-population, sd-webshop-stock and sd-hidden-chain.** These show the runaway self-reinforcing
  inflow reading.

`tag:canonical`, `tag:distilled` and `tag:control` are reported as separate sets in every phase that
covers them. Each phase is committed with its numbers and is rerunnable.

### 7.7 Arms and ablations (each decided once, globally)

Each arm reruns the same cells with one change. An arm becomes the default in the next code-table
version only if it reduces the E and P counts without adding new ones on any set.

| Arm | Change |
| --- | --- |
| A-φ | φ fixed at 1 vs free |
| A-β | β fixed at 0 vs free |
| A-t | Gaussian vs Student-t observation |
| A-cens | censoring mass at floors vs uncut predictive |
| A-sp | saddlepoint bin probability vs Gaussian bin probability |
| A-ukf | sigma-point vs iterated EKF (run if class P is not rare) |
| A-fisher | price each number by the observed Fisher information (½ ln(1 + λ_m r_m²/12) in the eigenbasis) vs ½ ln N_j, for short series and unidentified directions |
| A-pp | product-partition marginalisation of cut positions vs the counting code |
| A-bic | P_num = ½ ln N (all reports) and no P_struct, i.e. plain BIC |
| A-sens | every P_struct entry ×2 and ×½, and ε ×2 and ×½; list the decisions that flip |
| A-local | localised vs full filter on cases with 10 to 20 stocks (measures the screening approximation) |
| A-h (runaway rows only) | the one-step code vs a multi-horizon code (h = 1, 2, 4, 8, each a proper log score) |
| A-jump (runaway and pieces rows) | outside inflows as latent jump states instead of schedules |

### 7.8 Go/no-go for the search

Search work starts when both of these hold:

- P0 to P2 have no E and no F on achievable cells, or only a short list in which each item has a written
  cause;
- the sanity block passes on P1.

On P3 to P5, each remaining E names the missing data-model or class mechanism. That mechanism is added
in a new code-table version and every set is re-tested. A behaviour gate is never added.

## 8. Risks, stated now

**R1. Identifiability.**

- Noise-free, a link and a move tie, and so do births and deaths, the gap and inflow + drain, and the
  transit mirror. Only the tie order decides them, and the results say so.
- Freeing φ weakens how noise size identifies gross flows (A-φ measures this).

**R2. Noise absorbs structure.** τ_s, or φ > 1, can soak up a missing flow at no relative price, since
every candidate has them. The E subtype "noise component absorbing structure" tracks this. If it is
common, τ_s has to become a priced structural number in a new version.

**R3. The one-step weakness.** With exact levels the filter is the one-step LNA, which accepts
self-reinforcing inflow readings that run away. The state-space form does not fix this by itself.

If the test confirms it, there are two candidate fixes, decided globally:

- **A-jump.** Outside inflows become latent states, so pieces and feedback compete for the same
  variance.
- **A-h.** Multi-horizon terms enter the one likelihood for every case.

A behaviour gate or a boundedness prior is not a fix.

**R4. Nonlinear filtering.** The EKF is biased at floors that bind, at products and MIN, and at near-zero
counts. The censored and saddlepoint codes are approximations. The particle-filter referee only covers
cells with at most 4 states. If the referee often disagrees, the approximation is replaced everywhere
(A-ukf), never per case.

**R5. Pricing.** ½ ln N is asymptotic and weak below about 50 reports. N_j is a declared choice. ε is
declared. A-fisher and A-sens report how much these matter.

**R6. Front-end fidelity.** If the replica does not match the engine, the truth loses for implementation
reasons. Section 7.2 must pass first. An untranslatable truth is labelled C, never skipped.

**R7. Stored negatives.** Stored negatives come from mixed strategy versions, with stale hashes and
pieces at fixed places. The truth beating them is necessary but not sufficient, because a search may
still find a shorter wrong model. Later, every bench run will record J(truth) on the scorer side next to
J(found), so search failures and objective failures stay apart.

**R8. Cost.** The test covers about 1,400 cells × deduplicated candidates × 5 to 6 refits each, on a
shared machine. Mitigations:

- the pilot comes first;
- the phases are ordered by cost;
- results are cached;
- the pool is small;
- time caps apply;
- every run is stopped before an agent finishes.

**R9. Pre-registration discipline.** Changing the code table after seeing failures is exactly the suite
gaming the user rejects. Every change is a new version, re-run on every set, and the commit message
states what changed and why.
