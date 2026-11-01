# The intended model

Status: reviewed, 2026-11-01 (panel round 1; judge's verdicts rounds 2–3); aligned to
machine-design.md and instruments-on-machines.md as merged; coverage pass 2026-11-01. Nothing built. Proposal 2 of
`design-backwards.md` §7, written from `design-backwards-notes.md` §9, §11 and §13 and decision
D21, for milestone M2 of `docs/roadmap/GOAL-2026-11-01-workflows.md`. The page states are the
approved mockups `mockups/out/D1–D3`, `E1–E3` (`mockups/README.md`), with the corrections of §7.
Instruments attached to declared machines are proposal 5 (`instruments-on-machines.md`); what
the Supervisor does is proposal 4 (`machine-design.md`). Round 2 follows the panel's work list.

## 1. Purpose and scope

Orchestra describes what a system does (the event map, the discovered model); nothing says what
the owner wants. The owner: "Right now, both of those show only what truly exists. It doesn't
have the concept of a tentative or proposed change. There are two types of tentative changes -
user created and AI inferred. The user created one has precedence, but it's not real until the
user confirms it."

This proposal adds the **declared layer**: what the owner intends (stocks, effects, targets,
flows, machines, events) and what a plugin or inference proposes, kept as hypotheses beside the
observed layer, and the **comparison** of the two. It lives in the core ("You can put it in the
core if you think that makes sense", notes §11): the core already holds declared equations, and
the comparison is domain-neutral.

It runs nothing (rule 1): a declared machine is not started, a declared stock binds no series, a
declared flow changes no equation. Acting on a declaration is a plugin's. The core knows a
machine's envelope only (§2); what a Universal or Programmatic machine is made of is P4's, stored
here unread. No new page, wizard, step strip, chat on a page or layer toggle (rejected, notes
§13): "I want you to extend the Event Map page and the System Dynamics page."

## 2. What can be declared

Every element has an `id` (a slug, unique within its part), a `name`, a `note` (the owner's own
words only, never page wording), a `state` (§3) and `provenance` (§4). Elements that refer to
discovered parts do so by **key** (§3.1), never by discovered id. None of it is a domain concept:
"Features" is the owner's word in data, never in code.

- **Stocks.** A quantity the owner expects to accumulate, with or without a series yet ("A user
  would start by fabricating a system dynamics model, one that has no measurement for stocks
  yet"). Fields: `unit`, `near` (a stock key it is drawn beside: Features "beside DONE"),
  `found_as` (the key of the discovered stock it turned out to be, set only by `link`), `measure`
  (§6.3).
- **Expected marks.** "Yes I want to track the existence of this stock in the sysdyn inference": a
  discovered stock or flow marked expected is always drawn. A mark stores the part's key.
- **Flows.** An expected flow between two stocks ("Then the user suggests some flows to and from
  the stock"): `from`, `to` (keys of declared or discovered stocks; `null` for outside). No
  equation. Found when a version has a flow between those ends; with a `null` end, or two flows
  between the same ends, the matches are listed as `candidates` and nothing is chosen.
- **Effects.** The owner (notes §9.8): "things that exist and can be measured but are the
  consequences of the system", "nebulous, maybe ephemeral, measurable consequences of the system
  at large", not the environment; "Effects is good." Latency, error budget, the age of the review
  backlog, on-call load, customer trust, technical debt. Declared like a stock (`part: effect`);
  its `found_as` may name a stock key or a series key, since an effect may appear only as an input
  an equation reads. The core does not check what an effect is.
- **Targets.** On a stock or effect (a level) or a flow (a rate): `{op: below|above|within, value,
  hi?, over_s}`, judged on the **mean** over the last `over_s`: met, missed or unknown ("land five
  a day" is a flow target). Per-item conditions ("each pull request reviewed within a day") are
  P3's floor, not targets.
- **Machines.** Placed by name ("by name only", notes §9.3). The id is the `source` it is expected
  to publish under, matching `^[a-z][a-z0-9_]{1,40}$` (P4 §2.3: "Feature Count Improver" is
  `feature_count_improver`); instances are learned, never declared (sources
  `<machine>/<instance>`, and labels once an instrument is attached, P5). The core stores and
  checks only the **envelope** (P4 §2.3): `id`, `title`, `description`, `tags`, `kind` ∈
  `universal | programmatic` (the owner's switch), `managed` ∈ `orchestra | external` (started by
  `orchestra run` or the agents' host, or running elsewhere), `engagement` `{mode, at, tz,
  missed}` (`mode` ∈ `ad hoc | continuous | scheduled`; `at`, `tz` and `missed` ∈ `skip | run
  once` only when scheduled; any mode with either `managed`), `receives`, `emits`, `reads`.
  `managed` and `engagement` are separate axes: a nightly Jenkins job is `external`, `scheduled`. Everything else is `spec`, an object stored exactly as sent, never checked,
  rendered by the page generically in the order its keys were declared. P4 owns the schema of
  `spec` per kind and the check that a Universal Machine "is not described in AI terms".

  What P4 declares in `spec` and the page shows, from notes §13.2's table:

  | kind (and mode) | `spec` |
  |---|---|
  | `universal` | `invariants` (list), `steps` (numbered) |
  | `programmatic`, `ad hoc` or `scheduled` | `command`, or for `managed: external` a `trigger` (a remote call that starts it: a Jenkins job's URL); `arguments`, `environment`, `stdin`, `exit` |
  | `programmatic`, `continuous` | `command` (a daemon; none when external: "effectively continuous machines with no command"); `protocol` (`http`, `graphql`, `grpc`, `other`), `send`, `receive` (push, or a poll with its call and interval: `getTasks()` every 10 s) |
  | any, `managed: external` | `source`: the relayed actor whose events it is (`bot.jira`), never the bridge (rule 2, D19); `log` shown only inside the repository or state directory |

- **Events.** A declared event type: `type`, `description` (its purpose, which P4's refinement
  passes read). A type a machine names but nobody declared is declared implicitly, undescribed.
- **A machine's expected effect** (notes §13.3: "if we can't point to any prediction then we
  probably don't want the Machine in there at all"): edits in the grammar of
  `orchestra.prediction.made` with a `horizon_s`, kept as a **draft prediction**, unpublished. It
  is not an association (rule 6 as amended, §8). When the machine is confirmed and started, the
  plugin publishes it with `change` the id of the event that begins the machine's era, and the
  core judges it as any other (SPEC §4.3); `record_prediction` then links its id. An edit naming a
  declared stock with no `found_as` makes the draft unpublishable until linked. Two edit kinds are
  added to the grammar (C1, SPEC §4.3): `{"stock", "rises"|"falls": true}`, judged as `factor`
  is: the stock's slope after the change against its slope before, met when it moved by `|z| ≥ 2`
  in that direction. "A flow appears" is the existing `{"from", "to", "appears": true}`.

## 3. States, identity, the expected set

| state | put there by | shown as |
|---|---|---|
| **proposed** | inference (a part new in a discovered version) or a plugin (`author` its `source`, or `owner` when the owner asked through it) | inference: "new in vN" ring; plugin: dashed violet, "unconfirmed", labelled from `provenance.source` ("proposed by the Supervisor") or "added by you" |
| **declared** | the owner, through a plugin with the owner's words quoted, or by confirming | stocks, effects, flows: "expected", gold pin when present, ghost when absent; machines: "declared · unheard" until heard |
| **observed** | the bus (machines, edges) and discovery (stocks, flows) | as today |

Declared and observed are independent; proposed and declared are exclusive. **Precedence:** where
an owner proposal and another touch the same field, the owner's is shown, the other kept.
**Declared at once** (the D1 frame as approved): stocks, effects, flows, targets and marks the
owner asks for are declared at once; machines always enter proposed. Whether this squares with
"not real until the user confirms it" is §11's question 2.

### 3.1 Identity: keys

Discovered ids are assigned by arrival order (`sd/discover.py` `unique_id`) and are not stable.
A part's **key** is: for a stock, its series name plus `_identity(labels)` (the labels without
`NOT_IDENTITY`: instrument, machine, source, project, instance, and also `simulated` and `draft`, so a real
series takes over a placeholder's mark); for a flow, its ends' keys plus
its counter's key (none for a net flow). Marks, ignores, suggestions, settling and new/removed
all match by key; the id is for display. The diff (§5) is computed on keys, inside `intended/`,
not with `sd.compare`; parts `sd.prior` carries into an era are excluded, and each key counts
once. Swapping an instrument (a renamed collector) keeps the key.

### 3.2 The expected set and the marks

- **Expected set** = declared stocks, effects and flows, and discovered parts marked expected.
  Always drawn. Present: drawn as found, with the pin. Absent: a **ghost**, same shape, darker
  fill and dashed outline, label readable, "expected · not in vN"; a declared stock with no series
  also tagged "not measured"; a declared flow is a dashed ghost edge, never struck through.
- **Changes since vN** is on by default, the base the previous version; the switch turns the marks
  off, and the base can be any version (`since=`). One default everywhere. **New**: a key in the
  shown version and not the base, ringed "new in vM". **Removed**: in the base, not the shown one,
  faint dashed, label struck through, "gone in vM".
- **Browsing a past `vN`** pairs it with the `dN` current when `vN` was saved (`saved_at`).

### 3.3 How long tentative things persist

"We won't dismiss them entirely, over time the system dynamics model will hopefully stabilize."

1. A key inference adds becomes a **suggestion** the first time it is in a saved version.
2. A suggestion present in `[discovery] announce_hold` consecutive saved versions is **settled**:
   it loses the "new" ring, needs no answer, and can still be expected. It stays settled only while
   present.
3. One that leaves before settling moves to a collapsed group "came and went" (with how many
   versions it was in) and returns if its key comes back.
4. **Ignore** moves it to a collapsed "ignored" group; `unignore` returns it. Nothing is hidden.
5. The model has **stabilised** when no suggestion is unsettled.

Per element: a suggestion persists until settled, expected or ignored; a plugin's proposed
element (machine, stock, effect, flow, P5's attachment) until confirmed or discarded; a pending
change (§4) until confirmed or discarded; a guessed field until set or confirmed; a declared
element until `retract`; a mark until `unexpect`. Nothing expires by time.

## 4. Provenance and changes

```json
{"author": "owner", "via": "plugin", "source": "supervisor", "at": 1793505421.2,
 "turn": "sessions/supervisor/41", "message": "msg_0193", "quote": "I'm going to create a Features stock."}
```

`author` ∈ `owner | inference | <source>`; `reason` is the plugin's one-line why (P4 needs 1, 5).
`via` is `plugin` (§6.3), `page` (§6.2, with
`control`, `page`, `from`) or `host` (inference). Every change has an id (`c<seq>.<i>`: call,
op). A **revision** by `author: owner` with a `quote` applies at once while the element is still
proposed (E2: the Supervisor changes the machine as the owner talks); on a confirmed machine, and
for any other author, a revision becomes a **pending change** on the element,
shown as proposed, answered by confirm/discard `{part, id, change}`. "You" is the holder of the
web token (SPEC §10.2 has no other identity); a plugin's `author: owner` is its assertion, backed
by the quote.

## 5. Storage

In the model store beside the discovered versions (the goal's decision 3), never in
`orchestra.toml` ("If TOML is the interface for setting this up, it will be a miserable
experience", D21):

```
<state>/model/
  v0001.json …  discovered.json     unchanged
  intended/
    journal.jsonl     every accepted call: seq, at, provenance, ops with change ids (append-only)
    d0001.json …      the declared layer after each accepted call: one version
    diff/             cached structural diffs (below)
```

- **A version `dN`** is the whole declared layer after one accepted call (§6.3) or one page
  observation (§6.2): stocks, effects, flows, targets, marks, machines, events, P5's attachments.
  Past versions stay readable. `dN` and `vN` are separate numberings (rule 4 as amended); neither
  makes the other's versions.
- **Only through `ModelStore.intended()`** (`project.intended`, an `IntendedStore` in
  `orchestra/sd/intended/`), writes under `ModelStore.locked("intended")`. The host and the web
  server are the only processes that write under `intended/` (rule 5 as amended).
- **Derived on read, never stored:** present, heard, recording and its points, measured, met,
  instances, candidates, alias candidates, unexpected, verdicts. An op carrying one is refused.
- **The cache holds only the structural diff:** per key, present or absent for the expected set,
  new and removed against the base, suggestion status. Keyed `diff/d{N}-v{M}-v{K}-{era}.json`
  (`live` for the latest discovery, newest only); inputs immutable, so a file never changes. The
  host writes the current one after each discovery and declaration; the web server writes a past
  pair on a miss. Bus and metrics facts are computed on every read under a time limit (as the
  levels are today); past the limit the answer says which are missing.
- **Announced:** after each accepted call the host publishes `orchestra.intent.changed` as
  `orchestra-host` (its own type: `subject` `<part>:<id>`, `data` `{version, via, ops: [{op,
  part, id, change}]}`), following the journal by `seq`, so a call the web server wrote is
  announced once the host is up. A listener filters with the existing syntax,
  `orchestra.intent.changed:subject=machine:feature_count_improver`.

## 6. The API

### 6.1 Reading: the page states

**`GET /api/dynamics/model?version=&era=&since=`** (D1–D3; `since` defaults to the previous
version, `since=off` drops the marks). The answer's `model` gains:

```json
"intended": {
  "version": 7, "since": 14, "since_saved_at": 1793498000,
  "expected": [
    {"part": "stock", "id": "features", "key": null, "name": "Features", "declared": true, "present": false,
     "measured": false, "near": "tasks_tickets{state=\"DONE\"}", "note": null, "provenance": {…}, "target": null,
     "candidates": [{"key": "acceptance_tests_passing", "id": "acceptance_tests_passing", "why": "recorded by the chosen instrument"}],
     "measure": {"options": [{"key": "a", "title": "…", "how": "…", "kind": "script collector", "instrument": "features.acceptance",
                              "simulated": false, "cost": "…", "caveat": "…", "clearance": "…",
                              "provenance": "free text from the plugin", "commit": "3f2c1aa", "first_points": [[t, 41]]}],
                 "chosen": "a",
                 "recording": {"instrument": "features.acceptance", "since": 1793503500, "points": 3, "every_s": 900,
                               "last": 46, "points_series": [[t, 41], [t, 43], [t, 46]]}}},
    {"part": "stock", "key": "acceptance_tests_passing", "id": "acceptance_tests_passing", "declared": false,
     "present": true, "since_version": 15, "provenance": {"via": "page", "control": "expect", "from": "changes since v14", …}}
  ],
  "marks": {"stocks": {"acceptance_tests_passing": ["new", "expected"]}, "flows": {"<id>": ["new"]}},
  "removed": {"stocks": [], "flows": [{"key": "…", "from": "repo_files", "to": "repo_commits", "rate": "0.41 /min",
              "machines": [{"machine": "merge_gate", "confidence": 0.71}], "in": 14}]},
  "changes": [
    {"sign": "+", "part": "stock", "key": "…", "status": "new", "since": 15, "why": "…", "controls": ["expect", "ignore"]},
    {"sign": "+", "part": "flow", "key": "…", "status": "new", "since": 15, "controls": ["expect", "ignore"]},
    {"sign": "-", "part": "flow", "key": "…", "in": 14},
    {"sign": "o", "part": "stock", "id": "features", "why": "expected · not in v15", "candidates": [ … ]}
  ],
  "came_and_went": [], "ignored": [], "settled": 3,
  "predicted": [{"machine": "feature_count_improver", "from": "tasks_tickets{state=\"DONE\"}", "to": "features",
                 "edit": {"from": "…", "to": "features", "appears": true}, "present": false, "machines": []}]
}
```

**`GET /api/machines?era=`** (E1–E3). Each machine gains `intent` (`null` when undeclared); a
declared machine not yet heard is appended (`unseen: true`); a plugin placeholder never replaces
an `intent`. The card's kind is the declared kind until the machine is heard, then the announced
one.

```json
"intent": {"state": "proposed", "author": "supervisor", "kind": "universal", "heard": false,
  "title": "Feature Count Improver", "description": "…", "tags": ["features", "feedback loop"],
  "managed": "orchestra", "engagement": {"mode": "scheduled", "at": "00:00", "tz": "America/Los_Angeles", "missed": "skip"},
  "receives": ["changes.requested", "gate.rejected", "gate.landed"], "emits": ["work.requested"],
  "reads": ["features", "acceptance_tests_passing"], "spec": {"invariants": […], "steps": […]},
  "guessed": ["receives[0]", "receives[1]"], "pending": [], "requested": null,
  "expected_effect": {"horizon_s": 604800, "prediction": null, "edits": [
     {"edit": {"stock": "features", "rises": true}, "label": "Features ↑", "link": "/dynamics#s:features",
      "publishable": false, "why": "waits for a series"}]},
  "provenance": {…},
  "latest": {"change": "c9", "at": 1793505501, "quotes": ["…watch the ticket queue…", "…12am every day"],
             "added": {"receives": ["changes.requested", "gate.rejected", "gate.landed"]},
             "removed": {"receives": ["session.settled", "task.reported"]},
             "before": {"engagement": {"mode": "continuous"}, "steps": […]}}}
```

`guessed` names a whole field or one item (`field[i]`). `latest` is the latest change's
difference; the page marks it "just now" for ten minutes. `requested` is the owner's latest
request (§6.2) with no later op answering it: the page shows "asked the Supervisor · waiting". The
machine also gains `comparison`: `heard`, "attached, nothing measured" or "declared, neither
heard nor measured" (P5 §3; the same entries are open items in `design()`), beside P5's
`measured`. The top level gains `intended_edges` (`{from, to, kind, state, observed, gone}`) and `intended_types`
(declared event types and descriptions).

`predicted` lists the flows a declared machine's expected effect makes appear (`appears` edits),
drawn as expected ghost flows labelled "predicted by <machine>'s expected effect"; they carry no
machine association (`machines: []`, rule 6 as amended) and are `present` once a version has a flow
between those ends.

**Also:** `GET /api/intended?version=`, `/api/intended/versions`, `/api/intended/journal?after=`,
`/api/intended/diff?d=&v=&since=`, and `/api/intended/script?instrument=` (the script of an
option, read only inside the repository or the state directory, where P4 writes them, as logs are; its `[[collect]]` entry through `project.config`).

### 6.2 The page controls: observations and requests

A closed list; no control carries a value.

| control | where | kind | effect |
|---|---|---|---|
| `expect`, `unexpect` | D2 Changes panel; D3 drawer switch | observation | a mark on a discovered key |
| `ignore` | D2 Changes panel | observation | the suggestion to "ignored" |
| `confirm`, `discard` on a stock, effect or flow (or a pending change on one) | D1 drawer; D2 panel | observation | a proposal declared or discarded |
| `confirm`, `discard` on a machine or an attachment (or a pending change on one); `switch_kind` | E1–E3 status strip, card; the Universal \| Programmatic switch | **request** | nothing changes until the Supervisor applies it |

An observation, `POST /api/intended/control {control, part, id, change?, from}`, records a
declaration with `via: page` provenance, announced as `orchestra.intent.changed`; it changes no
machine, no configuration and no discovered version. A request, `POST /api/intended/request`
(same body), publishes `orchestra.intent.requested` with `source` `owner` (the person, a machine
under rule 2, which then appears as one) and `data` `{control, part, id, change, from}`. The
Supervisor answers by `apply`ing, with `provenance.request` the request's event id. Everything
else on the panels is rendered read-only with "ask the Supervisor" (§7).

### 6.3 Declaring: the plugin's API

`project.intended.apply(ops, provenance) -> {"version", "changes"}` in process; over HTTP, `POST
/intended` on the host's events endpoint (its token, as the experiments API, SPEC §3.1), body
`{source, author, turn, message, quote, request?, ops}`, answered `{"ok": true, "version",
"changes"}` or 422 `{"ok": false, "error", "index"}`. All ops of a call apply or none. Any op may
name `guessed` fields. The ops:

```
declare_stock {id?, name, unit?, near?, note?}       declare_effect {same}
declare_flow {from, to, name?}                       set_target {part, id|key, op, value, hi?, over_s}
expect {part, key} · unexpect · ignore · unignore    link {id, found_as}       alias {machine, observed}
propose_machine {id, envelope…, spec}                revise_machine {id, set, add, remove}
declare_event {type, description}                    set_expected_effect {machine, edits, horizon_s}
record_prediction {machine, prediction}              record_measurement {part, id, options, chosen?}
confirm {part, id, change?} · discard {…} · retract {part, id}   (part may be "attachment")
propose_attachment {machine, instrument, match?, instance_label?} · revise_attachment {id, set}   (P5)
```

`project.intended.read(version=None)`, `.diff(model=None, since=None)` and `.design()` read back;
`design()` (also `GET /intended/design` on the endpoint) lists the layer's version, each element
with state, presence, link and guessed fields, the open items (unconfirmed proposals, pending
changes, unanswered requests, unsettled suggestions, absent expected parts, unpublishable drafts)
and the last 20 changes, under 20 KB for 100 elements.

**Measurement options** (the goal's decision 2): `record_measurement` stores the options (`key,
title, how, kind, instrument, simulated, cost, caveat, clearance, provenance, commit,
first_points`) and `chosen`; the core proposes
none. It stores the instrument's name, never a copy of its configuration.

**Simulated series** (the coordinator's decision on item 10). A simulated option's `[[collect]]`
entry carries `simulated = true` (written by the plugin through `project.config_edit`), and the
instrument adds the label `simulated="true"` to every point. Discovery reads the series as any
other, and marks every stock, flow, equation and machine hypothesis fitted from a simulated series
`simulated: true` in the saved version, from the label, so the mark lives in `vN`. The pages draw
simulated parts distinctly ("simulated"); a prediction verdict never counts a simulated part as an
unpredicted change or side effect; a target backed only by simulated parts is never "met". When a
real option records, the plugin removes the simulated entry. Its points stay in the store, so
discovery reads a `simulated="true"` series only while a `simulated = true` entry names its
instrument; once the entry is gone the series is left out (`left_out`: "simulated, expired") and
the simulated parts leave the next version. The expected mark survives by key: the key
excludes `instrument` (§3.1), so a real series of the same name and identity labels takes it;
otherwise the Supervisor `link`s the declared stock to the real series' key.

**Draft instruments** (P4 need 2). An option offered and not yet chosen may record under a
`[[collect]]` entry with `draft = true` and `expires` (a time), and its points carry the label
`draft="true"`. Discovery leaves a `draft="true"` series out of its candidates (`left_out`:
"draft") while such an entry names its instrument, and also once the entry is gone, as it does an
expired simulated series. The core honours the flag and nothing more; the plugin sets it, removes
the entry at `expires` or clears the flag when the option is chosen (points written after that
are ordinary; the key leaves `draft` out, so they join the same stock).

## 7. The pages

The marks are the mockups' language (`mockups/README.md`). What each frame needs:

| frame | on the page | from |
|---|---|---|
| D1, D1-closed | the declared stock's ghost at `near`, "expected · declared by you", "not measured"; drawer: quote, status, How to measure it (options, the chosen one's recording line and sparkline, script and `[[collect]]` entry collapsed), Level waiting; Expected group, "N found · M expected" | `expected[]`, `measure`, `/api/intended/script` |
| D2 | the switch, on, "changes since v14"; rings, struck-through ghosts, the ○ ghost with its candidate line; Changes panel (+ with expect / ignore on every + row, −, ○), "against version 14, saved …" from `since_saved_at`, collapsed came-and-went and ignored; four legend entries; table marks | `marks`, `removed`, `changes` |
| D3, D3-closed | the drawer's switch "Expected: always show this stock" and provenance; the pin; Expected group | `expect`, `expected[]` |
| E1 | the proposed machine dashed violet, "unconfirmed", engagement sub-line; the highlight; the panel: status strip with confirm / discard (requests), quote, kind row, envelope, `spec` rendered in order, "a guess" on guessed items, expected effect rows with label, link and "waits for a series"; its card first | `intent`, `intended_edges` |
| E2 | "+ new link", "− link removed", "changed just now", "was continuous: …" from `latest.before`, "rewritten just now"; card chips marked | `intent.latest` |
| E3, -continuous, -external | kind row (Universal \| Programmatic) and `managed` (orchestra / external) separate from the engagement tabs; `spec` by mode | `intent` |
| E4 | a declared external machine measured and never heard (P5 §3): an outline "declared · never heard", no halo, no links, the rest shadowed by the highlight rule; its card "seen: never heard · measured by 1 instrument · 3 instances · last measured 1m ago" and "measured ×3"; the panel's kind, managed, engagement rows, "Instances: none heard on the bus", and **Measured by** after Instances (instrument, match, instance label, series, measured instances with last values) | `intent`, `comparison`, P5's `measured` |

**Read-only renderings, "ask the Supervisor":** E3's "+ argument" and "+ variable" and its
input-like boxes; D1's option radios; D1's "you can say whether that is this stock" (the
candidate line; linking is `link`, the Supervisor's); every field of the E panels.

**Mockup corrections for C2/C3:** E3 gets a kind row apart from its engagement tabs; E1's footnote
becomes "confirm asks the Supervisor", and "an AI agent: a prompt, its tools" is reworded in the
work's terms; D1 drops "on DEMO-35"; D2 gains the candidate line on Features and expect / ignore on
the + flow row (every + row, stock or flow, keeps expect / ignore; the frame changes to match).

**No frame yet, one line each (or deferred):** settled parts lose their ring, no other mark;
came-and-went and ignored are collapsed rows in the Changes panel; simulated parts with a "simulated" tag
and a hatched fill; candidates as "may be this stock" lines; a linked stock as "linked by you (assumption)"; alias
candidates as a line on the unheard machine's card; "declared · unheard" a dashed outline on the
map; a confirmed machine's verdict a chip on its expected-effect rows; event descriptions on
hover over an event type; a target a line in the drawer and Expected group; `retract` is the
Supervisor's, no control. Deferred to C2/C3: their exact styling.

**The highlight rule** (notes §13.2: "The Machine should be highlighted and the other shadowed
out, showing the Machine and the Event nodes with good colors, and the second-connection Machines
slightly less shadowed"), whenever the panel is open on a machine: the machine and its event
types at full colour (1); the machines one hop away (on those event types) slightly shadowed
(.7); two hops away (their other event types and the machines on those) more (.45); the rest at
`ng-dim` (.1). An edge takes the lesser of its two ends; links
the latest change removed stay drawn as ghosts at full colour. Both pages refresh while open, so
changes appear without a reload.

## 8. Invariants amended

Each is stated in the commit that builds it (C1); SPEC follows (C5).

**Rule 2.** Replace "System dynamics has no machines" with "The discovered model has no machines;
the declared layer stored beside it (the intended model) names machines, never in a stock, flow
or equation." Add after the sentence on `Plugin.machines`:

> The owner may declare machines (the intended model, `orchestra/sd/intended/`), through a plugin
> or by confirming a proposal. A declaration persists until retracted. A declared machine is shown
> as declared, and as heard only once its `source` is on the bus; its declared envelope and `spec`
> are shown as the declaration, apart from what is observed, and never override what is
> observed, never make a machine exist in the observed layer, and say nothing about flows.

**Rule 4.** Add: "The model's versions are of two kinds: discovered (`vN`: stocks, flows,
equations) and declared (`dN`: the intended model); a change to one never makes a version of the
other, and a comparison names one of each."

**Rule 5.** After "the model through `orchestra.sd.store.ModelStore`" add: "; the intended model
through `ModelStore.intended()` (`project.intended`), in `<state>/model/intended/`, written only by
the host and the web server; nothing else opens anything under it."

**Rule 6.** Add: "A machine's draft expected effect is an unpublished prediction, not an
association; the expected flows drawn from it carry no machine."

**Rule 7.** Add after "Stocks are discovered, not configured":

> A stock, effect or flow may be declared, and a discovered one marked expected (the intended
> model): an expectation drawn beside the discovered model, never a part of it. A declaration
> binds no series, is not (yet) handed to discovery, changes no equation, and is matched to what
> discovery finds only by the `link` op; marks derived from labels (candidates) are display only.

**Rule 9.** Replace "except for observations: rediscovering the model …" with:

> except for observations: rediscovering the model (…), and a closed list of intended-model page
> controls that carry no values: `expect`, `unexpect`, `ignore`, and `confirm` and `discard` on a
> stock, effect or flow. Each records a declaration with its provenance and changes no machine, no
> configuration and no discovered version. A machine's `confirm`, `discard` and kind switch are
> requests: published as `orchestra.intent.requested` from `owner`, changing nothing until the
> Supervisor acts.

Why: the scenario has the user clicking (D2 "expect", E1 "confirm"). Stock and flow controls
change what Orchestra believes, like the rediscover button; a machine's confirm is what a plugin
starts a machine on, so it goes to the Supervisor (decision D1).

**Not a rule change:** discovery gains one flag, `simulated` on every part fitted from a series
labelled `simulated="true"`, and the verdict and targets skip such parts (§6.3). Rule 3 is unchanged: the host's
announcement is its own type, and a request is a person's event whose `data` Orchestra reads as
its own type (`orchestra.intent.requested` joins rule 3's list of Orchestra types machines publish,
a one-line addition made with C1).

## 9. What P4 and P5 need

| # | answer |
|---|---|
| P4.1 API | `project.intended`: `apply`, `read`, `diff`, `design` (§6.3); provenance §4; `guessed` per op. |
| P4.2 time | every change has an id and `at`; `latest.at` drives "just now". |
| P4.3 fields | the envelope (§2, P4 §2.3) is checked; `spec` is P4's, per kind and mode, with the table of §2 as the starting schema and the "no AI terms" check. |
| P4.4 options | `measure.options`, `measure.chosen`, in the declared layer. |
| P4.5 matching | never automatic: `candidates` on read, `link` to set; P4 links in the same turn it instruments when they are the same quantity. |
| P4.6 simulated | the `[[collect]]` flag and label; parts marked `simulated` in `vN`; read only while the entry exists; P4 removes the entry when a real option records (§6.3). |
| P4 need 2, drafts | the `draft = true` + `expires` flag on an instrument entry, which discovery leaves out (§6.3); the core honours it, the plugin sets and removes it. |
| P4.7 ids | keys (§3.1). |
| P4.8 page events | `orchestra.intent.changed` for observations, `orchestra.intent.requested` (source `owner`) for requests, which P4 handles; filter `…:subject=machine:<id>`. |
| P4.9 predictions | `rises`/`falls` and `appears` (§2); unpublishable until linked. |
| P4.10 summary | `design()`. |
| P5 | `propose_attachment`, `revise_attachment` on the same `apply`, with `confirm`/`discard`/`retract` taking `part: "attachment"` (confirm and discard on the page are requests), comparison entries defined in P5; `alias` (§6.3) joins a declared id to an observed source or a counted `<prefix>.<name>`, never inferred (name matches are `alias_candidates`, on read); `managed: external` takes any mode; the rule-5 amendment (§8); `dN` covers attachments (§5); observed facts derived on read (§5); persistence per element (§3.3). |

## 10. Acceptance tests

Unit tests on the store and diff, API tests against the web app on a temporary state directory,
and the C2/C3 screenshot comparison against `mockups/out/` (with §7's corrections).

1. One call with several ops writes one journal line and one `dN`; a refused op (index 2 of 3)
   writes nothing and answers 422 with `index: 2`.
2. Past `dN` read back unchanged after later calls; numbered without gaps.
3. Every element carries `provenance` (`author`, `via`, `at`); a plugin call keeps `source`, `turn`,
   `message`, `quote`; a page control keeps `control`, `page`, `from`; every change has an id.
4. The store refuses any envelope key it does not know, an id not matching
   `^[a-z][a-z0-9_]{1,40}$`, a `kind`, `managed`, `mode` or `missed` outside its list, and `at`
   without `scheduled`; it accepts `managed: external` with every mode; it stores `spec` as sent.
5. A declared stock with no series is in `expected` with `present: false`, `measured: false`, and
   in `changes` as ○; the model's `stocks` are unchanged by it.
6. Discovery with and without a declared layer produces identical `model` bodies (not `saved_at`).
7. A stock marked expected and absent from a later version is in `expected` with `present: false`
   and listed as ○.
8. A key in v15 and not v14 is `new` by default and with `since=14`; `since=off` drops the marks.
9. A flow in v14 and not v15 is in `removed.flows` with its v14 rate and machines.
10. A stock whose discovered id changes between versions while its key holds is neither new nor
    removed, and its mark holds; a collector renamed (instrument label changed) keeps the mark.
11. A part `sd.prior` carries into a new era is not new; a key counts once.
12. A suggestion present in `announce_hold` consecutive versions is settled (no ring, not in
    `changes`, still expectable); one that leaves first is in `came_and_went` and returns with its
    key.
13. `ignore` moves a suggestion to `ignored`; `unignore` returns it.
14. A declared flow with a `null` end, or two flows between its ends, gives `candidates` and no
    match.
15. `/api/intended/control` accepts exactly the observations of §6.2 and refuses a machine or attachment target
    or any value (400); `/api/intended/request` publishes one `orchestra.intent.requested` from
    `owner` and writes no `dN`; neither writes `orchestra.toml` or a `vN`.
16. A request with no later op answering it shows as `requested` on the machine; an `apply` with
    `request` set clears it.
17. A series labelled `simulated="true"` yields a stock marked `simulated` in the saved version;
    a prediction verdict does not list it as unpredicted and a target on it is not met; after the
    entry is removed its points stay but it is gone from the next version (`left_out`), and a real
    series of the same key (the `simulated` label left out) keeps the expected mark.
18. Each accepted call is announced once as `orchestra.intent.changed` by `orchestra-host`, also
    one written while the host was down; the filter `…:subject=machine:<id>` selects it.
19. The diff cache holds only structural entries; with the same `dN`, `vM`, `vK`, era, a machine
    first heard after the file was written reads `heard: true`; a slow metrics read past the time
    limit answers with the missing facts named.
20. An op carrying a derived field (`present`, `heard`, …) is refused.
21. `record_measurement` options come back as recorded with the recording read from the metrics
    store; the core adds none; `/api/intended/script` reads the repository and the state
    directory and refuses any other path.
22. `link` alone sets `found_as`; a stock recorded by the chosen instrument appears only in
    `candidates`. An effect may link to a series key.
23. A declared machine never heard is in `/api/machines` with `unseen: true` and `intent`; once its
    source publishes, the same entry has observed fields and `heard: true`; the card's kind
    switches from declared to announced; `alias` joins a counted `<prefix>.<name>`.
24. An undeclared observed machine has `intent: null`.
25. A revision by `owner` with a quote on a proposed machine applies at once, with
    `latest.added`, `removed` and `before`; the same revision on a confirmed machine, or one by
    another author, is `pending` until confirm/discard `{change}`.
26. `set_expected_effect` adds no flow and no hypothesis; edits carry `label`, `link`,
    `publishable`; an edit on an unlinked declared stock is unpublishable; `record_prediction`
    links the verdict.
27. `{"stock", "rises": true}` on a cumulative stock is met when its slope after the change exceeds
    its slope before by `|z| ≥ 2`, and absent when the slope is unchanged though the level rose.
28. A target on a flow is judged on its mean rate over `over_s`; on a stock, its mean level.
29. Browsing `vN` returns the `dN` current at its `saved_at`.
30. E1: node opacity 1 for the machine and its event types, .7 for one-hop machines, .45 for the
    two-hop ring, .1 for the rest; edges the lesser of their ends.
31. A declared machine with an `appears` edit in its expected effect puts that flow in
    `intended.predicted` with `machines: []`, adds no flow and no hypothesis to `vN`, and is
    `present` once a version has a flow between its ends.
32. A series labelled `draft="true"` is in `left_out` ("draft") while its entry exists and after
    it is removed; points written after the flag is cleared enter discovery under the same key.
33. A declared machine with an attachment matching nothing has `comparison` "attached, nothing
    measured"; with neither events nor a measured attachment, "declared, neither heard nor
    measured"; both are open items in `design()`.
34. The Core page answers with `intended/` missing, corrupt or locked (rule 8).
35. Each frame of §7 renders from C1's answers and matches its mockup in the C2/C3 screenshot
    comparison.

**Coverage of notes §13.4 (the core's part):** related series enter with no declaration (6);
expected stock drawn and listed when absent (7); new parts listed until answered, never dismissed
(12, 13); placeholder series marked (17); a new machine's node and panel (23, 35); the highlight
(30); live changes (25, 35); the engagement change (25); each kind's fields, no AI terms (4, and
P4's `spec` check); predicted flows shown and judged (26, 27, 31); no page control changes the system
(15). The Supervisor's tests (instrument within one turn, options, script readable) are P4's.

## 11. Out of scope and open questions

Out of scope: instruments on machines and instances from labels (P5); how the Supervisor
measures, drafts, refines, links, answers requests and publishes predictions (P4); piles, items
and the floor (P3); starting a confirmed machine (the agents' plugin).

1. **Rule 9, the other way.** Every click, observations included, goes to the Supervisor as a
   request. Rule 9 then needs no amendment; the price is a chat round trip per click.
2. **Declared at once vs "not real until the user confirms it."** The default follows the
   approved D1 frame: what the owner asks for is declared at once; machines are proposed.
   Should owner-asked stocks also wait for a confirm?
3. **"Unexpected" machines.** `design-backwards.md` §3 marks an undeclared observed machine; the
   approved E frames do not. The diff records `unexpected`; the map does not draw it.
4. **Declarations as priors** (D4): rule 7 as amended says "not yet".
5. **Simulated parts in the loop.** Placeholders exercise the model "to make sure the rest of it
   works correctly", marked in `vN`; whether a simulated part may seed the next era's prior
   (`sd.prior`) is left open (default: it may not).
6. **Suggestion volume** under churning strategies: settling, collapse and the Supervisor's
   triage (P4) are the defences.
7. **Effects drawn as boxes?** An effect found only as an input has no level box; left to C2.
