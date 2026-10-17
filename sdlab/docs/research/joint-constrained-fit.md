# One constrained joint fit of all stocks

**Status:** idea (not started)

## Why
Rows are fitted separately and reconciled by conservation rules afterwards; a joint fit with flows as shared columns, sign constraints and conservation built in removes the rules (and the misfit rows they leave).

## How it could be tried
cvxpy QP; mixed-integer best-subset selection for exact structure choice; compare with stepwise BIC and [pysindy](pysindy.md)'s ConstrainedSR3.
