# Proposal: reading other time-series stores (sources and series definitions)

Status: draft, 2026-10-26. Nothing built. `[[collect]]` and `[[scrape]]` (being built) copy data
*into* the project's store; this reads other stores where the data lives, copying nothing. The
owner: "we just want to query it at the right times with the right time ranges"; "the target repo
can specify the data transformation patterns."

## 1. Sources and series definitions

A **source** is where series live: `own` (the project's metrics store; always there), `prometheus`
(anything speaking the Prometheus query API: Prometheus, VictoriaMetrics, Thanos, Mimir, Grafana
Cloud), later `sql` (§4). A **series definition** is a named query against one source in the
source's own language. That is the transformation layer; Orchestra invents no query language.

```toml
[[sources]]
name = "work"
type = "prometheus"
url = "https://prometheus.corp.example:9090"
auth = { bearer_env = "WORK_PROM_TOKEN" }      # never the secret itself (§5)
timeout = "30s"
concurrency = 4

[[series]]                                      # raw samples; counters summed per service, reset-safe
name = "authz_requests_total"
source = "work"
select = 'grpc_server_handled_total{service="authz"}'
by = ["service"]
kind = "counter"

[[series]]                                      # any PromQL, evaluated per step; one series per label set
name = "requests_in_flight"
source = "work"
query = 'sum by (service) (rate(grpc_request_latency_seconds_sum[1m]))'
kind = "level"
labels = { machine = "{service}" }              # label template: flows attributed to the k8s service
```

Two forms: **`select`** (a plain selector: Orchestra fetches raw samples and groups by `by`
itself, adding increments for counters) and **`query`** (any expression, evaluated by the source).
Definitions live in `orchestra.toml` or a file it names (`series_file = "orchestra/series.toml"`);
company definitions can ship as configuration in that company's plugin (D10). Nobody imports
Orchestra.

**Fan-out.** A result with several label sets yields one series per set (`count by (service)
(...)` → `name{service="authz"}`, `name{service="billing"}`, ...). `name` may be a template
(`"work_{__name__}"`) so one selector over many names fans out into many named series.
`max_series` (default 200) refuses a definition that matches more, saying how many.

**One catalogue, one model.** The catalogue is the own store's project series (as today) plus
every series the definitions yield; a remote source enters only through what is declared. Names
are one namespace: a definition colliding with an own series or starting with `orchestra_` is
refused with the reason. Sources label, never separate (rule 4): a remote stock and a local
counter can meet in one balance.

**Provenance is metadata, not a label** (`source` already means the CloudEvents emitter and
`machine_of` reads it). `SeriesRef` gains optional `source`, `query`, `kind` (with its origin)
and `resolution_s`, defaulting to own, so every stock, flow and equation input names where its
data came from and old versions still load.

## 2. Querying, not syncing

**Window and step.** Discovery's window is already aligned on multiples of the step
(`rediscover.aligned`). A `query` goes out as `query_range` with that aligned start, end and step:
Prometheus evaluates at exactly `start + k·step`, so the remote grid *is* discovery's grid (and
VictoriaMetrics, which rounds start to the step for its rollup cache, hits that cache). A `select`
is an instant query of a range selector (`selector[window+1h]`), which returns stored samples, not
evaluated ones. This matters: discovery needs real sample times (`events_of` for the
point-process likelihood, `usual_interval`/`on_events` for liveness, `between.py`); evaluated
points are stamped at grid times and carried through Prometheus' 5-minute lookback. Prefer
`select` wherever `by` can do the aggregation.

**Per-source limits:** `max_points` (Prometheus refuses over 11,000 per series; longer requests
are split into step-aligned chunks and joined), `max_range` (Mimir/Grafana Cloud cap query
length), `concurrency` (a semaphore), `timeout` per request plus a total deadline inside
rediscovery's existing share of `[discovery] every`, `max_series` per definition.

**Caching.** A past range is taken as immutable once older than a settle age (default 10 min:
late scrapes, remote-write lag). Chunks aligned on step and hour are cached by (source, query,
step, chunk) in `<state>/sources/cache/`, dropped when a definition changes, expired after a day;
`cache = false` per source. Each rediscovery then fetches only the unsettled tail. Honest limit:
VictoriaMetrics accepts backfill at any time; a backfill older than the settle age is missed until
expiry, which the Sources page states.

**Partial failure.** Each source is queried on its own; a dead one costs only its series.
Discovery runs on what arrived and records `missing: {definition: reason}`. A run with anything
missing is written as the latest discovery but **never saved as a version**, so an outage does
not churn versions or delete stocks; the Dynamics page shows the last complete version with a
banner ("work unreachable since 14:05; 3 stocks not re-read").

**The live sample's 6 h at 5 s** is 4,321 steps per series, under the 11,000 cap. Against a busy
server: `sum by (service)(rate(x[1m]))` with `x` at 30,000 series scraped every 15 s reads about
30,000 × 4 × 4,321 ≈ half a billion samples (seconds to tens of seconds of server CPU) and
returns 50 services × 4,321 points (~6 MB JSON). A raw select of 300 counters is 300 × 1,440
samples (~12 MB) once. Uncached, every 5-minute rediscovery repeats that: 12 times an hour. With
the cache, each run costs (5 min + settle)/6 h ≈ 4% of the first. And a 5 s step on a 15 s scrape
triples the cost for no information: remote queries are evaluated at the series' own resolution
(§3), never finer, and discovery holds values between.

## 3. Semantics discovery needs

**Counter or level.** Today `series.py` decides by the name (`_total`) and few drops. Remote
series get an explicit kind, in order: the definition's `kind` (`counter`, `level`, `rate`); the
source's `/api/v1/metadata` type (Prometheus answers; VictoriaMetrics often doesn't); the name
(`_total`, `_count`, `_sum`); the values, as today. The kind and its origin are recorded; one
guessed from values alone gets a "declare this" warning. Discovery honours a passed kind before
its name rule: H1's "explicit counter/gauge typing".

**Cumulative counts.** Prometheus counters already are cumulative, with resets. Fetch raw samples
from an hour before the window; increments are `b − a`, or `b` after a drop (the rule
`Series.deltas` and `sum_instances` already use); group by `by` as increments, never
`sum(counter)`, where one pod's restart reads as the service going backwards. One change to
`sample()` is forced: a remote counter's **first sample is a baseline**, not events (as
Prometheus' `increase()` treats it). Today "before a counter's first point nothing was counted",
so a counter first seen at 1,234,567 would read as a million-event burst. `kind = "rate"` (a query
that is already `rate(...)`) is integrated (Σ rate × step); that flow's evidence says its event
times are smeared over the rate window, and it is fitted on counts per step, never the
exact-event likelihood.

**The owner's examples, read honestly:** `count(grpc_request_latency{service="authz"})` counts
*series* (pods × methods × buckets): a level that moves when pods come and go. If
`grpc_request_latency` is a histogram, `_count` is requests completed (a flow), `rate(_sum[1m])`
is mean requests in flight by Little's law (a real stock), and `histogram_quantile(...)` is a
latency (an input or auxiliary, not a stock). Discovery treats each right once its kind is right.
Native histograms are refused in slice 1.

**Units:** the definition's `unit`, then metadata, then the suffix (`_seconds`, `_bytes`);
counters default to "events".

**Resolution.** For `select`, measured from the raw samples (`usual_interval`: the scrape
interval). For `query`, measured once from a short raw fetch of its selectors, or declared
(`resolution = "30s"`). Recorded per series, it is the input to H1's per-series-resolution work:
no slow series explains anything faster than itself, and remote queries are never evaluated
finer.

**Staleness and gaps.** Staleness NaNs and ±Inf are dropped. With raw samples a gap is a gap, and
`live.py` treats it as any machine-less series (stale after ten intervals of silence). Evaluated
points fake up to 5 minutes of holding after a series ends (the lookback): a recorded limit of
`query`. Pod churn makes every replaced pod's series "no longer written"; definitions should
aggregate pods away (`by = ["service"]`), as `sum_instances` already does for `instance`.

## 4. SQL, OLTP, lakes and warehouses

**OLTP state tables** (open orders, queue rows) keep no history: the past value is gone, so they
can only be polled. A `[[collect]]` script is enough and needs no code, documented as a recipe:

```sh
psql "$ORDERS_DB" -At -c "select 'orders_open ' || count(*) from orders where state = 'open'"
```

Polling once a minute is also gentler on a production database, and fits the events proposal's
rule that models never call operational systems directly.

**History tables, lakes and warehouses** (event tables with `created_at`/`closed_at`; Parquet;
BigQuery, Snowflake, ClickHouse) *can* answer any past time: `count(*) where created_at <= t` is a
counter at every `t`. That, and only that, earns a first-class **SQL source**: a template
returning `(ts, labels…, value)` rows, with `:start`, `:end`, `:step` bound as parameters (never
formatted into the text), behind an extra. DuckDB first (no server; reads Parquet, CSV and
Postgres), then Postgres URLs. Warehouses bill per query, so caching and coarse steps are
mandatory. Slice 3, after Prometheus is proven.

## 5. Secrets

- **Never in `orchestra.toml`.** A literal `password`, `token`, `key` or `secret` field, or a URL
  with `user:pass@`, is refused at load with the reason. Credentials come from environment
  variables (`bearer_env`, `basic = {user, password_env}`), a file outside the repository
  (`bearer_file`, `headers_file`; refused inside the repo or readable by others), later the macOS
  keychain. Non-secret headers (Mimir's `X-Scope-OrgID`) may be inline.
- **TLS:** `ca_file` for a company CA; `client_cert`/`client_key` for mTLS; `insecure = true`
  allowed but always shown red.
- **The UI and logs** show scheme, host and port, the kind of auth, and whether its variable or
  file is present; never values, headers, or a failing URL's query string. Error bodies are
  truncated.
- **Remote data on disk:** the cache and model versions (label values, fitted rates) hold company
  data in `~/.orchestrator/<key>/`; `cache = false` is for data that must not rest here (D10).

## 6. The UI

- **Sources page** (its own page: rule 8 keeps Core to the bus, store and runtime record; Core's
  metrics panel links to it). Per source: health, last error, server version, query latency
  p50/p95, series yielded, points fetched in the last discovery and the cached share, retention
  when the server says (warning when the window exceeds it). Per definition: query, kind and its
  origin, unit, resolution, series count, refusal and reason. The catalogue lists own and remote
  series together with a provenance column.
- **Dynamics:** each stock's and flow's drawer names its data ("work · `sum by (service)(rate(…))`
  · 15 s"); remote nodes carry a badge; nodes whose source was missing in the latest run are
  dimmed with the reason.
- **Preview:** pick a source, type a query, see the fan-out (label sets), a sparkline per series
  over the last hour (at most 50, within the source's timeout), the guessed kind and resolution,
  and the `[[series]]` TOML to paste. A read; it changes no configuration (rule 9). Same in the
  CLI: `orchestra sources preview --source work '<query>'`, `orchestra sources check`.

## 7. Where the code lives

```
orchestra/sources/
  __init__.py    Source protocol, Result (labels, points), Health, open_source()
  spec.py        [[sources]] / [[series]] / series_file parsing; refusals with reasons
  auth.py        credentials (env, file, keychain); the TLS context
  prometheus.py  query_range, raw samples, series, metadata, buildinfo; chunking, limits
  own.py         the project's MetricsStore as a Source
  kinds.py       kind, unit, resolution, each with its origin
  catalogue.py   own + definitions: fan-out, by, names, collisions, provenance, routing
  cache.py       settled chunks on disk
```

```python
class Source(Protocol):
    name: str
    def health(self, timeout: float) -> Health: ...
    def evaluate(self, query: str, start: float, end: float, step: float) -> list[Result]: ...  # query_range
    def samples(self, selector: str, start: float, end: float) -> list[Result]: ...             # raw points
    def series(self, match: str, start: float, end: float) -> list[dict[str, str]]: ...         # for preview
    def metadata(self, name: str) -> dict | None: ...
```

`MetricsStore` stays as it is, the write side and the own backend; `own.py` adapts it as the
first source. Rule 5 gains a sentence, stated in the commit: *other stores are read only through
`orchestra.sources`, never written; their cache lives in the state directory.*

**Discovery's read path:** `rediscover` calls `catalogue.dump(start − 1h, end)` (same tuple shape)
instead of `metrics.dump("", {"project": key})`, which also stops reading the own store's whole
history every run. The catalogue hands over `kinds`, `provenance` and `missing`; `discover()` and
`sample()` take `kinds` (and the counter baseline) and write provenance into `SeriesRef`.
`web/background.py`'s `history()` and `latest()` go through `catalogue.raw(ref, …)`, routed by
`ref.source`; the pages still read only background caches.

## 8. Tests

- **A fake Prometheus** (`tests/sources/fake_prometheus.py`): a stdlib HTTP server speaking
  `query_range`, instant `query` with range selectors (raw-sample matrices), `series`,
  `metadata`, `buildinfo` and Prometheus' error JSON, evaluating with `orchestra/metrics/promql.py`
  (which already does selectors, `rate`, `increase`, `sum`/`count by`). Injectable: latency, 5xx,
  401 without the bearer, the 11,000-points error, resets, staleness NaNs, Thanos `warnings`.
- **Conformance** (`tests/sources/`, like `tests/bus`): one suite against every source; own file
  and the fake always, own VictoriaMetrics and a real Prometheus by opt-in variable
  (`ORCHESTRA_TEST_PROM_URL`). It holds each to: the remote grid equals discovery's; raw samples
  equal what was written; fan-out label sets; resets; chunked equals unchunked; a timeout is a
  reasoned failure, not a hang.
- **Unit:** secret refusal, kinds and their origins, cache settle and invalidation, collisions,
  no version saved on partial failure; and the property that matters, **querying equals
  copying**: discovery over a fake remote yields the model that the same points written to the
  own store yield.
- **Live:** the bakery's VictoriaMetrics (127.0.0.1:8428) as a remote source of
  `~/orchestra-sample-live`: `select = '{__name__=~"bakery_.*", project="orchestra-bakery-5ba3c6da"}'`,
  `name = "{__name__}"`.

## 9. Phased plan

**Slice 1 (3–4 days): Prometheus-compatible sources feed discovery.** `spec`, `auth` (env vars,
`ca_file`), `prometheus` (raw samples, `query_range`, chunking, timeouts, concurrency), `own`,
`catalogue` (fan-out, `by`, templates, collisions, provenance); declared kind and counter baseline
in `series.py`; `rediscover` and `background` through the catalogue; `missing` recorded, no
version on a partial run; `orchestra sources check|preview`; the fake, conformance and
querying-equals-copying tests.
*Done when:* with the bakery run for an hour, the live sample's one model holds the bakery's
stocks and flows with `source = "bakery-vm"` beside the sample's own, matching what UC-1 finds
from the bakery's own store; stopping VictoriaMetrics mid-run keeps the last version and records
why; no secret appears in TOML, logs or API.

**Slice 2 (2–3 days): cheap, honest, visible.** The cache with incremental refresh; measured
resolution recorded, remote queries no finer than it (handed to H1's resolution work); kinds from
metadata and suffix with warnings; `kind = "rate"`; staleness; `series_file`; the Sources page,
Dynamics badges and dimming, preview in the UI.
*Done when:* a second rediscovery of the 6 h window fetches under 10% of the first's points; every
node's drawer names its source and query; a preview of `count by (job) (up)` against the bakery's
store shows the fan-out and the TOML.

**Slice 3 (about 3 days): beyond Prometheus, real company access.** DuckDB SQL source (bound
parameters), then Postgres history tables; file and keychain credentials, mTLS, tenant headers;
retention detection; an optional snapshot of a version's data for reproducibility after remote
retention expires; the SQL `[[collect]]` recipe documented.
*Done when:* a Parquet event table discovers as counters beside Prometheus series, and a Mimir or
Grafana Cloud tenant passes the opt-in conformance suite.

**Limits that stay:** evaluated queries lose exact event times; the cache can miss late
backfills; a model fitted on remote data cannot be re-derived past the remote's retention unless
snapshotted (D3: retention is the user's); Amazon Managed Prometheus needs SigV4, not planned.

## 10. Questions only the owner can answer

1. **Auth at work:** bearer token, basic, mTLS, an OAuth/OIDC proxy that wants a browser login, or
   only Grafana (then Orchestra queries through Grafana's datasource proxy with a service-account
   token: a different client)?
2. **Network and policy:** can this machine reach those servers (VPN, Tailscale, jump host)? May
   query results and fitted models of company data rest on a personal machine (D10)?
3. **Size and product:** Prometheus, Thanos, Mimir or Amazon Managed Prometheus? Their scrape
   intervals, retention and query limits? How many series does `grpc_request_latency` have?
4. **Shared definitions:** one company plugin carrying `[[series]]` for many repositories
   (`Plugin.series`), or always per repository?
5. **Machines from labels:** may a definition name machines (`machine = "{service}"`, k8s services
   as machines)? Should remote machines be prefixed (`work.authz`) so they never merge with a
   local machine of the same name?
6. **"The stock of request latency":** requests in flight (a stock, by Little's law) or latency
   as a driver of other flows (an input)? The definition's `kind` differs.
7. **Reproducibility:** should a model version keep the remote data it was fitted on, or only the
   queries and window, accepting that old fits may become unreproducible?
