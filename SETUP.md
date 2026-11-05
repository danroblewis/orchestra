# Setup

You give the Supervisor (an AI agent) a few details; it does the setup. You watch.

Every command you need is in this file. Run them in order, in a terminal, from the top. To start
again from nothing, run section 8, then this file again from section 2.

## 1. What you need

- macOS or Linux, `git` and [uv](https://docs.astral.sh/uv/).
- The GitHub CLI logged in, so the plugins install: `gh auth login`, then `gh auth setup-git`. The
  Workflows plugin's repository is private; the others are public.
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (or [Pi](https://github.com/badlogic/pi-mono))
  installed and logged in once by hand: run `claude` (or `pi`, then `/login`).
- The token files for your systems, each `chmod 600`, outside the repository (for example in
  `~/.config/orchestra/`). You give the Supervisor their paths, never the tokens.

## 2. Install

```bash
uv tool install --force 'orchestra[sd,dev] @ git+https://github.com/danroblewis/orchestra@main' \
  --with 'orchestra-agents @ git+https://github.com/danroblewis/orchestra-agents@main' \
  --with 'orchestra-bridges @ git+https://github.com/danroblewis/orchestra-bridges@main' \
  --with 'orchestra-workflows @ git+https://github.com/danroblewis/orchestra-workflows@main' \
  --with 'orchestra-scm @ git+https://github.com/danroblewis/orchestra-scm@main'
uv tool update-shell        # the first time only; then open a new terminal
```

Run the same command to upgrade. Stop Orchestra first (section 7), and start it again after.

The scm plugin turns a worker's branch into a GitHub pull request. Installed, it does nothing until
you ask the Supervisor to set it up (an `[scm]` section, with a GitHub token file that can open
pull requests). Leave it unset while you only observe.

## 3. The project

Orchestra works on a git repository: your own, or an empty one made for it. Either way, keep
Orchestra's files out of the repository: `--clean` writes nothing in it, and the private overlay in
Orchestra's state directory holds the whole configuration. This is about Orchestra's own files only.
Workers that change your project's code later do it in their own worktrees, in the state directory,
on their own branches (`workflows/<item>-<hash>`); your checkout is never touched, and nothing is
pushed unless you allow it.

```bash
cd <your repository>        # or: mkdir ~/my-orchestra && cd ~/my-orchestra && git init -q
OVERLAY=$(orchestra init --clean | sed -n 's/^  config: \(.*\) (the private overlay.*/\1/p'); echo "$OVERLAY"
```

It prints the overlay's path, `~/.orchestrator/<key>/orchestra.local.toml`, and keeps it in
`$OVERLAY` for the next step. If it prints nothing, run `orchestra init --clean` alone to see why.

## 4. The Supervisor's settings

```bash
cat >> "$OVERLAY" <<'EOF'

[agents]
harness = "claude_code"
model = "sonnet"
tools_via = "bash"          # tools from its shell; no MCP server
serves = []                 # the Supervisor only, for now
review_usd_per_day = 1.0    # what its own initiative (reviews, notices) may spend a day
chat_usd_per_day = 5.0      # what your chat turns may spend a day
EOF
```

The Supervisor may rerun a command outside Claude Code's sandbox when the sandbox blocks
something Orchestra needs, and says so (`sandbox_escape = true`, the default). Set
`sandbox_escape = false` if your company requires the sandbox; the Supervisor then stops at a
blocked command and names the setting to ask IT for.

With Pi instead: `harness = "pi"`, `provider = "anthropic"`, `model = "claude-sonnet-5"` (the id Pi
lists for Sonnet).

To stop all spending at once but keep Orchestra observing, set `harness = "dummy"` and restart
`orchestra run`. The Agents page also has "Pause the Supervisor's own initiative until tomorrow";
your chat keeps working while it is paused.

## 5. Start it

From the project directory:

```bash
orchestra run --web
```

It runs the host and the web UI together, and Ctrl-C stops both. Open the "log in" link it prints,
then the **Agents** page: the Supervisor's chat. (`orchestra run` and `orchestra web` in two
terminals do the same; `--port` picks another port than 8000.)

## 6. The first message

Fill in the values in angle brackets and send it as one message:

> Set up observation only, in this order. Don't ask me; decide and tell me what you did. The one exception: ask before anything that writes outside this machine.
>
> 1. **Keep Orchestra's own files out of the repository.** Every setting goes in the private overlay.
>    Every machine, workflow and resource kind goes in the state directory. This is about Orchestra's
>    files only: code changes to the project come later, from workers in their own worktrees and
>    branches.
> 2. **The metrics store**, a Prometheus API, read-only: `<the store's URL>`, bearer token in
>    `<path to its token file>`. Match only `<a selector, e.g. {__name__=~"queue_.*", env="prod"}>`.
>    Never a selector that matches everything. Keep the rate at 1 request a second, with a daily cap.
>    Name the stocks with general naming rules, not one by one. Widen or narrow the match yourself
>    as discovery needs, within `<a wider selector you may survey, e.g. {env="prod"}>`.
> 3. **The tracker** (Jira Data Center), read-only, through the bridges' Jira reader:
>    `<Jira base URL>`, token in `<path to its token file>`, scope `<your team's JQL, e.g. project = ABC>`.
>    One Jira machine only. Set its `history = "full"` and `since = "7d"`, so the first run fills in
>    the whole history of every ticket updated in the last 7 days, finished ones included. Set
>    `content = ["summary", "description", "comments"]` so the items show each ticket's title,
>    description and comments. Never write to Jira or Slack.
> 4. **Workflows**: make each ticket in that scope an item, with steps that follow its status
>    category (to do, in progress, done). Only observe; nothing is offered to any role.
> 5. **Keep your own wake-ups to trouble signals.** Add no duty that wakes on routine events.
>    Use delegate for long surveys.
>
> When each step works, tell me in one or two sentences what you set up and what I should see on
> the Core, Dynamics and Items pages.

Leave out the parts you don't have. Add Slack, alerting or another store the same way: its
address, its token file's path, and the part of it the Supervisor may read.

## 7. Watch, and stop

- **Core**: each store and whether it is reachable.
- **Dynamics**: the model; its run drawer lists each discovery and what it cost.
- **Items**: the tickets and where each one is.
- **Agents**: the chat, what wakes the Supervisor, and what it spent today.

Raise problems with the Supervisor in the chat. To stop, press Ctrl-C.

## 8. Start over from nothing

Stop Orchestra first (Ctrl-C). Then, from the project directory:

```bash
KEY=$(basename "$(git rev-parse --show-toplevel)")-$(python3 -c "import hashlib,subprocess;print(hashlib.sha256(subprocess.check_output(['git','rev-parse','--show-toplevel']).decode().strip().encode()).hexdigest()[:8])")
echo "removing ~/.orchestrator/$KEY"; rm -rf ~/.orchestrator/"$KEY"
uv tool uninstall orchestra
```

This removes Orchestra's state for this project only: the overlay, the model, the machines, the
records and the Supervisor's sessions. Your token files and your repository are untouched. Then
start again at section 2.

The Supervisor's manual: [orchestra/guide.md](orchestra/guide.md).
