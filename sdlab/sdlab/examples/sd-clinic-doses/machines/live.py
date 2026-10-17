"""Sensor: the sd-clinic-doses example, live; see sdlab/livefeed.py.

    live.py [seed]
"""

import sim

from sdlab.livefeed import play

if __name__ == "__main__":
    play(sim, __file__)
