"""structures' shared room (room._family, docs/research/fixes/317-structures.md): moves of several services that
start into one capacity, each by its share."""

import numpy as np

from sdlab.discovery.strategies.structures import room

SVC = ("x", "y", "z")
STOCKS = ([{"id": f"{s}_p", "unit": "pods"} for s in SVC] + [{"id": f"{s}_r", "unit": "pods"} for s in SVC]
          + [{"id": "nodes", "unit": "nodes"}])


def _run(n=300):
    # each service's pending pods p get a pulsed demand from outside; p -> r at
    # min(0.5 p, max(0, 4 nodes - sum r) * p / max(1, sum p)); r leaves at 0.05 r; nodes follow a slow schedule
    rng = np.random.default_rng(3)
    nodes = np.round(4 + 2 * np.sin(np.arange(n) / 40.0) + 0.5 * np.sin(np.arange(n) / 7.0))
    demand = {s: (rng.random(n) < 0.15) * rng.integers(1, 6, n) for s in SVC}
    p = {s: [2.0] for s in SVC}
    r = {s: [3.0] for s in SVC}
    for k in range(n - 1):
        P = sum(p[s][-1] for s in SVC)
        R = sum(r[s][-1] for s in SVC)
        room_ = max(0.0, 4 * nodes[k] - R)
        for s in SVC:
            st = min(0.5 * p[s][-1], room_ * p[s][-1] / max(1.0, P))
            out = 0.05 * r[s][-1]
            p[s].append(p[s][-1] + demand[s][k] - st)
            r[s].append(r[s][-1] + st - out)
    lv = {f"{s}_p": list(np.round(p[s], 4)) for s in SVC} | {f"{s}_r": list(np.round(r[s], 4)) for s in SVC}
    lv["nodes"] = list(nodes)
    bound = {f"{s}_p": {"in": ["estimate"]} for s in SVC} | {f"{s}_r": {"out": ["estimate"]} for s in SVC}
    bound["nodes"] = {"in": ["estimate"], "out": ["estimate"]}
    inputs = {f"d_{s}": [0.0] + [float(v) for v in demand[s][:n - 1]] for s in SVC}   # input i is read by step i - 1
    return {"t": list(range(n)), "levels": lv, "boundary_declared": True, "boundary": bound}, {"inputs": inputs}


def test_three_moves_share_one_room():
    run, opts = _run()
    # the answer has each start as a plain proportional move, the demands and the drains
    flows = ([{"id": f"d{s}", "from": None, "to": f"{s}_p", "rate": {"form": "proportional", "stock": f"d_{s}", "k": 1.0}} for s in SVC] +
             [{"id": f"m{s}", "from": f"{s}_p", "to": f"{s}_r", "rate": {"form": "proportional", "stock": f"{s}_p", "k": 0.3}} for s in SVC]
             + [{"id": f"o{s}", "from": f"{s}_r", "to": None, "rate": {"form": "proportional", "stock": f"{s}_r", "k": 0.05}} for s in SVC])
    r = room.apply({"flows": flows}, STOCKS, run, opts)
    info = r["room"]
    assert info.get("kept") and sorted(info["family"]) == sorted(f"{s}_p -> {s}_r" for s in SVC), info
    assert info["cap"] == "nodes"
    p = room.polish(r, STOCKS, run, opts)["room_polish"]
    assert abs(p["c"] - 4.0) < 0.2 and abs(p["theta"] * np.mean(p["k"]) - 1.0) < 0.1, p
