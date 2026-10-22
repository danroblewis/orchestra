# 310 (k8s-memory-oom), combined2, round 2 check (2026-10-22, agent combined2-r2-310)

**Status: combined2 passes every achievable variant of 310. No code change this round; no fix added.**
none-short and none-long PASS 26/26 at d363245 (pool job 285). counts-short and counts-long fail and are
**data-limited on the OOM move**, now shown with the knots free (below), so they are not targets.

| variant | achievable? | result (d363245, job 285) |
|---|---|---|
| none-short | yes | **PASS 26/26**, 168 s |
| none-long | yes | **PASS 26/26**, 389 s |
| counts-short | no: OOM move, 27% off at best even with the true knots | FAIL 16/23 |
| counts-long | no: OOM move, 11.6-33.5% off with the knots fitted (9.2% only with the true knots given) | FAIL 13/23 |

The results are current: `runner.plan(['310-k8s-memory-oom'], runner.select_strategies('combined2')[0],
[the four variants], every_variant=True)` returns no items at HEAD de2b09c (`uv run sdlab-ladder show
310-k8s-memory-oom --strategy combined2 --variant V`). No pool job was submitted: nothing was stale and no code changed.

## Why the counts variants are not targets (rule 4b)

`analyse` gives no verdict on 310 ("not analysed": tables, switches, a hidden stock), so I checked by hand. The
coordinator's note (kubernetes-ladder.md, "310 after round 1") counted them as achievable until shown otherwise, and two
earlier oracle checks disagreed: mine (round 2, NNLS at the true knots) put counts-long's OOM move 16.4% off, while
milp's (Poisson ML at the true knots) put it 9.2% off, inside the 10% tolerance. Both give the true knots, which no method
has. This check settles it. In every fit the truth's model is kept exact except the kill table (on both `ready -> pending`
and `leak -> outside`). The table is fitted to the measured `diff(oom_kills_total)` on the measured `ready` and `mem` by
Poisson maximum likelihood, and the result is scored with `score.equations` (scratch `c2r2/freeknot.py`, `c2r2/shapes.py`,
`m310/oracle_tab.py`).

counts-long (44 kill steps, 91 kills, mem 481-682 MiB at the kills):

| table fitted | Poisson -log L | BIC | `ready -> pending [ready]` error (tol. 10%) |
|---|---|---|---|
| true knots 480/512/560/5000, heights fitted (milp's oracle) | 52.01 | - | 9.2% (pass) |
| 1 segment, knot free (BIC's choice) | 52.48 | 120.2 | 33.5% |
| 2 segments, knots free | 51.05 | 132.5 | 16.5% |
| 3 segments, knots free | 49.97 | 145.5 | 15.6% |
| zero / two knots / flat, knots free (6 numbers) | 51.21 | - | 11.6% |

The data prefer wrong tables: every free-knot fit has a higher likelihood than the true-knot one, and every one misses.
Only the truth's own knots pass, and only by 0.8 points. The heights there are 0.29, 0.49 and 17 (true 0.3, 0.8, 1), so
that pass is luck. Without the knots no method can place this part, so counts-long is data-limited. On counts-short
(3 kill steps, 6 kills) even the true knots give 27.4% (Poisson ML) or 28.7% (NNLS).

This corrects the round-2 doc's wording. Its 16.4% was a least-squares fit, and Poisson ML at the true knots passes.
The conclusion stands on the free-knot fits above. kalman_lna's r2 doc cites the 16.4%. The table above replaces that number.

## mem's drain on counts: a method fault, but downstream of the data limit

`diff --summary` puts `~ mem -> outside` too low in every strategy (combined2: 0.295 and 0.292 against 0.5). Scratch
`c2r2/memrow.py` / `memrow2.py` fit mem's row `c + g H + k inflight/max(1, ready) - a mem`, with H stepped on the
measured mem by a given table:

| H from | fit | counts-long drain a (true 0.5) | counts-short |
|---|---|---|---|
| true table | one-step least squares | 0.458 | 0.570 |
| true table | output error (simulate mem's row alone, other columns measured) | 0.507 | 0.558 |
| free-knot ML tables (the three above) | one-step least squares | 0.376-0.438 | - |
| free-knot ML tables | output error | 0.490-0.533 | - |
| none-long, true table | one-step / output error | 0.501 / 0.504 | - |

So the 0.29 is not the data's limit. It comes from (a) combined2's H, drained by 0.036 x the found table because the
borrowed kill fraction (0.179) is off, which is the data-limited part above; (b) extra columns the forward selection takes
on counts (`traffic/max(1, ready)`, `pending/max(1, ready)`); and (c) the one-step fit of a fast row (drain 0.5 a step)
under counting noise. An output-error refit of the hidden row's numbers would bring the drain within 10% even with a
data-attainable table. It is not built: neither counts variant can pass while the OOM move is data-limited, and 311,
312 and 317 keep the same OOM table. **Candidate fix type for later (`hidden-row-output-error`):** in `hiddenrow.py`,
after the columns are chosen, refit (c, g, w, a) by least squares of S simulated alone (its other columns measured,
H stepped) against measured S. Keep it only where `eiv.white_z` shows measurement or counting noise, so the none variants
keep their exact one-step fit.

The other counts-long misses were not diagnosed this round: `outside -> cpu` used 13.5 x ready against 20 (309
counts-long passes this row in combined2, so 310's pipeline causes it, not the data), `cpu -> outside` 0.433, and
`inflight -> errors_total` written as a MIN with traffic.

## Fixes

None new. The fixes that make 310 pass are in `310-combined2.md` (round 1: counted-flow, joint-active-set-refit,
add-missing-move, table-amounts, oefit-guard; round 2: hidden-integrator-stock, block-repair-nnls, input-side-held,
bare-trigger).

## Not done

- No regression run on earlier rungs (the plan: once, later). Risks for it are in `310-combined2.md`.
- counts-long runs 757 s of its 1800 s limit (job 285).
