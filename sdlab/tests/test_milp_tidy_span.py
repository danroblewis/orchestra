"""regress-milp: tidy's refit fits a flow on every row it touches. Two drains of one stock into two counters
(inflight -> responses 0.5, inflight -> errors 0.03) were refitted on the inflight and retries rows alone when
the spurious move retries -> inflight was dropped: one column twice, and least squares split the sum evenly
(0.263 each; 306/307 counts-long)."""

import numpy as np

from sdlab.discovery.strategies.milp import tidy


def _model(n=400):
    rng = np.random.default_rng(3)
    traffic = 100.0 + 40.0 * np.sin(np.arange(n) / 20.0)
    inflight, retries, resp, err = (np.zeros(n) for _ in range(4))
    inflight[0], retries[0] = 100.0, 10.0
    for i in range(n - 1):
        out_r, out_e, back = 0.5 * inflight[i], 0.03 * inflight[i], 0.04 * inflight[i]
        inflight[i + 1] = inflight[i] + traffic[i] + 0.6 * retries[i] - out_r - out_e - back
        retries[i + 1] = retries[i] + back - 0.6 * retries[i] - 0.4 * retries[i]
        resp[i + 1], err[i + 1] = resp[i] + out_r, err[i] + out_e
    noise = lambda x: list(x + rng.normal(0, 1e-3, n))  # noqa: E731
    stocks = [{"id": "inflight", "unit": "requests"}, {"id": "retries", "unit": "requests"},
              {"id": "responses_total", "unit": "requests"}, {"id": "errors_total", "unit": "requests"},
              {"id": "traffic", "unit": "requests"}]
    run = {"t": list(range(n)), "levels": {"inflight": noise(inflight), "retries": noise(retries), "responses_total": noise(resp),
                                           "errors_total": noise(err), "traffic": list(traffic)},
           "boundary": {"inflight": {"in": ["estimate"]}, "retries": {"out": ["estimate"]}}, "boundary_declared": True}
    return stocks, run


def _p(src, dst, stock, k):
    return {"from": src, "to": dst, "ratio": 1, "rate": {"form": "proportional", "stock": stock, "k": k}}


def test_dropped_move_leaves_the_counters_drains_their_own():
    stocks, run = _model()
    answer = [_p("inflight", "responses_total", "inflight", 0.5), _p("inflight", "errors_total", "inflight", 0.03),
              _p(None, "inflight", "traffic", 1.0), _p("retries", "inflight", "retries", 0.55),
              _p("inflight", "retries", "inflight", 0.04), _p("retries", None, "retries", 0.4),
              _p("retries", "inflight", "retries", 0.05)]                          # a duplicate stand-in move
    for n, f in enumerate(answer):
        f["id"] = f"t{n}"
    flows, _ = tidy.refine(answer, stocks, run, {})
    k = {(f["from"], f["to"]): f["rate"].get("k") for f in flows if f["rate"].get("form") == "proportional"}
    assert abs(k[("inflight", "responses_total")] - 0.5) < 0.01
    assert abs(k[("inflight", "errors_total")] - 0.03) < 0.005
