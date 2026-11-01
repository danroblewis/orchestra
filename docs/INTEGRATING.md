# Integrating an outside system

Status: draft for the stranger test, 2026-11-01

This page is for a coding tool working alone, with no other context, and for the Supervisor (task
I3 of `docs/roadmap/GOAL-2026-11-01-workflows.md` turns it into a flow). It shows how to bring Jira,
Slack, PagerDuty and Chronosphere (or any similar system) into Orchestra. The owner put it this way: "it's integration as in
we give the Supervisor the knowledge and abilities to easily make its own solutions." Every command
and file here can be run as written. Replace `<…>` with your own values.

## 1. What an integration is here

Orchestra never calls an outside system. A **machine** or an **instrument** does, and Orchestra sees
only what they give it (`AGENTS.md` rules 1, 2 and 7). An integration can give three things:

| What | It means | Where it shows |
|---|---|---|
| **Series** | a measurement: "4 incidents open", "37 issues in progress" | the Instruments page, then the Dynamics page (stocks and flows are discovered from series) |
| **Events** | something happened, to one item: "PINC1 was acknowledged by PUSER" | the Machines page: the actor is a machine, and the `subject` is the item |
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
script prints Prometheus text, and a `[[scrape]]` reads a URL that already serves it. It is an
instrument: it measures and never acts (`docs/machines.md`).

**(c) A Programmatic Machine that polls an API.** *Use this when* you want **events**: what happened
to each item, and who did it. A small program reads what changed since its cursor, every N minutes
(5 by default), and posts one CloudEvent per change. Its measurement half is a `[[collect]]` entry
that runs the same file with `measure`. It runs in one of two ways:
- as a `[[machines]]` entry: a continuous process with its own interval loop, kept running by
  `orchestra run`. This needs no plugin;
- with the Workflows plugin installed, as a scheduled item (`[workflows.every.<name>]`) that runs
  the program once per interval (§5.4).

**(d) The bridges plugin's readers, where one exists:** Jira (Data Center or Cloud: issues, changes
and comments, plus counts by status category), Slack *pings* (mentions of you and DMs to you, and
whether you answered), and GitHub issues and pull requests (`~/orchestra-bridges/README.md`).
*Use this when* it already reads what you need. Before you write (c), check (d): it is configuration
only (`[bridges.jira]`, and so on). Never run both over the same items: they would publish the same
changes twice, under different ids.

| System | Series | Events |
|---|---|---|
| Chronosphere | (a), §8 | none: a metrics store has no item events |
| PagerDuty | (c)'s `measure`: open incidents | (c), §5 |
| Jira | (d) `jira_issues`, or (c)'s `measure` | (d) on Data Center, or (c), §6 |
| Slack | (c)'s `measure`: messages per channel | (c) for channel history, §7; (d) for pings to you |

## 3. Rules that bind every strategy

1. **Where files go.** By default they go in the state directory: `~/.orchestrator/<key>/integrations/<name>/`
   (the program, its test, `cursor.json`, `cache/`). Configuration entries go in the **private
   overlay** (`~/.orchestrator/<key>/orchestra.local.toml`), written through
   `project.config_edit` with `target="overlay"` (the default target is the repository, so always
   pass it). The company repository changes only through a pull request the owner approves. It
   then uses the `.orchestra/` shape (`.orchestra/instruments/`, `.orchestra/machines/<id>/`) and
   `target="repo"`. To find `<key>`, run `python -c "from orchestra.config import load_project; print(load_project().state_dir)"`
   in the repository.
2. **Credentials come from an environment variable name or a token file, never from the config.**
   Never put a token in `orchestra.toml` or the overlay: Orchestra refuses a source whose config holds one. The
   token file is `~/.config/orchestra-bridges/<name>-token` (`install -m 600 /dev/null <file>`,
   then the owner pastes the token in), outside every repository and readable only by its owner.
   Prefer the file for anything `orchestra run` launches: every launched process inherits the
   host's environment, so a token in that environment reaches every machine. Never print, log, echo
   or commit a token, and never ask for one in a chat. Ask the owner to put it in the file.
3. **Rate limits and caching.** Each integration gets one client per host, which sends at most
   one request per `gap_s` (1 s), retries 429 and 5xx after `Retry-After` or a jittered backoff,
   and caches answers on disk for a TTL. Reads for measurements are cached, typically 240 s. Reads
   for changes (since the cursor) are never cached. A measurement every 60 s with a 240 s TTL calls
   the API about every 4 minutes. A `[[sources]]` store is limited by Orchestra itself (`rate`,
   `max_requests_per_day`, shared by every process on the machine, `sources/limits.py`). Never go
   over a store's documented budget. If you are unsure, poll less often.
4. **Compliance comes before the first read** (`docs/work-charter.md` §8, a FedRAMP environment).
   Before any real call to a company system, stop and get the owner's written yes, naming the
   system, the token's scope and "metadata only". Until data classes exist, no company system is
   cleared by default. Do not guess. Two more rules follow:
   - **Never text.** Events, series, logs and cache files hold only metadata: ids, keys, accounts,
     states, names an administrator defines, numbers and times. Titles, descriptions, messages and
     comments pass through memory and are dropped there (as the bridges do: their rule 1). The
     cache stores only what `keep` returns.
   - **Your own session is a model too.** Build and test against the fake server. Never paste a
     real API answer into your conversation. To inspect real data, print counts and field names
     only.
5. **Idempotent emission.** Every event's `id` is built from the system's own id for that
   occurrence (`pagerduty:log_entry:<id>`, `jira:<site>:issue:<id>:history:<id>:status`). The
   events endpoint does not write an id it has already seen (it remembers the last 10,000). The
   cursor (`cursor.json`) is saved only after a round has posted everything, and every round reads
   again `overlap` (10 min) before the cursor. So a restart or a retry never duplicates and never
   skips.
6. **The envelope** (SPEC §2). `type` starts with the system's name and then says what happened:
   `jira.issue.transitioned`, `slack.message.posted`, `pagerduty.incident.acknowledged`. `source` is
   **who acted**: `person.<system>.<account>` for a person, `bot.<system>` for the system's own act.
   An instance is `<machine>/<instance>`. `subject` is the item: the Jira key (`ABC-12`),
   `pagerduty:<incident id>`, the Slack thread `<workspace>/<channel>/<thread ts>`. The Machines
   page infers hand-offs from subjects. `time` is the system's own (RFC 3339 with a zone), and
   `data` is metadata only.
7. **Your poller is not a machine** (`AGENTS.md` rule 2, decision D19: "the provider is never the
   machine"). The polling program is a relay. It never publishes under its own name, never
   announces itself and never writes a metric. The machines are the people and bots it relays,
   and each one is **announced** once before its first event: `orchestra.machine.started` from
   their source, with `{"mode": "ad hoc", "kind": "person" | "program", "package": "<name>"}`.
   The kit does this for you. Under the Workflows plugin the program's *runs* are a machine
   (`<id>/<n>` claims its turns), which is that plugin's business.
8. **Declare it on the Machines page with its expected effect** (§5.5). A declaration is a
   hypothesis: it names the machine (`^[a-z][a-z0-9_]{1,40}$`, e.g. `pagerduty`), says
   `managed: "external"` (it runs elsewhere), gives its engagement and what it emits, joins it to
   the observed source (`alias` → `bot.pagerduty`), and predicts its effect ("a flow into open
   incidents appears"). The owner confirms it on the page. It changes no flow and no equation.
9. **Test against a fake before any real call.** Every integration ships a fake server in the
   real response shapes, with a canary string in every text field, and a test that checks the
   events (types, sources, subjects, ids), the printed series, that the cache works, and that the
   canary appears nowhere: not in events, output or files.
10. **Confirm it works** with §9's commands and pages. A trial on a scratch project against the
    fake comes first, then the real one.

## 4. Kits (intended interface; being built as task I2)

Task I2 is building these in `~/orchestra-bridges` (`orchestra_bridges/kits/`). Until they land,
or when they are not installed (`python -c "import orchestra_bridges.kits"` fails), use
`minikit.py` below, which has the same names.

| Name | What it does |
|---|---|
| `state_dir(name)` | `<state>/integrations/<name>/`, made on demand (`$INTEGRATION_STATE` overrides, for tests) |
| `read_token(env, file)` | the token from `$env`, else from a `chmod 600` file outside the repository. Exits with a plain message if it is missing. Never prints it |
| `CachedClient(base, *, name, headers, ttl_s=300, gap_s=1.0, retries=4)` | `.get(path, params, *, keep=None, ttl_s=None)` returns parsed JSON. It caches on disk only what `keep(body)` returns, keeps per-host spacing, retries 429/5xx with `Retry-After`, and never logs a header |
| `Emitter(package)` | `.emit(type=, source=, kind=, subject=, id=, time=, data=)` posts to the events endpoint (`ORCHESTRA_EVENTS_ENDPOINT`, `_TOKEN`), and announces each actor once first |
| `run_poller(name, poll, *, every_s=300, overlap_s=600, lookback_s=3600, once=False)` | the loop: `poll(since)` returns event dicts, it posts them, then saves the cursor. A failed round says why on stderr and is retried next interval. With `once=True` it runs one round, and the return value is the exit code |
| `PromQuery(url, *, token_env, token_file, aliases)` | `.instant(q)` and `.range(q, start, end, step)` against a Prometheus API, label aliases applied (for §8's fallback) |
| `orchestra_bridges.kits.fakes` | fake Jira, Slack, PagerDuty and Prometheus servers in the real shapes, with a canary in every text field |
| `python -m orchestra_bridges.kits scaffold <system> --root <dir>` | writes a new integration from a kit: `poll.py`, `test_poll.py`, `machine.toml` (its name, interval, token's env and file names, clearance) and `AGENTS.md` for the coding tool |

**Without a kit**, save this as `minikit.py` beside your `poll.py`. It uses only the standard
library, which Orchestra's Python has (it has no `requests`). The interface is the same: a TTL
cache on disk, spacing and retries, idempotent posts and a persisted cursor.

```python
"""minikit.py: a stand-in for orchestra_bridges.kits, standard library only, same names."""
import hashlib, json, os, random, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

def state_dir(name):
    base = os.environ.get("INTEGRATION_STATE")
    if not base:
        from orchestra.config import load_project
        base = load_project().state_dir / "integrations"
    (d := Path(base) / name).mkdir(parents=True, exist_ok=True)
    return d

def read_token(env, file):
    if os.environ.get(env):
        return os.environ[env].strip()
    p = Path(file).expanduser()
    if not p.is_file():
        sys.exit(f"no token: set {env} or put it in {p} (chmod 600)")
    if p.stat().st_mode & 0o077:
        sys.exit(f"{p} is readable by others: chmod 600 {p}")
    return p.read_text().strip()

class CachedClient:
    def __init__(self, base, *, name, headers, ttl_s=300, gap_s=1.0, retries=4):
        self.base, self.headers, self.ttl, self.gap, self.retries = base.rstrip("/"), headers, ttl_s, gap_s, retries
        self.cache = state_dir(name) / "cache"
        self.cache.mkdir(exist_ok=True)
        self.last = 0.0

    def get(self, path, params=None, *, keep=None, ttl_s=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        ttl, f = self.ttl if ttl_s is None else ttl_s, self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if keep and ttl and f.exists() and time.time() - f.stat().st_mtime < ttl:
            return json.loads(f.read_text())
        for attempt in range(self.retries + 1):
            time.sleep(max(0.0, self.last + self.gap - time.time()))
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.headers), timeout=30) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise RuntimeError(f"GET {path}: HTTP {e.code}") from None
                time.sleep(min(float(e.headers.get("Retry-After") or 2 ** attempt + random.random()), 300))
        if keep:                          # only metadata reaches the disk
            f.write_text(json.dumps(body := keep(body)))
        return body

class Emitter:
    def __init__(self, package):
        self.url = os.environ["ORCHESTRA_EVENTS_ENDPOINT"].rstrip("/") + "/events"
        self.hdr = {"Authorization": "Bearer " + os.environ["ORCHESTRA_EVENTS_TOKEN"], "Content-Type": "application/json"}
        self.package, self.announced = package, set()

    def post(self, ev):
        req = urllib.request.Request(self.url, json.dumps(ev).encode(), self.hdr, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("duplicate", False)

    def emit(self, *, type, source, kind, subject, id, time, data):
        if source not in self.announced:
            self.post({"type": "orchestra.machine.started", "source": source, "time": time, "id": f"announce:{source}",
                       "data": {"mode": "ad hoc", "kind": kind, "package": self.package, "listens_for": []}})
            self.announced.add(source)
        return self.post({"type": type, "source": source, "subject": subject, "id": id, "time": time, "data": data})

def run_poller(name, poll, *, every_s=300, overlap_s=600, lookback_s=3600, once=False):
    em, f = Emitter(name), state_dir(name) / "cursor.json"
    while True:
        started, ok = time.time(), True
        since = json.loads(f.read_text())["since"] if f.exists() else started - lookback_s
        try:
            for ev in poll(since - overlap_s):
                em.emit(**ev)
            (tmp := f.with_suffix(".tmp")).write_text(json.dumps({"since": started}))
            tmp.replace(f)                # saved only after everything was posted
        except Exception as e:            # say what failed; never a body or a header
            print(f"{name}: poll failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            ok = False
        if once:
            return 0 if ok else 1
        time.sleep(max(5.0, every_s - (time.time() - started)))
```

## 5. Worked example: PagerDuty

The owner wants to be "aware of PagerDuty alerts" and "of every outage as it happens" (work charter
§3D–E). The events are each incident's log entries: triggered, acknowledged, escalated and resolved,
each by whoever did it. The series is the incidents open now, by status.

### 5.1 The program: `~/.orchestrator/<key>/integrations/pagerduty/poll.py`

```python
"""PagerDuty -> pagerduty.incident.* events (run), and open incidents as series (measure)."""
import os, sys, time
from datetime import UTC, datetime
try:
    from orchestra_bridges.kits import CachedClient, read_token, run_poller
except ImportError:
    from minikit import CachedClient, read_token, run_poller

KINDS = {"trigger_log_entry": "triggered", "acknowledge_log_entry": "acknowledged",
         "escalate_log_entry": "escalated", "assign_log_entry": "assigned", "resolve_log_entry": "resolved"}

def client():
    token = read_token("PAGERDUTY_TOKEN", "~/.config/orchestra-bridges/pagerduty-token")
    return CachedClient(os.environ.get("PAGERDUTY_API", "https://api.pagerduty.com"), name="pagerduty", ttl_s=240,
                        headers={"Authorization": f"Token token={token}", "Accept": "application/vnd.pagerduty+json;version=2"})

def translate(entry):
    kind = KINDS.get(entry.get("type"))
    if not kind:
        return None
    agent, inc = entry.get("agent") or {}, entry["incident"]
    person = agent.get("type") == "user_reference"
    return {"type": f"pagerduty.incident.{kind}", "subject": f"pagerduty:{inc['id']}",
            "source": f"person.pagerduty.{agent['id']}" if person else "bot.pagerduty",
            "kind": "person" if person else "program", "id": f"pagerduty:log_entry:{entry['id']}",
            "time": entry["created_at"], "data": {"incident": inc["id"], "service": (entry.get("service") or {}).get("id")}}

def poll(since):
    c, out, offset = client(), [], 0
    iso = lambda t: datetime.fromtimestamp(t, UTC).isoformat()
    while True:
        page = c.get("/log_entries", {"since": iso(since), "until": iso(time.time()), "is_overview": "true",
                                      "limit": 100, "offset": offset}, ttl_s=0)
        out += [e for e in map(translate, page["log_entries"]) if e]   # summaries dropped here, in memory
        if not page.get("more"):
            return sorted(out, key=lambda e: e["time"])
        offset += 100

def measure():
    c = client()
    for status in ("triggered", "acknowledged"):
        n = c.get("/incidents", {"statuses[]": status, "total": "true", "limit": 1}, keep=lambda b: {"total": b["total"]})
        print(f'pagerduty_incidents_open{{status="{status}"}} {n["total"]}')

if __name__ == "__main__":
    if sys.argv[1:] == ["measure"]:
        measure()
    else:
        sys.exit(run_poller("pagerduty", poll, every_s=300, once="--once" in sys.argv))
```

### 5.2 The fake and the test: `test_poll.py` (beside it)

```python
"""python test_poll.py: the test.  PORT=8765 python test_poll.py serve: the fake alone, for a trial."""
import contextlib, io, json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CANARY = "CANARY-7f3a"          # stands for every title and note; it must never leave memory

def entry(i, kind, agent, t):
    return {"id": f"L{i}", "type": f"{kind}_log_entry", "created_at": t, "summary": CANARY, "agent": agent,
            "service": {"id": "PSVC"}, "incident": {"id": "PINC1", "summary": CANARY}}

ENTRIES = [entry(1, "trigger", {"type": "service_reference", "id": "PSVC"}, "2026-11-02T10:00:00Z"),
           entry(2, "notify", {"type": "user_reference", "id": "PUSER"}, "2026-11-02T10:01:00Z"),
           entry(3, "acknowledge", {"type": "user_reference", "id": "PUSER"}, "2026-11-02T10:03:00Z")]

class Fake(BaseHTTPRequestHandler):
    calls = 0
    def do_GET(self):
        Fake.calls += 1
        if self.headers.get("Authorization") != "Token token=test-token":
            return self.send_error(401)
        if self.path.startswith("/log_entries"):
            body = {"log_entries": ENTRIES, "more": False}
        elif self.path.startswith("/incidents"):
            body = {"incidents": [{"id": "PINC1", "title": CANARY}], "total": 1}
        else:
            return self.send_error(404)
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *args):
        pass

def serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"

def test():
    tmp = tempfile.mkdtemp()
    os.environ.update(PAGERDUTY_API=serve(), PAGERDUTY_TOKEN="test-token", INTEGRATION_STATE=tmp)
    import poll
    evs = poll.poll(0)
    assert [e["type"] for e in evs] == ["pagerduty.incident.triggered", "pagerduty.incident.acknowledged"], evs
    assert [e["source"] for e in evs] == ["bot.pagerduty", "person.pagerduty.PUSER"]
    assert {e["subject"] for e in evs} == {"pagerduty:PINC1"} and evs[0]["id"] == "pagerduty:log_entry:L1"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        poll.measure(); poll.measure()
    assert 'pagerduty_incidents_open{status="triggered"} 1' in out.getvalue()
    assert Fake.calls == 3, "the second measure must come from the cache"
    files = [p.read_text() for p in Path(tmp).rglob("*") if p.is_file()]
    assert not any(CANARY in s for s in [json.dumps(evs), out.getvalue(), *files]), "text leaked"
    print("ok")

if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        print(serve(int(os.environ.get("PORT", "8765"))), flush=True); threading.Event().wait()
    else:
        test()
```

Run `python test_poll.py` in that folder. It prints `ok`.

### 5.3 The configuration (overlay), as a `[[machines]]` process

Run this once with Orchestra's Python, from the repository:

```python
from orchestra.config import load_project
p = load_project(); d = p.state_dir / "integrations" / "pagerduty"
for array, entry in [("machines", {"name": "pagerduty", "command": f"python {d}/poll.py"}),
                     ("collect", {"name": "pagerduty", "command": f"python {d}/poll.py measure",
                                  "every": "60s", "timeout": "30s"})]:
    print(p.config_edit.add_entry(array, entry, target="overlay").what)
```

`orchestra run` picks both up within seconds. The `[[machines]]` entry is the poll loop (every 5
minutes). The `[[collect]]` entry is the instrument, named `pagerduty` on the Instruments page. Both
share the name, but they are two different things. `python` in a command is Orchestra's own
Python, and `minikit.py` is found because it sits beside `poll.py`.

### 5.4 Or as a scheduled item, when the Workflows plugin is installed

Write `~/.orchestrator/<key>/machines/pagerduty_poller/machine.json`:

```json
{"id": "pagerduty_poller", "kind": "programmatic", "managed": "orchestra", "engagement": {"mode": "ad hoc"},
 "spec": {"command": "python /Users/<you>/.orchestrator/<key>/integrations/pagerduty/poll.py --once", "role": "pagerduty_poller",
          "exit": {"0": "landed", "1": "error"}}}
```

Then set the item with `p.config_edit.set("workflows.every.pagerduty_poll", {"every": "5m", "role":
"pagerduty_poller", "brief": "poll PagerDuty once"}, target="overlay")`. Leave out the
`[[machines]]` entry, but keep the `[[collect]]`.

### 5.5 The declaration on the Machines page

The Supervisor does this with `declare_machine` and `declare_expected_effect`
(`docs/proposals/machine-design.md` §2.3). Without the Supervisor, check that your Orchestra has the
intended-model layer: `curl -sf -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN"
"$ORCHESTRA_EVENTS_ENDPOINT/intended/design"` answers 200. If it does, post one call:

```bash
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/intended" -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" \
  -H "Content-Type: application/json" -d '{"source": "integrator", "author": "integrator",
  "reason": "PagerDuty brought in as events and an open-incidents series", "ops": [
  {"op": "declare_stock", "id": "open_incidents", "name": "Open incidents", "unit": "incidents"},
  {"op": "propose_machine", "id": "pagerduty", "title": "PagerDuty", "kind": "programmatic", "managed": "external",
   "engagement": {"mode": "continuous"}, "emits": ["pagerduty.incident.triggered", "pagerduty.incident.acknowledged",
   "pagerduty.incident.resolved"], "spec": {"source": "bot.pagerduty", "receive": "polled every 5 min (integrations/pagerduty)"}},
  {"op": "alias", "machine": "pagerduty", "observed": "bot.pagerduty"},
  {"op": "set_expected_effect", "machine": "pagerduty", "horizon_s": 86400,
   "edits": [{"from": null, "to": "open_incidents", "appears": true}]}]}'
```

`PagerDuty` then shows as proposed, and the owner confirms it on the page. Once a discovered stock
is `pagerduty_incidents_open`, the Supervisor `link`s `open_incidents` to it, and the prediction
can be published. If the call answers 404, the layer is not in your Orchestra yet: put the
declaration in your report for the Supervisor.

### 5.6 The trial, against the fake, on a scratch project

```bash
cd "$(mktemp -d)" && git init -q && orchestra init      # a scratch project, never the company repo
PORT=8765 python <dir>/test_poll.py serve &              # the fake
# copy poll.py, minikit.py, test_poll.py into this project's <state>/integrations/pagerduty/, run 5.3 here
PAGERDUTY_API=http://127.0.0.1:8765 PAGERDUTY_TOKEN=test-token orchestra run &
orchestra web --port 8077                                # then look, §9
```

`PAGERDUTY_TOKEN` in the environment is fine for a fake token only. For the real API the token
lives in `~/.config/orchestra-bridges/pagerduty-token`.

## 6. Jira (Data Center)

First check (d): `[bridges.jira]` in the bridges plugin reads Data Center with a personal access
token (`JIRA_API_TOKEN` or `~/.config/orchestra-bridges/jira-token`). It publishes
`jira.issue.created`, `.assigned`, `.transitioned`, `.updated` and `jira.comment.added` as the
people who did them, and serves `jira_issues{jira_project, category}`. Write your own only for what
it does not read. Take §5's `poll.py` and change these parts. The type names and the id scheme are
the bridge's, so the endpoint rejects anything the bridge already published.

```python
SITE, JQL = os.environ.get("JIRA_SITE", "jira.example.com"), os.environ["JIRA_JQL"]   # e.g. project = OPS
def client():
    token = read_token("JIRA_API_TOKEN", "~/.config/orchestra-bridges/jira-token")
    return CachedClient(f"https://{SITE}", name="jira", ttl_s=240,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
stamp = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z")                  # Jira's +0000 zone
who = lambda u: (f"person.jira.{u['name']}", "person") if u else ("bot.jira", "program")   # no author: Jira itself

def ev(kind, actor, issue, id, t, data):
    return {"type": f"jira.issue.{kind}", "source": actor[0], "kind": actor[1], "subject": issue["key"],
            "id": f"jira:{SITE}:issue:{issue['id']}:{id}", "time": stamp(t).isoformat(), "data": data}

def translate(issue, since):
    f, out = issue["fields"], []
    if stamp(f["created"]).timestamp() >= since:
        out.append(ev("created", who(f.get("creator")), issue, "created", f["created"], {"status": f["status"]["name"]}))
    for h in issue["changelog"]["histories"]:
        for item in h["items"] if stamp(h["created"]).timestamp() >= since else []:
            if item["field"] == "status":
                out.append(ev("transitioned", who(h.get("author")), issue, f"history:{h['id']}:status", h["created"],
                              {"from": item["fromString"], "to": item["toString"]}))
            elif item["field"] == "assignee":
                out.append(ev("assigned", who(h.get("author")), issue, f"history:{h['id']}:assignee", h["created"],
                              {"assignee": item.get("to")}))
    return out

def poll(since):
    c, out, start = client(), [], 0
    jql = f'{JQL} AND updated >= "-{int((time.time() - since) / 60) + 1}m" ORDER BY updated ASC'
    while True:
        page = c.get("/rest/api/2/search", {"jql": jql, "expand": "changelog", "startAt": start, "maxResults": 50,
                                            "fields": "created,creator,status"}, ttl_s=0)
        out += [e for issue in page["issues"] for e in translate(issue, since)]
        start += len(page["issues"])
        if not page["issues"] or start >= page["total"]:
            return sorted(out, key=lambda e: e["time"])

def measure():
    c = client()
    for cat in ("To Do", "In Progress", "Done"):
        n = c.get("/rest/api/2/search", {"jql": f'{JQL} AND statusCategory = "{cat}"', "maxResults": 0},
                  keep=lambda b: {"total": b["total"]})
        print(f'jira_issues_by_category{{category="{cat.lower().replace(" ", "_")}"}} {n["total"]}')
```

Notes: the search asks only for `created,creator,status`, so summaries are never fetched. `updated
>= "-Nm"` runs on Jira's clock, and `overlap` covers the skew. A changelog the search cut short
(`changelog.total > maxResults`) needs `/rest/api/2/issue/<key>?expand=changelog`, so add that
before you rely on long histories. The fake's issue has `fields.created`, `fields.creator.name`,
`fields.status.name`, and `changelog.histories[].{id, created, author.name, items[].{field,
fromString, toString, to}}`. Its summary carries the canary. Name the integration `jira_ops`, not
`jira`: a hand-made `jira` would collide with the bridge's names.

## 7. Slack (channel history, with mentions)

The owner tracks "about six channels, mine and other teams'" and wants to "respond to Slack
quickly". Pings to the owner are (d)'s Slack bridge (`[bridges.slack]`, a user token in
`~/.config/orchestra-bridges/slack-token`). For a channel's traffic, poll `conversations.history`
with a token that has `channels:history` (and `groups:history` for private channels). Slack
returns HTTP 200 with `"ok": false` on errors, and 429 with `Retry-After` when rate-limited. Check
your workspace's tier for this method before you pick `every_s`: six channels every 5 minutes is
about 1.2 calls a minute.

```python
WS, CHANNELS = os.environ.get("SLACK_WORKSPACE", "acme"), os.environ["SLACK_CHANNELS"].split(",")   # C0123,C0456
WATCH = [w for w in os.environ.get("SLACK_WATCH", "").split(",") if w]   # user ids (U…) and group ids (S…)
ONLY_MENTIONS = os.environ.get("SLACK_ONLY_MENTIONS") == "1"
def client():
    token = read_token("SLACK_TOKEN", "~/.config/orchestra-bridges/slack-history-token")
    return CachedClient(os.environ.get("SLACK_API", "https://slack.com/api"), name="slack_channels", ttl_s=240,
                        headers={"Authorization": f"Bearer {token}"})

def translate(ch, m):
    if m.get("subtype") not in (None, "bot_message", "thread_broadcast"):
        return None                                        # joins, topic changes, ...
    text = m.get("text", "")                               # checked here, in memory, and dropped
    mentions = [w for w in WATCH if f"<@{w}>" in text or f"<!subteam^{w}" in text]
    if ONLY_MENTIONS and not mentions:
        return None
    person = bool(m.get("user"))
    return {"type": "slack.message.mentioned" if mentions else "slack.message.posted",
            "source": f"person.slack.{m['user']}" if person else f"bot.slack.{m.get('bot_id', 'unknown')}",
            "kind": "person" if person else "program", "subject": f"{WS}/{ch}/{m.get('thread_ts') or m['ts']}",
            "id": f"slack:{WS}:{ch}:{m['ts']}", "time": datetime.fromtimestamp(float(m["ts"]), UTC).isoformat(),
            "data": {"channel": ch, "ts": m["ts"], "thread_ts": m.get("thread_ts"), "mentions": mentions}}

def history(c, ch, oldest, ttl_s=0, keep=None):
    msgs, cursor = [], None
    while True:
        p = c.get("/conversations.history", {"channel": ch, "oldest": f"{oldest:.6f}", "limit": 200,
                                             **({"cursor": cursor} if cursor else {})}, ttl_s=ttl_s, keep=keep)
        if not p.get("ok"):
            raise RuntimeError(f"slack: {p.get('error')}")
        msgs += p["messages"]
        if not (cursor := (p.get("response_metadata") or {}).get("next_cursor")):
            return msgs

def poll(since):
    c = client()
    return sorted((e for ch in CHANNELS for m in history(c, ch, since) if (e := translate(ch, m))), key=lambda e: e["time"])

def measure():
    c, hour = client(), time.time() // 300 * 300 - 3600    # a stable `oldest`, so the cache can hit
    slim = lambda b: {**b, "messages": [{"ts": m["ts"]} for m in b.get("messages", [])]}
    for ch in CHANNELS:
        print(f'slack_channel_messages_last_hour{{channel="{ch}"}} {len(history(c, ch, hour, ttl_s=240, keep=slim))}')
```

Thread replies are not in `conversations.history` (only the parent and broadcasts). Reading them
costs one `conversations.replies` call per thread, so leave them out unless the owner asks. The
fake serves `conversations.history` with `ok`, `messages[].{ts, user, text, thread_ts, subtype}`
and `response_metadata.next_cursor`, with the canary in every `text`.

## 8. Chronosphere (a Prometheus-API store)

Strategy (a). Nothing is copied and you write no code. Add the entry to the overlay:

```python
p.config_edit.add_entry("sources", {
    "name": "chronosphere", "url": "https://<tenant>.chronosphere.io/data/metrics",
    "auth": {"bearer_file": "~/.config/orchestra-bridges/chronosphere-token"},     # or bearer_env
    "prefix": "chrono", "machine": "service",                  # series chrono:<name>; machines chrono.<service>
    "match": ['{__name__=~"http_requests_total|http_request_duration_seconds_count|kube_deployment_status_replicas_available"}'],
    "max_series": 150, "rate": 2.0, "max_requests_per_day": 5000,
    "labels": {"service": ["service", "app", "k8s_app", "job"]}}, target="overlay")
```

- **`match`** keeps inference to what matters. Never leave a big tenant on the default (a `match`
  that selects more than 2,000 metric names is refused).
- **`max_series`** caps what discovery reads (at most 12 per family). **`labels`** are aliases:
  the first spelling a metric has becomes `service`.
- **`rate` and `max_requests_per_day`** are per store, shared by every project and process on the
  machine (`~/.orchestrator/stores/`). Set them under the tenant's published limits.
- A query you need exactly (an SLO, a ratio) is a hand-written `[[series]]` (`source =
  "chronosphere"`, `name`, `query`, `kind = "level" | "counter" | "rate"`). It is read in place too.
- Then run `orchestra sources check` (endpoints and credentials, never the value),
  `orchestra sources infer --source chronosphere` (what was kept and left out, and why), and
  `orchestra sources preview 'sum by (service) (rate(http_requests_total[5m]))' --source chronosphere`.

**Fallback: a PromQL poller.** Use it only when `[[sources]]` cannot be used, for example when the
tenant needs an auth kind not built yet (command, OAuth2, SigV4). It is a `[[collect]]` script that
runs a few instant queries and prints them. It copies data into Orchestra's own store, which a
source avoids, so keep it small (a handful of queries, every 60 s, cached for 60 s):

```python
"""chrono_measure.py: a few PromQL instant queries, printed as series (a [[collect]] instrument)."""
import os
try:
    from orchestra_bridges.kits import CachedClient, read_token
except ImportError:
    from minikit import CachedClient, read_token
QUERIES = {"checkout_requests_per_second": 'sum by (service) (rate(http_requests_total{service="checkout"}[5m]))'}
token = read_token("CHRONOSPHERE_TOKEN", "~/.config/orchestra-bridges/chronosphere-token")
c = CachedClient(os.environ.get("CHRONOSPHERE_URL", "https://<tenant>.chronosphere.io/data/metrics"),
                 name="chronosphere_fallback", ttl_s=60, gap_s=2.0, headers={"Authorization": f"Bearer {token}"})
for name, q in QUERIES.items():
    for r in c.get("/api/v1/query", {"query": q}, keep=lambda b: b)["data"]["result"]:
        labels = ",".join(f'{k}="{v}"' for k, v in r["metric"].items() if k != "__name__")
        print(f"{name}{{{labels}}} {r['value'][1]}")
```

## 9. Confirm it works

There is no single `orchestra check` command yet. These checks do its job:

| Check | What you should see |
|---|---|
| `python test_poll.py` | `ok` |
| `orchestra events info` and the poll's log `<state>/logs/machines/<name>.log` | events counted; no `poll failed` lines |
| `curl -s -H "Authorization: Bearer $(orchestra web token)" localhost:<port>/api/instruments` | your instrument, a recent `last write`, `failures: 0` |
| `orchestra metrics series \| grep pagerduty` | `pagerduty_incidents_open{instrument="pagerduty",status=…}` |
| `orchestra sources check` / `infer` | the source `ok`, its definitions kept (strategy (a)) |
| **Instruments page** (`/instruments`) | the `[[collect]]` entry, its target, interval, last write and log |
| **Machines page** (`/machines`) | `bot.pagerduty` and `person.pagerduty.<id>` (people, with the `package` you gave), edges by event type, a hand-off on `pagerduty:<incident>`; the declared `PagerDuty` dashed until confirmed. **No node named after your poller** |
| **Dynamics page** (`/dynamics`) | after discovery (every 5 min, over an hour of data), `pagerduty_incidents_open` as a stock or series, its flows' hypotheses naming `bot.pagerduty` and the people |

## 10. The checklist (the stranger test)

Run it at the end. Every line must be true.

- [ ] The owner's written yes for this system, its token's scope and "metadata only" is recorded
      in `machine.toml` (or the report) before the first real call.
- [ ] The token is only in `~/.config/orchestra-bridges/<name>-token` (`chmod 600`) or named by
      environment variable. `grep -ri token` over the overlay and the repository finds no value.
- [ ] Files are in `~/.orchestrator/<key>/integrations/<name>/`, entries in the overlay. Nothing was
      committed to the company repository (or there is an open pull request the owner asked for).
- [ ] `python test_poll.py` prints `ok`, against the fake, with the canary check.
- [ ] Every event has a stable `id` from the system's ids, `source` is the actor
      (`person.<system>.<account>` or `bot.<system>`), `subject` is the item, and `type` is `<system>.<item>.<what>`.
- [ ] A restart publishes nothing twice (`duplicate: true` on re-posts), and the cursor is saved
      after the posts.
- [ ] Cached reads keep metadata only, and change reads are not cached. The API is called no more
      often than the TTL and interval allow.
- [ ] The scratch trial (§5.6) shows the instrument, the actors and the hand-offs on the pages.
- [ ] The machine is declared (or the declaration is handed to the Supervisor) with an expected effect.

## 11. Troubleshooting

- **"no token: set X or put it in …"**: the file is missing or empty. Ask the owner to paste the
  token into it, and never into the chat. "readable by others" means run `chmod 600 <file>`. A token
  set in your shell but not in `orchestra run`'s environment is invisible to launched processes,
  which is one more reason to use the file.
- **HTTP 401 or 403**: the wrong token, or a scope it lacks (Slack: `channels:history`; PagerDuty: a
  read-only REST key; Jira DC: a personal access token sent as `Bearer`). Look at the status code
  only, never the body.
- **Rate-limited (429, `poll failed: … HTTP 429` in the log)**: the client already waited
  `Retry-After` and gave up after 4 tries. Raise `every_s`, raise the measurement TTL, or narrow
  the query (fewer channels, a tighter JQL). For a source, lower `rate`. Its daily cap shows in
  `orchestra sources check`.
- **Nothing on the Machines page**: is the process running (the Core page, its log)? Is
  `ORCHESTRA_EVENTS_ENDPOINT` set? It is set only for processes `orchestra run` launched; by hand,
  run `eval "$(orchestra events endpoint --env)"`. Did `poll` return anything (`lookback` 1 h on the
  first run)? Are all events `duplicate`? Then they were already published, so look further back.
- **Nothing on the Instruments page**: the `[[collect]]` entry is missing (check
  `/api/project`), the command fails (its log under `logs/instruments/`), or it prints a series
  named `orchestra_*` (refused).
- **Wrong subject, no hand-offs**: the subject must be the item, the same in every event about it
  (the Jira key, `pagerduty:<incident id>`, the Slack thread). It must never be a channel alone, a
  timestamp or the poller's name.
- **A node named after your poller**: it published or announced under its own name. Use the
  actor's source (rule 7).
- **The endpoint answers 400**: an unknown field (`kind` is the kit's, never sent), a `time`
  without a zone, or a `source` with characters other than letters, digits, `. _ : @ -`.
