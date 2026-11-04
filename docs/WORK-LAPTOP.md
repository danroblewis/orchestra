# Orchestra on a work laptop: Jira and Chronosphere, read only, AI optional

By hand; nothing here writes anywhere, and nothing calls a model but the optional Supervisor
(step 6). Have ready: GitHub
access to `danroblewis/orchestra-bridges` (private); a read-only Chronosphere service account
token and your namespace; a Jira Data Center personal access token (Profile → Personal Access
Tokens), Jira's URL and your board id (`rapidView=<id>` in the board's URL).

## 1. Install

```bash
gh auth login && gh auth setup-git        # once: git over https uses your GitHub login
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' \
  --with 'orchestra-bridges @ git+https://github.com/danroblewis/orchestra-bridges@main' \
  --with 'orchestra-agents @ git+https://github.com/danroblewis/orchestra-agents@main'  # only for step 6
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


**The levers, in the guide.** What each lever of the entry is for, when to use it and what it
costs the store is in Orchestra's operator's guide, `orchestra/guide.md` (in the installed package:
`"$PY" -c "import orchestra.guides as g; print(g.CORE)"`), the same text the Supervisor reads: "A
Prometheus-API store: the entry and every lever" (`match`, `split`, `kinds` and the conventions
that make most entries unnecessary, `names`, the caps and the sum to do before settling them),
"Reading what Orchestra sees of a store" (`sources check`, `sources infer`, the request log, the
explorer drawer, the run record and its health), "What makes a stock, in the owner's terms" (levels
and flows, "in progress" by Little's law, Pub/Sub's backlog and outstanding) and "Machines from a
workload label". In short: `split = ["service_name", "method", "status"]` when a label you never
wanted apart crowds the series; `kinds = { "*:count" = "flow" }` only for a metric read wrongly;
`[sources.names]` rules (`"*_num_undelivered_messages" = "{subscription_id} messages waiting"`) once
stocks appear. An edit to any of them takes effect at the next discovery, or at once with
`orchestra sources infer`: no reinstall, no cache to clear. A coding agent doing this for you
starts from `docs/WORK-CLAUDE-PROMPT.md`, which points it at the guide.

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

## 6. The Supervisor (optional, in bash mode)

The Supervisor is an AI agent (the agents plugin, `danroblewis/orchestra-agents`, private) that does
what steps 3 to 5 had you do: it reads the same guide (`orchestra/guide.md`), reads the store
within `match`, explains what is left out, and proposes `[[sources]]` changes. Your company allows
Claude Code shell commands but only approved MCP servers, so it runs with `tools_via = "bash"`: it
calls Orchestra by running `orchestra agents tool <name> '<json>'` from its shell, and no MCP
server is configured or started.

It needs: the `--with 'orchestra-agents …'` line in step 1 (GitHub access to the repository);
Claude Code installed (`claude` on the PATH `orchestra run` has) and logged in once by hand; and a
model. Opus for a setup session (about $5 to $7), Haiku for the standing role (a question about
the store costs about 2 cents). Append to `orchestra.toml`:

```toml
[agents]
harness = "claude_code"
model = "haiku"            # the agents' default; the Supervisor's own model is in its spec (below)
tools_via = "bash"         # no MCP server, ever
serves = []                # no worker or reviewer: the Supervisor only
review_usd_per_day = 0     # its own initiative (review rounds, wake-ups): 0 = none; e.g. 1.0 for a dollar a day
```

`review_usd_per_day` caps what it starts on its own. Your chat turns are not capped, so each one
costs what it costs. Slack stays off: add no Slack machine.

Restart `orchestra run`: it starts the agents' host, which writes the Supervisor's spec on
**Sonnet**. Its log (`~/.orchestrator/<key>/logs/machines/agents.host.log`) says where: the live
copy is `~/.orchestrator/<key>/agents/machines/supervisor/machine.toml`. Set the model there:

```bash
sed -i '' 's/^model = "sonnet"/model = "haiku"/' ~/.orchestrator/<key>/agents/machines/supervisor/machine.toml
```

(`"opus"` for a setup session). The log says `its model changed to haiku`; `orchestra agents
status` should say `claude_code · haiku`.

**Talk to it** on the Agents page of `orchestra web`, or in a terminal: `orchestra agents chat`
(Ctrl-D leaves). Name the scope in your first message, or it asks before it reads anything: "The
chronosphere source's match and max_series are the scope I set. Look at it and tell me which
families could be stocks; change nothing."

**Proof it uses no MCP server:**

- `cat ~/.orchestrator/<key>/agents/sessions/claude-code/supervisor.none.json` says
  `{"mcpServers": {}}`, and during a turn `ps -eo args | grep 'claude -p'` shows
  `--strict-mcp-config --mcp-config …/supervisor.none.json`: no server, not even your own.
- The transcript, `~/.claude/projects/<the project directory, / as ->/<uuid>.jsonl` (the uuid is in
  `supervisor.json` beside it): `grep -o '"command":"orchestra agents tool [a-z_]*' <it>` lists every
  Orchestra call, each a `Bash` tool call; `grep -c mcp__orchestra <it>` says `0`.

**What it runs with**, for your policy: each turn is `claude -p --dangerously-skip-permissions` with
a settings file (`supervisor.settings.json`, `--settings`) that denies reading credential stores
(`~/.config/**`, `~/.ssh/**`, ...), `curl`, `wget`, `nc`, `cd ~`, `env`, the build and test tools,
plus a hook that refuses file reads outside the project and the state directory, and Edit and Write
turned off. Claude Code writes its transcript under `~/.claude/`. The agents repository's
`docs/policy-modes.md` compares bash, MCP and file mode for a policy reviewer.

**What never happens**: the rules of step 7 hold for it. Every query carries `match` (metadata is
asked name by name), counts against the caps and is in the requests log; no store token enters
the session; nothing outside is written. It changes only Orchestra's own files (`orchestra.toml`,
each change a commit it tells you the reason for, and the state directory); "change nothing"
keeps it to reading.

**To stop it**: Ctrl-C `orchestra run` (the agents' host stops with it). To keep Orchestra and drop
the Supervisor: `enabled = false` under `[agents]`.

## 7. What never happens, and stopping

- **No write.** The Jira program only reads. Orchestra only queries Chronosphere's Prometheus API,
  inside `match`, under the caps; every request it sends (discovery's, inference's, the page's)
  is logged in `~/.orchestrator/<key>/sources/chronosphere.requests.jsonl` (the last 10,000), shown
  on the Core page's row of the store (the last twenty, and today's count beside the cap) and by
  `orchestra sources check` (the last five).
- **No AI** without step 6: only the Supervisor calls a model, on your Claude Code login.
- **No token leaves its file** except to its own host; pages and logs say only where it is.
  Ticket titles and descriptions are dropped.

To stop: Ctrl-C `orchestra web`, then `orchestra run` (the poller stops with it). To stop Jira
alone, delete its two entries. To remove everything: `uv tool uninstall orchestra`,
then delete `~/work-orchestra`, `~/.orchestrator/<key>/` and the token files.
