# Using Orchestra

This guide is for someone who has systems of their own and wants Orchestra to observe them. It
assumes you know Prometheus (the text format, counters and gauges, scraping) and how services
run. It does not assume you know Orchestra.

Orchestra watches a system of **machines** (your programs, services, scripts, AI agents, people)
through two things: an **event bus** and a **metrics store**. From the measurements in the store
it builds one **system dynamics model**: which levels are **stocks**, which counters are the
**flows** that fill and drain them, how fast each flow runs, and the feedback loops between them.
You never tell it what a stock is. You give it plain series, and it finds the stocks. Which
machines may drive a flow is something it infers, as a hypothesis, from the machines' events.

The measurements come from **instruments** (scripts, scrapes, other stores), not from the
machines: an instrument measures the system and never acts on it; a machine does the work and
speaks on the bus. Section 3 explains the difference.

Orchestra runs none of your logic and knows nothing of your domain. It starts the commands you
declare, reads what your instruments print or serve, and reads what your machines publish.

Where to go for more:

- [`docs/machines.md`](docs/machines.md): the short guide to writing a machine. This guide covers
  the same ground and more; where that page goes deeper, this one links to it.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): how Orchestra works inside (discovery in depth).
- [`PLUGINS.md`](PLUGINS.md): packages that add pages and processes to Orchestra.
- [`SPEC.md`](SPEC.md): the design of what exists, section by section.

Contents:

1. [Install and start a project](#1-install-and-start-a-project)
2. [Configure: `orchestra.toml`](#2-configure-orchestratoml)
3. [Add your own metrics](#3-add-your-own-metrics)
4. [Name series so discovery can use them](#4-name-series-so-discovery-can-use-them)
5. [Connect machines](#5-connect-machines) (and ask the model: [experiments](#59-asking-the-model-experiments))
6. [What Orchestra does with your data](#6-what-orchestra-does-with-your-data)
7. [A worked example: a queue](#7-a-worked-example-a-queue)
8. [Troubleshooting](#8-troubleshooting)
9. [Reference](#9-reference)

---

## 1. Install and start a project

### Install

Orchestra needs Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install 'orchestra @ git+https://github.com/danroblewis/orchestra@main'       # the `orchestra` command
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main'   # the same, with SD Lab's discovery strategies
uv tool install /path/to/orchestra            # or from a checkout
```

Plugins go into the same environment with `--with` (README, "Install"), for example
`--with 'orchestra-tasking @ git+ssh://git@github.com/danroblewis/orchestra-tasking'`. Plugins
name Orchestra as `git+https://github.com/danroblewis/orchestra@main`, so install Orchestra by that
exact URL beside them: pip refuses two different URLs for one package.

Extras add optional parts:

| Extra | What it adds |
|---|---|
| `sd` | SD Lab's discovery strategies (`kalman_lna` and about 70 others). Without it, discovery uses `conservation`, Orchestra's own. |
| `bus-redis`, `bus-rabbitmq`, `bus-kafka` | The client library for that event bus. `bus` installs all three. |

`deploy/dev/compose.yaml` in Orchestra's repository starts Redis, RabbitMQ, Kafka and
VictoriaMetrics locally, if you want server backends to try.

### Start a project

A **project** is one git repository. Orchestra keeps one bus, one store and one model per
project.

```bash
cd my_project                  # any git repository
orchestra init                 # writes orchestra.toml and registers the project
orchestra run &                # the host: instruments, launcher, event counter, discovery
orchestra web                  # the UI on http://127.0.0.1:8000; prints a link that logs you in
```

`orchestra init` prints the project key and where its state lives:

```
initialized my_project-1a2b3c4d
  repo:   /home/me/my_project
  state:  /home/me/.orchestrator/my_project-1a2b3c4d
  config: /home/me/my_project/orchestra.toml
```

What each command does:

| Command | What it does |
|---|---|
| `orchestra init` | Writes a starter `orchestra.toml` at the repository root, if there is none, and registers the project. It must run inside a git repository. Run it once. A clone that already has an `orchestra.toml` needs no `init`: the state directory is made the first time any command runs. |
| `orchestra run` | Starts the **host**, Orchestra's own machine (`orchestra-host`). It runs your `[[collect]]` and `[[scrape]]` instruments, keeps your `[[machines]]` running, counts every event on the bus, and rediscovers the model every `[discovery] every`. Stop it with Ctrl-C, SIGTERM or SIGHUP; it stops everything it started. |
| `orchestra web [--port 8000] [--host 127.0.0.1]` | Serves the web UI: Dashboard, Machines, Instruments, Dynamics, Experiments and Core, behind the project's web token ([Logging in](#logging-in-to-the-web-ui)). It reads; it changes nothing but the model (when you press "rediscover now"). |
| `orchestra web token [--rotate]` | Prints the web token; `--rotate` replaces it, which logs every browser out. |

Every command takes `--repo PATH` to name the repository. Without it, Orchestra uses
`ORCHESTRA_REPO`, then the current directory. From a subdirectory, or from a linked git worktree,
Orchestra finds the main repository's root: a worktree is the same project as its repository.

Only one host launches for a project. A second `orchestra run` started while one is running
counts events and rediscovers, but starts no processes and no instruments. It says so in its log.

### Logging in to the web UI

Every page and every API of `orchestra web`, a plugin's included, asks for the project's **web
token**. Only `GET /health` answers without it. The token is made the first time it is needed and
kept in `<state>/web.token`, readable by you only. It is never in `orchestra.toml`.

`orchestra web` prints it when it starts, with a link that logs you in:

```
orchestra web: http://127.0.0.1:8000/
  log in:  http://127.0.0.1:8000/login#token=Qm9...
  token:   Qm9...  (again: `orchestra web token`; kept in /home/me/.orchestrator/my_project-1a2b3c4d/web.token)
```

- **In a browser,** open the link, or open any page and paste the token into the login page. The
  token after `#` never leaves the browser; the login page sends it once. The browser then keeps a
  session cookie for 14 days. "log out" at the right of the nav ends it.
- **From a program,** send the token on every request: `Authorization: Bearer <token>`.
  `curl -H "Authorization: Bearer $(orchestra web token)" http://127.0.0.1:8000/api/core`.
- **To lock everyone out,** run `orchestra web token --rotate`. The new token takes effect at once,
  without a restart: every browser must log in again, and every program needs the new token.

The web token is not the events endpoint's token (`events.token`, §5.2). A machine that can
publish events cannot use the web UI with its token, and the other way round.

**Refusals.** A page asked for without a login goes to the login page and comes back after it. An
API asked for without one answers `401`. Five wrong tokens within a minute from one address (at the
login page, or as a bearer token) and further tries answer `429` for the rest of that minute. A
browser that is already logged in keeps working. A request that changes something (`POST`, `PUT`,
`DELETE`) with the session cookie must come from Orchestra's own pages; one sent by another site
answers `403`.

**Through a tunnel or a reverse proxy.** Start `orchestra web` as usual and point the tunnel at
it: `cloudflared tunnel --url http://127.0.0.1:8000`. Open the tunnel's address with `/login`
(`https://<name>.trycloudflare.com/login`) and paste the token. Do not open the printed
`127.0.0.1` link there: it logs in the browser on this computer only. The tunnel must pass the
`Host` header on unchanged, as `cloudflared` does; a proxy that rewrites it to `127.0.0.1` makes
every change from the page answer `403`. The cookie is marked `Secure` when the browser reached the
server over HTTPS. Orchestra never trusts `X-Forwarded-For`: the limit on wrong tokens counts the
address the connection comes from, which behind a tunnel is the tunnel's, shared by everyone.

**`[web] auth`.** On by default, on every address. Loopback is not private: a tunnel or a proxy on
the same computer makes a server on `127.0.0.1` public, other users of the computer reach it, and
any web page you visit can send requests to it. To serve without a login, on this computer only:

```toml
[web]
auth = "off"     # "on" (default) or "off"
```

`off` is refused, and `orchestra web` does not start, unless `--host` is a loopback address
(`127.0.0.1`, `::1`, `localhost`). Even then, a request that came through a proxy or a tunnel (it
has a forwarding header, such as `X-Forwarded-For` or `Cf-Connecting-Ip`, or names a host other than
a loopback address) answers `403`, so a tunnel in front of it is closed, not open.

### The project key and where state lives

The **project key** is the repository directory's name plus the first 8 hex digits of a SHA-256
of its full path: `my_project-1a2b3c4d`. Two clones in different places are two projects.

Nothing is written inside your repository except `orchestra.toml`. Everything else lives in the
state directory, `~/.orchestrator/<key>/`. Set `ORCHESTRATOR_HOME` to put `~/.orchestrator`
somewhere else (useful for trying things out: every command, and `orchestra run`, must see the
same value).

```
~/.orchestrator/                     ($ORCHESTRATOR_HOME)
  projects.json                      repository root → project key
  <key>/
    project.json
    orchestra.local.toml             your private configuration overlay, if you write one (§2)
    runtime.json                     the hosts, the launcher, the web server, the launched processes, the instruments' health
    events.jsonl                     the event log, when [events] url = "file"
    metrics.jsonl                    the metrics, when [metrics] url = "file"
    model/vNNNN.json                 the model's saved versions
    model/discovered.json            the latest discovery, saved or not
    sources/<name>.json              each [[sources]] entry's latest inference
    logs/orchestra-host.log          the host's log
    logs/machines/<name>.log         each launched process's output
    logs/instruments/<name>.log      each [[collect]] or [[scrape]] instrument's rounds (and a script's stderr)
```

Logs roll over to `<name>.log.1` at 5 MB.

---

## 2. Configure: `orchestra.toml`

`orchestra.toml` sits at the repository root and is committed with it. `orchestra run` reads it
again within a second of it changing: an instrument or machine added starts, one removed stops,
one changed starts over. You never need to restart `orchestra run` for a change to
`[[machines]]`, `[[collect]]` or `[[scrape]]`. After changing `[events]`, `[metrics]` or
`[discovery]`, restart `orchestra run` and `orchestra web`, so every process reads the same
settings (the web server reads them only when it starts).

Sections Orchestra does not know are ignored, so a plugin may keep its own settings here, and a
file written for an older Orchestra still loads.

### A private overlay: configuration that stays out of the repository

When the repository is shared (a team's or a company's), what is yours alone (your channels,
templates, identities, your own instruments) should not land in it. Put it in a **private
overlay**: a second file, outside the repository, merged over `orchestra.toml`. Orchestra reads
it from:

1. the file `ORCHESTRA_CONFIG_OVERLAY` names (relative to the repository root unless absolute),
   if that variable is set; a missing file is then an error, so a mistyped path never silently
   drops your settings;
2. otherwise `~/.orchestrator/<key>/orchestra.local.toml`, in the project's state directory, if
   it is there.

A file in the repository (an `orchestra.local.toml` at its root, say) is never read on its own:
the overlay is for what must stay out of the repository, and a file in it is one `git add -A`
from being shared. Without an overlay nothing changes.

The merge:

- **Tables** merge key by key, and the overlay's value wins.
- **Arrays of tables** (`[[machines]]`, `[[collect]]`, `[[scrape]]`, `[[sources]]`, `[[series]]`,
  a plugin's `[[tasks.roles]]`, at any depth) merge by `name`: an overlay entry with the name of
  one of the repository's replaces it whole; any other is added after them.
- **Removing** an entry: an overlay entry `{ name = "x", enabled = false }` takes the
  repository's `x` out.
- **Anything else** (a string, a number, an array of plain values) is replaced.

`[overlay]` in the overlay file is the overlay's own and is not merged. Its `secret` lists keys
whose values are never shown (below); a key covers what is under it. Secret here means private,
not a credential: **credentials never go in any configuration file**, overlay or not. They come
from the environment or from files outside the repository, as `[[sources]]` auth does.

```toml
# ~/.orchestrator/work-repo-1a2b3c4d/orchestra.local.toml

[overlay]
secret = ["desk.me", "machines[pager].command"]

[metrics]
url = "http://127.0.0.1:8428"          # my VictoriaMetrics, not the team's file store

[desk]                                  # a plugin's section, only mine
me = "U0123ABC"
channels = ["#my-team", "@me"]

[[machines]]                            # added to the repository's [[machines]]
name = "pager"
command = "machines/pager.sh --to U0123ABC"

[[machines]]                            # the repository's "demo" does not run for me
name = "demo"
enabled = false

[[collect]]                             # replaces the repository's "disk" entry
name = "disk"
command = "machines/disk.sh"
every = "5m"
```

`orchestra run` follows both files: a change to either, or the overlay appearing or going, is
read within a second, as for `orchestra.toml` alone. Plugins see the merged configuration
(`project.config.raw`) and need not know there is an overlay.

A plugin that changes configuration for you (the agents' Supervisor, when you ask it in the chat)
does it through Orchestra (`project.config_edit`, SPEC §8.2) and says which file it changes: your
own settings (identities, channels, templates) go to the overlay, the project's to
`orchestra.toml`. The overlay is created on its first change, readable only by you, and never
committed. You can always edit either file by hand as well.

To see where each key came from, open the Core page's Configuration panel, or
`GET /api/project`: it names both files and lists each key (`events.url`, `machines[pager]`)
with `"from": "repo"` or `"overlay"` and its value, except that a key the overlay marks secret has
`"secret": true` and no value (an entry with a secret field lists it under `secret_fields`), and
the entries the overlay removed are under `removed`.

Set `ORCHESTRA_CONFIG_OVERLAY`, if you use it, for `orchestra run`, `orchestra web` and every
CLI call alike. The state-directory file needs no variable.

### Durations

Wherever a key takes a duration, give a number of seconds (`30`, `2.5`) or a string with a unit:
`"500ms"`, `"30s"`, `"5m"`, `"1h"`. A string with no unit is seconds.

### `[events]`: the event bus

| Key | Type | Default | Meaning |
|---|---|---|---|
| `url` | string | `"file"` | `file` (a JSONL file in the state directory), `redis://host:6379/0` (Redis Streams), `amqp://user:pass@host:5672/` (a RabbitMQ stream), or `kafka://host:9092` (one topic, one partition). `rediss://` and `amqps://` work too. |
| `listen` | string | `"127.0.0.1:0"` | Where `orchestra run` serves the events endpoint ([§5.2](#52-publishing-and-reading-events)): `host:port`, port `0` meaning one the system picks. `"off"` serves none. |

The environment variable `ORCHESTRA_EVENTS_URL` overrides it. The stream is named
`orchestra.<key>.events` on every backend and is never shared with anyone else. A server backend
needs its extra (`bus-redis` and so on). `orchestra events copy --to URL` copies the log to
another backend.

```toml
[events]
url = "redis://127.0.0.1:6379/0"
```

### `[metrics]`: the metrics store

| Key | Type | Default | Meaning |
|---|---|---|---|
| `url` | string | `"file"` | `file` (a JSONL file in the state directory) or `http://host:8428` (VictoriaMetrics, or anything that speaks its JSON-lines import and the Prometheus query API). |

The environment variable `ORCHESTRA_METRICS_URL` overrides it. Every point carries a `project`
label, so several projects can share one VictoriaMetrics. Queries are PromQL: VictoriaMetrics
answers them itself; the file store answers a tested subset.

```toml
[metrics]
url = "http://127.0.0.1:8428"
```

### `[discovery]`: how the model is found

| Key | Type | Default | Meaning |
|---|---|---|---|
| `strategy` | string | `kalman_lna` when the `sd` extra is installed, else `conservation` | `conservation` is Orchestra's own. Any other name is an SD Lab strategy (`kalman_lna`, `combined2`, `matrix_v2`, ...). Without the `sd` extra, every strategy falls back to `conservation`; the host's log names the one that ran. |
| `window` | duration | `"60m"` (3600 s) | How far back each discovery looks. |
| `step` | duration | `"30s"` | The grid discovery samples on: the finest change it sees. |
| `every` | duration | `"5m"` (300 s) | How often the host rediscovers. An SD Lab strategy gets 80% of this as its deadline. |
| `[discovery.options]` | table | empty | Passed to the strategy as it is. |
| `eras_from` | array of strings | `["config.changed"]` | Events that begin an era, besides `system.changed`, which always does (section 5.7). Each is an event type or a glob of types, optionally with `:source=…` and `subject=…` globs, comma-separated: `"role.changed:source=supervisor"`. Only the envelope is matched, never `data`. `[]` leaves only `system.changed`. |
| `prior_for` | duration | the window | How long a new era carries the parts of the previous era's model it has not found yet. |
| `announce_hold` | whole number | `3` | How many discoveries in a row a structure change must hold before Orchestra publishes `orchestra.model.changed`. |
| `announce_gap` | duration | `"30m"` | The least time between two `orchestra.model.changed`. |
| `diverge_after` | duration | `"15m"` | How long a stock must stay outside its predicted band before `orchestra.model.diverged`. |

```toml
[discovery]
strategy = "conservation"
window = "60m"
step = "30s"
every = "5m"
```

The window and the step decide what discovery can see. A level written every 15 seconds that
changes for a few seconds at a time is visible on a 5 s grid and lost on a 30 s one. A stock
needs time to show itself (section 4), so a short window with a fine step suits a demo, and the
defaults suit a system that runs all day.

### `[[machines]]`: commands `orchestra run` keeps running

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string, required | | Letters, digits, `.`, `_` and `-`. Its log is `logs/machines/<name>.log`. |
| `command` | string, or array of strings, required | | A string is split like a shell would split it, but **no shell runs it**: no pipes, no `&&`, no `$VAR`. Put those in a script. |
| `restart` | string | `"always"` | `always`, `on-failure` (only after a non-zero exit) or `never`. |
| `stop_grace` | number (seconds) | `10` | How long after SIGTERM before SIGKILL when stopping it. |

```toml
[[machines]]
name = "app"
command = "bin/app --port 9100"
restart = "always"
stop_grace = 10
```

Section 5.5 describes what the launcher does with it. A name of the form `<plugin>.<name>`,
where `<plugin>` is a loaded plugin with processes, is refused: that form is kept for plugins.

### `[[collect]]`: a command whose output is measurements

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string, required | | The instrument's id. Letters, digits, `.`, `_` and `-`. Not `orchestra-host`, and not another `[[collect]]` or `[[scrape]]` entry's name. Instrument names are their own: it may share a `[[machines]]` entry's name without being that machine. Its log is `logs/instruments/<name>.log`. |
| `command` | string, required | | Split like a shell would, not run by one. A file in the repository is named with a slash: `machines/disk.sh` or `./disk.sh`. |
| `every` | duration | `"60s"` | How often it runs. At least 1 s. |
| `timeout` | duration | `"10s"` | How long one run may take. More than 0; never more than `every` (a larger value is cut to `every`). |

```toml
[[collect]]
name = "disk"
command = "machines/disk.sh"
every = "60s"
timeout = "20s"
```

### `[[scrape]]`: a URL that serves measurements

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string, required | | The instrument's id, as for `[[collect]]`. It may share a `[[machines]]` entry's name (a scrape of the program that entry runs, say); the scrape is still an instrument, not that machine. |
| `url` | string, required | | Starts with `http://` or `https://`. Fetched with a GET. |
| `every` | duration | `"60s"` | How often it is read. At least 1 s. |
| `timeout` | duration | `"10s"` | How long each wait for the server may take (it bounds each read, not the whole transfer). Never more than `every`. |

```toml
[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"
timeout = "10s"
```

An entry of `[[collect]]` or `[[scrape]]` that cannot be used is left out, with a line in the
host's log saying why. The others still run.

### `[[sources]]`: another store, read where its data lives

A source is a server that answers the Prometheus HTTP query API (Prometheus, VictoriaMetrics,
Thanos, Mimir, Chronosphere). Orchestra reads it in place and never writes to it. Section 3.3
explains how.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string, required | | Lower-case letters, digits and `_`, starting with a letter or `_`. |
| `type` | string | `"prometheus"` | The only type built. |
| `url` | string, required | | `http(s)://host[:port][/path]`. The API path (`/api/v1/...`) is appended. No `user:pass@`, no query string. |
| `auth` | table | none | How Orchestra proves who it is. See [auth](#auth). |
| `prefix` | string | the `name` | Series become `<prefix>:<name>`, machines `<prefix>.<id>`. Lower-case letters, digits and `_`; must not start with `orchestra`; unique among sources. |
| `machine` | string | none | The canonical label that names machines (after `[sources.labels]`). |
| `match` | string or array | `['{__name__=~".+"}']` | Selectors that say what to infer from. |
| `max_series` | integer | `200` | The most series kept from this source. |
| `max_per_family` | integer | `12` | The most kept from one family. |
| `identity` | array | `["pod", "instance", "container"]` | Labels that name one reporting thing (never summed into a stock by themselves). |
| `timeout` | duration | `"30s"` | Per request. |
| `deadline` | duration | `"120s"` | For one discovery's reads from this source, all told. |
| `max_points` | integer | `11000` | Points per series per request; longer ranges are read in chunks. |
| `concurrency` | integer | `4` | Requests in flight at once. |
| `infer_every` | duration | `"1h"` | How often the schema is inferred again. |
| `insecure` | boolean | `false` | Skip TLS verification. Always shown as such. |
| `infer` | boolean | `true` | `false` reads only the declared `[[series]]`, never the schema. |
| `settle` | duration | `0` | End every read this long before now (for a store that hides its newest samples from range queries, such as VictoriaMetrics' `-search.latencyOffset`). |
| `preset` | string | none | A TOML file of `[[series]]` and `[source]` defaults for one exporter, relative to the repository or absolute. |
| `[sources.labels]` | table | empty | `canonical = ["spelling", ...]`: label spellings that mean the same thing. The first a metric has wins. |
| `[sources.producers]` | table | empty | `channel = "machine"`: who produces into a channel whose counts name nobody (counted traffic). |
| `[sources.transform]` | table | none | `queries = "scripts/queries.py"` (the query script) and `timeout` (default `"20s"`). |

A key anywhere in the table named like a secret (`token`, `password`, `secret`, `api_key`,
`credentials`, ...) with a literal value refuses the source.

```toml
[[sources]]
name = "work"
url = "https://tenant.example/data/metrics"
auth = { bearer_env = "WORK_TOKEN" }
prefix = "work"
machine = "service"
match = ['{__name__=~"http_.*|queue_.*"}']
[sources.labels]
service = ["service", "app", "k8s_app"]
[sources.transform]
queries = "scripts/queries.py"
```

### `[[series]]`: a series you define by hand

A definition read from a source, always read, whatever inference ranks.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `source` | string, required | | A usable `[[sources]]` name. |
| `name` | string, required | | Lower-case letters, digits and `_`. The series is `<prefix>:<name>`. |
| `query` | string | | A PromQL query. Give `query` or `select`, not both. |
| `select` | string | | A selector whose raw samples are read as a counter, reset-safe. Needs `kind = "counter"`. |
| `by` | array of strings | | With `select`: sum by these labels. |
| `kind` | string | `"level"` | `level`, `counter` or `rate`. A rate is integrated into counts. |
| `unit` | string | none | Shown beside the stock. |
| `traffic` | table | none | Counted traffic: `{ direction = "out" \| "in" \| "backlog", channel = "{label}", machine = "{label}" }`. See [SPEC §4.4](SPEC.md). |

```toml
[[series]]
source = "work"
name = "checkout_errors"
query = 'sum(rate(http_errors_total{svc="checkout"}[5m]))'
kind = "rate"
```

### Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `ORCHESTRATOR_HOME` | every command | Where state lives instead of `~/.orchestrator`. |
| `ORCHESTRA_CONFIG_OVERLAY` | every command, `load_project()` | The private overlay to merge over `orchestra.toml`, instead of `<state>/orchestra.local.toml` (§2). |
| `ORCHESTRA_REPO` | every command, `load_project()`, `for_repo()` | The repository, when `--repo` is not given. The launcher and the instruments set it for what they run. |
| `ORCHESTRA_EVENTS_URL` | every command, `Events.for_project` | Overrides `[events] url`. |
| `ORCHESTRA_METRICS_URL` | every command, `for_repo()` | Overrides `[metrics] url`. |
| `ORCHESTRA_MACHINE_LOG` | set for what Orchestra runs | The log file of the process or `[[collect]]` script (the name is kept for both). |
| `ORCHESTRA_EVENTS_ENDPOINT` | set for what the launcher runs | The events endpoint's URL, `http://127.0.0.1:<port>`. Not the same as `ORCHESTRA_EVENTS_URL`, which names the bus backend. |
| `ORCHESTRA_EVENTS_TOKEN` | set for what the launcher runs | The token the events endpoint wants, as `Authorization: Bearer <token>`. |

If you set an override, set it for `orchestra run`, `orchestra web` and every CLI call alike, or
they will read different stores.

---

## 3. Add your own metrics

### Instruments and machines

Orchestra keeps two things apart:

- An **instrument** measures the running system and never acts on it: a `[[collect]]` script, a
  `[[scrape]]` URL, a `[[sources]]` store, or a collector a plugin declares
  (`Plugin.collectors`). Its measurements go into the metrics store, or, for a source, are read
  where they live.
- A **machine** does actual work: a program, an AI agent, a person. Orchestra knows a machine
  because it shows up on the event bus (section 5). A machine does not produce the metrics.

**The metrics store is filled by instruments directly.** The one series derived from the bus is
`orchestra_events_total{type, source}`, Orchestra's count of the machines' events, and it is
secondary. Keeping the measurements apart from the machines is what lets them test what we
believe the machines do: system dynamics has no machines, and how a machine's work relates to
the model's flows is not known. A machine may influence no flow, one or several, and several
machines may contribute to one flow. Discovery infers which, and only as hypotheses
([section 6](#machines-and-flows-hypotheses)).

```mermaid
flowchart LR
    machines["Machines<br/>programs, agents, people"]
    instruments["Instruments<br/>[[collect]], [[scrape]]"]
    sources[("[[sources]]<br/>another store")]
    bus[("Event bus")]
    store[("Metrics store")]
    disc["Discovery"]
    model[("Model<br/>stocks and flows")]

    machines -- "events" --> bus
    bus -- "orchestra_events_total<br/>(secondary)" --> store
    instruments -- "points labelled instrument=#lt;name#gt;" --> store
    store --> disc
    sources -- "read at each discovery" --> disc
    disc --> model
    machines -. "associated with flows<br/>only as hypotheses" .-> model
```

An instrument is not a machine. It is not announced on the bus and is not on the Machines page.
It has a page of its own, **Instruments** (`/instruments`, and `/api/instruments`): each
instrument's name, kind (script, URL, source), target, how often it is read, its last write and
how many points, its failures, its last error and its log
(`/api/instruments/<name>/log`). Its health is in `runtime.json` under `instruments`, its log in
`<state>/logs/instruments/<name>.log`. A plugin's collectors run like yours, named
`<plugin>.<name>`; a `[[collect]]` or `[[scrape]]` of the same name takes its place, and the
host's log says so ([`PLUGINS.md`](PLUGINS.md)).

Every point an instrument writes is labelled `instrument=<name>` and `project=<key>`. The label
says which instrument measured it (provenance) and nothing else: it never makes a machine and is
never read to associate a machine with a flow. Every other label the target serves is kept as
it is, `machine` included (it is then the measured system's own dimension).

Instruments changed on 2026-10-27; see [Migration](#migration-2026-10-27) for what that does to
existing stores.

### Ways to get measurements in

There are three ways to get measurements in. None needs Orchestra's library.

```mermaid
flowchart LR
    subgraph yours["Your systems"]
        script["A script<br/>prints Prometheus text"]
        svc["A service<br/>serves /metrics"]
        remote[("Another store<br/>Prometheus, VictoriaMetrics,<br/>Mimir, Chronosphere")]
        py["A Python program<br/>orchestra.events / orchestra.metrics"]
    end

    subgraph host["orchestra run (the host)"]
        collect["[[collect]]<br/>runs it every 'every'"]
        scrape["[[scrape]]<br/>GETs it every 'every'"]
        parse["Prometheus text parser<br/>sets instrument and project labels"]
        counter["Event counter<br/>orchestra_events_total{type, source}"]
        disc["Discovery<br/>every [discovery] every"]
    end

    store[("Metrics store<br/>file or VictoriaMetrics")]
    bus[("Event bus<br/>file, Redis, RabbitMQ, Kafka")]
    cat["Catalogue<br/>own series + [[sources]]"]
    model[("Model<br/>model/vNNNN.json")]

    script --> collect --> parse
    svc --> scrape --> parse
    parse --> store
    py -- "for_repo().write()" --> store
    py -- "Events.publish()" --> bus
    bus --> counter --> store
    store --> cat
    remote -- "read in place, never copied" --> cat
    cat --> disc --> model
```

| Way | Use it when | You declare |
|---|---|---|
| A script | You can measure something from a shell or a short program. | `[[collect]]` |
| A URL | A program already serves Prometheus metrics (your service, `node_exporter`). | `[[scrape]]` |
| Another store | The series already live in Prometheus or something like it. | `[[sources]]` |

A fourth way, writing points from Python with `orchestra.metrics.for_repo()`, is in
[section 5.2](#52-publishing-and-reading-events).

Orchestra reads the Prometheus text format only. There is no push endpoint for measurements and
no remote-write receiver. (Events have an HTTP endpoint: [section 5.2](#52-publishing-and-reading-events).)

### 3.1 A script (`[[collect]]`)

```sh
#!/bin/sh
# machines/disk.sh: free disk space and the files in the repository.
set -eu
echo "disk_free_bytes $(df -Pk . | awk 'NR == 2 { print $4 * 1024 }')"
echo "repo_files $(git ls-files | wc -l)"
```

```bash
chmod +x machines/disk.sh
ORCHESTRA_REPO=$PWD ORCHESTRA_MACHINE_LOG=/dev/stderr ./machines/disk.sh   # try it
```

```toml
[[collect]]
name = "disk"
command = "machines/disk.sh"
every = "60s"
timeout = "20s"
```

**What the script must print.** The Prometheus text exposition format, version 0.0.4, on
standard output:

```
# HELP disk_free_bytes Free space on the volume.
# TYPE disk_free_bytes gauge
disk_free_bytes{volume="/"} 201491873792
files_written_total 42 1761500000000
```

- One sample per line: `name{label="value",...} value [timestamp]`. Labels are optional.
- A name matches `[a-zA-Z_:][a-zA-Z0-9_:]*`; a label name `[a-zA-Z_][a-zA-Z0-9_]*`. Avoid `:` in
  names: Orchestra uses `<prefix>:<name>` for series read from other stores.
- Label values escape `\\`, `\"` and `\n`.
- The value is a float (`42`, `1.5e9`). `NaN`, `+Inf` and `-Inf` are left out.
- The optional timestamp is whole **milliseconds** since 1970. Without one, the point takes the
  time the round began. That is usually what you want.
- `# TYPE` says what a series is. Counters, gauges and untyped series are kept as they are. Of
  a histogram or a summary only `_count` and `_sum` are kept; buckets, quantiles and `_created`
  are left out. `# HELP`, other comments and `# EOF` are ignored.
- A line that cannot be read is skipped. The host's log says so once, with the first bad line's
  number; the rest of the output is still written.
- If a series appears twice in one round, the last value is kept.

**What Orchestra adds or refuses.**

- Every point gets `instrument="<name>"` and `project="<key>"`. A `project` or `instrument`
  label in the output is kept as `exported_project` or `exported_instrument` (as Prometheus
  does). Any other label, `machine` and `instance` included, is kept as it is.
- A series named `orchestra_*` is **refused**. The host's log and the instrument's log say to
  rename it.
- A point stamped more than 60 seconds in the future is **refused** by the store (section 4).

**How it runs.** Every `every`, in the repository root, in a process group of its own, with
standard input closed. Its standard error goes to its log. If a run is still going when the next
is due, the next is skipped.

| Environment | Value |
|---|---|
| `ORCHESTRA_REPO` | The repository root. |
| `ORCHESTRA_MACHINE_LOG` | Its log: `<state>/logs/instruments/<name>.log` (the variable's name is shared with launched processes). |
| everything else | Inherited from `orchestra run`, including `PATH`. |

**When a run fails.** A run fails when it exits non-zero, runs past `timeout` (its whole process
group is killed), cannot start (not executable, not found), or prints more than 10 MB. A failed
run writes nothing. The host's log and the instrument's log say why, and
`orchestra_collect_failures_total{collector="<name>"}` counts it (the host's own series,
labelled `machine="orchestra-host"`). The next run is on time.

A run that succeeds adds a line to the instrument's log: `wrote N points`.

**On the Instruments page** it is the instrument `<name>`, kind script, with its command, how
often it runs, its last write, its failures and its log. Nothing is announced on the bus for it,
and it is not on the Machines page.

### 3.2 A `/metrics` URL (`[[scrape]]`)

```toml
[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"
```

The body is read exactly like a script's output (section 3.1), with the same labels and the same
refusals. The request sends `Accept: text/plain;version=0.0.4;q=1.0, */*;q=0.1` and
`User-Agent: orchestra-scrape`. A round fails on any answer but 200, no answer within `timeout`,
or a body over 10 MB.

**Labels.** Orchestra sets `instrument` to the scrape's `name` and sets `project`; a target's own
`instrument` or `project` label is kept as `exported_instrument` or `exported_project`. Every
other label the target serves is kept, `machine` included. Unlike Prometheus, it adds no `job`
or `instance` label of its own. To name an instance, the target must serve an `instance` label
itself (`requests_total{instance="2"} 17`); Orchestra keeps it. Discovery then sums a counter's
instances into one flow per writer. To read several instances, give each its own `[[scrape]]`
with the same metric names and an `instance` label in what each serves.

**On the Instruments page** the scrape is the instrument `<name>`, kind URL. It is not on the
Machines page.

**A program and its scrape.** Run the program under `[[machines]]` and scrape it under
`[[scrape]]`, under the same name if you like (section 7 does this): the launcher keeps it
running and the scrape measures it. They stay two things: a process, which is a machine only by
what it publishes on the bus, and an instrument. A `[[collect]]` may share a `[[machines]]` name
too.

### 3.3 Another store (`[[sources]]`)

When your series already live in a Prometheus-compatible store, Orchestra reads them where they
are, for exactly each discovery's window, and copies nothing into its own store.

#### Auth

Every credential comes from an environment variable or a file **outside the repository**, read
at each request (so a rotated token is picked up). Pages, logs and errors show the kind, where it
comes from and whether it is there, never the value.

| Kind | `auth = ...` |
|---|---|
| None | leave `auth` out |
| Bearer token | `{ bearer_env = "TOKEN" }` or `{ bearer_file = "~/.config/x/token" }` |
| A header | `{ header = { name = "API-Token", value_env = "TOKEN" } }` (or `value_file`) |
| A header that is no secret | `{ header = { name = "X-Scope-OrgID", value = "tenant-1" } }` |
| Several headers | `{ header = [ { name = ..., value_env = ... }, { ... } ] }` |
| Basic | `{ basic = { user = "orchestra", password_env = "PASS" } }` (or `password_file`) |
| mTLS | `{ client_cert = "~/certs/me.pem", client_key = "~/certs/me.key", ca_file = "~/certs/ca.pem" }` |

Kinds combine (a bearer token over mTLS). `ca_file` alone sets the CA for a private server.

The source is **refused**, with the reason, when it has: a literal secret (a `token = "..."`
anywhere, `password` in `basic`, a literal `value` for a header whose name looks secret, such as
`Authorization` or `X-API-Key`); `user:pass@` in the URL; a query string in the URL; a secret file
inside the repository; both `bearer_env` and `bearer_file`; half of mTLS; or a kind not built yet
(`bearer_command`, `oauth2`, `sigv4`). A refused source counts as **missing**, and discovery then
saves no model version until it is fixed.

#### Inference

Every `infer_every` (an hour), Orchestra reads the store's schema and decides what to read. The
result is kept in `<state>/sources/<name>.json`.

- **Families.** Names that differ by a statistic suffix, or by a `stat`, `statistic` or `quantile`
  label, are one family. A histogram's `_count` is its count. A recording rule `...:sum` or
  `...:avg` is a view of its base.
- **Label roles.** Each label is **identity** (one of `identity`: a pod, an instance; or churning;
  or over 50 values), **constant**, or **grouping**. Label spellings are merged by
  `[sources.labels]`.
- **Reporting interval.** Measured per family; no series is read finer than that.

#### Views

From each family, Orchestra proposes views, each a candidate series:

| Family | Views |
|---|---|
| A counter | Increments from raw samples, reset-safe, by each grouping. |
| A plain gauge | The sum, or the max and average for latencies and ratios. |
| A per-pod statistic | Max of max, min of min, average of average (flagged unweighted), max of p95/p99 (flagged an upper bound). Never a sum. |
| A recording rule | Its function, by grouping. |
| Any family | **The count of reporters** (`count by (G) (last_over_time(F[R]))`): a level, with its turnover (pods that started and stopped reporting) as two counters that balance it exactly. So "pods per service" is a stock. |

Each candidate is read over the window. One that returns nothing or does not move is left out.
The rest are scored and taken round-robin across families up to `max_series`, at most
`max_per_family` from one. A `[[series]]` you write is always read.

Series read from a source are named `<prefix>:<name>` and labelled
`machine = <prefix>.<value>` from the `machine` label (a remote `machine` or `source` label is
prefixed too). One that collides with your own store's series is refused.

#### The query script

`[sources.transform] queries` names a script, run from the repository root once per inference
round, with the `timeout` (default 20 s). Any executable works; a `.py` file that is not
executable runs with Orchestra's own Python. Company-specific rules live here, in your
repository, not in Orchestra.

On standard input it gets the candidates as JSON:

```json
{"source": "work",
 "candidates": [{"id": "...", "family": "worker_queue_depth", "stat": null, "view": "sum_by",
                 "group_by": ["service"], "kind": "level", "unit": null, "resolution_s": 15.0,
                 "labels": {"service": {"real": "app", "cardinality": 2, "churn": 0.0, "role": "grouping"}},
                 "query": "sum by (app) (last_over_time(worker_queue_depth[23s]))"}]}
```

On standard output it prints a JSON list of answers:

```json
[{"id": "<candidate id>", "queries": [], "reason": "not needed"},
 {"id": "<candidate id>", "queries": [{"name": "queue_depth", "query": "...", "kind": "level"}]},
 {"id": null, "queries": [{"name": "checkout_queue_jobs", "query": "sum(worker_queue_depth{app=\"checkout\"})", "kind": "level"}]},
 {"id": "<candidate id>", "queries": [...], "pin": true}]
```

- An empty `queries` drops the candidate, keeping `reason`.
- A candidate not mentioned is kept as it is.
- `"id": null` adds a definition of the script's own.
- `pin: true` keeps a definition past the ranking (not past `max_series`).
- Each query needs a `name` (lower-case letters, digits, `_`) and a `query`; `kind` (`level`,
  `counter`, `rate`), `unit` and `labels` are optional.

A non-zero exit, a timeout, or output in another shape fails the whole round; nothing is
half-applied. Every definition it touched records `queries.py@<hash>` as its origin.

#### Commands

```bash
orchestra sources check                                  # each source: credentials present, endpoints answering
orchestra sources infer [--source work]                  # run an inference round; print families, kept, left out
orchestra sources preview 'sum by (app) (up)' --source work [--minutes 30] [--step-s 30]
```

For example (against a test store with two services of three pods each):

```
$ orchestra sources infer
work: 2 families, 4 definitions kept, 7 left out
  family http_requests_total [counter] every 15 s: service=app (grouping, 2 values), job=job (constant, 1 values), pod=pod (identity, 6 values)
  family worker_queue_depth [gauge] every 15 s: service=app (grouping, 2 values), job=job (constant, 1 values), pod=pod (identity, 6 values)
  kept:
    work:http_requests_total by () [increments, counter] score 7.0: http_requests_total
    work:worker_queue_depth by () [sum_by, level] score 6.6: sum(last_over_time(worker_queue_depth[23s]))
    work:http_requests_total by (service) [increments, counter] score 6.269: http_requests_total
    work:worker_queue_depth by (service) [sum_by, level] score 5.869: sum by (app) (last_over_time(worker_queue_depth[23s]))
  left out:
    worker_queue_depth_pods by () [count]: did not move in the window (score 4.0)
    ...
```

Not built yet: command, OAuth2 and SigV4 auth; SQL sources; a Sources page. Counted traffic
(producers and consumers on another system's bus, known by counts) is in
[SPEC §2 and §4.4](SPEC.md).

### 3.4 Counting your tests: the test-report instrument

Orchestra ships one ready-made script instrument, `orchestra/instruments/test_reports.py`. It
reads the reports your test runner writes and prints how many tests there are of each kind (unit,
acceptance, e2e), how they came out, which are flaky and which are confirmed. The growth in tests
is then a stock in the model, and a regression is a rise in failures. It imports nothing from
Orchestra, so you can also copy the file into your repository and run it with any Python 3.12.

**Adopt it in one entry.** Have your runner write JUnit XML (pytest `--junitxml=reports/<run>/tests.xml`,
Jest's `jest-junit`, Maven Surefire, `go-junit-report`) or pytest's report log
(`--report-log`, from `pytest-reportlog`), then:

```toml
[[collect]]
name = "tests"
command = "python -m orchestra.instruments.test_reports --reports reports/*/*.xml --history .git/test-reports.json"
every = "60s"
```

Use a `python` that has Orchestra installed (section 5.5, "Which `python` runs it"), or the copied
file's path. Try it first: `python -m orchestra.instruments.test_reports --reports 'reports/*/*.xml'`.

| Option | Default | Meaning |
|---|---|---|
| `--reports GLOB` | required, repeatable | Report files, relative to the repository root. `~`, `$VARS` and `**` work. |
| `--kind KIND=PATTERN` | repeatable | A kind rule, tried in order before the defaults `e2e=*e2e*`, `acceptance=*acceptance*`, `unit=*`. The pattern is a glob over the test's path (JUnit's `file`, else its `classname` with dots as slashes; pytest's node id file), over `path::name` when it has `::`, or a marker when it starts with `@` (`e2e=@e2e`, from pytest's report log only). The kind `ignore` drops what it matches. |
| `--window N` | 10 | Runs per stream read and judged for flakiness. |
| `--confirm N` | 3 | Consecutive passing runs that confirm a test. |
| `--history FILE` | none | Where the instrument keeps the runs it has seen and its counters. Needed when your runner overwrites one file per run, and for the counters below. Put it outside version control (`.git/` works in a plain clone). |

**Runs.** A report's *stream* is its file name with its digits ignored: `reports/<run>/tests.xml`
files are one stream, and so are `unit-1712.xml` and `unit-1713.xml`. Each file is one run of its
stream, ordered by modification time, and the newest file that can be read is the current run.

**What it prints** (all gauges, one per kind, zero for a kind with no tests):

| Series | Meaning |
|---|---|
| `tests{kind}` | Tests in the current runs. |
| `test_outcomes{kind, outcome}` | By outcome: `passed`, `failed`, `error`, `skipped`. |
| `tests_flaky{kind}` | Current tests that are **flaky**: within the last `--window` runs of their stream they both failed (or erred) and passed, or a report marks them passing on a rerun (Surefire's `flakyFailure`, pytest-rerunfailures' `rerun`, or the same case reported twice in one file, failed then passed). |
| `tests_confirmed{kind}` | Current tests that are **confirmed**: they passed in each of their last `--confirm` runs, consecutively, and none of those runs marked them flaky. A new test is unconfirmed until it has passed that many runs; one failure unconfirms it until it has again. |
| `tests_duration_seconds{kind}` | The time the kind's tests took in their current runs. |
| `test_report_files{state}` | Report files `read` and `unreadable` this round. |
| `tests_added_total{kind}`, `tests_removed_total{kind}` | With `--history` only: counters of the tests that appeared in, or disappeared from, a stream's run since its previous run. They balance `tests`, which is what lets discovery find the test count a stock, with writing tests and deleting them as its flows. |

**Missing and partial reports.** A report that cannot be read (being written, empty, not JUnit or
a report log, over 50 MB) is skipped, counted under `test_report_files{state="unreadable"}`, and
named in the instrument's log; its stream's previous run stands. With no readable report at all
it prints only `test_report_files` (and the counters, with `--history`): a repository that has
not run its tests yet has no test count, not a count of zero. Its arguments wrong, it exits 2,
and the round counts as a failure (section 3.1).

**A merge gate's reports.** The task system's merge gate keeps each run's reports and declares
this instrument for them itself (`orchestra-tasking`, its README).

---

## 4. Name series so discovery can use them

Discovery tells counters from levels by name and by behaviour. It reads every series of the
project (except Orchestra's own plumbing) and decides itself what is a stock or a flow. A good
name says what is measured, with its unit.

| Rule | Why |
|---|---|
| **A counter ends in `_total`**: `jobs_done_total`, `bytes_sent_total`. | Only a `_total` series can be a flow. |
| A counter only goes up. Starting again from zero after a restart is fine. | A drop is read as a **reset**, as in Prometheus. A `_total` series that falls more often than twice or 1% of the steps (whichever is more) is read as a level. |
| **Anything else is a level** (a gauge): how much there is now. `queue_jobs`, `disk_free_bytes`. | A level may be found to be a stock when counters explain its changes. |
| Name it for what it measures, not for its role: `queue_jobs`, not `queue_stock`. | Whether it is a stock is discovery's answer, not yours. |
| **Never start a name with `orchestra_`.** | The prefix is Orchestra's own. An instrument's series with it is refused. Discovery leaves out any such series (except `orchestra_events_total`), saying so. |
| **Never stamp a point in the future.** | Any store refuses a point stamped more than 60 s past now, whoever writes it: it would make its writer look alive until a time not yet come. |
| Keep label values few. | Each label value is a series of its own. |
| Use `instance` for several instances of one measured thing. | Counters that differ only by `instance` are summed into one flow per writer. |
| Write every series on a schedule, even when it has not changed. | Discovery judges a series' writer alive while its writes keep coming. A level written only when it changes looks, between writes, like a writer that stopped. Instruments do this for you. |

The `instrument` label says who measured a series; instruments set it. When you write points
yourself (section 5.2), name the writer with it. No label associates a flow with a machine:
that is inferred from the machines' events ([section 6](#machines-and-flows-hypotheses)).

**Labels that tell series apart.** Two series with the same name and different labels (`disk="/"`
and `disk="/data"`, or two machines' `jobs_done_total`) are two series to discovery. Counters
that differ in a label whose values tell measured levels apart are never merged.

**What discovery needs before a level is a stock.** A level is a stock when counters, added or
subtracted, balance its changes: `Δlevel ≈ Σ inflows − Σ outflows`, with R² ≥ 0.9. In addition:

- the level changed in at least 5 steps of the grid;
- each counter that carries the balance counted at least 5 events;
- the level has been written for at least half of the window's data (a series that started
  ten minutes ago in a sixty-minute window is "too new" and waits);
- its writer (the instrument, or the `machine` label of a series written under that name) has
  not been silent for more than five minutes at the end of the window;
- a level that only takes two values (a flag: busy or not) is a stock only when its balance is
  exact in 97% of steps.

A level no counters balance can still be a stock by a **fitted net flow** (a temperature, a
backlog nobody counts), when its change is explained by its own level or another series better
than by a constant. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full method.

---

## 5. Connect machines

### 5.1 What a machine is

A **machine** is anything outside Orchestra that does actual work: a program, an AI agent, a
person. Orchestra knows it exists because it shows up on the event bus:

- its CloudEvents **`source`**: the machine's id on the bus. Several instances of one machine
  publish as `<machine>/<instance>` (`baker/1`, `baker/2`: one machine, two instances);
- the events it publishes, and the event types it says it listens for;
- how it says it is engaged: **continuous** (runs all the time), **scheduled** (run by the
  clock) or **ad hoc** (a fresh instance per piece of work);
- or, for a machine on another system's bus, as the producer or consumer of the traffic a
  `[[sources]]` definition counts: known by those counts, never by events.

A machine does not produce the metrics, and a series never makes a machine, whatever its labels.
Instruments measure the system ([section 3](#instruments-and-machines)); they are not machines. A
process the launcher runs is **not** a machine by being launched: it becomes one by what it
publishes. A plugin may declare machines (`Plugin.machines`): placeholders that fill in a machine
not seen yet, never override what is observed, and say nothing about flows.

Orchestra's own machine is `orchestra-host`.

A machine comes to exist in one of three ways. Orchestra sees the same thing in each, a `source`
on the bus:

| How the machine comes to exist | Who writes it | Its `source` | Example |
|---|---|---|---|
| The target repository's own code publishes under its own source | the repository's author: a program, a script, a service | the machine's own name, through the events endpoint or the Python helper (`orchestra.events.Events`) | `baker/2`, `machines/billing.sh` as `billing` |
| A bridge relays another system's actors | the bridge (a plugin, `orchestra-bridges`) | each actor of the other system | `person.<login>` for a GitHub user |
| The Agents plugin runs a configured agent | the owner or the Supervisor configures it (role, harness, model, engagement, permissions); the agents' host runs it | the agent's name or instance | `supervisor`, `worker/1` |

The provider is never the machine. A bridge, the agents' host or a task system's scheduler is the
program that publishes *for* machines: it never announces itself, never publishes under its own
name and writes no metrics of its own (its plugin's instrument reads them). On the Machines page
you see `supervisor` and `person.alice`, never `agents` or the bridge. When you write your own
machine, publish as the machine, not as the script or service that hosts it.

### 5.2 Publishing and reading events

A machine publishes and reads events over HTTP, through the **events endpoint** `orchestra run`
serves. Nothing of Orchestra's library is needed: `curl`, or any language's HTTP client, is
enough. (Orchestra's Python helper does the same from Python, below; it is optional.)

**Where it is.** `orchestra run` listens on `127.0.0.1` and a port the system picks
(`[events] listen` sets another) and gives every process it launches two variables:

| Variable | Value |
|---|---|
| `ORCHESTRA_EVENTS_ENDPOINT` | `http://127.0.0.1:<port>` |
| `ORCHESTRA_EVENTS_TOKEN` | The project's token. Send it as `Authorization: Bearer <token>`. |

A program `orchestra run` did not start (one you run by hand, or one a service manager runs)
asks for them:

```bash
eval "$(orchestra events endpoint --env)"     # exports both; exits 1 when orchestra run is not running
```

The token lives in `<state>/events.token`, readable by you only, and stays the same across
restarts of `orchestra run`. The port changes with each start unless `[events] listen` fixes it.

**Publishing.** `POST /events` with one JSON object:

```bash
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "invoice.sent", "source": "billing/1", "subject": "order-42", "data": {"order": 42}}'
```

```json
{"ok": true, "id": "8565e16af5e94072a6b29667bb530108", "duplicate": false, "event": {"specversion": "1.0", ...}}
```

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | What happened: `invoice.sent`. Letters, digits, `.`, `_`, `:`, `-`. Types starting `orchestra.` are Orchestra's: a machine may send only `orchestra.machine.started` (and the older `orchestra.machine.subscribed`). |
| `source` | yes | The machine, or `<machine>/<instance>`. Not `orchestra-host`. |
| `data` | no | Any JSON. Orchestra never reads it. |
| `subject`, `correlationid`, `causationid` | no | Strings, as in the envelope ([§5.3](#53-the-cloudevents-envelope)). |
| `time` | no | RFC 3339 with a timezone (`2026-10-27T18:58:31.043Z`); stored as UTC milliseconds. Default: now. |
| `id` | no | Your id for the event. Default: a fresh one. Send one to make retries safe: a post whose `id` the endpoint has already written is answered `200` with `"duplicate": true` and written once. |

Orchestra adds `specversion`, the `id` and `time` it was not given, and `datacontenttype`. A
CloudEvent in structured mode (the same object, with `"specversion": "1.0"` and
`"datacontenttype": "application/json"`) is accepted as it is. Answers:

| Status | When |
|---|---|
| `201` | Written. The body has the `id` and the whole `event`. |
| `200` | A duplicate `id`: not written again. |
| `400` | Not one JSON object, a missing or malformed field, or a field it does not know (named in `error`). |
| `401` | No token, or the wrong one. |
| `403` | An `orchestra.*` type other than the announcements, or the source `orchestra-host`. |
| `413` | A body over 1 MB. |
| `503` | The bus could not take it. Retry with the same `id`. |

**Reading.** `GET /events` returns the events after an offset, and the offset to read from next:

```bash
curl -sf "$ORCHESTRA_EVENTS_ENDPOINT/events?after=0&types=order.placed,order.cancelled&wait=30" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN"
```

```json
{"ok": true, "events": [{"specversion": "1.0", "type": "order.placed", ...}], "next": 118}
```

| Parameter | Default | Meaning |
|---|---|---|
| `after` | `0` | The offset to read after: `0` is the start of the bus, `end` its current end (only what comes next). |
| `types` | every type | Comma-separated types to return. `next` moves past the events read either way. |
| `wait` | `0` | Seconds (at most 30) to hold the request until a matching event arrives: a long poll. |
| `limit` | `1000` | At most this many events (at most 10,000); read again from `next` for the rest. |

To follow the bus, call it in a loop with `after` set to the last `next`, and keep `next` where
you will find it after a restart. An offset is a cursor: never compute one. On the file bus a
page cut at `limit` may repeat an event after an unreadable line; drop repeats by `id`.

`GET /health` answers `{"ok": true}` without the token, for a program waiting for
`orchestra run` to be up.

A shell machine, start to finish:

```bash
#!/bin/sh
# machines/billing.sh: announce, then answer every order.placed with an invoice.sent.
post() { curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" \
           -H "Content-Type: application/json" -d "$1" > /dev/null; }
post '{"type": "orchestra.machine.started", "source": "billing", "data": {"mode": "continuous", "kind": "program", "listens_for": ["order.placed"]}}'
after=end
while true; do
  page=$(curl -sf "$ORCHESTRA_EVENTS_ENDPOINT/events?after=$after&types=order.placed&wait=30" \
           -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN") || { sleep 1; continue; }
  after=$(printf '%s' "$page" | jq -r .next)
  printf '%s' "$page" | jq -c '.events[] | {type: "invoice.sent", source: "billing", subject: .subject, causationid: .id, id: ("invoice-" + .id)}' |
    while read -r ev; do post "$ev"; done
done
```

(`jq` reads the JSON; the `id` derived from the order's makes a retry after a crash write
nothing twice.)

#### From Python, with the library (optional)

To use the library, the program's Python must be able to `import orchestra`:

- if the project has a `pyproject.toml`, add Orchestra to it:
  `uv add "orchestra @ git+https://github.com/danroblewis/orchestra"` and run the program with
  `uv run python ...`;
- or use the interpreter Orchestra is installed in. After `uv tool install`, that is
  `$(uv tool dir)/orchestra/bin/python`.

Publishing:

```python
import os
from orchestra.config import load_project
from orchestra.events import Events

project = load_project()                        # ORCHESTRA_REPO (the launcher sets it), else the working directory
bus = Events.for_project(project, source="billing/1")   # machine "billing", instance "1"

bus.publish("orchestra.machine.started", {      # announce yourself once, at start
    "mode": "continuous", "kind": "service", "listens_for": ["order.placed"],
    "log": os.environ.get("ORCHESTRA_MACHINE_LOG")})

bus.publish("invoice.sent", {"order": 42}, subject="order-42", correlationid="checkout-7")
```

| Call | What it does |
|---|---|
| `Events.for_project(project, source=...)` | Opens the project's bus (`[events] url`, or `ORCHESTRA_EVENTS_URL`). `source` is the default source of what it publishes. |
| `publish(type, data=None, *, source=None, subject=None, correlationid=None, causationid=None, time=None, id=None)` | Appends one event with the envelope and returns it. `time` and `id` are for an event brought in from another system (it keeps the time it happened there and an id stable across re-imports). |
| `after(offset)` | Every event after `offset`, in order, and the offset to read from next. Follow the bus by calling it in a loop. |
| `end()` | How many events the bus holds. |

Orchestra counts every event by type and source into `orchestra_events_total{type, source}`, so
your events become series discovery can use. These counts are how discovery associates a machine
with a flow, as a hypothesis ([section 6](#machines-and-flows-hypotheses)).

Writing points from Python, instead of serving them (or serve them for a `[[scrape]]`, which
needs no library). A program that does this is acting as an instrument of your own: it is not
on the Instruments page, which lists only the declared ones, and its points make no machine.

```python
import shutil, time
from orchestra.config import load_project
from orchestra.metrics import Point, for_repo

store = for_repo()                              # the store orchestra.toml configures; adds the project label
root = load_project().repo_root
while True:
    store.write([Point("disk_free_bytes", shutil.disk_usage(root).free, time.time(), {"instrument": "telemetry"})])
    time.sleep(30)
```

`Point(series, value, ts, labels)` takes unix **seconds**. Write the series of one moment in one
`write` call. Set the `instrument` label yourself, to say who measured it (discovery groups a
writer's series by it to judge when the writer was alive). Never write to a store URL of your own choosing,
or to the files yourself: `for_repo()` writes where the web UI and discovery read. More, including
how to keep such a program testable, is in [`docs/machines.md`](docs/machines.md#the-python-helper-optional).

### 5.3 The CloudEvents envelope

Every event on the bus carries the CloudEvents 1.0 envelope. `orchestra.events.envelope` writes
it; Orchestra reads the envelope and **never your `data`** (except for its own event types, such
as `orchestra.machine.started`).

| Field | Required | What it is |
|---|---|---|
| `specversion` | yes | `"1.0"` |
| `id` | yes | Unique. A fresh hex UUID unless you give one. |
| `type` | yes | What happened: `invoice.sent`. Orchestra's own types start with `orchestra.`. The part up to the first dot is the event's family on the Machines page. |
| `source` | yes | The machine, or `<machine>/<instance>`. |
| `time` | yes | RFC 3339 with milliseconds, UTC: `2026-10-27T18:58:31.043+00:00`. |
| `subject` | no | What the event is about (an order, an issue). The Machines page infers hand-offs from it: when one machine acts on a subject after another did. |
| `correlationid` | no | The request or piece of work it belongs to. |
| `causationid` | no | The event that caused it. |
| `datacontenttype` | with `data` | `"application/json"`. |
| `data` | no | Your payload. It belongs to the machines that use it. |

An event as it lands in the file bus:

```json
{"specversion": "1.0", "id": "8565e16af5e94072a6b29667bb530108", "type": "invoice.sent",
 "source": "billing/1", "time": "2026-10-27T18:58:31.043+00:00", "subject": "order-0",
 "datacontenttype": "application/json", "data": {"order": 0}}
```

### 5.4 Announcing a machine: `orchestra.machine.started`

An instance announces itself when it starts by publishing `orchestra.machine.started` from its
own `source`. It is a plain event: send it like any other, over HTTP or with the helper.

```bash
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d "{\"type\": \"orchestra.machine.started\", \"source\": \"billing/1\",
       \"data\": {\"mode\": \"continuous\", \"kind\": \"service\", \"listens_for\": [\"order.placed\"],
                \"log\": \"$ORCHESTRA_MACHINE_LOG\"}}"
```

This is Orchestra's own event type, so Orchestra reads these fields of its `data`:

| Field | Type | Meaning |
|---|---|---|
| `mode` | string | `continuous`, `scheduled` or `ad hoc`. Per instance; the latest stands. |
| `kind` | string | `program`, `agent`, `person` or `service`. Per instance; the latest stands. |
| `listens_for` | array of strings | The event types it reads. Draws arrows on the event map. |
| `log` | string | Its log file. Shown in its dialog only when the real path is a regular file inside the repository or the state directory. |
| `package` | string | The package it belongs to (a plugin draws its card). |
| `name` | string | The name to show it by. |
| `group` (or `team`) | string | A label that groups it near others on the page. It never separates it. |

Anything else in `data` (strings, numbers, booleans, lists) is passed to its package's card
unread. The older `orchestra.machine.subscribed` with `data.types` is read too.

You announce only what Orchestra cannot observe. Everything else (what it publishes,
when it was last seen) is observed. Instruments are not machines and are not announced; the
host's announcements for them before 2026-10-27 (with `data.collector`) are ignored.

### 5.5 Processes the launcher runs (`[[machines]]`)

`orchestra run` starts each `[[machines]]` entry, and each plugin's processes, and keeps them
running.

**How it starts one.** In the repository root, in a process group of its own, with standard input
closed and standard output and error both going to `<state>/logs/machines/<name>.log`. Its
environment is `orchestra run`'s, plus:

| Variable | Value |
|---|---|
| `ORCHESTRA_REPO` | The repository root. |
| `ORCHESTRA_MACHINE_LOG` | Its log file. |
| `ORCHESTRA_EVENTS_ENDPOINT`, `ORCHESTRA_EVENTS_TOKEN` | The events endpoint and its token ([§5.2](#52-publishing-and-reading-events)), unless `[events] listen = "off"`. |
| `PYTHONUNBUFFERED` | `1`, so a Python program's output reaches its log at once. |

`python` in a command is whatever `python` is on the `PATH` `orchestra run` was started with.
Name an interpreter by its full path, use `python3`, or use `uv run python ...` when the
project's `pyproject.toml` lists what the program needs.

**What happens when it exits.**

```mermaid
stateDiagram-v2
    [*] --> waiting: declared in orchestra.toml
    waiting --> running: its start time comes
    running --> waiting: exits and restart applies
    running --> exited: exits and restart does not apply
    running --> gave_up: 5th failure in a row
    running --> stopped: entry removed or changed, or orchestra run stops
    gave_up --> waiting: entry changed, or orchestra run restarted
    exited --> waiting: entry changed, or orchestra run restarted
    stopped --> [*]

    note right of waiting
        pause 1 s after a run of 60 s or more,
        else 2, 4, 8, 16 ... up to 60 s
    end note
    note right of stopped
        SIGTERM to its process group,
        SIGKILL after stop_grace
    end note
```

- **Restart applies** with `restart = "always"` (any exit) or `"on-failure"` (a non-zero exit).
  With `"never"`, or `"on-failure"` and exit code 0, it stays exited.
- **The pause** before starting again doubles with each **quick** exit (within 60 seconds of
  starting): 2 s, 4 s, 8 s, 16 s, ..., up to 60 s. A run that lasted 60 seconds or more resets
  the count, and the next pause is 1 s.
- **Giving up.** After five **failures** (non-zero exits, or a command that cannot start, counted
  as code 127) in a row, each within 60 seconds of starting, it is given up on. A program that
  exits 0 is never given up on: it is started again after the pause. Giving up is said in the
  host's log, in the process's log
  (`gave up after 5 failures in a row, each within 60 s of starting`), and on the bus
  (`orchestra.process.gave_up`). It is tried again when its entry changes or `orchestra run`
  restarts.
- **A change to `orchestra.toml`** is seen within a second: an entry added starts, one removed
  stops, and one whose `command` or `restart` changed is stopped and started again. A change to
  `stop_grace` alone applies the next time it is stopped. A change to the program itself takes
  effect at its next restart.
- **Stopping.** Stopping `orchestra run` stops every process group it started: SIGTERM, then
  SIGKILL after each one's `stop_grace`. A host started again after being killed first stops
  what the previous one left running.

The host publishes, from `orchestra-host`, `orchestra.process.started` (`name`, `pid`, `command`,
`owner`), `orchestra.process.exited` (`name`, `pid`, `code`, `restart_in`) and
`orchestra.process.gave_up` (`name`, `code`, `failures`). Every process, with its state
(`running`, `waiting`, `exited`, `gave_up`), restarts, last exit code and log, is in
`runtime.json` under `processes` and on the Core page.

A plugin's processes are named `<plugin>.<name>` in the record, on the Core page and in their
logs' names, so they never collide with yours.

### 5.6 How the Machines page judges a machine

The Machines page lists every machine seen on the bus, with its instances, and the machines
known by counted traffic from another store and those a plugin declares. A series labelled
`machine=X` never makes a machine `X`, and instruments are not here (they are on the
Instruments page).

| Shown | Where it comes from |
|---|---|
| **Machine and instance** | The event `source` (`<machine>/<instance>`). |
| **Kind** | `data.kind` from each instance's latest `orchestra.machine.started`. When instances differ: `agent ×2, program ×1`. Empty for a machine that never announced (the host is `program`). |
| **Mode** | `data.mode` the same way. |
| **Last seen** | The later of its latest event and its latest write to a series labelled with it. An event stamped in the future counts as seen when it was read; a point stamped more than 60 s ahead is not counted. |
| **Active** | See below. |
| **Metrics** | The series labelled `machine=<id>`, if any exist, and series from another store that the latest discovery bound to it. They are listed on the card of a machine seen otherwise; they never make one. |
| **Publishes, listens for** | The event types it published (counted), and its announced `listens_for`. |

**Active.** An instance is active while either:

- its last event is more recent than 2.5 times its **event cadence**, or
- its last write is more recent than 2.5 times its **write cadence**,

and never for less than 2 minutes. A cadence is observed, never announced: the median gap
between its last nine events (announcements left out, since they come in bursts) or its last
nine writes, counted at most as a day. A machine is active while any of its instances is. So a
machine scheduled every 15 minutes stays active between its runs, and a machine that stops goes
quiet after a few of its own beats.

A machine known only by counted traffic from another store is active within five minutes of its
last nonzero count.

The web server refreshes the bus index every 5 seconds and the list of series (with each
machine's latest write) every 60 seconds, so a machine known only by its writes may show a
last-seen up to a minute old.

---

### 5.7 Marking a change to the system: `system.changed`

When a machine changes how the system works (it edits a prompt or a role, changes the
configuration, adds a worker kind, deploys), it says so, and a new **era** begins. Each era is
discovered from its own data: after the change it is a different system, and what came before is
not evidence for it. The previous era's model is its prior until the new era has enough data of
its own, and the Dynamics page and `GET /eras` (section 5.9) say what changed at the boundary: each
rate before and after, with its uncertainty, and what appeared or disappeared.

Publish `system.changed` from the machine that made the change, with what it changed as the
`subject` if you like. Orchestra reads only the envelope; `data` is yours:

```bash
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "system.changed", "source": "deployer", "subject": "billing",
       "data": {"version": "2.4.1", "why": "faster invoicing"}}'
```

Events you already publish can begin eras too, without a new event: name them in `[discovery]
eras_from` (section 2), by type and optionally by source and subject:

```toml
[discovery]
eras_from = ["config.changed", "role.changed:source=supervisor", "deploy.finished:subject=billing*"]
```

The host records each era once (`e1`, `e2`, ...) and announces it as `orchestra.era.started`
(`subject`: the era; `causationid`: your event's id). Orchestra's own events never begin one.

**What Orchestra says about its model.** Machines can listen for these, published by
`orchestra-host`:

| Type | When | `data` |
|---|---|---|
| `orchestra.era.started` | An era began. | `era`, `start`, `label`, `cause` (`id`, `type`, `source`, `subject`) |
| `orchestra.model.changed` | Stocks, flows or loops were added or removed, and the new structure held for `announce_hold` discoveries in a row; at most one per `announce_gap`. A flip that comes back is never announced. | `added` and `removed`, each `{stocks, flows, loops}` as ids; `era`, `held`, `first_seen` |
| `orchestra.model.diverged` | A stock's measured level stayed outside the band the model predicted for at least `diverge_after`. | `stocks`: each with `stock`, `gap` (how far from the predicted level, in half-widths of the band), `level`, `central`, `lo`, `hi`, `since`; `diverged`: every stock diverged now; `era`, `era_start` |
| `orchestra.model.returned` | A diverged stock is back inside its band. | as `diverged`, with `diverged_since` |

A divergence soon after an era began is expected (the change did something); one with no era
behind it is a lead: something changed that nobody announced.

### 5.8 Saying what a change will do: predictions

Before a machine changes the system it can say what the change will do, and Orchestra tells it
afterwards whether it did. This is the intended-effect test: the change's success is decided by
what the system did, not by the machine that made it. The steps:

1. **Choose the id your change event will carry**, any unique string.
2. **Record the prediction**: publish `orchestra.prediction.made` from your machine's `source`,
   with `data`:
   - `change`: that id;
   - `expect`: what the change will do, as edits of the model (the ids are the flows' and stocks'
     on the Dynamics page):

     | Edit | Means |
     |---|---|
     | `{"flow": "jobs_arrived_total", "factor": 2}` | the flow's rate doubles (`"param": "k"` for one of its numbers; `0` for the flow to go) |
     | `{"flow": "jobs_done_total", "unchanged": true}` | this flow does not change |
     | `{"flow": "jobs_done_total", "equation": "k * min(jobs_waiting, 4)", "params": {"k": 0.5}}` | the flow's whole rate becomes this equation (section 5.9's language); judged by whether it predicts what the new era counts |
     | `{"flow": "f", "appears": true}`, `{"stock": "s", "disappears": true}` | a part appears or disappears (`loop` too) |
     | `{"from": "jobs_waiting", "to": null, "appears": true}` | a new flow between two stocks (`null`: outside); `equation` and `params` may say its rate |
     | `{"stock": "jobs_waiting", "below": 6}` | the stock's mean level over the horizon's second half (`above` too) |

     `[]` is the **null test**: the change (a refactor, an upgrade) should change nothing.
   - `horizon_s` (or `horizon`, such as `"30m"`): how long after the change to judge it. Long
     enough for the flows you name to count a few dozen events in the new era;
   - optionally `trajectories`: your own forward run of the stocks from the change
     (`{"t": [seconds after the change], "stocks": {"jobs_waiting": {"central": [...], "lo": [...],
     "hi": [...]}}}`). Without it Orchestra runs the previous era's model with your edits.

   Committing an experiment (section 5.9) does this step for you, from the experiment's edits and
   its forward run.
3. **Make the change**, and publish the event that begins its era (`system.changed`, or one
   `[discovery] eras_from` names) with `"id"` set to the id you chose.

```bash
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "orchestra.prediction.made", "source": "deployer", "subject": "billing",
       "data": {"change": "deploy-2.4.1", "expect": [{"flow": "invoices_sent_total", "factor": 1.5}], "horizon": "2h"}}'
# ... deploy ...
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "system.changed", "source": "deployer", "id": "deploy-2.4.1", "subject": "billing"}'
```

From Python, in a plugin or a machine that uses the library:

```python
from orchestra.config import load_project
from orchestra.events import Events
from orchestra.sd.predictions import Predictions

project = load_project()
mine = Predictions(project, source="deployer")
made = mine.record([{"flow": "invoices_sent_total", "factor": 1.5}], horizon="2h", subject="billing")
Events.for_project(project, source="deployer").publish("system.changed", {"version": "2.4.1"}, id=made["change"])
# later
mine.get(made["id"])["status"]      # "waiting", then "judged"
mine.verdict(made["id"])            # the verdict, as below
```

**The verdict.** The host judges the prediction after its first discovery at least the horizon
after the change, and publishes `orchestra.prediction.judged` (`source` `orchestra-host`,
`subject` and `causationid` the prediction's event id, `correlationid` the change's id). Listen
for it, or read `GET /predictions` (section 5.9), `orchestra sd predictions` or the Dynamics
page, under the era. `data.verdict` is:

| Verdict | Meaning |
|---|---|
| `passed` | What you predicted happened, and the stocks moved as the model said they would. |
| `no effect` | A predicted edit did not appear: the change did not do what you thought, or did not take effect. |
| `side effect` | Something you did not predict changed (`data.unpredicted` names it, with its numbers), or a predicted flow changed by another amount. |
| `model wrong elsewhere` | What you predicted happened, but a stock did not move as the model said: the model of the rest of the system is wrong there (`data.stocks.rows`, `out`). |
| `interrupted` | Another change began a new era before the horizon. `data.partial` is what could be judged until then. |
| `undecided` | The new era still had no evidence of its own on a predicted flow at twice the horizon. |

`data.expectations` gives each edit's `status` (`met`, `absent`, `different`, and for levels
`missed`) with the numbers it was judged by: a flow's number before and after, `z` (the change
over its standard error) and, for a factor, the predicted value and how far the result is from it;
for an equation, `law` (the events it predicts over the era, the events counted, and `z`) and
`old_law` (the same for the previous era's equation).
`data.false_change` says how often a change is reported where there was none: the threshold
(`z`, 2), the nominal rate (`nominal`, 4.55% a number) and, when the era before was long enough,
the share of flows flagged between its two halves (`measured`). A null test is worth what that
rate is. `data.late` is true when the prediction was made after its change began.

### 5.9 Asking the model: experiments

A machine (an AI agent, or any program) can ask the model what a change would do before making
it, check whether an equation explains what happened, and ask what would have had to be different
for an outcome to have been. It does so with an **experiment**: a copy of the model it edits and
runs, which changes nothing in the system. The host serves experiments beside the events
endpoint, with the same address and token (section 5.2), so any language with an HTTP client can
use them; from Python, `orchestra.sd.experiments.api.Experiments` does the same. The web UI shows
them (section "What the owner sees", below) and cannot change them.

**Read first.** Everything answers JSON, `{"ok": true, ...}`:

```bash
api() { curl -s -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" "$@"; }
api "$ORCHESTRA_EVENTS_ENDPOINT/model"                 # stocks, flows with their equations, inputs, loops
api "$ORCHESTRA_EVENTS_ENDPOINT/eras"                  # the eras, and what changed at the last boundary
api "$ORCHESTRA_EVENTS_ENDPOINT/language"              # the equation language: functions, rules, limits
api "$ORCHESTRA_EVENTS_ENDPOINT/series?ids=jobs_waiting,jobs_done_total&span_s=3600"            # summaries
api "$ORCHESTRA_EVENTS_ENDPOINT/series?ids=jobs_waiting&span_s=86400&points=1&limit=500"         # and points, paged
api "$ORCHESTRA_EVENTS_ENDPOINT/observability"         # which stocks what is measured determines
api "$ORCHESTRA_EVENTS_ENDPOINT/predictions"           # predictions and their verdicts
```

`/model` gives each flow as a machine would write it:

```json
{"id": "jobs_done_total", "from": "jobs_waiting", "to": "jobs_reviewing",
 "equation": "k * jobs_waiting", "params": {"k": 0.58}, "origin": "fitted", "method": "poisson-mle",
 "reads": {"stocks": ["jobs_waiting"], "inputs": [], "params": ["k"], "functions": []},
 "spread": 0.05, "measured": true}
```

`/series` answers at most 5,000 points a series and 20,000 in all; a series cut short has
`next`: ask again with `after=<next>`.

#### The equation language

A flow's rate is an expression in Python's syntax, per the model's time unit (`time_unit` in
`/model`), over:

- **stock ids** (their level now), **measured inputs** (their value now) and **parameters**,
  named numbers you give beside it (`{"equation": "k * jobs_waiting", "params": {"k": 0.6}}`), and
  plain numbers. An id that is not a plain name, or that is both a stock and an input, is written
  `stock("id")` or `input("name")`;
- `+ - * / **`, unary `-`, brackets, and one comparison (`<`, `<=`, `>`, `>=`, `==`, `!=`), which
  is 1 when true and 0 when false;
- the functions `min(a, b, …)`, `max(a, b, …)`, `abs`, `exp`, `log` (natural), `sqrt`,
  `clip(x, lo, hi)`, `if_then_else(c, a, b)`, `zidz(a, b)` (a / b, or 0 when b is 0),
  `lookup(x, [[x0, y0], [x1, y1], …])` (straight between the points, held beyond them),
  `smooth(x, tau)` (x smoothed over tau time units), `delay(x, tau)` (x as it was tau time units
  ago), `observed()` (the flow's own measured rate: what was counted in a replay, the last ten
  minutes' mean going forward), and SD Lab's `ceil`, `floor`, `integer`, `power`, `modulo`,
  `quantum`, `ln`, `log10`, `sin` and the rest, `xidz`, `and_`, `or_`, `not_`.

A rate below 0 is taken as 0 (a flow moves material one way), a rate that is not a number
(`log(0)`) as 0 and reported, and a stock's outflows share what it holds. **Units are not
checked**: `k * waiting` is per hour if the model's time unit is the hour. Nothing you write is
run as code: the text is parsed into a fixed set of operations, and every name is checked against
the model (`POST /equations/check` with `equation` and `params` says whether it parses and what it
reads). Examples:

| Rate | Means |
|---|---|
| `c` | constant |
| `k * waiting` | proportional to a stock |
| `c + k * demand` | linear in an input |
| `k * min(waiting, 2 * workers_free)` | capacity-capped: at most two jobs per free worker |
| `k * waiting * (1 - backlog / cap)` | slowing as a backlog fills |
| `(target - level) / tau` | closing a gap |
| `rate * delay(approved, 2)` | following another level two time units late |
| `observed()` | as measured: no equation |

#### An experiment's life

```bash
E=$(api -X POST "$ORCHESTRA_EVENTS_ENDPOINT/experiments" \
     -d '{"source": "curator", "title": "pair reviews", "purpose": "does pairing halve review time?"}' | jq -r .experiment.id)
api -X POST "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/edits" -d '{"source": "curator", "edits": [
  {"op": "replace_flow", "id": "jobs_reviewed_total", "equation": "k * min(jobs_reviewing, 2 * reviewers)", "params": {"k": 0.8}},
  {"op": "add_stock", "id": "rework", "initial": 0},
  {"op": "add_flow", "id": "sent_back", "from": "jobs_reviewing", "to": "rework", "equation": "k * jobs_reviewing", "params": {"k": 0.05}}]}'
api -X POST "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/runs" -d '{"source": "curator", "mode": "forward", "horizon_s": 7200}'
api -X POST "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/runs" -d '{"source": "curator", "mode": "replay", "span_s": 86400}'
api "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/diff"
```

An experiment starts as a copy of the current era's latest model (`"version": N` for a saved
version). It is its owner's, the `source` that made it: only the owner edits, commits or discards
it; anyone may read and run it.

**Edits** come in batches (`edits`), applied together or not at all. A refused batch answers 422
with the reason and the edit's `index`, and leaves the draft as it was.

| `op` | Fields | Does |
|---|---|---|
| `add_flow` | `id`, `from`, `to` (a stock, or `null` for outside), `equation`, `params` | a new flow |
| `replace_flow` | `id`, `equation`, `params`, optionally `from`, `to` | the flow's whole equation (and ends) |
| `remove_flow` | `id` | the flow is gone |
| `set_params` | `flow`, `params` | some numbers of the flow's equation |
| `add_stock` | `id`, `initial` | a hidden stock (no series measures it), starting at `initial` |
| `remove_stock` | `id` | the stock is gone; no flow may still end at it or read it |
| `set_level` | `stock`, `level` (`null` clears) | where a forward run starts the stock |
| `set_input` | `input`, `scenario` | what a forward run assumes of an input: `{"kind": "hold"}`, `{"kind": "value", "value"}`, `{"kind": "scale", "factor"}`, `{"kind": "step", "at_s", "value"}`, `{"kind": "ramp", "to_s", "value"}`, `{"kind": "series", "points": [[s, v], …]}` |
| `load_model` | `model` | the whole draft: `{"stocks": [{"id", "initial"?}], "flows": [{"id", "from", "to", "equation", "params"}]}` |

Every equation an edit writes is recorded as `declared` (an assumption until it is fitted), with
the experiment and your source as its method.

**Runs** (`POST .../runs`, `mode` and its options; each run is kept, `GET .../runs/<id>`):

- **`forward`** (`horizon_s`, `members`, `seed`, `bounds`: `{"stock": [lo, hi]}`, `stocks`,
  `points`): the base model and your draft from the levels now. Per stock and flow: `base`,
  `experiment` and (for stocks) `difference`, each `{central, lo, hi}` at the times `t` (seconds
  from now): the run with the numbers as written, and the 10th–90th percentile of runs with every
  rate perturbed by its recorded error. Your own equations are declared, so their band is ±50%
  until the model fits them. `limits`: where a stock reaches 0 or leaves your bounds, and whether
  your change brings it. `not_trusted`, with reasons: read them before you believe the numbers;
- **`replay`** (`start` and `end`, or `span_s` back from now, or `era`): both models over a past
  window, on its measured inputs, from the levels measured at its start, against what was
  measured. Per stock: `measured`, `base`, `experiment` and `error` (how far each run misses, in
  the level's own spread). Per counted flow: `one_step`, the equation evaluated on the measured
  levels against what its counter counted (`deviance`, lower is better; `d2`, the share of a
  constant rate's misfit it explains), and `versus_base`. Use it to check that an equation
  explains what happened, not just the outcome you want, and to replay last month with your
  equations;
- **`inverse`** (a window, `targets`, `hold`, `new_flows`, `max_changes`, `deadline_s` up to 300,
  `alternatives`, `check`): "if we ran this window again with these outcomes, what else would
  have had to be true?" Targets are `{"stock": S, "scale": 1.5}` (its mean, ×1.5 of the base
  replay's), `{"stock": S, "level": x}`, `{"stock": S, "below": x}` / `"above"` (its highest or
  lowest level), `{"flow": F, "scale": r}` or `{"flow": F, "total": x}`; holds are `{"flow": F}`
  (its equation stays) and `{"series": X}` (a stock's or flow's history stays). The solver looks
  for the fewest changes to the draft's numbers and rates (and, with `new_flows`, a new inflow or
  outflow of a target stock) under which the replay meets the targets within 5%. It answers with
  `reached` (or the best it could do), `changes`, `side_effects` (what else would have moved, by
  how much), `alternatives` (other changes that do as well), `uniqueness` (whether the data the
  solved model would make, discovered again, shows the same changes) and `ambiguous`, and a new
  draft of yours with the changes in it (`experiment`). It looks one change ahead, so two changes
  that only work together are not found; it optimises what you name, so hold what must not move.

**Commit** turns the experiment into a prediction of the change you are about to make (section
5.8): your edits become the expected edits, and a forward run over the horizon the predicted
trajectories. Then make the change, carrying the returned `change` id:

```bash
api -X POST "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/commit" -d '{"source": "curator", "horizon": "2h"}'
# ... make the change, publishing system.changed with "id": the returned change ...
api "$ORCHESTRA_EVENTS_ENDPOINT/experiments/$E/prediction"     # later: the verdict
```

A flow whose numbers alone you changed is judged by how its fitted numbers move; a flow whose
equation you rewrote, by whether your equation predicts what the new era counted. Hidden stocks
you added are not judged directly (no series measures them), only through the stocks they move.
`POST .../discard` ends an experiment you will not commit.

From Python:

```python
from orchestra.config import load_project
from orchestra.sd.experiments.api import Experiments

x = Experiments(load_project(), source="curator")
e = x.create("pair reviews")["experiment"]
x.edit(e["id"], [{"op": "set_params", "flow": "jobs_reviewed_total", "params": {"k": 0.8}}])
r = x.run(e["id"], "forward", horizon_s=7200)["run"]["result"]
made = x.commit(e["id"], horizon="2h")      # publish your change with id made["change"]
```

#### What the owner sees: the Experiments page

The web UI's **Experiments** page (`/experiments`) lists every experiment: the machine that made it
(a link to its card on the Machines page), its title and purpose, whether it is a draft, committed
or discarded, the model it was copied from (version and era), its latest run and when, and, once
committed, its prediction's verdict. Filter it by machine, status or era; an era's experiments are
those made on its model and those predicting the change that began it, and the Dynamics page links
each era to them.

Opening one shows, from the top:

- **the prediction it became**, if committed: what it expects, the `change` id, the era the change
  began, and the verdict once judged (passed, no effect, side effect, model wrong elsewhere,
  interrupted) with the numbers behind it;
- **its edits against the base**: each flow replaced, added or removed, its equation and numbers
  before and after side by side (a number that changed in bold); stocks added and removed; input
  scenarios and starting levels;
- **its runs**, one at a time (the newest first; `#<run id>` in the address opens one). A forward
  run puts its warnings first: the limits hit (a stock reaching 0 or leaving a bound, and whether
  the experiment brings it) and everything not trusted, with why. Then a chart per stock: the base
  (blue) and the experiment (orange), each with its 10–90% band, from "now" over the horizon, and
  the measured level (grey) for the hour before, and since, so a forecast can be held against what
  happened. A replay charts each stock measured against both simulations, with each run's error,
  and lists every counted flow's fit, marked ▲ better, = same or ▼ worse than the base. An inverse
  run shows what was asked and held, the changes found (and the new draft's diff), the side
  effects largest first, alternatives that would do as well, the uniqueness check, and a red
  **Ambiguous** warning when the answer is not the only one;
- **the edit log**: every batch in order, a refused batch marked with the edit that failed and
  why, so you see how the machine got there.

The pages follow your browser's light or dark setting, work on a phone, and change nothing.

| Status | Means |
|---|---|
| 400 | the request is malformed (a missing `source`, an unknown option) |
| 403 | the experiment is another machine's |
| 404 | no such experiment, run, version or series |
| 409 | the experiment is committed or discarded |
| 422 | an edit or equation was refused (`error`, `index`) |

## 6. What Orchestra does with your data

```mermaid
sequenceDiagram
    autonumber
    participant S as Your service
    participant H as orchestra run
    participant M as Metrics store
    participant D as Discovery
    participant V as Model store
    participant W as Dynamics page

    loop every [[scrape]] every
        H->>S: GET /metrics
        S-->>H: jobs_received_total 74, jobs_done_total 69, queue_jobs 5
        H->>M: write points with instrument=#quot;queue#quot;, project=#quot;#lt;key#gt;#quot;
    end
    loop every [discovery] every
        D->>M: read every series over the window
        D->>D: sample each on the step grid, mark when its writer was alive
        D->>D: tell counters (_total) from levels
        D->>D: balance each level, Δqueue_jobs ≈ received − done, R² ≥ 0.9, so a stock
        D->>D: fit each flow's rate (Poisson likelihood, the best form by AIC)
        D->>D: associate machines with flows by their events on the bus, as hypotheses
        D->>V: write the discovery, and a new version if the structure changed
    end
    W->>V: read the latest discovery and the saved versions
    W->>M: read levels and history (through the web server's caches)
```

**Discovery in brief.** The host rediscovers every `[discovery] every`, over the last `window`,
on a grid of `step`:

1. Every series is sampled onto the grid at its own resolution, and marked with when its
   writer was alive.
2. A level whose changes counters balance is a **stock**. Each balancing counter is a **flow**:
   from one stock to another, or from or to outside (a cloud on the page).
3. Each flow's rate is fitted by maximum likelihood: a constant, proportional to its source
   stock, or linear in another stock or measured level (an **influence**, which closes feedback
   loops). Every equation records its origin (`fitted`, `discovered` or `declared`) and quality.
4. Machines are **associated** with flows, only as hypotheses inferred from their events on the
   bus (below).
5. Everything else is **left out, with the reason**, recorded in the model.
6. The window never reaches back past the start of the current **era** (section 5.7): each era
   is discovered from its own data, with the era before as its prior, and compared with it.

With an SD Lab strategy, conservation runs first; the SD Lab strategy then explains only what
counters do not balance exactly. A hidden stock or an unexplained flow it finds is a question
about the system: something in it is not measured or not understood yet. Depth:
[`ARCHITECTURE.md`](ARCHITECTURE.md) and [SPEC §4.3](SPEC.md).

### Machines and flows: hypotheses

System dynamics has no machines. A flow is a measurement of the system; which machine's work it
reflects is not known, and inferring it is what Orchestra is for. A machine may be associated
with no flow, one or several, and several machines with one flow. **Nothing declares an
association**: no setting in `orchestra.toml` and no plugin. Who wrote a flow's counter (its
`instrument` label, or a `machine` label) is never read for it, and neither is the `machine`
label of a counted-traffic counter from another store.

Discovery forms a hypothesis from Orchestra's count of the bus, `orchestra_events_total`, in one
of two ways:

| `by` | When |
|---|---|
| **its own events** | The flow's counter is itself one machine's count of one event type. |
| **events on the bus** | A machine's events of one type (its instances summed) match the counter's increments step by step, at the same step or one step either way: equal in at least 90% of the steps either moved (confidence: that share), or correlated at least 0.9 with totals within a factor of 2 (confidence: the correlation times the smaller ratio of the totals). |

Orchestra's own event types (`orchestra.*`) are never candidates. Each hypothesis is kept in the
flow's evidence (`evidence.machines.hypotheses`) with the machine, origin `inferred`, `by`, the
event type and source, the share of equal steps, the correlation, the lag, the counts, a
sentence saying why, and a `confidence` from 0 to 1. Every machine that matches is a hypothesis.
A flow with none reads **no machine associated yet**. A hypothesis never changes a flow's
equation or the model's stocks and flows. In the model, a machine's `attributed` lists the flows
it is a hypothesis for, and `observed_by` the event counts that matched.

Its limits: a match is a correlation in time, not a cause; two machines reacting to the same
events both match; and discovery may not tell apart two similar flows between the same stocks,
so a hypothesis may belong to a flow's twin.

A machine that publishes nothing is never associated with anything. To let Orchestra relate a
machine's work to the flows, have it publish an event for each piece of work it does
(section 5.2).

A model version saved before 2026-10-27 keeps its old association, read from the counter's
`machine` label, and the page marks it "label (before 2026-10-27)".

**Model versions.** There is one model per project. Each discovery is kept as the latest
(`model/discovered.json`). When its structure differs from the current version (stocks, flows,
their ends), and it found at least one stock, and no `[[sources]]` source was missing, it is saved
as a new version, `model/vNNNN.json`. The highest is current; past versions stay readable.

```bash
orchestra sd discover [--minutes 60] [--step-s 30] [--strategy conservation]   # discover now, print the result
orchestra sd show [--version N]                                                # stocks, flows, machines
orchestra sd versions                                                          # every saved version
orchestra sd fit [--step 1]                                                    # refit the current model's flows
```

`GET /observability` on the events endpoint (and `/api/dynamics/observability` on the web) answers, for the latest model:
can each stock's level, a hidden stock's above all, be determined from the series and counters
there are? For each it says how (through which flow and which instrument), or, when it cannot,
which new series or counter would make it determinable. It also lists numbers that only show in
combination and which stocks the flows machines are hypothesised to affect connect to. The model
is linearised at the last hour's mean levels, so the answers are local, and it names the flows for
which that matters.

`orchestra sd discover` is an observation: it reads the metrics and may save a version, and
changes nothing else. One discovery runs at a time per project; the host skips its turn while
the CLI or the page is discovering.

**The Dynamics page** (`/dynamics`) shows the model as a stock-and-flow diagram: each stock with
its level, a tank fill and a sparkline; a valve on each flow with its equation; in the flows
table, the machines associated with each flow (as hypotheses, with confidence) or "no machine
associated yet";
influences as dashed + or − links; the feedback loops, marked balancing or reinforcing. Clicking a
stock or a flow opens a drawer with its history, its balance (or fitted net flow), the flow's
observed rate against its equation, each machine hypothesis with why, and a simulation from now over a horizon you choose. The page
says what the window and step are, lists what was left out and why, and steps through the saved
versions. **Rediscover now** reruns discovery in the background, optionally with another
strategy for that run.

**What if.** A machine asks the model what a change would do through an experiment (section
5.9): any change to the equations, not only a flow scaled. The `orchestra sd whatif` command and
`POST /api/dynamics/whatif` were removed on 2026-10-27.

The other pages: **Machines** (section 5.6, with the event map and each machine's dialog),
**Instruments** (section 3: each instrument's health and log), **Core** (the host and its processes, the bus and the store probed live, a series catalogue, a
PromQL editor, an events explorer, and every log), and the **Dashboard** (what runs now and the
host's resources). The UI is read-only: nothing on it changes your machines.

---

## 7. A worked example: a queue

A small service with a queue: jobs arrive at random, one worker takes them off. It serves two
counters and a level on `/metrics`. By the end, the Dynamics page shows the stock `queue_jobs`
with an inflow `jobs_received_total` and an outflow `jobs_done_total`, measured by the scrape
`queue`. The service publishes no events, so no machine is associated with either flow yet.

### Files

Start in an empty git repository:

```bash
mkdir queue-demo && cd queue-demo && git init
orchestra init
mkdir machines
```

`machines/queue_service.py` (standard library only):

```python
"""A small service with a queue: jobs arrive at random, one worker takes them off.

It serves its measurements on http://127.0.0.1:9397/metrics in the Prometheus text format.
"""
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
queue = 0          # jobs waiting now: a level
received = 0       # jobs that ever arrived: a counter
done = 0           # jobs that ever finished: a counter


def arrivals():
    global queue, received
    while True:
        time.sleep(random.expovariate(1.0))          # about one job a second
        with lock:
            queue += 1
            received += 1


def worker():
    global queue, done
    while True:
        time.sleep(random.expovariate(1.2))          # a bit faster than they arrive
        with lock:
            if queue > 0:
                queue -= 1
                done += 1


class Metrics(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        with lock:
            body = (
                "# TYPE jobs_received_total counter\n"
                f"jobs_received_total {received}\n"
                "# TYPE jobs_done_total counter\n"
                f"jobs_done_total {done}\n"
                "# TYPE queue_jobs gauge\n"
                f"queue_jobs {queue}\n"
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=arrivals, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 9397), Metrics).serve_forever()
```

Replace `orchestra.toml` with:

```toml
[events]
url = "file"

[metrics]
url = "file"

[discovery]
strategy = "conservation"
window = "10m"          # short and fine, so a stock shows within minutes;
step = "5s"             # the defaults (60m, 30s) suit a system that runs all day
every = "1m"

[[machines]]            # keep the service running ...
name = "queue"
command = "python3 machines/queue_service.py"

[[scrape]]              # ... and measure it (an instrument; the same name is allowed)
name = "queue"
url = "http://127.0.0.1:9397/metrics"
every = "5s"
timeout = "2s"
```

### Run it

```bash
orchestra run &
orchestra web --port 8000 &
```

The host's log shows the service starting and the scrape beginning. The first scrape may fail
with "Connection refused" while the service starts; the next succeeds.

```
host started (pid 99681) for queue-demo-224d431e
launcher: queue: started `python3 machines/queue_service.py` (pid 99686)
collect: queue: scraping `http://127.0.0.1:9397/metrics` every 5 s
collect: queue: cannot fetch http://127.0.0.1:9397/metrics: [Errno 61] Connection refused; nothing written
```

### Check each step

The series are in the store, labelled with the instrument that measured them:

```
$ orchestra metrics series | grep instrument=queue
jobs_done_total instrument=queue
jobs_received_total instrument=queue
queue_jobs instrument=queue
```

The scrape is on the Instruments page (http://127.0.0.1:8000/instruments): `queue`, kind URL,
its target, every 5 s, its last write and points. The service is a process on the Core page. It
is not on the Machines page, since it publishes nothing on the bus.

After a minute or two, discover (or wait for the host's next run):

```
$ orchestra sd discover
conservation, over the last 10 min in 5 s steps: 1 stocks, 2 flows, 0 machines
  stock queue_jobs: Δ = − jobs_done_total{instrument="queue"} + jobs_received_total{instrument="queue"}   (R² 1.000, exact in 100% of steps)
left out:
  orchestra_host_up{machine="orchestra-host"}: Orchestra's own (the host's and the Core page's plumbing), not a measure of the system
  ...
saved as version 1
The system (version 1)

stocks (latest level):
  queue_jobs                    5.0

flows:
  jobs_done_total                      fitted     constant     53.05 /minute                  n=65
  jobs_received_total                  fitted     constant     60.39 /minute                  n=74

machines (attributed flows are hypotheses):
```

What happened:

1. `queue_jobs` has no `_total`, so it is a level. The two `_total` series only rise, so they
   are counters.
2. Each 5-second step, the change in `queue_jobs` equals `jobs_received_total`'s increase minus
   `jobs_done_total`'s. The balance is exact, so `queue_jobs` is a stock, `jobs_received_total`
   a flow into it from outside, and `jobs_done_total` a flow out of it to outside.
3. Each flow's rate is fitted. Which form wins depends on the run: a constant, or, as the
   worker drains faster when more is waiting, one linear in `queue_jobs`
   (`25.1 + 12.13 × queue_jobs /minute` on one run). Your numbers will differ.
4. No machine is associated with either flow. The `instrument="queue"` label says only which
   instrument measured the counters. A machine would be associated only by its events: if the
   service published a `job.done` event for each job it finished, its count in
   `orchestra_events_total` would match `jobs_done_total` step by step, and the service would
   become a hypothesis for that flow, with its confidence.

Open http://127.0.0.1:8000/dynamics: the stock `queue_jobs` with its level, a cloud feeding it
through the valve `jobs received`, and a valve `jobs done` draining it to a cloud, each with its
equation, and "no machine associated yet" in the flows table. Click the stock to see its history
and its balance.

### Stop it

```bash
kill %1 %2        # or Ctrl-C each; stopping orchestra run stops the service too
```

---

## 8. Troubleshooting

`<state>` below is `~/.orchestrator/<key>` (or under `$ORCHESTRATOR_HOME`). `orchestra init`
printed it; `cat ~/.orchestrator/projects.json` lists every project's key.

### A series never shows up

1. **Is it in the store?**

   ```bash
   orchestra metrics series | grep my_series
   curl -s 'http://127.0.0.1:8000/api/core/metrics/query?q=my_series&hours=1'
   ```

2. **Did the entry load?** An entry that cannot be used is left out with a line in the host's log:

   ```bash
   grep -E 'collect:|launcher:' <state>/logs/orchestra-host.log | tail -20
   ```

   Look for `left out` (a bad name, a name another instrument already has, a missing
   `command` or `url`, a URL that is not `http(s)://`, `every` under 1 s) and
   `cannot read orchestra.toml` (a file that does not parse: the previous entries keep running).

3. **Is this host the one that launches?** Only one host runs instruments. If the log says
   `another orchestra run (pid N) runs this project ... this one starts none`, the other host is
   running them. Check `<state>/runtime.json` (`launcher`, `instruments`), the Core page or the
   Instruments page.

4. **Did the run fail?** The Instruments page shows each instrument's failures and last error.
   Its own log says each round's result:

   ```bash
   tail -20 <state>/logs/instruments/<name>.log
   curl -s 'http://127.0.0.1:8000/api/core/metrics/query?q=orchestra_collect_failures_total&hours=1'
   ```

   `exited with code N`, `took longer than its timeout`, `cannot run ... (is it executable?
   chmod +x)`, `answered 404`, `cannot fetch ...: Connection refused`.

5. **Does the output parse?** Run it the way Orchestra does, and read what it prints:

   ```bash
   ORCHESTRA_REPO=$PWD ORCHESTRA_MACHINE_LOG=/dev/stderr ./machines/disk.sh
   curl -s -H 'Accept: text/plain;version=0.0.4' http://127.0.0.1:9100/metrics | head
   ```

   Then check against section 3.1. Common causes: a line the parser skips (the host's log says
   `line(s) of its output not understood and skipped (line N: why)`), a `NaN` value, a histogram
   bucket or summary quantile (only `_count` and `_sum` are kept), and a name starting with
   `orchestra_` (`series ... refused: the orchestra_ prefix is Orchestra's own`).

6. **Is it stamped in the future?** A point more than 60 s ahead of the host's clock is refused.
   The warning goes to `orchestra run`'s **standard error**, not to the host's log file:
   `metrics store file: refused 1 point(s) stamped more than 60 s in the future; the first: ...`.
   Timestamps in the text format are milliseconds; seconds there read as 1970, and microseconds
   as far in the future. Leave the timestamp out unless you need it.

7. **Same store?** `ORCHESTRA_METRICS_URL` set in one shell and not another means two stores.
   `curl -s http://127.0.0.1:8000/api/core` shows the bus and store the web server reads
   (`bus.url`, `metrics.url`).

### A machine shows inactive

1. **What does the page see?**

   ```bash
   curl -s http://127.0.0.1:8000/api/machines | python3 -m json.tool | less
   ```

   For the machine, look at `last_seen` (unix seconds), `active`, and each instance's
   `cadence_s` (`events` and `writes`). It is active while the last event is within
   2.5 × the events cadence, or the last write within 2.5 × the writes cadence, and never less
   than two minutes (section 5.6).

2. **Does it write on a schedule?** A level written only when it changes looks stopped between
   writes. Write every series every few seconds to a minute, changed or not.

3. **Is it a machine at all?** A machine is on the page because it publishes on the bus. A
   series, whatever its labels, never puts one there, and an instrument is never one (look on
   the Instruments page). For a machine seen on the bus, writes to series labelled
   `machine=<id>` (and `instance=<n>`) also count as signs of life, if any exist.

4. **Is its clock ahead?** Points stamped more than 60 s in the future are refused, and events
   stamped ahead count only from when they were read.

5. **Is it a process, not a machine?** A `[[machines]]` entry is a process. It is on the Core
   page (`running`, `waiting`, `gave_up`) whether or not it publishes. It is on the Machines page
   only by what it publishes. Scraping it, under any name, does not put it there.
   If it was given up on:

   ```bash
   tail -20 <state>/logs/machines/<name>.log      # "gave up after 5 failures in a row ..."
   ```

   Fix it, then change its entry (or restart `orchestra run`).

6. **Is the page behind?** The web server reads the list of series once a minute, so a machine
   whose last sign of life is a write can show a last-seen up to a minute old.

7. **Was it a detector or collector before 2026-10-27?** Those were shown as machines then. They
   are instruments now, on the Instruments page, and the old announcements are ignored.

### A stock is not found

1. **Ask discovery why.** Everything left out is listed with its reason:

   ```bash
   orchestra sd discover                       # the configured window and step
   orchestra sd discover --minutes 30 --step-s 10 --strategy conservation
   ```

   The Dynamics page shows the same list.

2. **Read the reason.**

   | Reason (in part) | What to do |
   |---|---|
   | `a level that changed in only N steps: fewer than 5` | It needs to move more in the window, or a finer `step`. |
   | `a level that did not change in the window` | Nothing to balance. |
   | `a counter of only N events: fewer than 5` | Wait for more events, or a longer window. |
   | `no counters balance it (best R² ...)` | A flow is not measured. Add a counter for every way in and out of the level (arrivals, completions, expiries, retries). Or the level is a quantity of its own, and stays an input. |
   | `too new to be a stock yet, an input until it covers enough` | Wait: the level must have been written for half the window's data. |
   | `no longer written: its writer ... has been silent N min before the end of the window` | The series' writer (named there: usually the instrument) stopped writing more than five minutes before the window's end. Fix the instrument (Instruments page), or look at a window when it ran (`--minutes`). |
   | `named orchestra_*` | Rename it. |
   | `a counter no stock's balance needed` | Not a problem: a counter that explains no level. |
   | `the same as ...` / `the same quantity measured again` | Two series measure one thing; one is kept. |

3. **Is the counter read as a counter?** It must end in `_total` and only rise (except resets).
   A `_total` series that falls often is read as a level. A counter without `_total` is a level.

4. **Did its writer go quiet?** A series whose writer was silent for more than five minutes at
   the end of the window is left out as gone.

5. **Are the window and step right?** A level that changes for a few seconds is lost on a 30 s
   grid. A slow system needs a longer window.

6. **Which strategy ran?** The host's log names it (`discovery (conservation): ...`). Without the
   `sd` extra every strategy is `conservation`.

7. **Was a version saved?** `orchestra sd versions`. A discovery with no stocks, the same
   structure as the current version, or a missing `[[sources]]` source is not saved (the host's
   log says `not saved: missing ...`).

---

## 9. Reference

### Commands

| Command | What it does |
|---|---|
| `orchestra init` | Register the repository and write `orchestra.toml`. |
| `orchestra run [--once]` | The host. `--once` starts, records one heartbeat and stops. |
| `orchestra web [--port 8000] [--host 127.0.0.1]` | The web UI. |
| `orchestra events info` | Which bus, how many events it holds, and the events endpoint while `orchestra run` serves it. |
| `orchestra events endpoint [--env]` | The events endpoint's URL and the token's file; with `--env`, `export` lines for `eval`. Exits 1 when no host serves it. |
| `orchestra events copy --to URL [--force]` | Copy the event log to another bus backend. |
| `orchestra metrics series` | Every series of the project, with its labels. |
| `orchestra metrics backfill [--append]` | Replay the event log into `orchestra_events_total`. |
| `orchestra sd discover [--minutes N] [--step-s S] [--strategy S]` | Discover the model now. |
| `orchestra sd show [--version N]` | The model: stocks with their latest level, flows, machines. |
| `orchestra sd versions` | The saved versions. |
| `orchestra sd fit [--version N] [--step H]` | Refit the flows over H-hour steps and save a version. |
| `orchestra sd predictions [--json]` | The predictions recorded and their verdicts, by era. |
| `orchestra sources check` | Probe each source's endpoints and credentials. |
| `orchestra sources infer [--source NAME]` | Run an inference round and print what is kept and left out. |
| `orchestra sources preview QUERY [--source NAME] [--minutes N] [--step-s S]` | Read a query's fan-out, with sparklines. |

Every command takes `--repo PATH`. Removed on 2026-10-27: `orchestra sd whatif`, `sd predict`,
`sd eras` and `sd observability`; their data is read through the HTTP API (section 5.9).

### Events Orchestra publishes

All from `source = "orchestra-host"`. Nothing is published for an instrument.

| Type | `data` |
|---|---|
| `orchestra.host.started`, `orchestra.host.stopped` | `pid` |
| `orchestra.machine.started` (the host's own) | `mode = "continuous"`, `listens_for = []` |
| `orchestra.process.started` | `name`, `pid`, `command`, `owner` |
| `orchestra.process.exited` | `name`, `pid`, `code`, `restart_in` (seconds, or null) |
| `orchestra.process.gave_up` | `name`, `code`, `failures` |

### Series Orchestra writes

| Series | Labels | Meaning |
|---|---|---|
| `orchestra_events_total` | `type`, `source` | Every event on the bus, counted by type and source: the one series derived from the event log, and secondary. Discovery uses it, and associates machines with flows from it. |
| `orchestra_host_up` | `machine="orchestra-host"` | 1 while the host runs, 0 when it stops. Left out of discovery. |
| `orchestra_collect_failures_total` | `collector`, `machine="orchestra-host"` | Failed `[[collect]]` and `[[scrape]]` rounds, by instrument (`collector` is its name). Left out of discovery. |

Everything else in the store was written by an instrument (labelled `instrument=<name>`) or by a
program of your own.

### Limits

| What | Value |
|---|---|
| An instrument's output (a script's or a URL's) | 10 MB |
| An event posted to the endpoint | 1 MB; `type`, `source` and `id` 256 characters, `subject` and the extensions 1024 |
| `GET /events` | `wait` at most 30 s, `limit` at most 10,000 |
| `GET /series` | 5,000 points a series, 20,000 an answer, a window of 90 days, 64 series |
| An equation | 4,000 characters, 600 parts, 64 parameters, 256 lookup points |
| An edit batch | 256 edits |
| An inverse run | `deadline_s` at most 300, `max_changes` at most 8 |
| Duplicate ids the endpoint remembers | the bus's last 10,000 when it started, and every one posted to it since |
| A point's timestamp | at most 60 s in the future |
| `every` | at least 1 s |
| Launcher pause | 1 s after a run of 60 s or more, else doubling from 2 s up to 60 s |
| Giving up | 5 failures in a row, each within 60 s of starting |
| Log rollover | 5 MB, to `<name>.log.1` |
| Active | 2.5 × the observed cadence, at least 2 minutes |

### Migration (2026-10-27)

Instruments were told apart from machines on 2026-10-27. What changes for an existing project:

- **Collected series change identity.** A point from `[[collect]]` or `[[scrape]]` was labelled
  `machine=<name>`; it is now labelled `instrument=<name>`. Each collected series' history
  therefore splits at the upgrade: points before it carry `machine`, points after carry
  `instrument`. Stores are not rewritten.
- **The model keeps its ids.** Discovery reads both labels as provenance only, so stock and flow
  ids do not change (replays of recorded systems kept every stock and flow). A window that spans
  the upgrade sees two series for one measurement until the old one ages out of the window.
- **Past model versions stay readable.** A version saved before shows its old, label-based
  association, marked "label (before 2026-10-27)". New versions associate machines with flows
  only as hypotheses from their events ([section 6](#machines-and-flows-hypotheses)).
- **Detectors and collectors leave the Machines page.** The host no longer announces them, and
  its old announcements for them (`orchestra.machine.started` with `data.collector`) are ignored.
  They are on the new **Instruments** page.
- **Logs move** from `<state>/logs/machines/<name>.log` to `<state>/logs/instruments/<name>.log`
  for instruments. A launched process's log stays where it was.
- **Names.** A `[[collect]]` may now share a `[[machines]]` entry's name (before, only a
  `[[scrape]]` could).
