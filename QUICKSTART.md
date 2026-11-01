# Quickstart

Orchestra on your own project in five steps:

- **Measure it:** your tests and your own metrics, over time.
- **Model it:** a system dynamics model, discovered from those measurements.
- **Ask for changes:** tell the Supervisor what you want. Work moves through a workflow (write,
  review), done by AI agents.

You start on the core and the Workflows plugin, with its first example, the **task loop**
(write → review → gate). You write no configuration: `orchestra init` writes a starter file, and
from then on the Supervisor writes every setting from what you tell it in the chat.

You need:

- macOS or Linux, `git`, and [uv](https://docs.astral.sh/uv/);
- a git repository with tests.

## 1. Install

```bash
uv tool install 'orchestra[sd,agents,workflows] @ git+https://github.com/danroblewis/orchestra@main'
uv tool update-shell
```

Open a new terminal. `orchestra --help` should list `agents` and `workflows`.

`sd` is the model and its discovery; `agents` is the Supervisor and the agents that do the work;
`workflows` moves the work. Add `bridges` and `outbox` to the brackets when you want them (see
**Plugins** below).

## 2. Watch the task loop run

The Workflows plugin's first example runs on scripted machines: no model, no cost, nothing outside
a temporary folder.

```bash
git clone https://github.com/danroblewis/orchestra-workflows
orchestra-workflows/examples/task_loop/demo.sh
```

It prints a link. Open it: the **Machines** page shows the coordinator, two workers, a reviewer and
the merge gate handing ten pieces of work to each other; **Items** shows each one's step; after a
few minutes **Dynamics** shows the model discovered from it. Ctrl-C stops it. This is what your
own project will do in step 5, with AI agents in place of the scripts.

## 3. Start Orchestra on your repository

```bash
cd <your repository>
orchestra init     # registers it and writes a starter orchestra.toml: nothing in it to change
orchestra run      # terminal 1: measures, models, runs the agents
orchestra web      # terminal 2: the web UI; click the "log in" link it prints
```

Lost the link? Run `orchestra web token`. With no `[agents]` settings, the agents run on Claude
Code with Haiku (cheap); ask the Supervisor for `sonnet` or `opus` for harder work.

## 4. Tell the Supervisor what to measure

Open the **Agents** page and type, with your own test command:

> Measure my tests every 5 minutes. The command is `uv run pytest -q`.

The Supervisor tries the command once, then writes this to `orchestra.toml` and commits it, with
its reason (`set_collector`):

```toml
[[collect]]
name = "tests"
command = "python -m orchestra.instruments.test_reports --run 'uv run pytest -q'"
every = "5m"
timeout = "4m"
```

The **Instruments** page shows it within a round. Anything else you want measured, ask the same
way ("measure the number of open TODOs every minute").

## 5. Tell the Supervisor how work moves

Type:

> Set up the task loop on this repository: a worker writes each change in its own worktree, and a
> reviewer reviews it; a rejection goes back to the worker, at most three rounds.

The Supervisor writes the workflow (`declare_workflow`) to
`~/.orchestrator/<key>/workflows/task_loop/workflow.json`: a `write` step for the role `worker`
needing a `worktree`, then a `review` step for the role `reviewer` (`approved` ends it, `rejected`
goes back to `write`, `rounds` 3). The built-in worker and reviewer agents take those roles, and
the worktrees are built in (each made from `origin/main`, fetched: your repository needs an
`origin` with a `main` branch; nothing is pushed to it). The **Workflows** page draws it; **Items** shows each piece of work.

**Starting a piece of work.** Type: *"Start the task loop on adding a /version endpoint that
returns the app version, with a test."* The Supervisor asks which workflow if more than one fits,
then starts the item and answers with its id (for example `task_loop-3fa2c1`) and its link on
**Items** (`/items/<id>`); ask it where the item is at any time. If `orchestra run` is not
running, it says so and starts nothing. The approved change is a commit on the item's branch in
its worktree; you merge it.

**Known gap today** (the Supervisor cannot do this from the chat yet):

- **The gate.** The example's third step, `gate` (merge into `main` when the tests pass), is a
  program, and a program is code: the Supervisor hands code to the Coordinator, which today plans
  it as tickets only with the tasking plugin, which this quickstart leaves out. The example's gate
  (`examples/task_loop/target/.orchestra/machines/merge_gate/`) pushes to `origin`, so do not copy
  it into a repository whose `origin` you do not want pushed to.

---

# After the quickstart

## What each page shows

| Page | What it shows |
|---|---|
| Agents | The Supervisor's chat, every agent, and what each one is doing |
| Workflows | Each workflow, drawn: its steps, who does each, and where a result goes |
| Items | Each piece of work: its step, who holds it, and why it waits |
| Machines | Who does the work (agents, programs, people), and who hands work to whom |
| Instruments | Each measurement: when it last ran, and what it wrote |
| Dynamics | The model: stocks, flows, and how well they fit, and what you expect beside it ([the intended model](USING_ORCHESTRA.md#what-you-expect-the-intended-model)). The first model appears once something measured moves. |
| Experiments | Edits to the model's equations, run forward and compared with what was measured |
| Core | The bus, the metrics store, and the processes. Up even when everything else is broken. |

## Hook in your project

Ask the Supervisor; it writes the entry and tells you why. What it writes, so you can read
`orchestra.toml`:

| You ask | It writes |
|---|---|
| "Measure any number my script prints" | `[[collect]]` with `name`, `command` and `every`. The command prints `name value` lines (Prometheus text). |
| "Read my app's `/metrics`" | `[[scrape]]` with `name`, `url = "http://127.0.0.1:8080/metrics"` and `every = "15s"` |
| "Run unit and e2e tests on different schedules" | Two `[[collect]]` entries, each with its own `--run` command |
| "Keep this program running" | `[[machines]]` with `name` and `command` |

Inside these commands, `python` is Orchestra's own Python. For your project's Python, use `uv run python`.

## Safety

- Agents work in local worktrees, on local branches. Nothing is pushed unless a program you add pushes.
- The web UI listens on localhost only, and needs the login token.
- Orchestra runs no AI. The pages change nothing but observations: rediscovering the model, and
  marking what you expect or confirm, each recorded with who and when; a machine's confirm is a
  request to the machine that listens for it.
- In your repository Orchestra writes only `orchestra.toml`: on `orchestra init`, and when a
  plugin changes the configuration through Orchestra (`project.config_edit`).

## Plugins

| Plugin | What it adds | Ask the Supervisor, for example |
|---|---|---|
| agents | The Supervisor, Coordinator, workers and reviewers | (on from the start) |
| workflows | How work moves: workflows of steps, items, offers to machines | "Set up the task loop on this repository" |
| bridges | A library for collectors of Jira, Slack, PagerDuty and GitHub activity: each one a script in your repository | "Connect our Jira so I can see issue transitions and open counts" |
| outbox | Messages and actions on your behalf, each one approved by you | "Open GitHub issues for problems you find, after I approve them" |
| desk | Standing conditions, such as "tests pass on main", and a ledger of what you asked for | "Keep the tests passing on main" |

Install one by adding its name to the brackets in step 1 and running the install again; it does
nothing until you ask the Supervisor to set it up. `workflows` is private: it installs only with access to its
repository; the rest install without it. To connect Jira, Slack, PagerDuty or a
Prometheus store, ask the Supervisor: it scaffolds the collector into your repository
(`.orchestra/machines/<name>/`), asks for your yes and for where the token is (a variable's name or
a file's path, never the token), and writes the rest. Or follow
[docs/INTEGRATING.md](docs/INTEGRATING.md) with your own coding tool. Tokens never go in
`orchestra.toml`. Outbox drafts wait on the **Outbox** page until you approve them.

The tasking plugin (`orchestra[tasking]`: tickets, milestones, a merge gate) is the older, naive
implementation of the same loop; this quickstart leaves it out.

To leave a plugin out, drop its name from the brackets and run the install again: a plugin left out is uninstalled.

## Update, stop, remove

| To | Run |
|---|---|
| Update | The install command again, with `--reinstall` |
| Stop | Ctrl-C in both terminals |
| Remove the project's data | `rm -rf ~/.orchestrator/<key>` (`orchestra init` prints the key) |
| Uninstall | `uv tool uninstall orchestra` |

## If something is wrong

| You see | Do |
|---|---|
| `orchestra: command not found` | Run `uv tool update-shell`, then open a new terminal. |
| `orchestra --help` has no `workflows` | The install line was missing `workflows`. Run it again, complete. |
| The Supervisor doesn't answer | Core page: is `agents.host` running? Log: `~/.orchestrator/<key>/logs/machines/agents.host.log`. Check `claude --version`. |
| An item is waiting | Open it on the Items page for the reason. Ask the Supervisor what to do. |
| `orchestra: port 8000 is in use` (address already in use) | Another program, or another `orchestra web`, serves on it. Serve on another: `orchestra web --port 8010`. |
| An instrument writes nothing | Instruments page: its last error. Try its command by hand in the repository. |
| No model on Dynamics | Read why each series was left out on the Dynamics page; a level that never changes is never a stock. |
| A plugin's command is missing from `orchestra --help` | The install line was missing its name. Run it again, complete. |
| A graph or the Dashboard's grid stays blank | The core pages need no outside address: d3, elkjs and GridStack ship with Orchestra (`orchestra/web/static/vendor/`). Reload with the browser's cache bypassed; a plugin's page may still load its own from the internet. |

More: [USING_ORCHESTRA.md](USING_ORCHESTRA.md) (the full guide), [PLUGINS.md](PLUGINS.md) (writing plugins), [ARCHITECTURE.md](ARCHITECTURE.md).
