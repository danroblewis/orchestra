# combined_r2: combined_misfit's choice, then combined_lean's leaner pass

**Status:** done on the ladder. The tests ran at e0bc5f5; the realistic runs ran at 781c56c (two
fixes to the leaner pass; see combined_lean.md). Examples bench: started, then stopped at the
coordinator's request (load). **Not run.**
**Strategy:** `sdlab/discovery/strategies/combined_r2/`: own copies of combined (`_vendored/`, from
237f52c), of combined_misfit (`misfit.py`, `fitcheck.py`) and of combined_lean (`lean.py`, `prune.py`).
**Verdict:** this is the proposal for combined's round 2 (queue 2f). It is the best of the three on
strict and close to combined_misfit on the realistic runs.

| | tests pass (936) | strict | noisy pass / strict (110) | realistic skill@20 (62) |
|---|---|---|---|---|
| combined (stored) | 679 | 618 (66.0%) | 26 / 19 | 40.6% |
| lna | 579 | 432 (46.2%) | 20 / 12 | 17.5% |
| combined_misfit | 678 | 617 (65.9%) | 26 / 19 | 45.2% |
| combined_lean | 682 | 649 (69.3%) | 32 / 27 | 39.4% |
| **combined_r2** | **682** | **649 (69.3%)** | **32 / 27** | **44.1%** |
| effect_hats | | | | 49.9% (54 runs, 12 timeouts) |

On the 54 runs effect_hats has, combined_r2 reaches 49.2% against effect_hats' 49.9% and combined's
44.9%. Paired with the stored combined over 63 runs it is +1.6 points (11 better, 12 worse, p = 0.72).
Paired with combined_lean, the same session, it is +5.4 (8 better, 8 worse, p = 0.71). Paired with
combined_misfit it is -0.4: sd-population long is worse (-42% against 46%) and sd-support-tiers long
better (95% against 42%). Sources and commands are as in [combined_misfit.md](combined_misfit.md) and
[combined_lean.md](combined_lean.md). The ideas and the offline study are in
[ideas-2026-10-18.md](ideas-2026-10-18.md).

## The declared boundary (2026-10-20)

Outside flows are a modelling decision the case makes, not something discovery may invent (the user's
approval, CLAUDE.md invariant 2; docs/research/declared-boundary.md). This strategy carries its own copy of
`matrix/boundary.py` at 723f72c (`combined_r2/boundary.py`; HIDDEN_PRICE 0, CLAIM_PRICE 2) and uses it:

- **lna's atoms** (the search lna, gap_prior, lna_pulses, lna_stack and its levels and products stages share,
  `_vendored/lna/`): an atom with an outside end (in, grow, link, gap, out, drain) is offered only on a
  declared side and kind (`atom_rule`: one that reads a measured input is "measured", any other
  "estimate"); the candidate set is filtered before the noise check and every later fit holds an atom off
  the boundary at 0 (swaps and stages cannot bring one back). A stock with no declared outflow therefore
  has no drain: what it loses is moves.
- The other specialists' copies (censored, effect_hats, common_cause, hidden_transit, periodic_inflows)
  start from the main line's matrix method (the pinned shared library, which they cannot change) and are
  kept inside the boundary by the guard on their models below.
- **Every candidate before the judge:** where a boundary is declared, each candidate model passes the guard
  (`inside_candidates`: a flow outside it becomes its best-priced alternative, a move into a stock of its
  unit, a link made a move, or nothing), with one refit budget for all candidates (GUARD_FITS 150 refits,
  and at most 30 s or half what the caller's timer leaves; past it the offending flows are dropped
  unrefitted, never kept). Identical candidates are guarded once.
- **The judge:** with no boundary declared, each outside flow is a boundary claim and adds CLAIM_PRICE x log T
  (on the -2 log L scale, so half that on the judge's negative log-likelihood) to the candidate's BIC.
- **The answer:** the guard and the anti-correlated pair moves once more (declared), or the moves and the
  priced claims (not declared), bounded the same way; `boundary` and `boundary_claims` in the result.

Results (CPU pool, 2026-10-20, paired: before = 3cc5c54, after = a578c86; same cells, variants and seeds;
`pool_results` of the jobs named; nothing timed out or errored):

| set | jobs (before/after) | pass + equivalent | invented boundary | discovery seconds (sum) |
|---|---|---|---|---|
| Kubernetes 300-305, all variants (28 cells) | 34/72 | 27 -> 26 (-303 meas-long) | 1 -> 0 | 594 -> 338 |
| 40 Tests cells (104, 114, 152, 155, 202, 207, 220, 012, 010, 063 x none/counts, short/long) | 35/73 | 8 -> 8 (no flips) | 28 -> 0 | 1069 -> 730 |

The Tests cells were chosen where the stored results had the most invented boundaries (and three that
passed). Every invented boundary is gone. The loss on 303 meas-long (in all six composites) is the
numbers, not the structure: before, the pick had three invented outside flows that the errors-in-variables
refit (eiv.py) dropped while instrumenting the numbers (queue -> inflight 0.56, true 0.6); now the pick is
already inside the boundary, eiv's multi-step check keeps the least-squares numbers biased by the
measurement error (0.68; instrumented 0.56 judged 0.212 against 0.209), and the cell fails on the numbers.
The fix belongs to eiv's acceptance test (next step). Discovery time rose on most of them (the guard over
every candidate and the final passes, each bounded at 150/120 refits and 30 s).
