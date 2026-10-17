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
