"""No strategy imports another strategy; a composite or derivative carries its own copy
(sdlab/CLAUDE.md invariant 11; tests/isolation.py)."""

from isolation import violations

# Strategies that still import others (2026-10-19). Queue item 0c converts them to copies; this
# list may only shrink. A new entry is a failure: copy the code you build on instead of importing it.
KNOWN = {
    "combined": {"censored", "common_cause", "effect_hats", "gap_prior", "hidden_transit", "lna", "lna_pulses", "lna_stack", "periodic_inflows"},
    "combined_lean": {"combined", "combined_misfit"},
    "combined_misfit": {"combined"},
    "combined_r2": {"combined_lean", "combined_misfit"},
    "gap_prior": {"lna"},
    "gated_no_high": {"gated"},
    "held_out_blend": {"held_out"},
    "inflow_attribution_both": {"inflow_attribution"},
    "inflow_attribution_refine": {"inflow_attribution"},
    "kalman_lna": {"combined", "lna"},
    "lna_levels": {"lna"},
    "lna_loops": {"lna"},
    "lna_products": {"lna", "lna_levels"},
    "lna_pulses": {"impulses", "lna"},
    "lna_stack": {"gap_prior", "impulses", "lna", "lna_levels", "lna_products", "lna_pulses"},
    "mass_balance_all": {"mass_balance"},
    "structures": {"combined", "lna_stack"},
}


def test_no_new_cross_strategy_imports():
    new = {n: u - KNOWN.get(n, set()) for n, u in violations().items()}
    new = {n: u for n, u in new.items() if u}
    assert not new, ("A strategy imports another strategy. Copy the code you build on into your own "
                     f"package instead (sdlab/CLAUDE.md invariant 11): {new}")
