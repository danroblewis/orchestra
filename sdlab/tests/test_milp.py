"""milp (docs/research/milp.md): the program recovers a MIN of two stocks and stays inside the boundary."""

import numpy as np

from sdlab.discovery.strategies import load


def _run(T: int = 200):
    """outside -> A at 30 + 20 sin; A -> B at MIN(0.5 A, 8 C) (C a measured capacity, stepped by hand);
    B -> outside at 0.2 B."""
    A, B = [40.0], [50.0]
    C = np.where((np.arange(T) // 40) % 2 == 0, 3.0, 6.0)
    u = 30 + 20 * np.sin(np.arange(T) * 2 * np.pi / 50)
    for k in range(T - 1):
        move = min(0.5 * A[-1], 8 * C[k])
        A.append(A[-1] + u[k + 1] - move)
        B.append(B[-1] + move - 0.2 * B[-1])
    stocks = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    run = {"t": list(range(1, T + 1)), "levels": {"A": A, "B": B, "C": list(C)},
           "boundary": {"A": {"in": ["measured"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, "boundary_declared": True}
    return stocks, run, {"inputs": {"u": list(u)}}


def test_recovers_a_min_of_two_stocks():
    stocks, run, opts = _run()
    r = load("milp")(stocks, run, opts)
    flows = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert set(flows) == {(None, "A"), ("A", "B"), ("B", None)}, flows
    assert flows[("A", "B")]["form"] == "expr" and "C" in flows[("A", "B")]["expr"], flows
    assert abs(flows[(None, "A")]["k"] - 1) < 1e-3 and abs(flows[("B", None)]["k"] - 0.2) < 1e-3
    assert r["milp"]["solves"] and "gap" in r["milp"]


def test_no_outside_flow_where_none_is_declared():
    stocks, run, opts = _run()
    r = load("milp")(stocks, run, opts)
    for f in r["flows"]:
        assert f["from"] is not None or f["to"] == "A"
        assert f["to"] is not None or f["from"] == "B"
