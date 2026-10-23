# z3robust: Z3 under a noise band, for noisy data

**Status:** round 2 done (2026-10-21; commits 5f0f3aa, round 1, and 79d7da5, round 2); kubernetes 308-311
fixes ported 2026-10-22 (27df2d1, see Results). Keep as an active
strategy: on the Tests sample it now passes more than z3exact and matrix and fewer than milp and
structures; it is the best of the five on outliers and gaps, the worst on measurement error.
**Code:** `sdlab/discovery/strategies/z3robust/` (`robust.py` the formulation, `__init__.py` the
strategy, `core.py`, `flows.py` and `capmin.py` copies of z3exact's at 45bfaac, `compare.py` the
encoding timings, `post/` milp's post-program passes copied at a72bb0d). **Tests:** `tests/test_z3robust.py`. **Dependency:** `z3-solver` 5.3.1 (as z3exact).

## The question

z3exact (docs/research/z3.md, experiment B) asks Z3 for the fewest terms that fit every one-step change
exactly, to within the data's rounding. It is exact on noise-free data and has nothing to offer on noisy
data (its fallback is a plain backward elimination). Can Z3's optimisation features (OMT, MaxSMT,
lexicographic objectives) give a noise-tolerant version of the same search?

## The class (z3exact's, copied)

Each measured stock's one-step change is a sum of terms, each a number times a column: a measured
level, a measured input, or a constant, each split per announced era. A term is a move between two
stocks of one unit that reads one of its two stocks (z3exact's "ends" class), or an outside term on one
stock, allowed only where the declared boundary allows it ("kinds" as written, then "sides" as the
scorer reads it; the lower objective is kept). A declared `input` inflow's number is fixed at 1. A
capacity limit MIN(a X, b Y) with its regime is offered as one more series where the data show one
(capmin.py's offer, unchanged). A goal gap is a constant plus a level on one row. Three additions over
z3exact: with announced eras each column also has a whole-run copy, so a number that does not change
at an era costs one term instead of one per era (flows.py merges the two); steps whose spacing is not
the commonest (samples missing from `t`, the `gaps` variants) are left out instead of being read as
one-step changes; and a *link* (an outside term reading another stock) must be an inflow (number >= 0)
unless its stock also has an outside constant (then it is a goal gap, c - kX).

## The formulation that works (robust.py, encoding "band")

1. **Every step, in a few rows.** With X = U diag(d) V' (the one-step columns), a stock's squared misfit
   is ||U'y - diag(d) V' k||^2 plus a constant that no structure changes. So q = rank(X) rotated rows per
   stock (3 to 15 here) carry the evidence of all 300 or 2,000 steps, and under the true structure each
   rotated residual is one step's noise (white, since U is orthonormal). Before the rotation, *gross*
   steps are left out: a residual of the all-column least-squares fit beyond 5 robust noise levels in
   any stock (the outlier robustness; at most 20% of the steps).
2. **Noise levels from the data.** Each stock's rows are divided by sigma_s = 1.4826 x MAD of its
   all-column one-step residuals, x sqrt(T / (T - columns)), never below the data's rounding tolerance
   (z3exact's per-step epsilon). Noise-free data so get z3exact's tolerance back.
3. **An epsilon band that grows with the noise.** Each stock's rotated residuals must lie in an L1 ball
   of 0.8 q + 0.6 sqrt(q) noise units (the expected L1 of q unit normal residuals plus one standard
   deviation); where nothing fits at all, the ball is doubled, then quadrupled.
4. **The fewest terms, by Z3.** A Boolean per term (its number is 0 unless included), the residuals'
   absolute values as slack variables, the ball as hard linear constraints. Z3 (a `Solver` with an
   `AtMost(k)` assumption literal) is asked for a structure of at most k terms, k lowered from the last
   one found until Z3 says "unsat" (then the smallest size is proved), and then lists the other structures
   of that size (each found one and its supersets blocked; at most 12, 5 s).
5. **Choosing among them** (lexicographic: fewest terms first, then fit). The structures of the smallest
   size, and a warm start (backward elimination from all candidates on the same objective, with moves
   substituted for pairs of outside terms where that is cheaper), are compared on L1 + price, the L1 at
   each structure's L1-optimal numbers (HiGHS), the price sqrt(log T) per term (BIC's threshold in the
   rotated L1: dropping a term worth |t| standard errors moves the L1 by about |t|). Of structures within
   0.5 of the best (rivals the data cannot rank), the one with the fewest moves is kept: a prior, disclosed
   because it turns some `equivalent` verdicts into passes (link loops 046, 055) and some passes into
   `equivalent` (it can choose the wrong one of two equal rivals).
6. **Numbers by least squares** on every step (rows divided by their one-step noise level, the declared
   inputs at 1, steps beyond 5 noise levels left out once; a link the refit turns negative outside a goal
   gap is dropped), then z3exact's flow writer.

**Kept small:** at most 30 candidates per class (above that, a screen keeps terms whose (stock, column)
pair has a least-squares |t| > 2.5, a move needing it in both its rows), coefficients rounded to enough
significant digits for the equations' size in noise units (6 to 15), 25 s of Z3 per class and 90 s in
all. Z3 runs in a forked process killed 3 s past its timeout: Z3 did not honour its own timeout (a 25 s
limit ran 131 s on 306 counts-short in round 1). When Z3 is killed or finds nothing in time, the warm
start is returned and the note says so.

## What did not work (measured, kept as encodings in robust.py and compare.py)

- **Sampled steps (60 of 300).** On counts the empty structure won: near equilibrium the evidence for a
  drain is in many small fluctuations, and 60 steps do not carry it (007, 029 counts-short: 0 terms).
- **Blocks** (sums of consecutive steps, 40 per stock): exact for the class and every step used, but the
  sums average away the same fluctuations (counts: 0 terms on 007, 029, 043#4, 044#2).
- **One weighted objective (OMT)**: minimise sum max(0, |r| - band) + price x If(b, 1, 0). Exact and fast
  on 8 candidates (0.1-0.5 s), timeouts at 18 or more (20 s; also with big-M indicator variables, with
  the warm start's objective as an upper bound, with `optsmt_engine` symba, and with local branching in
  a radius of 2 switches). Asking Z3 only "is there a structure better than the incumbent?" (a feasibility
  check) took 10 s to say "no" on 18 candidates and over 30 s on 30.
- **MaxSMT** (MaxRes): terms and outlier marks as soft constraints under a hard band, or the L1 as a
  staircase of soft constraints ("ladder", a truncated L1): fast on 8 candidates, timeouts at 18-30. The
  same constraints through `Optimize.check` were also far slower than through a plain `Solver` (043#4
  counts-short: k = 28 timed out in Optimize; the Solver proved k = 9 smallest in 1.2 s).

Encoding times (2026-10-21, commit 79d7da5, here, single-threaded, 20 s per solve, class "ends, kinds";
`uv run python -m sdlab.discovery.strategies.z3robust.compare <cells>`):

| cell | candidates | band (Solver, AtMost) | weighted (OMT) | ladder (MaxSMT) | blocks, maxsmt |
|---|---|---|---|---|---|
| 007 none-short | 8 | proved, all listed, 0.03 s (4 terms) | optimal 0.13 s (4) | 0.11 s (4) | 1.8 s (4) |
| 007 counts-short | 8 | proved, 0.03 s (3) | optimal 0.37 s (4) | 0.15 s (4) | 0.05 s (0 terms) |
| 044#2 counts-short | 18 | proved, 0.62 s (6, warm start wins) | timeout 20 s | timeout 20 s | 0.12 s (0) |
| 029 counts-short | 30 | not proved, 20 s (warm start) | timeout 20 s | timeout 20 s | 0.04 s (0) |
| 043#4 counts-short | 30 | not proved, 20 s (warm start) | timeout 20 s | timeout 20 s | 0.10 s (0) |
| 081 outliers-short | 8 | proved, 0.04 s (4) | optimal 0.49 s (5) | 0.53 s (5) | 0.23 s (0) |

(043#4 counts-short was proved smallest at 9 terms in an earlier run of the same code on a quieter
machine; at 20 s it is on the edge.)

## Results

Pool jobs (2026-10-21, commit 79d7da5, `--priority 200 --by z3robust`): 228 and 229 (the Tests sample:
the 120 cases of jobs 206-209, declared-boundary.md, x none-short, none-long, counts-short, counts-long;
460 cells, some cases lack a variant), 230 (kubernetes 300-307, every variant, 40 cells), 231 (`tag:noisy`
x meas, gaps, outliers, short and long; 70 cells); 0 errors, 0 timeouts. Paired with the store's latest
results of milp, z3exact, matrix and structures on the same cells, as stored on 2026-10-21: those are of
mixed versions (the rung-307 workflow was editing some of them), and z3exact's missing cells (counts and
the noisy variants, 255) were run at the same commit for this comparison (jobs 232-240). milp's
none-long is "not run" on 47 cells (its none-short did not pass); those are left out of its pairs. Sign
test on the cells where exactly one of the two passes.

| set (cells) | z3robust pass + equiv | milp | z3exact | matrix | structures |
|---|---|---|---|---|---|
| Tests sample, none (226) | 118 + 19 | 124 + 12 of 179 (10 / 18, p = 0.18) | 96 + 41 (27 / 5, p = 1e-4) | 106 + 42 (30 / 18, p = 0.11) | 132 + 45 (31 / 45, p = 0.14) |
| Tests sample, counts (234) | 104 + 38 | 120 + 22 (8 / 24, p = 0.007) | 32 + 11 (75 / 3) | 102 + 24 (16 / 14, p = 0.86) | 147 + 28 (4 / 47, p = 2e-10) |
| Tests sample, all (460) | **222** + 57 (48%) | 244 + 34 of 413 (18 / 42, p = 0.003) | 128 + 52 (102 / 8, p < 1e-20) | 208 + 66 (46 / 32, p = 0.14) | 279 + 73 (35 / 92, p = 4e-7) |
| kubernetes 300-307 (40) | **33** | 33 (3 / 3) | 27 + 2 (6 / 0, p = 0.03) | 36 (0 / 3) | 34 (1 / 2) |
| noisy: gaps (16) | **6** + 2 | 3 + 1 (5 / 2) | 2 + 1 | 0 + 1 (6 / 0, p = 0.03) | 2 + 1 (6 / 2) |
| noisy: outliers (16) | **4** + 3 | 2 (2 / 0) | 2 | 0 + 1 | 3 + 2 |
| noisy: meas (38) | 8 + 1 | 17 + 1 (0 / 9, p = 0.004) | 14 + 2 (1 / 7) | 13 + 3 (0 / 5) | 16 + 3 (1 / 9, p = 0.02) |

("a / b": cells only z3robust passes / only the other passes.) Kubernetes per case: 300-302 and 304 pass
every variant they have (300 also meas-short and meas-long, which milp and z3exact fail); 303 all but
meas-long; 305 all but counts-long (counts-short passes, milp fails it); 306 none and counts, not meas;
307 none and counts-long, not counts-short or meas.

**Where it beats milp** (28 cells over the three sets: 18 Tests, 3 kubernetes, 7 noisy): link loops and loop gains (046, 054, 055: milp `equivalent`, the
fewest-moves tie rule), the teacup (104: 3 cells), outliers and gaps (080, 081, 087: the gross-step
filter and the gap filter), 300 meas, 305 counts-short, 141 none-short, 202 counts-long, 083 counts-short.
**Where it loses to milp** (56 cells: 42 Tests, 3 kubernetes, 11 noisy): unannounced inflow steps (048, 053: 14 cells; outside the class,
milp finds the change points), measurement error (080, 082, 084, 087, 088, 303 meas: 10; one-step
selection under errors in variables, the true structure does not fit the band and a spurious constant
does), announced eras (019: 4; 30 candidates with the whole-run copies, Z3 runs out of time and the warm
start keeps a spurious term), identical twins (037: 3), counts ties scored `equivalent` (007, 043, 045,
046, 052, 081 counts: 9), 170 (4), and one to two cells each of 044#4, 045#7, 049, 056, 058, 226, 305 counts-long, 307 counts-short, 081 gaps-short, 082 gaps-long.

**Solve times** (discovery seconds, from the jobs): Tests median 0.33 s, p90 18 s, max 59.9 s;
kubernetes median 13.9 s, p90 55 s; noisy median 0.51 s, p90 1.6 s. The cost is in cases of 6+ stocks or
with eras, where Z3 uses its 25 s per class and the warm start often decides.

**Round 1** (commit 5f0f3aa, jobs 224-227, the same cells): Tests 159 pass + 69 equivalent; its MaxSMT
engine (MaxRes) timed out on 18+ candidates, its screen dropped needed moves (043#4 kept 30 of 72
candidates by the larger |t| of a move's two rows), and a negative link was written as an outflow.
Round 2 fixed those three (the cardinality search, the both-rows screen, the link rule): Tests 222 + 57.

**Kubernetes 308-311 port** (2026-10-22, `docs/research/fixes/port-z3robust.md`; commits 8edfe20, 9032b6b and 27df2d1;
pool job 404). The climb's fixes were added around the Z3 search. milp's post-program passes were copied into
`post/`: controllers, floored gaps, counted moves and table effects, the hidden integrator, room-limited moves, the
delay stage, and tidy and conserve. Controlled stocks' rows are taken out of the Z3 problem, counters are never
readers, the capmin guards are in, and gaps are also read first. Result: 308-311 pass every achievable cell (none-*
on all four rungs and 308 counts-long, 8 of 8, 0 before). On 300-307, everything that passed before still passes,
and 307 counts-short now passes too.

## Verdict

**Keep as an active strategy; not a main-line candidate yet.** Z3's optimisation features as such
(OMT objectives, MaxSMT) do not scale here: they are exact on 8 candidates and time out on 18-30, the
size of a three- to six-stock case. What works is the epsilon-band reading of the problem: compress
every step into a few white rotated equations per stock, scale them by the estimated noise, and ask Z3
the feasibility question it is good at (does a structure of at most k terms fit the band?), with the
fit used only to rank the smallest structures. That makes Z3 useful on noisy data: z3robust passes 222
of 460 Tests-sample cells against z3exact's 128, is level with matrix (+46 / -32), and is the best of
the five on the outliers and gaps variants. It stays behind milp (-24 net, p = 0.003; milp's
change-point search and its numbers fitted jointly with the structure) and structures (-57 net), and it
is weak on measurement error, where every one-step method needs an output-error stage (k8s-306.md).

**Open:** an output-error refit for meas (oe.py elsewhere); unannounced inflow steps (outside the
class); a faster proof on 30 candidates (symmetry between per-era and whole-run columns; a stronger
lower bound for k); listing the band's smallest structures as an identifiability statement for noisy
data (z3exact's experiment A only speaks to noise-free data); a principled tie rule in place of
"fewest moves".
