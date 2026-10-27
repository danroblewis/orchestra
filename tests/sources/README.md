# Sources: conformance, inference and the rig

`orchestra.sources` reads other time-series stores where their data lives
(`docs/proposals/time-series-sources.md`, SPEC §4.4). These tests hold it to that.

- `test_source_conformance.py`: one suite for every source. The own store (file backend) and the
  fake Prometheus (`fake_prometheus.py`, the PromQL subset over points in memory, with injectable
  tokens, mTLS, latency, failures, missing endpoints and NaNs) always run; a real server runs when
  its URLs are set (below).
- `test_source_spec.py`: credentials (every kind from a variable or a file outside the repository,
  refusals with reasons, an mTLS round trip against the fake).
- `test_source_inference.py`: families, aliases, roles, views, the query script, the cap, the
  inference cache.
- `test_source_catalogue.py`: discovery through the catalogue: provenance, declared kinds, a
  remote counter's baseline, a missing source saving no version, gaps, and querying a remote
  store giving the model copying the same points into the own store gives.
- `test_rig_acceptance.py`: the proposal's acceptance, against the rig (below).

## The rig

`rig/` stands in for a hosted store: a VictoriaMetrics of its own (container `orchestra-test-vm`,
`127.0.0.1:8431`, data in the docker volume `orchestra-test-vm-data`), a proxy that demands a
bearer token (`127.0.0.1:8432`; `RIG_PROXY_MODE=header` wants `API-Token` instead), and a
generator writing the owner's metric shape (`rig/world.py`: three services spelled three ways,
per pod per minute max/min/avg/p50/p95/p99 latency and a requests counter, pods scaled on p95
after a delay, rolling deploys, a region down for an hour, a `:sum` recording-rule rollup) with
the ground truth beside it.

```
PYTHON=$(pwd)/.venv/bin/python tests/sources/rig/rig.sh start    # fresh: six hours backfilled, then live
tests/sources/rig/rig.sh status
ORCHESTRA_SOURCES_RIG=~/.orchestra-sources-rig uv run python -m pytest tests/sources/test_rig_acceptance.py
ORCHESTRA_TEST_PROM_URL=http://127.0.0.1:8432 ORCHESTRA_TEST_PROM_TOKEN_FILE=~/.orchestra-sources-rig/token \
  ORCHESTRA_TEST_PROM_IMPORT_URL=http://127.0.0.1:8431 uv run python -m pytest tests/sources/test_source_conformance.py
tests/sources/rig/rig.sh stop                                     # stops it all and removes the container and its data
```

The token, the ground truth (`ground_truth.jsonl`: per minute and per service and region, the pods
reporting, the pods gone since the minute before, requests per second, p95), `rule.json` and the
logs are in `~/.orchestra-sources-rig` (`RIG_DIR`), outside every repository. A project reads the
rig with:

```toml
[[sources]]
name = "rig"
url = "http://127.0.0.1:8432"
auth = { bearer_file = "~/.orchestra-sources-rig/token" }
machine = "service"
[sources.labels]
service = ["service", "app", "k8s_app"]
region = ["region", "zone", "location"]
pod = ["pod", "pod_name", "kubernetes_pod_name"]
```

A count over one and a half reporting intervals still holds a pod at the minute after its last
sample, so the rig's pods per service equal the ground truth's pods plus the pods gone that minute
(the acceptance checks exactly that).
