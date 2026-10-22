# 311 (k8s-node-pool): engine_forms, round 2

**Status (2026-10-22, agent ef311-r2, engine_forms lock held and released): engine_forms passes every achievable
variant of 311 at the current `sdlab` HEAD (94eb116). No code change was needed this round, and none was made.**

Since round 1 (4326b3a, docs/research/fixes/311-engine_forms.md) nothing that engine_forms's results depend on has
changed: `git log 4326b3a..HEAD -- sdlab/discovery/strategies/engine_forms sdlab/ladder sdlab/discovery/*.py` is
empty, and `uv run sdlab-ladder status --strategies engine_forms --detail` shows the 311 row `PPFF` with no stale
mark (strategy, case and scorer hashes equal the HEAD's). The results are deterministic, so the pool was not asked
to recompute them; they are round 1's pool job 295 (`uv run sdlab-ladder job 295`).

| variant | achievable? | result (code 4326b3a, job 295, fresh at 94eb116) | seconds |
|---|---|---|---|
| none-short | yes | **PASS 26/26** | 136 |
| none-long | yes | **PASS 26/26** | 393 |
| counts-short | no: data-limited | FAIL 5/23 | 292 |
| counts-long | no: data-limited | FAIL 3/23 | 666 |

(`uv run sdlab-ladder show 311-k8s-node-pool --strategy engine_forms --variant V`.)

## Achievability (rule 4b)

`uv run sdlab-ladder analyse 311-k8s-node-pool --variant counts-short|counts-long` still says "not analysed: a truth
this analysis does not cover". The bound therefore comes from the direct measurements on file, which agree:

- engine_forms round 1: Fisher information of the truth's own kill table (knots given): expected relative rms error
  of the kill flow 0.31 (counts-short) and 0.20 (counts-long) against a tolerance of 0.10.
- combined2 (311-combined2.md): free-knot Poisson ML misses the OOM move by 15.4% / 17.2%.
- milp (311-milp.md): P 0.25 / 0.36 of being within tolerance at the Cramér-Rao bound, knots given.
- structures and kalman_lna (311-structures.md, 311-kalman_lna.md): counts data-limited by the same kill-rate bound
  as 310.

So counts-short and counts-long are not targets for this rung.

## Fixes kept this round

None. Round 1's fixes carry the rung (311-engine_forms.md): the MIN move read from a row pair (start into the room
left), the collinear column guard (COND), the counted-flow screen that sees the table's onset, and expression rates
evaluated in the checks. Each entry there says how another strategy adopts it.

## Left for the counts and regression rounds

Round 1's notes stand: check 309 and 310 none-short/none-long once (the pair reader, the COND guard and the
expression-aware explained-row check change every exact re-read), and the counts method faults (absurd
`outside -> pending` numbers, invented `desired -> errors_total` on counts-long) are for the counts round.
