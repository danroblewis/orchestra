# Orchestra on a work laptop: Jira and Chronosphere, read only, no AI

By hand; nothing here calls a model or writes anywhere. Have ready: GitHub
access to `danroblewis/orchestra-bridges` (private); a read-only Chronosphere service account
token and your namespace; a Jira Data Center personal access token (Profile → Personal Access
Tokens), Jira's URL and your board id (`rapidView=<id>` in the board's URL).

## 1. Install

```bash
gh auth login && gh auth setup-git        # once: git over https uses your GitHub login
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' \
  --with 'orchestra-bridges @ git+https://github.com/danroblewis/orchestra-bridges@main'
uv tool update-shell                      # then open a new terminal
PY="$(uv tool dir)/orchestra/bin/python"  # Orchestra's Python: set it in each terminal
"$PY" -c "import orchestra_bridges.kits"  # no output: the kits are there
```

## 2. A project directory

```bash
mkdir ~/work-orchestra && cd ~/work-orchestra && git init -q && orchestra init
```

`orchestra init` needs a git repository. It writes `orchestra.toml` here (every setting commented
out) and registers the directory in `~/.orchestrator/projects.json`; events, metrics, logs and the
web token go in `~/.orchestrator/<key>/`. Run everything from here.

## 3. Chronosphere

The token goes in a file only you can read:

```bash
mkdir -p ~/.config/orchestra && chmod 700 ~/.config/orchestra
(umask 077; pbpaste > ~/.config/orchestra/chronosphere-token)    # the token copied
```

Append to `orchestra.toml`:

```toml
[[sources]]
name = "chronosphere"
url = "https://<tenant>.chronosphere.io/data/metrics"
auth = "bearer"
token_file = "~/.config/orchestra/chronosphere-token"
match = ['{service=~"hk-.*"}']      # required: a PromQL label selector; nothing outside it is read
prefix = "chrono"
machine = "service"
max_series = 100
rate = 2.0                           # requests a second, for every process here
max_requests_per_day = 5000          # per UTC day; past it, nothing is asked until the next
[sources.labels]
service = ["service", "app", "k8s_app"]
```

`match` is a list of PromQL label selectors, the same shape as Prometheus's `match[]`. Orchestra
conjoins it into every query it sends, so the store is never asked for everything. `namespace`
is only the usual label on Kubernetes-scraped series; use whatever label scopes your team's
series: `service`, `app`, `job`, `team`, `cluster`, or a metric-name prefix such as
`{__name__=~"hk_.*"}`. A selector that matches everything (`{}`, `{__name__=~".+"}`) is refused.
To see which labels and values your store has, use the Core page's External stores section
after step 5: in each source's row, under its match, the **labels** button beside the query box lists the label names within the
match (narrowed to the query box's first selector, if it has one), and clicking a name lists its
values, both through the store's bounded label endpoints. There is no CLI command for this; the
page is the way (or your store's own explorer).

**`[sources.labels]` is an alias map, not a selection.** Each line says which of the store's
label spellings stand for one of Orchestra's own label names (`service`, `instance`, `pod`,
`container`, ...): `service = ["service", "app", "k8s_app"]` means "a series' `service` is its
`service` label, or else its `app`, or else its `k8s_app`" (the first one a metric has wins).
Orchestra uses it to name machines (`machine = "service"`) and places. It never selects or
limits which labels or series are read: only `match` does that, and every label on a series is
kept as a tag whether or not it is in the map. So do not read `service = [...]` as "read only
these services" or "only these labels": to narrow what is read, narrow `match`.

**The first match: a service, not a metric family.** Discovery finds a stock where a level
(a queue depth, requests in flight, replicas) moves, or where counters balance one (what came
in minus what went out). A match of one counter family, such as
`{__name__=~"grpc_client_callMillis.*"}`, holds no level and nothing for its counters to
balance, so it can yield no stock at all ("no counters balance", "no counter moved"). Match the
service's gauges and counters together instead: its queue depths, in-flight requests and
replicas, and its request and error counters. For example:

```toml
match = ['{service="hk-checkout",__name__=~".*(queue|inflight|in_flight|pending|replicas|requests_total|errors_total).*"}']
```

(one selector; adjust the name pattern to what the **labels** button and the store's metric
names show), and widen it later.


**`split`: name the labels a series is split by.** Left alone, inference splits each family by
the labels it judges to be groupings, and a label with many values you never wanted to look at
apart (a `edge_service` with a value per downstream caller, say) becomes a series per value, or
crowds out the ones you did want. Name the labels instead:

```toml
split = ["service_name", "method", "status"]
```

Every family under the source is then split by those labels only (the ones it has) and summed
over every other label, `edge_service` included; the store does the sum (`sum by (service_name,
method, status) (…)`), so each family gives as many series as the named labels have value
combinations, and no more. The Instruments page shows the split on the source's row, and a
left-out series on the Dynamics page says "summed over edge_service, …". Leave `split` out to
let inference choose again.

**`kinds`: only for the exceptions.** Most metrics say what they are by their names and the
store's metadata, and are read so with no entry:

| Name or metadata | Read as |
|---|---|
| typed `counter` | a counter: its increments are a flow |
| a gauge whose help says per interval ("delta", "in the sampling period") | a flow |
| a gauge or untyped `…_count` / `…_total` (GCP's per-minute DELTA counts: `ack_message_count`, `send_request_count`) | a flow (not `pod_count` and the like: things held) |
| `num_…`, `oldest_…_age`, `…undelivered…`, `…backlog…` (`num_undelivered_messages`, `oldest_unacked_message_age`, `backlog_bytes`) | a level |
| `:count` beside a `:sum` | a flow |

Anything else is judged by how its samples behave. When one is read wrongly, say what it is,
by name or by a glob (an exact name wins over a pattern, a longer pattern over a shorter):

```toml
kinds = { "*:count" = "flow", "gcp_pubsub_*_count" = "flow", "some_gauge" = "level", "noise" = "ignore" }
```

The Instruments page then says "kind: flow (declared by *:count)". An edit to `kinds` (or
`match`, `split`, `prefix`, the labels) takes effect at the next discovery, or at once with
`orchestra sources infer`: no reinstall, no cache to clear.

**Naming your stocks.** A series read from the store is called by its metric's words and the
labels that tell it from its siblings ("gcp pubsub subscription num undelivered messages
(orders)"). Give it a better name by rule, not one name per stock: a few patterns, each a
template over the labels, cover whole families:

```toml
[sources.names]
"*_num_undelivered_messages" = "{subscription_id} messages waiting"
"*_oldest_unacked_message_age" = "{subscription_id} oldest unacked age"
"grpc_client_callMillis:count" = "{method} calls completed"
"*:sum" = "{method} calls in progress"     # the occupancy view, calls in flight by Little's law
```

Keys match like `kinds` (an exact name over a pattern, a longer pattern over a shorter); a
value's `{label}` is any label of the series, `{metric}` the metric's own name, and a label a
series lacks is dropped from its name. Exact names are for the exceptions. A name takes effect
at the next discovery, with no new inference; a name you give a stock on the Dynamics page
still wins over it.

Every series read from the store is listed with the selector you would type in Chronosphere
itself (its own metric name and labels, not Orchestra's `chrono:` name), copyable, and a **view**
link that opens the Core page's External stores box on it: a counter as `rate(<selector>[<step>])`,
a gauge as the bare selector, over the window discovery fitted.

`orchestra sources check` should say `bearer from file …: present`, `answers`, and the endpoints
(`metadata no` is normal); never the token. `orchestra sources infer --source chronosphere` lists
what it will read.

## 4. Jira Data Center

Save the token: `(umask 077; pbpaste > ~/.config/orchestra/jira-token)`. Then
`orchestra bridges scaffold jira jira_ops` writes `.orchestra/machines/jira_ops/` (`poller.toml`,
`jira_ops.py`, `test_jira_ops.py`, `AGENTS.md`). In `poller.toml`'s `[settings]`:

```toml
base_url = "https://jira.<company>.com"         # no /rest/...
edition = "datacenter"
token_file = "~/.config/orchestra/jira-token"   # replaces the token_env line
jql = "project = OPS"     # your board's filter: Board settings → General → Saved filter
```

`since = "1d"` relays the last day's open tickets at once.

**Against a fake first.** In a second terminal, the kit's fake Jira (Data Center):

```bash
"$PY" -c "import threading; from orchestra_bridges.kits.fakes import FakeJira; from orchestra_bridges.kits.runner import FAKE_TOKEN
f = FakeJira(token=FAKE_TOKEN, edition='datacenter').start(); print(f.url, flush=True); threading.Event().wait()"
```

In the first, with the URL it printed:

```bash
cd .orchestra/machines/jira_ops
"$PY" jira_ops.py edition --base-url http://127.0.0.1:<port>   # edition = "datacenter" …
"$PY" jira_ops.py measure --base-url http://127.0.0.1:<port>   # jira_issues{…} lines
"$PY" -m pytest test_jira_ops.py -q                            # starts its own fake; passes
cd ../../..
```

A fake gets a placeholder, never your token. Ctrl-C the fake.

**Approve, then the real site.** Until `poller.toml` says so, the program refuses every host but a
fake. Change its top-level lines to:

```toml
clearance = "approved"
data_class = "metadata"
```

`"$PY" .orchestra/machines/jira_ops/jira_ops.py edition` now reads your site and should print
`edition = "datacenter"`. Append to `orchestra.toml`:

```toml
[[machines]]
name = "jira_ops"
command = "python .orchestra/machines/jira_ops/jira_ops.py"
restart = "always"

[[collect]]
name = "jira_ops"
command = "python .orchestra/machines/jira_ops/jira_ops.py measure"
every = "5m"
timeout = "60s"
```

`orchestra bridges integrations` should list `jira_ops` `approved`, token `file`, guesses `0`.

## 5. Run it and look

```bash
orchestra run          # terminal 1: the host; it starts the poller
orchestra web          # terminal 2: http://127.0.0.1:8000/ (--port N if 8000 is taken)
orchestra web token    # terminal 3: paste it at /login
```

The first hour:

- **Instruments**: `jira_ops`, a script every 5 min, one `jira_issues` series per status; and
  `chronosphere`, a source, "read at the last discovery".
- **Core**: the processes the host keeps (`jira_ops`, with its log), the bus, the store. Its
  **External stores** row for `chronosphere` shows the URL, `bearer from file <path>` (never the
  value), the `match`, the caps, "N of 5,000 today (UTC)", the last read and error, the
  definitions kept, and a PromQL box that stays inside `match`. A discovery (every 5 minutes)
  costs about 35 requests.
- **Machines**: after the second poll (5 minutes), the people who created or moved tickets, as
  `person.jira.<user name>`. Never a node named `jira_ops`.
- **Dynamics**: rediscovered every 5 minutes. Chronosphere's history shows at once. Tickets
  move rarely, so the header may say "read over the last … (widened from …: widened for sparse
  data (N levels): they moved in too few of its steps)": discovery reached back until each slow
  series moved often enough to fit. The first Jira stocks are the ticket
  counts per status (`jira_issues`); the `jira.issue.*` events are counted and become flows as
  they accumulate.

Logs: `~/.orchestrator/<key>/logs/machines/jira_ops.log` (`poll N: K events`).

## 6. What never happens, and stopping

- **No write.** The Jira program only reads. Orchestra only queries Chronosphere's Prometheus API,
  inside `match`, under the caps; every request it sends (discovery's, inference's, the page's)
  is logged in `~/.orchestrator/<key>/sources/chronosphere.requests.jsonl` (the last 10,000), shown
  on the Core page's row of the store (the last twenty, and today's count beside the cap) and by
  `orchestra sources check` (the last five).
- **No AI.** Nothing installed here calls a model.
- **No token leaves its file** except to its own host; pages and logs say only where it is.
  Ticket titles and descriptions are dropped.

To stop: Ctrl-C `orchestra web`, then `orchestra run` (the poller stops with it). To stop Jira
alone, delete its two entries. To remove everything: `uv tool uninstall orchestra`,
then delete `~/work-orchestra`, `~/.orchestrator/<key>/` and the token files.
