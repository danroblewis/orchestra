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
match = ['{namespace="<yours>"}']    # required: nothing outside it is read
prefix = "chrono"
machine = "service"
max_series = 100
rate = 2.0                           # requests a second, for every process here
max_requests_per_day = 5000          # per UTC day; past it, nothing is asked until the next
[sources.labels]
service = ["service", "app", "k8s_app"]
```

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
  inside `match`, under the caps; page queries are logged in
  `~/.orchestrator/<key>/sources/chronosphere.asked.jsonl`.
- **No AI.** Nothing installed here calls a model.
- **No token leaves its file** except to its own host; pages and logs say only where it is.
  Ticket titles and descriptions are dropped.

To stop: Ctrl-C `orchestra web`, then `orchestra run` (the poller stops with it). To stop Jira
alone, delete its two entries. To remove everything: `uv tool uninstall orchestra`,
then delete `~/work-orchestra`, `~/.orchestrator/<key>/` and the token files.
