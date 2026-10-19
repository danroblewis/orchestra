"""The combined strategy (sdlab/discovery/strategies/combined): its judge prices what a candidate
writes down, prefers the true equations to wrong ones on the ladder's data, follows unmeasured
stocks, floors and caps as the engine does, and the strategy picks the specialist that recovers the
truth where only one does.

The full judge sanity study (every case and variant, the truth with its numbers fitted against every
specialist's stored model) is run with `uv run python tests/test_ladder_combined.py`."""

import copy
import math
import sys

import pytest

from sdlab.discovery.strategies import combined
from sdlab.discovery.strategies.combined import judge as J
from sdlab.discovery.strategies.combined.params import inflow_numbers, numbers
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def truth_flows(model, d):
    """The truth over the run as a found model would write it: an unannounced schedule of an outside
    constant as inflow pieces, other changes as byTime."""
    out = []
    for f in truth_by_time(model, d["t"])[0]:
        segs = f.get("byTime") or []
        g = {k: v for k, v in f.items() if k != "byTime"}
        if len({repr(s["rate"]) for s in segs}) <= 1:
            out.append(g)
        elif all((s["rate"] or {}).get("form") == "constant" for s in segs):
            out.append({**g, "inflow": [{"from": s["from"], "to": s["to"], "value": s["rate"]["value"]} for s in segs]})
        else:
            out.append(f)
    return out


def cell(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    stocks = casemod.page_stocks(model)
    inj = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d.get("injections") or []] or None
    run = {"t": d["t"], "levels": d["levels"]}
    return c, model, d, stocks, run, J.Data(stocks, run, inj, d.get("inputs"))


def hidden_starts(model):
    return {s["id"]: s.get("initial", 0) for s in model["stocks"] if s.get("measured") is False}


def by_id(flows, fid):
    return next(f for f in flows if f.get("id") == fid)


# ---- what a candidate writes down ----

def test_inflow_pieces_cost_a_value_and_a_place_each_and_a_repeating_profile_its_period_once():
    plain = [{"from": 2, "to": 100, "value": 3.0}, {"from": 101, "to": 200, "value": 7.0}, {"from": 201, "to": 300, "value": 3.0}]
    assert inflow_numbers(plain) == 2 + 2                     # two distinct values, two places
    day = [{"from": 2 + 24 * i + o, "to": 0, "value": v} for i in range(20) for o, v in ((0, 5.0), (7, 30.0), (17, 10.0))]
    assert inflow_numbers(day) == 3 + 3 + 1                   # three values, three places a period, the period
    assert inflow_numbers([{"from": 2, "to": 300, "value": 4.0}]) == 1


def test_numbers_count_rates_effects_coflows_and_unmeasured_stocks():
    flows = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 2}},
             {"from": "A", "to": "H", "rate": {"form": "proportional", "stock": "A", "k": 0.2}},
             {"from": "H", "to": "B", "rate": {"form": "proportional", "stock": "H", "k": 0.1},
              "effects": [{"stock": "C", "shape": "table", "points": [[0, 1], [10, 2]]}], "uses": [{"stock": "C", "per": 0.5}]}]
    # 3 flows + 3 rate numbers + 4 effect numbers + 1 co-flow + 1 unmeasured stock
    assert numbers(flows, {"A", "B", "C"}) == 3 + 3 + 4 + 1 + 1


# ---- the judge on the ladder's data ----

@pytest.mark.parametrize("case_id,variant", [("003-chain-2", "counts-long"), ("003-chain-2", "none-short"),
                                             ("016-coflow", "counts-long"), ("024-floor-binds", "none-short"),
                                             ("025-runs-empty", "counts-long")])
def test_the_truth_beats_its_own_numbers_put_wrong(case_id, variant):
    _, model, d, _, _, D = cell(case_id, variant)
    truth = truth_flows(model, d)
    best = J.score(truth, D)["bic"]
    for i, f in enumerate(truth):
        r = f.get("rate") or {}
        if f.get("inflow") or f.get("byTime"):
            continue
        for key in ("k", "value", "c"):
            if isinstance(r.get(key), (int, float)) and r[key]:
                wrong = copy.deepcopy(truth)
                wrong[i]["rate"][key] = r[key] * 1.15
                assert J.score(wrong, D)["bic"] > best, (i, key)


def test_noise_free_truth_fits_to_the_data_s_rounding():
    _, model, d, _, _, D = cell("013-merge", "none-long")
    assert not D.counts and D.q == 1e-4
    assert J.misfit(truth_flows(model, d), D) < 0.5           # within ~3x the rounding


def test_a_link_read_as_a_move_is_told_apart_by_the_counting_noise():
    """Same means, different covariance: the move's draw leaves B as it reaches A."""
    _, model, d, _, _, D = cell("007-link", "counts-long")
    truth = truth_flows(model, d)
    link = next(f for f in truth if not f.get("from") and (f.get("rate") or {}).get("form") == "proportional")
    as_move = [f for f in truth if f is not link] + [{**link, "from": link["rate"]["stock"]}]
    # a move from the stock it reads also drains it: give that stock back its own loss
    src = link["rate"]["stock"]
    as_move = [({**f, "rate": {**f["rate"], "k": f["rate"]["k"] - link["rate"]["k"]}}
                if f.get("from") == src and not f.get("to") and (f.get("rate") or {}).get("form") == "proportional" else f)
               for f in as_move]
    assert J.score(truth, D)["nll"] < J.score(as_move, D)["nll"]


def test_an_unmeasured_stock_is_followed_open_loop_and_beats_a_straight_move():
    _, model, d, _, _, D = cell("015-hidden-stock", "none-short")
    truth = truth_flows(model, d)
    s_truth = J.score(truth, D, starts=hidden_starts(model))
    straight = [f for f in truth if "H" not in (f.get("from"), f.get("to"))]
    straight.append({"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.2}})
    assert s_truth["bic"] < J.score(straight, D)["bic"] - 100
    assert J.misfit(truth, D) < 0.5


def test_a_via_delay_is_an_unmeasured_stock():
    _, model, d, _, _, D = cell("015-hidden-stock", "none-short")
    truth = truth_flows(model, d)
    via = [f for f in truth if "H" not in (f.get("from"), f.get("to"))]
    via.append({"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.2}, "via": {"delay": 10}})
    assert J.misfit(via, D) < 0.5


def test_rounded_numbers_are_refitted_to_the_data_s_precision():
    from sdlab.discovery.strategies.combined.refit import refit
    _, model, d, _, _, D = cell("012-rework", "none-long")
    truth = truth_flows(model, d)
    rounded = copy.deepcopy(truth)
    for f in rounded:
        r = f.get("rate") or {}
        for key in ("k", "value", "c"):
            if isinstance(r.get(key), (int, float)):
                r[key] = float(f"{r[key] * 1.01:.3g}")
        for x in r.get("terms") or []:
            x["k"] = float(f"{x['k'] * 1.01:.3g}")
    assert J.misfit(rounded, D) > 1
    again = refit(rounded, D)
    assert J.misfit(again, D) < 0.5 and J.nll(again, D) < J.nll(rounded, D)


def test_behaviour_follows_unmeasured_stocks_from_their_estimate():
    _, model, d, _, _, D = cell("015-hidden-stock", "none-short")
    assert J.behaviour(truth_flows(model, d), D, {"t": d["t"], "levels": d["levels"]}) < 0.01


def test_a_candidate_that_runs_away_is_set_aside():
    _, model, d, stocks, run, D = cell("003-chain-2", "counts-long")
    truth = truth_flows(model, d)
    runaway = truth + [{"from": None, "to": "A", "rate": {"form": "proportional", "stock": "A", "k": 0.3}}]
    cands = [{"name": "runaway", "result": {"flows": runaway}}, {"name": "truth", "result": {"flows": truth}}]
    cfg = {**combined.DEFAULTS, "refit": False}
    assert combined.choose(cands, D, run, cfg)["name"] == "truth"
    assert cands[0]["score"]["ran_away"] and not cands[1]["score"]["ran_away"]


def test_a_flow_that_reads_a_measured_input_is_judged_and_refitted_with_it():
    from sdlab.discovery.strategies.combined.refit import refit
    _, model, d, _, run, D = cell("062-tank-fed-by-measured-pump", "none-long")
    truth = truth_flows(model, d)
    assert D.inputs and J.misfit(truth, D) < 0.5
    assert J.behaviour(truth, D, run) < 0.01
    off = copy.deepcopy(truth)
    next(f for f in off if not f.get("from"))["rate"]["k"] *= 1.1
    assert J.misfit(refit(off, D), D) < 0.5


def test_a_specialist_over_its_cap_is_stopped_and_the_rest_run(monkeypatch):
    import time
    _, _, _, stocks, run, _ = cell("002-inflow-outflow", "counts-short")

    def slow(*a, **k):
        time.sleep(30)
    monkeypatch.setitem(combined.STRATEGIES, "censored", slow)
    began = time.perf_counter()
    r = combined.identify(stocks, run, {"specialists": ["censored", "lna"], "cap": 1})
    assert time.perf_counter() - began < 20
    assert r["combined"]["chosen"] == "lna"
    assert r["combined"]["candidates"][0]["error"].startswith("capped")


def test_exact_ties_go_to_flows_that_read_their_own_stocks():
    own = [{"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.2}}]
    other = [{"from": "B", "to": None, "rate": {"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 0.2}]}}]
    assert combined.cross_reads(own) == 0 and combined.cross_reads(other) == 1


# ---- the strategy ----

@pytest.mark.parametrize("case_id,variant,specialist", [("024-floor-binds", "counts-short", "censored"),
                                                        ("015-hidden-stock", "none-short", "hidden_transit")])
def test_the_specialist_that_recovers_the_truth_is_chosen(case_id, variant, specialist):
    c, model, d, stocks, run, _ = cell(case_id, variant)
    r = combined.identify(stocks, run, {})
    assert r["combined"]["chosen"] == specialist
    s = score.score(c, casemod.variant(c, variant)["noise"], model, r["flows"], d, None, r.get("inferred_levels"))
    assert s["status"] == "pass"
    names = [x["name"] for x in r["combined"]["candidates"]]
    assert names == combined.SPECIALISTS


def test_a_specialist_that_raises_is_skipped(monkeypatch):
    _, _, _, stocks, run, _ = cell("002-inflow-outflow", "counts-short")

    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setitem(combined.STRATEGIES, "censored", boom)
    r = combined.identify(stocks, run, {"specialists": ["censored", "lna"]})
    assert r["combined"]["chosen"] == "lna"
    assert "RuntimeError" in r["combined"]["candidates"][0]["error"]


# ---- the judge sanity study (not part of the suite: reads the ladder's result store) ----

SPECIALISTS = combined.SPECIALISTS


def sanity(price: float = 1.0) -> list[dict]:
    """For every case and variant in the store: the truth (its numbers fitted by the judge's own
    likelihood, starting at the truth) against every specialist's latest model that does not pass,
    its numbers refitted as the strategy refits them.
    A row for each wrong model the judge scores better than the truth."""
    from collections import defaultdict

    from sdlab.discovery.strategies.combined.refit import refit
    from sdlab.ladder import store
    by = defaultdict(dict)
    for s in SPECIALISTS:
        for r in store.latest(strategy=s, found=True):
            by[(r["case"], r["variant"])][s] = r
    rows = []
    for (case_id, variant), res in sorted(by.items()):
        try:
            _, model, d, _, _, D = cell(case_id, variant)
        except (KeyError, ValueError, FileNotFoundError):
            continue
        _, model, d, _, _, D = cell(case_id, variant)
        tf = fit(truth_flows(model, d), D, hidden_starts(model))
        t = J.score(tf, D, price, 0.0, hidden_starts(model))
        for s, r in res.items():
            if r["status"] == "pass" or r.get("found") is None:
                continue
            w = J.score(r["found"], D, price, 0.0)
            again = refit(r["found"], D, J.weights(r["found"], D))
            if again:
                w2 = J.score(again, D, price, 0.0)
                w = w2 if w2["nll"] < w["nll"] else w
            if w["bic"] < t["bic"]:
                rows.append({"case": case_id, "variant": variant, "wrong": s, "status": r["status"], "by": round(t["bic"] - w["bic"], 1),
                             "truth_nll": round(t["nll"], 1), "truth_k": t["k"], "wrong_nll": round(w["nll"], 1), "wrong_k": w["k"]})
    return rows


def fit(flows: list[dict], D: J.Data, starts: dict, most: int = 40) -> list[dict]:
    """The truth's numbers refitted by the judge's likelihood (Powell, from the truth), so it is
    compared with fitted candidates on equal terms; left as it is with more than `most` numbers."""
    import numpy as np
    from scipy.optimize import minimize

    flows = copy.deepcopy(flows)
    paths = []
    for i, f in enumerate(flows):
        rates = [(f.get("rate") or {}, [i, "rate"])] if not f.get("byTime") else [(g["rate"], [i, "byTime", j, "rate"]) for j, g in enumerate(f["byTime"])]
        if f.get("inflow"):                                 # equal values stay one number (a repeating schedule)
            groups: dict = {}
            for j, g in enumerate(f["inflow"]):
                groups.setdefault(g["value"], []).append([i, "inflow", j, "value"])
            paths += list(groups.values())
            rates = []
        for r, base in rates:
            paths += [base + [k] for k in ("value", "k", "c", "goal", "time") if isinstance(r.get(k), (int, float))]
            paths += [base + ["terms", j, "k"] for j in range(len(r.get("terms") or []))]
        for j, e in enumerate(f.get("effects") or []):
            if e.get("points"):
                e["points"] = [list(p) for p in e["points"]]
                paths += [[i, "effects", j, "points", q, 1] for q in range(len(e["points"]))]
    if not paths or len(paths) > most:
        return flows

    paths = [p if isinstance(p[0], list) else [p] for p in paths]   # each number: the places it is written

    def at(p):
        x = flows
        for k in p[:-1]:
            x = x[k]
        return x

    x0 = np.array([float(at(p[0])[p[0][-1]]) for p in paths])
    sc = np.where(np.abs(x0) > 1e-3, x0, 1e-3)              # signed: z = 1 is the truth

    def nll(z):
        for ps, v in zip(paths, z * sc):
            for p in ps:
                at(p)[p[-1]] = float(v)
        v = J.nll(flows, D, starts)
        return v if math.isfinite(v) else 1e12

    one = np.ones_like(x0)
    base = nll(one)
    res = minimize(nll, one, method="Powell", options={"maxfev": 200 * len(paths), "xtol": 1e-6, "ftol": 1e-10})
    if nll(res.x) > base:                                   # keep the truth's own numbers unless the fit is better
        nll(one)
    return flows


if __name__ == "__main__":
    price = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    rows = sanity(price)
    for r in rows:
        print(r)
    print(f"{len(rows)} wrong models scored better than the fitted truth")
