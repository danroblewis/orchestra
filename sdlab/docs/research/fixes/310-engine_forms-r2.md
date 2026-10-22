# 310 (k8s-memory-oom): engine_forms, round 2

**Status (2026-10-22, agent engine_forms-r2-310, engine_forms lock held and released): engine_forms passes 310 on
every achievable variant at the current `sdlab` HEAD. No code change was needed this round, and none was made.**
engine_forms's package is unchanged since round 1 (7e7bd2b, docs/research/fixes/310-engine_forms.md). Its stored
results were all marked stale (`uv run sdlab-ladder status --strategies engine_forms --detail`), so the four variants
were re-run once through the pool to confirm them on the current code.

Pool job 291 ran at commit f2491d4 on node2 (`uv run sdlab-ladder job 291 --json`):

| variant | achievable? | job 291 (f2491d4) | seconds | note |
|---|---|---|---|---|
| none-short | yes | **PASS 26/26** | 125 | the leak is matched as engine_forms's own `hidden_mem` (hidden.py) |
| none-long | yes | **PASS 26/26** | 449 | the same |
| counts-short | no: data-limited | FAIL 7/23 | 264 | 6 kills on 3 steps |
| counts-long | no: data-limited | FAIL 11/23 | 316 | 91 kills on 44 steps |

Round 1's job 282 at 7e7bd2b gave the same statuses.

## Achievability (rule 4b)

`uv run sdlab-ladder analyse 310 --variant V` covers only the noise-free variants: "hidden stock without noise:
exact if identifiable". It says "not analysed" for the counts variants, so the bound comes from the three direct
measurements already on file. They agree:

- engine_forms round 1 (Fisher information of the truth's own table, with the knots given): the expected relative rms
  error of the kill flow is 0.35 on counts-short and 0.20 on counts-long. The tolerance is 0.10.
- combined2 round 2 (310-combined2.md): the truth's own table, refitted at its true knots, misses the OOM move by
  28.7% (counts-short) and 16.4% (counts-long). The tolerance is 10%.
- structures round 2 (310-structures.md): the relative SE of the kill rate is about 40% (counts-short) and about
  10.5% (counts-long), and it calls counts-long "borderline at best".

Even the truth's own form with its knots given misses the kill move on counts-long by more than the tolerance. Both
counts variants are therefore data-limited, and they are not targets for this rung.

## Fixes kept this round

None. The round 1 fixes still carry the rung:

- counted-flow exact re-read (reread.py, ec6265e)
- precision-snap (ec6265e)
- hidden-integrator stock (hidden.py, 7e7bd2b)

310-engine_forms.md describes each one and how another strategy adopts it.

## Method faults left on the counts variants (for the counts or regression round)

These are not targets on 310 (the variants are data-limited), but they are method faults, not data limits:

- counts-long: the pods block blows up. The answer has `outside -> pending = -1,145,165` and
  `ready -> outside = -541,303 - 587,916 x mem` in place of the gap controller and the kill move. The same family of
  faults has been on 309 counts-long since 309 (PPFF there). A coefficient guard (refuse a flow whose amounts dwarf
  every measured change of its stocks) is the obvious candidate. Without a regression run it was not attempted.
- counts-short: there are spurious moves `ready <-> desired`, `inflight -> queue` reads pending, and the retries
  split is lost (`retries -> outside` 0.001 against 0.4).
- Both: mem's drain is absorbed (hidden.py rightly leaves noisy rows alone). A noisy-row version would need the
  Kalman likelihood (kalman_lna's `_hidden` machinery, written out as a stock and not as a schedule).
