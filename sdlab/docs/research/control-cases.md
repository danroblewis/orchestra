# Control-theory cases (200-215, tag `control`)

**Status:** done (queue item 1a, requested by the user on 2026-10-19): 16 cases, the control
metrics, the leaders' run, the closed-loop identification family and three distilled cases.
Verdict: the control cases are hard for every leader (at most 3 passes in 34 achievable cells).
Commits: see "Commits" at the end.
**Cases:** `sdlab/ladder/cases/200-*.yaml` to `215-*.yaml` (and `cases/data/prbs7-hold8.csv`).
**Metrics:** `sdlab/ladder/control.py` (harness, scorer side): `uv run python -m sdlab.ladder.control
[--truth] [--strategies ...] [--cases ...] [--json]`. Tests: `tests/test_ladder_control.py`.

## What control theory is, in one paragraph

A **controller** measures something (a room's temperature, a car's speed, a queue's length), compares
it with the value it is told to hold (the **setpoint**), and acts on the difference (the **error**)
through an **actuator** (a heater, the throttle, an admission gate). The thing it acts on is the
**plant**. Because what the controller does changes what it measures next, the controller and the
plant form a **feedback loop**: the balancing loop of system dynamics, built on purpose. Control
theory is about designing that loop so it is fast, does not overshoot or oscillate, and ends up
where it was told to go despite **disturbances** (a hill, a cold night, a rush of requests).

In SD Lab's format a controller is just flows:

- **P control** (push in proportion to the error) is a gap flow, `k x setpoint - k x level`.
- **I control** (push in proportion to the running sum of the error) needs that sum: it is a
  stock, the **integral** `I`, gaining the setpoint and losing the level each step. The integral
  is signed, so it is kept positive by an offset (it starts at 1,000-50,000 and the controller reads
  `k x (I - offset)`, i.e. a constant `-k x offset` plus `k x I`), as the physics cases kept
  position and velocity positive. Its flows are information, not material: `exact: true` (no
  counting noise). The controller's integral is measured (a controller logs it).
- **D control** (react to how fast the level changes) needs the level's rate of change, which in
  SD is the stock's net flow, a linear function of the stocks that feed it: D action reads them.
- **Saturation** (an actuator's limits) is the floor at 0 (a heater cannot cool, an engine cannot
  brake), or a table effect when the whole controller is a curve (on/off, a proportional band,
  admission control).
- **Dead time** is a DELAY3 chain of hidden stocks between the controller and the plant.
- Setpoints and disturbances are **measured inputs**, given to discovery as data.

## Sources

- **Åström & Murray, *Feedback Systems: An Introduction for Scientists and Engineers*** (Princeton
  University Press; free online at fbswiki.org; first edition v2.10, 2009, used here for section
  and example numbers, the second edition of 2021 renumbers the chapters): sec. 1.5 *Simple forms
  of feedback* (on/off, proportional with a proportional band, eq. 1.2, integral and PID), sec. 3.1
  *Cruise control*, Example 2.10 *Queuing systems* (Agnew's flow model dx/dt = lambda - mu_max x /
  (x + 1)) with Exercise 2.8 *Admission control for a queue* (u = sat(0,1)(k (r - x))), sec. 3.4
  *Computing systems and networks* (web server control), sec. 9.3 *Stability margins* (and the
  phase lag of a time delay), ch. 10 *PID control* (Example 10.3 *Cruise control using PI
  feedback*: a = 0.0101, b = 1.3203, g = 9.8; sec. 10.4 *Integrator windup*, Example 10.5 the car
  winding up on a 6 degree hill), sec. 11.2 *Feedforward design*.
- **Ogata, *Modern Control Engineering*** (Pearson): liquid-level systems, transient response
  (overshoot, settling time) and steady-state errors in unity-feedback systems, PID controllers.
- **Nise, *Control Systems Engineering*** (Wiley): steady-state errors and system type (a plant
  that integrates, like a tank with no drain, has no steady-state error to a step under P control).
- **Franklin, Powell & Emami-Naeini, *Feedback Control of Dynamic Systems*** (Pearson): the
  frequency response of a time delay (its phase lag grows with frequency, so it eats phase margin).
- **Seborg, Edgar & Mellichamp, *Process Dynamics and Control*** (Wiley) and **Åström & Hägglund,
  *PID Controllers*** (ISA): cascade control.
- **Ljung, *System Identification: Theory for the User*** (Prentice Hall) and **Söderström &
  Stoica, *System Identification*** (Prentice Hall, free online): closed-loop identification and
  input design (PRBS).

The numbers are SD Lab's own (per step, Euler at dt = 1, levels in hundreds so counting noise is
moderate), chosen to show each textbook behaviour; only the car's a, b and g are the book's.

## The cases, one plain explanation each

| case | control idea | what it looks like in SD Lab |
|---|---|---|
| 200-control-p-room-heater | **P control leaves a steady-state error.** The heater pushes 0.3 x (setpoint - T); the room loses 0.05 x (T - outdoor). Some error is needed to keep the heater on, so T settles 14% of a setpoint step short. | heater `0.3 setpoint - 0.3 T` (floored: it cannot cool), outdoor warming `0.05 outdoor`, drain `0.05 T` |
| 201-control-pi-room-heater | **PI removes the error.** 200 plus the error's running sum I; while any error remains, I grows and pushes harder, so T ends exactly at the setpoint (after a 2.6% overshoot). | I gains the setpoint and loses T; heater `-20 + 0.3 setpoint - 0.3 T + 0.02 I` |
| 202-control-pid-two-tanks | **PID on a second-order plant: overshoot and settling.** A pump fills H1, which drains into H2; the controller holds H2. D action (on the measurement) reads H1, because H2's rate of change is 0.1 H1 - 0.1 H2. 19% overshoot, settles in 30 steps. | pump `-40 + 0.4 setpoint - 0.32 H2 - 0.08 H1 + 0.02 I` |
| 203-control-cruise-on-hills | **PI rejects a disturbance.** Åström & Murray's car (drag 0.0101 V, gravity 9.8 x slope): on each hill the speed sags, then the integral opens the throttle until the speed is back at the setpoint. The driver changes the setpoint only at steps 700 and 1300. | engine `-778 + 0.39 setpoint - 0.39 V + 0.04 I`; hill `V -> outside: 9.8 slope` (an input) |
| 204-control-p-tank-level | **An integrating plant needs no integral for a setpoint step, but does for a load.** A tank with no drain of its own and a measured demand drawn out: P control reaches every setpoint step exactly, but a change in demand leaves an offset (demand - 10) / 0.25. | valve `10 + 0.25 setpoint - 0.25 H`; demand `H -> outside: demand` |
| 205-control-dead-time-low-gain | **Dead time, low gain: stable but sloppy.** The heater's output arrives through a DELAY3 of 6 steps; at gain 0.11 the loop overshoots 19% and keeps a 31% steady-state error (gain margin 3.1). | `delay3(0.11 setpoint - 0.11 T, 6)`, drain `0.05 T` |
| 206-control-dead-time-high-gain | **Dead time, high gain: ringing near instability.** The same loop at gain 0.27 (gain margin 1.26, phase margin 18 degrees): each setpoint step rings for ~170 steps (overshoot 77%, damping 0.09). A little more gain and it would oscillate for ever. | `delay3(0.27 setpoint - 0.27 T, 6)` |
| 207-control-cascade-two-tanks | **Cascade.** An outer PI loop on the lower tank H2 sets the level an inner P loop holds in the upper tank H1; a measured side stream into H1 is corrected by the inner loop before it reaches H2. | pump `-130 + 0.6 setpoint - 0.6 H2 + 0.03 I - 0.5 H1` (the two loops multiplied out) |
| 208-control-feedforward-tank | **Feedforward plus feedback.** 204's tank; the valve answers the measured demand directly (0.8 x demand, a model cancelling 80% of it) and the level (0.25 x (300 - H)). The level only sees the 20% the model misses. | valve `75 - 0.25 H + 0.8 demand`; outflow `demand` |
| 209-control-cruise-windup-downhill | **Integrator windup.** 203's car on long descents: the engine cannot brake (its thrust is floored at 0), the car runs fast, and the integral keeps summing the negative error. At the foot of the hill the wound-down integral keeps the engine off, so the speed sags to 13-15 m/s against 20 before recovering (Example 10.5, at the lower limit). | 203's controller with an offset of 50,000; gravity `outside -> V: 9.8 downhill` |
| 210-control-on-off-heater | **On/off (bang-bang).** Full heat (12) below the setpoint, none above: T never settles but chatters in a band (swing ~10 around 197) while the duty cycle follows the weather. | heater `12 x table(T)`: 1 up to 199, 0 from 201 |
| 211-control-proportional-band-heater | **A proportional band.** The same heater, full below 180, off above 220, a straight line between: T settles inside the band, without chattering, at a level that drifts with the weather (the error is the price of not overreacting). | heater `12 x table(T)`: 1 to 180, 0 from 220 |
| 212-control-admission-queue | **Admission control of a request queue** (the SRE's load shedder). Requests arrive at a measured rate (6 a step, rushes of 13), throughput saturates at 10 a step (10 Q / (Q + 1)); the gate admits everything below Q = 30, nothing above 40, a straight line between. In a rush the queue is held near 35 instead of growing for ever; rejected requests are counted. | `arrivals x falling table(Q)` into Q, `arrivals x rising table(Q)` into Rejected, `10 x table(Q)` Q -> Served |
| 213-control-closed-loop-id-steady | **Closed-loop identification, weak excitation.** A PI loop (plant Y drained at 0.05) whose setpoint never moves: only noise excites it, and nothing in the data says how it answers the setpoint. | control `-20 + 0.2 setpoint - 0.2 Y + 0.01 I`, setpoint fixed at 200 |
| 214-control-closed-loop-id-steps | **The same loop with setpoint steps** (200/260 every 100 steps): external excitation. | setpoint `200 + pulse_train(60, 50.5, 100, 200)` |
| 215-control-closed-loop-id-prbs | **The same loop with a PRBS setpoint**: a 7-bit maximal-length sequence (x^7 + x^6 + 1), each bit held 8 steps, 200/260, repeating every 1,016 steps. | `cases/data/prbs7-hold8.csv` |

Two older cases also carry the tag: 123-inflow-shut-by-own-level and phys-thermostat (the physics
on/off thermostat with hysteresis). The new cases are 200-215; the tables below cover only those.

### The true models' control metrics

`uv run python -m sdlab.ladder.control --truth --cases 200,...,215` (step up by `size` from the
operating point: the setpoint at its lowest level on the run, every other input at its mean; for
208, 210-212 a step in the disturbance). Steady-state error is the share of a setpoint step not
reached (for a disturbance step: the level's final shift per unit of disturbance); gm and pm are the
margins of the equivalent unity-feedback loop L = T / (1 - T) (control.py); rho the spectral radius
per step and zeta the damping of the slowest oscillating mode.

| case | overshoot | settling (steps) | steady-state error | gain margin | phase margin | rho | zeta |
|---|---|---|---|---|---|---|---|
| 200 P heater | 0% | 10 | 0.143 | 6.5 | 91 | 0.650 | 1 |
| 201 PI heater | 2.6% | 22 | 0 | 6.7 | 78 | 0.928 | 1 |
| 202 PID two tanks | 19.2% | 30 | 0 | 5.8 | 50 | 0.947 | 0.51 |
| 203 cruise (PI) | 15.2% | 25 | 0 | 5.4 | 65 | 0.804 | 1 |
| 204 P tank (integrating) | 0% | 14 | 0 | 8.0 | 83 | 0.750 | 1 |
| 205 dead time, low gain | 18.9% | 43 | 0.313 | 3.1 | 82 | 0.906 | 0.47 |
| 206 dead time, high gain | 76.8% | 174 | 0.156 | 1.26 | 18 | 0.978 | 0.09 |
| 207 cascade | 0% | 84 | 0 | 10.2 | 93 | 0.965 | 1 |
| 208 feedforward (demand +2) | 0% | 14 | -0.8 per unit | - | - | 0.750 | 1 |
| 209 cruise windup (linear part) | 15.2% | 25 | 0 | 5.4 | 65 | 0.804 | 1 |
| 210 on/off (outdoor +20) | limit cycle: swing 10.1 around 197 | | mean shift 0.010 per unit | - | - | - | - |
| 211 proportional band (outdoor +20) | 0% | 10 | 0.143 per unit | - | - | 0.650 | 1 |
| 212 admission queue (arrivals 11 -> 13) | 31% | 4 | 0.67 per unit | - | - | 1.000 (the final counters) | 1 |

(Each true model gives the same numbers on every variant; the counts variants' operating point differs only through the inputs' means.)
| 213-215 PI loop | 0% | 18 | 0 | 10.0 | 84 | 0.950 | 1 |

## Results: the leaders on the control cases

**Run** (19 October 2026): `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
NUMBA_NUM_THREADS=1 uv run sdlab-ladder run --strategies
combined,kalman_lna,structures,archetypes,odefit,effect_hats,matrix --cases 200,...,215 --jobs 2
--timeout 300`: 448 cells in 2,589 s, **14 pass, 91 equivalent, 343 fail, no errors or timeouts**.
Strategy code at cd9e8b1 (combined's row says `+dirty`: another agent's uncommitted edit to
`combined/__init__.py` was in the checkout when it ran, so combined's numbers are for that patch
3a98acdd2dfc60d4). The analysis labels are from `sdlab-ladder analyse --all --cases 200,...,215`:
34 cells achievable, 6 data-limited, 20 unidentifiable, 4 not analysed (the DELAY3 cases' counts
variants: the hidden-stock oracle covers one hidden stock). Numbers from the store
(`store.latest()`), by the scripts in this section's commands.

Per strategy over the 64 cells (16 cases x 4 variants):

| strategy | pass | equivalent | fail | pass on the 34 achievable cells | mean discovery s |
|---|---|---|---|---|---|
| structures | 7 | 13 | 44 | 3 | 21.9 |
| combined | 5 | 13 | 46 | 1 | 20.6 |
| archetypes | 1 | 13 | 50 | 1 | 9.8 |
| effect_hats | 1 | 15 | 48 | 1 | 1.0 |
| kalman_lna | 0 | 12 | 52 | 0 | 11.2 |
| odefit | 0 | 13 | 51 | 0 | 14.7 |
| matrix | 0 | 12 | 52 | 0 | 0.2 |

Per case: the analysis label of each variant (none-short, none-long, counts-short, counts-long: a
achievable, d data-limited, u unidentifiable, - not analysed), then each strategy's status (P pass,
e equivalent, F fail) in the same order.

| case | analysis | combined | kalman_lna | structures | archetypes | odefit | effect_hats | matrix |
|---|---|---|---|---|---|---|---|---|
| 200-control-p-room-heater | aaaa | FFeF | FFeF | FFeF | FFeF | FFeF | FFeF | FFeF |
| 201-control-pi-room-heater | aada | FFFe | FFFe | FFFe | FFFe | FFFe | FFFe | FFFe |
| 202-control-pid-two-tanks | aaaa | eeFF | eeFF | eeFF | eeFF | eeFF | eeFF | eeFF |
| 203-control-cruise-on-hills | uaua | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 204-control-p-tank-level | aaaa | FFFF | FFFF | PPFP | FFFF | FeeF | FFeF | FFeF |
| 205-control-dead-time-low-gain | uu-- | PPFF | FFFF | PPFF | FFFF | FFFF | FFFF | FFFF |
| 206-control-dead-time-high-gain | uu-- | PPFF | FFFF | PPFF | FFFF | FFFF | FFFF | FFFF |
| 207-control-cascade-two-tanks | aada | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 208-control-feedforward-tank | uuaa | eeeF | eeeF | eeeF | eeeF | eeFF | eeee | eeFF |
| 209-control-cruise-windup-downhill | uaua | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 210-control-on-off-heater | aaaa | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 211-control-proportional-band-heater | aadd | PFFe | FFFF | FFFe | PFFe | FFFF | PFFe | FFFF |
| 212-control-admission-queue | dduu | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 213-control-closed-loop-id-steady | uuuu | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 214-control-closed-loop-id-steps | uuaa | eeFF | eeFF | eeFF | eeFF | eeFF | eeFF | eeFF |
| 215-control-closed-loop-id-prbs | uuaa | eeFe | eeFe | eeFe | eeFe | eeFe | eeFe | eeFe |

The control cases are hard for every leader: 1-3 passes in 34 achievable cells. Of the 14 passes,
8 are 205/206's noise-free cells, which are unidentifiable (the hidden delay's mirror) and pass by
a prior, and 3 are 211 none-short (a proportional band that T never leaves on the short run, so a
straight controller is the truth there).

### What goes wrong (diagnosis, invariant 4b)

- **The controller's own-level term is written into the plant's drain** (200, 201, 203, 204, 207,
  209, 213-215). A controller k x (setpoint - T) has a term -k x T in an inflow; beside the plant's
  drain d x T, only their sum shows in the mean (the "inflow + drain = one gap inflow" equivalence),
  so every leader writes a drain of k + d. Only a floor that binds (the heater cannot cool) or the
  counting noise's variance separates them. Where neither does (noise-free, floor never binding:
  202, 208, 214, 215 none) the cells are unidentifiable and the leaders are equivalent, as they
  should be.
- **A floor that binds on only a few steps pulls the whole fit** (200, 203, 204, 209; distilled
  as 218). The heater or throttle is floored at 0 on 10-25 steps of 2,000, after a setpoint drop or
  at the end of a hill. These steps make the split identifiable (the analysis says achievable), but a
  one-step least-squares fit across them is biased everywhere: on 203 noise-free every number comes
  out at about two thirds of its value (setpoint 0.26 for 0.39, I 0.027 for 0.04, slope 6.8 for
  9.8; plain least squares on the data gives the same), and the main line adds inflow pieces for the
  floored steps. structures recovers 125 and 218 (a floored gap alone) but not 200 (the same with a
  second, input-driven inflow, the outdoor warming).
- **The integral's exact inflow is cut into pieces** (214, 202, 207 counts; distilled as 216).
  The PI controller's integral I gains the setpoint and loses the level, with exact (noise-free)
  flows. On the counts variants every leader writes I's inflow as a constant or unannounced pieces
  (230 = the setpoint's mean) instead of 1 x setpoint, or scales both of I's flows (on 216, combined: 0.63
  for 1). The same loop with I's flows counted finds the input: the trigger is one exact stock among
  counted ones.
- **The cascade's and PID's pump reads the downstream tank** (202, 207): a negative term in H1's
  inflow on H2 is written as an outflow of H1 reading H2 (the "negative inflow term = outflow"
  equivalence), and in 207 the side stream (a measured input into H1) and most of the I term are
  lost. Tested as a two-tank candidate (pump 20 + 0.4 setpoint - 0.4 B): equivalent for matrix and
  combined, a pass for structures with counts, so no new mechanism; 207's failure is the floor
  (49 floored steps of 2,000) plus the equivalence.
- **Gates and switches as table effects of the stock they fill** (210, 212; 212 distilled as 217).
  On/off control (210) is 123's mechanism (a steep table of its own level), which no leader passes.
  Admission control (212) multiplies a measured input by a falling table of its own stock: every
  leader writes k x arrivals plus a constant and a faster drain, or moves from Q to Rejected.
- **An input read by an inflow and an outflow of the same stock** (208, feedforward): only the net
  (-0.2 x demand) shows without noise (unidentifiable: every leader is equivalent there); with
  counts the noise of each flow separates them (achievable, p 0.81 and 0.96), but no leader uses it
  (only effect_hats stays equivalent on counts-long). 009 (births and deaths) is the same split on a
  stock's own level, which combined, kalman_lna, structures and archetypes pass with counts. 208 is
  already the smallest case of this (two flows), so it stands as its own probe.
- **Dead time** (205, 206): the DELAY3 in the loop is found on noise-free runs by combined and
  structures (exact numbers), and lost with counts (structures: one hidden stage with delay 6.8 and
  numbers 13-22% off). The ladder's delay cases (063, 105, 134) fail the same way for most leaders:
  not a new mechanism.

### Control metrics of the found models

`uv run python -m sdlab.ladder.control --strategies combined,kalman_lna,structures,archetypes,odefit,effect_hats,matrix
--cases 200,...,215 --json` at 34e948c, on the stored results above. Each cell: overshoot /
steady-state error / gain margin ("no answer": the found model's level barely moves after a
setpoint step, i.e. it does not read the setpoint; "cycle": a limit cycle).

Noise-free long runs:

| case | true | combined | kalman_lna | structures | archetypes | odefit | effect_hats | matrix |
|---|---|---|---|---|---|---|---|---|
| 200 | 0% / 0.14 / 6.5 | 0% / 0.53 / 11.1 | 0% / 0.40 / 9.0 | 0% / 0.53 / 11.1 | 0% / 0.53 / 11.1 | 0% / 0.40 / 9.0 | 0% / 0.57 / 12.0 | 0% / 0.40 / 9.0 |
| 201 | 3% / 0 / 6.7 | 3% / 0 / 7.2 | 3% / 0 / 7.2 | 3% / 0 / 7.2 | 3% / 0 / 7.2 | 3% / 0 / 7.1 | 3% / 0 / 7.2 | 3% / 0 / 7.2 |
| 202 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 | 19% / 0 / 5.8 |
| 203 | 15% / 0 / 5.4 | 20% / 0 / 8.1 | 20% / 0 / 8.1 | 20% / 0 / 8.1 | 20% / 0 / 8.1 | 17% / 0 / 8.4 | 20% / 0 / 8.0 | 20% / 0 / 8.0 |
| 204 | 0% / 0 / 8.0 | 0% / 0.25 / 10.4 | 0% / 0.25 / 10.4 | 0% / 0 / 8.0 | 0% / 0.25 / 10.4 | 0% / 0 / 8.1 | 0% / 0.25 / 10.4 | 0% / 0.25 / 10.4 |
| 205 | 19% / 0.31 / 3.1 | 19% / 0.31 / 3.1 | no answer | 19% / 0.31 / 3.1 | no answer | 0% / 0.28 / 23.4 | no answer | no answer |
| 206 | 77% / 0.16 / 1.3 | 77% / 0.16 / 1.3 | no answer | 77% / 0.16 / 1.3 | no answer | 0% / 0.15 / 15.0 | no answer | no answer |
| 207 | 0% / 0 / 10.2 | 8% / 0 / inf | no answer | 8% / 0 / inf | 8% / 0 / inf | 0% / 0 / 20.2 | 8% / 0 / inf | 0% / 0 / 20.2 |
| 209 | 15% / 0 / 5.4 | no answer | no answer | no answer | no answer | no answer | no answer | no answer |
| 213 | 0% / 0 / 10.0 | no answer | no answer | no answer | no answer | no answer | no answer | no answer |
| 214, 215 | 0% / 0 / 10.0 | 0% / 0 / 10.0 (every strategy) | | | | | | |

Counts, long runs:

| case | true | combined | kalman_lna | structures | archetypes | odefit | effect_hats | matrix |
|---|---|---|---|---|---|---|---|---|
| 200 | 0% / 0.14 / 6.5 | 0% / 0.14 / 7.3 (every strategy) | | | | | | |
| 202 | 19% / 0 / 5.8 | no answer | no answer | 22% / 0 / 5.4 | no answer | no answer | no answer | no answer |
| 203, 207, 209, 213, 214 | (as above) | no answer (every strategy) | | | | | | |
| 205 | 19% / 0.31 / 3.1 | 0% / 0.31 / 36.8 | 0% / 0.31 / 36.8 | 13% / 0.31 / 10.1 | 0% / 0.31 / 36.8 | 0% / 0.31 / 30.0 | 0% / 0.31 / 30.0 | 0% / 0.31 / 30.0 |
| 206 | 77% / 0.16 / 1.3 | 0% / 0.43 / 53.1 | 0% / 0.43 / 53.1 | 0% / 0.43 / 53.1 | 0% / 0.43 / 53.1 | no answer | no answer | no answer |
| 208 (demand +2) | 0% / -0.80 per unit | -1.00 | no answer | -1.00 | -1.00 | -0.97 | -1.02 | -0.97 |
| 212 (arrivals 11 -> 13) | 31% / 0.67 per unit | cycle | cycle | 1.41 | 1.41 | 2.23 | 2.29 | 2.23 |
| 215 | 0% / 0 / 10.0 | 0% / 0 / 10.0 (every strategy) | | | | | | |

What the metrics add to the equation scores:

- **Equivalent models have the true control behaviour**, to the digit (201, 202 and 214-215
  noise-free, 215 counts-long, 200 counts-long): the metrics are read off the model's behaviour, so
  a different split of the same mean gives the same loop. That checks control.py.
- **A wrong split is a wrong controller.** On 200 noise-free the found models predict a P-control
  steady-state error of 0.40-0.57 of a step against the true 0.14, and a gain margin of 9-12
  against 6.5: the pieces and the merged drain make the loop look weaker and safer than it is. On
  204 five leaders predict a 25% error for a tank under P control that has none.
- **Dead time is lost as a delay, not as a number.** Where the DELAY3 is missed (205, 206 with
  counts) the found loops have gain margins of 10-98 against 3.1 and 1.26, and no overshoot: a
  model without the delay cannot ring, so it calls a loop near instability (206: damping 0.09) safe.
- **Feedforward**: with counts the leaders put the whole demand on the outflow (-1.0 per unit),
  i.e. they lose the feedforward entirely and predict five times the true sensitivity to demand.
- **Admission control**: the found queues answer a rush with 1.4-2.3 more requests in the queue per
  unit of arrivals (the true gate holds it to 0.67), or chatter (combined, kalman_lna): without the
  gate the queue is not held.

## Closed-loop identification (213-215)

The same PI loop (plant Y drained at 0.05, controller 0.2 x (setpoint - Y) + 0.01 x (I - 2000))
under three setpoint designs, all measured inputs:

| | 213 steady | 214 steps | 215 PRBS |
|---|---|---|---|
| analysis (none-short, none-long, counts-short, counts-long) | u u u u | u u a (p 0.87) a (p 1.00) | u u a (p 0.92) a (p 1.00) |
| why not identifiable | the setpoint is constant: its column is the constant's (rank 3 of 4), so how Y answers the setpoint is not in the data, and without noise the start-up transient is the only movement | without noise the controller's -0.2 Y and the plant's 0.05 Y drain are one number (the split needs the counting noise) | the same |
| Cramér-Rao SE of the setpoint's coefficient (0.2), counts-long | not identified | 0.0088 | 0.0044 |
| leaders' statuses (7 strategies) | all fail | none: equivalent; counts: all fail | none: equivalent; counts-short: all fail; counts-long: all equivalent |
| found control metrics (counts-long) | no answer | no answer | true to the digit (gm 10.0, no error) |

Findings:

1. **The analysis already labels the weak-excitation cells** (no change to analysis.py was
   needed): every 213 cell is unidentifiable, with the reason "Y <- setpoint is collinear with the
   constant". With counting noise alone the loop's own numbers are still detectable (Y <- Y at
   z 6.7 short and 17.9 long, Y <- I at 3.7 and 8.1), so noise excites the loop, but not its answer
   to the setpoint. 203 and 209 show the same thing unplanned: their setpoint changes only at steps
   700 and 900-1300, so their short runs (300 steps) are unidentifiable too.
2. **In SD form the controller's feedback and the plant's drain never separate in the mean**,
   whatever the excitation: both are terms in the controlled stock's own level. Only counting noise
   (the variance of each flow) or a binding floor tells them apart. This is the SD face of the classic
   closed-loop problem (the controller's action is a function of the measured output, so plant and
   controller are confounded unless something outside the loop moves).
3. **A PRBS carries about four times the information of steps** on the setpoint's coefficient (SE
   0.0044 against 0.0088 on the long run, same amplitude), and it is the only design where the
   leaders reach the truth's behaviour with counts (215 counts-long equivalent for all seven, found
   gain margin 10.0 as the truth's). The reason they get there is partly the methods': 214's square
   wave has 20 switches in 2,000 steps, cheap enough to write as pieces, while the PRBS has ~125,
   where the input column pays (mechanism 216 below). On the short PRBS run (~19 switches) the leaders
   fail as on 214.

## Distilled cases (216-218, tag distilled)

Each from a control case's failure, the smallest case that makes the leaders make the same mistake
(confirmed: `sdlab-ladder run --strategies combined,kalman_lna,structures,archetypes,odefit,effect_hats,matrix
--cases 216,217,218 --jobs 2 --timeout 300`, single-threaded, at 34e948c: 84 cells, 2 pass, 23
equivalent, 59 fail, no errors or timeouts). Commit a319289.

| case | from | mechanism | analysis | combined | kalman_lna | structures | archetypes | odefit | effect_hats | matrix |
|---|---|---|---|---|---|---|---|---|---|---|
| 216-distilled-exact-integral-fed-by-stepping-input | 214 (202, 207) | an exact (noise-free) stock among counted ones, fed by a stepping input: its inflow is written as pieces or scaled | u u d a | FeFF | FeFF | eeFF | FeFF | eeFF | FeFF | FeFF |
| 217-distilled-input-gated-by-own-level | 212 | a measured input times a falling table of the stock it fills (an admission gate) | a a a a | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF | FFFF |
| 218-distilled-controller-floored-on-few-steps | 203, 209, 200 | a P controller floored at 0 on 1-10 steps of a run: least squares across the floor biases every number | a a a a | FFee | FFee | PPee | FFee | FFee | FFee | FFee |

Each reproduces the hard case's mistake in every leader that makes it there: on 216 counts-long
all seven fail (combined writes I's flows at 0.63 x setpoint and 0.63 x Y); 217 fails everywhere;
on 218 six leaders fail noise-free (matrix: drain 0.35, setpoint 0.25 for 0.3, a constant inflow in
33 pieces), and structures, which passes 218 (and 125), still fails 200: its floored-gap detector
does not survive a second inflow into the stock. With counts 218 is equivalent for all (the merged
drain), as 200 counts-short is.

Not distilled: the drain/controller merge (an equivalence, labelled by the analysis), 210's on/off
(123), dead time (063, 105, 134), and 208's feedforward split (already two flows).

## Commits

- cd9e8b1: cases 200-215, `cases/data/prbs7-hold8.csv`, `sdlab/ladder/control.py`, its tests.
- 34e948c: control.py, a model that barely answers a step gets no overshoot or margins.
- a319289: distilled cases 216-218.
- (this document, the LADDER.md section and the glossary: the docs commit after them.)
