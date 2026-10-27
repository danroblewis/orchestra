"""The sources rig's acceptance (docs/proposals/time-series-sources.md §10), against the rig's real
VictoriaMetrics behind its bearer proxy. Runs when the rig is up (``tests/sources/rig/rig.sh
start``) and ``ORCHESTRA_SOURCES_RIG`` names its directory (``~/.orchestra-sources-rig``)."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import project, source_toml

from orchestra.metrics import for_project
from orchestra.sd.rediscover import aligned, rediscover
from orchestra.sd.store import ModelStore
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.fetch import read as read_definition
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.schema import read
from orchestra.sources.spec import load
from orchestra.sources.views import Definition
from orchestra.web.dynamics import model_view

RIG = os.environ.get("ORCHESTRA_SOURCES_RIG")
PROXY = os.environ.get("ORCHESTRA_SOURCES_RIG_URL", "http://127.0.0.1:8432")
VM = os.environ.get("ORCHESTRA_SOURCES_RIG_VM", "http://127.0.0.1:8431")
pytestmark = pytest.mark.skipif(not RIG, reason="set ORCHESTRA_SOURCES_RIG to the rig's directory (tests/sources/rig/rig.sh start)")
HERE = Path(__file__).parent
LABELS = {"service": ["service", "app", "k8s_app"], "region": ["region", "zone", "location"], "pod": ["pod", "pod_name", "kubernetes_pod_name"]}


def rig_dir() -> Path:
    return Path(RIG).expanduser()


def token_file() -> str:
    return str(rig_dir() / "token")


def spec(tmp_path, **kw):
    s = load({"sources": [{"name": "rig", "url": PROXY, "machine": "service", "labels": LABELS,
                           "auth": {"bearer_file": token_file()}, **kw}]}, tmp_path)
    assert not s.refused, s.refused
    return s.sources[0]


def window(hours: float = 4.0) -> tuple[float, float]:
    now = time.time()
    return aligned(now - hours * 3600, now - 120, 60.0)           # the last two minutes may not be written yet


def test_three_spellings_group_under_service_region_and_pod(tmp_path):
    s = spec(tmp_path)
    start, end = window()
    fams = {f.name: f for f in read(PrometheusSource(s), s, start, end).families}
    for name in ("http_request_duration_seconds", "app_latency_seconds", "k8s_request_latency"):
        assert {c: i.role for c, i in fams[name].labels.items()} == {"service": "constant", "region": "grouping", "pod": "identity"}
    assert fams["http_requests_inflight:sum"].rollup["fn"] == "sum"


def test_pods_per_service_and_region_match_the_ground_truth_within_one_reporting_interval(tmp_path):
    s = spec(tmp_path)
    lines = [json.loads(line) for line in (rig_dir() / "ground_truth.jsonl").read_text().splitlines()]
    start, end = window(max(4.0, (time.time() - lines[0]["t"]) / 3600))      # the whole backfill: its region outage too
    truth = {t["t"]: t["cells"] for t in lines if start <= t["t"] <= end}
    src = PrometheusSource(s)
    queries = {"checkout": 'count by (service, region) (last_over_time(http_request_duration_seconds{stat="p50"}[91s]))',
               "search": "count by (app, zone) (last_over_time(app_latency_seconds_p50[91s]))",
               "authz": 'count by (k8s_app, location) (last_over_time(k8s_request_latency{statistic="p50"}[91s]))'}
    rename = {"app": "service", "zone": "region", "k8s_app": "service", "location": "region"}
    read = {}
    for service, q in queries.items():
        d = Definition(id=service, source="rig", name=f"{service}_pods", family=service, view="count", kind="level", query=q,
                       rename=rename, resolution_s=60.0)
        for _, labels, pts, _ in read_definition(src, d, "rig", None, start, end, 60.0):
            read[f"{service}/{labels['region']}"] = dict(pts)
    checked = exact = zero = 0
    for t, cells in truth.items():                      # every cell of the truth, so a minute with no pods is checked too
        for key, cell in cells.items():
            v = read.get(key, {}).get(t)
            assert v is not None, (key, t, cell)
            checked += 1
            zero += cell["pods"] == 0
            # a pod is counted until a reporting interval after its last sample: the pods gone this minute still count
            assert cell["pods"] <= v <= cell["pods"] + cell["gone"], (key, t, v, cell)
            exact += v == cell["pods"] + cell["gone"]
    assert checked > 500 and exact == checked and zero > 0, (checked, exact, zero)


def test_no_latency_view_is_a_sum_and_the_cap_holds(tmp_path):
    s = spec(tmp_path, max_series=30)
    start, end = window()
    inf = infer(PrometheusSource(s), s, [], tmp_path, start, end)
    latency = [d for d in inf.kept + inf.left_out if re.search("latency|duration", d.family)]
    assert latency and not any(re.match(r"\s*sum\b", d.query) for d in latency)
    src = PrometheusSource(s)
    assert sum(len(read_definition(src, d, "rig", "service", start, end, 60.0)) for d in inf.kept) <= 30


def test_a_script_adding_a_filter_changes_every_final_query(tmp_path):
    script = tmp_path / "queries.py"
    script.write_text(f"""#!{sys.executable}
import json, re, sys
out = []
for c in json.load(sys.stdin)["candidates"]:
    q = re.sub(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(\\{{([^}}]*)\\}})?(?=\\[|$)',
               lambda m: m[1] if m[1] in ("by", "count", "max", "min", "avg", "sum", "last_over_time") else m[1] + '{{' + ((m[3] + ',') if m[3] else '') + 'env="prod"}}', c["query"])
    out.append({{"id": c["id"], "queries": [{{"name": "prod_" + c["id"], "query": q}}]}})
print(json.dumps(out))
""")
    script.chmod(0o755)
    s = spec(tmp_path, transform={"queries": "queries.py"})
    start, end = window(1.0)
    inf = infer(PrometheusSource(s), s, [], tmp_path, start, end)
    every = inf.kept + [d for d in inf.left_out if not d.why.startswith("dropped")]
    assert every and all('env="prod"' in d.query for d in every), [d.query for d in every if 'env="prod"' not in d.query][:3]
    assert all(d.origin[-1].startswith("rewritten by queries.py@") for d in every)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_the_model_holds_pods_and_an_outage_keeps_the_last_version_with_the_reason(tmp_path, monkeypatch):
    port = _free_port()
    proxy = subprocess.Popen([sys.executable, str(HERE / "rig" / "proxy.py"), "--listen", f"127.0.0.1:{port}", "--to", VM,
                              "--token-file", token_file()], stderr=subprocess.PIPE)
    try:
        time.sleep(0.5)
        toml = source_toml(f"http://127.0.0.1:{port}", auth=f'auth = {{ bearer_file = "{token_file()}" }}', window="360m")
        p = project(tmp_path, monkeypatch, toml)
        first = rediscover(p, for_project(p))
        pods = [st for st in first.model.stocks if st.series and st.series.name.endswith("_pods") and "region" not in st.series.labels]
        assert first.version == 1 and {st.series.labels["service"] for st in pods} == {"checkout", "search", "authz"}
        assert all(st.unit == "pods" and st.series.source == "rig" for st in pods)
        proxy.terminate()
        proxy.wait(10)
        down = rediscover(p, for_project(p))
        assert down.version is None and "rig" in down.model.discovery["not_saved"]
        assert ModelStore.for_state(p.state_dir).current_version() == 1
        secret = Path(token_file()).read_text().strip()
        seen = [(p.repo_root / "orchestra.toml").read_text(), json.dumps(model_view(p)),
                *(f.read_text() for f in p.state_dir.rglob("*") if f.is_file() and f.suffix in (".json", ".log", ".jsonl"))]
        out = subprocess.run([sys.executable, "-m", "orchestra", "--repo", str(p.repo_root), "sources", "check"], check=True, capture_output=True, text=True)
        assert "rig: prometheus" in out.stdout and "DOES NOT ANSWER" in out.stdout
        assert not any(secret in x for x in [*seen, out.stdout, out.stderr])
        reading = Catalogue(p, for_project(p)).read(*window(0.5), 60.0)
        assert "rig" in reading.missing
    finally:
        proxy.kill()
        proxy.wait(10)
