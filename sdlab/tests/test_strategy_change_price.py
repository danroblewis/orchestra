"""Experiment change_price (docs/DISCOVERY-EXPERIMENTS.md): pieces of outside inflow must not stand in
for a stock's own dynamics, while a real intake that changes every 30 steps is still found.

One synthetic chain: an inbox fed by an intake that changes every 30 steps (5, 9, 3, 6 a step), then
inbox -> b (0.3), b -> c (0.2), c -> outside (0.2). c has no outside inflow.

- matrix: c gets 9 chance pieces of outside inflow (the fine first pass, at half the usual price,
  finds them in noise; fitted beside short pieces its numbers drift: b -> c 0.229, drain 0.212),
  and the inbox's intake is found in 62 pieces.
- change_price: before any piece can bias a row, a stock gets pieces only if, beside the levels
  alone, an outside inflow beats none or a change survives the textbook price (2 x log n x the
  long-run noise variance). c gets none (b -> c 0.203, drain 0.201); the inbox keeps its 62.
"""

from __future__ import annotations

import numpy as np
import pytest
from synth import generate

from sdlab.discovery.pricing import noise_variance, prune, scan
from sdlab.discovery.identify import identify as main_line  # the pinned main line (the matrix strategy earns its pieces since docs/research/k8s-302.md)
from sdlab.discovery.strategies import load

P = lambda a, b, k: {"id": f"{a}_{b}", "from": a, "to": b, "rate": {"form": "proportional", "stock": a, "k": k}}  # noqa: E731
INTAKE = {"every": 120, "changes": [{"t": t, "set": {"intake": {"form": "constant", "value": v}}} for t, v in ((1, 5), (31, 9), (61, 3), (91, 6))]}


@pytest.fixture(scope="module")
def chain():
    return generate(stocks=[{"id": "inbox", "initial": 30}, {"id": "b", "initial": 40}, {"id": "c", "initial": 50}],
                    flows=[{"id": "intake", "from": None, "to": "inbox", "rate": {"form": "constant", "value": 5}},
                           P("inbox", "b", 0.3), P("b", "c", 0.2), {"id": "c_out", "from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.2}}],
                    steps=2000, schedule=INTAKE)


def row(r, sid):
    return next(x for x in r["matrix"] if x["id"] == sid)


def test_an_internal_stock_gets_no_pieces_and_the_real_intake_keeps_its_own(chain):
    base = main_line(chain["stocks"], chain["run"], {"eras": chain["eras"]})
    r = load("change_price")(chain["stocks"], chain["run"], {"eras": chain["eras"]})
    # matrix: chance pieces in the internal stock, which pull its numbers off
    assert len(row(base, "c")["inflow"]) > 1
    # change_price: none, and its numbers are the truth's
    c = row(r, "c")
    assert len(c["inflow"]) <= 1 and abs(c["coef"]["b"] - 0.2) <= 0.01 and abs(c["coef"]["c"] + 0.2) <= 0.01
    # the intake still changes (about every 30 steps: 66 changes in 2000) and the inbox drains at 0.3
    inbox = row(r, "inbox")
    assert len(inbox["inflow"]) >= 40 and abs(inbox["coef"]["inbox"] + 0.3) <= 0.02
    assert len(inbox["inflow"]) == len(row(base, "inbox")["inflow"])


def test_the_long_run_variance_grows_with_autocorrelation_and_differences_shrink():
    rng = np.random.default_rng(3)
    e = rng.normal(0, 1, 4000)
    ar = np.zeros_like(e)
    for i in range(1, len(e)):
        ar[i] = 0.6 * ar[i - 1] + e[i]                    # marginal variance 1.5625, long-run 6.25
    assert noise_variance(ar, "diff") < 1.0 < 5 < noise_variance(ar, "long") < 8
    assert abs(noise_variance(e, "long") - 1) < 0.15 and abs(noise_variance(e, "diff") - 1) < 0.1


def test_at_the_textbook_price_no_chance_changes_in_plain_noise_and_pruning_keeps_the_optimum():
    rng = np.random.default_rng(1)
    r = np.concatenate([rng.normal(m, 1, 200) for m in (5, 9, 3, 6)])
    assert scan(r, 5, 2) == [0, 200, 400, 600, 800]
    noise = rng.normal(5, 1, 3000)
    assert scan(noise, 5, 2) == [0, 3000]
    cuts = scan(r, 5, 1)
    assert prune(r, cuts, 1 * np.log(800) * noise_variance(r)) == cuts   # PELT's optimum: every change pays alone
