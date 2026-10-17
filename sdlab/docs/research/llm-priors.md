# LLM priors from stock names and units

**Status:** idea (not started)

## Why
Names and units carry meaning ('orders -> shipped' is likelier than the reverse). As a prior that makes plausible flows cheaper in the score - never as the answer - it could break ties the data cannot.

## How it could be tried
Ask a model for plausible flows and their kinds from the page's stock list; add a prior term to the selection score; measure on the bench and check it never overrides strong evidence.
