"""Experiment output_error: refine the matrix method's numbers by multi-step (output) error.

Mechanism tests on synthetic ground truth (tests/synth.py):

1. The building block: with the right structure and the right outside inflow, rates that are off
   (as a one-step bias leaves them) are brought back to the truth by the multi-step fit alone.
2. The bias it is for: children and adults, births from adults, a migration into adults that
   changes without being announced. When the main line treats the inflow as constant (it chooses
   that variant on sd-population long and sd-fishery long), the one-step fit lends the migration's
   swings to the levels: a spurious "adults grow with themselves" loop and a wrong drain, a model
   that runs off over 100 steps (matrix: skill@100 about -32 and -24 on seeds 1 and 2). The
   refinement shrinks the spurious loop by more than half and cuts the 100-step error about three
   times (skill@100 about -11 and -9). It cannot fix the structure, so the model is still poor: the
   refinement repairs numbers, not parts.
"""

from __future__ import annotations

import pytest
from synth import generate, skill

from sdlab.discovery.refine import refine
from sdlab.discovery.identify import identify as main_line  # the pinned main line (the matrix strategy earns its pieces since docs/research/k8s-302.md)
from sdlab.discovery.strategies import load


def _k(flows, src, dst, driver=None):
    for f in flows:
        if f.get("from") == src and f.get("to") == dst and f.get("driver") == driver and not f.get("inflow"):
            r = f["rate"]
            return r["k"] if r["form"] == "proportional" else r["terms"][0]["k"]
    return 0.0


def test_the_multi_step_fit_brings_rates_that_are_off_back_to_the_truth():
    d = generate(stocks=[{"id": "a", "initial": 20}, {"id": "b", "initial": 30}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 6}},
                        {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}},
                        {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}],
                 steps=1500, schedule={"every": 100, "changes": [{"t": 1, "set": {"in": {"form": "constant", "value": 6}}},
                                                                   {"t": 51, "set": {"in": {"form": "constant", "value": 12}}}]})
    t = d["run"]["t"]
    inflow = [{"from": t[0] + p * 100, "to": t[0] + p * 100 + 49, "value": 6} for p in range(15)]
    inflow += [{"from": t[0] + p * 100 + 50, "to": t[0] + p * 100 + 99, "value": 12} for p in range(15)]
    off = [{"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.45}},
           {"from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.12}},
           {"from": None, "to": "a", "rate": {"form": "constant", "value": 9}, "inflow": inflow}]
    flows, note = refine(off, ["a", "b"], t, d["run"]["levels"], {"profile": False, "max_nfev": 50})
    assert note["refined"]
    assert abs(_k(flows, "a", "b") - 0.3) < 0.03 and abs(_k(flows, "b", None) - 0.2) < 0.02
    assert skill({"flows": off}, d, 100) < 0.5 < 0.95 < skill({"flows": flows}, d, 100)


def _population(seed):
    every = 60
    waves = [(1, 800), (20, 3000), (30, 300), (45, 900)]
    return generate(stocks=[{"id": "kids", "initial": 3000}, {"id": "adults", "initial": 10000}],
                    flows=[{"id": "births", "from": None, "to": "kids", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "adults", "k": 0.022}]}},
                           {"id": "grow", "from": "kids", "to": "adults", "rate": {"form": "proportional", "stock": "kids", "k": 0.0556}},
                           {"id": "migrate", "from": None, "to": "adults", "rate": {"form": "constant", "value": 800}},
                           {"id": "deaths", "from": "adults", "to": None, "rate": {"form": "proportional", "stock": "adults", "k": 0.0242}}],
                    steps=3000, seed=seed,
                    schedule={"every": every, "changes": [{"t": t, "set": {"migrate": {"form": "constant", "value": v}}} for t, v in waves]})


@pytest.mark.parametrize("seed", [1, 2])
def test_a_spurious_reinforcing_loop_from_a_one_step_fit_is_shrunk(seed):
    d = _population(seed)
    constant = {"variants": [{"name": "constant inflows", "changes": False}]}
    m = main_line(d["stocks"], d["run"], constant)
    o = load("output_error")(d["stocks"], d["run"], constant)
    assert o["chosen"].endswith("refined")
    loop_m, loop_o = _k(m["flows"], None, "adults", "adults"), _k(o["flows"], None, "adults", "adults")
    assert loop_m > 0.025 and loop_o < loop_m / 2                     # the spurious loop (truth: none)
    s100_m, s100_o = skill(m, d, 100), skill(o, d, 100)
    assert s100_m < -15 and s100_o > s100_m / 2                         # matrix ~ -32 / -24; refined ~ -11 / -9
    assert skill(o, d, 20) > skill(m, d, 20)
