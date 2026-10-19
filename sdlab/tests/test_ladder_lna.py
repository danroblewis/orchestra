"""The lna strategy: the counting-noise likelihood tells links from moves, co-flows from drains and
births from deaths on the ladder's noisy runs, and leaves noise-free runs to the matrix."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.strategies.lna.atoms import Atom, features, pooling, stoich, superset
from sdlab.discovery.strategies.lna.likelihood import nll
from sdlab.ladder import cases as casemod
from sdlab.ladder import data
from sdlab.ladder.runner import discover


def _run(case: str, variant: str) -> dict:
    c = casemod.load(case)
    return discover("lna", casemod.truth_model(c, variant), data.load(c, variant))


def _flows(r: dict) -> set[tuple]:
    out = set()
    for f in r["flows"]:
        rate = f["rate"]
        reads = rate.get("stock") or ",".join(t["stock"] for t in rate.get("terms") or [])
        out.add((f["from"], f["to"], reads, tuple(u["stock"] for u in f.get("uses") or [])))
    return out


def test_gradient_matches_finite_differences():
    rng = np.random.default_rng(0)
    S, T = 3, 40
    prev = rng.uniform(5, 50, (S, T))
    Y = rng.normal(0, 3, (S, T))
    atoms = superset(S, [""] * S, set(), [None] * S) + [Atom("gap", dst=0, driver=1)]
    V, Z = stoich(atoms, S), features(atoms, prev, None)
    pool, sign = pooling(atoms)
    F = len(atoms)
    x = np.concatenate([rng.uniform(0.01, 0.2, F), [1.0, 2.0, 3.0]])

    def f(x, grad=True):
        return nll(x[:F], V, Z, Y, pool=pool, sign=sign, tau=x[F:], grad=grad)

    _, g = f(x)
    num = np.array([(f(x + 1e-6 * e, False) - f(x - 1e-6 * e, False)) / 2e-6 for e in np.eye(len(x))])
    assert np.allclose(g, num, rtol=1e-4, atol=1e-4)


def test_link_read_as_link_with_counting_noise():
    r = _run("007-link", "counts-long")
    assert r["method"] == "lna"
    assert ("A", "B", "A", ()) not in _flows(r)          # no move A -> B
    assert (None, "B", "A", ()) in _flows(r)             # a link: B's inflow follows A


def test_link_loop():
    fl = _flows(_run("008-link-loop", "counts-long"))
    assert ("A", "B", "A", ()) in fl and (None, "A", "B", ()) in fl and ("B", "A", "B", ()) not in fl


def test_coflow_found_with_its_ratio():
    r = _run("016-coflow", "counts-long")
    move = next(f for f in r["flows"] if f["from"] == "A" and f["to"] == "B")
    assert [u["stock"] for u in move.get("uses") or []] == ["R"]
    assert move["uses"][0]["per"] == pytest.approx(0.5, rel=0.15)


def test_births_and_deaths_apart():
    r = _run("009-births-and-deaths", "counts-long")
    fl = _flows(r)
    assert (None, "P", "P", ()) in fl and ("P", None, "P", ()) in fl


def test_noise_free_left_to_the_matrix():
    assert _run("003-chain-2", "none-short").get("method") != "lna"


def _inputs(case: str, variant: str):
    from sdlab.discovery.identify import identify

    c = casemod.load(case)
    d = data.load(c, variant)
    stocks = casemod.page_stocks(casemod.truth_model(c, variant))
    run = {"t": d["t"], "levels": d["levels"]}
    opts = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    return stocks, run, opts, identify(stocks, run, dict(opts))


@pytest.mark.parametrize("case,variant", [("016-coflow", "counts-short"), ("019-announced-era", "counts-long"), ("020-unannounced-step", "counts-short")])
def test_identity_hooks_change_nothing(case, variant):
    import json

    from sdlab.discovery.strategies.lna.run import HOOKS, discover

    stocks, run, opts, base = _inputs(case, variant)
    identity = {
        "data": lambda prev, dy, ctx: (prev, dy),
        "atoms": lambda atoms, d, ctx: atoms,
        "before_search": lambda cur, d, ctx: cur,
        "after_search": lambda cur, d, ctx: cur,
        "flows": lambda flows, cur, d, ctx: flows,
    }
    assert set(identity) == set(HOOKS)
    plain = json.dumps(discover(stocks, run, opts, base), sort_keys=True, default=float)
    hooked = json.dumps(discover(stocks, run, opts, base, hooks=identity), sort_keys=True, default=float)
    assert plain == hooked


def test_hook_extra_column_reaches_the_atoms():
    from sdlab.discovery.strategies.lna.atoms import Atom
    from sdlab.discovery.strategies.lna.run import discover

    stocks, run, opts, base = _inputs("007-link", "counts-short")
    seen = {}

    def data_hook(prev, dy, ctx):
        ctx["names"] = ctx["ids"] + ["A2"]
        return np.vstack([prev, prev[0:1] ** 2 / 100]), dy

    def atoms_hook(atoms, d, ctx):
        return atoms + [Atom("link", dst=1, driver=2)]

    def flows_hook(flows, cur, d, ctx):
        seen["atoms"] = [a for a in cur.atoms if a.driver == 2]
        return flows

    r = discover(stocks, run, opts, base, hooks={"data": data_hook, "atoms": atoms_hook, "flows": flows_hook})
    assert r is not None and "atoms" in seen          # ran through; the column was offered (and may be pruned)
