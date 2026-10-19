# combined_r2: combined_misfit's choice, then combined_lean's leaner pass

**Status:** done on the ladder. The tests ran at e0bc5f5; the realistic runs ran at 781c56c (two
fixes to the leaner pass; see combined_lean.md). Examples bench: started, then stopped at the
coordinator's request (load). **Not run.**
**Strategy:** `sdlab/discovery/strategies/combined_r2/`: own copies of combined (`_vendored/`, from
237f52c), of combined_misfit (`misfit.py`, `fitcheck.py`) and of combined_lean (`lean.py`, `prune.py`).
**Verdict:** this is the proposal for combined's round 2 (queue 2f). It is the best of the three on
strict and close to combined_misfit on the realistic runs.

| | tests pass (936) | strict | noisy pass / strict (110) | realistic skill@20 (62) |
|---|---|---|---|---|
| combined (stored) | 679 | 618 (66.0%) | 26 / 19 | 40.6% |
| lna | 579 | 432 (46.2%) | 20 / 12 | 17.5% |
| combined_misfit | 678 | 617 (65.9%) | 26 / 19 | 45.2% |
| combined_lean | 682 | 649 (69.3%) | 32 / 27 | 39.4% |
| **combined_r2** | **682** | **649 (69.3%)** | **32 / 27** | **44.1%** |
| effect_hats | | | | 49.9% (54 runs, 12 timeouts) |

On the 54 runs effect_hats has, combined_r2 reaches 49.2% against effect_hats' 49.9% and combined's
44.9%. Paired with the stored combined over 63 runs it is +1.6 points (11 better, 12 worse, p = 0.72).
Paired with combined_lean, the same session, it is +5.4 (8 better, 8 worse, p = 0.71). Paired with
combined_misfit it is -0.4: sd-population long is worse (-42% against 46%) and sd-support-tiers long
better (95% against 42%). Sources and commands are as in [combined_misfit.md](combined_misfit.md) and
[combined_lean.md](combined_lean.md). The ideas and the offline study are in
[ideas-2026-10-18.md](ideas-2026-10-18.md).
