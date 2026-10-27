# Proposal: reading other time-series stores (sources, inferred series, transformation scripts)

Status: draft, revised 2026-10-26 with the owner's answers (§12). Nothing built. `[[collect]]`
and `[[scrape]]` copy data *into* the project's store; this reads other stores where the data
lives, copying nothing. The owner: "the definitions should be inferred from the time-series
database schema, and we would have some way of writing scripts to transform the data or
transform the queries before they go out." The sibling `event-sources.md` uses the same
machinery for counted bus traffic.

## 1. Sources

A **source** is where series live: `own` (the project's metrics store) and `prometheus`
(anything answering the Prometheus HTTP query API: Prometheus, VictoriaMetrics, Thanos, Mimir,
Grafana Cloud, Google Cloud Monitoring's PromQL endpoint, and Chronosphere, the owner's work
store; public material puts Chronosphere in the M3 lineage rather than Mimir, but it speaks
PromQL over that API, which is all this needs). SQL comes later (§9).

```toml
[[sources]]
name = "work"
type = "prometheus"
url = "https://<tenant>.chronosphere.io/data/metrics"
auth = { bearer_env = "WORK_PROM_TOKEN" }   # never the secret itself (§6)
prefix = "work"                             # series work:<name>, machines work.<id>
machine = "service"                         # the canonical label that names machines
match = ['{__name__=~"http_.*|grpc_.*"}']   # what to infer from; default everything, capped
max_series = 200

[sources.labels]                            # canonical = spellings; the first a metric has wins
service = ["service", "svc", "app", "app_kubernetes_io_name", "k8s_app", "job"]
region  = ["region", "zone", "location", "cloud_region"]
pod     = ["pod", "pod_name", "kubernetes_pod_name"]

[sources.transform]
queries = "orchestra/transform/queries.py"  # any executable (§3)
data    = "orchestra/transform/data.py"     # optional
```

At start Orchestra asks which endpoints answer (`query_range`, `query`, `series`, `labels`,
`label/<n>/values`, `metadata`, `buildinfo`) and works with what it gets; `orchestra sources
check` prints it.

## 2. Series are inferred from the schema

Orchestra proposes definitions, the repository's scripts correct them, and discovery decides
what is a stock or a flow (rule 7). Run hourly by default, and cached:

1. **Read the schema:** metric names under `match`; a capped sample of each metric's label sets
   (`series`); each label's cardinality and **churn** (values that appear or vanish within the
   window); metadata type, unit and help where kept; the reporting interval, from a short raw
   fetch.
2. **Group families:** names differing only by a statistic suffix (`_max`, `_min`, `_avg`,
   `_p50`, `_p95`, `_p99`, `_count`, `_sum`, `_bucket`), or only by a label such as `stat`,
   `quantile` or `statistic`, are one family with a statistic dimension.
3. **Alias labels** to canonical names. Queries use each metric's real label; results are renamed
   on arrival, so `svc="authz"` and `app="authz"` become `service="authz"`.
4. **Classify labels:** a churning, high-cardinality label (`pod`) is an **identity** label (the
   lowest aggregate: aggregated away or counted, never kept); a stable, low-cardinality one
   (`service`, `region`) is a **grouping** label.
5. **Generate views** (§4), pass them through the query script, **rank and cap** them, and hand
   the survivors to the catalogue.

Every definition records its origin: `inferred` (from which family and view), `rewritten` (by
which script, with its content hash) or `declared` (a hand-written `[[series]]`, still allowed).

## 3. The transformation layer

Company specifics live in the target repository, never in Orchestra (D10).

- **Label aliases** (`[sources.labels]`) turn "a dozen different label names" into one table.
- **Prefix:** series are `<prefix>:<name>` and machines `<prefix>.<id>`, so a remote `authz`
  never merges with a local one. Collisions with own series, and `orchestra_` names, are refused.
- **Machines from labels:** `machine = "service"` labels each series `machine=work.<value>`; the
  label is chosen here, never guessed.
- **The query script** runs once per inference round like a `[[collect]]` command (any
  executable, repository root, a timeout; nobody imports Orchestra, D16). JSON in on standard
  input:

  ```json
  {"source": "work", "candidates": [{"id": "c17", "family": "http_latency", "stat": "p95",
    "view": "max_by", "group_by": ["service"], "kind": "level", "unit": "seconds",
    "resolution_s": 60, "labels": {"service": {"real": "svc", "cardinality": 41, "churn": 0.0}},
    "query": "max by (svc) (http_latency{stat=\"p95\"})"}]}
  ```

  JSON out on standard output: a list of `{"id", "queries": [{"name", "query", "kind"?, "unit"?,
  "labels"?}], "reason"?, "pin"?}`. An empty `queries` drops the candidate (the reason is shown);
  a candidate not mentioned is kept; `"id": null` adds a definition of the script's own. One
  script can rename, filter (add `{env="prod"}` to every selector), join families, or substitute
  a query the team already trusts.
- **The data script** (optional) does what PromQL cannot: mapping pod names to services by a
  naming rule, unit fixes. It reads fetched results as JSON lines (`name`, `labels`, `points`)
  and writes the same; over 10 MB or a non-zero exit fails those series for the round, with the
  reason. Rewriting queries is preferred: the server does the work.

## 4. Views: aggregations, and count() as a type switch

| Family | Views generated | Never |
|---|---|---|
| Counter | increments grouped by each grouping set (raw samples, reset-safe) | `sum(counter)` across restarting pods |
| Per-pod statistic (the owner's max, min, avg, p50, p95, p99 per minute) | `max by (G)` of max; `min by (G)` of min; `avg by (G)` of avg (unweighted, flagged); `max by (G)` of p95 or p99 (an upper bound, flagged) | summing latencies; an average of quantiles called a quantile |
| Histogram or summary | `_count` as a counter; `rate(_sum)` as mean in flight (Little's law); a quantile as a level | — |
| Any family | counts (below) | — |

**count() switches the type.** The owner: "we regularly use count() to basically switch types:
from latency to pod count, or latency to region count." A count of series is a **level of things
that report**, not a latency. Orchestra generates it explicitly:

- `count by (G) (last_over_time(F{stat="p50"}[R]))`: pods per G. One statistic only, so a pod's
  six statistics are not counted six times; `R` is the measured reporting interval plus half, so a
  pod that stops reporting drops out within a minute or two instead of lingering for Prometheus'
  five-minute lookback (remote-written data rarely carries staleness markers).
- `count(count by (L) (last_over_time(F[R])))`: how many distinct values of a grouping label
  (regions, clusters) report at all.

These are `kind = "level"`, with a unit named for what is counted (`pods`) and `view = "count"`
in their origin, so the drawer says "pods of authz, counted from http_latency". Pods per service
is a stock that scaling and deploys move, and may sit in a loop with latency: what the owner wants
found.

**Cap and ranking.** Families × statistics × groupings × views explode. Each candidate is scored,
and the top `max_series` series (default 200 per source, at most 12 per family) go to discovery.
Higher scores: it **moves** within the window; its label sets are **stable**; it is **small**
(series and samples, estimated from cardinalities); coarser grouping first. Candidates are taken
round-robin across families, so one family cannot take the cap. What is left out is listed with
its score and reason. A script's `"pin": true` bypasses the ranking, not the cap.

## 5. Querying, not syncing

- **Grid:** a `query` goes out as `query_range` with discovery's aligned start, end and step, so
  the remote grid is discovery's. A `select` fetches raw samples (`selector[window+1h]`), keeping
  real sample times for the point-process likelihood and liveness. Remote queries are never
  evaluated finer than a series' measured resolution.
- **Limits per source:** `max_points` (chunks under 11,000 points, joined), `max_range`,
  `concurrency`, a timeout per request and a total deadline inside rediscovery's share of
  `[discovery] every`.
- **Cache:** step-aligned chunks older than a settle age (default 10 minutes, per source) are
  cached by (source, final query, step, chunk) in `<state>/sources/cache/`; each rediscovery
  fetches only the unsettled tail. `cache = false` keeps company data off disk. A backfill older
  than the settle age is missed until the chunk expires (a day), and the Sources page says so.
- **Availability:** "external systems are as available as they intend to be." Each source is
  queried alone, with backoff; discovery runs on what arrived, records what is missing and why,
  and never saves such a run as a version, so outages neither churn versions nor delete stocks.

## 6. Semantics and secrets

**Kinds**, in order: the script's or declaration's `kind`; metadata; suffix; values (with a
"declare this" warning). A remote counter's first sample is a baseline, not events; increments
are `b − a`, or `b` after a drop. `kind = "rate"` is integrated and fitted on counts per step.
Resolution is measured and recorded per series (H1). Staleness NaNs and ±Inf are dropped.

**Auth: every common kind**, each from an environment variable or a file outside the repository;
a literal secret in `orchestra.toml`, or `user:pass@` in a URL, is refused at load.

| Kind | Fields | For |
|---|---|---|
| Bearer | `bearer_env`, `bearer_file` | Chronosphere, Grafana Cloud, most gateways |
| Header | `header = {name, value_env}`; non-secret ones inline | `API-Token`-style headers, `X-Scope-OrgID` |
| Basic | `basic = {user, password_env}` | Mimir behind a proxy |
| Command | `bearer_command = ["gcloud", "auth", "print-access-token"]`, cached until it fails | Google Cloud, SSO helpers, vault CLIs |
| OAuth2 client credentials | `oauth2 = {token_url, client_id, secret_env, scopes}` | company identity providers |
| mTLS | `client_cert`, `client_key`, `ca_file` | internal servers |
| AWS SigV4 | `sigv4 = {region, profile}`, extra `orchestra[aws]` | Amazon Managed Prometheus |

`insecure = true` is allowed and always shown red. The UI and logs show scheme, host, port, auth
kind and whether its variable or file is present; never values or headers.

## 7. Reproducibility: queries in the model, not data

A model version records per series the source, the final query, the scripts' hashes, window,
step, the server's build info, fetch time and a **fingerprint** (a hash of the returned points,
rounded). `orchestra sd verify vNNNN` re-runs the queries and says per series *same*, *changed*
(a backfill, a rewritten recording rule) or *gone* (past retention, D3). No remote data is
snapshotted; the first draft's snapshot item is dropped.

## 8. The UI

- **Sources page** (its own; rule 8 keeps Core to the bus, store and runtime record): per source,
  health, capabilities, last error, latency, points fetched and cached; the families, aliases,
  identity and grouping labels; every candidate with its view, score, fate and reason, and what
  the script did to it.
- **Dynamics:** each node's drawer names its source, final query, origin chain (inferred →
  rewritten by `queries.py@a1b2`) and resolution; nodes whose source was missing are dimmed.
- **Preview** (page and CLI): a query's fan-out and sparklines; a read (rule 9).

## 9. SQL (later)

Unchanged from the first draft: OLTP tables are polled by a `[[collect]]` recipe; history tables
and warehouses earn a SQL source (bound parameters, DuckDB first) after Prometheus is proven.

## 10. Code and tests

```
orchestra/sources/
  __init__.py   Source protocol, Result, Health, Capabilities
  spec.py       [[sources]], labels, transform, [[series]]; refusals with reasons
  auth.py       the kinds of §6
  prometheus.py query_range, raw samples, series, labels, metadata; chunks, limits
  own.py        the project's MetricsStore as a source
  schema.py     families, aliases, identity and grouping labels, reporting interval
  views.py      candidate views; count views
  transform.py  the query and data scripts
  rank.py       scores, cap, reasons
  catalogue.py  own + inferred + declared: names, prefix, provenance, routing
  cache.py      settled chunks
```

Rule 5 gains, stated in the commit: *other stores are read only through `orchestra.sources`,
never written; their cache lives in the state directory.* `rediscover` reads the catalogue
instead of the own store alone; `SeriesRef` gains optional `source`, `query`, `kind`, `origin`,
`resolution_s` and `fingerprint`, defaulting to own, so old versions load.

**Fakes and conformance:** a stdlib fake Prometheus (evaluating with `metrics/promql.py`;
injectable latency, errors, 401, resets, NaNs, missing endpoints); one suite over every source,
real servers by opt-in variable as in `tests/bus`; unit tests, including **querying equals
copying** (a fake remote yields the model the same points in the own store yield).

**The test rig** stands in for Chronosphere, since this Mac cannot reach work:
- **VictoriaMetrics** on its own port and data directory (never the bakery's 8428), behind a small
  proxy that demands a bearer token (or, in another mode, an `API-Token` header). **Mimir**
  monolithic in Docker is the opt-in second target: tenant header, query-length and series limits.
- **A generator** shaped like the owner's metric: per pod, once a minute, max, min, avg, p50, p95
  and p99 of latency over that minute. Three services spelled three ways: `service`/`region`/`pod`
  with a `stat` label; `app`/`zone`/`pod_name` with suffixes; `k8s_app`/`location`/
  `kubernetes_pod_name`. A daily load curve; latency from a queue (load per pod); pods scaled on
  p95 after a delay (a real loop); rolling deploys renaming pods; one region down for an hour.
  It backfills six hours through VictoriaMetrics' import API, then writes live (for Mimir, vmagent
  scrapes and remote-writes it), and writes a **ground-truth** file: pods per service and region
  per minute, requests, the scaling rule.
- **Acceptance:** the three spellings group under `service`, `region`, `pod`; `pod` is identity;
  pods per service equals the ground truth within one reporting interval; no latency view is a
  sum; the cap holds; a script adding `{env="prod"}` changes every final query; killing the proxy
  keeps the last version and records why; no secret in TOML, logs or API.

## 11. Phased plan

**Slice 1 (4–5 days): inferred series from a Prometheus source feed discovery.** `spec`, `auth`
(bearer, header, basic), `prometheus`, `own`, `schema`, `views`, the query script, `rank`,
`catalogue`; declared kind and counter baseline in `series.py`; `rediscover` through the
catalogue; `orchestra sources check|preview|infer`; the fake, the VictoriaMetrics rig, the tests.
*Done when* the rig's acceptance passes and the sample project's one model holds the rig's
pods-per-service levels beside its own stocks.

**Slice 2 (3 days): cheap, explained, reproducible.** Cache; resolution honoured; the data
script; fingerprints and `verify`; command, OAuth2 and mTLS auth; the Sources page and Dynamics
badges. *Done when* a second rediscovery fetches under 10% of the first's points and `verify`
reports *changed* after the generator rewrites an old hour.

**Slice 3 (3 days):** the Mimir rig, SigV4, the DuckDB SQL source.

**Limits that stay:** evaluated queries lose exact event times; inferred views are guesses;
per-pod quantiles never combine into a true service quantile; fits cannot be re-derived past
remote retention.

## 12. The owner's answers (2026-10-26), and what is open

Answered: bearer token at work, support all kinds (§6); test locally with a generator (§10);
Chronosphere (§1); definitions inferred, scripts transform queries or data (§2–3); prefix
remote metrics and machines, labels interpreted in the transformation layer (§3); per-pod
per-minute statistics and count() as a type switch (§4); queries in the model, not data (§7).

**Still open:**
1. **The metric's exact shape:** is the statistic a label or a suffix, and is there a request
   count beside it (so avg can be weighted)? A redacted `series` listing for one service settles it.
2. **What Chronosphere keeps:** do aggregation or drop rules roll pods up before storage? Does
   your tenant answer `series`, `labels` and `metadata`? Its query limits, and the token's header
   form (`Authorization: Bearer` or `API-Token`)?
3. **Where it runs at work:** which machine can reach Chronosphere, and may the cache and model
   versions of company data rest there, or is `cache = false` required (D10)?
4. **Starting scope:** a `match` list of families that matter, or everything under the cap?
