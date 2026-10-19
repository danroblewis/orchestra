"""Strategy matrix_v2 (docs/research/matrix_v2.md): the matrix with the proposed fixes as options.

With every option off it is the matrix, flow for flow; each fix does what it was proposed for on the
smallest case that shows it.
"""

from __future__ import annotations

import json
import os

import numpy as np

from sdlab.discovery.changes import pelt
from sdlab.discovery.regression import fit_subset, row_sums
from sdlab.discovery.strategies.matrix_v2 import OPTIONS
from sdlab.discovery.strategies.matrix_v2.pieces import pool_recut, white
from sdlab.ladder import runner

OFF = {**{k: False for k in OPTIONS}, "pelt_mult": 1}


def ladder(case_id: str, variant: str, strategy: str, **opts) -> tuple[dict, dict]:
    """The strategy on a ladder cell as the ladder runs it (runner.discover), opts over its defaults."""
    item = {"case": case_id, "variant": variant, "strategy": strategy, "case_hash": "", "strategy_hash": "", "score_hash": "", "mode": "run"}
    old = os.environ.get("SDLAB_MATRIX_V2")
    os.environ["SDLAB_MATRIX_V2"] = json.dumps(opts)
    try:
        row = runner.run_item(item, 300)
    finally:
        if old is None:
            os.environ.pop("SDLAB_MATRIX_V2", None)
        else:
            os.environ["SDLAB_MATRIX_V2"] = old
    return {"flows": row.get("found") or []}, {"status": row["status"]}


def test_every_option_off_is_the_matrix():
    for case_id, variant in (("002-inflow-outflow", "counts-long"), ("019-announced-era", "counts-short"), ("062-tank-fed-by-measured-pump", "counts-long")):
        a, _ = ladder(case_id, variant, "matrix")
        b, _ = ladder(case_id, variant, "matrix_v2", **OFF)
        assert json.dumps(a["flows"], sort_keys=True) == json.dumps(b["flows"], sort_keys=True), (case_id, variant)


def test_white_residuals():
    rng = np.random.default_rng(0)
    assert white(rng.normal(size=500))
    assert not white(np.sin(np.arange(500) / 20) + 0.1 * rng.normal(size=500))


def test_pooled_pieces_recut_at_the_real_changes_and_the_drain_unbiased():
    # a stock with an inflow stepping 3 <-> 7 every 100 steps and a drain of 0.1, counting noise
    rng = np.random.default_rng(1)
    T = 2000
    u = np.where((np.arange(T) // 100) % 2 == 0, 3.0, 7.0)
    x = np.zeros(T + 1)
    x[0] = 50
    for k in range(T):
        x[k + 1] = x[k] + rng.poisson(u[k]) - rng.binomial(int(x[k]), 0.1)
    y, X = np.diff(x), x[None, :-1]
    cuts = pelt(y + 0.1 * X[0], 5, 1)                     # the pieces the matrix would cut (30 on this draw)
    pieces = fit_subset(row_sums(y, X, cuts), [0]).beta[0]
    got = pool_recut(y, X, cuts)
    assert got is not None and len(set(np.round([v for _, _, v in got["segments"]], 6))) == 2
    # the pieces' drain is 0.144 here; pooled 0.109 (the true change times give 0.111 on this draw)
    assert -pieces > 0.13 and abs(-got["beta"][0] - 0.1) < 0.012


def test_products_find_logistic_crowding_and_a_product_move():
    for case_id in ("103-canonical-logistic", "126-product-move"):
        _, s0 = ladder(case_id, "none-short", "matrix")
        _, s = ladder(case_id, "none-short", "matrix_v2", products=True)
        assert s0["status"] == "fail" and s["status"] == "pass", case_id
