"""Ground truth for the shop example: what the measured model is never told.

Writes truth.json beside this file (the call graph with fan-outs, produce / consume / worker-call
edges, latencies, capacities, pool sizes per era, the outage, and the SD structure a perfect
discovery would report, with the coefficients it should find) and prints a short summary.

    python truth.py [seed]
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_sim():
    """The simulator is a program file beside the history program, not a package module."""
    spec = importlib.util.spec_from_file_location("shop_sim", HERE / "machines" / "sim.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod


sim = load_sim()


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    truth = sim.ground_truth(sim.run(seed))
    (HERE / "truth.json").write_text(json.dumps(truth, indent=1) + "\n")
    sd = truth["sd_structure"]
    print(json.dumps({"sizes": truth["sizes"], "requests": truth["requests"], "messages": truth["messages"],
                      "flows": len(sd["flows"]), "driven_inflows": len(sd["driven_inflows"]),
                      "mean_levels": truth["mean_levels"]}, indent=1))


if __name__ == "__main__":
    main()
