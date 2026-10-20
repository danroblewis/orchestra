# The unified objective test: does the true model score best?

**Question.** Before building any search for the unified design ([unified-design.md](unified-design.md),
built so far as [unified.md](unified.md)), does the objective J = D + P_num + P_struct (code table v1)
score the **true** model better than every wrong model already stored for the same data? If it does
not, no search can find the truth, and the failure is the objective's, not the search's.

**Code and commands.** Evaluator and harness at `d59a98a` (the objective modules `frontend`, `engine`,
`kalman`, `price` and `objective` are unchanged since then; `1724664` narrowed the evaluator hash to
those modules). Every number comes from

```sh
uv run sdlab-ladder objective-test --cases <list> --variants <list> --jobs 3 --timeout 900 [--max-groups N]
```

with timed-out cells resumed at 2400-9000 s. Cells are cached under
`~/.cache/sdlab/ladder/objective_test/v1-*` (folders `v1-f6443f802e`, `v1-8d4dffc289`, `v1-e02ff355d9`:
the hash moved twice during the runs with no change to the objective). Nothing went to the ladder store.
The machine ran at load 190-350 throughout, so every set was a deterministic sample, stated below.

The one exception is physics and particles: the committed harness labels all of them C ("no proxy
truth yet"). Their numbers come from an **exploratory, uncommitted** driver with that gate removed and
are not ladder-grade (invariant 8). They are reported because they show a mechanism the other sets do
not.

"Truth best" means no refitted wrong group beats the refitted truth T\* by more than eps = 0.5 nat.
"Equivalent winner" means the J-best is a right model or one the scorer accepts as equivalent (X).

## 1. Per set

| set | sample | judged | truth best | equivalent winner | wrong winner | data-limited / unidentifiable | E under plain BIC |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard + distilled | first draw of each family + every fixed case, counts-short (126 cells) | 102 | **81** | 9 | 12 | 4 | 28 |
| noisy (p2) | 080-087 x {counts, meas, gaps, outliers}-short, 088#1-7 meas, 139 meas, 141-143 {none, meas} (46) | 46 | **28** | 5 | 13 | 4 | 16 |
| canonical + control | every short variant (76; 8 C) | 68 | **47** | 5 | 7 (+9 limited) | 9 | fewer E (110, 117 OK) |
| realistic | every second non-heavy case + sd-brewery, counts-short, max 8 groups (17) | 17 | **15** (2 vacuous) | 1 | 0 (1 TIE) | 1 | 14 OK, 1 TIE |
| real twins | 52 | 0 | (all C: no proxy truth) | | | | |
| physics + particles (exploratory) | all 22 short cells + long of 3 systems (44) | 26 | **13** | 2 | 11 | 0 | J better on meas |

Notes per set:

- **Standard + distilled.** Labels: OK 50, S 38, C 13, no wrong candidates 10, E-price 6, E 3, F 3,
  TIE-unexplained 2, L 1. The equivalents include X winners that are a cheaper re-expression of the
  truth (006, 154, 216, 218), which is the objective working. 048#1 and 059 are the same frozen data.
- **Noisy.** Labels: OK 13, S 20, E 9, F 5, none 2. No measurement-error cell (meas, the 088 sweep) has
  a wrong winner caused by the measurement error itself. The 5 equivalent winners all come from the
  truth's own fit not reaching its optimum (082 counts/meas/gaps, 084 meas, 141 none).
- **Canonical + control.** On none-short the truth is best everywhere except the unidentifiable 209 and
  213. All 7 price failures (105, 108, 109, 110, 115, 117, 205) are counts-short with delay/smooth chains
  or lookup tables.
- **Realistic.** No E. Smallest margins: sd-learning-curve -0.07 (TIE-known), sd-saas +9.3, sd-ci +10.7,
  sd-housing +11.5. In sd-eras the overfitted stored models have D 30 nats below the truth; the prices
  reject them. sd-services is an equivalent winner (5.2 nats) under rationing noise.
- **Physics + particles.** Measured cells are healthy (proxy or equivalent best in 6 of 7 short cells,
  failing only on the thermostat). Noise-free cells are not (proxy best in 2 of 7). Against the better
  yardstick, the J-best is the proxy or a model the physics/particle scorer passes in **22 of 26** cells;
  the only J-best failures are the 4 thermostat cells.

**Headline.** Over the four committed sets the truth scores best in 171 of 233 judged cells; another 20
go to an equivalent model. J beats plain one-step BIC clearly (28 vs 12 wrong winners on the standard
set, 16 vs 13 on noisy). The remaining wrong winners are not spread thinly: four mechanisms explain
nearly all of them.

## 2. Failure mechanisms, ranked by cells

Counts are cells where the mechanism decides the outcome; "contributes" cells are listed but not counted.

### M1. The noise character is free per candidate and absorbs mean structure - 16 cells (+7 truth-fit cells)

Standard 10 (007, 027, 048#1/059, 063, 134, 135, 153, 160, 224), noisy 6 (081 counts/gaps/meas, 086
counts/meas/gaps). Two forms:

- **tau replaces counting noise.** The per-stock shock variance tau goes to about the counting variance
  and phi to 0. The counting covariances (a move's paired loss and gain; variance tied to gross flow)
  vanish, so a move-with-constant ties a link on D and wins 2.9 nats of P_struct. 007/081 is the design's
  own probe case: with tau capped at e^-14 the truth wins by +34.6 (081) / +52 (007); with phi fixed at 1
  by +15.6 / +76. The truth's own J moves by less than 0.5 nat.
- **phi trades against gross-flow size** (risk R1). The winner doubles inflow and drain and halves phi
  (027/086: k 0.216 vs 0.1, phi 0.45), or takes phi >> 1 overdispersion (059: phi 28.8; 134: 2.4-3;
  110: 4.2). Under known counting (phi = 1, tau = 0) the truth wins in **every** listed cell (by 2.2 to 863).

**Cause.** J treats the price of eta as cancelling because every model has the same eta slots. But each
candidate chooses its own eta, so eta is a free per-model degree of freedom that a wrong mean model uses
to hide its residuals. The same freedom shows on the truth itself: 30 of 105 judged standard cells and
20 of 46 noisy cells fail eta plausibility, and the truth's own fit sometimes sticks at phi 0 with large
tau (085 meas, part-capacity-gate, 082/084/141 equivalents) because restarts 2-5 inherit the first
start's eta.

### M2. Over-pricing of the truth's structure - 10 cells

- **Untied delay/smooth chains** (5: canonical 110, 117, 205, 115, 105; also 063 and 172 partly).
  DELAY3/SMOOTH3/DELAY FIXED are written as separate hidden stages, each rate, start and flow priced on
  its own. D favours the truth by 16-73 nats but P_struct + P_num costs it 37-108. Plain BIC calls 110
  and 117 OK.
- **Effect-table knots priced over all reports** (3: canonical 108, 109; standard 131; contributes in
  160 and 224). P_num charges 1/2 ln N_j with N_j = every report where the flow acts, even for knots the
  stock never visits (108: inventory 230-717, knots at 1200 and 2000). 108 loses by 110 nats with D in
  its favour.
- **Unannounced-cut code for regular mechanisms** (2: standard 121 drifting drain, 159 periodic pulse).
  A smooth drift or a pulse train is written as many cuts, each priced ln C(T-1, m) as an independent
  change point (121: 59 nats; 159: 421). This is a class gap: the grammar has no drift or periodic term.

**Cause.** The price charges the parts the class must spell out, not the information the data carry
about them.

### M3. Gaussian observation error against outliers - 6 cells

Noisy outliers-short 081, 082, 083, 084, 085, 086. One wild report costs 15-60 nats under a Gaussian;
a one-step piece costs 5-8. The winners put pieces exactly at the outlier times (085: B 110, A 128,
B 238). The truth first inflates alpha (alpha_P 47 in 083), which taxes every report. Arm A-t
(Student-t, nu estimated) is not built.

### M4. Noise-free corner and misspecification - 10 cells, exploratory only (+1 committed)

Physics none-short/long (draining tank, coupled tanks, mass-spring, thermostat x2), the 4 thermostat
cells (switching is not expressible, so this one also hits meas), and canonical 213 none-short. With
noise at its floor, D's resolution grows without bound and a cut or number costs a few nats, so pieces
that track systematic one-step misfit win by hundreds to thousands of nats while forecasting worse at
20 steps (Spearman(-J, gap20) = -0.8 on thermostat meas-long). In 213 none-short the bin code treats
rounding as independent Gaussian noise of q^2/12, which is not a proper likelihood for a deterministic
path: a decoupled model beats the truth even at its exact numbers. Separately, several physics "wins"
are J correctly preferring a better approximation than the proxy (one-step-map couplings at dt = 1,
an effect table bending sqrt(H)); the harness then mislabels them because it re-scores physics rows
with `score.equations` against the proxy.

### M5. Cut positions selected on the same data - 4 cells (mostly contributes)

Canonical 115, 108, 205; noisy 086. Stored schedules bring cut positions tuned on this realisation; the
truth's are fixed as written. 115's 10-cut winner reaches D 46 nats below the oracle (true mean, best
variance), about equal to its cut price. 086's truth with its cuts moved to 105/208 improves by 5.9
nats. The ln C(T-1, m) price is paid once, but the selection already happened.

### M6. Smaller noise-model gaps - 2 cells (ranking), more in S

- Rationing (sd-services): the engine draws Poisson and then rations outflows; one global beta plus tau
  and an EKF across the kink inflates the truth's D. Possible bug: `kalman.py`'s split term builds 0/1
  taker rows and ignores co-flow `per` and ratio weights, which `engine.py` uses.
- Move vs link P_num tilt (sd-learning-curve, a TIE): N_j counts only stocks a number moves, not those
  it reads, so an outside-link is always 1/2 ln 2 cheaper than the equivalent move.
- S only: `exact: true` flows get counting noise in the filter (201-216: phi -> 1e-11); small-count
  discreteness (sd-moderation, sd-support-tiers); floor stocks (Bass, SEIR); sd-housing underdispersion
  unexplained.

### Not objective failures

- **Data-limited / unidentifiable** (canonical 9, standard 4, noisy 4): MDL working as intended (203 and
  209 setpoint steps after the run ends; 211 table inside its linear band; 111 dropped 0.01 entries).
  Six are labelled F only because the harness checks F before L.
- **Cheaper equivalents** (X winners): the truth as written is not the shortest code of its dynamics.
- **Scoring/grouping ties**: 123 (scale-invariant constant x effect), 156/107 (hidden stock renamed).

## 3. What the objective must change before a search is worth building

In order of cells recovered:

1. **Eta must stop being a free per-candidate degree of freedom (M1).** Either estimate eta once per data
   set and hold it for every candidate (so its price really cancels), or price what each model uses:
   tau as a priced per-stock element that is off by default, phi as one shared number tied to the
   counting signature. The diagnosis (phi = 1, tau = 0 restores the truth in every M1 cell) is not itself
   the answer, since phi is not known in general; the arms in section 4 decide between these.
2. **Student-t observation error (M3)**, nu estimated, as the design already specifies.
3. **Price information, not spelling (M2).** Hidden-chain tying (one delay time and one start for an
   order-n chain); N_j for a table knot = the reports inside its support, or the Fisher effective-dimension
   arm; drift and periodic terms in the class so regular mechanisms are not paid as free cuts.
4. **Symmetric treatment of shape parameters (M5).** Either profile cut positions for every model,
   truth included, or re-select positions inside the objective test so stored data-tuned cuts get no
   free bonus.
5. **A proper corner for deterministic data (M4).** A likelihood for rounded deterministic paths (the
   rounding is not independent across coupled stocks), plus the multi-horizon arm for misspecified,
   noise-free cases; exact flows exempt from counting noise.

Each of these is a new code-table version, re-run on every set, decided once for all cases; none is a gate.

Harness fixes needed before the next run (labels, not the objective; status after `c0b9c85` in section 5):
`frontend.write_back` writes a shared schedule slot only to the first tied segment; `g['right']` comes
from stored statuses even when the refit fails; `signature()` keys hidden stocks by name; F is checked
before L; `beats_scaled = False` should give F, not E; eta restarts inherit the first start's eta;
`_plausible` assumes counting noise for every variant but `none` (wrong for meas and physics), checks
alpha and rho^2 separately, and its tau threshold is stricter than counting variance warrants (the
user's open decision); physics/particle rows must be re-scored with their own scorer; a resumed cell
keeps a stale `timeout` flag.

## 4. Next experiments, in order

1. **Harness fixes** above (no objective change), then re-label the cached cells, so E, F, L and S mean
   what they say.
2. **Eta arms** on the 23 M1 and truth-fit cells, then the full OK set for regressions: (a) eta fitted
   once on a common reference model and held fixed; (b) tau priced and off by default; (c) one shared phi;
   (d) restarts that also restart eta. Pick one, as code table v2.
3. **Student-t arm** on the noisy outliers cells (and every OK noisy cell for regressions).
4. **Pricing v2**: chain tying, knot-support N_j vs Fisher price, on the canonical price cells, 131, 160,
   224 and 063/172.
5. **Shape profiling** (cut positions) for every model, on 115, 108, 205, 086.
6. **Iterated EKF and Fisher scoring** for the truth fits that stall (172, 085 meas, part-capacity-gate,
   115, 105).
7. Then the full P1-P3 sets on v2, then physics with proxies (rounding likelihood and multi-horizon arms,
   the thermostat as a class gap), then real twins (their truths are plain 1-4 stock models).

The go/no-go of the design stands: build the search only when no E or F remains on achievable P0-P2
cells, or each that remains has a written cause.

## 5. Labelling fixes and the re-labelled baseline (c0b9c85, 20 October 2026)

**Fixed** (`sdlab/ladder/objective_labels.py`, outside the cache key; tests in `tests/test_objective_labels.py`):

- `frontend.write_back` now writes a schedule slot to every segment that shares it. Before, only the first
  tied segment got the fitted number; the others kept their written numbers, and a tied segment's other
  readers were dropped. This was common (most stored piecewise models repeat a value), but it changed
  the refit's score in only a handful of groups (e.g. 019, sd-eras fail -> pass; 082 outliers, 104 none
  fail -> equivalent).
- `signature()` names hidden stocks by their place, not their name (groups that only rename a hidden
  stock merge: 105, 107, 110, 205, 206 none or counts).
- A group is right when it has the truth's structure, or when its stored members pass and its refit
  does not re-score as a fail. Before, stored statuses alone decided, so a refit that J moved to failing
  numbers still counted as right.
- L is checked before F; a failed `beats_scaled` or `refit_no_worse` makes T*'s fit bad (F, not E).
- Eta plausibility: the process check follows the engine noise (every observation kind sits on counts);
  `meas` compares the combined error variance alpha + rho2 E[x^2] with abs^2 + rel^2 E[x^2] within a
  factor 2 (not alpha and rho2 one by one), and `abs = rel = 0` no longer passes any alpha.
- X groups are left out of the A-bic comparison (they were counted as TIE or E there); a resumed cell
  drops its stale `timeout` flag.

**Not fixed here:** eta restarts inheriting the first start's eta (a change to the fit, so it needs
refitting, not re-labelling); physics and particle rows with their own scorer (the committed harness still
labels them C); the tau threshold (the user's open decision).

**Command** (code at `c0b9c85`; reads the three run folders, writes `objective_test/v1-74e6892a11`, no refit):

```sh
uv run sdlab-ladder objective-test --relabel v1-f6443f802e,v1-8d4dffc289,v1-e02ff355d9 --jobs 3
```

Sets here are the report's tag sets (first match of canonical, control, realistic, physics, real, noisy,
distilled, else tests; one cell per case and variant, the later folder winning). They are not the hand-made
sample sets of section 1, whose counts (171 of 233) this command does not reproduce: section 1 is not
rerunnable as written. "Before" is the label stored by the run; outcomes as defined in section 1.

| set | cells | judged | truth best | equivalent winner | wrong winner | label changes (before -> after) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| tests | 81 | 63 -> 63 | 58 -> **56** | 2 -> 3 | 3 -> 4 | OK 32 -> 31, E-price 3 -> 4 (305), others equal (C 9, E 2, S 26, none 9) |
| distilled | 39 | 35 | 26 | 2 | 7 | F 3 -> 2, S 10 -> 11 (153); E 1, E-price 3, L 1, OK 16, TIE-u 1, C 3, none 1 unchanged |
| noisy | 47 | 45 -> 46 | 32 -> **33** | 3 | 10 | E 9 -> 8, OK 13 -> 15, S 19 -> 18, L 0 -> 1, none 2 -> 1; F 4 |
| canonical | 28 | 28 | 20 | 0 | 8 | F 3 -> 2, L 1 -> 2 (111); E-price 4, OK 5, S 14, TIE-u 1 |
| control | 45 | 40 | 32 | 0 | 8 | F 5 -> 0, S 29 -> 34; E-price 1, OK 4, TIE-u 1, C 5 |
| realistic | 17 | 15 | 15 | 0 | 0 | none |
| physics, real | 92 | 0 | | | | all C |
| **all** | 349 | 226 -> 227 | 183 -> **182** | 7 -> 8 | 36 -> 37 | |

A-bic: X groups out turns 9 noisy and 3 tests TIEs (and one E, 050#1) into OK.

Cells whose label or outcome changed (14):

- F -> S (6; data-limited, now L before F, the cell keeps its failed sanity block): 153 counts, 201
  counts, 203 counts, 209 counts and none, 213 none. F -> L: 082 outliers, 111 counts.
- E -> F: 083 outliers (T* is beaten by its own numbers scaled, `beats_scaled` false).
- S -> OK: 083 meas, 087 meas (the combined measurement-error variance is within x2; alpha and rho2 had
  traded against each other).
- none -> S: 088#1 meas (abs = rel = 0, the truth fits alpha 1.29 on B; it now counts as truth best).
- 305-k8s-retries counts: OK -> E-price, truth best -> wrong winner. A group of common_cause/sindy models
  scored equivalent in the store, but its J-refit re-scores as a fail and beats T* by 7.7 nats with D in
  the truth's favour: J prefers failing numbers on an equivalent structure.
- 060 counts: truth best -> equivalent winner (an alternative structure, stored equivalent, refit fail,
  beats T* by 4.3 on a data-limited cell, L; the J-best is a right group).

The corrected baseline: truth best in 182 of 227 judged committed cells (tests 56/63, distilled 26/35,
noisy 33/46, canonical 20/28, control 32/40, realistic 15/15).
