# schedules: a whole model's structure searched again, every number refitted jointly

**Status:** work in progress (commit fad2649; distilled 157-159 and their hard cases run; whole ladder 1,035 of 1,380 cells run, the rest not run)  
**Verdict:** promising as a specialist for schedules, eras and affine moves. On the distilled cases it
goes from 1 of 12 cells passing (censored) to 9 of 12. On the 1,035 paired cells run so far it passes
591 against censored's 503 (111 better, 1 worse). It is not yet a replacement for structures, which
passes 713 of the same cells. On sd-eras counts-long it makes behaviour much worse (see below).

Strategy: `schedules` (`sdlab/discovery/strategies/schedules/`). It builds on a copy of `censored`
taken at 2dee420 (`_vendored/censored`; CLAUDE.md invariant 11). Its cases come from the realistic
triage ([realistic-triage](realistic-triage.md), mechanisms G and H):

| case | mechanism | hard case |
|---|---|---|
| 157-two-chained-eras | announced eras on two moves of a chain, plus an unannounced inflow step | sd-eras |
| 158-affine-release | a move with a threshold, -6 + 0.02 x A | sd-reservoirs, sd-recycling (sell) |
| 159-periodic-pulse-and-top-up | a pulse of work and a capacity top-up every 14 steps, and a co-flow | sd-kanban |

## Why the leaders fail them

The main line fits each stock's row on its own, and with announced eras it fits each era's numbers
on their own. Conservation reconciles the rows afterwards. All three failures come from that:

- **157 (eras).** In a short or quiet era the rows are nearly collinear (the first era of 157
  starts near equilibrium). The main line then splits a move into a move plus a drain of its source
  and a link into its destination, used only in that era: A -> B 0.15 and A -> outside 0.15 in era
  1, 0 afterwards, with out -> C 0.23 x B and B -> outside 0.019 x C beside them. The model is
  exact in-sample (skill 100% noise-free), so no judge sees a problem. With counting noise the same
  freedom becomes a spurious drain of A of 0.36 and 22 inflow pieces (censored, counts-long).
  `sdlab-ladder analyse 157` finds every number identifiable in every variant, so this is a fault
  of the method, not a limit of the data.
- **158 (affine move).** The release `-6 + 0.02 A` makes the same levels as a move `0.02 A`, an
  inflow into A larger by 6 and a constant drain of B of 6. Each row alone prefers that: A's
  constant goes into its inflow pieces (26.5 instead of 20.5) and B's into a drain. Every leader
  scores *equivalent* noise-free and fails counts-short. The analysis calls counts-short
  data-limited (p = 0.23). The other three variants are identifiable.
- **159 (periodic pulse, top-up, co-flow).** A gets 25 on every 14th step and 1 otherwise. K is
  reset to 50 on the same steps (an inflow `50 - K` there, 0 otherwise). A -> B at 0.15 A uses one
  unit of K per unit moved. The main line reads A's inflow as a constant with drains on other
  stocks. Censored adds a floored gap `698 - 66.7 A` into K. Nothing in any leader writes a
  periodic schedule. The analysis calls every variant unidentifiable, because it treats each
  reset step's `50 - K` as its own pair of numbers: on one step only their sum shows. With one
  pair shared by all resets, the first cycles (K at 0, 5, 11, 12 before its resets) separate them
  noise-free. Under counting noise, K's measured level makes the shared `k` biased toward 0
  (errors in variables: -0.82 to -0.89 for -1). The analysis's verdict holds there.

## What it does

1. **censored's model** (the vendored copy) is the start. Two leaner starts are added: every
   pieced inflow as one piece, and only the flows whose rates are linear in their numbers (floors,
   gaps and effects dropped).
2. **Joint refit** (`refit.py`). Every flow whose amount is linear in its numbers becomes columns
   of one weighted least squares over all rows at once. This covers constant, proportional and
   linear rates, numbers per era group (`byTime`, grouped by era label or by a segment's `label`),
   and co-flows, whose `per` is held fixed. A move's number is shared by its two rows. Pieces of
   an outside flow are profiled out of their row and measured afterwards, as the mean of what the
   other flows leave there when stepped in the engine's form. Steps where some stock's outflows want
   more than it holds are left out of the fit, because the engine shares the level there.
3. **Beam search** (`search.py`, width 4). Each candidate is refitted and priced by the one-step
   BIC in the engine's form, plus 0.5 log T per flow. The steps offered are:
   - drop a flow;
   - one number for every era, or numbers per era;
   - a drop whose eras are handed to the flows beside it;
   - a constant on a move, replacing a constant or pieced flow at either end (158);
   - no constant;
   - a move for a drain of x and a link into y reading x;
   - a drain of x on another level z as an inflow `c - k z` (a goal gap);
   - a new move x -> y where y's residual rises with x;
   - a move that uses up a third stock (with u's other outflows dropped);
   - an outside flow as one-step pulses every P steps (P and phase from the residual, P ≤ 60).
     Pulses have a constant between them and a pulse that is constant or tops its stock up
     (`c + k x own`) (159).

   A step that adds numbers must win by 2 log T. A step that removes them must win by 0.25 log T.
   After each step, inflow pieces are merged (closed form) and cut. Cuts are found by binary
   segmentation that also tries 1-3-step bursts, keeping the best point on the path.
4. **Guard.** The result must behave on the data no worse than 1.5 x censored's model by the main
   line's judge, or censored's model is returned.

## Results

Commands: `sdlab-ladder run --strategies schedules --cases 157,158,159,sd-eras,sd-reservoirs,sd-recycling,sd-kanban --jobs 1 --timeout 300`,
then `sdlab-ladder sync --strategies schedules --jobs 1 --timeout 300` (stopped after 1,035 of 1,380 cells),
single-threaded, at fad2649, 2026-10-19. censored's stored cells are at a2d5e01 and structures' at 7e0a2bf.

**Distilled cases** (variants none-short, none-long, counts-short, counts-long):

| case | censored | structures | schedules |
|---|---|---|---|
| 157-two-chained-eras | F P F F | P P F P | **P P P P** |
| 158-affine-release | E E F E | E E E F | **P P F P** (counts-short is data-limited, p = 0.23) |
| 159-periodic-pulse-and-top-up | F F F F | F F F F | **P P F F** |

On 159's counts variants the structure is right: pulses every 14 steps into A, a top-up of K to a
level, A -> B 0.15 using K, and B's drain. The top-up's `-1 x K` comes out as -0.82 to -0.89,
biased toward 0 by the counting noise on K's level (errors in variables). This is the data's
limit, as the analysis's verdict says.

**Hard cases** (counts-short / counts-long; fresh skill@20):

| case | censored | structures | schedules |
|---|---|---|---|
| sd-eras | F 96.2% / F 54.1% | F 99.1% / F 54.1% | **P 99.3%** / F **-138.6%** |
| sd-reservoirs | F 93.6% / F 90.7% (recall 0.56/0.56) | F 98.5% / F 95.0% | **E 99.1%** / F 90.1% (recall 0.56/0.67) |
| sd-recycling | F 61.7% / F 93.3% | F 71.1% / F 93.3% | F 53.0% / F 93.3% |
| sd-kanban | F 83.3% / F 33.2% (recall/precision 0.64/0.35, 0.73/0.38) | F 77.4% / F 74.9% | F 39.6% / F 43.9% (0.82/0.82, 0.91/0.67) |

sd-eras counts-short passes, the first strategy to do so. On counts-long it does not:
censored's spurious loop finished -> raw stays, and the inflow's busy weeks lose their pieces. The
true structure's one-step BIC (185,233; 184,548 with level-weighted noise) is worse than the
model chosen (184,697). The cut search finds no cuts for the busy weeks, so the criterion prefers
the loop. The judge sees only 8% worse in-sample (0.388 against 0.359), but fresh skill falls to
-139%. On sd-kanban the equations are closer to the truth (recall 0.91, precision 0.67) but behave
worse fresh than structures'.

**Whole ladder, paired with censored** (1,035 cells both have): pass 591 against 503, equivalent
188 against 185; 111 cells better and 1 worse. The worse cell is 054-sweep-link-strength#5
counts-short, equivalent -> fail; the analysis calls it data-limited (p = 0.25). With structures
(1,055 cells): pass 591 against 713, 41 better, 165 worse. Not run at fad2649: 345 cells, mostly
the realistic cases and their long variants.

Fixed on the way (each a cell that lost to an earlier version):
- 046#8 and 006 counts-short: steps that add no numbers must win by 0.25 log T;
- 045#3: a drain and a link fuse into a move only when their numbers agree within 1.5x;
- 043#8: a tiny drain and link beside an existing move are dropped as a pair;
- 056#7: cuts are dearer;
- 054#5: a constant on a move replaces only a constant drain;
- 141 and 142: a drain on another level becomes a falling inflow only when it fits clearly better;
- 087 meas-short: pulses must stand 5 robust spreads out;
- 047#6: the falling-inflow rewrite itself.

## What remains

- **sd-eras counts-long:** the spurious loop. Cuts for inflow changes that a loop can imitate, or a
  held-out check in the guard, are the next things to try. A tighter judge slack (1.05) would
  reject it, but would also reject 158 counts-long (ratio 1.05).
- **159 counts:** the top-up's number is biased by measurement noise on the level it reads
  (errors in variables). A filter-based fit (as in kalman_lna) would be needed.
- **The rest of the whole ladder:** realistic cases and their long variants are not run at fad2649.
- **The beam is local:** it needed several composite steps for 157 and 159 (a drop that hands its
  eras to its neighbours, a co-flow that replaces the used stock's outflows). The search budget is
  60 s.
- No new distilled case was written.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (own copy of matrix/boundary.py, wired into this
strategy's search): see [declared-boundary-six.md](declared-boundary-six.md) for the hooks and the paired results.

## Kubernetes 306: the vendored main line (2026-10-21)

On `306-k8s-ready-replicas-cap` counts-short and counts-long (pool job 199, c7cade0), schedules was the
only survivor in the 306 round 3 set still failing counts. Its start (the vendored censored,
`_vendored/censored`, at 2dee420) took its main line from the pinned `sdlab/discovery/identify.py`, which
reads every input, including capmin's offered MIN series and the traffic input, in every row. On
counts-short, inflight's row read traffic, and the boundary pass paired that term into `inflight ->
errors_total = 0.052 x traffic` (true 0.03 x inflight). On counts-long the MIN landed on `queue ->
retries`. Current censored had already replaced that main line with its own earned one, which only
lets the limited flow's rows read the MIN series (capmin.excluded).

The change: `_vendored/censored/earned.py`, `earned_rows.py` and `earned_joint.py` are copies of
censored's at 6e18658, imports re-pointed to this package (its own boundary.py and capmin.py, which are
identical copies). The vendored censored's `main_line` now comes from them. The rest of the strategy
is unchanged. Pool job 204 (72d0aaf, 306 only): counts-short and counts-long fail -> pass (7/7 parts),
none-short and none-long stay pass, meas-short and meas-long stay fail (0 pass -> fail). Earlier rungs were
not re-run (one regression check at the end of the 306 round).
