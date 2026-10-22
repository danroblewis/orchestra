# sindy's copy of tests/test_engine_forms_tidy.py at 2bca23f (port-sindy, 2026-10-22): the same checks on sindy's copy.
"""engine_forms/tidy.py: a term carrying a float-floor share of its flow is dropped (k8s-307)."""

from sdlab.discovery.strategies.sindy import tidy


def test_negligible_terms_dropped_and_real_ones_kept():
    run = {"t": list(range(4)), "levels": {"a": [1, 2, 3, 4], "b": [10, 9, 8, 7], "c": [5, 5, 6, 6]}}
    opts = {"inputs": {"u": [100, 200, 300, 400]}}
    r = {"flows": [
        {"from": None, "to": "c", "rate": {"form": "linear", "c": 0.0, "terms": [
            {"stock": "a", "k": 1.25}, {"stock": "b", "k": 20.0}, {"stock": "u", "k": -1e-7}]}},
        {"from": "c", "to": None, "rate": {"form": "linear", "c": 1e-9, "terms": [
            {"stock": "c", "k": 0.5}, {"stock": "u", "k": 9.5e-8}]}},
        {"from": "a", "to": None, "rate": {"form": "linear", "c": 0.0, "terms": [
            {"stock": "a", "k": 0.5}, {"stock": "u", "k": 0.01}]}},
    ]}
    out = tidy.apply(r, run, opts)["flows"]
    assert [t["stock"] for t in out[0]["rate"]["terms"]] == ["a", "b"]
    assert out[1]["rate"] == {"form": "proportional", "stock": "c", "k": 0.5}
    assert out[2]["rate"] == r["flows"][2]["rate"]          # a real term (u carries 8 of a's 10) is kept
