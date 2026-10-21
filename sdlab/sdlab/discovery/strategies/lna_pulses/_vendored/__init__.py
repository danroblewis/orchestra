"""Copies of the strategies lna_pulses builds on (lna and impulses), taken unchanged from sdlab/discovery/strategies/ at
commit 0c7a76b (CLAUDE.md invariant 11: no strategy imports another; queue item 0c). Only their imports are rewritten to
point at these copies, so a change to the originals never changes lna_pulses.

The lna copy carries the declared boundary (2026-10-20): lna/boundary.py, a copy of
sdlab/discovery/strategies/matrix/boundary.py at commit 723f72c with lna's atom filter added, wired
into this copy's run.py, fit.py, swaps.py and __init__.py exactly as in sdlab/discovery/strategies/lna/
(docs/research/declared-boundary.md)."""
