# Hidden stocks reconstructed from a unit's mass balance

**Status:** idea (not started)

## Why
20 of the 31 truths have a hidden stock, mostly a delay between two measured stocks of one unit:
cloud-credits postproc, sawmill kiln, learning-curve escalated, webshop in_transit, restaurant
plating, fishery cold_store, kanban undetected, ev-fleet returning, housing permits, support-tiers
trying. The main line reads such a delay as an outflow to outside plus inflow pieces into the
receiver. On sd-cloud-credits default it finds running -> outside at 0.44 (truth: 0.25 into postproc)
and gives results 36 inflow pieces. On sd-sawmill it finds planks -> outside at 0.23 (truth: 0.25 into
the kiln).

Conservation gives the hidden level directly: H(t) = H(0) + cumsum(what A sends "outside" - what B
receives from "outside"). So a found outflow paired with same-unit inflow pieces elsewhere becomes an
estimated level series. That series joins the matrix as one more stock; its drain is 1 / residence
time by Little's law. This is nonparametric: unlike [hidden-stocks](hidden-stocks.md) it needs no
delay grid, and unlike [delay-deconvolution](delay-deconvolution.md) it estimates no kernel. It also
comes with a check that in-sample fit cannot game: a true pairing gives a bounded, nonnegative H, a
false one drifts.

## How it could be tried
- Strategy `mass_balance`, module `discovery/balance.py`. From the main line's result, list candidate
  pairs: A's outflow to outside, and B's inflow pieces, of the same unit.
- Form H_t = cumsum(alpha x k_A x A_t - u_B(t)), with alpha in (0, 1] (the share of A's outflow that
  goes to B) fitted so that H has no drift. Reject a pair if H is not stationary (ADF/KPSS) or goes
  below 0 by more than its noise.
- Add H as a column in B's row and give H its own row. Accept by the judge with B's pieces held at
  their means (the hidden-stocks acceptance rule), behind the behaviour gate.
- Output an unmeasured stock with its inferred levels (the grader extension on `exp/hidden-delays`).
- Mechanism test: a -> h -> b with h unmeasured (0.2 and 0.1) and a's inflow changing 3 times, plus an
  Erlang-2 variant. Expect corr(H, true h) above 0.95, rates within 0.02, skill@20 above 0.9 (matrix:
  -25%). Controls: a true outflow of A with an unrelated true inflow into B gives a drifting H that is
  rejected; a population-like model gets no hidden stock.
- Targets: the ten examples above, plus sd-ci, sd-recycling and sd-saas.

## Sources
Little (1961) Oper. Res. 9(3):383-387; Godfrey and Chapman (1990) Math. Comput. Simul. 32(3):273-295;
Kwiatkowski et al. (1992) J. Econometrics 54(1-3):159-178 (KPSS); Hurtado and Kirosingh (2019) J. Math.
Biol. 79(5):1831-1883; Daniels and Nemenman (2015) Nat. Commun. 6:8133 (one hidden variable at a time).
