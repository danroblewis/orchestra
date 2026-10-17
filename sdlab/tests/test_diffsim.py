"""The differentiable simulator (sdlab/discovery/diffsim.py) steps a model exactly as simulate.Model
does, with its smooth parts off, on random models with every feature Model has."""

from __future__ import annotations

import jax.numpy as jnp
import numpy as np
import pytest

from sdlab.discovery.diffsim import Sim, compile_flows, to_flows
from sdlab.discovery.simulate import Model


def random_rate(rng, ids):
    s = lambda: ids[rng.integers(len(ids))]  # noqa: E731
    form = rng.choice(["constant", "proportional", "gap", "linear"])
    if form == "constant":
        return {"form": "constant", "value": float(rng.uniform(-1, 8))}
    if form == "proportional":
        return {"form": "proportional", "stock": s(), "k": float(rng.uniform(0, 0.4))}
    if form == "gap":
        return {"form": "gap", "stock": s(), "goal": float(rng.uniform(0, 80)), "time": float(rng.uniform(1, 10))}
    return {"form": "linear", "c": float(rng.uniform(-5, 5)), "terms": [{"stock": s(), "k": float(rng.uniform(-0.2, 0.3))} for _ in range(rng.integers(1, 3))]}


def random_model(rng, ids, T):
    flows = []
    for _ in range(rng.integers(3, 9)):
        a, b = rng.choice([None, *ids], 2, replace=False)
        f = {"from": a, "to": b, "ratio": float(rng.choice([1, 1, 2]))}
        kind = rng.integers(4)
        if kind == 0:
            cuts = sorted(rng.choice(np.arange(2, T), 3, replace=False))
            spans = [(1, cuts[0] - 1), (cuts[0], cuts[1] - 1), (cuts[1], cuts[2] - 1), (cuts[2], T)]
            shared = random_rate(rng, ids)
            f["byTime"] = [{"from": int(x), "to": int(y), "rate": shared if rng.random() < 0.4 else random_rate(rng, ids)} for x, y in spans]
            f["rate"] = f["byTime"][0]["rate"]
        elif kind == 1 and a is None or kind == 1 and b is None:
            cuts = sorted(rng.choice(np.arange(2, T), 2, replace=False))
            f["inflow"] = [{"from": 1, "to": int(cuts[0]) - 1, "value": float(rng.uniform(-1, 9))},
                           {"from": int(cuts[0]), "to": int(cuts[1]) - 1, "value": float(rng.uniform(0, 9))}]
            f["rate"] = {"form": "constant", "value": 1.0}
        else:
            f["rate"] = random_rate(rng, ids)
        if rng.random() < 0.5:
            effects = []
            for _ in range(rng.integers(1, 3)):
                st = ids[rng.integers(len(ids))]
                if rng.random() < 0.5:
                    xs = np.sort(rng.uniform(0, 100, rng.integers(2, 7)))
                    effects.append({"stock": st, "shape": "table", "points": [[float(x), float(rng.uniform(-0.1, 1.5))] for x in xs]})
                else:
                    effects.append({"stock": st, "shape": "linear", "normal": float(rng.uniform(10, 80)), "max": float(rng.uniform(0.5, 2)),
                                    **({"min": float(rng.uniform(0, 0.4))} if rng.random() < 0.5 else {})})
            f["effects"] = effects
        if rng.random() < 0.4:
            f["uses"] = [{"stock": ids[rng.integers(len(ids))], "per": float(rng.uniform(0, 1.2))} for _ in range(rng.integers(1, 3))]
        flows.append(f)
    return flows


@pytest.mark.parametrize("seed", range(12))
def test_matches_the_numpy_model_on_random_models(seed):
    rng = np.random.default_rng(seed)
    ids = ["a", "b", "c", "d"][: rng.integers(2, 5)]
    T, H, M = 60, 25, 40
    times = np.arange(1, T + 1, dtype=float)
    flows = random_model(rng, ids, T)
    L0 = rng.uniform(0, 100, (len(ids), M))
    starts = rng.integers(1, T - H, M)
    want = Model(flows, ids).run(L0.copy(), times[starts[None, :] - 1 + np.arange(H)[:, None]])
    spec = compile_flows(flows, ids, times)
    sim = Sim(spec)
    got = np.asarray(sim.run({k: jnp.asarray(v) for k, v in spec.params().items()}, jnp.asarray(L0), jnp.asarray(starts - 1), H))
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-7)
    # the numbers written back give the same model
    again = Model(to_flows(spec, spec.params()), ids).run(L0.copy(), times[starts[None, :] - 1 + np.arange(H)[:, None]])
    np.testing.assert_allclose(again, want, rtol=1e-9, atol=1e-7)


def test_smooth_floor_is_close_and_has_gradients():
    import jax

    flows = [{"from": "a", "to": "b", "rate": {"form": "linear", "c": -2.0, "terms": [{"stock": "a", "k": 0.3}]}}]
    spec = compile_flows(flows, ["a", "b"], np.arange(1, 11, dtype=float))
    p = {k: jnp.asarray(v) for k, v in spec.params().items()}
    L0 = jnp.array([[5.0, 50.0], [0.0, 0.0]])
    exact = Sim(spec).run(p, L0, jnp.array([0, 0]), 1)
    smooth = Sim(spec, width=np.full(1, 0.01)).run(p, L0, jnp.array([0, 0]), 1)
    np.testing.assert_allclose(smooth, exact, atol=0.01)
    g = jax.grad(lambda C: Sim(spec, width=np.full(1, 0.01)).run({**p, "C": C}, L0, jnp.array([0, 0]), 1)[1, 0])(p["C"])
    assert float(g[0, 0]) > 0      # below the floor (5 x 0.3 - 2 < 0) the smooth floor still passes a gradient
