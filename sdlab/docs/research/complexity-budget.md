# A complexity budget the analyst states

**Status:** idea (not started)

## Why
An analyst can usually say how big the answer can be: "I can't imagine more than 10 stocks worth
talking about here", "maybe 20 flows", "demand changes a few times a season, not daily". Discovery's
worst overfitting comes from flexibility the data cannot pin down: outside-inflow pieces that track a
run's draws (151 pieces where the truth is a constant 800 in sd-population; pieces into internal
stocks in sd-support-tiers), and hidden stocks or flows added because they fit. The change-price
experiment showed no single price per change suits every example; an explicit budget is a clearer
prior, and modellers bound their models this way in practice (suggested by the user).

## How it could be tried
- Options on identify(): maximum hidden stocks, maximum flows, maximum changes per outside inflow
  (or a minimum time between changes), set by the user on the page.
- On the bench, budgets must come from what an analyst could plausibly say, never from the true model:
  generic rules (e.g. hidden stocks <= measured stocks; inflow changes <= one per N steps) and a sweep
  over budgets to show results are robust rather than tuned per example.
- Under a budget, selection keeps the best model within it (e.g. the best k inflow changes by
  optimal partitioning with a fixed number of segments, which PELT's segment-neighbourhood form does).
- Compare with the fresh-run grade (bench column): a budget should close any gap between in-sample
  and fresh-run skill.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook M15 (rank 8): step 2 of the procedure ("count and budget"); combine with [inflow-innovations](inflow-innovations.md).
- Killick, Fearnhead, Eckley (2012). JASA 107(500):1590-1598 (PELT and the segment-neighbourhood search with a fixed number of changes).
- Bai, Perron (1998). Econometrica 66(1):47-78 (m breaks, chosen by criterion or sequential tests).
- Jakeman, Hornberger (1993). How much complexity is warranted in a rainfall-runoff model? WRR 29(8):2637-2649 (4-6 parameters per series).
- Chen et al. (2024), CPT PSP 13(10):1784-1797, and Duvnjak et al. (2024), CPT PSP 13(10):1707-1721 (automatic model search drifts to over-complex models).
- Daniels, Nemenman (2015). Nat. Commun. 6:8133 (hidden variables added one at a time in a fixed order).
