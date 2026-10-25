"""Copies of the strategies combined builds on (the specialists it runs: censored, common_cause (with its own _vendored copies of the shared modules), effect_hats, gap_prior, hidden_transit (with its stages, stage.py and stagekf.py), lna, lna_pulses, lna_stack and periodic_inflows, and what they call: lna_levels, lna_products and impulses), taken unchanged from sdlab/discovery/strategies/ at
commit 0c7a76b (CLAUDE.md invariant 11: no strategy imports another; queue item 0c). Only their imports are rewritten to
point at these copies, so a change to the originals never changes combined."""
