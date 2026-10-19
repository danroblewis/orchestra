# realistic_flows: realistic_hats with co-flows and the rows' own drains

**Status:** in progress (round 2 on the realistic examples; triage in realistic-triage.md, round 1 in
realistic-hats.md).

## What it does

`sdlab/discovery/strategies/realistic_flows/` is self-contained (CLAUDE.md invariant 11):
- realistic_hats at 06b0062, every module (transit/ included);
- coflow_hats' coflows.py, cycles.py, joint.py, price.py, search.py and translate.py at 9d891b0, and
  its co-flow stage (`_inflow_coflows`), run inside the anytime cap (each accepted co-flow becomes the
  answer so far). joint.py keeps effect_hats' 1e-12 bar for a column with no weight (coflow_hats'
  1e-24 made 131 none-short pick a wrong effect; 128 and 129 do not need it).

Changes of its own:
- **Own drains** (mechanism B). The matrix is run a second time (when the time left allows) with
  every variant's rows' numbers kept: `slack` 0 (a changing row's drain is no longer set to what
  same-unit receivers take whenever the two are within 30%) and `tol` 1e-6 (the reader no longer
  drops a number below 0.003, whatever the level it multiplies). The judge picks across both runs.
  Distilled 154: the births (0.022 B) were read as a move out of B and B's drain set to it; the
  0.002 B left over (~200 a step) went into B's inflow (582 against 800). Distilled 153: the link
  0.001 x O (O ~ 20,000) and O's drain 0.0005 were dropped as below 0.003.
- **Transit with and without the co-flows.** A co-flow can stand in for a hidden stage's exit (161
  counts-long: two drains read as co-flows, and the transit pair is then skipped). Transit is tried
  on the answer and on the answer before the co-flow stage, and the one the judge prefers is kept.

## Results

Pending.
