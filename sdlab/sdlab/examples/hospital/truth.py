"""Ground truth for the hospital example: what the measured model is never told.

Writes truth.json beside this file (hidden stocks with their per-step levels, delays and branch
shares; every true flow with its per-step counts) and prints a short summary.

    python truth.py [seed]
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_sim():
    """The simulator is a program file beside the history program, not a package module."""
    spec = importlib.util.spec_from_file_location("hospital_sim", HERE / "machines" / "sim.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod


sim = load_sim()


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    truth = sim.ground_truth(sim.run(seed))
    (HERE / "truth.json").write_text(json.dumps(truth, separators=(",", ":")) + "\n")
    print(json.dumps({k: {x: v[x] for x in ("between", "delay", "mean_level", "max_level")} | ({"branch_shares": v["branch_shares"]} if "branch_shares" in v else {})
                      for k, v in truth["hidden_stocks"].items()}, indent=1))


if __name__ == "__main__":
    main()
