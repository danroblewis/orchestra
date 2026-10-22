# 310 (k8s-memory-oom): milp, round 2

Status (2026-10-22, milp code 9bbd66a, unchanged this round): **milp passes every achievable variant of 310.**
none-short and none-long pass 26/26 (pool job 284, results current: `uv run sdlab-ladder status --strategies milp`
shows `310-k8s-memory-oom PPFF`, no stale mark). counts-short and counts-long fail and are **data-limited** by the
analyse criterion (p < 0.5 even at the Cramér-Rao bound with the truth's knots given; measured below), so they
are not targets. No code was kept this round: the one change tried (below) did not change any outcome and was reverted.

| variant      | achievable?                                   | result (job 284, 9bbd66a) |
|--------------|-----------------------------------------------|---------------------------|
| none-short   | yes                                           | **PASS 26/26** |
| none-long    | yes                                           | **PASS 26/26** |
| counts-short | no: P(kill flow within 10%) = 0.22 at the bound, knots given | FAIL 15/23 |
| counts-long  | no: P(kill flow within 10%) = 0.38 at the bound, knots and the 5000 height given | FAIL 20/23 |

## The data limit, measured (rule 4b)

`analyse` gives no verdict for this truth ("not analysed": effect tables and a hidden stock), so the bound was
computed by hand with the analyse definitions (analysis.py: p = P(an estimator at the bound lands within the
scorer's tolerance); data-limited when p < 0.5). The scorer compares the kill flow `ready -> pending x table(mem)`
as a whole: the relative rms error of its amount per step on the run's states, within 10% (score.py). Kills per
step are Poisson about `ready x table(mem)`. With the truth's knots (480, 512, 560, 5000) given and only the
heights free, the Fisher information of the heights on the measured kills gives the bound's normal, and a Monte
Carlo of the scorer's error at that normal gives p (script below, run on the cached data at 88c453b):

| variant      | kill steps / kills | states with mem > 512 | heights free        | median error | P(error <= 10%) |
|--------------|--------------------|-----------------------|---------------------|--------------|-----------------|
| counts-short | 3 / 6              | 0 (mem max 503)       | 512 (others unseen) | 0.234        | **0.22** |
| counts-long  | 44 / 91            | 5 (mem max 682)       | 512, 560, 5000      | 0.141        | 0.23 |
| counts-long  | 44 / 91            | 5                     | 512, 560 (5000 given) | 0.114      | **0.38** |

That is the kill flow alone, with the knots handed over. The case's joint p (every one of the 23 parts) is lower
still, and a method that must also find the knots does worse. The same verdict from other methods: engine_forms'
Fisher SE 0.35 / 0.20 (491632e), combined2's truth table refitted at its true knots, 28.7% / 16.4% (1da08e2).
Round 1's milp oracle reached 9.2% on counts-long by Poisson ML at the true knots: that one realisation landed inside
the tolerance, but at a 0.38 chance.

```python
# uv run python bound.py 2,3     (free heights: 2 = at 512, 3 = at 560, 4 = at 5000)
import sys, numpy as np
from sdlab.ladder import cases, data
c = cases.load("310-k8s-memory-oom")
knots = np.array([0, 480, 512, 560, 5000.0]); h0 = np.array([0, 0, 0.3, 0.8, 1.0])
free = [int(x) for x in sys.argv[1].split(",")]
table = lambda m, h: np.interp(m, knots, h)
rng = np.random.default_rng(0)
for v in ["counts-short", "counts-long"]:
    L = data.load(c, v)["levels"]
    ready, mem = np.array(L["ready"], float)[:-1], np.array(L["mem"], float)[:-1]
    lam = ready * table(mem, h0); use = lam > 1e-12
    B = np.stack([ready * table(mem, np.eye(5)[j]) for j in free], 1)
    C = np.linalg.pinv((B[use].T / lam[use]) @ B[use])
    norm = np.sqrt(np.mean(lam ** 2)); errs = []
    for t in rng.multivariate_normal(h0[free], C, 20000):
        h = h0.copy(); h[free] = t
        errs.append(np.sqrt(np.mean((ready * np.clip(table(mem, h), 0, 1) - lam) ** 2)) / norm)
    print(v, np.median(errs), np.mean(np.array(errs) <= 0.10))
```

## The coordinator's errors-in-variables hypothesis (mem's drain too low on counts)

Not the cause for milp. On counts the levels are the true states (counting noise is process noise: each flow
Poisson about its rate), not measurements with error, so a one-step regression on them is not attenuated. milp's
low drain on counts-short (0.383 for 0.5) is omitted-variable bias: its mem row has no hidden stock there (a
6-term linear inflow without the leak), and the leak, which rises with mem, is taken up by the drain. With the
hidden stock forced in (below), the drain comes out 0.552 on counts-short and 0.458 on counts-long.

## Why the hidden step does not fire on counts (diagnosed, not changed)

`hidden.refine` on the stored counts answers (scratchpad script: the stored flows of job 284, `quantized.find` for
the skip list, `MILP_DEBUG=1`):

| variant      | BIC current -> hidden | rss current / hidden / Poisson floor | share explained (needs 0.5) |
|--------------|-----------------------|--------------------------------------|-----------------------------|
| counts-short | 1840.5 -> 1793.5      | 123.3k / 111.6k / 88.3k              | 0.33 |
| counts-long  | 13079.6 -> 12340.3 (current: an 11-segment schedule, 78 numbers) | 1032k / 937k / 764k | 0.35 |

The hidden model wins BIC clearly but explains about a third of the misfit above the floor, so SHARE keeps the
current flows. **Tried and reverted:** count the hidden stock's own counting noise in the floor (its fill and drain
are Poisson too, so mem reads `g^2 Var(H)` of scatter no model of H's mean explains; `V' = (1-E)^2 V + 1 + E H`).
It adds 11k (short) and 72k (long) to the floor, and the share becomes 0.49 and 0.48: still under 0.5, so nothing
changes. The rest of the excess is the hidden path's error from the borrowed kill table, which is the data-limited
part above (with SHARE off, the polished drain tables come out with 1.9 and 6.5 at their last knots). Lowering SHARE to
admit these would be tuning a threshold to one case, and the variants cannot pass anyway, so nothing was kept. If
the noise variants later need the hidden stock on counts, the right mechanism is a likelihood over the hidden
path (a Kalman filter on H, as kalman_lna does), not a looser share.

## Fixes kept

None this round. Round 1's fixes (hidden integrator, hidden-drain polish, noise-floor share, counted move replacing
a stepped counter inflow) are in [310-milp.md](310-milp.md) and the fix ledger.
