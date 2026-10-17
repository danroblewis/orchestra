"""Discovery as the page asks for it (sdlab/discovery/api.py): what the page knows is subtracted
first, the result is JSON-safe, and it says what is left unexplained.

These were the page's JavaScript discovery tests (tests/sim.test.mjs, example_repair.test.mjs);
the ones about hidden stocks, alternatives and whole-model splitting went with the JavaScript
search, which the Python engine does not have."""

import json
import math
from pathlib import Path

import numpy as np

from sdlab.discovery import identify
from sdlab.discovery.api import discover, jsonable

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "tests" / "fixtures" / f"{name}-run.json").read_text())


def stocks_of(example):
    return json.loads((ROOT / "sdlab" / "examples" / f"{example}.json").read_text())["stocks"]


def known_of(moved, n):
    """The page's known change per stock and step, from its per-step accounting of measured flows."""
    k = {}
    for i, m in enumerate(moved):
        for x in (m or {}).values():
            for s, v in (x.get("made") or {}).items():
                k.setdefault(s, [0.0] * n)[i] += v
            for s, v in (x.get("took") or {}).items():
                k.setdefault(s, [0.0] * n)[i] -= v
    return k


def find(r, src, dst):
    return [f for f in r["flows"] if f["from"] == src and f["to"] == dst]


def test_with_the_measured_flows_subtracted_it_finds_what_the_model_is_missing():
    run = fixture("surprises")
    r = discover({"stocks": stocks_of("surprises"), "run": run, "eras": run["eras"], "known": known_of(run["moved"], len(run["t"]))})
    # the dog takes 0.2 loose socks a minute
    dog = find(r, "loose", None)
    assert len(dog) == 1 and abs(dog[0]["perStep"] - 0.2) < 0.05, r["flows"]
    # worn sport pairs (2% a minute) come back to the basket as two socks each: pairs and socks are
    # different units, so it is a drain of sport and a gain of the basket that follows sport's level
    wear = find(r, "sport", None)
    assert len(wear) == 1 and wear[0]["rate"]["form"] == "proportional" and abs(wear[0]["rate"]["k"] - 0.02) < 0.005, wear
    back = [f for f in find(r, None, "basket") if f.get("driver") == "sport"]
    assert len(back) == 1 and abs(back[0]["rate"]["terms"][0]["k"] - 0.04) < 0.01, back
    assert len(r["flows"]) == 3, [(f["from"], f["to"]) for f in r["flows"]]
    assert not any(u["persistent"] for u in r["unexplained"].values()), r["unexplained"]


def test_departures_and_arrivals_of_a_stock_nobody_measures_match():
    run = fixture("repair")
    r = discover({"stocks": stocks_of("repair"), "run": run, "eras": run["eras"], "known": known_of(run["moved"], len(run["t"]))})
    out, back = find(r, "intake", None), find(r, None, "ready")
    assert len(out) == 1 and out[0]["rate"]["form"] == "proportional" and abs(out[0]["rate"]["k"] - 0.1) < 0.03, out
    assert len(back) == 1 and abs(out[0]["perStep"] - back[0]["perStep"]) < 0.2 * out[0]["perStep"], "what goes out comes back"


def test_from_stock_levels_alone_the_lost_socks_follow_the_loose_ones():
    run = fixture("socks-eras")
    r = discover({"stocks": stocks_of("socks"), "run": run, "eras": run["eras"]})
    into_lost = [f for f in find(r, None, "lost") + find(r, "loose", "lost")
                 if (f["rate"].get("stock") or (f["rate"].get("terms") or [{}])[0].get("stock")) == "loose"]
    assert len(into_lost) == 1, r["flows"]
    k = into_lost[0]["rate"].get("k") or into_lost[0]["rate"]["terms"][0]["k"]
    assert abs(k - 0.01) < 0.004, k                       # 1% of loose socks a minute are lost


def test_the_result_is_json_safe_and_shaped_for_the_page():
    run = fixture("socks")
    r = discover({"stocks": stocks_of("socks"), "run": run})
    json.dumps(r, allow_nan=False)
    assert r["strategy"] == "matrix" and r["chosen"] and isinstance(r["computeMs"], int)
    for f in r["flows"]:
        assert {"from", "to", "rate", "rates", "perStep", "ratio", "nearly", "bothWays"} <= f.keys()
    assert set(r["unexplained"]) == {s["id"] for s in stocks_of("socks")}
    assert all(None if v is None else math.isfinite(v) for t in r["tried"] for v in [t["error"]])


def test_nothing_known_gives_the_engines_own_result():
    run = fixture("socks")
    stocks = stocks_of("socks")
    plain = identify(stocks, {"t": run["t"], "levels": run["levels"]}, {"eras": None})
    zero = identify(stocks, {"t": run["t"], "levels": run["levels"]}, {"eras": None, "known": {}})
    assert jsonable(plain) == jsonable(zero)


def test_jsonable_makes_numpy_plain_and_drops_inf_and_nan():
    x = jsonable({"a": np.float64(1.5), "b": np.int64(2), "c": float("inf"), "d": [np.nan, np.array([1.0, -np.inf])], "e": np.bool_(True), 3: (1, 2)})
    assert x == {"a": 1.5, "b": 2, "c": None, "d": [None, [1.0, None]], "e": True, "3": [1, 2]}
    json.dumps(x, allow_nan=False)
