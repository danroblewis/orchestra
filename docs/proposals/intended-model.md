# The intended model

Status: draft for review, 2026-11-01. Nothing built. Proposal 2 of `design-backwards.md` §7,
written from `design-backwards-notes.md` §9, §11 and §13 and decision D21, for milestone M2 of
`docs/roadmap/GOAL-2026-11-01-workflows.md`. The page states it must produce are the approved
mockups, `mockups/out/D1–D3` and `E1–E3` (`mockups/README.md`). Instruments attached to declared
machines are proposal 5 (`instruments-on-machines.md`), referenced here, not repeated. What the
Supervisor does with any of this is proposal 4 (`machine-design.md`).

## 1. Purpose and scope

Orchestra describes what a system does: the event map (who talks to whom) and the discovered
model (how the quantities move). Nothing says what the owner wants it to do. The owner: "Right
now, both of those show only what truly exists. It doesn't have the concept of a tentative or
proposed change. There are two types of tentative changes - user created and AI inferred. The
user created one has precedence, but it's not real until the user confirms it."

This proposal adds the **declared layer** of the one model: what the owner intends (stocks,
effects, targets, flows, machines, events) and what the AI or inference proposes, kept as
hypotheses beside the observed layer, and the **comparison** of the two. It lives in the core
("You can put it in the core if you think that makes sense", notes §11), because the core
already holds declared equations and the comparison is domain-neutral.

It runs nothing (rule 1): a declared machine is not started, a declared stock binds no series,
a declared flow changes no equation. Acting on a declaration (instrumenting, drafting, starting a
confirmed machine) is a plugin's. No new page, wizard, step strip, chat on a page or layer toggle
(rejected, notes §13): "I want you to extend the Event Map page and the System Dynamics page."

## 2. What can be declared

Every declared element has an `id` (a slug, unique within its part), a `name`, a `note`, a
`state` (§3) and `provenance` (§4). None of it is a domain concept: "Features" and "Feature
Count Improver" are the owner's words in data, never in code.

**Stocks.** A quantity the owner expects to accumulate, with or without a series yet ("A user
would start by fabricating a system dynamics model, one that has no measurement for stocks yet",
notes §9.1). Fields: `unit`, `near` (a stock id it is drawn beside, a layout hint: Features
"beside DONE"), `found_as` (the discovered stock it turned out to be, set only by a declaration,
never by inference), `measure` (§6.3, recorded by the plugin).

**Expected marks on discovered parts.** "Yes I want to track the existence of this stock in the
sysdyn inference": a discovered stock or flow marked **expected** is always drawn. A mark names
the part by its discovered id; a flow whose id changed is matched by its ends (`from`, `to`).

**Flows.** An expected flow between two stocks (declared or discovered; `null` for outside):
"Then the user suggests some flows to and from the stock." A declared flow has no equation; it is
drawn as a ghost until a version has a flow between those ends.

**Effects.** From notes §9.8: "things that exist and can be measured but are the consequences of
the system", "nebulous, maybe ephemeral, measurable consequences of the system at large", not
the environment ("They are not 'environment' the way we've been using it"); the owner: "Effects
is good." An effect is a measurable quantity **no machine produces and no machine owns**:
latency, error budget, the age of the review backlog, on-call load, customer trust, technical
debt. It is declared like a stock (same fields, `part: "effect"`), but discovery may find it as a
stock or only as an input an equation reads (latency accumulates nothing); either counts as found.
An instrument is attached to it so discovery can find it (the plugin's work, P4/P5).

**Targets.** On a declared or discovered stock or effect: `{"op": "below"|"above"|"within",
"value": x, "hi": y?, "over_s": window}` ("Pull requests wait under a day for a first review").
The core says met, missed or unknown from the latest levels over `over_s`; nothing acts on it.

**Machines.** Placed by name ("by name only", notes §9.3). A name declares a machine; how many
instances it has is learned, never declared: from CloudEvents sources `<machine>/<instance>` as
today, and from series labels once an instrument is attached (P5). The id is the `source` it is
expected to publish under. Fields, exactly as notes §13.2's table lists them:

| kind | fields |
|---|---|
| common to all | `title`, `description`, `tags`, `engagement` (`mode`: `ad hoc` \| `continuous` \| `scheduled`; `schedule` when scheduled, e.g. `daily 00:00`), `receives`, `emits` |
| `universal` | `invariants` (list), `steps` (ordered list), `reads` (stock, effect or series ids it may read, never bound to it). No `model`, `prompt`, `tools` or `harness` field: "A Universal Machine is not described in AI terms"; the store refuses those keys |
| `programmatic-adhoc` | `command`; `interface`: `arguments` (`[{name, description, default}]`), `environment` (`[{name, description, value}]`), `stdin` (`{description, example}`), `exit` (what each code means) |
| `programmatic-continuous` | `command` (a daemon); `protocol` (`http` \| `graphql` \| `grpc` \| `other`), `listen`, `send` (how it sends events, e.g. `POST /events`), `receive` (`{"how": "poll"|"push", "call": "getTasks()", "every_s": 10}`), `health` |
| `external` | no `command`; not managed by `orchestra run`; `source` (the name its events carry), `runs_where`, `log` (shown only if inside the repository or state directory, rule 2) |

`receives` and `emits` are common because the mockups give every kind both (E1, E3).

**Events.** A declared event type: `type`, `description` (its purpose, which the refinement
passes of P4 read: "make sure the purposes of events aren't duplicated"). A machine's `receives`
and `emits` name event types; a type named but not declared is declared implicitly, with no
description.

**A machine's expected effect** (notes §13.3: "if we can't point to any prediction then we
probably don't want the Machine in there at all"): a list of edits in the grammar of
`orchestra.prediction.made` (`sd/predictions.py`: `{"flow", "factor"}`, `{"stock", "above"}`,
`{"from", "to", "appears"}` …) with a `horizon_s`. The declared layer keeps it as a **draft
prediction** and shows it; it is never a flow binding (rule 6). When the machine is confirmed,
the plugin that starts it publishes the prediction, with `change` the id of the event that begins
the machine's era (`system.changed` or `config.changed`), and the core judges it as any other
(SPEC §4.3, G13). The declaration then records the prediction's id (`prediction`), so the panel
links to its verdict. Edits that make a flow appear are also drawn on the Dynamics page as
expected flows (§7.1).

## 3. States, and the expected set

Each element is in one of three states, per layer of `design-backwards.md` §3:

| state | put there by | shown as |
|---|---|---|
| **proposed** | inference (a part new in a discovered version), or a plugin (the Supervisor's draft). Carries `author`: `inference`, `ai`, or `owner` when the owner asked for it through the plugin | inference: "new in vN" ring; plugin: dashed violet, "unconfirmed", "proposed by the Supervisor" or "added by you" |
| **declared** | the owner: directly through the plugin with their words quoted (`author: owner`), or by confirming a proposal (page or chat) | stocks, flows, effects: "expected", gold pin when present, ghost when absent; machines: plain, with "declared · unheard" until heard |
| **observed** | the bus (machines, event edges) and discovery (stocks, flows) | as the pages draw today |

Declared and observed are independent: an element can be both (a declared machine heard on the
bus, an expected stock present in the version). Proposed and declared are exclusive.

- **Precedence.** "The user created one has precedence, but it's not real until the user
  confirms it." When an `owner` proposal and an `ai` proposal touch the same field, the owner's
  is shown and the AI's kept in history.
- **What needs a confirm.** Stocks, effects, flows, targets and expected marks the owner asked for
  are declared at once (D1: "expected · declared by you"). A **machine** always enters proposed and
  needs a confirm, even when the owner asked for it (E3: "added by you · unconfirmed"), because a
  confirm is what a plugin acts on (it may start the machine). Inferred parts enter proposed.
- **The expected set** = every declared stock, effect and flow, and every discovered part marked
  expected. Each is always drawn. Present in the version shown: drawn as found, with the pin.
  Absent: drawn as a **ghost** (same shape, dashed, reduced opacity, label readable, tagged
  "expected · not in vN"), and listed in the Changes panel.
- **New since vN.** A stock or flow in the shown version and not in version N: ringed, "new in
  vM" (shown only while the "changes since vN" switch is on). **Removed since vN**: in version N,
  not in the shown one: a faint dashed ghost, label struck through, "gone in vM" (switch on only).
- **How long tentative things persist.** "We won't dismiss them entirely, over time the system
  dynamics model will hopefully stabilize." The rule:
  1. A part inference adds becomes a **suggestion** the first time it is in a saved version, and
     stays listed until it is **expected** or **ignored**, by the owner on the page or by the
     plugin on the owner's word. Nothing removes it by time or by count.
  2. A suggestion that later leaves the model is not dropped: it moves to a collapsed group
     "came and went" with how many versions it was in, and returns to the main list if it comes
     back.
  3. **Ignore** hides the suggestion from the list and the "new" ring for good (by id; for a flow
     also by ends); it is kept in the record and undone by the plugin (`unignore`).
  4. A suggestion that has held through `[discovery] announce_hold` discoveries (the host has
     announced it in `orchestra.model.changed`) is marked **held**; one that has not is
     **tentative**. The list orders held before tentative, so churn sinks.
  5. A plugin's proposal (a machine, a field) stays until confirmed or discarded; it never expires
     (each element's rule: §9, P5.e).
  The model has **stabilised** when no suggestion is tentative; the list then shows only what
  needs a human answer.

## 4. Provenance

Every element, and every change to it, records who, when and from where:

```json
{"author": "owner", "via": "plugin", "source": "supervisor", "at": 1793505421.2,
 "turn": "sessions/supervisor/41", "message": "msg_0193", "quote": "I'm going to create a Features stock.",
 "control": null, "page": null}
```

`via` is `plugin` (§6.3: the plugin machine's `source`, session turn, message, and the owner's
words in `quote`), `page` (§6.2: `control`, `page`, and `from`, e.g. "changes since v14"), or
`host` (inference). An element keeps its first provenance and its latest; the journal (§5) keeps
all. The pages print it ("declared by you · 20:57", "confirmed by you just now, from 'Changes
since v14'"). "You" is the holder of the web token (SPEC §10.2 has no other identity); a plugin's
`author: owner` is its assertion, backed by the quote.

## 5. Storage

In the model store, beside the discovered versions (rule 5; the goal's decision 3), never in
`orchestra.toml` ("If TOML is the interface for setting this up, it will be a miserable
experience", D21):

```
<state>/model/
  v0001.json …            discovered versions (unchanged)
  discovered.json         the latest discovery (unchanged)
  intended/
    journal.jsonl         every accepted change: seq, at, provenance, ops (append-only)
    d0001.json …          the declared layer after each accepted change: one version
    compare/              cached comparisons, one file per key (below)
```

- **A version of the declared layer** (`dN`) is its whole state after one accepted call: one
  call of §6.3 or one page control. A call may carry many ops (the Supervisor's whole turn), so
  "changed just now" groups by call. Versions never change; past ones stay readable (rule 4).
  The declared and discovered versions are two numberings of the one model: neither is a model
  of its own, and the comparison always pairs one of each.
- **Reached only through `ModelStore`** (`ModelStore.intended()`, an `IntendedStore` under
  `orchestra/sd/intended/`), writes under `ModelStore.locked("intended")` across processes.
- **The comparison** `compare(dN, model, since)`: `model` is a saved version or the latest
  discovery, `since` the base version (default: the one before the shown one). It lists, per part:
  present or absent for each element of the expected set; new and removed since the base
  (`sd.compare`'s structure diff: appeared and disappeared, loops excluded); the suggestions (§3)
  with held / tentative / came-and-went, from the versions between the first appearance and the
  shown one; each declared machine heard or unheard, each declared edge observed or not, each
  observed machine and edge undeclared (`unexpected`, kept in the data; §11, question 2); each
  target met, missed or unknown.
  Everything observed (present, heard, recording, met, candidates) is derived here, on read, and
  never stored in the declared layer. Its inputs are immutable, so it is cached by key, `compare/d{N}-v{M}-v{K}.json` (`live` for the
  latest discovery, of which only the newest file is kept). The host computes the current one
  after each discovery and each declaration; the web server reads it, or computes and writes it
  on a miss for a past pair (milliseconds: the layer is tens of elements, a version hundreds of
  parts). Nothing rediscovers on request.
- **Announced.** After each accepted change the host publishes `orchestra.intent.changed` as
  `orchestra-host` (its own type, its own `data`: `version`, `ops` by kind and id, `via`), so the
  Supervisor sees a page control as an event (decision 1). The host follows the journal by `seq`,
  so a change the web server wrote is announced once the host is up. Rule 3 is unchanged:
  nothing reads a machine's `data`.

## 6. The API

### 6.1 Reading: the page states

Both pages keep their endpoints; each answer gains a block. Every field below is new.

**`GET /api/dynamics/model?version=&era=&since=`** (D1–D3). `since` is the base of the diff
(the version bar's switch; absent: no diff marks). The answer's `model` gains:

```json
"intended": {
  "version": 7, "since": 14,
  "expected": [
    {"part": "stock", "id": "features", "name": "Features", "declared": true, "present": false,
     "found_as": null, "near": "tasks_tickets_DONE", "note": "your note · waiting for a flow",
     "provenance": {…}, "target": null,
     "measure": {"options": […], "chosen": "a",
                 "recording": {"instrument": "features.acceptance", "since": 1793503500, "points": 3,
                               "every_s": 900, "last": 46, "series": "acceptance_tests_passing"}}},
    {"part": "stock", "id": "acceptance_tests_passing", "declared": false, "present": true,
     "since_version": 15, "provenance": {"via": "page", "control": "expect", "from": "changes since v14", …}}
  ],
  "marks": {"stocks": {"acceptance_tests_passing": ["new", "expected"]},
            "flows": {"acceptance_tests_passing_net@tasks_tickets_DONE": ["new"]}},
  "removed": {"stocks": [], "flows": [{"id": "repo_files>repo_commits", "from": "repo_files", "to": "repo_commits",
              "rate": "0.41 /min", "machines": [{"machine": "merge_gate", "confidence": 0.71}], "in": 14}]},
  "changes": [
    {"sign": "+", "part": "stock", "id": "acceptance_tests_passing", "status": "tentative", "since": 15,
     "why": "from the series acceptance_tests_passing recorded by features.acceptance", "controls": ["expect", "ignore"]},
    {"sign": "+", "part": "flow", "id": "…@tasks_tickets_DONE", "status": "tentative", "since": 15, "controls": ["expect", "ignore"]},
    {"sign": "-", "part": "flow", "id": "repo_files>repo_commits", "in": 14},
    {"sign": "o", "part": "stock", "id": "features", "why": "expected · not in v15"}
  ],
  "came_and_went": 0,
  "simulated": ["features.placeholder"]           // instruments of options recorded as simulated
}
```

D1 is this with no version 15 and `since` absent; D2 with `since=14`; D3 after `expect`. The
version bar's existing fields (`version`, `current`, `versions`) are unchanged.

**`GET /api/machines?era=`** (E1–E3). Each machine gains `intent` (`null` for one nobody
declared); a declared machine not yet heard is appended, as plugin placeholders are today
(`unseen: true`), and a plugin placeholder never overrides a declaration:

```json
"intent": {"state": "proposed", "author": "ai", "kind": "universal", "heard": false,
  "title": "Feature Count Improver", "description": "…", "tags": ["features", "feedback loop", "delivery"],
  "engagement": {"mode": "scheduled", "schedule": "daily 00:00"},
  "invariants": ["…"], "steps": ["…"], "reads": ["features", "acceptance_tests_passing"],
  "receives": ["changes.requested", "gate.rejected", "gate.landed"], "emits": ["work.requested"],
  "expected_effect": {"horizon_s": 604800, "expect": [{"stock": "features", "above": 46},
                      {"flow": "tasks_gate_runs_total_landed", "factor": 1.2}, …],
                      "prediction": null},
  "provenance": {…},
  "latest": {"version": 9, "at": 1793505501, "quotes": ["…watch the ticket queue…", "…12am every day"],
             "added": {"receives": ["changes.requested", "gate.rejected", "gate.landed"]},
             "removed": {"receives": ["session.settled", "task.reported"]},
             "changed": ["engagement", "steps"]}}
```

`latest` is the difference between the machine's declaration before and after the latest call
that changed it; the page marks it "just now" for ten minutes. The top level gains
`intended_edges` (`{from, to, kind: "publishes"|"subscribes", state, observed, gone}`, `gone` for
an edge the latest call removed) and `intended_types` (declared event types with descriptions).

**Also:** `GET /api/intended?version=` (the whole layer), `/api/intended/versions`,
`/api/intended/journal?after=`, `/api/intended/compare?d=&v=&since=`, and
`/api/intended/script?instrument=` (the text of a measurement option's script, read only inside
the repository, as logs are).

### 6.2 The page controls

One endpoint, `POST /api/intended/control`, `{"control", "part", "id", "from"}`, five controls:

| control | where | what it records |
|---|---|---|
| `expect` / `unexpect` | D2 Changes panel; D3 drawer switch | an expected mark on a discovered part (resolves its suggestion) |
| `ignore` | D2 Changes panel | the suggestion ignored (§3 rule 3) |
| `confirm` / `discard` | E1–E3 panel and card; D1 drawer for a proposed stock | a proposal declared, or discarded (kept in history) |

Each is a declaration with `via: page` provenance; it changes no machine, no configuration and
no discovered version. Everything else on the panels (title, steps, the Universal | Programmatic
switch, the engagement tabs, the measurement options) **shows** the declaration and is changed by
talking to the Supervisor ("Ask the Supervisor to change any of this", E1). The "changes since
vN" switch is a view setting (`since=`), not a control.

### 6.3 Declaring: the plugin's API

In process, `ModelStore.for_state(dir).intended().apply(ops, provenance) -> {"version", "ids"}`;
over HTTP, on the host's events endpoint (its token, like the experiments API, SPEC §3.1):
`POST /intended` with `{"source", "turn", "message", "quote", "author", "ops": [...]}`, answered
`{"ok": true, "version", "ids"}` or `{"ok": false, "error", "index"}` (422, the op refused). All
ops of a call apply or none; any op may name `guessed` fields (§9). The ops:

```
declare_stock {id?, name, unit?, near?, note?}      declare_effect {same}
declare_flow {from, to, name?}                      set_target {part, id, op, value, hi?, over_s}
expect {part, id} · unexpect · ignore · unignore    link {id, found_as} · alias {machine, observed}
propose_machine {id, kind, …fields of §2}           revise_machine {id, set: {field: value}, add: {…}, remove: {…}}
declare_event {type, description}                   set_expected_effect {machine, expect, horizon_s}
record_prediction {machine, prediction}             record_measurement {part, id, options, chosen?}
confirm {part, id} · discard {part, id} · retract {part, id}   (retract: a declaration withdrawn, kept in history)
```

`record_measurement` is how "How to measure it" reaches the page (the goal's decision 2): the
plugin records `options` (`[{key, title, how, kind, simulated, instrument?, script?, config?}]`)
and which is `chosen`; the core proposes none and shows what was recorded, with the recording
status it reads itself (the instrument's series in the metrics store: since, points, every, last).
An option marked `simulated` marks every stock and flow whose series carries
`instrument=<its instrument>` as simulated, on both pages (13.4: "marked as such").

## 7. The pages

The marks are the mockups' visual language (`mockups/README.md`): ghost, new in vN, unconfirmed,
removed, expected pin, and green / struck-through / gold for a change "just now". What each frame
needs from §6:

| frame | what changes on the page | from |
|---|---|---|
| D1, D1-closed | ghost of the declared stock at `near`, tagged "expected · declared by you · 2 min ago"; its drawer: quote, status "no series yet → recording", **How to measure it** (the recorded options, the chosen one's recording line, sparkline, script and `[[collect]]` entry collapsed), Level waiting; the Stocks table's **Expected** group, counts "N found · M expected" | `expected[]`, `measure`, `/api/intended/script` |
| D2 | the switch "changes since vN" in the version bar; new parts ringed "new in vM"; removed flows as struck-through ghosts; the expected-but-absent ghost "expected · not in vM"; the **Changes since vN** panel beside the loops (+ with expect / ignore, −, ○, "came and went"); four legend entries; new and removed rows in the tables | `since=`, `marks`, `removed`, `changes` |
| D3, D3-closed | the drawer's switch "Expected: always show this stock" and its provenance line; the gold pin; the Expected group listing both; the declared stock's note | `expect` control, `expected[]` |
| E1 | the proposed machine dashed violet, "unconfirmed", sub-line its engagement; the highlight; the details panel (status strip with confirm / discard, the quote, Universal \| Programmatic showing the declared kind, common fields, invariants, steps, receives "a guess", emits, reads, expected effect linking to /dynamics); its card first in the grid | `intent`, `intended_edges` |
| E2 | "+ new link" green edges, "− link removed" ghost edges, "changed just now" on the node and engagement, "rewritten just now" on steps, chips marked on the card | `intent.latest`, `gone` |
| E3, -continuous, -external | the Programmatic panel with the engagement tabs and each kind's fields of §2 | `intent` |

Targets, declared flows and an expected effect's appearing flows have no frame yet: a target is a
line in the drawer and the Expected group (met / missed / unknown); a declared flow is a ghost
edge, like a removed one but tagged "expected".

**The highlight rule** (notes §13.2), whenever the panel is open on a machine: the machine, its
event types and the machines on those event types (its direct connections) at full colour; their
other event types and the machines on those (the second ring) at .45 opacity; everything else at
the page's `ng-dim` (.1). An edge takes the lesser of its two ends; links the latest call removed
stay drawn, as ghosts, at full colour. Both pages already refresh while open, so a change appears
without a reload.

## 8. Invariants amended

Each change is stated in the commit that builds it (C1), and SPEC follows (C5).

**Rule 2** (machines are known by their events). Add after the sentence on `Plugin.machines`:

> The owner may also declare machines (the intended model, `orchestra/sd/intended/`), through a
> plugin or by confirming a proposal: placeholders of the same kind as a plugin's, from the owner,
> with the same limits. A declared machine is shown as declared, and as heard only once its
> `source` is on the bus; its declared kind, engagement, interface and events are shown as the
> declaration, apart from what is observed, and never override it, never make it exist in the
> observed layer, and say nothing about flows.

Why: the map must show machines that do not exist yet (E1) and machines that will never publish
(`external`, E3), without the observed layer ever trusting a declaration.

**Rule 7** (stocks are discovered). Add after "Stocks are discovered, not configured":

> A stock, effect or flow may be declared, and a discovered one marked expected (the intended
> model): an expectation drawn beside the discovered model, never a part of it. A declaration
> binds no series, is not handed to discovery, changes no equation, and is matched to what
> discovery finds only by a declaration (`found_as`), never by a name or a label.

Why: Features must be on the page before anything measures it (D1), and discovery must stay the
only source of the model's stocks. Whether declarations later become discovery's priors (D4) is
an open question (§11).

**Rule 9** (humans talk only to the Supervisor). The default, as the goal's decision 1: replace
"except for observations: rediscovering the model …" with

> except for observations: rediscovering the model (…), and the intended model's page controls
> (expect, unexpect, ignore, confirm, discard), which record a declaration with its provenance,
> are announced on the bus (`orchestra.intent.changed`), and change no machine, no configuration
> and no discovered version. What a plugin does on seeing a confirm is that plugin's path, under
> its own rules.

Why: the owner's scenario has the user clicking them (D2: "expect", E1: "confirm"), and like the
rediscover button they change what Orchestra believes, not what the system does. The honest
caveat: a confirm is what the agents' plugin starts a machine on (E1's footnote: "confirm starts
it under the agents' host"), so one click leads to a running machine through the plugin.
**The alternative, for the owner:** no page writes at all; each control sends the Supervisor a
message ("confirm feature-count-improver"), and the Supervisor makes the declaration. Rule 9
stands unchanged; the price is a chat round-trip per click and the Supervisor having to be up.
Both produce the same records except `via`.

**Rule 5** (state). The declared layer is new state. Add after "the model through
`orchestra.sd.store.ModelStore`":

> ; the intended model through `ModelStore.intended()` (`project.intended`), in
> `<state>/model/intended/`, whose journal and versions nothing else opens.

**Rule 4** (one model, by versions). Add: "The model's versions are of two kinds: discovered
(`vN`: stocks, flows, equations) and declared (`dN`: the intended model, §5); a change to one
never makes a version of the other, and a comparison always names one of each."

Rules 3 and 6 need no change: the host's announcement is its own type; expected effects are
predictions, and a machine's association with a flow stays inferred.

## 9. What P4 and P5 need

| # | need | answer |
|---|---|---|
| P4.1 | Python API with provenance | `project.intended` (an `IntendedStore`, the same object as `ModelStore.intended()`): `apply(ops, provenance) -> {"version", "ids"}`, `read(version=None)`, `design()`, `compare(model=None, since=None)`. Provenance as §4 (`author`, `via`, `source`, `turn`, `message`, `quote`). A field the plugin guessed is named in the op's `guessed: [field, …]` (E1's "a guess"); it stays guessed until an op sets it without `guessed`, or the element is confirmed. |
| P4.2 | each change timed | every journal entry and every element's latest provenance has `at`; `intent.latest.at` drives "just now" (ten minutes). |
| P4.3 | machine field names | §2's table, exact. `kind` ∈ `universal`, `programmatic-adhoc`, `programmatic-continuous`, `external`; `engagement.mode` ∈ `ad hoc`, `continuous`, `scheduled`: any for `universal`, `ad hoc` or `scheduled` for `programmatic-adhoc`, `continuous` for the other two. Any other key is refused. |
| P4.4 | measurement options | on the declared stock or effect, `measure.options` and `measure.chosen`, in the declared layer (`record_measurement`). |
| P4.5 | declared ↔ discovered stock | never automatic. On read, the comparison lists `candidates`: discovered stocks whose series carries `instrument=<the chosen option's instrument>`. The drawer shows them as "may be this stock" (a proposal). Only `link {id, found_as}` (the plugin, on the owner's word) sets it. Features stays a ghost in D2 because no link was made. |
| P4.6 | simulated series | an option with `simulated: true`; every stock or flow whose series carries that option's `instrument` label is marked simulated on read (§6.3). |
| P4.7 | stable ids across versions | discovered ids are not promised stable. A mark stores the id and a **key**: a stock's is its series key (name and labels without `project`, `sd.series.series_key`); a flow's is its ends' keys. A mark matches by id, else by key. |
| P4.8 | events on page clicks | one type, `orchestra.intent.changed`, from `orchestra-host`, `subject` `<part>:<id>` (a listener filters `orchestra.intent.changed:machine:feature-count-improver`), `data` `{version, via, ops: [{op, part, id}]}`. `op` is `confirm`, `discard`, `expect`, `unexpect` or `ignore` for page controls (the D3 switch is `expect`/`unexpect`). The rule-9 amendment is in §8. |
| P4.9 | predictions for parts with no series | "a flow appears": `{"from", "to", "appears": true}` (existing). "A stock goes up": a new edit kind, `{"stock", "rises" \| "falls": true}`, judged like `above` / `below` with x the level at the change (a SPEC §4.3 change in `sd/predictions.py`, built in C1). An edit naming a declared stock with no `found_as` keeps the draft unpublishable: the panel says "waits for a series", and the plugin publishes once it is linked, with the discovered id. |
| P4.10 | a summary read | `project.intended.design()`, and `GET /intended/design` on the endpoint: the layer's version; each stock, effect, flow and target with state, present, linked; each machine with state, kind, engagement, heard, receives, emits, guessed fields; declared event types; the open items (proposals unconfirmed, suggestions unanswered, expected parts absent). Under 20 KB for a layer of 100 elements. |
| P5.a | rule 5 | amended, §8. |
| P5.b | aliases | a declared machine id is the `source` expected on the bus. When it is known under another name (an observed source, or a traffic source's `<prefix>.<name>`), `alias {machine, observed: [names]}` joins them: a declaration, never inferred. The comparison lists name matches after removing a prefix as `alias_candidates` (a proposal). Joined, the observed entry carries the `intent` and no separate unseen entry is added. |
| P5.c | the map versioned apart from equations | one `dN` numbering covers the whole declared layer: stocks, effects, flows, targets, machines, events and P5's attachments. Equations are only in `vN`. Neither makes the other's versions (rule 4 as amended). |
| P5.d | observed facts derived on read | `present`, `heard`, `recording`, `measured`, `instances`, `met`, `candidates`, `alias_candidates`, `unexpected` are computed by the comparison and only ever cached in `compare/`. They are never written to a `dN` or the journal; an op carrying one is refused. |
| P5.e | how long proposed things persist | by element: inference suggestion, until `expect` or `ignore` (§3); a plugin's proposed machine, stock, effect, flow or attachment, until `confirm` or `discard`; a guessed field, until set or confirmed; a declared element, until `retract`; an expected mark, until `unexpect`; an ignore, until `unignore`. Nothing expires by time. |

## 10. Acceptance tests

Each is a program: a unit test on the store and comparison, an API test against the web app on a
temporary state directory, or a page test rendering the real page with the fixtures and comparing
with `mockups/out/` (C2, C3).

1. `apply` of one call with several ops writes one journal line and one `dN`; a refused op
   (index 2 of 3) writes nothing and answers 422 with `index: 2`.
2. Every past `dN` reads back unchanged after later calls; versions are numbered without gaps.
3. Every element carries `provenance` with `author`, `via`, `at`; a plugin call keeps `source`,
   `turn`, `message`, `quote`; a page control keeps `control`, `page`, `from`.
4. `propose_machine` with a `model`, `prompt`, `tools` or `harness` key on a `universal` machine
   is refused; each kind accepts exactly its fields of §2 and refuses `command` on `external`.
5. A declared stock with no series appears in `intended.expected` with `present: false`, and in
   `changes` as ○; the model's `stocks` list is unchanged by it (rule 7).
6. Discovery run with and without a declared layer present produces byte-identical versions.
7. A discovered stock marked expected and absent from a later version is in `expected` with
   `present: false` and listed as ○ in that version's `changes`.
8. A stock in v15 and not v14 is in `marks` as `new` with `since=14`, and not without `since`.
9. A flow in v14 and not v15 is in `removed.flows` with its v14 rate and machines, with `since=14`.
10. A suggestion stays in `changes` across later versions until `expect` or `ignore`; it is never
    removed by time or count; after it leaves the model it is counted in `came_and_went`, and
    returns to `changes` when it comes back.
11. A suggestion announced by `orchestra.model.changed` is `held`; before that, `tentative`; held
    are listed first.
12. `ignore` removes the suggestion from `changes` and its `new` mark; `unignore` restores both.
13. `POST /api/intended/control` accepts exactly the five controls; any other value, or a body
    with field values, answers 400; no control writes `orchestra.toml`, a discovered version, or
    publishes anything but `orchestra.intent.changed`.
14. Each accepted change is announced once as `orchestra.intent.changed` by `orchestra-host`,
    including a change written while the host was down (announced when it starts).
15. A comparison is written under its key and served from the cache on the next request; a new
    discovery or declaration produces a new key, never an edited file.
16. `record_measurement` options are returned as recorded, with the recording status read from the
    metrics store; the core adds no option of its own; changing `chosen` changes nothing else;
    `/api/intended/script` serves a script inside the repository and refuses one outside it.
17. A stock or flow whose series carries the instrument of a `simulated` option is marked
    simulated in the Dynamics answer and on the Machines page's reads.
18. A declared machine never heard is in `/api/machines` with `unseen: true` and its `intent`;
    once an event with its source is on the bus, the same entry has observed fields and
    `intent.heard: true`; a plugin placeholder of the same id does not replace its `intent`.
19. An observed machine with no declaration has `intent: null` and no new mark.
20. After a `revise_machine` that adds and removes receives, `intent.latest` lists them and
    `intended_edges` marks the removed edges `gone`; the next `/api/machines` refresh shows it.
21. A `revise_machine` setting `engagement` to scheduled daily appears in the next answer's
    `intent.engagement` and in `latest.changed`.
22. `set_expected_effect` is stored as a draft and never adds a flow to the model or a hypothesis
    to a flow; `record_prediction` links the prediction id, and the answer carries its verdict
    once `orchestra.prediction.judged` is recorded.
23. An expected effect with `{"from", "to", "appears"}` is drawn on the Dynamics answer as an
    expected flow; when a version has a flow between those ends it is `present: true`.
24. A target on a stock is `met`, `missed` or `unknown` from the levels over `over_s`.
25. Page D1, D1-closed, D2, D3, D3-closed, E1, E2, E3, E3-continuous and E3-external, rendered by
    the real page code from API answers that C1 produces, match the mockup frames' elements: the
    tags, panels, groups, legend entries and controls named in `mockups/README.md`.
26. On E1, node opacity is 1 for the machine, its event types and the machines on them, .45 for
    the second ring, .1 for the rest; edges take the lesser of their ends.
27. The Core page answers with the intended store missing, corrupt or locked (rule 8).
28. `link` alone sets `found_as`; a stock recorded by the chosen instrument appears only in
    `candidates`. A mark survives a flow's id changing when its ends' keys hold. An `alias` joins a
    declared machine with an observed or counted one, which then carries the `intent`.
29. No `dN` or journal line contains a derived field; an op carrying one is refused (422).
30. `{"stock", "rises": true}` is judged met when the mean level over the horizon's second half is
    above the level at the change by 2 standard errors; a draft naming an unlinked declared stock
    is reported unpublishable by `design()`.
31. `design()` lists every unconfirmed proposal, unanswered suggestion and absent expected part,
    and each guessed field.
32. From notes §13.4, the core's part: a related series enters the model with no declaration
    (6); the expected stock is still drawn and listed when a later
    inference lacks it (7); a new part stays listed until confirmed (10); a placeholder series is
    marked (17); a new machine adds a node and opens its panel with the draft (18, 25); the
    highlight (26); changes without a reload (20); the engagement change (21); each kind's fields,
    no model or prompt (4); predicted flows shown and judged (22, 23); no page control changes the
    system (13).

## 11. Out of scope and open questions

Out of scope: attaching instruments to declared machines and instances from labels (P5); how the
Supervisor finds measurement options, writes instruments, drafts and refines machines, runs the
refinement passes and publishes predictions (P4); the Workflows plugin's piles, items and floor
(P3); starting a confirmed machine (the agents' plugin); a separate design page (rejected).

Open questions for the owner:

1. **Rule 9** (§8): page controls as observations (default), or every click through the Supervisor.
2. **"Unexpected" machines.** `design-backwards.md` §3 says an observed machine no one declared
   "shows as unexpected", but the approved E-frames draw existing machines with no mark. This
   proposal keeps the mockups: the comparison records `unexpected`, the map does not draw it.
   Should it, once the owner has declared any machine?
3. **Declarations as priors.** D4 lets a human hand discovery a skeleton. Should declared stocks
   and flows become discovery's priors (tried first, like `[[series]]` pins)? Not here: rule 7 as
   amended keeps them out of discovery until the owner says otherwise.
4. **The kind switch and engagement tabs** are shown, not clicked. The owner's words ("a switch to
   choose between") may mean a control; under rule 9 it would be a sixth page control.
5. **Flow identity.** Discovered flow ids are composite and churn; matching by ends may merge two
   flows between the same stocks. Acceptable until a case shows otherwise.
6. **Suggestion volume.** With strategies that churn, the never-dismissed list could grow to
   hundreds; the "came and went" collapse and held-first order are the only defence here, and the
   Supervisor's triage duty (P4) the rest.
7. **The name "effects"** stands ("Effects is good"); whether an effect is drawn differently from a
   stock (no box: it may be an input, not a level) is left to the page work (C2).
