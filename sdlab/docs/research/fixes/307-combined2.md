# 307 (k8s-cpu-usage), combined2: noise-free and counts variants

Agent combined2-307, 2026-10-21. Plan: climb kubernetes 307-311 on none-short, none-long, counts-short and
counts-long only (the user, 2026-10-21).

## Status: passes all four, no new fix needed

`uv run sdlab-ladder show 307 --strategy combined2 --variant V` at code 1b31e14 (the `sdlab` HEAD), read
2026-10-21; `status --strategies combined2` shows the row `PPPPPT` with no stale mark:

| variant | status | parts | complexity (found / true) | worst part error |
|---|---|---|---|---|
| none-short | PASS | 10/10 | 20 / 20 | 0.0% |
| none-long | PASS | 10/10 | 20 / 20 | 0.0% |
| counts-short | PASS | 10/10 | 21 / 20 | 4.9% (cpu's link from ready, 20.99 for 20) |
| counts-long | PASS | 10/10 | 21 / 20 | 12.6% (retries -> queue, 0.524 for 0.6; `analyse`: achievable, p 0.91) |

History (`store.history('307-k8s-cpu-usage', V, 'combined2')`): the last fails are at 4d317d5 (none-short,
2026-10-21 06:54Z) and 793b5b5 (counts-long, 01:01Z). Each variant has passed on every run since 45bfaac
(17:22Z), and again at 90dba1e, 08d0733 and 1b31e14. At the last fail, none-short had 6/10 parts. The MIN
missed by 21.5%, the input link was 0.92 for 1, and retries -> queue and retries' drain were missing.

## Fixes that turned it (already in combined2, from the 306 work; none are new here)

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| boundary-fill | a declared outside flow is always in the model: `fill_declared` adds each declared side the model lacks (estimated inflow: a constant; outflow: a drain) | 1403d66 | copy `boundary.py` (identical copy per strategy) and call it on the final structure |
| min-form | a capacity limit `min(a X, b Y)` offered to the strategy's own fit (capmin.py), the offered MIN series read like a level only in the limited flow's rows | f8883c5, 6e18658 | copy `capmin.py` into the package and offer it after the strategy's own fit |
| input-kind | a declared `input` inflow is exactly 1 x the measured series, and one outside flow per declared side | 284de71, c7cade0 | in the copied `boundary.py`, honour `kind: input` (fix the number at 1) and merge same-side outside flows |

C1's oefit.py commits (08d0733, 1b31e14) do not act on these variants: oefit runs only when the one-step
residuals show measurement error (`eiv.white_z`). The passes at 08d0733 and 1b31e14 show it does no harm here.

## Left open (not a failure)

On the counts variants retries' drain is found as `-2.8 + 0.388 x retries` (counts-short) and `-1.8 +
0.404 x retries` (counts-long). The affine form `c + k X` (gap_forms, 730ae03) is kept on a declared
estimate side, and that costs +1 term against the truth. It passes, so I left it alone. Without regression
runs I could not show that tightening the affine form's price would leave the cases it was added for
(083 meas-short) unharmed. It belongs in the later full regression run.

No pool job was submitted. The four target cells were already current on the HEAD commit.
