# Kubernetes rung 4 (case 303): sindy's two fails, and what sindy can represent

**Status:** done (2026-10-20; code 3bdf982, 4bf3e9b). 303 counts-short and meas-short **fail -> pass**;
300-303 now 20 of 20 pass. Earlier: [k8s-303-c1.md](k8s-303-c1.md), [k8s-303-c2.md](k8s-303-c2.md),
[pysindy.md](pysindy.md) (what the strategy is).

## Diagnosis (rule 4b)

`sdlab-ladder analyse 303-k8s-daily-traffic` rates every variant achievable (p 1.00), and sindy's own
levels-only candidate recovers counts-short (0.6004 / 0.5018 / 1.0017; scratchpad `sindy303/d2.py`), so
both fails are the method's.

**One cause, chance pieces.** `sparse.fit_row` (pinned) priced an outside inflow's change by its value
alone while PELT picked the places, so pieces paid on pure noise:

- counts-short: the counter's row `responses_total` took 5 pieces of an outflow (-16, -42, -84, -38, -17
  per step; an outflow from a final counter). At slope 0.5 the residual is Poisson (sd 19.9 against
  sqrt(0.5 x inflight) 19.8, correlation with inflight 0.05), yet the 5 pieces lowered the BIC by 21
  (1794 -> 1773) because 4 places came free; priced at a value and a place each, they lose by 1.8. The
  pieces let the slope rise to 0.540, and the joint conservation fit carried the 8% to every number
  (0.646, 1.078). The products candidate kept them and the judge chose it (0.17406 against 0.17489).
- meas-short: 9 pieces on inflight (a `77` outflow), and with them in place eiv.py's pruning guard
  rejected every stage (C2's "the 3 left"), so the traffic link into inflight and the pieces stayed.

## The change (3bdf982; 4bf3e9b)

`fit_row` copied into sindy.py from `sparse.py` (pinned, at b9fe1d6) with one addition, `_earned`: when
the row chose pieces, they are dropped for no inflow or a constant one (the levels chosen beside the
pieces kept) if that leaves white residuals (Ljung-Box to lag sqrt(T), level 0.01, copied from
earned_pieces' rows.white) and a lower BIC with every change priced as a value and a place. That is
earned_pieces' rule (rows.reselect, "beside"), a change inside the row's own fit, not a choice between
finished models. Pricing the places outright instead (prototype) broke the mechanism test on a real
stepping inflow (`test_a_flow_sped_up...`: products stood in for 14 real changes, as pysindy.md warns);
the whiteness condition keeps those pieces (residuals without them are not white). 4bf3e9b: a row that
may read no column gets none (sparse.select failed on an empty library; 001-inflow-only errored in all 4
variants).

With the pieces gone, eiv.py's pruning acts on meas-short: it drops `queue -> outside` and the traffic
link into inflight and moves the drain into the counter (0.466 / 0.389 / 0.781 against 0.6 / 0.5 / 1;
all 22% low, the instrumented fit's short-series loss C2 describes, inside the tolerances).

## Numbers

- 300-303: `uv run sdlab-ladder run --strategies sindy --cases 300,301,302,303,001 --jobs 4 --timeout 600`
  (single-threaded, 4bf3e9b; stored as 8d397f3, which has the same sindy.py): 24 of 24 pass. Against each
  cell's previous row: 303 counts-short fail -> pass, 303 meas-short fail -> pass, 001 4 x error -> pass,
  the other 18 pass -> pass.
- Paired, in process (the same code with `sparse.fit_row` off / sindy's copy on; scratchpad
  `sindy303/rp2.py`, `pick.json` seed 303): 40 random cells sindy ran before (25 passing, 15 not;
  kubernetes and node2 cases left out): 20 pass -> pass, 5 equivalent -> equivalent, 10 fail -> fail,
  **4 fail -> pass** (006 counts-short, 042#2 counts-short, 049#2 counts-long, 050#2 counts-short), **1 fail -> equivalent** (055#6 counts-long), none worse. 38 cells of piece-heavy
  cases (020, 021, 022, 023, 027, 062, 086 all 14 variants, 154): 10 pass, 1 equivalent and 26 fail
  unchanged, **1 fail -> pass** (020 counts-short), none worse.
- The same cells as ladder rows (8d397f3, `sindy303/runs.sh`), plus the watcher's 69 re-runs at 711d936
  (3bdf982's sindy): every flip is fail -> pass or error -> pass (19 more on counts-long cells of 002,
  028, 039, 040, 050, 056, 061; three checked in process off/on: all fail -> pass); no pass lost.

## What sindy can and cannot represent

Each stock's change per step is a sparse sum of library terms: measured levels, products of two levels
(read as linear or two-point table effects), measured inputs (sign: inflow or outflow), and an outside
inflow in constant pieces; conservation ties a source's number to its receivers' (ConstrainedSR3); a
loss into another unit's stock is read as a co-flow; announced eras give numbers per configuration.
Measurement error is handled only by the eiv.py copy refitting its answer.

It cannot represent hidden stocks or delays (no latent state: `sdlab-ladder status --strategies sindy`,
hidden 0 of 86, delay 0 of 82), MIN/MAX and controllers (control 0 of 84, floor 22 of 48, threshold and
switch 0 of 4), table effects beyond two points (effect-table 0 of 44), two-way or sign-changing flows
(two-way 0 of 18, signed 0 of 6), integral / offset forms (0 of 36). Over its stored rows it is the lowest
of the 44 active strategies (35.7% pass or equivalent; combined2 74.9%; scratchpad `sindy303/cap.py`),
and no cell is passed by sindy alone. The board mixes versions: these commits made every sindy row
stale and the watcher is re-running them.

**Verdict.** The 303 fails were fixable and are fixed. The limits above are hard (a regression on
measured levels has no latent state, delay or saturation), every cell sindy passes another active
strategy passes too. Its one distinct piece, the joint conservation fit (conserve_joint.py), is used by
no other strategy; it is a shared-library module, so retiring sindy loses no code. Retirement is
recommended, as pysindy.md concluded at its first bench.
