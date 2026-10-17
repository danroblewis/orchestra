"""History: what the example's dashboard showed at every step (see sdlab/sdtruth.py).

    history.py [seed] [steps]
"""

import sim

from sdlab.sdtruth import history_main

if __name__ == "__main__":
    history_main(sim.TRUTH)
