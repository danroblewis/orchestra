# Gradient descent through a differentiable SD simulator

**Status:** done (wave 2, benchmark v2)  
**Verdict:** needs a combination (refit numbers as a final step; generous structure not worth it)

## What was done
Branch `exp/gradient`, commit `268f595`. `diffsim.py` (a JAX copy of `simulate.Model`, matching it to 1e-9),
`gradfit.py` (multiple shooting 5 then 20 steps, L-BFGS, sparsity prices, fixed or learned inflows),
`structure.py` (an effect and a co-flow of every stock on every flow), `hidden.py`, strategy `gradient`.
JAX adds 273 MB.

## Mechanism tests
- Table effect: curve within 9.8% of its mean, skill 0.97/0.99 (matrix 0.36/0.82) -- only when inflows start
  flat and are learned under a smoothness price; from the matrix's pieces the effect is never found.
- Hidden stock: 0.196 / 0.104 (truth 0.2 / 0.1), receiver drain 0.2985 (0.3).
- Co-flow ratio ~0.53 (0.5), but learned as an effect, not a co-flow.

## Results (baseline v2: 31.6% / 32.1% / 17 of 62)
| attempt | skill@20 | skill@100 | goal | time |
|---|---|---|---|---|
| refined (matrix structure, numbers refitted) | 34.5% | 33.3% | 18 | 757 s |
| clean (generous structure, inflows learned) | 34.5% | 29.5% | 16 | 22,365 s |

## Lessons
- The judge (own fitted inflow pieces) rewards noise-tracking refits: on the effect synthetic the truth
  judges worse than the found model.
- Inflow pieces absorb nonlinear structure; choosing them together with it is what let an effect be found.

## Open ideas
- Refit numbers as a last step of the main line (like output-error).
- Choose inflow pieces jointly with nonlinear structure, not before it.

