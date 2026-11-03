# Writes audit: Jira, Slack, Discord, GitHub (2026-11-03)

The owner, today: "When I start using this at work, we won't be doing any write-access to Jira or
Slack." This audit lists every code path that writes to Jira, Slack, Discord or GitHub across the
six repositories (main branches, read in place, nothing changed), what gates each, and whether a
read-only deployment can switch it off without a code change. GitHub writes (branches, pull
requests) stay allowed for the Supervisor's own changes.

"Off without code" means by configuration or by credentials alone. Tokens and `~/.config` were not
read.

## orchestra_2 (core)

No write path. The only POSTs are the metrics store's import (`orchestra/metrics/victoria.py:43`)
and PromQL queries (`orchestra/sources/transport.py:165`). No Slack, Jira, Discord or GitHub
client, no `git push`, no `gh`.

## orchestra-outbox

Every built-in sender is called from one place, `dispatch.py:102` (`sender.send`), only for a draft
in state `approved`. A kind is configuration (`[outbox.kinds.<name>]`). A built-in sender is usable
only when its system's table `[outbox.slack|github|jira]` exists (`config.py:180`; the shared
`accounts.toml` alone does not turn a system on, `config.py:135-138`). Approval is `always` by
default; `auto` only by an explicit entry (`config.py:231`, `service.py:106`). Approving a pull
request is refused everywhere (`actions.py`, `dispatch.py:93`).

| file:line | writes | system | gated today by | off without code? |
|---|---|---|---|---|
| `senders/slack.py:66` | `chat.postMessage` (senders `slack.message`, `slack.reply`) | Slack | the kind's approval; `[outbox.slack]` present | **Yes**: leave out `[outbox.slack]` (any kind naming it then fails the check) |
| `senders/jira.py:79` | `POST /issue/{key}/comment` (`jira.comment`) | Jira | approval; `[outbox.jira]` | **Yes**: leave out `[outbox.jira]` |
| `senders/jira.py:87` | `POST /issue/{key}/transitions` (`jira.transition`) | Jira | same | **Yes**, same |
| `senders/jira.py:93` | `POST /issue` (`jira.create`) | Jira | same | **Yes**, same |
| `senders/github.py:88` | `POST .../issues/{n}/labels` (`github.label`; a merge label needs the owner the first time per PR) | GitHub | approval; `[outbox.github]`; approval labels refused | Yes (not wanted off) |
| `senders/github.py:93` | `POST /repos/{r}/pulls` (`github.pr_open`) | GitHub | approval; `[outbox.github]` | Yes (not wanted off) |
| `senders/github.py:98` | `POST .../issues/{n}/comments` (`github.pr_comment`) | GitHub | approval; `/approve` and `/lgtm` refused | Yes (not wanted off) |
| `senders/github.py:110` | `POST /repos/{r}/issues` (`github.issue_create`) | GitHub | `owner_only`: always the owner, `auto` refused (`config.py:234`) | Yes (not wanted off) |
| `senders/script.py:63` | runs the kind's `command` with the approved draft on stdin: **any system, any token the script can read** | any | approval; the declared `action` is only `other`, `git.push`, `github.pr_*`. Nothing says which system a script writes to | **Only by not configuring script kinds.** Leaving out `[outbox.jira]` does not stop a script that writes to Jira |

No Discord sender exists.

Weak point: `[outbox]` lives in `orchestra.toml` and the owner's overlay, which the Supervisor's
`set_setting` writes. It is live at once through the overlay and committed for review afterwards
(`orchestra-agents/orchestra_agents/harness/tools.py:369`,
`config_change.py`, `setup_tools.py:75` labels `outbox.kinds`). So the Supervisor can add
`[outbox.slack]`, a new Slack kind or `approval = "auto"` on its own, and nothing refuses it.

## orchestra-workflows

The plugin only drafts to the Outbox. The program host runs arbitrary programs. The
`delivery_live` example adds direct writes of its own (the "stage", `machines/writer.py`) that skip
the Outbox's senders.

| file:line | writes | system | gated today by | off without code? |
|---|---|---|---|---|
| `orchestra_workflows/outbox.py:67` | `POST /drafts` to the local Outbox (an outbox step, `floor/drafts.py`) | Outbox (local) | the Outbox's gates above | Yes: leave out the kinds |
| `orchestra_workflows/programs/step.py:149` | runs a step's program (`machine.json` `spec.program`) with the env the spec names | any | nothing about writes. The program's own tokens decide | **No** switch. Only credentials |
| `orchestra_workflows/programs/relate_prs.py:72` | (GET only: reads a PR's branch and title) | GitHub read | — | n/a, not a write |
| `orchestra_workflows/define/write.py` | a local `workflow.json` file only | none | — | n/a |
| `examples/delivery_live/machines/writer.py:47-55` | `Writer.call`: any method, JSON, as the owner, with the **pollers' tokens** (`poller.toml`), not the Outbox's | Jira, GitHub | `require_clearance` (`writer.py:60`: `poller.toml` clearance `approved`, else loopback fakes only). That is a *read* clearance | Only by not running the example |
| `examples/delivery_live/machines/close_ticket.py:71` | `POST /issue/{key}/transitions` (to a done status) | **Jira** | runs as Outbox script kind `live.close_ticket`, `approval = "auto"` under `--scope tests` (`demo.py:221-222`); `--only-label orchestra-live-test` | No: it bypasses `[outbox.jira]` |
| `examples/delivery_live/machines/create_ticket.py:41` | `POST /issue` (a test ticket, assigned to the owner) | **Jira** | Outbox script kind `live.create_ticket`, `approval = "auto"` (`demo.py:223-224`) | No, same |
| `examples/delivery_live/demo.py:304`, `:311` | `POST /issue` and `PUT /issue/{key}/assignee` (`create_tickets`, test setup) | **Jira** | nothing beyond clearance; runs directly from `demo.py` | No (don't run it) |
| `examples/delivery_live/demo.py:330-331` | `PATCH` PR closed, `DELETE` ref (`--cleanup`) | GitHub | nothing; `workflows/` branches only | No |
| `examples/delivery_live/standing.py:239`, `:273` | `PATCH` PR closed, `DELETE` ref | GitHub | nothing | No |
| `examples/delivery_live/machines/review_stand_in.py:77` | `POST .../pulls/{n}/reviews` (a COMMENT review standing in for reviewers) | GitHub | `stand_in_review` setting | No |
| `examples/delivery_live/machines/sail_fake.py:146`, `:151-152`, `:166` | `PUT .../merge` (squash), label drop and add, `DELETE` ref | GitHub | nothing (fake SAIL on the test repo) | No |
| `examples/delivery_live/machines/live_worker.py:55` | `git push -f origin HEAD:refs/heads/<branch>` | GitHub | nothing (item branch) | No |
| `examples/delivery_live/demo.py:219-229` | configures Outbox kinds: `live.pr_open` (auto), `live.sail` (auto), `live.nudge` (always), `live.close_ticket`, `live.create_ticket`, and, when a Slack token file exists, `[outbox.slack]` + `live.slack` (`slack.message`, **auto**) | GitHub, Jira (via script), Slack | the owner's 2026-11-01 approval for this example | Slack: yes (no token file → no `[outbox.slack]`); Jira: no |
| `examples/delivery_live/machines/slack_notify.py:144` | drafts `live.slack` lines to the Outbox (it reads Slack itself: `conversations.list`, a form POST, `:105`) | Slack (via Outbox) | Outbox kind `live.slack`, auto | Yes |
| `examples/delivery_live/machines/review_nudger.py` | drafts `live.nudge` (PR comment) | GitHub (via Outbox) | always the owner | Yes |

The other examples write only to local fakes, a fake outbox or local bare repositories. `slack_queues/real.py` and `discord.py` only read.

## orchestra-agents

| file:line | writes | system | gated today by | off without code? |
|---|---|---|---|---|
| `orchestra_agents/supervisor_pr.py:262` → `orchestra-scm` push | pushes `orchestra/supervisor` | GitHub | `[scm]` set and a remote; scm refuses main, master, base and default | Yes: no `[scm]` |
| `supervisor_pr.py:260` (Outbox **not** installed) | opens the PR directly (`scm.open_pr` → `create_pull`) | GitHub | `[scm]` only. **Bypasses the Outbox** | Yes: no `[scm]` |
| `supervisor_pr.py:263-273` (Outbox installed) | drafts `supervisor.pull_request` (`github.pr_open`) | GitHub (via Outbox) | the Outbox kind's approval | Yes |
| `supervisor_pr.py:298-311` (`_update`) | rewrites an open PR's title and body (`update_pr` → `PATCH`), **with or without the Outbox** | GitHub | `[scm]` only | Yes: no `[scm]` |
| `orchestra_agents/upstream.py:66` | drafts `upstream.issue` (`github.issue_create`) | GitHub (via Outbox) | owner-only kind | Yes |
| `orchestra_agents/harness/tools.py:369` (`set_setting`) | writes `[outbox]`, kinds included, live through the overlay | config (it opens writes elsewhere) | the commit and PR are reviewed **after** it is already live | No |
| agent sessions' shell (`push_guard.py`, `harness/bounds.py`) | anything a session's commands do with the owner's credentials | any | workers: `git push` and `gh` writes are blocked (`push_guard.py:69-78`), unless `[agents] allow_push`. **The Supervisor is exempt** (`push_guard.py:42`). Curl to Slack or Jira is not blocked for workers; for the Supervisor it is denied by Claude Code rules that its own docstring calls "no security boundary" | No. Only credentials and the OS user |

No agent tool posts to Slack or comments on or moves a Jira ticket. `demo/run_task_loop.py:139`
pushes to a local bare `origin` only.

## orchestra-bridges

| file:line | writes | system | gated today by | off without code? |
|---|---|---|---|---|
| `orchestra_bridges/kits/client.py:242-244` | **none**: GET, or POST of a form; any other method or a JSON body raises `KitError` | — | the client | n/a |
| `kits/fakes/*.py` (`base.py:133-140`, `github.py:238-300`, `jira.py`) | accept writes, on loopback only | fakes | — | n/a |

Latent gap: a form POST is allowed so PromQL can send long queries (`promql.py:105`, `:151`).
Slack's Web API takes form posts, so `client.post("/api/chat.postMessage", form=...)` would be a
write that passes the guard. Nothing calls it today. Restricting `post` to an allowlist of read
paths (or of hosts the kit declares queryable) would close it.

## orchestra-scm

| file:line | writes | system | gated today by | off without code? |
|---|---|---|---|---|
| `orchestra_scm/git.py:70-76` (`push_branch`) | `git push` of one branch (`--force` optional) | GitHub | `guard.refuse_protected`: never main, master, base or default | Yes: no `[scm]` |
| `orchestra_scm/github/api.py:123-131` (`create_pull`) | `POST /repos/{r}/pulls` | GitHub | caller (`branch_pr.propose(open_pr=True)`) | Yes: no `[scm]` |
| `orchestra_scm/github/api.py:134-139` (`update_pull`) | `PATCH /repos/{r}/pulls/{n}`, title and body only | GitHub | caller | Yes: no `[scm]` |

Nothing else: no merge, label, review or ref deletion (`api.py:1-6`). `protect` adds the item's
base to the refused names. `land` only reads.

## Counts

| system | write paths | through the Outbox's own sender | other |
|---|---|---|---|
| Jira | 7 | 3 (`jira.comment`, `.transition`, `.create`) | 4 in `delivery_live`: 2 run as Outbox **script** kinds (`close_ticket`, `create_ticket`), 2 run directly (`demo.py` setup) |
| Slack | 2 | 2 (`slack.message`, `slack.reply`, one call site) | none |
| Discord | 0 | — | — |
| GitHub | 17 | 4 (label, PR open, PR comment, issue) | 3 in orchestra-scm (push, PR open, PR update) used by the Supervisor; 10 in the `delivery_live` stage |
| any system | 3 | 1 (the Outbox's script sender) | the program host's programs; agent sessions' shells |

## Answers

### 1. Does every outbound write go through the Outbox?

No. The Outbox's built-in senders are well gated, but these bypass them:

- **`delivery_live`'s stage** (`writer.py`). The Jira ticket setup in `demo.py:304/311`, and on
  GitHub `sail_fake.py`, `review_stand_in.py`, `live_worker.py:55`, `demo.py --cleanup` and
  `standing.py`. They use the pollers' tokens directly.
- **Outbox script kinds that write to Jira** (`close_ticket.py:71`, `create_ticket.py:41`). These go
  through the Outbox's approval, both `auto` in the example. But the Outbox cannot tell which
  system a script writes to, so leaving out `[outbox.jira]` does not stop them. This is the
  bypass that matters most for the work deployment: it looks like the Outbox gates it, and only
  the approval does.
- **orchestra-scm, called by the Supervisor.** The push always goes direct. The PR is opened direct
  when the Outbox is not installed (`supervisor_pr.py:260`), and an open PR's title and body are
  always edited direct (`:298-311`). These are GitHub only, so they are allowed.
- **The program host** (`programs/step.py:149`) and **agent sessions' shells**. Nothing limits
  what their programs or commands write. The Supervisor is exempt from the push guard. A worker's
  `curl` is not blocked.
- **`set_setting`** can add a Slack or Jira kind with `approval = "auto"`, live at once. It is not
  a write, but it changes what the Outbox will write.

Today a read-only deployment gets most of the way with no code change: leave out `[outbox.slack]`
and `[outbox.jira]`, configure no script kind, do not run `delivery_live`. The real hard backstop
needs no code either: **read-only credentials** (a Slack bot token without `chat:write`, a Jira
account or PAT without write permission). That stops every path above, bypasses included. Nothing
stops the Supervisor from adding `[outbox.slack]` back.

### 2. The smallest change that makes read-only the default for Jira, Slack and Discord

**The setting:** `writes`, a top-level key in the owner's `accounts.toml`
(`~/.config/orchestra/accounts.toml`, read by `orchestra_outbox/accounts.py`), with the default
`["github"]` when it is absent:

```toml
writes = ["github"]                     # the default; at home: ["github", "jira", "slack"]
```

**Why there**, and not in the other two places named:

- **Not `[outbox]` in `orchestra.toml` or the overlay.** The Supervisor's `set_setting` writes
  both, live at once, so it could flip the switch itself. `accounts.toml` is the owner's file,
  outside every repository and state directory. No Supervisor tool writes it, and its bounds deny
  `~/.config`.
- **Not the bridges kit settings.** Kits already never write. The writes are the Outbox's and the
  scripts'.
- **Not the Supervisor's role.** The Supervisor does not send. A role list would not cover the
  floor, the program host or the scripts.

**What reads it** (about 40 lines plus tests):

1. `accounts.py`: `Accounts.writes(system) -> bool`. True for `github` by default; true for any
   other system only when it is listed. A closed list, so a future Discord sender is off by
   default too.
2. `config.py` `problems()`:
   - Refuse `[outbox.slack]` or `[outbox.jira]` when the system is not writable and its `api` is
     not a loopback fake. The loopback exemption is the same one `_api` already makes, and it keeps
     every test and dry run working.
   - Give a script kind a required key `writes_to`: one of `slack`, `jira`, `github`, `discord`,
     `none`. Refuse it when that system is not writable. This is declared, like `action`, because a
     script cannot be read for intent.
3. `dispatch.py` `attempt()`: check again at send time, `refused:read_only:<system>` (permanent),
   as it does for `refused:pr_approval`. This covers an `accounts.toml` edited while drafts wait.
4. `script.py`: pass `OUTBOX_WRITES=<comma list>` to the script, so a well-behaved script
   (`delivery_live/writer.py`) can refuse a non-loopback write itself. Two lines in
   `writer.Writer.call`: refuse a non-GET to a non-local base unless the system is in
   `Accounts.load().writes`. Check at call time, not at construction.

This leaves GitHub writable: the Outbox's GitHub kinds, orchestra-scm's push and PRs, and the
Supervisor's branch. Pair it with read-only Jira and Slack credentials at work. The switch makes
read-only the default and refuses clearly; the credentials are the boundary against the program
host and the shells, which no Outbox setting reaches.

### 3. What breaks under that default, and how each opts in

- **orchestra-outbox tests: nothing**, because every test's Slack and Jira `api` is a loopback
  fake (`tests/conftest.py:25-60`). New tests should cover a non-loopback api refused by default,
  allowed with `writes`, a script kind with no `writes_to`, and the refusal at send time. If the
  loopback exemption is dropped, `conftest.py`, `test_autonomy`, `test_rate_limits`, `test_canary`,
  `test_sensitive`, `test_config_check`, `test_idempotent`, `test_jira_and_script` and
  `test_accounts` break. They opt in with one line in the autouse `accounts_dir` fixture
  (`conftest.py:69-76`): write `accounts.toml` with `writes = ["github", "jira", "slack"]`.
- **`delivery_live` live run (real Jira board and Slack channel): breaks.**
  - `live.close_ticket` and `live.create_ticket` need `writes_to = "jira"` in
    `demo.py:221-224`.
  - The owner's `accounts.toml` needs `writes = ["github", "jira", "slack"]`. That one line is the
    opt-in for `live.slack` (`[outbox.slack]`) and for `writer.py`'s `create_tickets` and
    `--cleanup` Jira writes too.
  - `--dry-run` uses loopback fakes and is unaffected.
- **orchestra-workflows tests.**
  - `test_example_delivery_live_settings.py::test_the_outbox_names_the_owner_so_approvals_carry_the_person_id`
    runs the Outbox's `check` on the demo's real-API config. It breaks until `writes_to` is added
    and the test points `ORCHESTRA_ACCOUNTS` at a temporary `accounts.toml` that lists jira and
    slack.
  - `test_data_center_the_writer_sends_the_pat_as_bearer` only builds the writer, so it passes if
    the check is at call time.
  - The other `test_example_delivery_live*` tests, and the e2e examples, use loopback fakes and are
    unaffected.
- **orchestra-agents, orchestra-scm, orchestra-bridges and the core: nothing.** Their writes are
  GitHub or none. `test_supervisor_pr.py` and `test_machine_sends.py` read GitHub kinds only. The
  live integration test (`tests/live/test_integrate_live.py`) only reads Jira.
