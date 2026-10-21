# realistic_flows: realistic_hats with co-flows and the rows' own drains

**Status:** first version done, commit 4afc298 (round 2 on the realistic examples; triage in
realistic-triage.md, round 1 in realistic-hats.md). Measured on the 66 realistic runs and 592
hand-written test cells, 19 Oct 2026.
**Verdict:** keep as realistic_hats' successor: realistic mean skill@20 +2.9 points paired, goals
15 -> 16, test cells 11 more passes (19 better, 3 worse). Mechanisms B and C gain on their distilled
cases; D and E do not yet.

## What it does

`sdlab/discovery/strategies/realistic_flows/` is self-contained (CLAUDE.md invariant 11):
- realistic_hats at 06b0062, every module (transit/ included);
- coflow_hats' coflows.py, cycles.py, joint.py, price.py, search.py and translate.py at 9d891b0, and
  its co-flow stage (`_inflow_coflows`), run inside the anytime cap (each accepted co-flow becomes the
  answer so far). joint.py keeps effect_hats' 1e-12 bar for a column with no weight (coflow_hats'
  1e-24 made 131 none-short pick a wrong effect; 128 and 129 do not need it).

Changes of its own:
- **Own drains** (mechanism B). The matrix is run a second time (when the time left allows) with
  every variant's rows' numbers kept: `slack` 0 (a changing row's drain is no longer set to what
  same-unit receivers take whenever the two are within 30%) and `tol` 1e-6 (the reader no longer
  drops a number below 0.003, whatever the level it multiplies). The judge picks across both runs.
  Distilled 154: the births (0.022 B) were read as a move out of B and B's drain set to it; the
  0.002 B left over (~200 a step) went into B's inflow (582 against 800). Distilled 153: the link
  0.001 x O (O ~ 20,000) and O's drain 0.0005 were dropped as below 0.003.
- **Transit with and without the co-flows.** A co-flow can stand in for a hidden stage's exit (161
  counts-long: two drains read as co-flows, and the transit pair is then skipped). Transit is tried
  on the answer and on the answer before the co-flow stage, and the one the judge prefers is kept.
- **The own-drain base only when clearly better.** It replaces the matrix's base only when its judge
  error is 5% lower (`own_gain`). On near ties (sd-hospital short 2%, sd-emergency long 0.3%) the
  effect search built on it accepted effects that behaved far worse off the data (97% -> 33%,
  82% -> -100% at ac65a00).
- **Readings** (moves.py), tried on the effect stage's answer before the co-flow stage, on runs of
  any length; each refitted, inflows re-cut, priced and judged, kept when it prices better and
  behaves no worse (0.2%, `reading_margin`):
  - *A move driven by a third stock* (mechanism E, 152): A's drain reading S plus B's gain from S
    (S's drain read as a move S -> B, and a link outside -> B reading S), within a factor 2, become one
    move A -> B at k x S, and S's drain goes back to outside.
  - *A constant drain read as part of a move* (mechanism B, 131, 158): Y's constant drain and the
    same excess in X's outside inflow become the move X -> Y at k x X - c. Same dynamics, one outside
    flow fewer; kept unless it prices 2 worse (`drain_tie`).

## Results

All numbers from the store's latest rows (realistic_flows at 4afc298, realistic_hats at 06b0062),
both scored again by today's scorer in one process:
`JOBS=2 uv run python tests/study_rescore_pair.py realistic_hats realistic_flows tag:realistic OUT`
and the same with the 148 hand-written, non-parametric cases (`runner.select_cases`, 592 cells).
The realistic runs were made with `sdlab-ladder run --strategies realistic_flows --cases
tag:realistic --jobs 2` (4,952 s), under a machine load of about 400 on 28 cores.

**Realistic (66 runs; in-sample skill@20, each clipped at -100%):**

| | graded | timeouts | mean @20 (graded) | mean over 66 (timeout = -100%) | fresh@20 | goals met | equation passes | recall |
|---|---|---|---|---|---|---|---|---|
| realistic_hats 06b0062 | 65 | 1 | 44.5% | 42.3% | 43.8% | 15 | 0 | 0.566 |
| realistic_flows 4afc298 | 65 | 1 | 47.4% | 45.2% | 46.2% | 16 | 0 (1 equivalent) | 0.565 |

Paired on the 65 runs both graded: +2.9 points (se 2.0), 10 better, 5 worse (more than 2 points).

- Better: sd-ev-fleet long -28.6 -> 58.2, sd-moderation short -42.0 -> 22.6, sd-emergency short
  29.5 -> 65.9, sd-fishery long 23.7 -> 45.4 and short 41.7 -> 58.4, sd-orders short 76.2 -> 97.2
  (meets the goal), sd-manufacturing short 81.3 -> 88.5, sd-reservoirs long 94.9 -> 99.0, sd-farm-soil
  short 95.5 -> 98.5 (meets the goal), sd-support-tiers long 41.7 -> 44.2.
- Worse: sd-k8s-small short 58.2 -> 2.6, sd-recycling short 75.9 -> 66.4, sd-reservoirs short
  95.4 -> 89.6 (loses the goal), sd-population short 68.2 -> 62.5, sd-ci long 85.7 -> 81.9.
  sd-k8s-small short is load-dependent: the time cap stops its search (265 s); the same commit's
  code gave 58% in a run on a quieter machine (the strategy at that time differed only in stages
  that did not run). sd-reservoirs short: the own-drain base is 20% better on the judge and
  grades worse.
- An earlier version (ac65a00: own-drain base on any judge gain, readings within 10%) had +0.4
  points and 18 goals, with sd-emergency long 82 -> -100 and sd-hospital short 97 -> 33; 4afc298
  fixes both and keeps most gains (16 goals).
- Unchanged where the triage expected the co-flow stage to help: sd-print-shop, sd-clinic-doses,
  sd-cloud-credits, sd-sawmill, sd-learning-curve short, sd-support-tiers short. Long runs (over
  3,000 steps) skip the co-flow stage, as in coflow_hats.
- Repeatability: long runs end on the time cap, so their results depend on the machine's load
  (sd-k8s-small, sd-ev-fleet; realistic-hats.md).

**Distilled cases** (letters: none-short, none-long, counts-short, counts-long; mean in-sample skill@20):

| mechanism | case | realistic_hats | realistic_flows |
|---|---|---|---|
| B | 153 link from a large slow stock | FFEF -100% | EEEF 0% |
| B | 154 move into a stepping-fed stock | FFEF 39% | EEEE 100% |
| B | 131 effect fed by its flow | EEFF 13% | EEFF 83% |
| B | 158 affine release | EEFE 13% | PPFP 49% |
| B | 123 inflow shut by own level | FFFF 98% | FFFF 98% |
| C | 128 co-flow on an outside inflow | EEFF -51% | PPPP 84% |
| C | 129 co-flow runs empty | FFFF -34% | PFFP 7% |
| C | 130 move slowed by used stock | FFFF -19% | FFFF -19% |
| C | 161 hidden stage exit co-flow | FFFF 97% | FFFF 95% |
| D | 155 gap of downstream drives move | FFFF 99% | FFFF 99% |
| D | 124 gap over two stocks | FFFF 97% | FFFF 97% |
| D | 125 floored gap to measured target | FFEF 99% | FFEF 99% |
| E | 152 move driven by third stock | EEFE 88% | EEFE 88% |
| E | 126 product move | PEFP 50% | PEFP 50% |
| E | 127 predator-prey products | EEFE 90% | EEFE 90% |

153 counts: the link is not identifiable under counting noise (`sdlab-ladder analyse`: H <- O z
0.07); its -100% comes from the grader's swap of H's true inflow. 152's move is now found as A -> B
at 4 x S on none-short, none-long and counts-long (recall 0.83), but the scorer calls A's inflow
300 - 0.08 A an outside inflow reading A, so the status stays equivalent.

**Test cells (592 hand-written cells, same rescoring):** realistic_hats 152 pass / 71 equivalent,
realistic_flows 163 / 70. 19 cells better (128 x4, 129 x2, 132 x3, 154 x3, 153 x2, 158 x3, 016
none-long, 010 counts-short), 3 worse: 058-move-equals-other-chains-drain none-short and none-long
(pass -> fail) and 016-coflow counts-short (equivalent -> fail). Fresh skill@20 paired over 580
cells: +3.5 points, 33 cells better by more than 10 points, 4 worse.

## Next

- 058 none (pass -> fail) and 016 counts-short: find which stage (own drains, a reading or a co-flow)
  takes them, and gate it.
- D (155, sd-supply): the destination's gap is the reversed move plus a constant handed between the
  two stocks' inflows; both readings step the same, so it needs an SD prior (a move's rate reads its
  source or its destination's gap), offered as a reading like the two above.
- E on counts (152 counts-short): S's row (a small, fast stock) loses its stepping inflow; the
  reading needs S's drain right first.
- C on the long runs and the realistic co-flow cases: the co-flow stage runs only up to 3,000 steps
  and changed none of sd-print-shop, sd-clinic-doses, sd-cloud-credits or sd-sawmill.
- Time: a fixed-budget mode (or a load-independent cap) so long runs are repeatable.


## The declared boundary (2026-10-20)

Outside flows only where the case declares them ([declared-boundary.md](declared-boundary.md)). The package
carries its own `boundary.py`, copied from matrix/boundary.py at 723f72c (HIDDEN_PRICE 0, CLAIM_PRICE 2),
with changes of its own marked "(this copy)": a guard refit budget (GUARD_FITS 60, then a flow outside is
dropped without a refit), an estimated side may hold a flow reading a measured input (the cases declare
"estimate" for any flow not driven by inputs alone, 217), no self-move among the alternatives, and the
helpers `inside`, `keep_inside`, `placement_ok`. In its own search: as coflow_hats, and the readings (moves.py) that leave the boundary are not offered; the transit search tries B's outside constant and A's share to outside only where declared and offers no transit model outside the boundary; the final passes run in at most half the time left on the item's timer. Every answer ends with
`boundary.apply` (the guard and the moves; with no boundary declared, outside flows are priced boundary
claims, listed in `boundary_claims`). The eiv copy holds an instrumented refit with nothing to prune to the
pruned model's longest-horizon test (303 meas-long).

Paired on the CPU pool (commits 71ec999, 9cfeb75, d5cd56a; before = this strategy at 3cc5c54 on the same
HEAD, branch boundary-before-hats): Kubernetes 300-305 (28 cells, jobs 54 -> 119) 26 -> 28 pass (304 none-long, 305 none-long fail -> pass); 40 Tests
cells (008, 028, 059, 114, 117, 154, 196, 203, 208, 213 x none/counts short/long; jobs 57 -> 120)
8 -> 8 pass, 9 -> 11 equivalent (008 counts-short, counts-long fail -> equivalent). Invented boundary (k8s / tests): 2 -> 0 / 10 -> 0. Timeouts unchanged (154 counts-long times out on
both sides where it did). Kubernetes 316-317 (job 122, after only, 8 cells each; none-long skipped by the pool): no pass; timeouts only on 317 (meas-long in five of the six, counts-long in effect_hats and own_tables, meas-short in own_tables), where the stored results at 793b5b5 already timed out on 317's long variants; coflow_hats now finishes 317 counts-long and meas-long.
