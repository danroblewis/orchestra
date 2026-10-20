"""The numopt_bo/cma/nm/powell packages carry their own copies of numopt.py and outerror.py that pass
the run's measured inputs (opts["inputs"]) to every model they run and to the judge. The shared
copies (sdlab/discovery/numopt.py, outerror.py) ran models reading a measured input with the input
missing, so on kubernetes 300 the search drove the drain to 0 and the judge, blind in the same way,
kept the broken model."""

import importlib

import numpy as np
import pytest

from sdlab.discovery.strategies import load

PACKAGES = ["numopt_bo", "numopt_cma", "numopt_nm", "numopt_powell"]


def _run(n=400):
    t = list(range(n))
    traffic = [300 + 60 * np.sin(2 * np.pi * i / 70) + (200 if (i // 50) % 3 == 1 else 0) for i in t]
    x = [100.0]
    for i in t[1:]:
        x.append(x[-1] + traffic[i] - 0.5 * x[-1])
    return [{"id": "inflight"}], {"t": t, "levels": {"inflight": x}}, {"traffic": traffic}


TRUE = [{"from": "inflight", "to": None, "rate": {"form": "proportional", "stock": "inflight", "k": 0.5}},
        {"from": None, "to": "inflight", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "traffic", "k": 1.0}]}}]


@pytest.mark.parametrize("pkg", PACKAGES)
def test_objective_reads_inputs(pkg):
    outerror = importlib.import_module(f"sdlab.discovery.strategies.{pkg}.outerror")
    stocks, run, inputs = _run()
    with_inputs = outerror.Objective(["inflight"], run["t"], run["levels"], inputs=inputs).cost(TRUE)
    without = outerror.Objective(["inflight"], run["t"], run["levels"]).cost(TRUE)
    assert with_inputs < 1e-12 < without


@pytest.mark.parametrize("pkg", ["numopt_nm", "numopt_powell"])
def test_true_model_survives_the_search(pkg):
    stocks, run, inputs = _run()
    r = load(pkg)(stocks, run, {"inputs": inputs})
    rates = {(f.get("from"), f.get("to")): f["rate"] for f in r["flows"]}
    assert rates[("inflight", None)]["k"] == pytest.approx(0.5, rel=1e-3)
    assert rates[(None, "inflight")]["terms"][0]["k"] == pytest.approx(1.0, rel=1e-3)
