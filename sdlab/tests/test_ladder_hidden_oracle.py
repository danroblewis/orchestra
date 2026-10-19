"""The oracle for hidden-stock cases (sdlab/ladder/hidden_oracle.py): the truth's own structure
fitted by the Kalman filter's likelihood on the measured data, whose standard errors widen the
number tolerances on noisy variants, and never the structure."""

from __future__ import annotations

import copy

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder.hidden_oracle import HiddenOracle
from sdlab.ladder.parts import windows
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def setup(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    return c, model, d


def oracle(case_id, variant):
    c, model, d = setup(case_id, variant)
    noise = casemod.variant(c, variant)["noise"]
    return HiddenOracle(truth_by_time(model, d["t"])[0], d, windows(model, d["t"]), noise)


def scored(case_id, variant, delay=10.0, k_in=0.2, kb=0.2, plain=False):
    """The truth with the hidden stock found as one `via` flow (or, plain, as a move A -> B)."""
    c, model, d = setup(case_id, variant)
    flows = copy.deepcopy(truth_by_time(model, d["t"])[0])
    keep = [f for f in flows if f["id"] not in ("a_h", "h_b")]
    for f in keep:
        if f["id"] == "b_out":
            f["rate"]["k"] = kb
            for g in f.get("byTime") or []:
                g["rate"]["k"] = kb
            f.pop("byTime", None)
    move = {"id": "ab", "from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": k_in}}
    if not plain:
        move["via"] = {"delay": delay, "shape": "exp"}
    return score.equations(c, casemod.variant(c, variant)["noise"], model, keep + [move], d)


@pytest.mark.parametrize("case_id", ["015-hidden-stock", "026-hidden-stock-driven"])
@pytest.mark.parametrize("variant", ["counts-short", "counts-long"])
def test_hidden_cases_get_standard_errors_of_a_plausible_size(case_id, variant):
    o = oracle(case_id, variant)
    assert o.ok
    se = o.hidden_se(("hidden", "A", "B"), 0)
    assert 0.2 < se["delay"] < 3.0                     # about a step: the delay is poorly pinned down
    assert 0.002 < se["k_in"] < 0.03
    assert 0 < o.part_se(("flow", "B", None, "B"), 0) < 0.03
    assert 0 < o.part_se(("flow", None, "A", "1"), 0) < 3.0
    assert o.part_se(("flow", "A", "B", "A"), 0) is None          # a part the truth lacks: no allowance


def test_no_oracle_without_noise_or_without_a_hidden_stock():
    assert not oracle("015-hidden-stock", "none-short").ok
    assert not oracle("002-inflow-outflow", "counts-short").ok


def test_the_fit_is_deterministic():
    a, b = oracle("026-hidden-stock-driven", "counts-short"), oracle("026-hidden-stock-driven", "counts-short")
    assert a.fit == b.fit


def test_a_delay_off_by_more_than_rel_passes_within_three_standard_errors_with_noise_only():
    se = oracle("015-hidden-stock", "counts-short").hidden_se(("hidden", "A", "B"), 0)["delay"]
    delay = 10.0 + min(2.5 * se, 3.0)
    assert delay > 11.0                                              # more than the 10% the tolerance alone allows
    s = scored("015-hidden-stock", "counts-short", delay=delay)
    hidden = next(p for p in s["parts"] if p["kind"] == "hidden")
    assert hidden["ok"] and hidden["se_hidden"]["delay"] == pytest.approx(se)
    assert not next(p for p in scored("015-hidden-stock", "none-short", delay=delay)["parts"] if p["kind"] == "hidden")["ok"]


def test_a_number_beyond_three_standard_errors_still_fails():
    se = oracle("015-hidden-stock", "counts-short").hidden_se(("hidden", "A", "B"), 0)["delay"]
    s = scored("015-hidden-stock", "counts-short", delay=10.0 + 3.5 * se)
    assert s["status"] == "fail"
    assert scored("015-hidden-stock", "counts-short", k_in=0.3)["status"] == "fail"


def test_a_wrong_structure_never_passes():
    for variant in ("counts-short", "counts-long"):
        s = scored("015-hidden-stock", variant, plain=True)
        assert s["status"] == "fail"
        assert not next(p for p in s["parts"] if p["kind"] == "hidden")["found"]
