"""The sd-hidden-chain example's simulator: its truth model (../truth.model.json), a system dynamics model
stepped with SD Lab's own equations (see sdlab/sdtruth.py)."""

from pathlib import Path

from sdlab.sdtruth import Truth

TRUTH = Truth(Path(__file__).resolve().parent.parent / "truth.model.json")
SEED, STEPS, LONG_STEPS = TRUTH.seed, TRUTH.steps, TRUTH.long_steps
MEASURED_STOCKS = TRUTH.measured_ids
UNBOUNDED = True                       # a longer run begins with the shorter one: it can go on forever


def run(seed: int = SEED, steps: int = STEPS) -> dict:
    return TRUTH.run(seed, steps)


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    return TRUTH.measured(seed, steps)
