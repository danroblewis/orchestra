"""combined2's floored outside flows (hinge.py) and the switch's dropped moves (switch.py),
docs/research/fixes/309-combined2.md."""

import numpy as np

from sdlab.discovery.strategies.combined2 import hinge, switch


def _record(n=400):
    """An actuator `want` stepped by a load, `wait` filled to the gap want - wait - have, `have` fed from
    `wait` at 0.5 a step and cut to `want` at once (the gaps floored at 0)."""
    t = np.arange(n + 1, dtype=float)
    load = 1500 + 900 * np.sin(2 * np.pi * t / 150)
    want, wait, have = (np.zeros(n + 1) for _ in range(3))
    want[0] = have[0] = 9
    for i in range(n):
        up = 1.0 if (load[i] > 190 * want[i] and want[i] < 16) else 0.0
        down = 1.0 if (load[i] <= 160 * (want[i] - 1) and want[i] > 3) else 0.0
        made = max(0.0, want[i] - wait[i] - have[i])
        cut = max(0.0, have[i] - want[i])
        want[i + 1] = want[i] + up - down
        wait[i + 1] = wait[i] + made - 0.5 * wait[i]
        have[i + 1] = have[i] + 0.5 * wait[i] - cut
    return t, load, want, wait, have


def _run(t, **lv):
    return {"t": list(t), "levels": {k: list(v) for k, v in lv.items()},
            "boundary": {"want": {"in": "estimate", "out": "estimate"}, "wait": {"in": "estimate"}, "have": {"out": "estimate"},
                         "load": {"in": "estimate"}},
            "boundary_declared": True}


def test_floored_side_replaces_a_smeared_drift():
    t, load, want, wait, have = _record()
    run = _run(t, want=want, wait=wait, have=have, load=load)
    stocks = [{"id": k} for k in ("want", "wait", "have", "load")]
    flows = [{"from": "wait", "to": "have", "rate": {"form": "proportional", "stock": "wait", "k": 0.5}},
             {"from": None, "to": "wait", "rate": {"form": "linear", "c": 0.0, "terms": [
                 {"stock": "want", "k": 1.0}, {"stock": "wait", "k": -1.0}, {"stock": "have", "k": -1.0}]}},
             {"from": "have", "to": None, "rate": {"form": "proportional", "stock": "have", "k": 0.003}}]
    out = hinge.apply({"flows": flows}, stocks, run, {})
    cut = [f for f in out["flows"] if f["from"] == "have" and f["to"] is None]
    assert len(cut) == 1
    w = {x["stock"]: x["k"] for x in cut[0]["rate"]["terms"]}
    assert set(w) == {"have", "want"} and abs(w["have"] - 1) < 1e-6 and abs(w["want"] + 1) < 1e-6
    assert abs(cut[0]["rate"]["c"]) < 1e-9
    assert [n["stock"] for n in out["floored"]] == ["have"]           # wait's exact row is left alone


def test_switch_drops_an_actuators_smeared_move_and_repairs_the_partner():
    t, load, want, wait, have = _record()
    run = _run(t, want=want, wait=wait, have=have, load=load)
    stocks = [{"id": k} for k in ("want", "wait", "have", "load")]
    flows = [{"from": "wait", "to": "have", "rate": {"form": "proportional", "stock": "wait", "k": 0.5}},
             {"from": "want", "to": "have", "rate": {"form": "proportional", "stock": "want", "k": 0.08}},
             {"from": "have", "to": None, "rate": {"form": "proportional", "stock": "have", "k": 0.082}},
             {"from": None, "to": "want", "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "load", "k": 0.0005}]}}]
    out = switch.apply({"flows": flows}, stocks, run, {})
    pairs = {(f["from"], f["to"]) for f in out["flows"]}
    assert ("want", "have") not in pairs
    assert {(None, "want"), ("want", None)} <= {(f["from"], f["to"]) for f in out["flows"] if f.get("switch")}
    note = out["switch"][0]
    assert note["moves_dropped"] == ["want->have"] and note["repaired"][0]["sse_after"] < 1e-12
