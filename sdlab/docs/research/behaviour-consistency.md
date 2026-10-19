# Behaviour-consistency gate against runaway models

**Status:** done (wave 3, benchmark v2.1), branch `exp/behaviour-gate`. Playbook M1.
**Verdict:** reject on the main line; keep `sdlab/discovery/gate.py` as a building block (the
acceptance check for strategies that add flexibility: hidden stocks, products, effects).
**Copies (2026-10-19, queue item 0c):** `gated_no_high` is now a package carrying its own copy of `gated` (`gated_no_high/_vendored/gated.py`, commit 0c7a76b, imports rewritten; CLAUDE.md invariant 11). Found flows byte-identical before and after on 23 cells.

## What was built
- `sdlab/discovery/gate.py`: `check(flows, stocks, run, opts)` -> `{"ok", "reasons", "culprit", "rho"}`.
  Free runs with floors and caps (`simulate.Model`) from 12 moments in the data for H = n/2 steps
  (100-500): "observed" (measured levels; own inflows, and inflows held at their means), "empty" (all
  stocks 0, mean inflows), "high" (5 x observed maxima, mean inflows). Fail: a stock beyond its
  observed max (from "high": beyond its start) by more than 3 x its observed range, scaled by the
  growth the data themselves show (log-level trend, continued for H steps). Culprit: the step's
  Jacobian at the failing state (linearisation with the floors and caps active there); the row and
  level whose coefficient raises the dominant eigenvalue most (sensitivity w_i v_j / w.v x the
  coefficient). `choose(candidates, stocks, run, judge)` gates, then judges those that pass (all if
  none passes).
- Strategy `gated`: identify()'s 16 candidates through the gate; a rejected candidate whose culprit
  coefficient is in one of its rows (no era split) is refitted once with it bounded at 0 (`lsq_linear`
  on the row's single steps with its inflow pieces) and re-enters as a candidate. Ablation
  `gated_no_high`: without the "high" test.

## What the data said first (before building)
Every candidate of the 31 default runs was graded and gated by hand (scratch diagnostics). **The
judge already discards runaways:** candidates that run away under their own (or mean) inflows have
judge errors 2-10^5 x the best and never win. The chosen candidate of the worst runs (bakery,
cloud-credits, clinic-doses, print-shop, support-tiers default) is *bounded* under its own inflows,
from observed, empty and high states; it diverges only under the truth's inflows, which the grader
substitutes (e.g. sd-bakery default: the orders row has no inflow and a drain of 0.0046; fed the true
40 orders an hour it fills without limit). So the hypothesis's premise - wrong candidates win by
replaying the data while holding a runaway loop - is false for the main line's candidates; it holds
for the flexible strategies (pysindy products, hidden stocks), which this gate can now serve.

## Mechanism test (`tests/test_strategy_gate.py`, 4 tests, pass)
- A spurious reinforcing loop (+0.02 x on x) with one inflow piece per step replaying the run: the
  judge prefers it (error < half the matrix model's) though it grades below -100%; the gate rejects it
  ("observed"), names x on x (k = 0.02) as the culprit, passes the matrix model; `choose` keeps the
  right one.
- The playbook trap (+0.02 own coefficient beside a constant, constant inflow 10, drain 0.1, 1000
  steps): rejected; the bounded refit recovers the drain 0.083 (0.1 +- 0.02) and the inflow ~8, and passes.
- Controls: a growing population (births 0.02, deaths 0.01) passes with rho 1.01 and `gated` keeps its
  growth (skill > 95%); sd-manufacturing's structure (all stocks measured, Jacobian eigenvalue 1.047:
  unstable linear part held by floors and caps) passes, and `gated` chooses as `matrix`.

## Results (baseline v2.1: 29.6% / 29.3% / 12 of 62; fresh runs 28.9% / 29.7%)
| strategy | skill@20 | skill@100 | goal | fresh @20 / @100 | changed |
|---|---|---|---|---|---|
| `gated` | 25.3% (-4.3) | 29.3% | 12 | 24.6% / 29.8% | 5 runs |
| `gated_no_high` | 29.6% (0) | 29.3% | 12 | 28.9% / 29.7% | none (identical in all 62) |

`gated`, runs moving > 2 points at skill@20: sd-orders default 76.2 -> 81.7 (+5.6; the refit bounded
budget's spurious link to stock, a loop budget -> stock -> budget that only shows when pending floors
at 0), sd-bakery long 18.8 -> -852.4, sd-support-tiers long 42.5 -> -342.4, sd-orders long 85.9 -> 75.4,
sd-restaurant long 65.3 -> 62.4 (@100 -75 -> 12). Every loss is the "high" test rejecting the judge's
best candidate (bakery long: all four constant-inflow candidates grow from 5 x max; support-tiers long:
hiring_budget from 5 x max) and the next candidate being much worse.

Gate counts (`gated`, all 62 runs): 836 candidates (incl. 52 refits), **278 rejected**: by test
(a candidate may fail several) high 258, observed 130, empty 93; only high 125, all three 61,
high+observed 58, empty+high 14, empty 9, empty+observed 9, observed only 2. In 6 runs no candidate
passed (fishery both, housing both, university both: the judge then chose as before). Without "high",
every observed/empty rejection was of a candidate the judge also ranked below the winner.

Run time: summed over runs 868 s (`gated`), 1034 s (`gated_no_high`) vs 586 s (v2.1), measured on an
overloaded machine (load ~200 on 28 cores), so only roughly 1.5x.

## Lessons
- Behaviour from 5 x the observed maxima is not evidence: found linear models extrapolate, and a
  coefficient that is harmless inside the data (a loop held by a term that floors at extremes) is
  judged by states the grader never visits. Rejecting on it costs more than it saves.
- Inside the data's range the in-sample judge (5/20/100 steps, own inflows) already does the gate's
  job for the main line's candidates. The main line's runaways are a different failure: wrong
  attribution of outside inflow (a stock with no inflow, a link standing in for one), which only shows
  when the true inflows are fed in.
- The culprit + bounded refit works where a spurious link closes a loop (orders default +5.6) - a
  structural repair, not a selection.

## Open ideas
- Use `gate.check` as the acceptance step of hidden stocks / products / effects (where replaying
  candidates do win the judge) - the use it was built for.
- Repair without rejection: offer the culprit-bounded refit of *every* candidate (also passing ones)
  to the judge; orders default suggests spurious loops hide in winners.
- A test for the real failure: a row with no outside inflow whose stock the data shows rising (a
  partial-model simulation per row, M8), or the judge run with inflows re-estimated coarsely.

## Why
The worst runs are runaways: a found loop grows where nothing in the data grows (v2.1 skill@20:
sd-bakery default -1170%, sd-clinic-doses -602%/-347%, sd-cloud-credits default -859%, sd-print-shop
-529%/-158%, sd-support-tiers default -548%). Four literature traditions recommend rejecting such models
before judging; the System Dynamics field reads behaviour modes off the eigenvalues of the linearised
model. Our data adds a caveat: some truths are unstable in their linear part and held by floors
(sd-manufacturing 1.047) or grow (population), so the test must be on simulated behaviour with floors
and caps, not on the spectral radius alone. Also an acceptance gate for added structure: the
hidden-stocks branch accepted a false hidden stock in sd-population in-sample. Playbook M1.

## How it could be tried
- In `identify()`, before the judge: free runs (H = 100-500) of each candidate from observed states,
  from all stocks at 0 and at 5-10x their observed maximum, with its own inflows, floors and caps;
  reject or penalise candidates that leave a generous multiple of the observed range when the data
  show no comparable growth.
- For a rejected candidate: the dominant eigenvalue of the per-era step matrix I + B and its
  sensitivity to each coefficient name the culprit; refit that row with it bounded (`lsq_linear`) and
  add it as a new candidate.
- Mechanism test: a stock with constant inflow 10 and drain 0.1 near equilibrium on a short run, with a
  trap candidate (positive own-coefficient plus a large constant); the gate rejects the trap, the refit
  recovers 0.1 within 0.02. Controls: a growing population keeps its positive eigenvalue; a floored
  unstable linear part is not rejected.

## Sources
Aguirre and Billings (1995) Physica D 80:26-40, doi:10.1016/0167-2789(95)90053-5; Umenberger et al.
(2018) Automatica 96:280-292, doi:10.1016/j.automatica.2018.06.036; Lacy and Bernstein (2003) IEEE TAC
48(7):1259-1263; Kaptanoglu et al. (2021) Phys. Rev. Fluids 6:094401; Kampmann and Oliva (2008) Syst.
Res. Behav. Sci. 25(4):505-519, doi:10.1002/sres.909; N. B. Forrester (1982) PhD thesis, MIT; Barlas
(1996) SDR 12(3):183-210; Forrester and Senge (1980) TIMS Studies in the Management Sciences 14.
