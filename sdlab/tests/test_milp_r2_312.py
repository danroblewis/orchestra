"""milp, k8s-312 round 2: the inflow-step budget and the table-aware joint polish."""

import numpy as np

from sdlab.discovery.strategies import milp
from sdlab.discovery.strategies.milp import polish


def test_largest_keeps_the_biggest_jumps_in_order():
    e = np.r_[np.zeros(10), np.ones(10) * 5, np.ones(10) * 5.1, np.ones(10) * 2]
    assert milp._largest(e, [10, 20, 30], 2) == [10, 30]
    assert milp._largest(e, [10, 20, 30], 3) == [10, 20, 30]


def test_step_cap():
    assert milp._step_cap(300) == 3 and milp._step_cap(2000) == 20 and milp._step_cap(50) == 2


def test_tabled_reads_a_table_effect_on_a_proportional_rate():
    f = {"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 1.0},
         "effects": [{"stock": "m", "shape": "table", "points": [[480, 0.0], [0, 0.0], [800, 3.0]]}]}
    pos = {"a": 0, "b": 1, "m": 2}
    assert polish._tabled(f, pos, ()) == ("a", 1.0, "m", (0.0, 480.0, 800.0), (0.0, 0.0, 3.0))
    assert polish._tabled({**f, "byTime": [{}]}, pos, ()) is None
    assert polish._tabled({**f, "effects": []}, pos, ()) is None
