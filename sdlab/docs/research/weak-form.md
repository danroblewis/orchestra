# Weak-form fitting

**Status:** idea (not started)

## Why
Fitting integrals against test functions instead of single-step differences is robust to noise.

## How it could be tried
Weak SINDy-style row fits; compare bias and variance with one-step fits on counting noise.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook conflict C2: weak forms buy robustness to measurement noise; our data are exact counts with process noise, and windows already biased our fits. Not recommended unless real data with measurement error arrive.
