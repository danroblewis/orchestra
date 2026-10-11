# Orchestra

A ticket tracker, milestone planner, and CI/CD workflow operated by AI agents on
the [Pi](https://github.com/earendil-works/pi) harness. Point it at a git
repository; describe work to the Supervisor; workers build tickets on their
own branches, reviewers check them, and a merge gate lands what passes on
`main`.

- `SPEC.md` is the design.
- `AGENTS.md` is the list of rules that must not be broken.

## Install

```bash
uv sync --extra dev          # in this repository
uv run orchestra --help
```

Requires `pi` on your PATH with a configured model.

## Use it on a repository

```bash
cd /path/to/your/repo
orchestra init --provider <pi-provider> --model <pi-model> --prefix ABC \
    --unit-command "uv run pytest -q"
# edit orchestra.toml to taste, commit it

orchestra run        # terminal 1: the loop (workers, reviewers, gate, coordinator, pipeline manager)
orchestra web        # terminal 2: the UI on http://127.0.0.1:8000
orchestra chat       # terminal 3: talk to the Supervisor; it creates milestones and tickets
```

From any other directory, pass `--repo /path/to/your/repo` or set `ORCHESTRA_REPO`.

Read-only inspection:

```bash
orchestra status
orchestra ticket list | show ABC-3
orchestra milestone list
orchestra sessions list | show worker-ABC-3
orchestra doctor
```

State lives in `~/.orchestrator/<repo-name>-<hash>/`: tickets, runtime records,
the event log, Pi session files, worktrees, gate logs. Nothing is written to your
repository except `orchestra.toml`.

## What is implemented

Phase 1 of `SPEC.md` plus the project agents:

- Ten-state ticket model with the transition table enforced by the store.
- Worker and reviewer Pi sessions in per-ticket worktrees, reporting through the
  `report_ticket` and `report_review` tools.
- Long-lived Supervisor, Coordinator, and Pipeline Manager sessions with role
  prompts in `orchestra/agents/prompts/`, woken by events.
- A merge gate that assembles a gate branch, runs build, unit, start, and
  acceptance stages, and fast-forwards `main`. One ticket per run for now.
- The three-column web UI: agents, ticket graph, pipeline.

Not yet: batched gates with bisection, staging deploy and tunnel, external
ticket backends, the React frontend.
