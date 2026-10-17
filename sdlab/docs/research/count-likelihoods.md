# Poisson / negative-binomial likelihoods and count-aware weights

**Status:** idea (not started)

## Why
The data is made of counts: a flow's variance equals its mean. Least squares with equal weights ignores that; calibration practice recommends count likelihoods.

## How it could be tried
Weight each row by its flows' variance (iteratively reweighted least squares / GLM); variance-based drain estimates (see [shared-noise](shared-noise.md) open ideas).
