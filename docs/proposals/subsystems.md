# Proposal: subsystems, boxes in the one map

Status: proposal, 2026-11-02. Steps 1, 2 and 3 (§7) built. The owner answered §8 the same day (§8). It answers the
owner's words of 2026-11-02 (`docs/roadmap/GOAL-2026-11-02-second-half.md`, the 21:49Z entry) and
sits beside D2a, the names proposal in flight (scopes and nouns become tags beside a place-only
name). No invariant of `AGENTS.md` changes; SPEC §10 gains a paragraph per step. This
document's decisions are B1–B15; a `Dn` is the owner's (`docs/roadmap/decisions.md`).

## 1. The question

The owner: "We could also move that text to a 'subsystem', we haven't built subsystems yet but we
do want the ability to filter our dynamic system models and we may want to draw them in their own
boxes in the same map, we would hope to see very few flows going between the systems to show
their separation." And earlier the same day: workflows are sub-graphs (a focus) of the Event Map
and the model, never a separate model; and rule 4: never split topics, models or views per
package or domain; packages and metadata label, they never separate.

So a subsystem is a way of looking at the one model: the pages filter by it and draw boxes from
it, and its quality is the number of flows that cross between boxes.

## 2. What a subsystem is

**B1. A subsystem is a group of a partition of the one model.** A partition divides the model's
stocks, flows and machines by the values of one label the series and events already carry: a
workflow, a package, a team, a service. Each value is a group; every part is in at most one
group, or unassigned. The model is not split: discovery, equations, loops, hypotheses, keys and
versions are those of the whole model, and a partition changes none of them.

**B2. Derived first, declared later.** A partition is derived on read from the labels of the
model's series, display only, like the candidate marks of the intended model (§3.2 there): it is
saved in no version and binds nothing. Later (§5) the owner may declare a subsystem in the
intended model; a declared subsystem is a declaration with its provenance, never a split.

**B3. Which labels.** Every label on a stock's series (its own series, or the level discovery
keeps for a hidden stock, `evidence["level"]`), except who wrote it (`NOT_IDENTITY`: instrument,
machine, source, project, instance) and Orchestra's own flags (`simulated`, `draft`). A label with
fewer than two values among the stocks partitions nothing and is not offered. The writer labels
are excluded because a series' writer is never a machine's subsystem any more than it is the
machine (rule 7: a machine's existence, or its place, is never inferred from who wrote a series).
No label's name is known to the core (rule 1): `workflow`, `step` and `team` are data. Amended
2026-11-02 (the coordinator, after the delivery demo opened on a pile's state): a stock its
instrument's places name (`sd.titles`: a count view's `place` label and the labels its value spells,
a step and a state) is partitioned only by its **scope**, the labels its place value does not spell,
recorded as its `label=value` tags (B14: a subsystem's label is the tag the name no longer carries);
never by its place label or the labels the place spells, which say where a thing is, not which
subsystem it is in. A hidden stock's level labels are classified the same way (its tags). A stock
whose series has no count view keeps the rule above.

**B4. Several partitions side by side in the API, one at a time on the page.** The API reports
every partition the series carry, so the Supervisor and a plugin can compare them; the page draws
boxes for one partition at a time, since nested or overlapping boxes from two labels would make
the map unreadable. Nested subsystems (a team's services) are §8's question 3.

**B5. The default partition is the one the data separates best,** never a label chosen by name:
the partition that keeps the most flows between two stocks inside one group, then crosses the
fewest, then assigns the most stocks, then has the fewest groups, then by the label's spelling.
A label that names a step crosses at every move; one that names a workflow keeps its
moves inside. It is only where the page starts (B10).

**B6. A stock whose series carries no such label is unassigned,** drawn outside every box, inside
the system's frame, as today. Unassigned is not a group: no box, no title, never a side of a
crossing. A hidden stock is placed by its level's
labels when discovery keeps one, and is unassigned otherwise (SD Lab's hidden stocks).

**B7. A flow is placed by its ends, never by its counter's labels.** Inside a group when both its
ends are stocks of that group, or one is and the other is outside the system (a cloud); crossing
when its ends are in two groups; touching the unassigned when an end is an unassigned stock. A flow whose counter says `workflow="a"` between stocks of `a` and `b` still crosses: what
crosses is what moves material between boxes. Each
flow counts once; a co-flow (`<flow>@<writer>`, the same counter moving another stock) is a flow
of its own and counts on its own ends.

**B8. The separation measure is the count of crossing flows per pair of groups,** computed from
the shown model's flows (the latest discovery, or the version asked for), unordered by pair, each
crossing flow listed with its id so the page can draw it with its direction. Beside it, `joined`: flows between two stocks of one group (not those from or to outside). Two kinds of part are apart:

- a flow fitted from a simulated series (`evidence["simulated"]`, `sd.simulated`) is counted in
  its pair's `simulated`, never in `count`, `joined` or `crossed`: a placeholder's numbers neither
  join two subsystems nor keep them apart, and the page draws such a crossing dashed, as it
  draws simulated parts;
- a draft series is never in a model (discovery leaves it out), so it never places a stock or
  counts a flow; the `draft` label is never a partition.

Parts an era carries from its prior (`sd.prior`) are drawn and so are counted, each as itself.
The measure is shown, never judged: many crossings are a finding about the system or the label.

**B9. Machines are placed only by their hypotheses.** A machine is in a group when every flow it
is a hypothesis for (`sd.attribute`, the flow's `evidence["machines"]`) has its assigned ends in
that group; it **spans** groups when they are in several, and is then drawn **outside every box**
(never between them, never inside one) and listed as outside, "in two subsystems: outside the
boxes" (the owner, 2026-11-02: "a machine should only belong to one subsystem, i think. if it needs
to belong to 2, it is probably outside of the box, it would be part of a different system for
interconnectivity"); it is unassigned when it is a hypothesis for no flow. Never by a `machine` label on a series, and the
placement is not an association: it reads the hypotheses and adds none (rule 6). On the Event
Map (§3) a machine may also be placed by what it announced (`group`, `package`, SPEC §2) and a
declared machine by its declared `tags` (§5).

## 3. Drawing

**B10. Boxes in the same diagrams, never a separate map.** The Dynamics diagram and the Machines
page's event map each gain a "boxes" control in their own bar, beside tidy and reset: off, or one
of the partitions the API reports, the default first, each named by its label and how many groups
and crossings it has ("workflow · 3 boxes · 2 crossing"). Boxes are **on when the page opens**, by
the default partition (the owner, 2026-11-02: "sub 1. yes, boxes on"); one partition at a time, no
nesting ("sub 3. ... we dont need them now"). With boxes on:

- **Dynamics.** Each group is a box inside the system's frame, titled by its label's value (or a
  declared subsystem's name, §5), holding its stocks, the clouds of its flows from and to outside,
  and the auxiliaries its rates read when no other box's rate reads them. Unassigned stocks sit
  outside every box, inside the frame; so does every machine spanning two groups (B9), on the
  Dynamics page in the note under the diagram and the phone list, since the diagram draws no
  machine node. As built (step 2): the clouds keep the cloud rule (just outside the frame, beside
  their stock), so a box holds its stocks, its places and its auxiliaries; a pair's count is
  written whole where the gap between the boxes holds it, else its count alone ("1 flow", the
  sentence on hover). A crossing flow is drawn from box to box, and each pair's count is written
  between the boxes ("2 flows between delivery and hotfix"). ELK lays the boxes out as compound nodes (`sd-layout.js` already draws the system as a
  box of its own).
- **Event Map.** Each group is a box around its machines; an event type or channel is inside a box
  when every machine that publishes or listens for it is, and between boxes otherwise. A hand-off
  from a machine in one box to a machine in another is drawn across, and counted on the box's edge
  the same way. Boxes replace the ring anchors of announced groups (`groupAnchors`) while on;
  spanning and unassigned machines sit outside every box. As amended by the owner (2026-11-02: "The
  event map should show multiple system boxes as well"): every group is a box, as on the Dynamics
  diagram, side by side, one no machine acts only in drawn with its title and "no machine acts only
  here" inside, boxes on by the default even when every machine is outside.

**B11. A subsystem is a focus you can also draw as a box.** Focus is a filter to one; boxes are all
at once. With boxes on, each box's title is a focus chip of the core's own offer
(`Orchestra.focus.offer`, title the value): clicking it focuses that subsystem exactly as a
plugin's focus does, the box kept as the frame of what is shown and the crossing flows drawn to
grey named stubs (`Focus.dynamics`, `Focus.eventMap`), so the stub's name says which box it
leads to. A plugin's focus with boxes on draws its subset in the boxes it touches; neither changes
the other.

**B12. Reset, saved layouts and the hash.** Turning boxes on, off or to another partition is a new
structure and is laid out exactly as reset lays it out (SPEC §10: a new structure is laid out as
"reset", fitted). A dragged node stays in its group: a box is the hull of its members, so a drag
moves a member and the box follows, never membership. Each partition keeps its own saved layout
(the layout key gains `boxes=<label>`). The choice is kept in the hash beside the focus
(`#boxes=<label>&focus=<title>`), so a link carries both.

**B13. Both widths.** At desktop width, as above. At phone width the Dynamics page shows the model
as a list (`phoneList`) and the Machines page as lines in groups: with boxes on, the list gains
one heading per group (its value, its stocks or machines under it), then "between subsystems" with
the crossing flows or hand-offs by pair, then "outside every subsystem" with the unassigned; on
the Machines page every group keeps its heading, an empty one saying "no machine acts only here"
and who acts there and elsewhere (the owner, 2026-11-02).

## 4. Names: nothing said twice

**B14. A subsystem's label is exactly the tag the name no longer carries.** D2a makes a stock's name
its place only ("items held at write") and moves its scope and noun to tags (`titles.py`: the
labels a place's value does not spell are its scope, today said in brackets only when two scopes
share a thing, "(hotfix)"). The scope label is what a partition is made of; so:

- with boxes on by a label, that label's tag is not shown on the parts inside its box (the box's
  title says it once), and is shown on the unassigned and on a crossing flow's two ends only as the
  box they are in;
- with boxes off, the tags show as D2a shows them;
- a declared name linked to a discovered part ("named by you") stays on the part; a declared
  subsystem's name titles its box, with "named by <who>", and the label's raw value is shown in the
  box's drawer only;
- `titles.py` is unchanged by subsystems: it already knows no label's name, and the partition reads
  the labels, never the titles.

## 5. The API, what a plugin may offer, what the owner may declare

**B15. The core reports keys, nothing per domain.**

`GET /api/dynamics/model` gains `model.subsystems` (built in step 1):

```json
{"default": "workflow",
 "partitions": [{"label": "workflow",
                 "groups": [{"value": "hotfix", "stocks": ["s1"], "flows": ["f1"], "machines": ["planner"]}],
                 "unassigned": {"stocks": ["disk"], "flows": ["f9"], "machines": ["idle"]},
                 "crossing": [{"between": ["delivery", "hotfix"], "flows": ["f4", "f5"], "count": 1, "simulated": 1, "simulated_flows": ["f5"]}],
                 "spanning": [{"machine": "worker", "groups": ["delivery", "hotfix"]}],
                 "joined": 3, "crossed": 1, "crossed_simulated": 1}]}
```

Ids are the shown version's; anything kept across versions uses keys (intended model §3.1). `GET /api/machines` gains `subsystems` of the same shape over machines, event
types and hand-offs (step 3): the model's partitions carried to machines by B9, and one partition
per announced field that groups machines (`group`, `package`), named by the field. Neither knows a label's meaning (rule 1).

**A plugin may offer a partition as it offers a focus,** on the page:
`Orchestra.subsystems.offer({title, groups: [{title, machines, events, stocks, flows}]})`, each
group a focus subset in the same keys (`{name, labels}` series included, keyed by `Focus.keyOf`).
The Workflows plugin would offer "workflows", one group per definition, from the focus it already
builds (`pages/focus.py`), placing machines by the definitions that name them,
which no series says. It is listed after the derived partitions, display only, stored nowhere.

**The owner may declare, through the Supervisor only** (rule 9; no page control is added to the
closed list): a `subsystem` element in the intended model, `{id, name, note, label, value}` (a
name for a label's value: "the hotfix line"), or `{id, name, note, members}` (stocks and flows by
key, machines by id) when no label says it. It is declared with its provenance through the plugin's declaring API the Supervisor already uses (`intended-model.md` §6.3), shown "named by you" or "proposed by the
Supervisor", and drawn as a box under its name; a declared machine's `tags` place it in a
declared subsystem's box. A declared subsystem binds no series, changes no equation and no
association, and is never handed to discovery (rule 7 as amended); its members are matched by
key, and a member no longer in the model is shown as a ghost in its box, as an expected part is.

## 6. What is not built

No new page, wizard or chat dock. No per-subsystem model:
no discovery per group, no version per group, no equation fitted inside a box, no loop split at a
box's edge. No equation changes and no change to discovery, keys, hypotheses or titles. No
nested or overlapping boxes. No judgement of the separation measure (no "too many crossings"
attention). No page control that declares one. No partition by an event's `data` (rule 3).

## 7. Build plan

1. **Server, additive (built).** `orchestra/sd/subsystems.py`: pure, the
   model in, the partitions out (B3–B9); `web/dynamics.py` `model_view` adds
   `model.subsystems`; SPEC §10 says so. No page reads it yet. Tests, `tests/unit/test_subsystems.py`: writer labels
   and flags are never a partition; groups, unassigned and hidden stocks; flows inside, crossing
   (simulated apart) and touching the unassigned; machines by hypotheses; the default; the model
   view carries it and changes nothing else.
2. **The Dynamics diagram's boxes.** The boxes control, compound nodes in `sd-layout.js`, the
   box-title focus chips (B11), the hash and layout key (B12), the phone list's headings (B13), the
   tags left off inside a box (B14, after D2a merges). Tests: Node tests beside `tests/focus` for
   the pure part (a box per group, crossing flows between them, unassigned outside, a focus on a
   box cutting to it with stubs); `tests/layout` on a saved two-workflow model, scoring no worse
   than without boxes and every member inside its box; an acceptance check on the delivery demo
   that the default partition is drawn with its crossing count.
3. **The Event Map's boxes, and the declared and offered partitions.** `/api/machines`'s
   `subsystems` (B15) in `web/machines.py`, the event map's boxes, `Orchestra.subsystems.offer`,
   the `subsystem` element of the intended model and its op. Tests: unit tests for the machines'
   partitions (by hypotheses, by announced group, event types inside or between boxes, hand-offs
   crossing); the op's checks and provenance in `tests/unit` beside the intended model's; a Node
   test that an offered partition is listed and drawn and stored nowhere; the Workflows plugin's
   offer tested in its own repository.

   As built (2026-11-02): `web/machine_subsystems.py` (`/api/machines` `subsystems`: groups with
   `machines` and `events`, `unassigned` machines and events, `between` event types, `crossing`
   per pair with its `handoffs`, `count` the pairs of machines and `subjects`, `spanning`; each
   partition's `source`: `labels`, `declared` or `announced`); `sd/subsystems.place` (a partition
   from any assignment, the declared one's too); `sd/intended/subsystem_ops.py` (the op) and
   `sd/intended/subsystems.py` (`with_declared`: the gathering partition `declared` first, a
   name on the group it names, ghosts by key); `static/subsystem-offers.js`
   (`Orchestra.subsystems`); `subsystem-boxes.js` `applyMap`, `anchors`, names and ghosts;
   `NetGeometry.separateBoxes` and a box force for the force-laid map. A box's "drawer" is its
   title's hover: who named it, the raw value, its note, its ghosts. Not done: the Workflows
   plugin's offer (one group per definition from `pages/focus.py`, its machines and event types,
   its piles' series), left to that repository; `tests/layout` has no saved machines graph with
   groups (the map is laid out by d3's forces, not ELK; `NetGeometry.separateBoxes` is tested in
   `tests/subsystems/map-boxes.test.mjs` instead).

## 8. Questions for the owner

Answered 2026-11-02, verbatim: "sub 1. yes, boxes on / sub 2. a machine should only belong to one
subsystem, i think. if it needs to belong to 2, it is probably outside of the box, it would be part
of a different system for interconnectivity / sub 3. nested subsystems sound like a good idea but
might not be, we dont need them now / sub 4. yes it can gather". So: on at open (B10); a spanning
machine outside every box (B9); no nesting; a declared subsystem may gather members no label
groups (§5's `members`, step 3).

1. Should the page start with boxes on, by the default partition, or off until you pick one?
2. When a machine spans two subsystems, should it be drawn between their boxes or in the one it
   is most confident for?
3. Do you want nested subsystems (a team's workflows) later, or is one partition at a time enough?
4. Should a subsystem you declare be able to gather parts no label says belong together, or only
   name a label's value?
