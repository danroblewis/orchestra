# Hidden stocks from delayed copies of levels

**Status:** done (wave 1, benchmark v1)  
**Verdict:** needs a combination (finds true hidden stocks; the acceptance step can be fooled)

## Question
In most failing examples the truth has unmeasured stocks between measured ones. Do first-order-delayed
copies of a stock's level, offered as regressors and turned into hidden stocks (A -> H -> B), recover them?

## What was done
Branch `exp/hidden-delays`, commit `2b8cbb8` (worktree `.claude/worktrees/agent-a2ea3ecc8609bbe06`).
`discovery/hidden.py`, strategy `hidden_delays`. After the usual candidates are judged, delayed copies of
each stock's level are offered to other same-unit rows; proposals are tried one at a time; an accepted
one becomes a hidden stock carrying its own estimated level (`result["inferred_levels"]`). Acceptance
needs: H fed mostly by A losing stuff into it (not a link); the receivers better explained with their
inflow pieces held at their means (with pieces the judge always prefers them); each stock's error
scaled by how far it moved. The delay is then tuned between grid points.

Grader extension (on the branch): a result may carry its own unmeasured stocks and their estimated
levels, started from that estimate, never from the truth; A -> H -> B counts as a hidden relation.
Bug fixed there: a found stock sharing an id with the truth's hidden stock used to start from the
truth's level.

## Mechanism test
a -> h -> b (h unmeasured), a's inflow changing 3 times, 2000 steps: recovered a -> H 0.208 (truth 0.2),
H -> b 0.1 (0.1), b drain 0.26 (0.25); skill@20 94%, @100 98%. `matrix`: a drained to outside, 12
inflow pieces into b; -25% / 72%.

## Results (baseline python: 70.8% / 68.9% / 18 of 42, parts 59.9%)
70.9% / 68.6% / **20 of 42**, parts 62.0%; 3.7x bench time. True hidden stocks found: sd-ci review
(long 93.5%/86.9% -> 95.9%/96.6%), sd-fishery cold store (long 29.5% -> 39.5%), sd-moderation vendor,
sd-recycling rail (long 86.4% -> 91.5%), sd-restaurant plating. sd-university default 85.7% -> 95.2%.
**sd-population default 68.2% -> 6.7%**: a false hidden stock adults -> elderly. Not found: kanban
(weak beside sprint spikes), supply (the truck stage is driven by the shop's level), support-tiers,
manufacturing, saas. The best bench setting (v8: 72.1%/69.6%, 20 runs, nothing worse by 2 points)
fails the mechanism test (synthetic -310%), so the committed version is the one that passes it.

## Open ideas
- An acceptance judge in-sample fits cannot fool: fresh-run grading, or the stability check
  (reject found loops whose modes the data does not show).
- The change scan uses one noise variance and over-segments counting noise (24-33 pieces where 4 are true).
- The main judge's per-stock scaling ignores stocks that only accumulate.
- Inflow pieces into a stock the truth does not feed replay their own run (a wrong model grades 100% on
  noise-free data): the reason for the bench's fresh-run column.
- Estimate the number of hidden states first (subspace methods) and their delays by deconvolution
  (literature reports).
