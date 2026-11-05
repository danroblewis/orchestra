# Setup

You give the Supervisor (an AI agent) a few details; it does the setup. You watch.

Every command you need is in this file. Run them in order, in a terminal, from the top. To start
again from nothing, run section 9, then this file again from section 2.

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
  --with 'orchestra-workflows @ git+https://github.com/danroblewis/orchestra-workflows@main'
uv tool update-shell        # the first time only; then open a new terminal
```

Run the same command to upgrade. Stop Orchestra first (section 8), and start it again after.

## 3. Let the Supervisor leave Claude Code's sandbox

Until the agents plugin has its `[agents] sandbox_escape` setting, this patch lets the Supervisor
rerun a command outside Claude Code's sandbox when the sandbox blocks something Orchestra needs
(its own tools, a source reading its token file). Run it after every install or upgrade. It is
safe to run twice. If it prints "expected one match", stop: the plugin changed, and the patch
needs updating.

```bash
cat > /tmp/escape.py <<'EOF'
import re, sys, pathlib
pkg = pathlib.Path(sys.argv[1])
NEW = ("- **When Claude Code's sandbox blocks a command Orchestra needs** (its tool command, a source's probe reading "
       "its token file), rerun it outside the sandbox (`dangerouslyDisableSandbox: true`) and say so in one line. "
       "The owner allows this. Never print a token.\n")
def edit(rel, old, new, done, regex=False):
    p = pkg / rel; s = p.read_text()
    if done in s:
        print("already changed", rel); return
    n = len(re.findall(old, s, re.S)) if regex else s.count(old)
    if n != 1:
        sys.exit(f"{rel}: expected one match, found {n}; stop here")
    s = re.sub(old, lambda m: new, s, flags=re.S) if regex else s.replace(old, new)
    p.write_text(s); print("changed", rel)
edit("harness/sandbox.py", '{"sandbox": out | {"allowUnsandboxedCommands": False}}', '{"sandbox": out}', '{"sandbox": out}\n')
edit("harness/claude_code.py", "return sandbox.BLOCKED.report(found)", "return None  # the owner allows leaving the sandbox",
     "the owner allows leaving the sandbox")
edit("prompts/supervisor_core.md", r"- \*\*You never rerun a command outside the sandbox\.\*\*.*?\n(?=\n|- \*\*|#)", NEW,
     "When Claude Code's sandbox blocks a command Orchestra needs", regex=True)
RERUN = "Rerun this command outside the sandbox (dangerouslyDisableSandbox: true); the owner allows it. If that is refused too, tell the owner"
edit("local_http.py", "Never rerun this command outside the sandbox: stop, and tell the owner", RERUN, "the owner allows it. If that is refused")
edit("sandbox_writes.py", "Never rerun this command outside the sandbox: stop, and tell the owner", RERUN, "the owner allows it. If that is refused")
print("done: the Supervisor may now leave the sandbox")
EOF
PY="$(uv tool dir)/orchestra/bin/python"
"$PY" /tmp/escape.py "$("$PY" -c 'import orchestra_agents, os; print(os.path.dirname(orchestra_agents.__file__))')"
```

If your company's managed Claude Code settings forbid leaving the sandbox, Claude Code refuses
anyway and the Supervisor tells you what to ask IT for.

## 4. The project

Orchestra works on a git repository: your own, or an empty one made for it. Either way, keep
Orchestra's files out of the repository: `--clean` writes nothing in it, and the private overlay in
Orchestra's state directory holds the whole configuration.

```bash
cd <your repository>        # or: mkdir ~/my-orchestra && cd ~/my-orchestra && git init -q
OVERLAY=$(orchestra init --clean | sed -n 's/^  config: \(.*\) (the private overlay.*/\1/p'); echo "$OVERLAY"
```

It prints the overlay's path, `~/.orchestrator/<key>/orchestra.local.toml`, and keeps it in
`$OVERLAY` for the next step. If it prints nothing, run `orchestra init --clean` alone to see why.

## 5. The Supervisor's settings

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

With Pi instead: `harness = "pi"`, `provider = "anthropic"`, `model = "claude-sonnet-5"` (the id Pi
lists for Sonnet).

To stop all spending at once but keep Orchestra observing, set `harness = "dummy"` and restart
`orchestra run`. The Agents page also has "Pause the Supervisor's own initiative until tomorrow";
your chat keeps working while it is paused.

## 6. Start it

In two terminals, from the project directory:

```bash
orchestra run
```

```bash
orchestra web
```

Open the "log in" link `orchestra web` prints, then the **Agents** page: the Supervisor's chat.

## 7. The first message

Fill in the values in angle brackets and send it as one message:

> Set up observation only, in this order, and ask me before anything that writes outside this machine.
>
> 1. **The repository must stay clean.** Every setting goes in the private overlay. Every machine,
>    workflow and resource kind goes in the state directory. Write nothing in the repository.
> 2. **The metrics store**, a Prometheus API, read-only: `<the store's URL>`, bearer token in
>    `<path to its token file>`. Match only `<a selector, e.g. {__name__=~"queue_.*", env="prod"}>`.
>    Never a selector that matches everything. Keep the rate at 1 request a second, with a daily cap.
>    Name the stocks with general naming rules, not one by one. Ask me before widening the match.
> 3. **The tracker** (Jira Data Center), read-only, through the bridges' Jira reader:
>    `<Jira base URL>`, token in `<path to its token file>`, scope `<your team's JQL, e.g. project = ABC>`.
>    One Jira machine only. Never write to Jira or Slack.
> 4. **Workflows**: make each ticket in that scope an item, with steps that follow its status
>    category (to do, in progress, done). Only observe; nothing is offered to any role.
> 5. **Keep your own wake-ups to trouble signals.** Add no duty that wakes on routine events.
>    Use delegate for long surveys.
>
> When each step works, tell me in one or two sentences what you set up and what I should see on
> the Core, Dynamics and Items pages.

Leave out the parts you don't have. Add Slack, alerting or another store the same way: its
address, its token file's path, and the part of it the Supervisor may read.

## 8. Watch, and stop

- **Core**: each store and whether it is reachable.
- **Dynamics**: the model; its run drawer lists each discovery and what it cost.
- **Items**: the tickets and where each one is.
- **Agents**: the chat, what wakes the Supervisor, and what it spent today.

Raise problems with the Supervisor in the chat. To stop, press Ctrl-C in both terminals.

## 9. Start over from nothing

Stop both terminals first. Then, from the project directory:

```bash
KEY=$(basename "$(git rev-parse --show-toplevel)")-$(python3 -c "import hashlib,subprocess;print(hashlib.sha256(subprocess.check_output(['git','rev-parse','--show-toplevel']).decode().strip().encode()).hexdigest()[:8])")
echo "removing ~/.orchestrator/$KEY"; rm -rf ~/.orchestrator/"$KEY"
uv tool uninstall orchestra
```

This removes Orchestra's state for this project only: the overlay, the model, the machines, the
records and the Supervisor's sessions. Your token files and your repository are untouched. Then
start again at section 2.

The Supervisor's manual: [orchestra/guide.md](orchestra/guide.md).
