"""Identifying a known system dynamics model from its measured stocks (sdlab/discovery).

The data comes from the ground-truth examples' simulators (generated once and cached outside the
repository by tests/bench/datasets.py), so the right answer is known exactly.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from sdlab.discovery import identify
from sdlab.discovery.changes import pelt
from sdlab.discovery.simulate import Model

ROOT = Path(__file__).resolve().parents[1]


def _datasets():
    spec = importlib.util.spec_from_file_location("bench_datasets", ROOT / "tests" / "bench" / "datasets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def data(example: str, steps: int):
    d = json.loads(_datasets().dataset(example, steps=steps).read_text())
    model = json.loads((ROOT / "sdlab" / "examples" / f"{example}.json").read_text())
    return model, {"t": d["t"], "levels": d["levels"]}


def find(r, src, dst, link=None):
    return next((f for f in r["flows"] if f["from"] == src and f["to"] == dst and bool(f.get("driver")) == bool(link) and (not link or f["driver"] == link)), None)


def k(f):
    return f["rate"]["k"] if f["rate"]["form"] == "proportional" else f["rate"]["terms"][0]["k"]


def test_pelt_finds_the_changes_in_a_noisy_series():
    rng = np.random.default_rng(1)
    r = np.concatenate([rng.normal(m, 1, 200) for m in (5, 9, 3, 6)])
    # at the textbook price (a change's value and its place: 2 x log n x the noise variance); the
    # method itself uses a lighter price, which finds a few chance changes as well
    assert pelt(r, 5, 2) == [0, 200, 400, 600, 800]
    assert {200, 400, 600} <= set(pelt(r, 5, 1))


def test_a_model_steps_many_states_at_once_and_floors_at_zero():
    flows = [{"from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.5}},
             {"from": None, "to": "a", "inflow": [{"from": 1, "to": 1, "value": 10}, {"from": 2, "to": 9, "value": 0}], "rate": {"form": "constant", "value": 5}},
             {"from": "b", "to": None, "rate": {"form": "constant", "value": 100}}]
    L = Model(flows, ["a", "b"]).step(np.array([[4.0, 8.0], [0.0, 1.0]]), np.array([1.0, 2.0]))
    assert L.tolist() == [[12.0, 4.0], [0.0, 0.0]]


@pytest.mark.xfail(strict=True, reason="the inbox's row takes a spurious +0.026 x working (a link working -> inbox); with the "
                   "intake measured consistently with the row's numbers it is 4.88, not 5.75 (docs/DISCOVERY-EXPERIMENTS.md)")
def test_the_work_pipeline_every_flow_between_stocks_and_the_intake_that_changes():
    model, run = data("sd-pipeline", 6000)
    r = identify(model["stocks"], run)
    for src, dst, want in [("inbox", "working", 0.3), ("working", "review", 0.2), ("review", "done", 0.25), ("review", "working", 0.05)]:
        f = find(r, src, dst)
        assert f and abs(k(f) - want) <= 0.02, f"{src} -> {dst}: {f and k(f)} (truth {want})"
    intake = next((f for f in r["flows"] if not f["from"] and f["to"] == "inbox" and not f.get("driver")), None)
    assert intake and intake["changes"] >= 100 and abs(intake["rate"]["value"] - 5.75) <= 0.6
    assert not any(f["from"] == "inbox" and not f["to"] for f in r["flows"]), "nothing leaves the inbox for outside"


def test_saas_the_ad_link_the_funnel_and_the_budget_released_in_eras():
    model, run = data("sd-saas", 3650)
    r = identify(model["stocks"], run)
    ads = find(r, None, "visitors", link="ad_budget")
    assert ads and abs(k(ads) - 0.114) <= 0.01
    for src, dst, want, tol in [("ad_budget", None, 1 / 7, 0.01), ("visitors", "trials", 0.012, 0.002), ("visitors", None, 0.25, 0.02),
                                ("trials", "paying", 0.0157, 0.003), ("trials", None, 0.0557, 0.005), ("paying", "churned", 0.005, 0.002)]:
        f = next((x for x in r["flows"] if x["from"] == src and x["to"] == dst and not x.get("driver") and x["rate"]["form"] == "proportional"), None)
        assert f and abs(k(f) - want) <= tol, f"{src} -> {dst or 'outside'}: {f and k(f)} (truth {want})"
    release = next((f for f in r["flows"] if not f["from"] and f["to"] == "ad_budget"), None)
    assert release and release["changes"] >= 30 and abs(release["rate"]["value"] - 1400) <= 150
    assert not any(f["from"] == "ad_budget" and f["to"] == "visitors" for f in r["flows"]), "dollars do not become people: the ads are a link"


@pytest.mark.parametrize("length", ["default"])
def test_announced_eras_give_each_configuration_its_own_numbers(length):
    d = json.loads(_datasets().dataset("sd-eras").read_text())
    model = json.loads((ROOT / "sdlab" / "examples" / "sd-eras.json").read_text())
    eras = [{"start": e["start"], "label": e["label"]} for e in d["eras"]]
    r = identify(model["stocks"], {"t": d["t"], "levels": d["levels"]}, {"eras": eras})
    stage1 = find(r, "raw", "middle")
    assert stage1 and stage1.get("byTime"), "stage 1's rate follows the eras"
    by_label = dict(zip(r["eras"], (x["k"] for x in stage1["rates"])))
    assert abs(by_label["One machine at stage 1"] - 0.3) <= 0.03 and abs(by_label["Second machine at stage 1"] - 0.55) <= 0.03
    stage2 = find(r, "middle", "finished")
    by_label = dict(zip(r["eras"], (x["k"] for x in stage2["rates"])))
    assert abs(by_label["Stage 2 machine breaks down (half speed)"] - 0.2) <= 0.03 and abs(by_label["Stage 2 repaired"] - 0.4) <= 0.03


def test_synthetic_ground_truth_a_plain_chain_is_recovered_exactly_enough():
    from synth import generate, skill

    d = generate(stocks=[{"id": "a", "initial": 20}, {"id": "b", "initial": 10}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 6}},
                        {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.3}},
                        {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}], steps=2000)
    r = identify(d["stocks"], d["run"])
    assert abs(k(find(r, "a", "b")) - 0.3) <= 0.02 and abs(k(find(r, "b", None)) - 0.2) <= 0.02
    assert skill(r, d) > 0.95
