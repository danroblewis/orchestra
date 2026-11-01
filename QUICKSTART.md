# Quickstart

Orchestra on your own project in five steps:

- **Measure it:** your tests and your own metrics, over time.
- **Model it:** a system dynamics model, discovered from those measurements.
- **See who does the work:** every machine that publishes on the event bus, and who hands work to whom.

You need:

- macOS or Linux, `git`, and [uv](https://docs.astral.sh/uv/);
- a git repository with tests.

## 1. Install

```bash
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main'
uv tool update-shell
```

Open a new terminal. `orchestra --help` should list `run`, `web` and `init`.

`sd` is the model and its discovery. Plugins are installed the same way, by adding their names to
the brackets (see **Plugins** below).

## 2. Configure

Save this as `orchestra.toml` at the root of your repository. Change the line marked `←`.

```toml
# Measure: your test results, every 5 minutes.
[[collect]]
name = "tests"
command = "python -m orchestra.instruments.test_reports --run 'uv run pytest -q'"   # ← your test command
every = "5m"
timeout = "4m"
```

Then:

```bash
orchestra init
git add orchestra.toml && git commit -m "Orchestra"
```

## 3. Start

Two terminals, both in your repository:

```bash
orchestra run    # terminal 1: measures, models, keeps declared commands running
orchestra web    # terminal 2: the web UI
```

## 4. Log in

Click the **log in** link that `orchestra web` prints. Lost it? Run `orchestra web token`.

## 5. Look

Open the **Instruments** page: the `tests` instrument's last run and what it wrote. The
**Dynamics** page shows the first model once something measured moves (counters that fill or
drain a level, or a level that changes enough to fit); until then it lists why each series was
left out.

---

# After the quickstart

## What each page shows

| Page | What it shows |
|---|---|
| Dashboard | Two panels: the machines running now, and the host (whether the host, bus and metrics store are up, and the computer's CPU, memory, disk and GPU). The instruments are on the Instruments page and the model on Dynamics. |
| Machines | Who does the work (programs, people, services), and who hands work to whom |
| Instruments | Each measurement: when it last ran, and what it wrote |
| Dynamics | The model: stocks, flows, and how well they fit, and what you expect beside it ([the intended model](USING_ORCHESTRA.md#what-you-expect-the-intended-model)). The first model appears once something measured moves. |
| Experiments | Edits to the model's equations, run forward and compared with what was measured |
| Core | The bus, the metrics store, and the processes. Up even when everything else is broken. |

## Hook in your project

| You want | Add to `orchestra.toml` |
|---|---|
| Any number your scripts can print | `[[collect]]` with `name`, `command` and `every`. The command prints `name value` lines (Prometheus text). |
| Your app's `/metrics` | `[[scrape]]` with `name`, `url = "http://127.0.0.1:8080/metrics"` and `every = "15s"` |
| Unit and e2e tests on different schedules | Two `[[collect]]` entries, each with its own `--run` command |
| A program kept running | `[[machines]]` with `name` and `command` |

Inside these commands, `python` is Orchestra's own Python. For your project's Python, use `uv run python`.

## Safety

- The web UI listens on localhost only, and needs the login token.
- Orchestra runs no AI. The pages change nothing but observations: rediscovering the model, and
  marking what you expect or confirm, each recorded with who and when; a machine's confirm is a
  request to the machine that listens for it.
- In your repository Orchestra writes only `orchestra.toml`: on `orchestra init`, and when a
  plugin changes the configuration through Orchestra (`project.config_edit`).

## Plugins

Each plugin is its own package. Install one by adding its name to the brackets of the install
command (`orchestra[sd,agents]`) and running it again; its own README says how to configure it.
`workflows` is private: it installs only with access to its repository; the rest install without it.

| Plugin | What it adds | Read |
|---|---|---|
| agents | AI agents as machines | [orchestra-agents](https://github.com/danroblewis/orchestra-agents#readme) |
| workflows | Your team's own workflows as items, piles and offers to machines | orchestra-workflows (private: needs access to its repository) |
| bridges | Activity in other systems, relayed onto the bus | [orchestra-bridges](https://github.com/danroblewis/orchestra-bridges#readme) |
| desk | Standing conditions and a ledger of what you asked for | [orchestra-desk](https://github.com/danroblewis/orchestra-desk#readme) |
| outbox | Messages and actions on your behalf, each one approved by you | [orchestra-outbox](https://github.com/danroblewis/orchestra-outbox#readme) |
| tasking | Tickets, milestones and a merge gate | [orchestra-tasking](https://github.com/danroblewis/orchestra-tasking#readme) |

To connect another system's store or events with your own coding tool, follow
[docs/INTEGRATING.md](docs/INTEGRATING.md).

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
| An instrument writes nothing | Instruments page: its last error. Try its command by hand in the repository. |
| No model on Dynamics | Read why each series was left out on the Dynamics page; a level that never changes is never a stock. |
| A plugin's command is missing from `orchestra --help` | The install line was missing its name. Run it again, complete. |

More: [USING_ORCHESTRA.md](USING_ORCHESTRA.md) (the full guide), [PLUGINS.md](PLUGINS.md) (writing plugins), [ARCHITECTURE.md](ARCHITECTURE.md).
