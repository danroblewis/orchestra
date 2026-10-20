# Kubernetes rung 4 (case 303): realistic_flows counts-short

**Status:** done (2026-10-20; fix 83bc1cd). 303 counts-short fail -> pass; 300-303 no other flip;
paired 40 cells no flip. Strategy doc: [realistic-flows.md](realistic-flows.md). Earlier rounds:
[k8s-303-c1.md](k8s-303-c1.md), [k8s-303-c2.md](k8s-303-c2.md), [k8s-302.md](k8s-302.md).

## Diagnosis (rule 4b)

After C1/C2, realistic_flows failed only 303 counts-short (b9fe1d6): 3/3 true parts right, plus a
spurious `responses_total -> outside` of 30.3 a step in 5 pieces on the final counter, with
inflight's drain 0.5402 (8% fast) and a 0.0103 x queue link into inflight. `sdlab-ladder analyse` rates
the cell achievable (p 1.00), and the same code with an earned-pieces base returns 0.6004 / 0.5018 /
1.0017 with nothing else, so it is the method's fault.

The base was the shared main line (`identify.identify`), chosen candidate "backward, changing inflows,
trust receivers": conservation ties inflight's drain to the counter's inflow, the inflight row reads
the drain fast, and the counter's row takes the excess back as chance inflow pieces (a negative inflow,
i.e. a drain). This is k8s-302's cause A (chance pieces win the in-sample judge); realistic_flows was not
among the 18 strategies that got the earned refit then, and passed 302 without it.

## The change (83bc1cd)

- The base is `earned.main_line`: strategy matrix's copy of earned_pieces' refit (`earned.py`,
  `earned_rows.py`, `earned_joint.py`, copied byte for byte from matrix at 49e4ca7).
- The own-drains run (a second main-line pass with slack 0 and tol 1e-6) stays on the plain
  `identify.identify`. Running it through the earned refit too undid it: the refit re-decides each row
  and conservation, and distilled 153 and 154 none-short fell from equivalent to fail (153: only
  `outside -> O`; its earned base judges 3.92 against 7.9e-11 for the plain own-drains run).
- Selection, labelled: the existing choice between the base and the own-drains run (the judge, own run
  kept only when 5% better, `own_gain`) is unchanged; it now compares the earned base with the plain
  own-drains run. On 303 counts-short the earned base wins (0.1749 vs 0.1738 is not 5% better).

## Numbers

`uv run sdlab-ladder run --strategies realistic_flows --cases 303,300,301,302 --jobs 4 --timeout 600`
(single-threaded, rows on descendants of 83bc1cd with realistic_flows unchanged), against each cell's
latest row snapshotted before (scratchpad `rf303/before.json`):

| cells | pass -> pass | fail -> pass | other |
|---|---|---|---|
| 300-303, 20 | 19 | 1 (303 counts-short) | 0 |

303 counts-short now: `queue -> inflight 0.6004`, `inflight -> responses_total 0.5018`,
`outside -> queue 1.002 x traffic` (complexity 7, truth 7; `sdlab-ladder show 303-k8s-daily-traffic --strategy realistic_flows --variant counts-short`).

Paired sample: 40 cells drawn at random (seed 303) from realistic_flows' latest rows on the b9fe1d6 code
outside node2 and kubernetes cases, re-run one case at a time with the same command and `--variants`:
32 pass -> pass, 7 fail -> fail, 1 equivalent -> equivalent, **no flip**. Also 153 and 154 all variants:
7 equivalent, 1 fail (153 counts-long), the same as their previous rows (ea82c31).

Runtime (summed discovery seconds, not paired in time; machine load ~360): 300-303 7.7 -> 29.9 s;
sample 45.4 -> 161.6 s. The earned refit costs a joint refit per candidate; part of the rise is load.
