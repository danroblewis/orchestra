"""Recession drains (docs/research/recession-drains.md): a stock's drain fitted on the steps where its
outside inflow stops, and the inflow measured with that drain fixed.

The smallest model where the main line fails: an inbox whose intake comes in short bursts (3 steps of
15, 10 or 20, unannounced) followed by 12 quiet steps, draining 0.1 a step into `working`, which drains
0.2. The bursts are shorter than the change scan's shortest piece (5 steps), so the main line's pieces
straddle bursts and quiet steps and the inbox row comes out with its own drain at ~0.36 and a spurious
term in `working` (skill@20 below 0). On the quiet steps the inbox simply decays, and the recession
reads 0.1 off them.
"""

from __future__ import annotations

import pytest
from synth import generate, skill

from sdlab.discovery.recession import quiet_steps
from sdlab.discovery.strategies import load


def bursts(seed: int = 1, on: tuple = (15, 10, 20), on_len: int = 3, off_len: int = 12, off: float = 0, k: float = 0.1) -> dict:
    changes, per = [], on_len + off_len
    for i, v in enumerate(on):
        changes.append({"t": 1 + per * i, "label": f"burst {i}", "set": {"arrive": {"form": "constant", "value": v}}})
        changes.append({"t": 1 + on_len + per * i, "label": f"quiet {i}", "set": {"arrive": {"form": "constant", "value": off}}})
    return generate(stocks=[{"id": "inbox", "initial": 20}, {"id": "working", "initial": 10}],
                    flows=[{"id": "arrive", "from": None, "to": "inbox", "rate": {"form": "constant", "value": on[0]}},
                           {"id": "start", "from": "inbox", "to": "working", "rate": {"form": "proportional", "stock": "inbox", "k": k}},
                           {"id": "finish", "from": "working", "to": None, "rate": {"form": "proportional", "stock": "working", "k": 0.2}}],
                    steps=600, schedule={"every": per * len(on), "changes": changes}, seed=seed)


def drain(r: dict, stock: str) -> float:
    """What the found model takes out of a stock per unit of its level (moves, outflows, and links
    reading it out of nothing are not counted)."""
    return sum(f["rate"]["k"] for f in r["flows"] if f.get("from") == stock and not f.get("driver") and f["rate"].get("form") == "proportional")


@pytest.mark.parametrize("seed", [1, 2])
def test_the_drain_is_read_off_the_quiet_steps_where_the_main_line_is_biased(seed):
    d = bursts(seed)
    base = load("matrix")(d["stocks"], d["run"], {})
    r = load("recession")(d["stocks"], d["run"], {})
    # the main line: the inbox drains 0.33-0.37 (truth 0.1), and runs off
    assert drain(base, "inbox") > 0.3
    assert skill(base, d) < 0
    # recession drains: within 0.02 of the truth, and the found model behaves as the truth
    assert "recession drains" in r["chosen"]
    assert abs(drain(r, "inbox") - 0.1) <= 0.02
    assert skill(r, d) > 0.95 and skill(r, d, 100) > 0.9


def test_an_intake_that_never_stops_gives_the_main_line_result():
    # 20 steps at 9, 6 or 12, then 20 at 4: the main line gets this right (drain 0.3 within 0.01)
    d = bursts(on=(9, 6, 12), on_len=20, off_len=20, off=4, k=0.3)
    base = load("matrix")(d["stocks"], d["run"], {})
    r = load("recession")(d["stocks"], d["run"], {})
    assert abs(drain(base, "inbox") - 0.3) <= 0.01
    assert r["flows"] == base["flows"] or skill(r, d) >= skill(base, d) - 0.005


def test_quiet_steps_are_where_the_unexplained_change_sits_at_its_lowest():
    import numpy as np

    rng = np.random.default_rng(1)
    on = np.tile(np.r_[np.ones(4), np.zeros(8)], 30).astype(bool)
    res = np.where(on, 12.0, 0.0) + rng.normal(0, 1.5, on.size)
    q = quiet_steps(res, trim=1)
    assert not (q & on).any()
    assert q.sum() >= 0.6 * (~on).sum()
