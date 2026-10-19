"""The Kubernetes ground-truth examples (sd-k8s-platform, sd-k8s-small; built by
sdlab/examples/k8s/build.py from a service catalogue): they are what the catalogue says, deterministic,
bounded over the week, and every mechanism they model actually happens in the run.
docs/research/k8s-model.md describes the model."""

import functools
import importlib.util
import json
import math
import statistics


import pytest

from sdlab.sdtruth import Truth
from sdlab.server import EXAMPLES, validate

K8S = EXAMPLES / "k8s"
IDS = {"sd-k8s-small": "small.yaml", "sd-k8s-platform": "platform.yaml"}
DAY = 1440


def build_module():
    spec = importlib.util.spec_from_file_location("k8s_build", K8S / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=None)
def truth(example: str) -> Truth:
    return Truth(EXAMPLES / example / "truth.model.json")


@functools.lru_cache(maxsize=None)
def week(example: str) -> dict:
    """The default run (a week, Monday to Sunday), shared by the tests."""
    return truth(example).run()


def total(run: dict, suffix: str) -> float:
    return sum(sum(v) for f, v in run["counters"].items() if f.endswith(suffix))


@pytest.mark.parametrize("example", IDS)
def test_the_catalogue_builds_exactly_the_committed_example(example):
    """Re-running the generator gives the same model, byte for byte (deterministic, and nobody edited
    the generated files by hand)."""
    out = build_module().build(K8S / IDS[example])
    assert json.dumps(out["truth"], indent=1) + "\n" == (EXAMPLES / example / "truth.model.json").read_text()
    assert json.dumps(out["page"], indent=1) + "\n" == (EXAMPLES / f"{example}.json").read_text()


@pytest.mark.parametrize("example", IDS)
def test_it_compiles_and_the_page_is_the_measured_stocks(example):
    page, t = json.loads((EXAMPLES / f"{example}.json").read_text()), truth(example)
    assert validate(page) == []
    assert validate({**t.model, "stocks": [{k: v for k, v in s.items() if k != "measured"} for s in t.model["stocks"]]}) == []
    assert [s["id"] for s in page["stocks"]] == t.measured_ids
    assert t.model["time_unit"] == "minute" and t.steps == 7 * DAY
    hidden = [s["id"] for s in t.model["stocks"] if s.get("measured") is False]
    assert all(s.endswith(("_lbq", "_retry", "_cpu_pod", "_cpu_slow", "_leak", "_pending", "_starting", "_terminating", "_queue"))
               or s.startswith(("provisioning_", "cpu_requested_slow_")) for s in hidden), hidden


def test_the_platform_is_large_and_the_small_one_is_its_first_rung():
    big, small = truth("sd-k8s-platform"), truth("sd-k8s-small")
    services = lambda t: [s["id"][: -len("_ready")] for s in t.model["stocks"] if s["id"].endswith("_ready")]  # noqa: E731
    assert len(services(big)) >= 30 and len(services(small)) == 5
    assert any(s["id"].endswith("_conn") for s in big.model["stocks"]) and not any(s["id"].endswith("_conn") for s in small.model["stocks"])


@pytest.mark.parametrize("example", IDS)
def test_a_run_is_deterministic(example):
    t = truth(example)
    assert t.run(steps=300) == t.run(steps=300)
    assert t.run(steps=300)["levels"] != t.run(seed=t.seed + 1, steps=300)["levels"]


@pytest.mark.parametrize("example", IDS)
def test_the_levels_stay_bounded(example):
    """A week: every level finite and never negative; replicas within the HPA's bounds, memory at most
    a little over its limit (the ceiling), node pools within their sizes, occupancy near 100% at most,
    and nothing grows without limit (the last day's peak within 3x the first weekday's)."""
    t, r = truth(example), week(example)
    L = r["levels"]
    stocks = {s["id"]: s for s in t.model["stocks"]}
    for s, v in L.items():
        assert all(math.isfinite(x) and x >= 0 for x in v), s
        if s.endswith("_desired"):
            assert max(v) <= stocks[s]["max"], s
        if s.endswith("_mem"):
            assert max(v) <= 1.2 * stocks[s]["max"] / 1.5, s                      # the limit, +20% at most in a transient
        if s.startswith("cpu_requested") or s.startswith("mem_requested"):
            assert max(v) <= 120, (s, max(v))
        if not s.endswith(("_retry", "_oom", "_leak", "_terminating", "_pending", "_starting", "_lag", "_queue")) and not s.startswith(("provisioning_", "mq_")):
            assert max(v[-DAY:]) <= 3 * max(v[DAY:2 * DAY]) + 50, (s, max(v[-DAY:]), max(v[DAY:2 * DAY]))
    for s, v in L.items():
        if s.startswith("nodes_"):
            pool = s[len("nodes_"):]
            assert 1 <= min(v) and max(v) <= 60, (pool, min(v), max(v))


@pytest.mark.parametrize("example", IDS)
def test_the_daily_and_weekly_cycle(example):
    """The traffic peaks in the afternoon and dips at night, and the weekend is quieter; the services'
    load, replicas and nodes follow it."""
    r = week(example)
    edge = r["levels"]["ingress"]
    days = [edge[d * DAY:(d + 1) * DAY] for d in range(7)]
    for d in days[:4]:                                                       # Monday to Thursday (Friday has the spike at 19:00)
        assert max(d) > 2 * min(d)
        assert 10 * 60 <= d.index(max(d)) <= 16 * 60                          # the peak around midday (12:05 without noise)
    assert days[4].index(max(days[4])) // 60 == 19                             # the campaign spike
    weekday, weekend = sum(map(sum, days[:5])) / 5, sum(map(sum, days[5:])) / 2
    assert weekend < 0.8 * weekday
    ready = r["levels"]["web_frontend_ready"]
    assert max(ready[:DAY]) >= 2 * min(ready[:DAY])
    nodes = r["levels"]["nodes_general"]
    assert max(nodes[:DAY]) > min(nodes[:DAY])


@pytest.mark.parametrize("example", IDS)
def test_every_mechanism_fires(example):
    r, t = week(example), truth(example)
    L = r["levels"]
    fires = {
        "HPA scales up": total(r, "_hpa_up"), "HPA scales down": total(r, "_hpa_down"),
        "pods created": total(r, "_create"), "pods scheduled": total(r, "_scheduled"), "pods start": total(r, "_started"),
        "pods terminate": total(r, "_gone"), "scale-down deletes ready pods": total(r, "_delete_ready"),
        "OOM kills": total(r, "_oom_kill"), "OOM-killed containers restart": total(r, "_restart"),
        "requests lost to OOM kills": total(r, "_oom_lost"), "leaks reset by kills": total(r, "_leak_oom"),
        "throttled requests time out": total(r, "_timeouts"), "5xx errors": total(r, "_errors"),
        "clients retry": total(r, "_retried"), "clients give up": total(r, "_given_up"),
        "a rolling update": total(r, "_rollout"),
        "cluster autoscaler adds nodes": total(r, "_scale_up"), "cluster autoscaler removes nodes": total(r, "_scale_down"),
        "new nodes boot": total(r, "_provision_3"), "downstream calls": total(r, "_calls_" + ("catalog" if example == "sd-k8s-small" else "orders")),
    }
    if example == "sd-k8s-platform":
        fires.update({"database queries time out": total(r, "_query_timeout"), "replica applies writes": total(r, "_apply"),
                      "workers pull messages": total(r, "_pull"), "messages published": total(r, "_produces_order_events")})
    missing = [k for k, v in fires.items() if v <= 0]
    assert not missing, missing
    # pods wait for room: some pending pods while a pool is near full
    assert any(v > 0.5 for s, v in ((s, max(v)) for s, v in L.items() if s.endswith("_pending")))
    # the node failure is an announced injection, the rolling update an announced era
    assert any(j["stock"].startswith("nodes_") and j["amount"] < 0 for j in r["injections"])
    assert any(e["label"].startswith("Rolling update") for e in r["eras"])
    # CPU throttling: some service's CPU per pod reaches its limit
    lim = {f["id"][: -len("_done")]: f["effects"][0]["points"][2][0] for f in t.model["flows"] if f["id"].endswith("_done")}
    assert any(max(L[f"{s}_cpu_pod"]) >= 0.9 * lim[s] for s in lim)


@functools.lru_cache(maxsize=None)
def five_weeks(example: str) -> dict:
    t = truth(example)
    return t.run(steps=5 * t.steps)


@pytest.mark.parametrize("example", IDS)
def test_five_weeks_stay_sane_and_keep_exercising_the_model(example):
    """tests/test_sd_examples.py's long-run checks, for these large models (five weeks instead of fifty
    times the length: ~3 minutes for the platform; five weeks so that the first and last tenths start
    on the same weekday and hour). Every level finite and never negative; everything that moved is
    accounted for (inflows - outflows + the injections, the node failures); every measured stock keeps
    moving and ranging as much in the last tenth as in the second (step spread >= 0.8x, level spread
    >= 0.5x, as there) and its last week's peak stays within 2x its first week's. The exceptions are
    the event stocks (pods restarting after an OOM kill, and stocks that change in under 2% of the
    minutes, such as a small service's replicas: a few events a week, whose spread is noise) and the
    hidden ones (retries and leaks are incident-driven: a later week's incident can be larger
    than the first week's)."""
    t, r = truth(example), five_weeks(example)
    W, L = t.steps, r["levels"]
    start = {s["id"]: s.get("initial") or 0 for s in t.model["stocks"]}
    injected = {}
    for j in r["injections"]:
        injected[j["stock"]] = injected.get(j["stock"], 0) + j["amount"]
    for s in t.stock_ids:
        v = L[s]
        assert len(v) == 5 * W and all(math.isfinite(x) and x >= 0 for x in v), s
        net = injected.get(s, 0) + sum(sum(r["counters"][f["id"]]) for f in t.model["flows"] if f.get("to") == s) \
            - sum(sum(r["counters"][f["id"]]) for f in t.model["flows"] if f.get("from") == s)
        assert abs(start[s] + net - v[-1]) < 1e-6 * max(1, abs(net)) + 1, s
    spread = lambda a: statistics.pstdev([b - x for x, b in zip(a, a[1:])])  # noqa: E731
    for s in t.measured_ids:
        if s.endswith("_oom"):
            continue
        v = L[s]
        w = len(v) // 10
        early, late = v[w:2 * w], v[-w:]
        if sum(1 for x, y in zip(early, early[1:]) if x != y) < 0.02 * w:
            continue                  # constant, or moving only now and then (a 2-3 replica service's desired replicas)
        assert spread(late) >= 0.8 * spread(early), (s, spread(late), spread(early))
        assert statistics.pstdev(late) >= 0.5 * statistics.pstdev(early), s
        assert max(v[-W:]) <= 2 * max(v[:W]) + 50, (s, max(v[-W:]), max(v[:W]))
