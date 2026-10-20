# Kubernetes rung 4 (case 303): held_out's counts-short fail, and what held_out can represent

**Status:** done (2026-10-20; code 8d8f50d). 303 counts-short **fail -> pass**; held_out now passes all
20 cells of 300-303. No retirement. Earlier rounds on this rung: [k8s-303-c2.md](k8s-303-c2.md) (C2),
[k8s-303-c1.md](k8s-303-c1.md) (C1); earlier rungs [k8s-302.md](k8s-302.md), [k8s-300-301.md](k8s-300-301.md).

## Diagnosis (rule 4b)

After C1/C2 held_out passed every 303 variant except counts-short (`store.latest(case='303-k8s-daily-traffic')`,
row on b965158, identical held_out code to b9fe1d6). `sdlab-ladder analyse` rates counts-short achievable
(p 1.00), and 41 other strategies pass it, so the failure is the method's.

It returned the three true flows plus `responses_total -> outside 30.3` (5 pieces) and `outside -> inflight
0.0103 x queue` (scratchpad `ho/cands.py`). Every one of the 8 candidates held_out chooses between came out
wrong from the pinned `matrix.identify_one`:

| candidate (on all the data) | held-out error | what is wrong |
|---|---|---|
| forward, changing / constant inflows | 0.794 | only the counter's row: `outside -> responses_total 0.54 x inflight` (+ 5 pieces out of it) |
| backward, changing inflows (chosen) | 0.525 | chance pieces on the final counter, a 0.0103 cross-link |
| backward, constant inflows | 0.998 | `responses_total -> outside 0.0459 x queue`, the same cross-link |

This is k8s-302.md's cause A (chance pieces and leftover drain once the final counter fixes inflight's
drain), here on the counter's own row. Round 1 and round 2 copied earned_pieces' refit into 21 strategies,
but not held_out, which passed 302 after its input-blind judge was fixed (c33de93), so the refit never
reached it. Not the judge's fault: no candidate it was offered was right.

## The change (8d8f50d)

- held_out becomes a package with its own copy of the earned refit (`earned.py`, `earned_rows.py`,
  `earned_joint.py` from recession/ at 284390d, themselves matrix/ at 8c507a8).
- `fit_one`: every candidate fit, in each held-out fold (on the fold's steps) and on all the data, is
  `identify_one(..., keep_fit, keep_rows, input_columns)` then `earned.refit`. Rows chosen again, pieces kept
  only where earned, conservation decided jointly. A change inside each candidate's fit; the held-out
  choice between candidates is unchanged (it was, and remains, a selection between finished candidates, as
  the main line's judge is).
- `opts["earned"] = False` restores the old fits (the mechanism test uses it).
- Tests: `test_held_out_judge_rejects_a_candidate_whose_pieces_compensate_for_a_misread_flow` now runs
  with `earned: False` (with the refit, the trap candidate's rows are chosen again and it becomes the same
  model as "trust rows", so it is no longer the worst); a new test records the refitted behaviour: the trap
  and "trust rows" tie, skill@20 0.98 against the in-sample pick's 0.66, but births come out as a move
  adults -> children 0.03 plus a link 0.007 (truth: a link 0.022).

On 303 counts-short the refitted candidates give `queue -> inflight 0.6002`, `inflight -> responses_total
0.5016`, `outside -> queue 1.0015 x traffic` and nothing else (chosen: forward, constant inflows).

## Numbers

`uv run sdlab-ladder run --strategies held_out --cases 300,301,302,303 --jobs 4 --timeout 600`
(single-threaded, 8d8f50d): 20 done, 20 pass. Against each cell's previous row (all on held_out's
previous code, hash 8016caad): 19 pass -> pass, **303 counts-short fail -> pass**.

Paired sample: 40 cells drawn at random (seed 303) from held_out's latest rows on its previous code
outside 300-303 (31 pass, 8 fail, 1 equivalent), re-run on 8d8f50d with `sdlab-ladder run --strategies
held_out --cases <their 32 cases> --variants <their 9 variants>` (140 cells; scratchpad `ho/before.json`,
`ho/flips.py`). The same three flips appeared in an in-process run beforehand.

| cells | unchanged | fail -> pass | fail -> equivalent | equivalent -> fail | pass -> anything else |
|---|---|---|---|---|---|
| the 40 sampled | 37 | 1 (044-random-three-stocks#1 counts-long) | 1 (081-noisy-link meas-short) | 1 (083-noisy-goal-gap counts-long) | 0 |
| all 155 re-run cells with a previous row on the old code (incl. 300-303 and the 40) | 151 | 2 | 1 | 1 | 0 |

- The loss, 083 counts-long: both versions write the gap link `outside -> P = -0.2 x I` as `P -> outside
  x I` (0.2246 before, 0.2372 after) beside the constant (64.7 in 2 pieces before, 67.5 in 1 after); the
  scorer took the first as equivalent, the second not. recession lost the same cell to the same refit
  (k8s-302-round2.md); it is the earned refit's open loss, not new here.
- Runtime: summed discovery seconds over the 155 cells 95 -> 459 s (4.8x; not paired in time, machine
  load ~330 during the runs). Each of the 8 candidates is refitted in 6 fits (5 folds and all the data).
  Not reduced in this round.

## Capability remark

**Model class.** held_out is the pinned matrix main line (`matrix.identify_one`) with a different judge.
Each stock's change is linear in the measured levels and measured inputs: proportional drains, moves
between measured stocks, linear links, constant or piecewise-constant outside inflows (PELT pieces,
now kept only where earned), numbers split by announced eras, conservation (moves) decided jointly on the
counting likelihood, final stocks (no self-reading, no drain). eiv.py's errors-in-variables refit (pruning,
counter moves) handles 5% level error. The candidates are chosen by 5-fold blocked cross-validation instead
of the in-sample multi-step judge.

**What it cannot represent.** Anything outside a linear rate on measured quantities. From the store
(`store.latest(strategy='held_out')` grouped by case tag; scratchpad `ho/tags.py`; rows from mixed code
versions, most stale after this commit): hidden stocks 0/142 pass, delays 0/104, effects 0/148 and
effect tables 0/62, MIN 0/48, MAX 0/26, products 0/36, nonlinear 0/62, coflows 0/80, gap (goal-seeking,
signed links) 0/106 pass with 47 equivalent; matrix and earned_pieces have the same zeros. On the
kubernetes ladder its old rows fail every variant of 306-312 and 316-317 (MIN with ready replicas,
capacity, MAX, delays, effect tables, hidden stocks): that is the model class, shared with matrix and
the 20 earned-refit copies, and the fix there belongs to whatever adds MIN/capacity to the main line.

**Where its judge is worse than the main line's** (same tags, same mixed-version caveat): excitation
6/28 pass (matrix 24/28, earned_pieces 28/28), unannounced inflow changes 45/166 (matrix 63/166,
earned_pieces 72/166). Held out, a changing inflow's last piece is a stale guess, so it prefers constant
inflows when they are wrong (held-out-judge.md, the tickets test). Where it is better: independent stocks
161/198 (matrix 107/198), identifiability 42/52 (matrix 28/52); earned_pieces reaches the same (159, 42)
with the in-sample judge.

**Verdict for 303: fixable, fixed.** The failure was missing the earned refit every other main-line
strategy had, not a limit of the held-out judge. Not retired. (Its general status stays
"retire-candidate" from benchmark v1, held-out-judge.md; that is a separate question.) The coming
kubernetes rungs with MIN/capacity (306 on) will be a hard limit of the linear model class it shares
with matrix, earned_pieces and their copies, which cover everything it does.
