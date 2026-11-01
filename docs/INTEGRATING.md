# Integrating an outside system

This page is for a coding tool working alone, with no other context, and for the Supervisor. It shows how to bring Jira,
Slack, PagerDuty and Chronosphere (or any similar system) into Orchestra. The owner put it this way:
"it's integration as in we give the Supervisor the knowledge and abilities to easily make its own
solutions." Every command and file here can be run as written. Replace `<…>` with your own values.

## 1. What an integration is here

Orchestra never calls an outside system. A **machine** or an **instrument** does, and Orchestra sees
only what they give it (`AGENTS.md` rules 1, 2 and 7). An integration can give three things:

| What | It means | Where it shows |
|---|---|---|
| **Series** | a measurement: "2 incidents open", "37 issues in progress" | the Instruments page, then the Dynamics page (stocks and flows are discovered from series) |
| **Events** | something happened, to one item: "PINC002 was acknowledged by PUSER01" | the Machines page: the actor is a machine, and the `subject` is the item |
| **A declared machine** | "PagerDuty is part of our system, and we expect it to fill the open-incidents stock" | the Machines page as a dashed "proposed" node until it is heard and confirmed |

Orchestra counts every event by type and source by itself (`orchestra_events_total`), so an event
stream is also a flow. You never need to write a counter of your own events.

## 2. Choosing a strategy

Go down this list in order and use the first strategy that fits. Most systems take two of them: a
series strategy and an events strategy.

**(a) `[[sources]]`: a store with a Prometheus API** (Chronosphere, Prometheus, Mimir, Thanos,
VictoriaMetrics). *Use this when* the numbers already live in a store that answers
`/api/v1/query`. Orchestra reads the series where they are, never copies them, infers what to read,
maps label spellings with aliases, and keeps within the store's rate and daily cap (SPEC §4.4). You
write no code. See §8.

**(b) `[[collect]]` or `[[scrape]]`: one measurement.** *Use this when* you need a number the store
does not have, and one cheap call gets it (open incidents now, issues per status). A `[[collect]]`
command prints Prometheus text, and a `[[scrape]]` reads a URL that already serves it. It is an
instrument: it measures and never acts (`docs/machines.md`).

**(c) A Programmatic Machine that polls an API.** *Use this when* you want **events**: what happened
to each item, and who did it. You build it from a kit (§4). The program reads what changed since
its cursor, every N minutes (5 by default), and publishes one CloudEvent per change. The same file
run with `measure` is a `[[collect]]` instrument. It runs in one of two ways:
- as a `[[machines]]` entry: a continuous process with its own interval loop, kept running by
  `orchestra run`. This needs no plugin;
- with the Workflows plugin installed, as a scheduled item (`[workflows.every.<name>]`) that runs
  it once per interval (§5.5).

There is no fourth strategy of "the bridges plugin's own reader". **The bridges plugin is a
library** (the owner, 2026-11-01: "a library or framework so that AI agents within my repo ...
could write scripts in the target repo to do the metrics and event collection"): kits, fakes,
templates and a scaffold. It reads no system itself; every collector, for (b) and (c), is a script
in the owner's repository (§3.1), scaffolded from a kit and edited there like any other code. Its
older direct readers (`[bridges.jira]`, `[bridges.slack]`, `[bridges.github]`) are being retired
into scaffolded examples: do not configure them for a new integration.

| System | Series | Events |
|---|---|---|
| Chronosphere | (a), §8 | none: a metrics store has no item events |
| PagerDuty | (c)'s `measure`: open incidents | (c), §5 |
| Jira | (c)'s `measure`: issues by status | (c), §6 |
| Slack | (c)'s `measure`: messages per channel | (c), for channel history and pings to you, §7 |

## 3. Rules that bind every strategy

1. **Where files go.** **The program goes in the owner's repository**, the target repository
   Orchestra runs in: `.orchestra/machines/<name>/` (`poller.toml`, `<name>.py`,
   `test_<name>.py`, `AGENTS.md`), scaffolded with `--root repo`. There a coding tool (the
   owner's, or the Coordinator's worker on a ticket) edits it, its test runs with the
   repository's, and it lands by a pull request the owner approves, like any other code. **The
   state directory is the exception**: `--root state` writes `~/.orchestrator/<key>/machines/<name>/`
   (find it with `python -c "from orchestra.config import load_project; print(load_project().state_dir)"`),
   only when the owner says their repository must stay clean, or for a throwaway trial (§5.4).
   Whichever holds the program, what changes as it runs stays in the state directory:
   - its cursor and the ids it has emitted: `kits/pollers/<name>/`;
   - the HTTP cache: `kits/cache/`.

   Configuration entries (the `[[machines]]` and `[[collect]]` that run it, with the owner's
   credentials by reference) go in the **private overlay** (`orchestra.local.toml` in the state
   directory), written through `project.config_edit` with `target="overlay"`. The default target is
   the repository, so always pass it. **The kits are read-only**: their client sends GET (and the
   few POSTs a search API needs) and nothing else. A write to the system (a label, a transition, a
   comment, a Slack post) is never the collector's: it is an Outbox draft (the outbox plugin), sent
   only as the owner's approval settings allow. **With the Supervisor**, you write none of this:
   its `integrate_system` scaffolds into the repository (or, on the owner's word, the state
   directory), names the path, and hands the script to the Coordinator as work when its test fails
   or no kit has a template for the system; `approve_integration` writes the clearance, the
   credentials' references and the overlay entries.
2. **Credentials come from an environment variable or a token file, never from the config.**
   Never put a token in `orchestra.toml`, the overlay or `poller.toml`. Orchestra and the kits
   refuse a `token` key. `poller.toml` holds only the variable's *name* (`[settings] token_env`),
   and `[bridges.kits] tokens = { pagerduty = "PAGERDUTY_TOKEN" }` maps a system to a name. A token
   file is `~/.config/orchestra-bridges/<name>-token` (`install -m 600 /dev/null <file>`, then the
   owner pastes the token in), outside every repository. `CachedClient(token_file=…)` reads it.
   Two cautions:
   - With `token_env`, the variable must be set in the environment of `orchestra run`, and every
     process the host launches inherits it. Where that matters, name `[settings] token_file`
     instead (§5.2 does). An HTTP Basic login (Jira Cloud: the account's email with the token)
     names the account the same way, `user_env` or `user_file`.
   - Never print, log, echo or commit a token, and never ask for one in a chat. Ask the owner to
     set it.
3. **Rate limits and caching.** `CachedClient` limits each host with Orchestra's own token bucket,
   shared by every process on the machine (`per_minute`; `[bridges.kits] hosts` caps a host for the
   whole project). It retries 429 and 5xx with a doubling backoff and honours `Retry-After` up to
   `max_wait_s`. It caches on disk, for `ttl_s`, only what `keep` returns. Change reads that a stale
   answer would hide use `ttl_s=0`. With a measurement every 5 minutes and a 240 s TTL, each
   measurement makes one call. A `[[sources]]` store is limited by Orchestra itself (`rate`,
   `max_requests_per_day`). Never go over a store's documented budget. If you are unsure, poll less
   often.
4. **Compliance comes before the first read** (`docs/work-charter.md` §8, a FedRAMP environment).
   A scaffolded `poller.toml` starts with `clearance = "needs approval"`. Until the owner sets
   `"approved"` (with `data_class`), the program reads only a fake on this machine and refuses any
   other host before it sends a request. You never change the clearance yourself: stop and get the
   owner's written yes, naming the system, the token's scope and "metadata only". Two more rules
   follow:
   - **Never text.** Events, series, logs and cache files hold only metadata: ids, keys, accounts,
     states, names an administrator defines, numbers and times. Titles, descriptions, messages and
     names pass through memory and are dropped by `keep`/`meta`.
   - **Your own session is a model too.** Build and test against the fake. Never paste a real API
     answer into your conversation. To inspect real data, use `--dry-run` (answers only from the
     cache) and print counts only.
5. **Idempotent emission.** `Poller.emit` builds each id as `<name>:<type>:<key>@<stamp>`. The key
   is the item's own id, and the stamp is its change (`last_status_change_at`, a changelog id). It
   skips any id already emitted, across restarts too (`kits/pollers/<name>/`), and the events
   endpoint refuses repeats as well. The cursor is saved only after a good poll, so a restart never
   duplicates and never skips.
6. **The envelope** (SPEC §2). `type` starts with the system's name and then says what happened:
   `jira.issue.transitioned`, `slack.message.posted`, `pagerduty.incident.acknowledged`. `source` is
   **who acted**: `actor_source(system, account=None, *, bot=False)` gives `person.<system>.<account>`,
   `bot.<system>.<account>`, or `bot.<system>` for the system's own act. **The identity map wins**:
   an account the project's `[bridges] people` map lists on that system is published as
   `person.<key>`, as the bridges' own readers publish it, so one person is one machine. `subject` is the item: the
   Jira key (`ABC-12`), the PagerDuty incident id (`PINC001`), the Slack `<channel>/<thread ts>`.
   The Machines page infers hand-offs from subjects. `time` is the system's own, in RFC 3339 with a
   zone, and `data` is metadata only. **Never stamp an event in the future.** An event whose `time`
   is more than 60 s ahead of this machine's clock is published, but its point in
   `orchestra_events_total` is refused, so the flow never sees it. The refusal shows only in
   `orchestra run`'s own output, not in the poller's log. Take the system's time as it is, and never
   compute one (a "due" time is data, not `time`).
7. **Your poller is not a machine** (`AGENTS.md` rule 2, decision D19: "the provider is never the
   machine"). The program is a relay. It never publishes under its own name, never announces
   itself and never writes a metric. `Poller.emit` refuses any source but `person.…` or `bot.…`.
   The machines are the actors, and the poller announces each one once (`orchestra.machine.started`
   from their source, `mode: "ad hoc"`, `kind: "person"` or `"program"`, `package: "bridges"`, and
   a mapped person's name and team).
   Under the Workflows plugin the program's *runs* claim turns as `<id>/<n>`, which is that
   plugin's business.
8. **Declare it on the Machines page with its expected effect** (§5.6). A declaration is a
   hypothesis. It names the machine (`^[a-z][a-z0-9_]{1,40}$`, e.g. `pagerduty`), says
   `managed: "external"` (it runs elsewhere), gives its engagement and what it emits, joins it to
   the observed source (`alias` → `bot.pagerduty`), and predicts its effect ("a flow into open
   incidents appears"). It changes no flow and no equation. The owner's confirm on the page is a
   request that a listening machine, or you, must answer (§5.6); until then it stays proposed.
9. **Test against a fake before any real call.** The kits' fakes (`FakeJira`, `FakeSlack`,
   `FakePagerDuty`, `FakePrometheus`) serve the real shapes, check the token and put `CANARY` in
   every text field. Each test checks the events (types, subjects, sources), that a restart
   publishes nothing twice, the printed series, and that neither the canary nor the token appears
   in any output or file.
10. **Confirm it works** with §9's commands and pages. A trial on a scratch project against the
    fake comes first, then the real system.
11. **Behind a corporate proxy.** Orchestra's own HTTP (a `[[sources]]` store, a VictoriaMetrics
    metrics store) uses Python's standard library, which takes `HTTPS_PROXY`, `HTTP_PROXY` and
    `NO_PROXY` from the environment of `orchestra run` and `orchestra web`; every process the host
    launches inherits them. Put the local hosts in `NO_PROXY` (`127.0.0.1,localhost`) or the web
    UI's own calls and a local bus go through the proxy too. A proxy that re-signs TLS with a
    corporate CA needs that CA trusted: for one store, `[[sources]] auth = { ca_file = "…" }`; for
    everything in the process, `SSL_CERT_FILE=/path/to/corporate-ca-bundle.pem` (a bundle holding
    the public CAs as well as the corporate one, or every other host fails). `uv` itself reads
    `SSL_CERT_FILE`, or `UV_NATIVE_TLS=1` to use the system's store. The hosts to allow: `github.com`
    (installing Orchestra and its plugins), `pypi.org` and `files.pythonhosted.org` (their
    dependencies), `api.anthropic.com` (only if an AI agent machine runs here), and each system you
    integrate or store you read, by the host its URL names. The browser showing the web UI also
    loads its drawing libraries from `cdnjs.cloudflare.com` and `cdn.jsdelivr.net`.

## 4. The kits (`orchestra_bridges.kits`, in the bridges plugin)

**Installing.** The kits come with the bridges plugin, in Orchestra's own environment. Use one of:

```bash
uv tool install "orchestra[bridges,dev] @ git+https://github.com/danroblewis/orchestra"   # Orchestra with the plugin
uv pip install --python <orchestra's venv>/bin/python -e ~/orchestra-bridges --no-deps     # an editable checkout of the plugin
```

The second form uses `--no-deps` because the plugin's pin on Orchestra's version can refuse an
Orchestra already installed from source. `python -c "import orchestra_bridges.kits"` with
Orchestra's Python says whether the kits are there. **pytest** comes with the `dev` extra. Without
it, run `uv pip install --python <venv>/bin/python pytest`. Then always run tests as
`<venv>/bin/python -m pytest …`, so they import the same Orchestra and kits that `orchestra run`
uses.

| Name | What it does |
|---|---|
| `api.get(path, params, keep=…)`, `api.post(path, form={…}, keep=…)` | the `CachedClient` a program is handed (`runner.main` builds it): parsed JSON; reads only (a POST is a form that asks a question), one origin, the token never logged; `--dry-run` answers from the cache only |
| `p.emit(type, subject, data, source=actor, stamp=…)`, `p.cursor`, `p.counter(name, by, labels)` | the `Poller` a `poll(p)` is handed: idempotent emission as whoever acted (the identity map first), the cursor and counters saved after each good poll |
| `actor_source(system, account=None, *, bot=False)` (`kits.poller`) | the source of whoever acted |
| `p.announce(source, time=None, **about)` | an actor announced ahead of their first event (`emit` does it for you) |
| `Prometheus(client, aliases, max_series=500)` (`kits.promql`) | `.instant(q)`, `.range(q, start, end, step)` and `.series(match)`, which return `Series(name, labels, points)`. It refuses an answer with more than `max_series` series |
| `kits.fakes`: `FakeJira`, `FakeSlack`, `FakePagerDuty`, `FakePrometheus`, `CANARY` | `with FakePagerDuty(token="t") as f: f.url`. Use `f.set_status(...)` and `f.add_incident(...)` to change the world between polls, `f.fail_next(429)`, and `f.requests` to see what arrived |
| `kits.fakes.FakeServer` | the base of every fake, for a system no kit knows: subclass it and implement `route(method, path, query, body)` (below) |
| `orchestra bridges scaffold <jira\|slack\|pagerduty\|promql\|http> <name> [--root state\|overlay\|repo]` | writes `<root>/machines/<name>/` (`poller.toml`, `<name>.py`, `test_<name>.py`, `AGENTS.md`) and prints the `[[machines]]` and `[[collect]]` entries. `promql` only measures (no poller); `http` is any JSON API no kit knows |
| `orchestra bridges integrations [--json]` | read-only: the kits, and each poller scaffolded under the three roots with its kit, clearance, data class, the token's variable NAME (never a value), what schedules it (`[[machines]]`, `every` for the Workflows route, or `no`), whether its `[[collect]]` entry is configured, and how many `# guess` marks are left |

The kits' reference, with every signature, is the bridges' SPEC §7.

A scaffolded program runs as `python <name>.py [--once | --rounds N] [--every S] [--base-url URL]
[--state-dir DIR] [--events-file FILE] [--ttl S] [--dry-run] [--set KEY=VALUE ...]`. `python
<name>.py measure` is its `[[collect]]` command. `--set` gives one run a kit setting (a TOML value:
`--set 'jql="project = ABC"'`), never the URL or the credentials; the scaffolded test uses it to give
the run the scope its fake holds. Its `poller.toml` holds `[settings]` (`base_url`, `token_env`,
`every`, `per_minute`, `ttl` and the kit's own keys), the clearance, and the `[[publishes]]` list.
Values the template guessed (the site, the JQL, the channels, the queries, an API's paths) end in
`# guess: ask the owner` (or `# guess: from the API's docs`): ask for each, and remove the mark once
the value is the owner's.

**Not yet cleared.** Run for good (no `--once`, no `--rounds`) with `clearance = "needs approval"`
and a real `base_url`, the poller does not exit: it logs `waiting for approval` once, reads nothing,
and re-reads `poller.toml` on its interval, polling as soon as it says `approved` (against a fake
on this machine it polls at once). `--once`, `--rounds` and `measure` refuse with exit 2 before any
request. The scaffolded test reads the token's variable name and the scope from `poller.toml`, so
it still passes after the owner's values are filled in.

**The scaffold's shape.** A scaffolded `<name>.py` is three functions and a `main`:

- `make_poll(api, settings)` returns `poll(p)`. `api` is the `CachedClient`; `settings` is the
  parsed `poller.toml`, with `settings.extra` holding every `[settings]` key beyond the common ones
  (`jql`, `channels`, `open_statuses`, `queries`). `poll` calls `p.emit(...)` and sets `p.cursor`.
- `measure(api, settings, series)` prints series through `series.gauge(name, value, labels,
  help=…)` (and `series.counter`).
- `main()` calls `runner.main(HERE, make_poll, argv, measure=measure, auth_format=…, headers=…)`,
  which reads `poller.toml`, checks the clearance, builds the client and the `Poller`, and parses
  the command line above. A measurement only (`promql`) passes `None` for `make_poll`, and refuses
  a poll (exit 2). Exit codes: 0 done, 1 a measurement that failed, 2 refused before any read.

To change what it reads, edit `keep_*`/`meta` and `poll`. To change how it runs, edit
`poller.toml`. Leave `runner.main` alone.

**Auth formats** (`auth_format`; the token is what the variable or file holds):

| System | `auth_format` | The token |
|---|---|---|
| Jira DC, Slack, Chronosphere, most APIs | `"Bearer {token}"` (the default) | the token as issued |
| PagerDuty | `"Token token={token}"` | a read-only REST API key |
| Jenkins, Jira Cloud, anything with HTTP Basic | `"Basic {token}"` | `printf '%s' 'user:apitoken' \| base64` |

**Which token name is used.** In a scaffolded program, `[settings] token_env` in `poller.toml` wins.
If you remove that line, the name comes from `[bridges.kits] tokens.<kit>`, where `<kit>` is
`poller.toml`'s `kit =` line (`kit = "pagerduty"` reads `tokens.pagerduty`). Use this to set the
name once for the project. A test run with `--state-dir` takes only `token_env`.

**A system with no kit** (Jenkins, Opsgenie, a home-grown API). Start from the generic `http`
template: `orchestra bridges scaffold http <name>`. Its `[settings]` name the list endpoint and
where each item's id, change stamp, state and actor are (dotted paths), and its test carries a fake
written on `FakeServer` (`FakeAPI`), to change to the API's real shapes. When the API is not a list
of items, scaffold the closest template instead, rename its types and rewrite `keep_*`, `poll` and
`measure`:

- `pagerduty` for a list of items that each carry a status and who last changed it (Jenkins builds,
  alerts, deployments). This is the usual choice;
- `jira` for a search of what was updated since a time, with a history per item;
- `slack` for append-only streams read by timestamp (logs, chat, audit trails);
- `promql` for numbers only.

Then write a fake for it from the kits' `FakeServer`. Implement `route(method, path, query, body)`
to return `(status, json)` in the real API's shape. Set `auth_format` to what the real server checks,
seed it with a dict (its `self.data`), and put `CANARY` in every text field. The base records each
request (`fake.requests`, with `.authorized`), refuses a wrong token with 401, and fails on demand
(`fake.fail_next(429, {"Retry-After": "1"})`). A Jenkins fake and its first test:

```python
"""A fake of the one Jenkins endpoint the poller reads, in its real shape, with the canary in every text field."""
import base64
from orchestra_bridges.kits.fakes import CANARY, FakeServer

TOKEN = base64.b64encode(b"robot:test-api-token").decode()    # Basic auth: base64 of user:apitoken

class FakeJenkins(FakeServer):
    auth_format = "Basic {token}"
    def route(self, method, path, query, body):
        if method == "GET" and path == "/job/deploy/api/json":
            return 200, {"builds": [{**b, "description": CANARY, "fullDisplayName": CANARY} for b in self.data["builds"]]}
        return 404, {"message": "Not Found"}

def test_reads_builds_through_the_kit(tmp_path, monkeypatch):
    from orchestra_bridges.kits import CachedClient
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path))         # the rate bucket's file goes here
    monkeypatch.setenv("JENKINS_TOKEN", TOKEN)
    builds = [{"number": 41, "result": "SUCCESS", "timestamp": 1793500000000}]
    with FakeJenkins({"builds": builds}, token=TOKEN) as fake:
        api = CachedClient(fake.url, token_env="JENKINS_TOKEN", auth_format="Basic {token}", cache_dir=tmp_path / "c")
        got = api.get("/job/deploy/api/json", {"tree": "builds[number,result,timestamp]"},
                      keep=lambda b: [{k: x[k] for k in ("number", "result", "timestamp")} for x in b["builds"]])
        assert got == builds and all(r.authorized for r in fake.requests)
```

Replace the scaffolded test's fake import with yours, and keep its checks: the events, a restart
that publishes nothing twice, `measure`'s series, and no canary or token in any output or file.

**Without the kits** (the bridges plugin is not installed), save this as `minikit.py` beside your
program. It has the same names and arguments for what §5.2 uses, and needs only the standard library
and Orchestra. It has no scaffold or fakes: write the test's fake yourself (§5.2 has one), and keep
the clearance as a constant in the program.

```python
"""minikit.py: a stand-in for orchestra_bridges.kits with the same names, standard library and Orchestra only."""
import hashlib, json, os, re, signal, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

def state_root():
    from orchestra.config import load_project
    return load_project().state_dir

def actor_source(system, account=None, *, bot=False):
    safe = lambda s: re.sub(r"[^a-z0-9._-]", "-", str(s).lower())
    return f"bot.{safe(system)}" if not account else f"{'bot' if bot else 'person'}.{safe(system)}.{safe(account)}"

def read_token(token_env, token_file):
    if token_env and os.environ.get(token_env, "").strip():
        return os.environ[token_env].strip()
    p = Path(token_file).expanduser() if token_file else None
    if not p or not p.is_file():
        sys.exit(f"no token: set {token_env} or put it in {token_file} (chmod 600)")
    if p.stat().st_mode & 0o077:
        sys.exit(f"{p} is readable by others: chmod 600 it")
    return p.read_text().strip()

class CachedClient:
    def __init__(self, base_url, token_env=None, token_file=None, per_minute=60, cache_dir=None, ttl_s=300, *,
                 auth_format="Bearer {token}", headers=None, retries=3):
        self.base, self.ttl, self.retries, self.gap = base_url.rstrip("/"), ttl_s, retries, 60.0 / per_minute
        self.hdr = {"Accept": "application/json", **(headers or {})}
        if token_env or token_file:
            self.hdr["Authorization"] = auth_format.format(token=read_token(token_env, token_file))
        self.cache_dir = Path(cache_dir) if cache_dir else state_root() / "kits" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last = 0.0

    def get(self, path, params=None, *, keep=None, ttl_s=None, cache=True):
        items = [(k, x) for k, v in (params or {}).items() if v is not None
                 for x in (v if isinstance(v, (list, tuple)) else [v])]
        url = self.base + "/" + path.lstrip("/") + ("?" + urllib.parse.urlencode(items) if items else "")
        ttl = self.ttl if ttl_s is None else ttl_s
        f = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        cache = cache and keep is not None and ttl > 0        # only what keep returns reaches the disk
        if cache and f.exists() and time.time() - f.stat().st_mtime < ttl:
            return json.loads(f.read_text())
        for attempt in range(self.retries + 1):
            time.sleep(max(0.0, self.last + self.gap - time.time()))
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.hdr), timeout=30) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise RuntimeError(f"HTTP {e.code} from {self.base}{path}") from None
                time.sleep(min(float(e.headers.get("Retry-After") or 2 ** attempt), 300))
        body = keep(body) if keep else body
        if cache:
            f.write_text(json.dumps(body))
        return body

class Poller:
    def __init__(self, name, every_s=300, state_dir=None, *, events=None, project=None, package=None):
        from orchestra.config import load_project
        from orchestra.events import Events
        self.name, self.every_s, self.package = name, every_s, package or name
        self.dir = Path(state_dir) if state_dir else state_root() / "kits" / "pollers" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = events or Events.for_project(project or load_project())
        cur, ids = self.dir / "cursor.json", self.dir / "emitted.log"
        self.cursor = json.loads(cur.read_text()) if cur.exists() else None
        self.emitted = set(ids.read_text().split()) if ids.exists() else set()
        self.stopped = threading.Event()

    def _publish(self, eid, type, data, source, **ext):
        ev = self.events.publish(type, data, source=source, id=eid, **ext)
        with open(self.dir / "emitted.log", "a") as fh:
            fh.write(eid + "\n")
        self.emitted.add(eid)
        return ev

    def announce(self, source, time=None):
        eid = f"{self.name}:announce:{source}"
        if eid not in self.emitted:
            data = {"mode": "ad hoc", "kind": "program" if source.startswith("bot.") else "person",
                    "listens_for": [], "package": self.package}
            self._publish(eid, "orchestra.machine.started", data, source, **({"time": time} if time else {}))

    def emit(self, type, subject, data=None, source=None, *, key=None, stamp=None, time=None):
        if not str(source).startswith(("person.", "bot.")):
            raise ValueError(f"{type}: publish only as who acted (person.…, bot.…), never {source!r}")
        stamp = stamp or hashlib.sha1(json.dumps([type, data], sort_keys=True).encode()).hexdigest()[:16]
        eid = f"{self.name}:{type}:{key or subject}@{stamp}"
        if eid in self.emitted:
            return None
        self.announce(source, time)
        return self._publish(eid, type, data, source, subject=subject, **({"time": time} if time else {}))

    def run(self, poll, *, once=False, rounds=None):
        signal.signal(signal.SIGTERM, lambda *_: self.stopped.set())
        n, ok = 0, True
        while not self.stopped.is_set():
            before = self.cursor
            try:
                poll(self)
                tmp = self.dir / "cursor.tmp"
                tmp.write_text(json.dumps(self.cursor))
                tmp.replace(self.dir / "cursor.json")     # saved only after a good poll
                ok = True
            except Exception as e:                        # say what failed; never a body or a header
                self.cursor, ok = before, False
                print(f"{self.name}: poll failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            n += 1
            if once or (rounds and n >= rounds):
                break
            self.stopped.wait(self.every_s)
        return 0 if ok else 1
```

**Ratios and flows.** Discovery derives flows from counts. Each event type is already a counter
(`orchestra_events_total{type}`), and so is any `_total` you print. A ratio you compute (a
failure rate, a share answered in time) is a level. It is never a flow or a stock, and discovery
cannot take it apart. So for "the build failure rate", publish one event per outcome
(`jenkins.build.succeeded`, `jenkins.build.failed`; the outcome goes in the *type*, not only in
`data`, because Orchestra counts by type). Then discovery sees the two flows. If the owner wants
the rate on a page, also print `jenkins_build_failure_ratio` from `measure` as an effect: a
gauge over a stated window (`{window="1h"}`), beside the counts it was made from
(`jenkins_builds_total{result}`), never instead of them.

## 5. Worked example: PagerDuty

The owner wants to be "aware of PagerDuty alerts" and "of every outage as it happens" (work charter
§3D–E). The events are each incident's status changes (triggered, acknowledged, resolved), each
made by whoever made it (`last_status_change_by`: a user, or the service itself). The series is the
open incidents, by service and urgency.

### 5.1 With the kit

```bash
cd <repository>
PY="$(uv tool dir)/orchestra/bin/python"     # Orchestra's Python (§4): bare python and uv run lack the kits
orchestra bridges scaffold pagerduty pagerduty_alerts --root repo   # -> .orchestra/machines/pagerduty_alerts/
"$PY" -m pytest .orchestra/machines/pagerduty_alerts/test_pagerduty_alerts.py -q   # 4 passed
```

The program (`pagerduty_alerts.py`) lists the open incidents each poll and reads by id each one
that was open last poll and is not now. For each, it emits `pagerduty.incident.<status>` with the
incident id as subject, `actor_source("pagerduty", <user id>)` as source and
`last_status_change_at` as the stamp. `measure` prints `pagerduty_incidents_open{service, urgency}`
(no total beside it: a gauge is never named `_total`, which discovery reads as a counter, and a sum of
its own parts is the same level measured twice). Edit `[settings]` in `poller.toml` (`every`, `per_minute`,
`ttl`, `open_statuses`), never `clearance`.

### 5.2 Without the kit: `pagerduty_alerts.py`, beside `minikit.py`

This is the same program in a second style: one file with its own `__main__`, no `runner` and no
`poller.toml`, so its settings and clearance are constants at the top. It runs unchanged on the
kit as well, because the import falls back to `minikit` only when the kit is missing. The two
styles are not mixed. A scaffolded program keeps the scaffold's shape (above), and this one is for
a machine with no kit installed.

```python
"""PagerDuty -> pagerduty.incident.<status>, as who changed it (poll); open incidents as series (measure)."""
import os, sys, urllib.parse
try:
    from orchestra_bridges.kits import CachedClient, Poller
    from orchestra_bridges.kits.poller import actor_source
except ImportError:
    from minikit import CachedClient, Poller, actor_source

CLEARANCE = "needs approval"     # the owner's word turns it to "approved"; until then only a fake is read

def client(**kw):
    url = os.environ.get("PAGERDUTY_API", "https://api.pagerduty.com")
    if CLEARANCE != "approved" and urllib.parse.urlsplit(url).hostname not in ("127.0.0.1", "localhost"):
        sys.exit(f"reading {url} is not cleared: CLEARANCE = {CLEARANCE!r}")
    kw = {"per_minute": 30, "ttl_s": 240, **kw}
    return CachedClient(url, token_env="PAGERDUTY_TOKEN", token_file="~/.config/orchestra-bridges/pagerduty-token",
                        auth_format="Token token={token}", headers={"Accept": "application/vnd.pagerduty+json;version=2"}, **kw)

def meta(i):                     # what is kept of an incident: never its title or a name
    by = i.get("last_status_change_by") or {}
    return {"id": i["id"], "status": i["status"], "urgency": i.get("urgency"),
            "service": (i.get("service") or {}).get("id"), "changed_at": i.get("last_status_change_at"),
            "by": by.get("id") if by.get("type") == "user_reference" else None}

def open_incidents(api):
    out, offset = [], 0
    while True:
        page = api.get("/incidents", {"statuses[]": ["triggered", "acknowledged"], "offset": offset, "limit": 100},
                       keep=lambda b: {"incidents": [meta(i) for i in b.get("incidents") or []], "more": bool(b.get("more"))})
        out += page["incidents"]
        if not page["more"]:
            return out
        offset += 100

def make_poll(api):
    def poll(p):
        now_open = open_incidents(api)
        gone = [iid for iid in (p.cursor or {"open": []})["open"] if iid not in {i["id"] for i in now_open}]
        closed = [api.get(f"/incidents/{iid}", keep=lambda b: meta(b["incident"]), ttl_s=0) for iid in gone]
        for i in now_open + closed:
            p.emit(f"pagerduty.incident.{i['status']}", i["id"], {"urgency": i["urgency"], "service": i["service"]},
                   source=actor_source("pagerduty", i["by"]), stamp=i["changed_at"], time=i["changed_at"])
        p.cursor = {"open": sorted(i["id"] for i in now_open)}
    return poll

def measure(api):
    n = {}
    for i in open_incidents(api):
        n[(i["service"], i["urgency"])] = n.get((i["service"], i["urgency"]), 0) + 1
    for (service, urgency), count in sorted(n.items()):
        print(f'pagerduty_incidents_open{{service="{service}",urgency="{urgency}"}} {count}')

if __name__ == "__main__":
    if sys.argv[1:2] == ["measure"]:
        measure(client())
    else:
        sys.exit(Poller("pagerduty_alerts", every_s=300).run(make_poll(client()), once="--once" in sys.argv))
```

The test, `test_pagerduty_alerts.py`, beside it (run `python test_pagerduty_alerts.py`; it prints
`ok`):

```python
"""python test_pagerduty_alerts.py: the test, against a fake of /incidents with a canary in every title."""
import contextlib, io, json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from orchestra.events import Events

CANARY = "CANARY-7f3a"
SERVICE = {"type": "service_reference", "id": "PSVC1"}
WORLD = {"PINC1": {"status": "triggered", "by": SERVICE, "at": "2026-11-02T10:00:00Z"},
         "PINC2": {"status": "acknowledged", "by": {"type": "user_reference", "id": "PUSER1"}, "at": "2026-11-02T10:03:00Z"}}

def shape(iid, w):
    return {"id": iid, "title": CANARY, "status": w["status"], "urgency": "high", "service": SERVICE,
            "last_status_change_at": w["at"], "last_status_change_by": {**w["by"], "summary": CANARY}}

class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Token token=test-token":
            return self.send_error(401)
        path = self.path.split("?")[0]
        if path == "/incidents":
            body = {"incidents": [shape(k, w) for k, w in WORLD.items() if w["status"] != "resolved"], "more": False}
        elif path.startswith("/incidents/") and path[11:] in WORLD:
            body = {"incident": shape(path[11:], WORLD[path[11:]])}
        else:
            return self.send_error(404)
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a):
        pass

def test():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(PAGERDUTY_API=f"http://127.0.0.1:{srv.server_port}", PAGERDUTY_TOKEN="test-token")
    import pagerduty_alerts as pd
    def poll_once():
        api = pd.client(cache_dir=tmp / "cache", ttl_s=0)
        pd.Poller("pagerduty_alerts", state_dir=tmp / "state", events=Events(tmp / "events.jsonl")).run(pd.make_poll(api), once=True)
        return [json.loads(x) for x in (tmp / "events.jsonl").read_text().splitlines()]
    changes = lambda evs: [(e["type"], e["subject"], e["source"]) for e in evs if e["type"] != "orchestra.machine.started"]
    assert changes(poll_once()) == [("pagerduty.incident.triggered", "PINC1", "bot.pagerduty"),
                                    ("pagerduty.incident.acknowledged", "PINC2", "person.pagerduty.puser1")]
    WORLD["PINC1"] = {"status": "resolved", "by": {"type": "user_reference", "id": "PUSER2"}, "at": "2026-11-02T10:20:00Z"}
    evs = poll_once()                                           # a restart: cursor and emitted ids read back
    assert changes(evs)[2:] == [("pagerduty.incident.resolved", "PINC1", "person.pagerduty.puser2")], changes(evs)
    assert sum(e["type"] == "orchestra.machine.started" for e in evs) == 3     # each actor announced once
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pd.measure(pd.client(cache_dir=tmp / "cache"))
    assert 'pagerduty_incidents_open{service="PSVC1",urgency="high"} 1' in out.getvalue()
    files = [p.read_text() for p in tmp.rglob("*") if p.is_file()]
    assert not any(CANARY in s or "test-token" in s for s in [out.getvalue(), *files]), "text or token leaked"
    print("ok")

if __name__ == "__main__":
    test()
```

### 5.3 Run it: the entries, in the overlay

**When.** The entries come last, after the owner's approval: scaffold, test against the fake, then
(on the owner's word) set `clearance = "approved"` with `data_class`, and `token_env` to the name of
the variable the owner set, and only then add the entries. The Supervisor's `integrate_system` flow
works this way: it writes `[[machines]]` and `[[collect]]` at `approve_integration`, never before. A
coding tool following this document does the same. An entry added early does no harm to the
poller (it waits, above), but its `[[collect]]` measurement fails every round until approval.

The scaffold prints the entries under "run it for good: add these entries through config_edit"
(the `[[machines]]` entry only for a kit with a poller). Add them with Orchestra's Python, from the
repository:

```python
import sys
from orchestra.config import load_project
p = load_project(); d = p.repo_root / ".orchestra" / "machines" / "pagerduty_alerts"   # or p.state_dir / "machines" / ...
for array, entry in [("machines", {"name": "pagerduty_alerts", "command": f"{sys.executable} {d}/pagerduty_alerts.py",
                                  "restart": "always"}),
                     ("collect", {"name": "pagerduty_alerts", "command": f"{sys.executable} {d}/pagerduty_alerts.py measure",
                                  "every": "5m", "timeout": "60s"})]:
    print(p.config_edit.add_entry(array, entry, target="overlay").what)
```

`orchestra run` picks both up within seconds. `[[machines]]` is the poll loop, every 5 minutes, and
it is restarted whenever it exits (`restart = "always"`). `[[collect]]` measures on the same
5-minute rhythm; between rounds the store carries the last value forward. It is the instrument,
named `pagerduty_alerts` on the Instruments page. Both share the name, but they are two different things.

### 5.4 The trial, against the fake, on a scratch project

```bash
cd "$(mktemp -d)" && git init -q && orchestra init       # a scratch project, never the company repository
orchestra bridges scaffold pagerduty pagerduty_alerts
PY="$(uv tool dir)/orchestra/bin/python"                   # Orchestra's Python (§4), which has the kits
"$PY" -c "import threading; from orchestra_bridges.kits.fakes import FakePagerDuty
f = FakePagerDuty(token='test-token').start(); print(f.url, flush=True); threading.Event().wait()" &   # prints its URL
# run 5.3 here, adding  --base-url <the fake's URL>  to both commands; then:
PAGERDUTY_TOKEN=test-token orchestra run &
orchestra web --port 8077                                 # then look, §9
```

The trial should publish `pagerduty.incident.triggered` on `PINC001` as `bot.pagerduty`, and
`pagerduty.incident.acknowledged` on `PINC002` as `person.pagerduty.puser01`. Each actor is
announced once. The instrument stores two points of `pagerduty_incidents_open`. A token in the environment is fine for the fake's token only.

### 5.5 Not a Workflows item

A poller is never scheduled as a Workflows item or role: it is a relay, not a machine (rule 2),
and must not be declared as one. Keep its `[[machines]]` and `[[collect]]` entries. A workflow
consumes what it relays: wait on its events (`github.pr.approved`, `jira.issue.assigned`) and
declare the system, managed elsewhere, as `bot.<system>`.

## 6. Jira (Data Center or Cloud)

```bash
orchestra bridges scaffold jira jira_ops --root repo   # not "jira": that is the system's (the machine's) name
```

Set `[settings]` in `poller.toml`: `base_url = "https://jira.<company>.com"`, `jql = "project = OPS"`
(no `ORDER BY`), `every = "5m"`, `per_minute = 20`, `lookback`, `overlap`. Each poll searches
`(<jql>) AND updated >= "-Nm" ORDER BY updated ASC` with the changelog, fresh (`ttl_s=0`). It emits
`jira.issue.transitioned` once per status change: the issue key as subject, `person.jira.<login>`
(or `bot.jira`) as source, the changelog id as stamp, and from/to as data. `measure` prints
`jira_issues{status, category}`. `keep_changes` keeps keys, logins, status names and times, and
drops summaries.

`[settings] flavour`: `datacenter` (REST v2 `/search`, a personal access token as Bearer) or
`cloud` (REST v3 `/search/jql`, the account's email in `user_file`/`user_env` plus an API token,
as HTTP Basic). `auto` picks `cloud` on `*.atlassian.net`; a Cloud site on its own domain must say
`cloud`. `jira.issue.assigned` is published for any assignee.

Assignments are built in: `jira.issue.assigned` for each change of assignee (`stamp`
`<changelog id>:assignee`; an issue created assigned gets one too). Use these event names, so every
Jira collector agrees. A changelog that the search cut short (`changelog.total > maxResults`) needs
`/rest/api/2/issue/<key>?expand=changelog`; add that before you rely on long histories.

## 7. Slack (channel history, with mentions)

The owner tracks "about six channels, mine and other teams'" and wants to "respond to Slack
quickly" (work charter §3D). For a channel's traffic, and for pings to the owner (the mention
filter below), scaffold the `slack` kit:

```bash
orchestra bridges scaffold slack team_channels --root repo
```

Set `[settings]`: `channels = ["C0123", "C0456"]` (ids, not names), `every = "5m"` and
`per_minute = 20` (`conversations.history` is Tier 3, about 50 a minute). The token needs
`channels:history` (and `groups:history` for private channels) and `users:read`. Each message
becomes `slack.message.posted`: subject `<channel>/<thread ts>`, source `person.slack.<member id>`
or `bot.slack.<id>`, and data `channel`, `reply` and `bot`. `measure` prints
`slack_channel_messages_last_hour{channel}`.

**Mention filtering** works in memory and keeps ids only. In `keep_history`, check each message's
text against the ids to watch, and keep only what matched:

```python
WATCH = ["U0OWNER", "S0TEAMGROUP"]             # or settings.extra["watch"]
def mentions(text):                            # called inside keep_history; the text is never kept
    return [w for w in WATCH if f"<@{w}>" in text or f"<!subteam^{w}" in text]
# in keep_history's message dict:  "mentions": mentions(m.get("text", "")),
# in poll:  p.emit("slack.message.mentioned" if m["mentions"] else "slack.message.posted", ..., data={..., "mentions": m["mentions"]})
```

Thread replies are not in `conversations.history` (only parents and broadcasts). Reading them
costs one `conversations.replies` call per thread, so leave them out unless the owner asks.

## 8. Chronosphere (a Prometheus-API store)

This is strategy (a). Nothing is copied and you write no code. Add the entry to the overlay:

```python
p.config_edit.add_entry("sources", {
    "name": "chronosphere", "url": "https://<tenant>.chronosphere.io/data/metrics",
    "auth": {"bearer_file": "~/.config/orchestra-bridges/chronosphere-token"},     # or bearer_env
    "prefix": "chrono", "machine": "service",                  # series chrono:<name>; machines chrono.<service>
    "match": ['{__name__=~"http_requests_total|http_request_duration_seconds_count|kube_deployment_status_replicas_available"}'],
    "max_series": 150, "rate": 2.0, "max_requests_per_day": 5000,
    "labels": {"service": ["service", "app", "k8s_app", "job"]}}, target="overlay")
```

- **`match`** limits inference to what matters. Never leave a big tenant on the default: a `match`
  that selects more than 2,000 metric names is refused.
- **`max_series`** caps what discovery reads, at most 12 per family.
- **`labels`** are aliases: the first spelling a metric has becomes `service`.
- **`rate` and `max_requests_per_day`** are per store, shared by every project and process on the
  machine (`~/.orchestrator/stores/`). Set them under the tenant's published limits.
- **A query you need exactly** (an SLO, a ratio) is a hand-written `[[series]]` (`source =
  "chronosphere"`, `name`, `query`, `kind = "level" | "counter" | "rate"`). It is read in place too.
- **Then check it:** `orchestra sources check` probes the endpoints and credentials and never shows
  the value. `orchestra sources infer --source chronosphere` shows what was kept and left out, and
  why. `orchestra sources preview 'sum by (service) (rate(http_requests_total[5m]))' --source chronosphere`
  reads a query's fan-out.

**Fallback: the `promql` kit.** Use it only when `[[sources]]` cannot be used: the tenant needs an
auth kind not built yet (command, OAuth2, SigV4), or a series must be computed and stored here. It
copies data into Orchestra's own store, which a source avoids, so keep it small.

```bash
orchestra bridges scaffold promql chrono_slo
```

Set `[settings]`: `base_url` (the API root that serves `/api/v1/query`), `token_env`,
`ttl = "50s"`, `max_series`, `aliases = { k8s_cluster = "cluster" }`, and one
`[[settings.queries]]` (`name`, `query`, `help`) per gauge. It has no poller. Add only its
`[[collect]]` entry (`python …/chrono_slo.py measure`, every 60 s).

## 9. Confirm it works

There is no single `orchestra check` command for an integration. These checks do its job:

| Check | What you should see |
|---|---|
| the program's test | passes, against the fake, with the canary check |
| `orchestra bridges integrations` | the poller, `approved`, its token's variable name, scheduled (`[[machines]]` or `every`), `[[collect]]` `yes`, no guesses left |
| `<state>/logs/machines/<name>.log` | `poll N: K events`; no `poll failed` |
| `<state>/logs/instruments/<name>.log` | `wrote N points` |
| `orchestra metrics series \| grep pagerduty` | `pagerduty_incidents_open instrument=pagerduty_alerts service=PSVC001 urgency=high` (the name, then labels separated by spaces) |
| `orchestra sources check` / `infer` | the source `ok`, its definitions kept (strategy (a)) |
| **Instruments page** (`/instruments`) | the `[[collect]]` entry: its target, interval, last write, no failures, its log |
| **Machines page** (`/machines`) | `bot.pagerduty` and `person.pagerduty.<id>` (people, with the `package` you gave), edges by event type, and hand-offs on incident ids that two actors touched; the declared `PagerDuty` dashed until confirmed. **No node named after your poller** |
| **Dynamics page** (`/dynamics`) | after discovery (every 5 min, over an hour of data), `pagerduty_incidents_open` as a stock or series, its flows' hypotheses naming `bot.pagerduty` and the people |

**Hand-offs need two actors on one subject.** A hand-off is drawn only when one actor acts on a
subject and then a different actor acts on the same subject (`bot.pagerduty` triggers `PINC001`,
then `person.pagerduty.puser02` resolves it). If every subject has a single actor (each build
started and finished by the same bot), there are no hand-offs. That is correct, not a fault: the
machines and their event types still show.

For the API, send the web token: `curl -s -H "Authorization: Bearer $(orchestra web token)"
localhost:8077/api/instruments` (and `/api/machines`).

## 10. The checklist (the stranger test)

Run it at the end. Every line must be true.

- [ ] `poller.toml` says `clearance = "needs approval"` until the owner approved this system (in
      writing, naming its token's scope and "metadata only"). You did not change it yourself.
- [ ] The token is only in the environment (by name in `token_env`) or in
      `~/.config/orchestra-bridges/<name>-token` (`chmod 600`). Grep for the *value's shape*,
      not the word (which matches `token_env` and `token_file`): `grep -rEn
      '(xox[bpa]-|Bearer [A-Za-z0-9._-]{12,}|[A-Za-z0-9+/=_-]{32,})' <overlay> <state>/machines/<name>
      <repository>` finds nothing but hashes you can explain.
- [ ] Files are in `.orchestra/machines/<name>/` on a pull request the owner approves (or in
      `~/.orchestrator/<key>/machines/<name>/` because the owner keeps the repository clean), and
      entries are in the overlay. The program writes nothing to the system; any write is an Outbox draft.
- [ ] The test passes against the fake, with the canary and token check.
- [ ] Every event's `source` is the actor (`person.<system>.<account>` or `bot.<system>`), its
      `subject` is the item, its `type` is `<system>.<item>.<what>`, and its stamp changes only
      when the item does.
- [ ] A restart publishes nothing twice: the second `--once` emits only what changed.
- [ ] `keep` keeps metadata only, and change reads use `ttl_s=0`. `per_minute` and `ttl` stay under
      the system's budget.
- [ ] The scratch trial (§5.4) shows the instrument and the actors on the pages, and hand-offs
      wherever two actors acted on one subject (one actor per subject gives none, and that is correct).
- [ ] No event's `time` is more than 60 s in the future (check `orchestra run`'s output).
- [ ] A ratio is printed only as a gauge beside its counts, and the outcomes are event types.
- [ ] The machine is declared, or the declaration is handed to the Supervisor, with an expected effect.
- [ ] The entries (`[[machines]]`, or the `workflows.every` item of §5.5, and `[[collect]]`) were
      added after the approval, not before (§5.3).
- [ ] `orchestra bridges integrations` lists the poller with `clearance` `approved`, the token as
      `$<THE_VARIABLE>`, `scheduled` `[[machines]]` or `every` (`-` for a measurement only),
      `[[collect]]` `yes` and `guesses` `0`.

## 11. Troubleshooting

- **"the environment variable X is not set" / "no token file at …"**: ask the owner to set it, never
  in the chat. "readable by others" means run `chmod 600 <file>`. A variable set in your shell but
  not in `orchestra run`'s environment is invisible to the processes the host launches.
- **"… is not cleared"**: this is the compliance check working as intended. Use the fake
  (`--base-url http://127.0.0.1:…`) until the owner approves.
- **`waiting for approval` in the poller's log**: its `[[machines]]` entry is in, the approval is
  not. It reads nothing until `poller.toml` says `clearance = "approved"`, then polls on its own.
- **HTTP 401 or 403**: the wrong token, or a scope it lacks (Slack: `channels:history`,
  `users:read`; PagerDuty: a read-only REST key sent as `Token token=…`; Jira DC: a personal access
  token sent as `Bearer`). Look at the status code only, never the body.
- **Rate-limited (`HTTP 429` in the log)**: the client waited `Retry-After` and gave up after its
  retries. Raise `every`, raise `ttl`, lower `per_minute`, or narrow the query (fewer channels, a
  tighter JQL). For a source, lower `rate`. Its daily cap shows in `orchestra sources check`.
- **Nothing on the Machines page**: is the process running (the Core page, its log)? Did the poll
  emit anything (`poll N: 0 events` on the first run means nothing changed within `lookback`)? Were
  the ids already emitted (`kits/pollers/<name>/`)?
- **Nothing on the Instruments page**: the `[[collect]]` entry is missing (check `/api/project`),
  the command fails (its log under `logs/instruments/`), or it prints a series named `orchestra_*`
  (refused).
- **Wrong subject, no hand-offs**: the subject must be the item, the same in every event about it
  (the Jira key, the incident id, the Slack thread). It must never be a channel alone, a timestamp
  or the poller's name.
- **"a poller publishes only as the person or bot who acted"**: you passed the poller's name as
  `source`. Use `actor_source` (rule 7).
- **The same change published twice under different ids**: the stamp moved without a change (a
  hash of data that includes a timestamp), or a bridge and your poller read the same items.
