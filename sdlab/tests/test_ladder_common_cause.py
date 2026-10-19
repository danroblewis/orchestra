"""Strategy common_cause (docs/research/common_cause.md): independent systems recovered part by part,
with nothing invented between them.

- 032 without noise: chains 2 and 3 share an eigenvalue (C2 drains at 0.2, A3 at 0.2), so on one
  run from zero with constant inflows A3 is an exact linear combination of A2, B2, C2 and a
  constant. The matrix's stepwise BIC compares rounding errors (T log rss) and takes the first
  exact set it meets; common_cause floors rss at float precision and walks along exact ties to the
  sparsest set.
- 034/035 without noise: identical stocks are collinear; the plainest exact row (own level, no
  cross term) is chosen.
- 033 with counting noise: two chains whose inflows step together; the second chain's inflow is
  read as a link from the first chain's level unless its changes are priced at places another row
  already earned.
"""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.regression import row_sums, stepwise
from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.common_cause.exact import floored
from sdlab.discovery.strategies.common_cause.places import joint_pelt
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


def ladder(case_id: str, variant: str, strategy: str) -> tuple[dict, dict]:
    case = casemod.load(case_id)
    model = casemod.truth_model(case, variant)
    d = data.load(case, variant)
    opts = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    r = load(strategy)(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, opts)
    return r, score.equations(case, casemod.variant(case, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("case_id", ["032-three-chains-of-three", "034-identical-twins", "035-identical-twins-different-starts",
                                     "038-identical-twin-chains"])
def test_noise_free_collinear_levels(case_id):
    _, s = ladder(case_id, "none-long", "common_cause")
    assert s["status"] == "pass"


@pytest.mark.parametrize("variant", ["counts-short", "counts-long"])
def test_a_common_cause_invents_no_cross_link(variant):
    _, s = ladder("033-independent-chains-shared-driver", variant, "common_cause")
    assert s["status"] == "pass"


def test_exact_collinearity_reproduction():
    """The minimal reproduction of the 032 failure: C2's row on the noise-free long run. The shared
    stepwise (BIC on raw rss) ends with 8 columns, A3 among them; floored, with exchanges along
    exact ties, it ends with the truth, B2 and C2."""
    from sdlab.discovery import matrix

    case = casemod.load("032-three-chains-of-three")
    d = data.load(case, "none-long")
    ids = list(d["levels"])
    lv = np.array([d["levels"][i] for i in ids], dtype=float)
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    T = dy.shape[1]
    s = ids.index("C2")
    sums = row_sums(dy[s], prev, [0, T])
    plain = stepwise(sums, [], list(range(9)), np.log(T), 36)
    assert len(plain) > 2 and ids.index("A3") in plain
    with floored(float(np.mean(dy * dy))):
        got = matrix.stepwise(sums, [], list(range(9)), np.log(T), 36)
    assert sorted(ids[j] for j in got) == ["B2", "C2"]


def test_joint_places_find_shared_steps():
    rng = np.random.default_rng(1)
    u = np.r_[np.full(100, 5.0), np.full(100, 9.0), np.full(100, 3.0)]
    R = np.array([u + rng.normal(size=300), 0.6 * u + rng.normal(size=300)])
    assert joint_pelt(R, 5, 3 * np.log(300)) == [0, 100, 200, 300]
