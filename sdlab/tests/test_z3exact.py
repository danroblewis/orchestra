"""z3exact (docs/research/z3.md, experiment B) on tiny synthetic data: exact structure, refit numbers,
nothing on noisy data."""

import random

from sdlab.discovery.strategies import load


def _chain(noise: float = 0.0, steps: int = 120):
    x = {"A": 0.0, "B": 0.0}
    lv = {"A": [], "B": []}
    rng = random.Random(1)
    for _ in range(steps):
        for s, v in x.items():
            lv[s].append(round(v + rng.gauss(0, noise), 4) if noise else round(v, 4))
        a, b = x["A"], x["B"]
        x = {"A": a + 20 - 0.5 * a, "B": b + 0.5 * a - 0.2 * b}
    run = {"t": list(range(1, steps + 1)), "levels": lv, "boundary_declared": True,
           "boundary": {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}}
    return [{"id": "A", "name": "A"}, {"id": "B", "name": "B"}], run


def test_chain_recovered_exactly():
    stocks, run = _chain()
    r = load("z3exact")(stocks, run, {})
    got = {(f["from"], f["to"]): f["rate"] for f in r["flows"]}
    assert set(got) == {(None, "A"), ("A", "B"), ("B", None)}
    assert abs(got[("A", "B")]["k"] - 0.5) < 1e-4 and abs(got[("B", None)]["k"] - 0.2) < 1e-4
    assert abs(got[(None, "A")]["value"] - 20) < 1e-3


def test_noisy_data_gets_a_labelled_best_effort():
    stocks, run = _chain(noise=0.5)
    r = load("z3exact")(stocks, run, {})
    assert r["z3"]["best_effort"] and "BEST EFFORT" in r["note"]
    assert {(f["from"], f["to"]) for f in r["flows"]} >= {("A", "B")}
