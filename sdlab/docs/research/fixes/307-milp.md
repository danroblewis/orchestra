# 307 (k8s-cpu-usage): milp

Status (2026-10-21, 13:15 PDT): **passes all four plan variants at 1b31e14; I made no new fix.**

Where the results come from: `uv run sdlab-ladder show 307-k8s-cpu-usage --strategy milp --variant V`,
code 1b31e14d26, run 2026-10-21T19:57-20:00Z (fresh, not stale; job 244 `top5-refresh-307` reused them):

| variant      | status | parts | discovery |
|--------------|--------|-------|-----------|
| none-short   | PASS   | 10/10 | 20.8 s    |
| none-long    | PASS   | 10/10 | 40.5 s    |
| counts-short | PASS   | 10/10 | 67.1 s    |
| counts-long  | PASS   | 10/10 | 169.4 s   |

No failures, so there was nothing to diagnose (rule 4b) and nothing to submit. These variants were not
re-run on the pool for this note. The fixes that make milp pass came in earlier, from k8s-307 C1, inside
milp's own package (`sdlab/discovery/strategies/milp/oefit.py`, wired at the end of `milp/__init__.py`:
`identify` runs the MILP program, then `oefit.refit` on its answer):

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| oe-row-revise | Output-error refit of a stock's row after the strategy's own search. Links into declared outside inflows are allowed, moves only between stocks in the same unit, MIN, piece and effect expressions are simulated, and a Kalman score picks among the searched structures | 08d0733 | Copy `oefit.py` into the package and wrap `identify` as milp does (`_identify_program = identify`; new `identify` returns `oefit.refit(_identify_program(...), stocks, run, opts)`) |
| sens-fit | The refit uses the run's derivatives (`_sens`: 9 runs for 33 numbers), with a budget of 4e8 so it finishes before the wall-clock limit. The Kalman choice is among 4 structures, and flows that are dead after the Kalman numbers are dropped | 1b31e14 | Copy the updated `oefit.py` (the same 144-line change went into each copy) |

The strategy lock for milp was still held by k8s-307-C1 (59 min old, all roster strategies) when this note
was written. I edited nothing in the package, so I did not take the lock.
