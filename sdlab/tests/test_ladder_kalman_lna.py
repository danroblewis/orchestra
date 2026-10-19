"""The kalman_lna strategy: the stocks as hidden states seen through noisy, missing, averaged, late,
grossly wrong or scaled reports; the filter's gradient and information, the gate that decides when
the filter is needed, and a few noisy ladder cells it recovers."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.strategies.kalman_lna import noisy
from sdlab.discovery.strategies.kalman_lna.model import Layout, Problem
from sdlab.discovery.strategies.kalman_lna.robust import gross_errors
from sdlab.discovery.strategies.kalman_lna.run import Session
from sdlab.discovery.strategies.lna.atoms import Atom, superset
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.ladder.runner import discover


def _chain(T: int = 120, seed: int = 0) -> np.ndarray:
    """A chain of two (20 in, A -> B at 0.5, B out at 0.2) with counting noise: points x stocks."""
    rng = np.random.default_rng(seed)
    x = np.zeros((T, 2))
    x[0] = [40, 100]
    for k in range(1, T):
        a, b = x[k - 1]
        mv, out = rng.poisson(0.5 * a), rng.poisson(0.2 * b)
        x[k] = [a + rng.poisson(20) - mv, b + mv - out]
    return x


def _numeric_grad(pr, atoms, args, pt, pi):
    out = []
    for k in range(len(pt)):
        def ev(h):
            a = [np.array(args[0], float), np.array(args[1], float), args[2], args[3], np.array(args[4], float)]
            slot = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}[int(pt[k])]
            if slot in (0, 1, 4):
                a[slot][pi[k]] += h
            else:
                a[slot] += h
            return pr.evaluate(atoms, *a)[0]
        h = 1e-8 if pt[k] == 3 else 1e-6
        out.append((ev(h) - ev(-h)) / (2 * h))
    return np.array(out)


@pytest.mark.parametrize("span", [1, 7])
def test_gradient_matches_finite_differences(span):
    x = _chain(T=150)
    rng = np.random.default_rng(1)
    t = np.arange(1, 151)
    keep = np.sort(np.concatenate([[0, 149], rng.choice(np.arange(1, 149), 90, replace=False)])) if span == 1 else np.arange(6, 150, 7)
    Y = x[keep] + rng.normal(0, 2, (len(keep), 2))
    if span > 1:                                  # each point the mean over the 7 steps ending there
        Y = np.array([x[k - 6: k + 1].mean(axis=0) for k in keep])
    lay = Layout(["A", "B"], t[keep], Y, span=span)
    lay.mask[3, 1] = False                        # a value left out
    pr = Problem(lay, None)
    pr.scaled = (1,)
    atoms = superset(2, ["", ""], set(), [None, None], gaps=True)
    pt, pi, _ = pr.params(atoms)
    th = rng.uniform(0.01, 0.3, len(atoms))
    th[0] = 20.0
    args = [th, np.array([1.0, 2.0]), 0.7, 0.002, np.array([1.0, 1.1])]
    v, g, info = pr.evaluate(atoms, *args, pt, pi, grad=True, info=True)
    num = _numeric_grad(pr, atoms, args, pt, pi)
    assert np.isfinite(v)
    assert np.allclose(g, num, rtol=1e-5, atol=1e-4 * np.abs(num).max())
    assert np.all(np.linalg.eigvalsh(info) > -1e-6 * np.abs(info).max())


def test_measurement_error_and_rates_recovered():
    """With every level read with 5% error, the filter's fit of the true structure reads the rates and
    the error's size (the plain one-step regression reads B's drain far too fast)."""
    x = _chain(T=1500, seed=3)
    rng = np.random.default_rng(4)
    Y = x + 0.05 * x * rng.standard_normal(x.shape)
    lay = Layout(["A", "B"], np.arange(1, 1501), Y)
    pr = Problem(lay, None)
    atoms = [Atom("in", dst=0), Atom("move", src=0, dst=1, driver=0), Atom("out", src=1, driver=1)]
    from sdlab.discovery.strategies.kalman_lna import search as S
    f = S.refit(pr, atoms, None)
    pr.refresh(f)
    f = S.refit(pr, atoms, f)
    assert f.theta == pytest.approx([20, 0.5, 0.2], rel=0.08)
    assert np.sqrt(f.rho2) == pytest.approx(0.05, rel=0.25)


def test_gross_errors_found_and_peaks_left_alone():
    x = _chain(T=300, seed=5)
    Y = x.copy()
    Y[100, 1] = 5.0                                  # a gross error
    Y[200, 0] += 60.0
    bad = gross_errors(np.arange(300), Y, np.isfinite(Y))
    assert bad[100, 1] and bad[200, 0] and bad.sum() == 2
    # a pulse that decays is not an error
    Z = x.copy()
    Z[150:, 0] += 300 * 0.5 ** np.arange(150)
    assert not gross_errors(np.arange(300), Z, np.isfinite(Z)).any()


def _evidence(Y: np.ndarray) -> dict:
    ses = Session([{"id": "A"}, {"id": "B"}], {"t": list(range(1, len(Y) + 1)), "levels": {"A": Y[:, 0].tolist(), "B": Y[:, 1].tolist()}}, {})
    assert ses.prepare()
    return ses.evidence()


def test_measurement_error_is_read_where_it_is_and_not_where_it_is_not():
    x = _chain(T=600, seed=6)
    assert not noisy(_evidence(x))                                  # counts, every step
    rng = np.random.default_rng(7)
    assert noisy(_evidence(x + 0.05 * x * rng.standard_normal(x.shape)))


def _run(case: str, variant: str) -> tuple[dict, str]:
    c = casemod.load(case)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = discover("kalman_lna", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)["status"]


@pytest.mark.parametrize("variant", ["meas-short", "gaps-short", "weekly-long"])
def test_noisy_chain(variant):
    r, status = _run("080-noisy-chain-2", variant)
    assert r["kalman"]["reading"] in ("meas", "uneven")
    assert status == "pass"


def test_reporting_delay_read_from_injections():
    r, status = _run("087-noisy-injection", "lag-short")
    assert r.get("lag") == 3
    assert status == "pass"
