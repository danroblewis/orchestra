# engine_forms: the forms the engine can now write, read back by discovery

**Status:** work in progress (distilled cases 217, 220-225, 130, 131; the whole ladder checked offline
against kalman_lna's stored models; see "Results").

## Why

The canonical cases 113-117 and the control cases use the engine features of queue item 2d (two-way
flows, signed stocks, MIN, switches). The distilled cases 220-225 and 217 isolate the leaders'
mistakes: a rate that changes sign written as floored one-way flows (220, 221), MIN(capacity, level)
written as one function of one argument (222), an inflow switched on by another stock read as a move
out of it (224), an admission gate on a measured input read as `k x input` plus pieces (217), and a
switch with memory read as about 180 inflow pieces (225).

## What it does

`sdlab/discovery/strategies/engine_forms/`:

- `_kalman/`: a copy of kalman_lna at commit 6a93270 (imports renamed), the base.
- `steps.py`: the run as one-step changes (each step's start state after its injections, the inputs
  of the step, what the flows changed).
- `forms.py`: three families fitted to a stock's one-step change after the flows that stay:
  - `linear`: c + sum k z over the own level, the inputs and the other stocks, not floored. Kept only
    where the plain inflow/drain would be floored on the run's states, or the stock goes below 0.
    Written (`linear.py`) as an inflow and a drain both shifted by the same constant (one-way, so the
    found model behaves right under the floored simulator), or as one `two_way` flow when the stock
    itself goes below 0 (a signed stock).
  - `min`: a drain `min(a x X, c + sum b Z)` (Z: one or two other stocks or inputs) beside a constant
    inflow; both branches must be active on at least 5% of the steps. Written as an `expr` flow.
  - `table`: `m x T(z)` beside a linear part, T piecewise linear with heights >= 0 (free, rising or
    falling; 4, 6 or 8 knots, the knots refined by least squares), z any stock or input, m 1 or an
    input. Written as a table effect.
- `judge.py`: per stock, the base's outside flows and the moves into the stock are replaced by a form
  when it wins by BIC (margin 10; every base inflow piece counted; rows weighted by 1 / sqrt(gross
  flow), the counting noise), leaves at most 1.05x the base's residual, and on near-exact data (mean
  weighted square below 0.05) at most 5% of it. A table or MIN must also beat a straight line refitted
  in the same readers by the same rules. A form is also tried with the base's inflow pieces kept. A
  replaced move into x becomes a drain of its source, unless the source's own change fits better with
  the form's reading of the source as a move. Stocks joined to a base's hidden stage are left alone.

## Results

`sdlab-ladder run --strategies engine_forms --jobs 2` at 89f2097 (2026-10-19 18:38 PDT), passes of 4
(before: kalman_lna, its base, as stored): 220 4 (0), 221 4 (0), 222 3 (0; counts-short data-limited,
analyse p 0.57), 224 3 (0), 217 3 (0), 225 0 (0), 130 0 (0), 131 0 (0; none-* equivalent).
Hard cases: 210 1 of 4 (0; 4 of 4 at 5ba03f7, before the base's measurement-error reading was
skipped: kalman_lna reads 210's chatter as measurement error), 212 none-* 2/6 parts (0/6),
sd-webshop-stock 3/10 and 4/10 parts (0 and 2), 113, 114, phys-thermostat, sd-learning-curve as the
base (114's skill@20 drops to -100%: the MIN is an `expr`, which simulate.py evaluates as 0). Elsewhere
(cells re-run at 85e1e46+): 123 none-* and 196 none-long fail -> pass, 136 and 137 fail -> equivalent;
no pass lost among the 148 re-run cells but part-capacity-gate, which errors in the particle scorer
(KeyError 'gate', not this strategy). The watcher's other engine_forms rows ran an earlier
uncommitted version (17:00) and are stale.

## Scoring blockers found

- **225 and every switch truth (sim.py):** the scorer reads the switch from its recorded level at the
  step's start index, but the engine sets the switch from that state at the start of the next sub-step;
  the scorer's truth amount is one step late. kalman_lna's exact 8/0 pieces match the engine's own
  `heating` counter to 6e-6 yet score 42.7% off. Also, a found model cannot write a switch with memory.
- **113 (substep.py):** the per-step refit turns the truth's two-way rates into `0.48 x speed` and
  `-0.0 x position`; the truth given as found fails (speed's error 1.8e9).
- **114 (dt 1/32):** an `expr` (MIN) truth flow is compared at its instantaneous rate, the linear ones
  at their per-step equivalents; the truth as found fails noise-free on the hiring table (5.8-7.1%).
- **Behaviour:** `sdlab/discovery/simulate.py` (pinned) evaluates an `expr` rate as 0 and floors
  two-way rates and every level at 0, so a found MIN (222) scores skill@20 about -700% and a found
  two-way flow on a signed stock (220) about 33% though its equations pass.
- **A found `expr` flow needs an `id`** or the scorer raises (sdtruth `_Program.flow`).
- **130:** the restock `(550 - S) / 5` is scored as the gap's parts; an inflow 110 plus a drain 0.2 S
  (identical on data where S stays below 550) fails.

## Verdict

Pending the full ladder run; keep as a specialist for sign-changing rates, MIN drains and tables of
another stock or of the own level times an input.
