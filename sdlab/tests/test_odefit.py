"""odefit (sdlab/discovery/strategies/odefit, docs/research/odefit.md): output error keeps the
couplings measurement error shrinks in a one-step fit; products only where they earn it and do not
run away; counted data go to the main line."""

import numpy as np

from sdlab.discovery.strategies.odefit import extend as E
from sdlab.discovery.strategies.odefit import fit as F
from sdlab.discovery.strategies.odefit import eiv
from sdlab.discovery.strategies.odefit.run import identify, mainline, output_error


def oscillator(n=300, noise=0.0, seed=0):
    """P' = V - 1, V' = 0.15 - 0.01 P - 0.05 V + force (a damped oscillator in offset stocks)."""
    rng = np.random.default_rng(seed)
    force = np.where((np.arange(n) % 50) < 8, 0.03, 0.0)
    X = np.zeros((n, 2))
    X[0] = [12.0, 1.0]
    for k in range(1, n):
        P, V = X[k - 1]
        X[k] = [P + V - 1, V + 0.15 - 0.01 * P - 0.05 * V + force[k]]
    Y = X + rng.normal(0, noise, X.shape)
    stocks = [{"id": "P", "unit": "m"}, {"id": "V", "unit": "m/s"}]
    run = {"t": list(range(1, n + 1)), "levels": {"P": list(Y[:, 0]), "V": list(Y[:, 1])}}
    return stocks, run, {"inputs": {"force": list(force)}}, X


def test_output_error_keeps_the_coupling_noise_shrinks():
    stocks, run, opts, _ = oscillator(noise=0.02)
    r = output_error(stocks, run, opts)
    W = np.array(r["odefit"]["W"])              # columns P, V, force, 1
    assert abs(W[1, 0] + 0.01) < 0.003          # V <- P
    assert abs(W[1, 2] - 1.0) < 0.3             # V <- force
    assert abs(W[0, 1] - 1.0) < 0.05            # P <- V


def test_noise_free_linear_system_is_exact():
    stocks, run, opts, _ = oscillator()
    W = np.array(output_error(stocks, run, opts)["odefit"]["W"])
    assert np.allclose(W[1, :3], [-0.01, -0.05, 1.0], atol=1e-4)


def test_counted_levels_go_to_the_main_line():
    stocks, run, opts, _ = oscillator()
    run = {"t": run["t"], "levels": {k: [round(100 * x) for x in v] for k, v in run["levels"].items()}}
    r = identify(stocks, run, opts)
    assert r["chosen_by"].startswith("counted")
    # odefit's main line: its earned refit (earned.py), its numbers refitted under measurement error (eiv.py)
    assert r["flows"] == eiv.apply(mainline(stocks, run, dict(opts)), stocks, run, opts)["flows"]


def test_a_square_that_turns_a_drain_into_growth_runs_away():
    n = 200
    rng = np.random.default_rng(1)
    U = 1 + rng.random((n, 1))
    d = F.Data(np.linspace(10, 30, n)[:, None], U, np.zeros((n, 1)))
    spec = F.Spec(1, 1, [(0, 0)])
    # H' = -0.1 H + pump + 0.002 H^2: a drain that turns into growth past H = 25 + (a pump beyond)
    assert E.runs_away(spec, np.array([-0.1, 1.0, 0.0, 0.002]), d)
    assert not E.runs_away(spec, np.array([-0.1, 1.0, 0.0, 0.0]), d)


def test_two_square_root_flows_in_a_cascade_are_fitted_together():
    """H1' = pump - 0.5 sqrt(H1), H2' = 0.5 sqrt(H1) - 0.4 sqrt(H2): the roots family, both curves at once."""
    n = 600
    pump = 1 + 2 * ((np.arange(n) // 75) % 2)
    X = np.zeros((n, 2))
    X[0] = [30.0, 5.0]
    for k in range(1, n):
        h1, h2 = X[k - 1]
        X[k] = [h1 + pump[k] - 0.5 * np.sqrt(h1), h2 + 0.5 * np.sqrt(h1) - 0.4 * np.sqrt(h2)]
    stocks = [{"id": "H1", "unit": "cm"}, {"id": "H2", "unit": "cm"}]
    run = {"t": list(range(1, n + 1)), "levels": {"H1": list(X[:, 0]), "H2": list(X[:, 1])}}
    r = output_error(stocks, run, {"inputs": {"pump": [float(p) for p in pump]}})
    assert r["chosen"] == "roots"
    W = np.array(r["odefit"]["W"])           # columns H1, H2, pump, 1, sqrt H1, sqrt H2
    assert np.allclose(W[:, 4:], [[-0.5, 0.0], [0.5, -0.4]], atol=0.01)
    moves = [f for f in r["flows"] if f["from"] == "H1" and f["to"] == "H2"]
    assert moves and moves[0]["effects"][0]["shape"] == "table"
