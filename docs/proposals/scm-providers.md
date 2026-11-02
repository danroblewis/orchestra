# Proposal: SCM providers, a library for the places code is changed

Status: proposal, 2026-11-02. Nothing built. It answers the owner's third answer of 2026-11-02
(`docs/roadmap/GOAL-2026-11-02-second-half.md`, the 10:36Z entry) and takes up decision D8
(git-spice is acceptable), goal G7 (`docs/roadmap/goals.md`), the memory "PR trees" (the owner's
work uses the `gh-stack` gh extension) and `corporate-workflow.md` R1–R6. No invariant of
`AGENTS.md` changes; the Workflows plugin's SPEC §6 does (§7 below). This document's decisions are S1–S12; a `Dn` is the owner's (`docs/roadmap/decisions.md`).

## 1. The question, and what is wrong today

The owner: "'item' is a generic idea, a 'task' is a type of 'item' … the worktrees may be part of
an SCM or VCS library, but i dont know where it should go or what interface it should have."

Today the Workflows plugin, an engine of abstract items, ships one task-shaped thing: the built-in
`worktree` kind. Its name is special-cased in the parser (`orchestra_workflows/resources/kinds.py`:
`WORKTREE`, `WORKTREE_KEYS`, `Kind.builtin`, the default added in `load`), its git steps are the
floor's own (`resources/worktree.py`), and the item's branch name is the floor's
(`resources/ops.py`, `branch_for`: `workflows/<item>-<hash>`). Three other places depend on that
name: the agents' worker finds its workspace by `kind == "worktree"` (`orchestra_agents/floor.py`,
`workspace`), the scripted reference machine does the same
(`orchestra_workflows/machines/scripted.py`, `worktree`), and the live example reads items back from
the floor's branch names (`examples/delivery_live/machines/live.py`, `item_of`). The task_loop's gate
reads `ORCHESTRA_RESOURCE_WORKTREE` (`examples/task_loop/target/.orchestra/machines/merge_gate/gate.sh`).

Everything past the worktree is outside the plugin, scattered: the live worker pushes
(`examples/delivery_live/machines/live_worker.py`, `git push -f`), the Outbox opens the pull request
(`orchestra_outbox/kinds.py`, `github.pr_open`), the delivery workflows wait on `github.pr.*` events
(`examples/delivery_live/.../workflow.json`, `examples/delivery_sail/.../workflow.json`). A stack, a
second strategy or a company's description has nowhere to go.

## 2. Where it lives

**S1. A library, `orchestra-scm`, shaped like `orchestra-bridges`.** Providers, fakes, templates and
a scaffold; a plugin entry point only for its guide and its check, with no processes, no collectors
and no machines (as `orchestra_bridges/plugin.py`). What runs is written into the owner's repository
by the scaffold (`orchestra scm scaffold …`, as `orchestra bridges scaffold`): a resource kind, the
programs a workflow's steps name, and a watcher. Those are the repository's; the library is what
they are built from. It depends on Orchestra's core and on `orchestra-bridges` (its client, poller
and fake GitHub, `orchestra_bridges/kits/`), never on `orchestra-workflows`: it speaks the
resource-kind contract only by commands and environment, so any program that needs a place to
change code (the Supervisor's patches, `orchestra_agents/patching.py`, later) can use it without the
floor.

**S2. The Workflows plugin keeps only the generic kind** (SPEC §6: a name, a capacity, make, reset,
release) and ships no worktree kind. `resources/worktree.py`, the `builtin` branches of
`resources/ops.py`, `WORKTREE*` in `kinds.py`, `branch_for` and the guide's worktree section
(`orchestra_workflows/guide.md`) move to `orchestra-scm`, with the seven requirements of SPEC §6,
which become that library's SPEC.

**S3. The kind is named `workspace`**, not `worktree`: what a step needs is a place to change code,
and a provider may make it as a worktree, a clone or a sparse checkout. A step says
`needs: ["workspace"]`; the provider is a setting of the workflow, never a kind.

## 3. The provider interface

**S4. Five operations, every provider:**

| Operation | What it means | How it reaches the floor |
|---|---|---|
| **claim** a workspace for an item | a clean checkout on the item's branch, placed on its base | the kind's make and reset |
| **propose** the change for review | the item's commits made visible to reviewers | a program step; `scm.change.proposed` |
| **learn** the review's outcome | approvals, requested changes, checks | the watcher's events |
| **land** the change | it reaches the base | a program step, or the company's act; `scm.change.landed` |
| **release** the workspace | detached, its branch kept | the kind's release |

**S5. Claim and release are not events.** the request named `scm.workspace.claimed`; I propose
none. Claiming is the floor's act, already recorded (`resources/pool.py`), announced in `offer.made`'s
`resources` and measured (`floor_resources{kind, state}`, SPEC §6). The kind's commands run inside
the floor, a provider's process: an event from them would be published by infrastructure, which rule
2 and D19 forbid. The floor never waits on its own claim.

**S6. The change's events**, each with the item as `subject`, from the machine that acted:

| Event | Published by | `data` |
|---|---|---|
| `scm.change.proposed` | the proposing program (`scm_propose/1`) or the Outbox, whoever opened it | `provider`, `change` (a number or a commit), `url`, `head`, `base`, `parent` (a stack's) |
| `scm.change.updated` | whoever pushed: a rework, a restack | `change`, `head`, `why` (`rework`, `restack`) |
| `scm.change.checked` | the watcher, as the CI's bot (`bot.github.actions`) | `change`, `head`, `check`, `conclusion` |
| `scm.change.reviewed` | the watcher, as the reviewer (`person.github.<account>`) | `change`, `head`, `verdict` (`approved`, `changes_requested`, `commented`) |
| `scm.change.landed` | whoever landed it: the land program, or the watcher as the merger (SAIL's bot) | `change`, `commit` on the base |
| `scm.change.abandoned` | whoever closed it | `change` |

The watcher is a relay built on the bridges' poller (`orchestra_bridges/kits/poller.py`): it knows the
items' changes by the provider's branch naming and publishes as the person or bot who acted, never
as itself (the bridges' rule, `orchestra-bridges/README.md`). It relays only those changes; the
general GitHub relay skips them, so one act is never on the bus twice. The cost, said plainly: an
item's pull request is `scm.change.reviewed`, everyone else's pull request is `github.pr.approved`.
The gain is that a workflow waits on one vocabulary whatever the provider, and a `head` equality
(SPEC §7, `done_when` with an item field) keeps stale results from counting.

**S7. What each provider does differently:**

| | Branch + pull request | GitHub stacks (`gh-stack`) | git-spice | Trunk + flag |
|---|---|---|---|---|
| claim | a branch off `origin/<base>` | off the parent item's branch | `gs branch create` on the parent | a checkout of the base, no item branch |
| propose | push the branch, open one PR | push, open the PR on the parent's branch | `gs branch submit` | commit to the base behind a flag, push |
| updated | a push | the stack's restack, every child | `gs upstack restack`, then submit | none |
| reviewed | the PR's reviews | per PR | per PR | none, or after the fact |
| land | the company's merge, or a merge program | bottom first; children restacked onto the base | `gs repo sync` after the merge | at propose: `proposed` and `landed` together |

Stacks follow `corporate-workflow.md`: each PR's branch based on its parent's and targeting it (R1;
not `ghstack`, one commit per PR, "never that"), several stacks at once (R2), retesting every branch
that changes (R6). The **parent** is the planner's: it sets the item fact `stack_on` (another item),
and the provider keeps the branch graph in its own state (`<state>/scm/`, rule 5), apart from the
item graph, as the owner asked ("the branch structure should still be tracked separately from the
task structure", memory "PR trees"). A child whose parent landed or changed is restacked by the
`scm_restack` program, on the workflow's `on` for its parent's `scm.change.landed` or `updated`.

**The counter-example earns its place:** trunk-based work has no review between propose and land,
and its release is a flag system's event, not this library's. So the verbs are propose, learn and
land, never push, open and merge; and each provider lists the events it can produce. A packaged
workflow lists the events it waits on, and the scaffold refuses to pair it with a provider that
never produces one. A hand-written definition that waits anyway reaches its `within` guard and
attention, as any wait on an absent event does.

**S8. A workflow names the provider, never a command:** `[workflows.settings.<workflow>] scm =
"git_spice"`, read through `project.config` (rule 10), passed to the programs as an argument, and
read by the kind's reset. Two workflows with different providers on one repository share one
workspace pool: a workspace is a checkout, and only where the branch is placed differs.

## 4. Pull request descriptions, and the review workflow

**S9. One description template per company and repository**: markdown with `$field` placeholders,
the Outbox's template language (`orchestra_outbox/templates.py`: `string.Template`, a missing field
refuses the draft). It starts from the repository's own `.github/pull_request_template.md` when it
has one, and adds the company's sections. It is filled from the item's facts (the ticket and its
link, the title, the commit, the stack's parent and children, the tests the verifier ran), and marks
the places a human must write by hand: `<!-- by hand: why -->`, `<!-- by hand: risk and rollback -->`,
`<!-- by hand: testing done -->`. The worker drafts those places (§5); the description goes out
only as an Outbox draft (`github.pr_open`, or an edit of an open one), where the owner reads it
before it is sent under the owner's approval settings. A draft with a by-hand mark still empty is
refused by the template, naming the section.

**S10. The review workflow is a definition, packaged by the library** (through
`orchestra_workflows.packages`, SPEC §8), with settings, never code: `pr_review`, steps propose
(program `scm_propose`, or the Outbox when the provider may not push, §8 Q3), checks (outside,
`done_when` `scm.change.checked` with `head` equal to the item's `commit` and the setting
`required_checks`), review (outside, `scm.change.reviewed` approved, `count` the setting `approvals`,
`distinct: source`, as `delivery_sail` already does; `on` changes requested → back to the work),
label (Outbox: the setting `label`, `SAIL` at the owner's company, as `delivery_live` already drafts
`live.sail`), land (outside, `scm.change.landed`), and for a stack provider, restack (program, on the
parent's events). Reviewers to request and the channel to nudge are settings; their values live in
the private overlay (SPEC §8.1 of Orchestra; `[workflows.settings.<workflow>]`), never in the
package.

**S11. The company's workflow is the repository's.** `delivery_live` becomes `pr_review` with the
company's settings plus the steps no other company has (ticket, triage of SAIL rejections), kept in
`.orchestra/workflows/` and promoted only by the Workflows plugin's rule (SPEC §8: parameters when a
second repository wants it).

## 5. What stays in the agents plugin

**S12. The worker's harness calls the provider for three things, and pushes nothing.** (1) Where it
is: the handed `workspace` resource (`floor.workspace`, `orchestra_agents/floor.py`, matching the new
name), and from the provider the branch, its base and its parent, for the prompt (`floor.task_text`
today says only "a worktree on the item's branch"). (2) The by-hand places of the description
(S9): the worker writes them into the facts it finishes with (`offer.finished` `facts.set`,
`docs/machine-contract.md` §4). (3) Committing, clean, before it finishes, as today (the contract's
"each resource left committed and clean"). The push guard stands (`orchestra_agents/push_guard.py`,
the agents' SPEC: no session pushes unless its role is in `[agents] allow_push`): proposing is a
program step, not the worker's turn. The Supervisor's scratch worktree (`patching.py`) moves to the
library later (§9).

## 6. Migration, every step leaving the suites green

1. **Workflows, additive:** a kind's commands are given `ORCHESTRA_RESOURCE_DIR` (the unit's
   directory, `resources/<kind>/<unit>/`, which SPEC's state layout already reserves) and, for reset
   and release, `ORCHESTRA_FIELDS`, as a program is given (`orchestra_workflows/programs/step.py`), so
   a provider can place a stacked branch. Generic: a staging environment may need the item's service
   too. A test per variable in `tests/e2e/test_resource_commands.py`.
2. **`orchestra-scm` is built** with the `branch_pr` provider only: `worktree.py`'s mechanics moved
   unchanged, `branch_for`'s naming kept (so `live.py` reads the same branches), the fakes (a bare
   `origin` on disk, the bridges' fake GitHub, and `gh`/`gs` shims that record their calls over real
   git), and `tests/e2e/test_worktree_kind.py` moved over and passing against the scaffolded kind.
3. **Readers take both names:** `floor.workspace` and `scripted.worktree` accept `workspace` or
   `worktree`; `gate.sh` takes `ORCHESTRA_RESOURCE_WORKSPACE` or the old variable.
4. **task_loop moves:** its target gets the scaffolded `.orchestra/resources/workspace/kind.json`, its
   three steps `needs: ["workspace"]` and the setting `scm = "branch_pr"`. The proof is the drift test
   (SPEC §8): the same scripted run gives the same pile series before and after
   (`tests/task_loop_script.py`, `tests/e2e/test_example_task_loop.py`). `orchestra-scm` becomes a
   dev dependency of the examples, never of the plugin.
5. **delivery_sail and delivery_live move** the same way; `live_worker.py`'s push becomes the
   `scm_propose` program, and `live.item_of` calls the library's naming.
6. **Workflows drops the built-in:** `worktree.py`, the `builtin` branches, `WORKTREE*`, the guide's
   section; SPEC §6 keeps the generic kind and points at `orchestra-scm`. A repository still saying
   `needs: ["worktree"]` with no such kind is refused by the loader in one sentence naming the
   scaffold command (the loader already refuses unknown references, SPEC §7).
7. **Readers drop `worktree`.** Then the stack providers, each with its own acceptance: G7's three
   (a dependent ticket branches from its parent; a change to the first restacks the second; both
   pull requests show the right base), on a sandbox repository.

## 7. Contracts that change

The Workflows SPEC §6: the worktree kind and its seven requirements leave; a kind's commands gain
two variables (step 1). The machine contract (`docs/machine-contract.md` §3: "`handle` is, for the
worktree kind, the worktree's path") names the `workspace` kind. The scm events are a new
vocabulary of the library's, documented in its SPEC; Orchestra reads none of their `data` (rule 3).
Nothing in Orchestra's core changes (rule 1: no domain concept enters it).

## 8. Questions for the owner

**Q1.** Which stack provider first: `gh-stack`, which your company uses, or git-spice (D8)?

**Q2.** Where do the company's description templates live, since they are private: the private
overlay's directory, the state directory, or `~/work-desk` with the people and channels (D10)?

**Q3.** May a provider push the item's own branches from a program step (never the base), or does
every push go through the Outbox's `git.push` for approval (`orchestra_outbox/actions.py`)?

## 9. Not built

The stack providers' merge strategies beyond "bottom first" (the open question of
`corporate-workflow.md`: merge authority and style); ports and `arc port` (R5); the verifier's
depth by position (`corporate-workflow.md`, "Depth follows position"); adoption of the owner's own
worktrees (Workflows SPEC §12.1, which moves here); providers for other forges (GitLab, Bitbucket,
Gerrit) and other systems (Mercurial, Perforce); the feature-flag system the trunk provider's
release would need; the Outbox kinds for requesting reviewers and editing an open description; the
Supervisor's patches through the library. None is needed for task_loop and delivery to move.
