# Quickstart

Orchestra on your own project in five steps:

- **Measure it:** your tests and your own metrics, over time.
- **Model it:** a system dynamics model, discovered from those measurements.
- **Ask for changes:** tell the Supervisor what you want. Agents plan it, build it and review it, and your tests gate every change.

You need:

- macOS or Linux, `git`, and [uv](https://docs.astral.sh/uv/);
- [Claude Code](https://docs.claude.com/en/docs/claude-code), installed and logged in (`claude --version`);
- a git repository with tests.

## 1. Install

```bash
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' --with 'orchestra-tasking @ git+https://github.com/danroblewis/orchestra-tasking' --with 'orchestra-agents @ git+https://github.com/danroblewis/orchestra-agents' --with 'orchestra-bridges @ git+https://github.com/danroblewis/orchestra-bridges' --with 'orchestra-desk @ git+https://github.com/danroblewis/orchestra-desk' --with 'orchestra-outbox @ git+https://github.com/danroblewis/orchestra-outbox'
uv tool update-shell
```

Open a new terminal. `orchestra --help` should list `tasks`, `agents`, `bridges`, `desk` and `outbox`.

This installs every plugin. Bridges, desk and outbox stay off until you ask the Supervisor to set them up (see **Plugins** below).

## 2. Configure

Save this as `orchestra.toml` at the root of your repository. Change the lines marked `←`.

```toml
# Measure: your test results, every 5 minutes.
[[collect]]
name = "tests"
command = "python -m orchestra.instruments.test_reports --run 'uv run pytest -q'"   # ← your test command
every = "5m"
timeout = "4m"

# Changes: each ticket on its own branch. It lands on base_branch only if the tests pass.
[project]
base_branch = "main"     # ← your main branch
ticket_prefix = "APP"    # ← tickets are named APP-1, APP-2, …
work = "code"
push = false             # nothing leaves your machine

[[gate.unit]]
name = "unit"
command = "uv run pytest -q"   # ← your test command

# The agents: a Supervisor you talk to, and a Coordinator, workers and reviewers.
[agents]
harness = "claude_code"
model = "haiku"          # cheap; "sonnet" or "opus" for harder work
serves = ["worker", "reviewer"]
```

Then:

```bash
orchestra init
git add orchestra.toml && git commit -m "Orchestra"
```

## 3. Start

Two terminals, both in your repository:

```bash
orchestra run    # terminal 1: measures, models, runs the agents
orchestra web    # terminal 2: the web UI
```

## 4. Log in

Click the **log in** link that `orchestra web` prints. Lost it? Run `orchestra web token`.

## 5. Ask for something

Open the **Agents** page and tell the Supervisor what you want, for example:

> Add a `/version` endpoint that returns the app's version, with a test.

The Coordinator turns your request into tickets, workers build them and reviewers check them. Follow the progress on the **Tickets** page. A finished change is a commit on `main`.

---

# After the quickstart

## What each page shows

| Page | What it shows |
|---|---|
| Agents | The Supervisor's chat, every agent, and what each one is doing |
| Tickets | The plan: milestones and tickets, open, in progress, in review, done |
| Machines | Who does the work (agents, programs, people), and who hands work to whom |
| Instruments | Each measurement: when it last ran, and what it wrote |
| Dynamics | The model: stocks, flows, and how well they fit. The first model appears after about an hour of data. |
| Core | The bus, the metrics store, and the processes. Up even when everything else is broken. |

## Hook in your project

| You want | Add to `orchestra.toml` |
|---|---|
| Any number your scripts can print | `[[collect]]` with `name`, `command` and `every`. The command prints `name value` lines (Prometheus text). |
| Your app's `/metrics` | `[[scrape]]` with `name`, `url = "http://127.0.0.1:8080/metrics"` and `every = "15s"` |
| Unit and e2e tests on different schedules | Two `[[collect]]` entries, each with its own `--run` command |
| A program kept running | `[[machines]]` with `name` and `command` |
| More checks before a change lands | One `[[gate.unit]]` per command |

Inside these commands, `python` is Orchestra's own Python. For your project's Python, use `uv run python`.

Or ask the Supervisor: "measure the number of open todos every minute". It changes `orchestra.toml` and tells you why.

## Safety

- Agents work on local branches. Nothing is pushed while `push = false`.
- The web UI listens on localhost only, and needs the login token.
- Agents run as you, with your Claude Code login.

## Plugins

All five are installed by step 1. Tasking and agents run from the start. The others do nothing until you ask the Supervisor to set them up: it reads each plugin's guide and writes the configuration.

| Plugin | What it adds | Ask the Supervisor, for example |
|---|---|---|
| tasking | Tickets, milestones and the merge gate | (on from the start) |
| agents | The Supervisor, Coordinator, workers and reviewers | (on from the start) |
| bridges | GitHub, Jira and Slack activity on the bus | "Bring in the pull requests from my GitHub repository" |
| desk | Standing conditions, such as "tests pass on main", and a ledger of what you asked for | "Keep the tests passing on main" |
| outbox | Messages and actions on your behalf, each one approved by you | "Open GitHub issues for problems you find, after I approve them" |

GitHub uses your `gh` login. Jira and Slack need a token you create; the Supervisor tells you which file to save it in. Tokens never go in `orchestra.toml`. Outbox drafts wait on the **Outbox** page until you approve them.

To leave a plugin out, drop its `--with` from the install command and run it again: a plugin left out of the command is uninstalled.

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
| `orchestra --help` has no `tasks` | The install line was missing a plugin. Run it again, complete. |
| The Supervisor doesn't answer | Core page: is `agents.host` running? Log: `~/.orchestrator/<key>/logs/machines/agents.host.log`. Check `claude --version`. |
| A ticket is BLOCKED | Open it on the Tickets page for the reason. Ask the Supervisor what to do. |
| An instrument writes nothing | Instruments page: its last error. Try its command by hand in the repository. |
| No model on Dynamics | Wait about an hour. The page lists why each series was left out. |
| Want to try without a model | `harness = "dummy"`: scripted agents, free. They don't understand requests. |

More: [USING_ORCHESTRA.md](USING_ORCHESTRA.md) (the full guide), [PLUGINS.md](PLUGINS.md) (writing plugins), [ARCHITECTURE.md](ARCHITECTURE.md).
