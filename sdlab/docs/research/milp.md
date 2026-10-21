# milp: structure and numbers by one mixed-integer program (HiGHS)

**Status:** work in progress (v1, 2026-10-21, commit 1ba6519). The first strategy to pass Kubernetes
rung 7 (`306-k8s-ready-replicas-cap`): 4 of 6 variants (none and counts, short and long; the two
`meas` variants fail). On the Tests set it passes 60.3% of its cells against matrix's 49.1% and
structures' 66.4% on the same cells; it has no hidden stocks, delays, effects or products. Code: `sdlab/discovery/strategies/milp/`, tests `tests/test_milp.py`. Dependency:
`highspy` (MIT), added to `pyproject.toml` / `uv.lock`.

## Why

Every strategy failed rungs 306-312, which all contain 306's dispatch `min(0.6 x queue, 40 x ready)`
(docs/research/kubernetes-ladder.md, "Rung 7"). A regression has to guess which steps are capped and
then fit the coefficients; once the move `queue -> inflight` does not balance, the rest of the model
falls apart into links and exits. A mixed-integer program chooses the regime of every step and the
coefficients jointly: piecewise-affine identification by MIP (Roll, Bemporad and Ljung 2004,
Automatica 40(1)), and the structure itself as best-subset selection (Bertsimas, King and Mazumder
2016, Ann. Stat. 44(2); Bertsimas and Gurnee 2023 for SINDy-style discovery by mixed-integer
optimisation).

## Formulation

Data (`steps.py`). Step k runs from the levels at `t[k]` to `t[k+1]`; its change `dy[s,k]` is
`L[s,k+1] - L[s,k]` less the announced injections at `t[k+1]`, and its rates read the levels at `t[k]`
with those injections added, and each measured input at `t[k+1]` (the engine's convention; checked on
306, where the truth then leaves only the data's 1e-4 rounding).

Candidates (`candidates.py`, the same rules for every case):

- a move `i -> j` between measured stocks (`i` not final), proportional to `i`;
- an outside outflow from `i`, proportional to `i`, and an outside inflow into `j`, only where the
  declared boundary has that side (`run["boundary"]`, a hard constraint). A `measured` inflow reads
  the measured inputs only; an `estimate` inflow reads a constant, the inputs, the other stocks
  (links), and any stock with a negative number (a goal gap `c - k x level`, 0.5 log T extra).
  With no boundary declared every outside flow is allowed but is a boundary claim priced
  `CLAIM_PRICE = 2` log T on top of its numbers (as matrix's `boundary.py`);
- with announced eras, a signed change of every term per era (its rate in the era stays >= 0);
- a declared outside flow is a given, not a choice (the user, 2026-10-21): each declared side has at
  least one of its plain columns switched on (a row `sum z >= 1` in the program), the local search
  never removes its last part, and if no solve returns a model the declared flows are returned in
  their plainest form, fitted by least squares, with `milp.note` saying so. The result is never `[]`
  where a boundary is declared;
- a capacity-limited flow from `i` (a move, or an outflow where allowed): `MIN(a x i, b x Y)`, `Y`
  another measured stock that is not a counter, or an input.

Every number is non-negative (so is every rate), and conservation holds by construction: a move's
amount leaves one stock and enters the other.

The program (`program.py`): every candidate is a column with amount `v x f[k]`, `0 <= v <= ub z`,
`z` binary (in the model). A MIN's regime (which side is the lesser at step k) is a threshold on
`src[k] / cap[k]`: the demand side is the lesser exactly when `src / cap <= theta = b / a`. So the
per-step regime binaries of the Roll-Bemporad-Ljung formulation, `m <= a src, m <= b cap,
m >= a src - M (1 - d), m >= b cap - M d`, can only take the K + 1 patterns of a threshold over the
sorted ratios. The first version wrote exactly that (per-step `d` with the monotone chain
`d(1) >= d(2) >= ...`); HiGHS found no incumbent within 60 s on 306 (48,860 columns, 7,324 binaries).
The version here chooses `theta` among quantiles of the ratio (GRID = 8 per MIN flow, a group of
which at most one is used, and 12 more around the refitted threshold on later solves); the column is
then `f = MIN(src, theta x cap)` with `v = a`, and the refit frees `theta`.

On K = 150 steps evenly spaced over the run (all steps when shorter), for every stock s and step k:

    dy[s,k] = sum_columns sign(col, s) v_col f_col[k] + p[s,k] - n[s,k],   p, n >= 0

    minimise   sum_s,k (2 T / K) (p + n) / scale[s,k]          (Laplace -2 log L of the changes)
             + log T x (numbers: 1 per term, 2 per MIN)       (BIC)
             + CLAIM_PRICE log T x (outside flows, undeclared boundary only)

HiGHS solves mixed-integer *linear* programs (no MIQP), so the misfit in the program is absolute
(least absolute deviations); least squares comes after, on every step. `scale` is each stock's noise
scale: at first the scatter a plain linear fit leaves, then the mean absolute residual of the last
structure; with counts data (every level an integer) it grows as the square root of the amount moved
through the stock in the step (a Poisson-like weight).

The search (`__init__.py`): solve 1 has no MIN columns (a pure best-subset MILP; it closes its gap on
every case seen). Each later solve (at most 4) offers MIN flows on the pairs the last structure
moves between, plus the 6 MIN flows that would explain most of what it leaves unexplained alone (a
least-squares screen, column generation's pricing step); it starts from the last answer with the
screen's best MIN in place of the move it would limit, and searches within 10 switches of that start
(local branching, Fischetti and Lodi 2003). Each solve is limited to 100 branch-and-bound nodes
(deterministic) and 60 s (a safety limit); `mip_rel_gap` 1e-4, one thread. The loop stops when a
structure repeats, is not better (BIC on every step) than one already found, or explains every change
to within 10 x the data's floor.

Inflow steps (unannounced changes of an estimated inflow, `__init__._with_steps`): not in the program
(its 150-step sample sees too little of each stretch, and its absolute misfit at a fixed noise scale
prefers no flow at all over a constant that cannot follow the steps: on 027 and 048 the first
version returned `[]`). After the solves, what the rest of the model leaves of the stock's change is
cut into stretches of constant mean by optimal partitioning (dynamic programming; a price of
`factor x log T x` the noise variance per change, the variance from step-to-step differences,
stretches at least 5 steps), the steps are added as signed `piece` parts of the inflow's constant, the
model refitted, and the partition redone from the refitted rest, up to 5 times (a drain fitted without
the steps takes part of them up and hides them, so drain and steps are found in turn). It is tried at
factors 1 and 0.5 and without steps; each start goes through the local search below and BIC (pieces at
2 log T) chooses. Written as `byTime` segments.

Refit and local search (`refit.py`): the best structure's numbers by least squares on every step
(analytic Jacobian; a MIN evaluated exactly; a stock's proportional drains together at most 1 a step,
as a penalty). For counts data, the amounts are the expected amounts when whole things move: a stock's
outflows drawn Poisson around their total rate D share what it holds, so it loses on average
`E[min(N, level)]`, N ~ Poisson(D) (normal approximation). Without this the counts-long 306 answer
kept a spurious `inflight -> retries` (0.004 x inflight) to make up the 3.3 a step the truth's
retries lose to that cap. Then a local search on Gaussian BIC (per-stock variance profiled): drop a
part (never a declared side's last), read a MIN as its demand alone, send a flow to another allowed
destination, or move an inflow step by 1-4 steps, taking the first change that improves BIC, until
none does.

The result: `{"flows": [...], "milp": {"solves": [{status, seconds, gap, objective, bound, nodes,
columns, rows, binaries}], "seconds", "solve_seconds", "gap", "gap_closed", "candidates", "sample",
"counts"}}`. Flows are matrix's format; a MIN is `{"form": "expr", "expr": "min(a * src, b * cap)"}`
with an `id`; an era-dependent flow has `byTime` segments.

## Results

All numbers from pool jobs at commit 1ba6519 (2026-10-21): `uv run sdlab-ladder job 193 --json`
(300-312, 027 and 048, every variant) and `uv run sdlab-ladder job 192 --json` (the Tests set: every
numbered case, `--cases 0,1,2,3`, long variants only where the short one passed). The paired
comparison takes matrix's and structures' latest stored rows on exactly milp's cells (`store.latest()`;
their versions are mixed, the main line has a backlog: matrix rows from c0f0e7a 162, 1403d66 147,
723f72c 62, ...; structures 1403d66 150, 7e0a2bf 135, ...). Timeouts count as not passing.

**Rung 7, 306 (job 193):** none-short pass (16 s), none-long pass (44 s), counts-short pass (52 s),
counts-long pass (59 s), meas-short and meas-long fail. none-long's found model (job 193's stored
flows; `uv run sdlab-ladder show 306-k8s-ready-replicas-cap --strategy milp --variant none-long`):

    queue -> retries = 0.08 * queue            retries -> queue = 0.6 * retries
    retries -> outside = 0.4 * retries         outside -> queue = 1 * traffic
    inflight -> responses_total = 0.5 * inflight   inflight -> errors_total = 0.03 * inflight
    queue -> inflight = min(0.6 * queue, 40 * ready)

the truth exactly (7/7 parts, no spurious part). On counts-long the MIN came out `min(0.6017 x queue,
40.20 x ready)` and the retries split 0.600 / 0.378; counts-short passes with `min(0.583 x queue,
38.6 x ready)` beside a small extra `queue -> inflight = 0.012 x queue`, merged with it by the scorer
and within tolerance. On the way:

- the first solve (no MIN columns) answers `queue -> inflight = 0.198 x queue` and `retries ->
  inflight = 1.0 x retries`, the wrong shape every regression strategy reports; the screen then
  offers MIN flows and the second solve finds `min(0.6 x queue, 40 x ready)`, after which the retries
  route right;
- counts: the truth itself leaves retries +3.3 a step on average one-step (its two outflows total 1.0
  x retries, and Poisson draws above the level are cut to what it holds); without the capped
  expectation in the refit a spurious `inflight -> retries` (0.004 x inflight, 2.7 a step) took it up
  and failed the cell;
- counts-short's split (0.529 / 0.471 before the drain-total constraint) is data-limited: `sdlab-ladder
  analyse` gives p 0.30 to reach it within tolerance (bound SE 0.089 against 0.06 allowed); the truth
  structure scores better BIC than the mis-routed one (787 vs 804 on counts-short, 5273 vs 5387 on
  counts-long), so the mis-routings seen along the way were search failures, fixed by the local search;
- meas (5% measurement error on every level): one-step changes of noisy levels carry the noise twice
  and the regressors carry it too (errors in variables); milp has no measurement model or instrument,
  so its numbers are biased and the structure breaks (e.g. `retries -> queue = 0.91`). Method limit.

**300-312 (job 193):** 31 pass, 1 equivalent, 14 fail, 12 timeouts of 58. 300-305: every none and
counts variant passes except 305 counts-short (fail); 300 meas fails both lengths (errors in
variables), 303 meas passes both. 307 (rung 8, CPU links beside the MIN): none-short and counts-short
pass, none-long equivalent, counts-long fail. 308-312 fail or time out (300 s on the pool): their
HPA, pod start-up, OOM and autoscaler flows are `ceil`/`max` controllers, table effects of memory,
a hidden leak and a hidden provisioning delay, none of which milp's candidates can write. 308
none-long finds the MIN and every rung-8 flow right (9 of 12 parts) and misses only the controller
flows of `ready`.

**027, 048 (the coordinator's report: milp returned `[]` on 048 counts-long, every draw).** Cause: the
first version had no inflow steps, and with the program's misfit priced at a noise scale taken from a
crude fit's scatter, "no flow" leaves less absolute misfit than any constant that cannot follow the
steps (the scale is then re-estimated from that model: a fixed point). Not a timeout or a gap (the
solves closed in milliseconds). Now the declared flows are always there and the steps are searched
for: 048 none-short and none-long 8/8 each, counts-short 7/8, counts-long 6/8 (#1 and #8 fail); 027
none both pass, counts both fail. The four failures keep a constant inflow and a drain far too slow
(0.012-0.04 against 0.1-0.16): no step start beats the no-step model on BIC there, because the drain
fitted without the steps takes them up (the search alternates drain and steps from that start, but
too few steps survive the 2 log T price on counts). Matrix also fails 027 counts-long.

**Tests set (job 192):** 1,161 cells run: 700 pass, 66 equivalent, 375 fail, 20 timeouts (113 long
cells skipped because the short one failed). Item time median 2.5 s, 90th percentile 38 s, max 298 s;
275 CPU-minutes in all.

| on milp's cells | milp | other | paired difference (95% CI) | only milp / only other |
|---|---|---|---|---|
| vs matrix, pass (1,161) | 60.3% | 49.1% | +11.2% [+9.0, +13.4] | 160 / 30 |
| vs matrix, pass or equivalent | 66.0% | 59.8% | +6.2% [+4.1, +8.3] | 119 / 47 |
| vs structures, pass (1,152) | 60.4% | 66.4% | -6.0% [-8.4, -3.5] | 72 / 141 |
| vs structures, pass or equivalent | 66.1% | 77.7% | -11.5% [-13.8, -9.3] | 32 / 165 |

Earlier versions on the same set, for the record (each a pool job): v1 at 846655e (no eras, gaps,
steps or forced boundary) 507 pass of 1,133 (44.7%), level with matrix (45.2%); 6f5766f 499; b98c16b
494. The rise to 700 came from the declared boundary always present plus inflow steps (c483f97,
job 188 cancelled at 1,070 cells with 652 pass) and the local search.

Solver: the first solve (no MIN columns) closes its gap on every case seen (0.0-2.9 s on 306/307).
Later solves stop at the 100-node limit with the gap open (306 none-short: gap 0.37-0.47 after 100
nodes, the LP bound of the big-M formulation is weak), or at the 60 s safety limit on the largest
(307 counts-long). The node limit makes a solve deterministic only when it is reached before the time
limit; the root (cuts and sub-MIP heuristics) can take 10-40 s on 306-sized programs, so pool results
on a loaded machine can differ from a local run (seen: 306 none-short failed on node2 at b98c16b and
passed locally). The result reports each solve's status, seconds, gap, nodes and size.

## Where it breaks

By tag on the Tests set (job 192, pass / cells): 0% on everything milp cannot write, hidden (0/76),
delay (0/82), effect (0/101), product (0/22), nonlinear (0/47), control (0/63), coflow (0/24),
canonical (0/49), integral, offset, oscillation; low on min (9/40) and capacity (9/37: MINs of a level
and a constant capacity, or of sums, are not candidates), noisy (61/154), input (54/187), loop
(77/201), link (97/206), injection (24/86); high on chain (349/439), inflow (118/125), independent
(180/195), parametric (294/317), identifiability (46/50), timescale and run-length (all).

Also: measurement error (errors in variables, no instrument), a MIN whose capacity is a constant or a
sum of stocks (`min(0.5 x pending, 4 x nodes - ready)`, rung 12), MAX terms (not built), counts data
where an inflow steps and the drain is slow, and time: 20 timeouts on the Tests set and 12 on
300-312 (the largest programs and the local search over many inflow steps).

## Verdict

Adopt the idea, not yet the strategy. The joint program does what no regression strategy did: it
recovers rung 7's MIN exactly on noise-free and counts data, and with the declared boundary forced,
eras, gaps and inflow steps it beats matrix by 11 points of pass rate on the Tests cells (+160 / -30
cells). It is still 6 points below structures, has nothing for hidden stocks, delays, effects or
products, no measurement model, and its larger solves are time-limited (not reproducible across
machines). Next: MIN capacities that are a constant or a linear combination (rung 12), a MAX column,
an instrumented refit for measurement error (matrix's EIV), and the MIN columns offered to the
structures / combined lines (a copy of `candidates.py` and `program.py`) where hidden stocks and
effects already exist.
