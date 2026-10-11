# Rules for working on Orchestra

Read `SPEC.md` first. It is the design. This file is the short list of rules
that must not be broken without updating the spec and saying so in the commit.

## Invariants

1. **Only Orchestra changes ticket state.** Agents report through their tools;
   the loop applies the transition table in `SPEC.md` section 3. Never add a
   code path where an agent's output is translated into a different state.
2. **No zombies.** A ticket is `IN_PROGRESS`, `IN_REVIEW`, or `MERGING` only
   while a live process owns it. When the process stops, the ticket moves to a
   waiting state in the same code path.
3. **One worktree per ticket, outside the repository.** Workers and reviewers
   run with their working directory set to the ticket's worktree. Nothing is
   ever written inside the user's checkout except `orchestra.toml`.
4. **Merging is programmatic.** No agent runs `git merge`, `git push`, or
   touches the base branch. Only the gate lands code.
5. **State lives in `~/.orchestrator/<key>/`.** Business logic goes through
   the `TicketBackend` interface and the runtime store. No module reads or
   writes those JSON files directly except `orchestra/store/`.
6. **Pi's session file is the only transcript.** Do not write a parallel log
   of agent messages.
7. **Humans converse only with the Supervisor.** Humans may edit tickets via
   CLI and UI; they do not prompt the Coordinator, Pipeline Manager, workers,
   or reviewers.
8. **One package, no path hacks.** Everything importable is under
   `orchestra/`. No `sys.path` manipulation.

## Pi facts the code depends on

- No MCP, no inbound HTTP, no scheduler. Tools come from the Orchestra Pi
  extension. Timers live in the loop.
- `pi --mode rpc` reads one JSON command per line on stdin and writes events
  on stdout. `agent_settled` is the completion signal. `message_end` with
  `role: assistant` is the authoritative final message.
- Sessions are JSONL files. `--session-dir` and `--session-id` place them.
  `steer` interrupts a running agent; `follow_up` queues; `prompt` starts a
  turn when idle.
- Installed docs: `~/.pi/agent/install/releases/<version>/node_modules/@earendil-works/pi-coding-agent/docs/`.

## Conventions

- Python 3.12+, `uv` for everything, `pytest` for tests, `ruff` for lint and
  format.
- Tests that need a real Pi and model are opt-in via `ORCHESTRA_ACCEPTANCE=1`
  and must never be required for the suite to pass.
- Keep modules small and single-purpose. If a file needs a section divider
  comment, it should be two files.
