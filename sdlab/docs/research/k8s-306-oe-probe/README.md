# 306 meas: an output-error probe (diagnosis only, not a strategy)

**Status:** diagnosis, 2026-10-21. No strategy changed. This is the evidence for why blockwise,
engine_forms, lna_levels, matrix, own_tables and starved_coflows fail 306 meas-short and
meas-long. They pass every none and counts cell of 306: store, latest rows at f640c89, scorer 05eeb3.

## Files

- `oe.py`: an output-error refit of a found model, using data only (page stocks, measured levels,
  inputs, injections, the declared boundary). It handles proportional, linear and `[g *] min(a X, b Y)`
  rates; any other form returns None. The simulation follows the engine:
  1. injections are added first;
  2. the flows then read the previous level and that step's input;
  3. outflows are floored at 0 and capped at what the stock holds.

  Every measured stock is simulated and scored. The noise sd is sqrt(a + b x^2), fitted from the
  lag-1 covariance of the changes. A declared input inflow keeps its gain at 1, because
  the scorer's "input altered" rule fails any other gain. A greedy BIC search runs over three kinds
  of move:
  - drop a flow;
  - add a move `x -> y` (or `x -> outside` where the boundary declares it);
  - re-source a flow that reads one stock so it comes from that stock.
- `truthbic.py VARIANTS`: the true structure refitted by `oe.py`. This is the reference: can the data deliver?
- `drive.py STRATEGY VARIANTS [search]`: a strategy's stored found model refitted, then searched.

All runs single-threaded: `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 uv run python docs/research/k8s-306-oe-probe/<script>`.

## Results (scored by `score.equations` at 3747e29, z = 3 measured SEs)

| run | status | parts | time |
|---|---|---|---|
| true structure, meas-short | **pass** | 7/7 | ~10 s |
| true structure, meas-long | **pass** | 7/7 | ~60 s |
| matrix's stored meas-long model, refit only | fail | 2/7 | 3 s |
| matrix's stored meas-long model, refit + search | **pass** | 7/7 | 1646 s |
| matrix's stored meas-short model (no MIN), refit + search | fail | 3/7 (BIC 15215 vs the truth's 2592) | 74 s |

**What the results show:**
- Under the measured SEs of 3747e29, the meas cells are within the data's reach. The round-2 data limit
  was the bare 10% tolerance, and 3747e29 lifted it.
- The six strategies fail meas because of their method. Each picks its structure by one-step
  (equation-error) regression on noisy levels, and the IV refit (eiv.py) changes only the numbers of
  that structure. The result is a traffic gain of 0.45/0.82, a MIN slope of 0.375 (true 0.6), retries
  -> queue near 2.0, and no errors_total flow.
- An output-error structure search fixes this on meas-long, starting from matrix's own wrong model. It
  is not a small fix, for three reasons:
  - It is 14x over the 120 s item timeout in pure Python.
  - On meas-short it needs a MIN move. The capacity screen in capmin.py does not fire there, and the
    probe search does not offer a MIN.
  - The retries drains sit on a ridge where only their shares are seen. The engine empties retries
    every step, so a sum above 1 must be written summing to 1 (`normalise_drains`).

  It is the broad S2 fix of k8s-306-s1.md ("Round 2"), needed by every survivor: on 306, 0 of 45
  meas-short and 0 of 51 meas-long cells pass.
