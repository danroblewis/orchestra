"""drifting_drain: a drain whose rate drifts in stretches beside a constant inflow; the partition, the
counting-noise price, and the distilled case 121 (none-short)."""

import numpy as np
import pytest

from sdlab.discovery.strategies import drifting_drain
from sdlab.discovery.strategies.drifting_drain import counts, segment
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def test_partition_finds_the_stretches():
    z = np.concatenate([np.full(40, 0.1), np.full(30, 0.2), np.full(50, 0.05)])
    assert segment.partition(z, np.ones(120), 1e-6) == [(0, 40), (40, 70), (70, 120)]


def test_counts_need_whole_levels():
    assert counts.whole(np.array([[1.0, 2.0, 5.0]]))
    assert not counts.whole(np.array([[1.0, 2.5, 5.0]]))


def test_distilled_case():
    c = casemod.load("121-drifting-drain")
    model = casemod.truth_model(c, "none-short")
    d = data.load(c, "none-short")
    r = drifting_drain.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, {"eras": None})
    s = score.equations(c, "none", model, r["flows"], d)
    assert s["status"] == "pass", s["parts"]
    assert r["drifting_drain"]
