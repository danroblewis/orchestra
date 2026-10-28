"""Series inferred from a store's schema: families, aliases, identity and grouping labels, views,
the query script, and the cap. Against the fake, holding the rig's world."""

from __future__ import annotations

import json
import re
import stat as st
import sys
import time
from pathlib import Path

import pytest
from fake_prometheus import FakePrometheus
from helpers import world

from orchestra.sources.fetch import read as read_definition
from orchestra.sources.infer import infer, probe
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.rank import rank
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.transform import TransformError, apply
from orchestra.sources.views import one_count_per_thing, views

END = (int(time.time()) // 60) * 60
LABELS = {"service": ["service", "app", "k8s_app"], "region": ["region", "zone", "location"], "pod": ["pod", "pod_name", "kubernetes_pod_name"]}


def spec_for(url: str, tmp_path: Path, **kw):
    specs = load({"sources": [{"name": "rig", "url": url, "machine": "service", "labels": LABELS, **kw}]}, tmp_path)
    assert not specs.refused, specs.refused
    return specs.sources[0]


@pytest.fixture(scope="module")
def fake():
    dump, _ = world(END, 150, regions={"us-east": 1.0, "eu-west": 0.5})
    f = FakePrometheus(dump)
    yield f
    f.close()


def test_three_spellings_one_vocabulary(fake, tmp_path):
    spec = spec_for(fake.url, tmp_path)
    sch = read(PrometheusSource(spec), spec, END - 7200, END)
    fams = {f.name: f for f in sch.families}
    for name, stat_label in (("http_request_duration_seconds", "stat"), ("app_latency_seconds", None), ("k8s_request_latency", "statistic")):
        f = fams[name]
        assert f.stats == ["avg", "max", "min", "p50", "p95", "p99"] and f.stat_label == stat_label, name
        assert {c: i.role for c, i in f.labels.items()} == {"service": "constant", "region": "grouping", "pod": "identity"}, name
        assert f.resolution_s == 60.0
    assert fams["app_latency_seconds"].metrics["app_latency_seconds_p95"] == "p95"
    assert fams["k8s_request_latency"].labels["pod"].real == "kubernetes_pod_name"
    assert fams["k8s_requests_total"].kind == "counter"
    rollup = fams["http_requests_inflight:sum"]
    assert rollup.kind == "rollup" and rollup.rollup == {"of": "http_requests_inflight", "fn": "sum", "rate": False, "level": None}


def test_a_churning_label_is_identity_without_being_named(tmp_path):
    t0 = END - 7200
    dump = [("queue_depth", {"replica": f"r{i}", "zone": z}, [(t0 + 60 * k, float(k % 7)) for k in range(i * 6, i * 6 + 12)])
            for i in range(20) for z in ("a", "b")]
    f = FakePrometheus(dump)
    try:
        spec = spec_for(f.url, tmp_path, identity=[])
        fam = read(PrometheusSource(spec), spec, t0, END).families[0]
        assert fam.labels["replica"].role == "identity" and fam.labels["replica"].churn > 0.5
        assert fam.labels["region"].real == "zone" and fam.labels["region"].role == "grouping" and fam.labels["region"].churn == 0.0
    finally:
        f.close()


def test_views_never_sum_a_latency_and_count_each_thing_once(fake, tmp_path):
    spec = spec_for(fake.url, tmp_path)
    sch = read(PrometheusSource(spec), spec, END - 7200, END)
    defs = one_count_per_thing([d for f in sch.families for d in views(f, spec)], sch.families)
    latency = [d for d in defs if re.search(r"latency|duration", d.family)]
    assert latency and not any(re.match(r"\s*sum\b", d.query) for d in latency)
    assert all(d.view in ("max_by", "min_by", "avg_by", "upper_by", "count", "distinct", "starts", "stops") for d in latency)
    assert all("upper bound" in " ".join(d.flags) for d in latency if d.view == "upper_by")
    assert all("unweighted" in " ".join(d.flags) for d in latency if d.view == "avg_by")
    counts = [d for d in defs if d.view == "count"]
    assert {d.unit for d in counts} == {"pods"} and all("service" in d.group_by for d in counts)
    assert sorted(d.family for d in counts if d.group_by == ["service"]) == ["app_latency_seconds", "http_request_duration_seconds", "k8s_request_latency"]
    assert not any(d.family.endswith("_total") for d in counts)          # the requests counters' pods are the same pods
    assert any(d.view == "increments" and d.family == "app_requests_total" for d in defs)
    assert any(d.view == "rollup" and d.query.startswith("sum by (service, region)") for d in defs)


def _script(tmp_path: Path, body: str) -> str:
    p = tmp_path / "queries.py"
    p.write_text(f"#!{sys.executable}\nimport json, re, sys\ncands = json.load(sys.stdin)['candidates']\n" + body)
    p.chmod(p.stat().st_mode | st.S_IXUSR)
    return "queries.py"


def test_a_script_adding_a_filter_changes_every_final_query(fake, tmp_path):
    script = _script(tmp_path, """
out = []
for c in cands:
    q = re.sub(r'(\\b[a-zA-Z_:][a-zA-Z0-9_:]*)\\{([^}]*)\\}', lambda m: m[1] + '{' + m[2] + ',env="prod"}', c['query'])
    q = re.sub(r'(\\b[a-z][a-z0-9_:]*)(\\[|\\)|$)(?![^{]*\\})', lambda m: m[1] + ('{env="prod"}' if m[1] not in ('by', 'last_over_time', 'count', 'max', 'min', 'avg', 'sum') and '{' not in m[1] else '') + m[2], q)
    out.append({"id": c["id"], "queries": [{"name": "prod_" + re.sub('[^a-z0-9_]', '_', c['family'].lower()) + "_" + c['view'] + "_" + "_".join(c['group_by']), "query": q}]})
print(json.dumps(out))
""")
    spec = spec_for(fake.url, tmp_path, transform={"queries": script})
    sch = read(PrometheusSource(spec), spec, END - 7200, END)
    cands = [d for f in sch.families for d in views(f, spec)]
    for i, d in enumerate(cands):
        d.id = f"c{i}"
    kept, dropped, who = apply(spec, tmp_path, cands)
    assert not dropped and len(kept) == len(cands) and re.fullmatch(r"queries\.py@[0-9a-f]{8}", who)
    for d in kept:
        selectors = re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*\{[^}]*\}", d.query) or [d.query]
        assert all('env="prod"' in s for s in selectors), d.query
        assert d.origin[-1] == f"rewritten by {who}"


def test_a_script_drops_adds_and_pins(fake, tmp_path):
    script = _script(tmp_path, """
out = [{"id": c["id"], "queries": [], "reason": "not ours"} for c in cands if c["family"].startswith("k8s_")]
out.append({"id": None, "queries": [{"name": "checkout_errors", "query": "sum(rate(http_requests_total[5m]))", "kind": "rate"}], "pin": True})
print(json.dumps(out))
""")
    spec = spec_for(fake.url, tmp_path, transform={"queries": script}, max_series=12)
    inf = infer(PrometheusSource(spec), spec, [], tmp_path, END - 7200, END)
    assert not any(d.family.startswith("k8s_") for d in inf.kept)
    assert any(d.why.startswith("dropped by queries.py@") and d.why.endswith(": not ours") for d in inf.left_out)
    added = next(d for d in inf.kept if d.name == "checkout_errors")
    assert added.pin and added.kind == "rate" and added.origin[0].startswith("added by queries.py@")


@pytest.mark.parametrize("body, why", [("sys.exit(3)", "exited 3"), ("print('not json')", "not JSON"),
                                       ("print(json.dumps([{'id': 'nope', 'queries': []}]))", "no candidate")])
def test_a_failing_script_fails_the_round(fake, tmp_path, body, why):
    spec = spec_for(fake.url, tmp_path, transform={"queries": _script(tmp_path, body)})
    with pytest.raises(TransformError, match=why):
        infer(PrometheusSource(spec), spec, [], tmp_path, END - 7200, END)


def test_the_cap_holds_across_families(fake, tmp_path):
    spec = spec_for(fake.url, tmp_path, max_series=20, max_per_family=4)
    src = PrometheusSource(spec)
    sch = read(src, spec, END - 7200, END)
    cands = one_count_per_thing([d for f in sch.families for d in views(f, spec)], sch.families)
    for i, d in enumerate(cands):
        d.id = f"c{i}"
    probes = {d.id: probe(src, d, END - 7200, END) for d in cands}
    kept, left = rank(cands, spec, probes)
    assert sum(probes[d.id]["series"] for d in kept) <= 20
    per_family = {}
    for d in kept:
        per_family[d.family] = per_family.get(d.family, 0) + 1
    assert max(per_family.values()) <= 4 and len(per_family) >= 4         # round robin: no family takes the cap
    assert len(kept) + len(left) == len(cands)
    assert all(d.why for d in left) and any("did not move" in d.why for d in left)
    assert all(not probes[d.id]["series"] or probes[d.id]["moves"] or d.pin for d in kept)


def test_inference_is_cached_and_survives_a_failing_round(fake, tmp_path):
    from orchestra.sources.infer import definitions
    spec = spec_for(fake.url, tmp_path)
    src = PrometheusSource(spec)
    first = definitions(src, spec, [], tmp_path, tmp_path / "state", END - 7200, END)
    n = src.requests
    again = definitions(src, spec, [], tmp_path, tmp_path / "state", END - 7200, END)
    assert src.requests == n and [d.name for d in again.kept] == [d.name for d in first.kept]
    assert json.loads((tmp_path / "state" / "sources" / "rig.json").read_text())["source"] == "rig"
    fake.fail_status = 503
    try:
        stale = definitions(src, spec, [], tmp_path, tmp_path / "state", END - 7200, END, refresh=True)
    finally:
        fake.fail_status = None
    assert stale.error.startswith("inference failed") and [d.name for d in stale.kept] == [d.name for d in first.kept]


def test_definitions_a_script_adds_in_one_answer_each_have_their_own_id(fake, tmp_path):
    script = _script(tmp_path, """
print(json.dumps([{"id": None, "queries": [{"name": "a_total", "query": "sum(app_requests_total)", "kind": "counter"},
                                           {"name": "b_total", "query": "sum(k8s_requests_total)", "kind": "counter"}], "pin": True}]))
""")
    spec = spec_for(fake.url, tmp_path, transform={"queries": script})
    inf = infer(PrometheusSource(spec), spec, [], tmp_path, END - 7200, END)
    added = {d.name: d for d in inf.kept if d.family.startswith("script:")}
    assert set(added) == {"a_total", "b_total"} and added["a_total"].id != added["b_total"].id
    src = PrometheusSource(spec)
    for d in added.values():
        assert read_definition(src, d, "rig", "service", END - 3600, END, 60.0), d.id


def _rules_fake(names: list[str]) -> FakePrometheus:
    t0 = END - 7200
    dump = []
    for n in names:
        for region in ("a", "b"):
            lab = {"service": "checkout", "region": region} if ":" not in n or n.count(":") == 1 else {"job": "checkout"}
            if region == "b" and "job" in lab:
                continue
            dump.append((n, {**lab, **({"pod": f"{region}-1"} if ":" not in n else {})},
                         [(t0 + 60 * k, float(k if n.endswith("_total") else (k * 7 + len(n)) % 5)) for k in range(121)]))
    return FakePrometheus(dump)


@pytest.mark.parametrize("names, family, rules", [
    (["request_latency", "request_latency:avg", "request_latency:max"], "request_latency", {"avg", "max"}),
    (["request_latency:avg", "request_latency:max"], "request_latency:avg", {"avg", "max"}),
    (["job:http_requests:rate5m"], "job:http_requests:rate5m", {"rate"}),
    (["http_requests_total", "job:http_requests:rate5m"], "http_requests_total", {"rate"}),
])
def test_recording_rules_are_views_of_their_base_in_one_family(tmp_path, names, family, rules):
    f = _rules_fake(names)
    try:
        spec = spec_for(f.url, tmp_path)
        fams = read(PrometheusSource(spec), spec, END - 7200, END).families
    finally:
        f.close()
    assert [x.name for x in fams] == [family]
    fam = fams[0]
    assert set(fam.rollups) == rules
    defs = views(fam, spec)
    rolled = [d for d in defs if d.view == "rollup"]
    named = {r["metric"].replace(":", "_") if r.get("level") else f"{r['of']}_{fn}" for fn, r in fam.rollups.items()}
    assert {d.name for d in rolled} == named              # level:metric:fn by its full name: never an exporter's metric_fn
    if "rate" in rules:
        assert all(d.kind == "rate" and d.query.startswith("sum") for d in rolled)
    if fam.name == "request_latency":                     # the rules replace the base's own max and avg
        assert not any(d.view in ("max_by", "avg_by") for d in defs)


def test_a_count_and_its_turnover_are_kept_or_left_out_together(tmp_path):
    from orchestra.sources.views import Definition
    spec = spec_for("http://127.0.0.1:9", tmp_path, max_series=5)
    defs, probes = [], {}
    for group, n in (([], 2), (["region"], 1)):
        for view in ("count", "starts", "stops"):
            d = Definition(id=f"{view}{len(group)}", source="rig", name=f"pods_{view}_{len(group)}", family="lat", view=view,
                           kind="level" if view == "count" else "counter", query="x", group_by=group, counts="pod|" + "|".join(group))
            defs.append(d)
            probes[d.id] = {"series": n, "moves": True}
    kept, left = rank(defs, spec, probes)
    assert len(kept) + len(left) == 6
    assert {d.view for d in kept} == {"count", "starts", "stops"} and len({tuple(d.group_by) for d in kept}) == 1
    assert {d.view for d in left} == {"count", "starts", "stops"} and len({tuple(d.group_by) for d in left}) == 1
