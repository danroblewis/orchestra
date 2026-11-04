# Setup

You give the Supervisor (an AI agent) a few details; it does the setup. You watch.

## 1. What you need

- macOS or Linux, `git` and [uv](https://docs.astral.sh/uv/).
- GitHub access to the plugins: `danroblewis/orchestra-agents` (the Supervisor) and
  `danroblewis/orchestra-bridges` (the collectors' kits) are private; Orchestra itself is public.
  Run `gh auth login && gh auth setup-git` once.
- [Pi](https://github.com/badlogic/pi-mono) or [Claude Code](https://docs.claude.com/en/docs/claude-code)
  installed and logged in once by hand (`pi` then `/login`, or `claude`).
- The token files you already have for your systems (`chmod 600`).

## 2. Install

```bash
uv tool install 'orchestra[sd,dev] @ git+https://github.com/danroblewis/orchestra@main' \
  --with 'orchestra-agents @ git+https://github.com/danroblewis/orchestra-agents@main' \
  --with 'orchestra-bridges @ git+https://github.com/danroblewis/orchestra-bridges@main'
uv tool update-shell        # then open a new terminal
```

## 3. A project directory

```bash
mkdir ~/my-orchestra && cd ~/my-orchestra
git init -q                 # if needed
orchestra init
```

## 4. The Supervisor's settings

Append to `orchestra.toml`:

```toml
[agents]
harness = "pi"
provider = "anthropic"
model = "sonnet"
tools_via = "bash"          # tools from its shell; no MCP server
serves = []                 # the Supervisor only
review_usd_per_day = 2.0    # daily cap on its own initiative
```

With Claude Code: `harness = "claude_code"`, no `provider`. Your chat turns are not capped.

## 5. Start it

```bash
orchestra run               # terminal 1; starts the Supervisor
orchestra web               # terminal 2; open its "log in" link
```

Open the **Agents** page: the Supervisor's chat.

## 6. The short conversation

Tell it:

- which systems to connect (a metrics store, a tracker, a chat, alerting);
- where each token file is (the path, never the token);
- which part of each it may read (a namespace, a project, the channels);
- that it must not write anywhere outside Orchestra.

For example: *"Read our metrics store at `https://<store>/api`, token in
`~/.config/orchestra/metrics-token`, only `{namespace="shop"}`; our tracker's project OPS, token in
`~/.config/orchestra/tracker-token`. Write nothing anywhere."*

It asks for anything else it needs.

## 7. Watch

On its own, the Supervisor:

- sets up each store as a source and each other system as a read-only poller, tested on a fake,
  asking your yes before the first real read;
- explores within your scope, under each store's rate and daily caps;
- proposes changes (a wider match, names, machines) and applies each on your word, with its reason;
- reports what it set, what the model found, and what is left out.

Watch the chat, **Dynamics** (the model; its run drawer lists each discovery) and **Instruments**
(what is read, and its last error). Raise problems with the Supervisor in the chat.

## 8. Stop

Ctrl-C both terminals. To remove everything: `uv tool uninstall orchestra`, then delete the
directory and `~/.orchestrator/<key>/` (`orchestra init` printed the key).

The Supervisor's manual: [orchestra/guide.md](orchestra/guide.md).
