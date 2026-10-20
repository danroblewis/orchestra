# Kubernetes rung 4 (case 303): realistic_hats' last failing cell (counts-short)

**Status:** done (2026-10-20; fix 099e99d). 303 counts-short fail -> pass; 300-303 no other flip (20 cells,
all pass). **Cost: 2 of 40 paired cells lost** (083 counts-long equivalent -> fail, 084 outliers-short
pass -> fail), both losses matrix's earned line already has. Earlier rounds: [k8s-303-c1.md](k8s-303-c1.md), [k8s-303-c2.md](k8s-303-c2.md),
[k8s-302.md](k8s-302.md). Strategy doc: [realistic-hats.md](realistic-hats.md).

## Diagnosis (rule 4b)

After the C1 and C2 rounds realistic_hats failed one 303 cell, counts-short (`uv run sdlab-ladder show
303-k8s-daily-traffic --strategy realistic_hats --variant counts-short`, code b9fe1d6): the three true
parts right (0.6375, 0.5402, 1.064) plus a spurious `responses_total -> outside`, a constant drain of
30.3 a step in 5 pieces, and a small `outside -> inflight 0.0103 x queue`. `sdlab-ladder analyse` rates
the cell achievable (p 1.00), and 41 of 49 strategies pass it, so it is the method's fault.

The answer is the base, unchanged: running the stages in process (scratchpad `rh/stages.py`) the pinned
main line `identify.identify` already returns exactly these flows ("backward, changing inflows, trust
receivers", judge 0.1738 against 0.934 for the forward candidates); the effect search accepts nothing,
the re-cut keeps it, and eiv.py does not act (no measurement error). It is k8s-302's cause A on the next
stock along: chance changepoint pieces on a stock with no outside inflow (here the final counter
`responses_total`) win the in-sample behaviour judge. realistic_hats was not among the 20 strategies
given earned_pieces' refit in that round because it passed 302 then.

## The change (099e99d)

realistic_hats' base is now matrix's earned main line: a copy of `matrix/earned.py`, `earned_rows.py`
and `earned_joint.py` at 49e4ca7 (byte-identical to the 17 other copies except a provenance note), so
each main-line candidate's outside-inflow pieces are kept only where the data earns them and
conservation is decided jointly on the counting likelihood, before the judge picks the base. Nothing
else changes (the effect search's own candidates still use the pinned `identify_one`). No step reads
the case or the kind of input; it is a change inside the base's fit, not a choice between finished
models.

In process the base then is `queue -> inflight 0.6004`, `inflight -> responses_total 0.5018`,
`outside -> queue 1.0017 x traffic` (scratchpad `rh/proto.py`).

## Numbers

**300-303** (`uv run sdlab-ladder run --strategies realistic_hats --cases 300,301,302,303 --jobs 4
--timeout 600`, single-threaded, 099e99d): 20 cells, 19 pass -> pass, 1 fail -> pass (303 counts-short).

**Paired sample** (40 cells drawn with `random.seed(303)` from the 357 non-kubernetes, non-node2 cells
whose latest row was the previous strategy hash 5e177e03; before = those rows, after = 099e99d; scratchpad
`rh/sample.json`, `rh/flips.py`): 

| | cells | unchanged | fail -> pass | pass -> fail | equivalent -> fail |
|---|---|---|---|---|---|
| sample | 40 | 38 (32 pass, 6 fail) | 0 | 1 | 1 |

- **083-noisy-goal-gap counts-long, equivalent -> fail.** The goal-gap link `outside -> P = 60 - 0.2 x I`
  now comes out as `outside -> P 67.1` plus a drain `P -> outside 0.236 x I` (same levels, a different
  flow), scored as a spurious drain. matrix, unified and recession (all on the earned refit) fail this cell
  too; effect_hats (no earned refit) is equivalent. It is the "recession 083" loss listed as undiagnosed in
  the earlier rounds, now inherited here.
- **084-noisy-two-chains outliers-short, pass -> fail.** 4 pieces on `outside -> B1` (mean 13.6, spurious)
  and B1's drain 0.384 for 0.2: the earned refit takes outlier jumps for inflow changes (the open "eiv /
  earned refit fooled by outliers" issue, 087). matrix, unified, lna and recession fail it; effect_hats
  passes.

So the trade on this sample is +0/-2 (with +1 on 303), against +24/-0 for the same refit on k8s-302's
sample for the main line. It is kept because it is the same refit 20 strategies already carry for the same
cause, and the two losses are open issues of that refit, not of this copy; fixing them in the refit
(outlier-robust change detection; the goal-gap link vs drain reading) would fix them here too. Tried in process and
not taken: dropping flows out of an announced final stock after the pinned main line (scratchpad `rh/protoB.py`):
with the drain gone, the joint refit gives `inflight -> responses_total 0.5018` but turns the small
cross-link into `outside -> inflight -0.037 x queue`, so it does not clean the cell either.

Runtime (summed discovery seconds; not paired in time, the after runs ran at load ~350): 300-303 4.2 ->
18.7 s, the 40 sample cells 31.7 -> 110.9 s.

## Capability remark

What realistic_hats represents (effect_hats at 89adae4 + an anytime cap + hidden_transit's pair search):

- **Model class:** the matrix method's linear rates (proportional `k x X`, linear links `c + sum k_i X_i`,
  constants), outside inflows as changepoint pieces, per-era rates, plus effects: a flow's rate times a
  piecewise-linear tent curve of one stock's level (table functions, fitted jointly), co-flows, and one
  hidden transit stock between a measured pair (Kalman likelihood). Measured inputs are columns in every
  fit; eiv.py refits numbers under measurement error.
- **Cannot represent:** MIN/MAX of two flows (306, 307: 0 of 183 and 0 of 108 cells pass, for every
  strategy), products of two stocks except as a tent effect (product tag 6% pass, combined2 47%),
  integrals/offsets of hidden accumulations (0%), switching/threshold/hysteresis (0%). Signed links (an
  inflow reading another stock with a negative number, a goal gap) are representable, but the earned
  refit can read one as a drain instead (083 above). Delays: one hidden first-order stage per measured
  pair (transit), no higher-order or pure delays.
- **Noise:** counts and measurement error via the base and eiv.py; outliers fool the earned refit (084).
- **Ladder** (store, latest rows, 2026-10-20): 591 pass, 216 equivalent, 536 fail, 52 differs, 42 error of
  1,437 cells; kubernetes 69% pass (lna 74%, unified 77%, combined2 74%); 300-303 all 20 pass at 099e99d;
  304-305 pass or equivalent; 306-307 fail (as every strategy). Among the 44 active strategies it has no
  unique pass (no cell it passes that no other active strategy passes); realistic_flows (its derivative)
  passes 14 cells it does not and fails 11 it passes.
- **Verdict:** its 303 failure was fixable (done). Its remaining limits (MIN/MAX, products) are shared with
  the whole matrix line, not structural to it alone, and it stays the realistic line's base (realistic
  timeouts 12 -> 1). Keep; do not retire.
