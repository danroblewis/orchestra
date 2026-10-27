# Writing an Orchestra plugin

A **plugin** is a Python package, installed beside Orchestra, that adds things to an Orchestra
project: the programs `orchestra run` keeps running, the machines the Machines page lists before
they are first seen, and pages, API routes, Dashboard panels and machine cards in the web UI. The
task system (`~/orchestra-tasking`), the AI agents (`~/orchestra-agents`) and the bridges
(`~/orchestra-bridges`) are plugins.

This guide is for an engineer building one. It covers the interface exactly as the code on `main`
defines it (`orchestra/plugins.py`, `orchestra/launcher.py`, `orchestra/host.py`,
`orchestra/web/app.py`, `orchestra/web/static/app.js`), the rules a plugin lives under, how the
three existing plugins use the interface, and a walkthrough that builds a small plugin from
nothing and runs it end to end. The walkthrough's code was run as shown.

Read alongside it:

- [`SPEC.md`](SPEC.md) §2 (machines and events), §5.1 (the launcher) and §10.1 (plugins): the design.
- [`AGENTS.md`](AGENTS.md): the rules. Rules 1, 2, 3, 5 and 9 bind plugins directly.
- [`docs/machines.md`](docs/machines.md): writing a machine's measurements and events, with or without a plugin.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): how the core fits together.
- [`USING_ORCHESTRA.md`](USING_ORCHESTRA.md): running Orchestra on a project.

Contents:

1. [What a plugin is](#1-what-a-plugin-is)
2. [How Orchestra finds and loads plugins](#2-how-orchestra-finds-and-loads-plugins)
3. [What a plugin plugs into](#3-what-a-plugin-plugs-into)
4. [The interface, field by field](#4-the-interface-field-by-field)
5. [The browser side: scripts, cards, panels, pages](#5-the-browser-side-scripts-cards-panels-pages)
6. [Machines, events and metrics from a plugin](#6-machines-events-and-metrics-from-a-plugin)
7. [What a plugin may and may not do](#7-what-a-plugin-may-and-may-not-do)
8. [The existing plugins as worked examples](#8-the-existing-plugins-as-worked-examples)
9. [Walkthrough: a plugin from scratch](#9-walkthrough-a-plugin-from-scratch)
10. [Testing a plugin](#10-testing-a-plugin)
11. [Versioning and compatibility](#11-versioning-and-compatibility)
12. [Pitfalls the existing plugins hit](#12-pitfalls-the-existing-plugins-hit)
13. [What the interface does not do yet](#13-what-the-interface-does-not-do-yet)

---

## 1. What a plugin is

Orchestra is empty on purpose (AGENTS.md rule 1). It has an event bus, a metrics store, a system
dynamics model, a bootstrap host with a launcher, and a web UI. It has no tickets, tasks, builds or
agents, and it runs no AI. Everything with a domain lives outside it. A plugin is how a package of
machines gets the parts of Orchestra that a bare program cannot get by itself:

| A bare machine can... | A plugin can also... |
|---|---|
| publish and read events over HTTP (the events endpoint, `USING_ORCHESTRA.md` §5.2), or through `orchestra.events.Events` | have `orchestra run` start, restart and stop its processes (`processes`) |
| write series through `orchestra.metrics` | list its machines on the Machines page before they first run (`machines`) |
| be kept running by a project's `[[machines]]` entry | add pages and API routes to the web UI (`pages`, `router`) |
| be collected or scraped (`[[collect]]`, `[[scrape]]`) | draw its machines' cards and add Dashboard panels (`scripts`, `stylesheets`) |

A plugin adds nothing to the core. Orchestra never imports a plugin's modules by name, never reads
its events' `data`, and never learns what its pages mean. The core treats a plugin as a few lists:
paths to mount, commands to run and ids to show.

---

## 2. How Orchestra finds and loads plugins

A plugin is a **Python entry point** in the group `orchestra.plugins`. The entry point names a
function that takes the project (`orchestra.config.Project`) and returns an
`orchestra.plugins.Plugin`:

```toml
# the plugin's pyproject.toml
[project.entry-points."orchestra.plugins"]
heartbeat = "heartbeat.plugin:plugin"
```

That is all the registration there is.

- **Not listed in `orchestra.toml`.** Every plugin installed in the environment that runs
  `orchestra` is loaded for every project. A plugin decides for itself whether it does anything in
  a given project, usually by checking for its own section of `orchestra.toml` (§4.6).
- **Read from installed metadata.** `importlib.metadata.entry_points(group="orchestra.plugins")`
  reads the entry points from the installed package's `entry_points.txt`, so the plugin must be
  installed in the same environment as Orchestra. An editable install picks up code changes
  without reinstalling, but a change to the entry point itself needs `uv sync` (or
  `pip install -e`) again.
- **Same environment.** If Orchestra is installed as a tool, the plugin goes into that tool's
  environment, for example `uv tool install /path/to/orchestra --with /path/to/plugin`. The
  plugins on this machine each have their own `.venv` with Orchestra installed editable from
  `../orchestra_2` (`[tool.uv.sources]`), and run `orchestra` from there.

`orchestra.plugins.load(project)` calls each entry point's function and keeps what it returns. It
is called from two places, at different times:

| Caller | When | What it uses |
|---|---|---|
| `orchestra web` (`web/app.py`, `mount_plugins`) | **once**, when the web server starts | `pages`, `static`, `router`, `scripts`, `stylesheets`, `machines` |
| `orchestra run` (`host.py`, `Host._plugin_processes`) | when the host starts, and **again every time `orchestra.toml` changes** (after re-reading the config) | `processes` |

```mermaid
flowchart TD
    subgraph ENV["One Python environment"]
        ORC["orchestra<br/>(CLI, host, web)"]
        PKG["your package<br/>[project.entry-points.#quot;orchestra.plugins#quot;]<br/>heartbeat = #quot;heartbeat.plugin:plugin#quot;"]
        META[("installed metadata<br/>entry_points.txt")]
        PKG -- "uv sync / pip install" --> META
    end
    WEB["orchestra web<br/>create_app → mount_plugins"] -- "once, at start" --> LOAD
    HOST["orchestra run<br/>Host._plugin_processes"] -- "at start, and whenever<br/>orchestra.toml changes" --> LOAD
    LOAD["orchestra.plugins.load(project)<br/>entry_points(group=#quot;orchestra.plugins#quot;)"] -- reads --> META
    LOAD -- "ep.load()(project)" --> FN["your plugin(project)"]
    FN -- "returns a Plugin" --> OK["Loaded.plugins"]
    FN -- "raises, or returns<br/>something else" --> ERR["Loaded.errors"]
    OK --> MOUNT["web: mount pages, static,<br/>router, scripts, stylesheets;<br/>merge declared machines"]
    OK --> LAUNCH["host: launcher runs<br/>processes as #lt;plugin#gt;.#lt;name#gt;"]
    ERR --> REP["web: listed in /api/plugins errors<br/>host: logged; what it last declared stands"]
```

**A broken plugin is never fatal** (rule 8: the core stays up). If the function raises, or returns
something that is not a `Plugin`, `load` logs a warning and records
`{"plugin": <entry point name>, "error": ..., "trace": ...}`. The web app lists it under `errors` in
`/api/plugins` and leaves the plugin out. The host logs `plugin X failed to load: ...; what it last
declared, if anything, stands` and keeps running that plugin's processes as it last knew them.

Because the host calls your function on every `orchestra.toml` change, and builds your router each
time only to throw it away, **`plugin(project)` must be cheap and have no side effects**. Open the
bus or the store inside request handlers, not while building the `Plugin`.

---

## 3. What a plugin plugs into

```mermaid
flowchart LR
    subgraph PLUGIN["Plugin (returned by plugin(project))"]
        direction TB
        P_PAGES["pages: Page(path, title, file)"]
        P_STATIC["static: directory"]
        P_ROUTER["router: APIRouter"]
        P_SCRIPTS["scripts, stylesheets"]
        P_MACH["machines: Declared(...)"]
        P_PROC["processes: Process(...)"]
    end
    subgraph WEBAPP["orchestra web"]
        W_PAGE["GET /path (nav link: title)"]
        W_STATIC["/plugins/#lt;name#gt;/static/*"]
        W_API["/api/plugins/#lt;name#gt;/*"]
        W_EVERY["every page: #lt;link#gt; in head,<br/>#lt;script#gt; after app.js"]
        W_MACH["/api/machines<br/>(fills in unseen machines)"]
    end
    subgraph HOSTBOX["orchestra run (bootstrap host)"]
        LAUNCHER["launcher: keeps #lt;name#gt;.#lt;proc#gt; running,<br/>log: state/logs/machines/#lt;name#gt;.#lt;proc#gt;.log"]
    end
    PROCS["your processes<br/>(machines)"]
    BUS[("event bus<br/>orchestra.events.Events")]
    METRICS[("metrics store<br/>orchestra.metrics")]
    STATE[("your state<br/>~/.orchestrator/#lt;key#gt;/#lt;yours#gt;/")]

    P_PAGES --> W_PAGE
    P_STATIC --> W_STATIC
    P_ROUTER --> W_API
    P_SCRIPTS --> W_EVERY
    P_MACH --> W_MACH
    P_PROC --> LAUNCHER
    LAUNCHER -- "starts, restarts, stops" --> PROCS
    LAUNCHER -- "orchestra.process.*" --> BUS
    PROCS -- "announce, publish, listen" --> BUS
    PROCS -- "write series" --> METRICS
    PROCS --- STATE
    W_API -. "reads" .-> BUS
    W_API -. "reads" .-> METRICS
    W_MACH -. "observed from" .-> BUS
    W_MACH -. "observed from" .-> METRICS
```

The solid arrows are what the plugin declares and what its processes do. The dotted arrows are
reads. What the Machines page shows about a machine comes from the bus and the metrics store; a
declaration only fills in what has not been observed yet (rule 2).

---

## 4. The interface, field by field

Everything is in `orchestra/plugins.py` and `orchestra/launcher.py`:

```python
@dataclass
class Page:
    path: str            # where it is served, e.g. "/pages"
    title: str           # its link in the navigation
    file: Path           # the HTML

@dataclass
class Declared:
    id: str                                   # the machine, as its events' source names it
    kind: str = "program"                     # what the package says it is: program, person, service, ...
    mode: str | None = None                   # continuous | scheduled | ad hoc
    listens_for: list[str] = field(default_factory=list)

@dataclass
class Plugin:
    name: str
    pages: list[Page] = field(default_factory=list)
    static: Path | None = None
    router: Any = None   # a fastapi.APIRouter, mounted at /api/plugins/<name>
    scripts: list[str] = field(default_factory=list)   # files in ``static`` loaded on every page
    stylesheets: list[str] = field(default_factory=list)   # files in ``static`` every page links
    machines: list[Declared] = field(default_factory=list)
    processes: list[Process] = field(default_factory=list)   # what `orchestra run` starts for it

# orchestra/launcher.py
@dataclass
class Process:
    name: str
    command: str | list[str]
    restart: str = "always"
    owner: str = "project"         # "project", or the plugin that declared it
    stop_grace_s: float | None = None   # from SIGTERM to SIGKILL when stopping it; None: STOP_GRACE_S
```

That is the whole interface. There is no hook for CLI commands, config schemas, lifecycle
callbacks or scrapes (§13).

### 4.1 `name`

The plugin's name. It is used:

- in its URLs: `/plugins/<name>/static/...` and `/api/plugins/<name>/...`;
- as the prefix of its processes: a `Process("scheduler", ...)` from plugin `tasks` runs as
  `tasks.scheduler`, with its log at `<state>/logs/machines/tasks.scheduler.log`, and is recorded
  with `owner: "tasks"` in the runtime record, on the Core page and in `orchestra.process.started`;
- as the `package` of the machines it declares (§4.5).

Keep it to letters, digits, `.`, `_` and `-`. The launcher checks `<name>.<process>` against that
pattern and refuses (logs once, does not start) anything else. Use the same string as your entry
point's name: `load` reports errors under the entry point's name, everything else uses `Plugin.name`.

### 4.2 `pages`

Each `Page(path, title, file)` is served with `GET path` and linked in the navigation as `title`,
after Orchestra's own links. `app.js` adds the links on every page from `/api/plugins`.

- A page whose `path` Orchestra already serves (`/`, `/machines`, `/dynamics`, `/core`, any
  `/api/...`), or that an earlier plugin took, is left out and reported in `/api/plugins` errors.
- The file is read **on every request**, so editing the HTML takes effect at once. `{{v}}` in it is
  replaced with the mtime of Orchestra's newest static file (for `?v={{v}}` cache-busting), and the
  plugins' stylesheets are linked just before `</head>` unless the page already links them.
- The page is plain HTML. Most pages copy Orchestra's frame: `<link rel="stylesheet"
  href="/static/style.css?v={{v}}">`, the `<nav id="nav">` with `#proj` and `#conn`, the
  `#overlay`/`#drawer` pair, and `<script src="/static/app.js?v={{v}}">`. `app.js` fills in the
  navigation and loads the plugins' every-page scripts (§5).
- Pages are mounted whether or not the project uses the plugin. The Tickets and Agents pages appear
  in any project where those packages are installed.

### 4.3 `static`

A directory, mounted at `/plugins/<name>/static`. It is needed for `scripts` and `stylesheets`,
which name files in it. Without `static`, those two lists are ignored.

### 4.4 `router`

A FastAPI `APIRouter`, included at `/api/plugins/<name>`. The routes are the plugin's own;
Orchestra knows nothing of what they mean. Any method works: the task system's
`POST /api/plugins/tasks/control` and the agents' `POST /api/plugins/agents/supervisor` are the
human-facing writes that rule 9 allows plugins to have (§7).

The router is built in the web server's process. To see edits to `orchestra.toml` live, re-read it
in the handler (`project.reload_config()`; the task system does it in a router dependency,
`Depends(fresh)`).

### 4.5 `machines`: declared machines

`Declared(id, kind, mode, listens_for)` lists a machine the package provides, so the Machines page
shows it before it is first seen. The web app merges the declarations into every `/api/machines`
response (`mount_plugins.declare`):

- **What is observed always wins.** For a machine already seen on the bus or in the metrics, a
  declaration only fills in `package` (the plugin's name) and `kind`, and only where no
  announcement gave them.
- A machine not seen yet is added with `"unseen": true`, `package` = the plugin's name, and the
  declared `kind`, `mode` and `listens_for` (as `subscribes`). Cards draw it greyed or dashed
  ("declared, not run yet").
- Only `orchestra web` reads `machines`, and only once at start (§2). A machine declared because a
  section exists in `orchestra.toml` appears only after `orchestra web` restarts.

This is AGENTS.md rule 2's exception: "the machines a plugin declares, which only fill in machines
not seen yet and never override what is observed."

### 4.6 `processes`

What `orchestra run` keeps running for the plugin, the same `Process` as a project's
`[[machines]]` entry (SPEC §5.1):

| Field | Meaning |
|---|---|
| `name` | Letters, digits, `.`, `_`, `-`. Runs as `<plugin>.<name>`. |
| `command` | A list of arguments (preferred), or a string split like a shell would split it (`shlex`) but **not** run by a shell. |
| `restart` | `always` (the default), `on-failure` or `never`. |
| `stop_grace_s` | Seconds from SIGTERM to SIGKILL; `None` means 10. Make it longer than your own shutdown. |
| `owner` | Do not set it. The host sets it to the plugin's name. |

How the launcher runs it (`orchestra/launcher.py`):

- in the repository root, with the host's environment plus `ORCHESTRA_REPO` (the root),
  `ORCHESTRA_MACHINE_LOG` (its log file) and `PYTHONUNBUFFERED=1`;
- in its own process group, with stdout and stderr appended to
  `<state>/logs/machines/<plugin>.<name>.log` (rotated at 5 MB);
- restarted after it exits (per `restart`), after a pause that doubles with each quick exit, up to
  a minute. After 5 failing exits in a row, each within 60 s of starting, it is given up on
  (`orchestra.process.gave_up`), until its declaration changes or `orchestra run` restarts;
- stopped with SIGTERM to its group, then SIGKILL after its grace, when the host stops, or when the
  plugin no longer declares it, or declares it differently (a different argv or restart);
- published by the host as `orchestra.process.started` / `exited` / `gave_up` (source
  `orchestra-host`, `data.owner` = your plugin's name), and listed on the Core page.

Only one host launches per project (`launcher` in the runtime record). A second `orchestra run`
for the same project starts nothing.

Start Python processes with `sys.executable` (`[sys.executable, "-m", "yourpkg", ...]`). That is
the interpreter running `orchestra run`, which is the environment your plugin is installed in. A
bare `python` is whatever comes first on `PATH`.

The usual pattern is to declare processes only when the project configures the plugin:

```python
configured = section(project.config.raw, "github") is not None
processes=[Process("github", [sys.executable, "-m", "orchestra_bridges", "github"], stop_grace_s=10)] if configured else []
```

Since the host asks again whenever `orchestra.toml` changes, adding the section starts the
process within seconds and removing it stops the process. The walkthrough shows this working
(§9.6).

### 4.7 `scripts` and `stylesheets`

- `scripts`: file names in `static`. They are listed in `/api/plugins` as
  `/plugins/<name>/static/<file>`, and `app.js` appends each one as a `<script>` to the body of
  every page that loads `app.js`: Orchestra's pages and every plugin's. They run after
  Orchestra's own scripts. A page that already has the script keeps its copy.
- `stylesheets`: file names in `static`, linked in the `<head>` of every page Orchestra renders
  (its own and every plugin's), after `style.css`.
- A listed file that does not exist is dropped silently. It is **not** reported as an error.

### 4.8 Configuration: your section of `orchestra.toml`

Orchestra has no config registry. It parses the whole of `orchestra.toml` and keeps it as
`project.config.raw` (a `dict`). It reads its own sections (`[events]`, `[metrics]`,
`[discovery]`, `[[machines]]`, `[[collect]]`, `[[scrape]]`, `[[sources]]`) and ignores the rest.
A plugin reads its own sections from `raw` and validates them itself. Raise
`orchestra.config.ConfigError` for a bad value, and use `orchestra.config.parse_duration` for
`"60s"`-style values. The host re-reads the config (`project.reload_config()`) before it asks the
plugins for processes.

Name your section after your plugin (`[bridges.github]`, `[agents]`, `[heartbeat]`). Nothing stops
two packages from claiming the same section (§13).

### 4.9 CLI commands

Orchestra's CLI has no extension point. Plugins ship their own console scripts in
`[project.scripts]` (`tasking`, `orchestra-agents`) or a `__main__` (`python -m
orchestra_bridges github --once`). Their processes are usually that same entry point
(`python -m tasking run --wait`).

---

## 5. The browser side: scripts, cards, panels, pages

`orchestra/web/static/app.js` defines what an every-page script can use. It loads before any
plugin script.

**Machine cards: `Orchestra.machineCards`.** A machine belongs to a package when its announcement
says `package` or a plugin declares it (`m.package`). The package's script registers once, under
its package name:

```js
Orchestra.machineCards.register("<package>", {
  card(m, { compact }) { /* HTML for inside the card, or null for Orchestra's own */ },
  open(m)    { /* true if it opened the machine's dialog itself; else Orchestra opens its own */ },
  summary(m) { /* a few words for the Dashboard's machine list, or null */ },
  rank(m)    { /* sort position; Orchestra's own are 0, default 50 */ },
});
```

- Orchestra draws the frame and, under your HTML, its own rows of what it observed: engaged
  (mode), kind, package, group, instances, seen, publishes, listens for, counted traffic and
  metrics (`Orchestra.machineCards.rows(m)`). You draw what is inside; you cannot remove those rows.
- Every hook is wrapped in `try`/`catch`: a throw falls back to Orchestra's card.
- Call `Orchestra.machineCards.changed()` when your data arrives, so the pages draw the cards
  again (it dispatches `orchestra:machinecards`). `openDefault(id)` opens Orchestra's own dialog;
  the agents and tasks cards use it for their "machine details" link.
- `m` is the machine as `/api/machines` gives it: `id`, `kind`, `kinds`, `mode`, `package`,
  `name`, `group`, `about` (the announcement's other fields: strings, numbers, booleans, lists),
  `instances` (each with `id`, `kind`, `mode`, `active`, `last_seen`, ...), `publishes`,
  `subscribes`, `metrics`, `active`, `unseen`, `first_seen`, `last_seen`.

**Dashboard panels: `Orchestra.panels`.**

```js
Orchestra.panels.register({ id: "tasks", title: "Tasks", size: { w: 12, h: 9 }, mount(body, ui) {
  // draw into body once and keep it current yourself; ui.setSub(text) sets the line beside the title
} });
```

`size` is in grid columns of 12 and rows of 40 px. Where a panel sits, its size and whether it
is shown belong to the viewer and are kept in the browser.

**Helpers** in `app.js` that plugin scripts use: `$` (getElementById), `esc` (HTML-escape),
`ago(seconds)`, `color(state)`, `openDrawer(html)` / `closeDrawer()`. `openMachine(id)` exists only
on pages that load `machine-dialog.js`.

**Rules of thumb the existing plugins follow:**

- Guard the top: `if (!window.Orchestra || !Orchestra.machineCards) return;`.
- Every-page scripts run on other plugins' pages too, and load asynchronously, after
  `/api/plugins` answers. With several files, ship one loader script that loads the rest once.
  The task system's `tasks-boot.js` loads `tasks.js` and then `attention.js`, `machine-cards.js`
  and `tasks-panel.js`, skipping any the page already has.
- Stylesheets apply to every page: prefix your selectors (`.tkc-`, `.hb-`) so you never restyle
  Orchestra or another plugin.
- Read your own API (`/api/plugins/<name>/...`) on an interval. The agents' cards poll
  `/api/plugins/agents/agents` every 3 s and call `changed()` only when something they draw changed.

---

## 6. Machines, events and metrics from a plugin

A plugin's processes are machines like any other: Orchestra knows them only by what they publish
and write (rule 2). `docs/machines.md` covers measurements in full. This section covers what a
plugin's machines in particular need.

### 6.1 Identity: sources and instances

A machine is its CloudEvents `source`. Several instances of one machine publish as
`<machine>/<instance>` (`worker/1`, `worker/2`; Orchestra splits at the first `/`), and label their
series `machine=<machine>, instance=<instance>`. Open your bus handle with your source:

```python
events = Events.for_project(project, source="heartbeat")
```

`Events.for_project(project)` without `source=` publishes as **`orchestra-host`**, Orchestra's own
machine.

### 6.2 Announcing: `orchestra.machine.started`

When an instance starts, it announces itself. This is Orchestra's own event type, so Orchestra
reads its `data` (`web/machines.py`):

| `data` field | Meaning | Kept per |
|---|---|---|
| `mode` | `continuous`, `scheduled` or `ad hoc` | instance |
| `kind` | `program`, `agent`, `person`, `service` | instance |
| `listens_for` | event types it reads (older: `orchestra.machine.subscribed` with `types`) | machine (union) |
| `package` | your plugin's name, so your card draws it | machine (latest that says one) |
| `log` | its log file; shown only if inside the repository or the state directory | instance |
| `name`, `group` (or `team`) | a display name and a group label | machine (latest announcement) |
| anything else | passed unread to your card as `m.about` (scalars and lists only) | machine (latest announcement) |

Announcements are not counted as beats when Orchestra judges whether a machine is active. A
machine stays active while its events or its writes keep coming at their usual cadence.

### 6.3 Publishing and listening

```python
events.publish("heartbeat.pong", {"after_beats": 6}, subject="by-hand", causationid=ping["id"])
evs, offset = events.after(offset)        # every event after offset, in order; then read on from the new offset
```

- Name your event types with your own prefix (`task.*`, `ticket.*`, `github.issue.*`). The
  `orchestra.` prefix is Orchestra's.
- `subject` is what the event is about. The Machines page infers hand-offs from it: one machine
  acts on a subject, then another does.
- Follow the bus by offset with `Events.after`. Start from `events.end()` to hear only what comes
  after you started, or from `0` to rebuild your state from your own past events (the bridges keep
  no state of their own and rebuild it this way).
- An event brought in from another system keeps its own time and a stable id:
  `publish(..., time=..., id=...)`.
- A plugin's process that is not written in Python, or would rather not import Orchestra, uses
  the events endpoint instead: the launcher gives it `ORCHESTRA_EVENTS_ENDPOINT` and
  `ORCHESTRA_EVENTS_TOKEN`, as it does every process (`USING_ORCHESTRA.md` §5.2).

### 6.4 Metrics

Write through Orchestra's store, labelled with your machine:

```python
from orchestra.metrics import Point, ProjectStore, for_project
store = ProjectStore(for_project(project), project.key)        # or orchestra.metrics.for_repo()
store.write([Point("heartbeat_beats_total", 42, time.time(), {"machine": "heartbeat"})])
```

- Name each series for what it measures, with its unit. A counter ends in `_total`. Never start a
  name with `orchestra_`. Whether a series is a stock or a flow is for discovery to decide (rules
  6 and 7), not you.
- Write on a schedule, even when nothing changed. Points stamped more than 60 s in the future are
  refused.
- Or serve `/metrics` and have the project scrape it (`[[scrape]]`). A plugin cannot declare the
  scrape itself (§12.4, §13).

### 6.5 The whole path, in order

```mermaid
sequenceDiagram
    autonumber
    participant Host as orchestra run (host + launcher)
    participant Proc as plugin process (heartbeat.beat)
    participant Bus as event bus
    participant Store as metrics store
    participant Web as orchestra web (background index)
    participant UI as browser (app.js + plugin script)

    Host->>Host: plugins.load(project) → Plugin.processes
    Host->>Proc: start [sys.executable, -m, heartbeat.machine]<br/>env ORCHESTRA_REPO, ORCHESTRA_MACHINE_LOG
    Host->>Bus: orchestra.process.started {name: heartbeat.beat, owner: heartbeat}
    Proc->>Bus: orchestra.machine.started (source heartbeat)<br/>{package, mode, kind, listens_for, log}
    loop every [heartbeat] every
        Proc->>Bus: heartbeat.beat {n}
        Proc->>Store: heartbeat_beats_total{machine="heartbeat"}
    end
    Web->>Bus: read new events (incrementally)
    Web->>Store: read series labelled machine=...
    UI->>Web: GET /api/plugins
    Web-->>UI: pages, scripts
    UI->>Web: GET /plugins/heartbeat/static/heartbeat.js
    UI->>UI: Orchestra.machineCards.register("heartbeat", ...)
    UI->>Web: GET /api/machines
    Web-->>UI: heartbeat: package, kind, mode, subscribes, metrics, active<br/>(declared fields fill only what was not observed)
    UI->>Web: GET /api/plugins/heartbeat/state
    Web-->>UI: the plugin's own view
    UI->>UI: draw the card inside Orchestra's frame, with Orchestra's rows under it
```

---

## 7. What a plugin may and may not do

These follow from AGENTS.md. The plugins' own `AGENTS.md` files repeat them.

**A plugin may:**

- define any domain: tickets, agents, people, pings. These live in the plugin, never in Orchestra (rule 1);
- run processes through `orchestra run`, publish and listen on the bus, and write series;
- add pages, routes, panels and machine cards, and give humans a way to change the system. **Rule
  9: humans change the system only through plugins.** Orchestra's own UI and CLI are read-only
  except for rediscovering the model. The paths that exist are the agents' Supervisor chat (which
  edits `orchestra.toml` through its tools, after which the host restarts processes accordingly)
  and the task system's operator controls (pause pickup, capacity, stop a ticket's holder;
  `docs/roadmap/decisions.md` D1);
- read the `data` of `orchestra.machine.started` (an Orchestra event type) and of event types that
  another package publishes as a protocol for others to speak. The agents speak the task system's
  assignment and request protocol, documented in its SPEC.

**A plugin must not:**

- **add a domain concept to Orchestra.** If a feature needs Orchestra to know what a ticket or an
  agent is, the design is wrong. Do it in the plugin, or propose a domain-free mechanism for the
  core;
- **read `data` it does not own** (rule 3), and must not ask Orchestra to. Orchestra reads only the
  envelope and its own `orchestra.*` events;
- **turn counted traffic into events** (rule 3);
- **touch a backend or Orchestra's files directly** (rule 5). Events go through
  `orchestra.events.Events` or the events endpoint, metrics through `orchestra.metrics`, config through
  `orchestra.config`. Never open the JSONL files, Redis or VictoriaMetrics yourself, and never
  write Orchestra's `runtime.json`, `events.jsonl` or `metrics.jsonl`. Other stores
  (`[[sources]]`) are read only, through `orchestra.sources`;
- **keep state anywhere but its own place**: `~/.orchestrator/<key>/<plugin>/`
  (`project.state_dir / "tasks"`, `.../"agents"`), or the bus and the store themselves (the bridges
  keep nothing else). Records that belong in the repository go in a directory of your own (the
  agents use `.orchestra/`);
- **split the system** (rule 4): no topic, model or view per package. A plugin's events go on the
  project's one bus;
- import Orchestra's web app, host or model from runtime code. The bridges state it as their rule
  5: "Nothing here imports Orchestra's web app, model or host." Tests may use
  `orchestra.web.app.create_app`;
- describe its machines to Orchestra in place of being observed. A declaration fills in an unseen
  machine and nothing more (rule 2).

---

## 8. The existing plugins as worked examples

### 8.1 The task system: `orchestra-tasking`, plugin `tasks`

```toml
[project.entry-points."orchestra.plugins"]
tasks = "tasking.web:plugin"
```

```python
# tasking/web.py
def plugin(orchestra_project) -> Plugin:
    """The plugin for the repository Orchestra serves (its entry point, in pyproject.toml)."""
    project = Project.from_orchestra(orchestra_project)
    return Plugin("tasks", [Page("/tickets", "Tickets", STATIC / "tickets.html")],
                  STATIC, router(project), scripts=["tasks-boot.js"], stylesheets=["tasks.css"], machines=declared(),
                  processes=processes(project))


def processes(project: Project) -> list[Process]:
    if not ({"project", "tasks"} & set(project.config.raw)):
        return []
    return [Process("scheduler", [sys.executable, "-m", "tasking", "run", "--wait"])]


def declared() -> list[Declared]:
    return [Declared(SCHEDULER, "program", "continuous")]
```

| Field | What it registers |
|---|---|
| `pages` | `/tickets` ("Tickets"): the ticket graph |
| `static`, `scripts` | one loader, `tasks-boot.js`, which loads `tasks.js`, then `attention.js` (the blocked-ticket banner), `machine-cards.js` (the scheduler's card, `register("tasks", ...)`) and `tasks-panel.js` (the Tasks panel, `Orchestra.panels.register({id: "tasks", ...})`) |
| `stylesheets` | `tasks.css` |
| `router` | `/api/plugins/tasks/state`, `/board`, `/attention`, `/tickets/{id}`, and `POST /control` (operator controls, published as the machine `task_web`). A router dependency re-reads `orchestra.toml` on every request, so the capacity ceiling is live |
| `machines` | `task_scheduler` (program, continuous). `task_web` is not declared; it appears once used |
| `processes` | `tasks.scheduler`, only when `orchestra.toml` has `[project]` or `[tasks]` |

Its config sections: `[project]`, `[tasks]`, `[gate]`, `[staging]`. State:
`~/.orchestrator/<key>/tasks/`. The scheduler announces itself with
`{"package": "tasks", "mode": "continuous", "kind": "program", "listens_for": [...], "log": ...}`.

### 8.2 The AI agents: `orchestra-agents`, plugin `agents`

```toml
[project.entry-points."orchestra.plugins"]
agents = "orchestra_agents.web:plugin"
```

```python
# orchestra_agents/web.py
def plugin(orchestra_project) -> Plugin:
    """The plugin for the repository Orchestra serves (its entry point, in pyproject.toml)."""
    project = load_project(orchestra_project.repo_root)
    return Plugin("agents", [Page("/agents", "Agents", STATIC / "agents.html")], STATIC, router(project),
                  scripts=["attention.js", "machine-cards.js"], stylesheets=["agents.css"],
                  machines=declared(project), processes=processes(project))


def processes(project) -> list[Process]:
    raw = tomllib.loads((project.repo_root / "orchestra.toml").read_text(encoding="utf-8"))
    return ([Process("host", [sys.executable, "-m", "orchestra_agents", "run", "--wait"], stop_grace_s=STOP_GRACE_S)]
            if "agents" in raw else [])


def declared(project) -> list[Declared]:
    out = [Declared("agents", "program", "continuous")]
    for a in all_agents(project).values():
        out.append(Declared(a.name, "agent", "continuous" if a.resident else "ad hoc", sorted({w.split(":")[0] for w in a.wake_on})))
    return out
```

| Field | What it registers |
|---|---|
| `pages` | `/agents` ("Agents"): roles, agents, teams, wake-ups |
| `scripts` | `attention.js` (the way to the Supervisor chat on every page) and `machine-cards.js`, which loads `agents.js` on demand (transcripts, chat, session chips) and registers `Orchestra.machineCards.register("agents", ...)`: resident agents as a row, workers and reviewers as the tickets they are on, the host as a line |
| `stylesheets` | `agents.css` |
| `router` | `GET /org`, `/state`, `/agents`, `/agents/{name}`, `/roles/{name}`, `/teams/{name}`, `/attention`, `/sessions/{id}/transcript`; `POST /attention/seen`, and `POST /supervisor`: the one human write, the Supervisor chat (rule 9) |
| `machines` | the host `agents` (program, continuous), and each configured agent (kind `agent`; continuous when resident, ad hoc otherwise; its wake-up event types as `listens_for`) |
| `processes` | `agents.host`, only when `orchestra.toml` has `[agents]`; `stop_grace_s=30`, longer than the host's worst-case shutdown (20 s), so Orchestra never kills it halfway and orphans its sessions |

The host announces itself (`package: "agents"`, `kind: "program"`, `listens_for:
["ticket.transitioned"]`), and announces each agent instance it starts as `worker/1`,
`reviewer/1`, ... with `kind: "agent"` and extra fields (`role`, `harness`, `model`) that reach
the card as `m.about`. State: `~/.orchestrator/<key>/agents/`; the organisation's records are in
the repository under `.orchestra/`.

### 8.3 The bridges: `orchestra-bridges`, plugin `bridges`

```toml
[project.entry-points."orchestra.plugins"]
bridges = "orchestra_bridges.plugin:plugin"
```

```python
# orchestra_bridges/plugin.py (main)
def plugin(project) -> Plugin:
    configured = section(project.config.raw, "github") is not None
    return Plugin(
        "bridges",
        machines=[Declared(MACHINE, "program", "continuous")] if configured else [],
        processes=[Process("github", [sys.executable, "-m", "orchestra_bridges", "github"], stop_grace_s=10)]
        if configured else [])
```

This is the smallest real plugin. It has **no pages, router or scripts**: what the bridges show is
Orchestra's own Machines page and series. It declares one process and one machine
(`bridges.github`) when `[bridges.github]` exists. The bridge publishes each GitHub actor's doings
with the actor as the source (`person.<login>`), announcing each actor first with `kind: "person"`
(or `program` for a bot) and `package: "bridges"`. It writes its own series through
`orchestra.metrics`, and keeps no state of its own: it rebuilds everything from its events and
series at start.

On the unmerged `slack-bridge` branch, the plugin declares one process and one machine per
configured system (`SYSTEMS = ("github", "slack")`). The Slack bridge serves `/metrics` instead of
writing, and needs a `[[scrape]]` named `bridges.slack` that the owner adds to `orchestra.toml`
by hand, because a plugin cannot declare one (§12.4, §13).

---

## 9. Walkthrough: a plugin from scratch

We build `orchestra-heartbeat`, a plugin with one machine, `heartbeat`. It:

- runs as a process `orchestra run` keeps running (`heartbeat.beat`), only in projects with a
  `[heartbeat]` section;
- announces itself, publishes `heartbeat.beat` on an interval, listens for `heartbeat.ping` and
  answers each with `heartbeat.pong`;
- writes `heartbeat_beats_total` and `heartbeat_pongs_total`;
- adds a page (`/heartbeat`), an API route, a Dashboard panel and its machine card.

All of the code below was run against Orchestra `main` (828da6d0): the tests pass, and
`orchestra run` plus `orchestra web` served it as described in §9.6.

### 9.1 Layout

```
orchestra-heartbeat/
  pyproject.toml
  heartbeat/
    __init__.py         the plugin's and the machine's names
    config.py           [heartbeat] in orchestra.toml
    machine.py          the process: python -m heartbeat.machine
    plugin.py           the entry point: plugin(project) -> Plugin, and the router
    static/
      heartbeat.html    the page
      heartbeat.js      every-page script: machine card and Dashboard panel
      heartbeat.css     every-page stylesheet
  tests/
    conftest.py
    test_plugin.py
    test_orchestra_run.py
```

### 9.2 `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "orchestra-heartbeat"
version = "0.1.0"
description = "A minimal Orchestra plugin: one machine that beats, answers pings, and is shown on its own page."
requires-python = ">=3.12"
dependencies = ["orchestra", "fastapi>=0.115"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

# Orchestra finds the plugin here: the entry point names a function that takes the project.
[project.entry-points."orchestra.plugins"]
heartbeat = "heartbeat.plugin:plugin"

[tool.uv.sources]
orchestra = { path = "../orchestra_2", editable = true }

[tool.hatch.build.targets.wheel]
packages = ["heartbeat"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

The trial run used an absolute `path` to the Orchestra checkout, because the plugin lived in a
scratch directory. The three real plugins use `../orchestra_2`, as above. `httpx` is there for
FastAPI's `TestClient`.

### 9.3 The package

`heartbeat/__init__.py`:

```python
"""A minimal Orchestra plugin: the machine ``heartbeat`` and its page."""

PACKAGE = "heartbeat"      # the plugin's name: its URLs, its processes' prefix, its machines' package
MACHINE = "heartbeat"      # the machine's id: the CloudEvents source it publishes as
```

`heartbeat/config.py`: its own section, validated by itself:

```python
"""The plugin's settings: ``[heartbeat]`` in the project's orchestra.toml, a section Orchestra ignores.

::

    [heartbeat]
    every = "5s"      # how often the machine beats
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orchestra.config import ConfigError, parse_duration


@dataclass
class Settings:
    every: float = 5.0


def section(raw: dict[str, Any]) -> dict | None:
    """``[heartbeat]`` of a parsed orchestra.toml, or None when the project does not configure it."""
    s = raw.get("heartbeat")
    return s if isinstance(s, dict) else None


def settings(raw: dict[str, Any]) -> Settings:
    s = section(raw)
    if s is None:
        raise ConfigError("orchestra.toml has no [heartbeat] section")
    every = parse_duration(s.get("every"), 5.0)
    if every < 1:
        raise ConfigError("[heartbeat] every must be at least 1s")
    return Settings(every=every)
```

`heartbeat/machine.py`: the machine. It imports only `orchestra.config`, `orchestra.events` and
`orchestra.metrics`, and keeps its logic in a class a test can drive without a process:

```python
"""The machine ``heartbeat``: ``python -m heartbeat.machine``, which ``orchestra run`` keeps running
as ``heartbeat.beat``. It announces itself, publishes ``heartbeat.beat`` every ``[heartbeat] every``,
answers each ``heartbeat.ping`` with a ``heartbeat.pong`` about the same subject, and writes two
series labelled ``machine="heartbeat"``."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time

from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point, ProjectStore, for_project

from . import MACHINE, PACKAGE
from .config import settings

BEAT, PING, PONG = "heartbeat.beat", "heartbeat.ping", "heartbeat.pong"


class Heart:
    def __init__(self, events: Events, store, every: float, clock=time.time):
        self.events, self.store, self.every, self.clock = events, store, every, clock
        self.beats = self.pongs = 0
        self.offset = events.end()           # listen from now: pings sent before it started are not its

    def announce(self) -> None:
        log = os.environ.get("ORCHESTRA_MACHINE_LOG")    # the launcher sets it; shown in the machine's dialog
        self.events.publish("orchestra.machine.started", {
            "package": PACKAGE, "mode": "continuous", "kind": "program",
            "listens_for": [PING], **({"log": log} if log else {})})

    def beat(self) -> None:
        self.beats += 1
        self.events.publish(BEAT, {"n": self.beats})
        self.measure()

    def answer(self) -> int:
        """Answer the pings published since the last call; returns how many."""
        evs, self.offset = self.events.after(self.offset)
        n = 0
        for ev in evs:
            if ev.get("type") == PING:
                self.events.publish(PONG, {"after_beats": self.beats}, subject=ev.get("subject"), causationid=ev["id"])
                n += 1
        self.pongs += n
        if n:
            self.measure()
        return n

    def measure(self) -> None:
        now = self.clock()
        labels = {"machine": MACHINE}
        self.store.write([Point("heartbeat_beats_total", self.beats, now, labels),
                          Point("heartbeat_pongs_total", self.pongs, now, labels)])

    def run(self, stop: threading.Event) -> None:
        self.announce()
        next_beat = 0.0
        while not stop.is_set():
            if self.clock() >= next_beat:
                self.beat()
                next_beat = self.clock() + self.every
            self.answer()
            stop.wait(0.5)


def main() -> int:
    project = load_project()                  # ORCHESTRA_REPO, which the launcher sets
    heart = Heart(Events.for_project(project, source=MACHINE), ProjectStore(for_project(project), project.key),
                  settings(project.config.raw).every)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    print(f"{MACHINE}: beating every {heart.every:g} s", flush=True)
    heart.run(stop)
    print(f"{MACHINE}: stopped after {heart.beats} beats", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Notes: it opens the bus with `source=MACHINE`; it handles SIGTERM, so the launcher's stop is
clean; its counters start again from zero after a restart, which is a counter reset as in
Prometheus. The pong's data belongs to this machine; Orchestra never reads it.

`heartbeat/plugin.py`: the entry point. It does no work when called; the router opens the bus and
the store per request:

```python
"""The heartbeat as an Orchestra plugin (``orchestra/plugins.py``): its page, its API, its every-page
script and look, the machine it declares, and the process ``orchestra run`` keeps running for it,
only in a project whose orchestra.toml has a ``[heartbeat]`` section.

Orchestra calls ``plugin(project)`` in the web server once, when it starts, and in ``orchestra run``
each time orchestra.toml changes, so it does no work and opens nothing: the router opens the bus
and the store when a request comes."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import APIRouter
from orchestra.events import Events
from orchestra.launcher import Process
from orchestra.metrics import for_project
from orchestra.plugins import Declared, Page, Plugin

from . import MACHINE, PACKAGE
from .config import section
from .machine import BEAT, PING, PONG

STATIC = Path(__file__).parent / "static"


def plugin(project) -> Plugin:
    configured = section(project.config.raw) is not None
    return Plugin(
        PACKAGE,
        pages=[Page("/heartbeat", "Heartbeat", STATIC / "heartbeat.html")],
        static=STATIC,
        router=router(project),
        scripts=["heartbeat.js"],
        stylesheets=["heartbeat.css"],
        machines=[Declared(MACHINE, "program", "continuous", [PING])] if configured else [],
        processes=[Process("beat", [sys.executable, "-m", "heartbeat.machine"], stop_grace_s=5)] if configured else [],
    )


def router(project) -> APIRouter:
    r = APIRouter()

    @r.get("/state")
    def state() -> dict:
        """The machine's last beats and pongs (its own events, so it reads their data), and its
        beat counter as the metrics store has it."""
        events = Events.for_project(project)
        try:
            evs, _ = events.read(0, limit=500)           # the last 500 events on the bus
        finally:
            events.close()
        mine = [e for e in evs if e.get("source") == MACHINE and e.get("type") in (BEAT, PONG)]
        latest = for_project(project).latest("heartbeat_beats_total", {"machine": MACHINE})
        return {"ok": True, "now": time.time(), "configured": section(project.config.raw) is not None,
                "beats_total": latest[1] if latest else None,
                "recent": [{"type": e["type"], "time": e["time"], "subject": e.get("subject"), "data": e.get("data")}
                           for e in mine[-20:]][::-1]}

    return r
```

Pass `Plugin` fields **by keyword**. Positional arguments tie you to the dataclass's field order (§11).

### 9.4 The web side

`heartbeat/static/heartbeat.html`: a page in Orchestra's frame:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heartbeat</title>
<link rel="stylesheet" href="/static/style.css?v={{v}}">
</head>
<body>
<nav id="nav"><a href="/">Dashboard</a><a href="/machines">Machines</a><a href="/dynamics">Dynamics</a><a href="/core">Core</a><span class="muted" id="proj"></span><span class="muted" id="conn" style="margin-left:auto"></span></nav>
<main class="hb-page">
  <h1>Heartbeat</h1>
  <p class="muted">The machine <code>heartbeat</code>: its beat counter as stored, and its last beats and pongs on the bus.</p>
  <div id="hb-body">reading…</div>
</main>
<div id="overlay" class="overlay" onclick="if(event.target===this)closeDrawer()"><div id="drawer" class="drawer"></div></div>
<script src="/static/app.js?v={{v}}"></script>
<script>
async function refresh() {
  try {
    const d = await (await fetch("/api/plugins/heartbeat/state")).json();
    const rows = d.recent.map((e) => `<tr><td>${esc(e.time)}</td><td>${esc(e.type)}</td><td>${esc(e.subject || "")}</td><td>${esc(JSON.stringify(e.data))}</td></tr>`).join("");
    $("hb-body").innerHTML = `<p>beats stored: <b class="hb-n">${d.beats_total ?? "none yet"}</b></p>
      <table class="hb-table"><tr><th>time</th><th>type</th><th>subject</th><th>data</th></tr>${rows}</table>`;
    $("conn").textContent = "live";
  } catch (e) { $("conn").textContent = "disconnected"; }
}
refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>
```

`heartbeat/static/heartbeat.js`: the every-page script, with the machine card and a Dashboard panel:

```js
// The heartbeat on every page of Orchestra's web UI (Plugin.scripts): the machine's card and a
// Dashboard panel. Orchestra loads it after its own app.js, so Orchestra.machineCards and
// Orchestra.panels exist; a page without them (a page of another plugin) gets nothing.
(function () {
  if (!window.Orchestra || !Orchestra.machineCards) return;
  const API = "/api/plugins/heartbeat";
  let D = null;

  async function refresh() {
    try {
      const d = await (await fetch(API + "/state")).json();
      const changed = !D || d.beats_total !== D.beats_total;
      D = d;
      if (changed) Orchestra.machineCards.changed();     // ask the pages to draw the cards again
    } catch (e) {}
  }

  // the inside of the card of every machine whose package is "heartbeat"; Orchestra draws the
  // frame and its own rows (engaged, kind, instances, publishes, metrics) under it
  Orchestra.machineCards.register("heartbeat", {
    card(m) {
      if (m.id !== "heartbeat") return null;              // Orchestra's own card for anything else
      const n = D && D.beats_total != null ? D.beats_total : "–";
      return `<div class="hb-card"><span class="hb-dot ${m.active ? "on" : ""}"></span><b>${esc(m.id)}</b>
        <span class="muted">${m.unseen ? "declared, not run yet" : `${n} beats`}</span></div>`;
    },
    summary(m) { return D && D.beats_total != null ? `${D.beats_total} beats` : null; },
    rank() { return 40; },
  });

  if (Orchestra.panels) {
    Orchestra.panels.register({ id: "heartbeat", title: "Heartbeat", size: { w: 4, h: 4 }, mount(body, ui) {
      const draw = () => {
        body.innerHTML = `<div class="hb-n">${D && D.beats_total != null ? D.beats_total : "–"}</div><div class="muted">beats stored</div>`;
        ui.setSub(D && D.recent.length ? `last ${D.recent[0].type}` : "");
      };
      draw(); setInterval(draw, 3000);
    } });
  }

  refresh(); setInterval(refresh, 3000);
})();
```

`heartbeat/static/heartbeat.css`:

```css
/* The heartbeat's look: linked in the head of every page Orchestra serves (Plugin.stylesheets),
   so every selector is prefixed hb- and nothing here restyles Orchestra's or another plugin's. */
.hb-page { max-width: 900px; margin: 0 auto; padding: 16px }
.hb-n { font-size: 28px; font-weight: 800 }
.hb-table { border-collapse: collapse; font-size: 12px; width: 100% }
.hb-table td, .hb-table th { border-bottom: 1px solid var(--border); padding: 3px 6px; text-align: left }
.hb-card { display: flex; gap: 8px; align-items: center }
.hb-dot { width: 9px; height: 9px; border-radius: 50%; background: #64748b }
.hb-dot.on { background: #ef4444 }
```

### 9.5 Tests

`tests/conftest.py`: a project in a fresh git repository, under a temporary `ORCHESTRATOR_HOME`:

```python
"""A project in a fresh git repository under a temporary ORCHESTRATOR_HOME, with [heartbeat] set."""

import subprocess

import pytest
from orchestra.config import load_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))      # never the real ~/.orchestrator
    monkeypatch.delenv("ORCHESTRA_EVENTS_URL", raising=False)            # the file bus and store, in the temp home
    monkeypatch.delenv("ORCHESTRA_METRICS_URL", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "orchestra.toml").write_text('[events]\nurl = "file"\n\n[metrics]\nurl = "file"\n\n[heartbeat]\nevery = "1s"\n')
    monkeypatch.setenv("ORCHESTRA_REPO", str(repo))
    return load_project(repo)
```

`tests/test_plugin.py`: the declaration as a pure function, Orchestra finding the installed entry
point, the web app serving it, and the machine driven in-process:

```python
"""The plugin's declaration, Orchestra finding it, and the web app serving it."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from orchestra.config import Config, Project
from orchestra.events import Events
from orchestra.plugins import load
from orchestra.web.app import create_app

from heartbeat.machine import Heart
from heartbeat.plugin import plugin


def proj(toml: str) -> Project:
    return Project("k", Path("/repo"), Config.from_toml(toml))


def test_it_runs_only_where_it_is_configured():
    off = plugin(proj('[events]\nurl = "file"\n'))
    assert (off.name, off.processes, off.machines) == ("heartbeat", [], [])
    on = plugin(proj("[heartbeat]\n"))
    [p] = on.processes
    assert (p.name, p.argv(), p.restart) == ("beat", [sys.executable, "-m", "heartbeat.machine"], "always")
    assert [(m.id, m.kind, m.mode, m.listens_for) for m in on.machines] == [("heartbeat", "program", "continuous", ["heartbeat.ping"])]


def test_orchestra_finds_the_installed_plugin():
    loaded = load(proj("[heartbeat]\n"))
    assert "heartbeat" in [p.name for p in loaded.plugins] and not loaded.errors


def test_the_web_app_serves_its_page_script_and_api_and_declares_its_machine(project):
    c = TestClient(create_app(project))
    d = c.get("/api/plugins").json()
    assert {"plugin": "heartbeat", "path": "/heartbeat", "title": "Heartbeat"} in d["pages"] and d["errors"] == []
    assert "/plugins/heartbeat/static/heartbeat.js" in d["scripts"]
    assert '<link rel="stylesheet" href="/plugins/heartbeat/static/heartbeat.css">' in c.get("/").text
    assert "{{v}}" not in c.get("/heartbeat").text
    assert c.get("/api/plugins/heartbeat/state").json()["recent"] == []
    # the Machines page reads the bus in the background: wait for its first read
    for _ in range(100):
        m = c.get("/api/machines").json()
        if m.get("ok"):
            break
    hb = {x["id"]: x for x in m["machines"]}["heartbeat"]
    assert (hb["package"], hb["kind"], hb["unseen"]) == ("heartbeat", "program", True)


def test_the_machine_beats_answers_pings_and_measures(project):
    from orchestra.metrics import ProjectStore, for_project

    store = ProjectStore(for_project(project), project.key)
    heart = Heart(Events.for_project(project, source="heartbeat"), store, every=1.0, clock=lambda: 1_793_000_000.0)
    heart.announce()
    heart.beat()
    Events.for_project(project, source="tester").publish("heartbeat.ping", subject="p1")
    assert heart.answer() == 1
    evs, _ = Events.for_project(project).after(0)
    assert [(e["type"], e["source"], e.get("subject")) for e in evs] == [
        ("orchestra.machine.started", "heartbeat", None), ("heartbeat.beat", "heartbeat", None),
        ("heartbeat.ping", "tester", "p1"), ("heartbeat.pong", "heartbeat", "p1")]
    assert evs[0]["data"]["package"] == "heartbeat" and evs[0]["data"]["listens_for"] == ["heartbeat.ping"]
    assert store.latest("heartbeat_pongs_total", {"machine": "heartbeat"})[1] == 1
```

`tests/test_orchestra_run.py`: end to end through a real `orchestra run`:

```python
"""End to end: `orchestra run` starts the process the plugin declares, the machine beats and answers
a ping on the bus and writes its series, and stopping `orchestra run` stops it."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from orchestra.events import Events
from orchestra.metrics import for_project


def wait_for(check, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if v := check():
            return v
        time.sleep(0.3)
    raise AssertionError("timed out")


def test_orchestra_run_keeps_the_heartbeat_running(project):
    orchestra = Path(sys.executable).with_name("orchestra")      # the one installed beside the plugin
    host = subprocess.Popen([str(orchestra), "run"], cwd=project.repo_root, env=os.environ.copy(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
    bus = Events.for_project(project, source="tester")
    try:
        on_bus = lambda: Events.for_project(project).after(0)[0]   # noqa: E731
        wait_for(lambda: any(e["type"] == "heartbeat.beat" for e in on_bus()))
        bus.publish("heartbeat.ping", subject="e2e")
        wait_for(lambda: any(e["type"] == "heartbeat.pong" and e.get("subject") == "e2e" for e in on_bus()))
        assert wait_for(lambda: for_project(project).latest("heartbeat_beats_total", {"machine": "heartbeat"}))
        started = [e for e in on_bus() if e["type"] == "orchestra.process.started"]
        assert [(e["data"]["name"], e["data"]["owner"]) for e in started] == [("heartbeat.beat", "heartbeat")]
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=30)
    log = (project.logs_dir / "machines" / "heartbeat.beat.log").read_text()
    assert "heartbeat: stopped after" in log
```

The last test reads `orchestra.process.started`'s `data`. That is safe because it is an Orchestra
event type, and it is a test.

### 9.6 Install, run and see it

```bash
cd orchestra-heartbeat
uv sync --extra dev
uv run python -c "from importlib.metadata import entry_points; print([(e.name, e.value) for e in entry_points(group='orchestra.plugins')])"
# [('heartbeat', 'heartbeat.plugin:plugin')]
uv run python -m pytest -q
# 5 passed
```

Then on a project of its own. Any git repository with an `orchestra.toml` works. Use a plain
directory or a clone, never a git worktree: Orchestra resolves a worktree to its main repository
(§12.5).

```bash
export ORCHESTRATOR_HOME=$PWD/home            # keep this trial's state out of ~/.orchestrator
mkdir project && cd project && git init -q -b main
cat > orchestra.toml <<'EOF'
[events]
url = "file"

[metrics]
url = "file"

[heartbeat]
every = "2s"
EOF
git add -A && git commit -qm init

../orchestra-heartbeat/.venv/bin/orchestra run &              # the host, from the plugin's environment
../orchestra-heartbeat/.venv/bin/orchestra web --port 8093 &
```

What the run showed:

- the host's log: `launcher: heartbeat.beat: started `.../.venv/bin/python -m heartbeat.machine` (pid ...)`;
- `GET /api/plugins` →
  `{"ok":true,"pages":[{"plugin":"heartbeat","path":"/heartbeat","title":"Heartbeat"}],"scripts":["/plugins/heartbeat/static/heartbeat.js"],"errors":[]}`;
- `GET /api/plugins/heartbeat/state` → `beats_total` counting up, and the recent `heartbeat.beat` events;
- after publishing a `heartbeat.ping` with subject `by-hand` from another source (`tester`), the
  state showed `('heartbeat.pong', 'by-hand')`, and `/api/machines` showed `heartbeat` with
  `package: heartbeat`, `kind: program`, `kinds: {program: 1}`, `mode: continuous`, `subscribes:
  [heartbeat.ping]`, `metrics: [heartbeat_beats_total, heartbeat_pongs_total]`, `active: true`, its
  log, and publishes `heartbeat.beat` and `heartbeat.pong`. The Machines map drew `tester →
  heartbeat`;
- `/api/core` listed the process `heartbeat.beat`: running, `owner: heartbeat`, 0 restarts;
- in a browser: a "Heartbeat" link in the navigation, the page, a "Heartbeat" panel on the
  Dashboard, and "12 beats" beside `heartbeat` in the Dashboard's machine list (the card's `summary`);
- with `[heartbeat]` removed from `orchestra.toml`, the host's log said `launcher: heartbeat.beat:
  stopped (no longer declared as it was)` within seconds. SIGTERM to `orchestra run` then stopped
  the host, and nothing was left running.

---

## 10. Testing a plugin

The existing plugins test at four levels. Each level uses real Orchestra code, not mocks of it.

**The declaration, as a pure function.** `plugin()` takes a `Project`. A project built from a TOML
string needs no files, if your plugin reads only `project.config.raw`, as the bridges and the
heartbeat do:

```python
def proj(toml: str) -> Project:
    return Project("k", Path("/repo"), Config.from_toml(toml))
```

The task system's and the agents' plugins read files from the repository, so their tests make a
real one (`git init` plus `orchestra.toml`, or `orchestra.config.init_project`).

**Orchestra finds the installed plugin.** `orchestra.plugins.load(project)` with no `found=` reads
the real installed entry points (`orchestra-bridges/tests/unit/test_config_plugin.py`). Orchestra's
own tests stand in fake entry points instead: `monkeypatch.setattr(plugins, "entry_points", ...)`,
`plugins.load(project, found=...)`, or `Host(project, found=lambda: [EntryPoint()])`
(`tests/unit/test_plugins.py`, `tests/unit/test_launcher.py`).

**The web app with the plugin mounted.** `TestClient(create_app(load_project(repo)))` serves your
pages, static files and routes, and `/api/machines` with your declarations merged
(`orchestra-tasking/tests/unit/test_plugin.py`). `/api/machines` answers `{"ok": false, "warming":
true}` until its background read finishes, so poll it.

**Real processes, end to end.** Start `orchestra run` (and `orchestra web` on a free port) as
subprocesses from the plugin's environment (`Path(sys.executable).with_name("orchestra")`, or
`[sys.executable, "-m", "orchestra", "run"]`). Wait for the bus, the store or HTTP to show the
result, then SIGTERM the host and check the process's log in `<state>/logs/machines/`. Examples:
`orchestra-bridges/tests/e2e/test_orchestra_run.py`, and `orchestra-tasking/tests/e2e/test_demo_e2e.py`,
which reuses `demo/run.py`'s own `make_project`/`start`/`stop` and runs the Tickets page in
headless Chrome when one is at hand.

**Fixtures every level shares:**

- a temporary `ORCHESTRATOR_HOME`, so no test touches `~/.orchestrator`;
- `ORCHESTRA_EVENTS_URL` and `ORCHESTRA_METRICS_URL` removed, so the file bus and file store are used;
- `ORCHESTRA_REPO` set to the temporary repository, as the launcher would set it;
- an injected clock where time matters (the bridges' `Clock`, the heartbeat's `clock=`).

**Fakes, one per thing on the other side of a protocol.** The rule in all three repositories is
to fake what your code talks to, in its real shapes, and never to mock the code under test:

| Fake | Stands in for | Used by |
|---|---|---|
| `orchestra-tasking/tests/fake_machine.py` (`FakeMachine`) | a machine filling the worker and reviewer roles, speaking only the assignment protocol on the bus | the scheduler's tests |
| `orchestra-agents/tests/fake_tasks.py` (`FakeTasks`) | the task system's request desk (`request.done` / `request.refused`), in memory | the agents' tests, without the real task system |
| `orchestra-agents/tests/e2e/fake_pi.py`, `fake_claude.py`, `fake_codex.py` | the harness binaries, speaking their real stream protocols; selected with `PI_BINARY`, `CLAUDE_BINARY`, `CODEX_BINARY` | the agents' e2e tests, once per harness |
| `orchestra-bridges/tests/fake_github.py` (`FakeGitHub`) | GitHub's REST API, as a local HTTP server in the real response shapes | the bridge's unit and e2e tests |
| `orchestra-bridges/tests/contract/` | the real API, opt-in, shapes only | checks the fake stays honest |

The agents' and the task system's e2e tests also run the real other plugin (`orchestra-tasking`
is a dev dependency of `orchestra-agents`) beside the fakes.

---

## 11. Versioning and compatibility

How it stands today:

- Orchestra is `1.0.0a1`. The plugin interface has **no version number** of its own and no
  compatibility check. A plugin is a `Plugin` dataclass instance, and that is the contract.
- All three plugins depend on an unpinned `orchestra`, resolved through `[tool.uv.sources]` to an
  editable checkout at `../orchestra_2`. They run against whatever is checked out there.
- The interface changes in lockstep with its users. For example, `Declared` lost its
  `description` field in orchestra_2 `6d80b787`, and the agents dropped the argument the same day
  (orchestra-agents `ba7135c`). Kind per instance (`f6402f05`) changed what `m.kind` holds, and the
  agents' cards followed (`91ce6dd`).

How to stay compatible:

- **Pass `Plugin(...)` and `Declared(...)` fields by keyword** after `name`. The task system and the
  agents pass `pages`, `static` and `router` positionally, which ties them to the field order.
- Import only the interfaces: `orchestra.plugins` (`Plugin`, `Page`, `Declared`),
  `orchestra.launcher.Process`, `orchestra.events`, `orchestra.metrics`, `orchestra.config`, and
  `orchestra.runtime.alive` if you need it. Keep `orchestra.web.*` to tests.
- Don't set `Process.owner`, and don't depend on fields `/api/machines` does not document (§5).
- A plugin built against a newer Orchestra that passes a keyword an older `Plugin` lacks raises
  `TypeError` when it loads. The web app reports it, the host logs it, and nothing else breaks.
- When publishing a plugin outside this machine, pin a range (`orchestra>=1.0.0a1,<1.1`) and run
  your e2e test against Orchestra's `main` before each release.

---

## 12. Pitfalls the existing plugins hit

### 12.1 Announcements

- **Announce before your first event, once per instance, with `package`.** Without `package`, the
  machine is not yours and your card never draws it. Without `listens_for`, the map infers what you
  read from hand-offs.
- **Announce only what you act on as yourself.** The agents' host used to announce that it listened
  for `task.assigned`, `task.released` and `task.attention_needed`, which its agents act on, not
  the host (fixed in orchestra-agents `ca04f16`).
- **Publish as the right source.** The same commit fixed snapshot queries that went out under the
  host's default source, so the map showed the host asking the task system. Pass `source=` every time.
- **Don't describe yourself.** Announcements and declarations carried `does` and `description`
  fields that nothing read. They were removed (orchestra_2 `6d80b787`, orchestra-agents `ba7135c`).
  Orchestra reads `mode`, `kind`, `listens_for`, `log`, `package`, `name` and `group`. Anything else
  is passed to your card as `m.about`, and only the latest announcement's `about` survives.
- **A sync announces in its own time.** The GitHub bridge announces each person stamped with the
  time of their first event, with a stable id (`github:announce:...`), so a re-read never
  duplicates it, and announces again only when the name or team changed.
- **Announcing is not living.** Announcements do not count towards a machine's cadence. A machine
  that announces and then falls silent goes inactive.

### 12.2 Instance naming

A source is `<machine>/<instance>`. Two programs that publish as the same source are, to Orchestra
and to any protocol keyed on the source, **one instance**. In the agents' demo, the agents' host
names its AI workers `worker/1`, `worker/2`, so the program worker had to be named `worker/shell`
(`shell_worker.py shell`). Otherwise two machines would both have held one assignment. Choose an
instance name that cannot collide, and label your series `machine=<machine>`,
`instance=<instance>` to match the source.

### 12.3 Kind per instance

`kind` and `mode` belong to each instance; its latest announcement stands. A machine whose
instances differ gets a combined `kind` such as `"agent ×2, program ×1"`, with the counts in
`kinds` (`{"agent": 2, "program": 1}`) and each instance's own kind in `instances[i].kind`. The
agents' cards compared `m.kind === "agent"` and lost the worker's card when the program worker
joined it (fixed in `91ce6dd`: `m.kinds && m.kinds.agent ? "agent" : m.kind`). Read `kinds` or
`instances` and never compare `kind` exactly. A declared `kind` fills in only when no instance
announced one.

### 12.4 A `[[scrape]]` overwrites the `machine` label

A scrape (or a `[[collect]]`) replaces every point's `machine` and `project` labels with its own
name (`orchestra/collect/round.py`). So:

- name the scrape after the machine whose series it reads. The Slack bridge's must be named
  `bridges.slack`, or its series belong to some other machine and a restarted bridge cannot find
  its counts;
- one scrape cannot serve series for several machines. Per-machine `machine=` labels in your
  `/metrics` output are lost; use another label, or write through `orchestra.metrics` instead;
- the host announces the scrape on the machine's behalf (source = the scrape's name, `kind:
  program`, `mode: continuous`, extra fields `collector`, `url`, `every_s`, and the log
  `<state>/logs/machines/<scrape name>.log`). That becomes the bare instance's latest announcement,
  so it replaces `m.about` and that instance's log path. `package` survives, because the scrape's
  announcement carries none;
- the plugin cannot declare the scrape, so the owner adds it to `orchestra.toml` by hand (§13).

### 12.5 An editable install imports the working tree

- The plugins install Orchestra **editable** from `../orchestra_2`. Everything they run imports
  that checkout's working tree as it is now: their tests, `orchestra run`, `orchestra web`, and
  every process started with `sys.executable`. If someone switches that checkout to another branch
  or leaves it half-edited, every plugin runs that code. A git worktree of Orchestra is not what
  the plugins import, and neither is a clone elsewhere, unless the source path points there.
- Orchestra resolves a git worktree to its main repository (`find_repo_root` uses
  `--git-common-dir`). `orchestra run` inside a worktree runs the main checkout's project: its
  `orchestra.toml`, its project key and its state directory. Try plugins in a plain directory or a
  clone.
- The same applies to the plugin itself. Its own `.venv` imports the checkout it was synced from.
  A different checkout needs its own `uv sync`.
- Already-running processes keep the code they imported. `orchestra web` mounts plugins once, so
  restart it after changing a plugin. The host re-asks for processes, but its own imported plugin
  module is not reloaded. Launched processes pick up new code when they restart.

### 12.6 Smaller ones

- `plugin()` runs often (§2). The agents' plugin builds an `AgentStore` and an `Events` in its
  router on every call; keep yours lazy.
- `orchestra run` passes its whole environment to every process it starts. Never put a secret in
  it (the Slack bridge reads its token from a file outside the repository for this reason).
- `stop_grace_s` must exceed your own shutdown, or Orchestra kills you halfway and your children
  are orphaned (the agents' 30 s against their 20 s worst case).
- Every-page stylesheets restyle every page: prefix your selectors.
- Use `sys.executable` in process commands, not `python`.
- A series named `orchestra_*` is refused by collectors and left out by discovery.

---

## 13. What the interface does not do yet

Gaps and inconsistencies in the plugin interface on `main` today. This is a list, not a plan.

1. **No way to declare a scrape or a collector.** `Plugin` can declare processes but not
   `[[scrape]]` or `[[collect]]` entries. The Slack bridge serves `/metrics` and must ask the owner
   to add `[[scrape]] name = "bridges.slack"` by hand.
2. **The web app never reloads plugins.** The host asks for processes again on every
   `orchestra.toml` change; the web app calls `plugin()` once at start. Declarations that depend on
   config (the bridges', the heartbeat's) are stale until `orchestra web` restarts.
3. **No CLI extension point**, and the `orchestra` CLI cannot list the installed plugins or their
   errors. Only `/api/plugins` in the web app can.
4. **`/api/plugins` lists pages, scripts and errors only.** A plugin with no pages, such as the
   bridges, is invisible there. Its processes show on the Core page, its declared machines on the
   Machines page, and its stylesheets nowhere.
5. **No config registry or namespacing.** Sections are read from `raw` by convention, so two
   packages can claim one section undetected. The task system claims generic names (`[project]`,
   `[gate]`, `[staging]`).
6. **Plugin names are not checked.** A name that fails the process-name pattern only shows up as a
   launcher log line. Two plugins with the same `name` are not detected: the host keys processes by
   plugin name, so one plugin's processes silently replace the other's, and the web app mounts two
   static directories at one path. `load` reports errors under the entry point's name, which may
   differ from `Plugin.name`.
7. **No interface version.** The field order of `Plugin` is de facto API, because two plugins pass
   fields positionally (§11).
8. **`Process` has no `env` or `cwd`.** Every process runs in the repository root with the host's
   environment. There is no way to pass a per-process setting except argv, and no way to keep a
   secret out of other processes' environments.
9. **`Declared` cannot carry a log, a name or a group.** An unseen machine cannot show where its log
   will be.
10. **Missing script or stylesheet files are dropped silently**, not reported in `errors` (Orchestra's own
    test asserts this behaviour).
11. **`{{v}}` reflects only Orchestra's static files**, so `?v={{v}}` on a plugin's own assets
    never changes when the plugin's files change. The `Cache-Control: no-store` header on every
    response makes this harmless today.
12. **Collector names are not checked against plugin processes.** The launcher refuses a project
    `[[machines]]` entry named `<plugin>.<x>`, but a `[[collect]]` with a plugin process's name is
    accepted (only `[[scrape]]` is meant to share a program's name).
13. **The plugins read their config in different ways.** The bridges read `project.config.raw`.
    The agents re-read `orchestra.toml` from disk with `tomllib` in `processes()`, and build a
    second project with `load_project(repo_root)`, although the host has just reloaded the config
    it passes in.
