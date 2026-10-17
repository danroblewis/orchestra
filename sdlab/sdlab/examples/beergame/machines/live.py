"""Sensor: the beergame example, live. Each tick of a run reads one step of the same seeded simulation
the history comes from, played for as long as the simulator's long recording lasts (LONG_STEPS);
see sdlab/livefeed.py.

    live.py [seed]
"""

import sim

from sdlab.livefeed import play

if __name__ == "__main__":
    play(sim, __file__)
