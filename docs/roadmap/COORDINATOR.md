# The coordinator's manual

How the session given `/goal` runs an unattended goal such as
[GOAL-2026-11-01-workflows.md](GOAL-2026-11-01-workflows.md). The coordinator does no
implementation itself: it plans, dispatches, watches, reviews, merges, logs and reports. It keeps
its own context small so it lasts two days.

## 1. The loop

```
read the goal document → pick every task whose dependencies are done → dispatch them in
parallel (one agent each, Opus, background) → start the watchdog if not running → on each
result: read the report (never the transcript), run the gate, merge or send back → log → repeat
```

Rules of the loop:

- **Never wait for the owner.** A question the goal document does not answer is decided
  conservatively (the option that changes the least and is easiest to reverse), logged under
  "Decisions made for the owner", and the run continues.
- **Never block on one agent.** While one task runs, dispatch everything else that is ready.
  Reviews of finished tasks run while the next tasks are being built.
- **Never read a subagent's transcript.** Ask for a report of at most 300 words, and read the
  files and commits it names.
- **One agent, one task, one worktree.** A task that turns out to need two things becomes two
  dispatches.
- **Log before and after.** Every dispatch, result, merge and decision is one line in the goal
  document's progress log, committed with the merge it belongs to (or on its own every hour).

## 2. The watchdog

At the start of the run, create a recurring reminder (CronCreate, every 20 minutes) with the
prompt:

> Watchdog: list the running agents and background commands. For each agent running longer than
> 90 minutes with no report, send it a message asking for a 100-word status and whether it is
> blocked. For one past 150 minutes, stop it, read what it committed in its worktree, and
> re-dispatch the remainder as a narrower task. For any shell command past 20 minutes (a pytest
> run, a demo), check whether it is hung (no new output, no CPU) and kill it if so. Then dispatch
> any task whose dependencies are now done. Log what you did.

Also:

- Every pytest run is dispatched with a timeout (`timeout` on the Bash call, 10 minutes for a
  unit suite, 20 for e2e) and its `rc` checked explicitly.
- A demo or server an agent starts is stopped by that agent before it reports; the watchdog
  kills any left behind, by the ports in the never-list excluded.
- If the coordinator itself has not logged anything for an hour, the watchdog's next firing is
  the signal to re-read the goal document from the top and continue from the log.

## 3. Dispatch templates

Every brief begins with the task's id and the lines of the goal document for it, names the input
files the task needs (never "read everything"), and ends with the report format. Agents run on
Opus (`model: opus`) in the background.

### Implementer

```
Task <id> of docs/roadmap/GOAL-2026-11-01-workflows.md in <repo>. Read first: <files>.
Work in a git worktree of <repo>: `git -C <repo> worktree add <repo>-wt-<id> -b <id> origin/main`.
Deliverable: <from the goal document>. Acceptance: <from the goal document>.
Rules: follow AGENTS.md of the repository; keep modules small; tests for everything new;
`uv run python -m pytest` with the rc checked explicitly (rc=0 before you report; list any
pre-existing failure by name); ruff clean; commit on the branch with the trailer
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do not merge or push; stop every
process you start; never touch the never-list (below); never print credentials or tokens.
Report (≤300 words): the branch and commits, the suite result with rc, what is done, what is
not and why, anything the coordinator must decide.
```

### Document writer (M1)

```
Write <file> from docs/proposals/design-backwards-notes.md sections <…> and
docs/proposals/design-backwards.md, in the style of the existing proposals (plain language,
no code unless the thing is code, the owner's words quoted where they settle something).
Contents: <from the goal document>. Mark `Status: draft for review, <date>`. Each claim that
amends an invariant names the rule and the change. End with an acceptance-tests section.
Commit on a worktree branch; do not merge or push. Report the path and what you were unsure of.
```

### Document review panel (M1 and any spec)

Five reviewers in parallel, each an Opus agent with one lens, then a judge, then the writer
revises. The lenses:

1. **System dynamics:** does the proposal keep one model, stocks discovered, equations with
   origin, declared things as hypotheses? Would a modeller find the intended model and the
   diff meaningful?
2. **The owner's job (SRE, the work charter and user stories):** can every workflow in
   `docs/user-stories.md` and the seven examples be expressed? Where does it fail?
3. **Orchestra's invariants (AGENTS.md rules 1–10):** every violation, every amendment not
   stated, every domain concept leaking into the core.
4. **Experience (the approved mockups, rule 9, "humans talk only to the Supervisor"):** does
   the proposal produce exactly the page states in `mockups/out/`? Anything a human must do by
   hand that the Supervisor should do?
5. **Refuter:** assume the proposal is wrong; find the strongest case that it cannot be built,
   will not scale (the measured sizes in notes §4), or contradicts an earlier decision.

Each reviewer returns findings as `{severity: blocking|major|minor, where, what, why, fix}`.
The judge (one agent) confirms each finding against the document and the notes, drops
duplicates and the unfounded, and returns the work list. The writer revises; the panel runs
again only on blocking findings. Two rounds at most; then the coordinator decides.

### Coverage check (end of M1)

One agent, given the four proposals and the notes: for every section and bullet of notes §1–13,
name the proposal and section that holds it, or write MISSING. The coordinator sends every
MISSING back to the right writer. The check passes with zero MISSING.

### Code review

Use the project workflows: `layered-review` (pass the repository, its scope in one sentence,
the task's brief), `model-acceptance` for anything that changes discovery or an example,
`ux-review` for page changes (it needs a demo that one command starts: the agents' demo with
`--dummy`, or the workflows plugin's example), `subtraction-audit` before pushing a milestone.
Findings of weight go back to the implementer as a narrower task; the coordinator never fixes
code itself.

## 4. Merging and pushing

- The coordinator merges, nobody else: `git merge --no-ff` of the task branch into `main` of
  the repository, after the gate passed, with a message that names the task.
- Before every push: the suite on `main` once more with `rc` checked; `ruff check`; a secret
  scan of the diff (`git diff origin/main..main | grep -E` the usual patterns, count must be 0);
  then `git push origin main`.
- Plugins that depend on a core change: the core is pushed first, then the plugin's
  `uv lock` is refreshed and committed, then the plugin is pushed.
- A new repository: `gh repo create danroblewis/<name> --private` after the secret scan of the
  first commit.

## 5. Costs and models

- Subagents: Opus. Workflows and panels: Opus.
- Live agent runs (A3, demos for UX review): Haiku, the agents' demo, capped as the goal
  document says. Record the estimate from transcript tokens in the report.
- No live run for anything a scripted or dummy run can prove.

## 6. The never-list

- `~/orchestra` (the old checkout), `~/orchestra-automata` and its long-running pytest,
  pid 9936, `/tmp/respawn8093.sh` (pid 25686): never touched.
- Ports `:8000`–`:8003`, `:8040`, `:8050`, `:8060`, `:8062`, `:8070`, `:8074`, `:8428`, `:9090`:
  never used, never killed.
- `~/.orchestrator`: never wiped; only state directories an agent created are removed.
- `~/orchestra-bakery`, `~/orchestra-sample-live`, `~/orchestra-metrics-lab`,
  `~/orchestra-flow-lab`: never pushed. The labs' `truth/` and the flow-lab manifest never reach
  a Supervisor's prompt.
- Credentials: never in `orchestra.toml`, never printed, never logged, never copied. The Jira
  token at `~/.config/orchestra-bridges/jira-cloud-token` and the lab token at
  `~/.config/orchestra-metrics-lab/token` are not read.
- Headless Chrome: kill only what you started (`pkill -f puppeteer_dev_chrome_profile`), never
  a Playwright Chrome.
- Claude Code's own task and cron tools stay disallowed for Orchestra's agents.
- No workflows (the Workflow tool) without the goal's explicit scope; the five project
  workflows in `.claude/workflows` are in scope.

## 7. Context hygiene for the coordinator

- Keep reports short; put detail in files. Read files by section, not whole.
- After each milestone, write the state in one line per task into the progress log and into
  memory; if the session is compacted, the log is the source of truth.
- Prefer file paths and commit hashes in the log over prose.

## 8. The end

In the last four hours: stop dispatching new work, let the running tasks finish or stop them at
the watchdog's limit, run the suites, write the report, update memory, push. Then tell the owner
in a message of ten lines: what works now, what does not, where the report is.
