# 307 (k8s-cpu-usage): kalman_lna

Status (2026-10-21, 13:15 PDT): **passes all four plan variants at 1b31e14; I made no new fix.**

Where the results come from: `uv run sdlab-ladder show 307-k8s-cpu-usage --strategy kalman_lna --variant V`,
code 1b31e14d26, run 2026-10-21T19:58Z (fresh, not stale):

| variant      | status | parts | discovery |
|--------------|--------|-------|-----------|
| none-short   | PASS   | 10/10 | 33.2 s    |
| none-long    | PASS   | 10/10 | 122.2 s   |
| counts-short | PASS   | 10/10 | 4.2 s     |
| counts-long  | PASS   | 10/10 | 36.8 s    |

No failures, so there was nothing to diagnose (rule 4b) and nothing to submit. These variants were not
re-run on the pool for this note. The fixes that make the strategy pass came in earlier, from k8s-307 C1,
inside kalman_lna's own package (`sdlab/discovery/strategies/kalman_lna/oefit.py`, wired in `__init__.py`):

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| oe-row-revise | Output-error refit of a stock's row after discovery. Links into declared outside inflows are allowed, moves only between stocks in the same unit, MIN, piece and effect expressions are simulated, and a Kalman score picks among the searched structures | 08d0733 | Copy `oefit.py` into the package and call it after the strategy's own structure search (39 roster strategies already have a copy) |
| sens-fit | The refit uses the run's derivatives (`_sens`: 9 runs for 33 numbers), with a budget of 4e8 so it finishes before the wall-clock limit. The Kalman choice is among 4 structures, and flows that are dead after the Kalman numbers are dropped | 1b31e14 | Copy the updated `oefit.py` (the same 144-line change went into each copy) |

The strategy lock for kalman_lna was still held by k8s-307-C1 (59 min old) when this note was written.
I edited nothing in the package, so I did not need the lock.
