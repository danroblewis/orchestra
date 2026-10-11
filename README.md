# Orchestra

A ticket tracker, milestone planner, and CI/CD workflow operated by AI agents on
[Pi](https://github.com/earendil-works/pi) or Claude Code. Point it at a git
repository; describe work to the Supervisor; workers build tickets on their
own branches, reviewers check them, and a merge gate builds, tests, and lands
what passes on `main`.

- `SPEC.md` is the design.
- `AGENTS.md` is the list of rules that must not be broken.

## Install

As a tool, available on your PATH from any directory:

```bash
uv tool install /path/to/orchestra          # or: uv tool install -e /path/to/orchestra for development
```

Or for hacking on Orchestra itself: `uv sync --extra dev` and `uv run orchestra ...`.

Requires `pi` on your PATH with a configured model.

## Use it on a project

```bash
cd my_other_project          # any git repository, or a subdirectory or worktree of one
orchestra init               # writes orchestra.toml and registers the project (once)
orchestra web &              # the dashboard on http://127.0.0.1:8000
orchestra run                # the loop: workers, reviewers, merge gate, and the resident
                             # coordinator and pipeline-manager sessions
orchestra chat               # in another terminal: talk to the Supervisor
```

The project is the nearest git repository above the current directory; from
inside a linked worktree it resolves to the main repository. A repository that
already carries an `orchestra.toml` needs no `init`, so a fresh clone works
immediately. `--repo /path` or `ORCHESTRA_REPO` override the directory.

`orchestra init` accepts `--provider`, `--model`, `--prefix`, and
`--unit-command`; leave provider and model empty to use the harness's defaults.
`[agents] harness` in `orchestra.toml` picks `pi` (default) or `claude_code`
(for example `harness = "claude_code"` with `model = "haiku"`). Edit
`orchestra.toml` for the build, unit, acceptance, and staging stages the gate
runs (see `SPEC.md` section 9, or this repository's own `orchestra.toml`).

Read-only inspection:

```bash
orchestra status
orchestra ticket list | show ABC-3
orchestra milestone list
orchestra sessions list | show worker-ABC-3
orchestra doctor
```

State lives in `~/.orchestrator/<repo-name>-<hash>/`: tickets, runtime records,
the event log, agent session records, worktrees, gate logs. Nothing is written to your
repository except `orchestra.toml`.

## Orchestra on Orchestra

This repository is configured to be developed by Orchestra. Its
`orchestra.toml` defines the gate the way any project should:

| Stage | What runs |
|---|---|
| build | `uv build --wheel` producing `dist/orchestra-*.whl` |
| unit | `tests/unit` (model, store, config, harness layer) and `tests/e2e` (the real loop and gate driven by fake harnesses: `tests/e2e/fake_pi.py` and `fake_claude.py`, once each) |
| start | `scripts/acceptance_target.py` installs the built wheel in an isolated environment, creates a throwaway project, seeds it through the CLI, runs the loop on the fake Pi, and serves the web UI |
| acceptance | `tests/acceptance` against that running instance; `scripts/acceptance_real.sh [provider] [model] [harness]` runs the opt-in real-model flow (a Supervisor message becomes code on main) on either harness |

Each unit spec has a `select` template so the gate can rerun individual
failing tests during bisection. Run the ordinary suite with
`uv run pytest tests/unit tests/e2e -q`; acceptance tests skip unless
`ORCHESTRA_TARGET_URL` is set.

## What is implemented

Phase 1 of `SPEC.md` plus the project agents:

- Ten-state ticket model with the transition table enforced by the store.
- Worker and reviewer sessions in per-ticket worktrees, reporting through the
  `report_ticket` and `report_review` tools, on whichever harness the project
  configures (`orchestra/harness/`: Pi, Claude Code; others slot in behind the
  same interface).
- Long-lived Supervisor, Coordinator, and Pipeline Manager sessions with role
  prompts in `orchestra/agents/prompts/`, resident while `orchestra run` is up.
- A merge gate that assembles a gate branch, runs build, unit, start, and
  acceptance stages, and fast-forwards `main`. One ticket per run for now.
- Staging: the most recently landed build runs as a live instance, supervised by the
  loop, redeployed by the gate, rolled back on a failed health probe; optional
  cloudflared tunnel. `orchestra staging deploy|status|logs|restart|stop`.
- The dashboard (agents, merge gate, system stats, staging) and the ticket graph page.

Not yet: batched gates with bisection, external
ticket backends, the React frontend.
