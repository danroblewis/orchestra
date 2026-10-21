"""Z3 identifiability (sdlab/ladder/z3_ident.py) on tiny synthetic data: a page's view, no case files."""

from sdlab.ladder import z3_ident as zi


def _run(flows, x0, steps=80, inputs=None):
    """Levels rounded to 4 decimals, from linear flows {(from, to): (coef, column)}."""
    ids = list(x0)
    x = dict(x0)
    lv = {s: [] for s in ids}
    for i in range(steps):
        for s in ids:
            lv[s].append(round(x[s], 4))
        u = {k: v[i + 1] for k, v in (inputs or {}).items()} if i + 1 < steps else {}
        d = {s: 0.0 for s in ids}
        for (a, b), (k, col) in flows.items():
            rate = k * (1.0 if col == "1" else x[col] if col in x else u.get(col, 0.0))
            if a:
                d[a] -= rate
            if b:
                d[b] += rate
        x = {s: x[s] + d[s] for s in ids}
    return [{"id": s, "name": s} for s in ids], {"t": list(range(1, steps + 1)), "levels": lv}


def test_chain_is_identifiable_with_its_boundary():
    stocks, run = _run({(None, "A"): (20, "1"), ("A", "B"): (0.5, "A"), ("B", None): (0.2, "B")}, {"A": 0.0, "B": 0.0})
    run.update(boundary={"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}, boundary_declared=True)
    p = zi.prepare(stocks, run, {})
    assert p.decimals == 4
    r = zi.enumerate_structures(p, slack=0, budget=30)
    assert r["status"] == "identifiable" and r["k_min"] == 3
    assert zi.describe(p, r["structures"][0]).count("move A~B [A]") == 1


def test_undeclared_move_has_no_equal_size_rival_but_a_declared_none_boundary_fits_nothing():
    stocks, run = _run({(None, "A"): (20, "1"), ("A", "B"): (0.5, "A"), ("B", None): (0.2, "B")}, {"A": 0.0, "B": 0.0})
    r = zi.enumerate_structures(zi.prepare(stocks, run, {}), slack=1, budget=30)
    assert r["status"] == "identifiable"                     # the split (outflow A, inflow B) costs one term more
    assert any(len(s) == 4 for s in r["structures"])
    run.update(boundary={}, boundary_declared=True)           # declared: no outside flow anywhere
    assert zi.enumerate_structures(zi.prepare(stocks, run, {}), budget=30)["status"] == "outside the class"


def test_nonlinear_data_is_outside_the_class():
    ids = ["A"]
    x, lv = 1.0, []
    for _ in range(60):
        lv.append(round(x, 4))
        x = x + 0.1 * x * (1 - x / 50)
    run = {"t": list(range(1, 61)), "levels": {"A": lv}, "boundary": {"A": {"in": ["estimate"], "out": ["estimate"]}}, "boundary_declared": True}
    r = zi.enumerate_structures(zi.prepare([{"id": i} for i in ids], run, {}), budget=30)
    assert r["status"] == "outside the class"
