# Instruments on machines: the integration step

Status: reviewed, 2026-11-01 (panel round 1, judge's verdict round 2); aligned to intended-model.md as of its round-1 revision; coverage pass 2026-11-01, aligned to intended-model.md as merged (round 3). Built in the core: C4 of milestone M2, merge
09b001f4 (attachments, instances from a label, the Machines panel's "Measured by" and the
Instruments page). Proposal 5 of `design-backwards.md`
§7, written from that file's §5 and `design-backwards-notes.md` §9 (items 7 and 12, and "the
invariants this touches") and §13.1. It builds on proposal 2 (`intended-model.md`, as
merged), which defines declared machines and the declared layer; §8 lists what is taken from
it.

## 1. Purpose

The machines that matter most at work already exist, and none of them will ever publish an event on
Orchestra's bus: a Jenkins job pipeline, a Postgres cluster, the company's merge gate, SAIL. The
Machines page lists what the bus has heard, and the machines a source's counted traffic names on
another system's bus (rule 2, `sources/traffic.py`); an instrument that measures Jenkins is, rightly,
not a machine (rule 7). So Jenkins' series are in the metrics store and on the Dynamics page, and
Jenkins is nowhere on the map.

The owner: "The existing Machines will need to be mapped, and this is where the fun part happens,
because this is the integration step. Because the Machines aren't likely to emit their actual
metrics, and because we would want to incorporate and model existing machines, we need to attach
our measurement instruments to Machines. This is where we would do it."

So an existing machine is **declared** (P2 §2, `managed: external`) as a placeholder on the map, and
**instruments are attached to it**: through the Supervisor, the owner says which series measure
which declared machine, and which of their labels counts its instances. The instrument still
measures; the declared machine is where the measurement hangs on the map.

Counted traffic is the precedent and the contrast. A source's `[sources.producers]` is already an
owner's declaration that names a machine on another bus, and counts make that machine seen and
active, because a count is the machine's own work on a channel. An attachment's series are
measurements *about* a machine (its queue length, its connections, its `up`), so they never make it
seen or active.

## 2. What "attached" means, and what it does not

An **attachment** is one declaration: *these series measure that declared machine*. Its parts:

- **machine**: a declared machine's id (P2 §2). Only a declared machine takes an attachment; a
  machine the bus already knows is declared first (P2's `propose_machine` and `confirm`).
- **instrument**: the name of a `[[collect]]`, a `[[scrape]]`, a plugin's collector
  (`<plugin>.<name>`) or a `[[sources]]` entry, as the Instruments page names it.
- **match**, optional: a series-name prefix and label matchers, equality (`job="postgres"`) or
  regular expression (`job=~"deploy-.*"`, a Jenkins folder of jobs). For a source, the labels are
  its canonical ones, after `[sources.labels]` aliases (`svc` and `service` are one label). With no
  match, every series the instrument writes is this machine's.
- **instance label**, optional: the label whose values are the machine's replicas (§2.1).

It is **declared provenance**, of the same kind as the `instrument=<name>` label: what was
measured, and where on the map the owner hangs it. In particular:

1. **It never makes a machine seen or active.** A declared machine with attachments and no events
   or counts is *measured, never heard*: no "last seen", never "active" (activity is the bus's and
   counted traffic's, SPEC §10). Its last point is shown under its own name, *last measured*.
2. **It never binds the machine to a flow.** `orchestra/sd/attribute.py` is untouched and never
   reads the declared layer. The cost is stated: a machine that is only attached never gets a flow
   hypothesis, and its dialog says what it says today, "none hypothesised yet". Its route to the
   model is a prediction (P2 §2, "a machine's expected effect"; notes §13.3), judged when the flow
   appears. Using attached series as evidence for a hypothesis is §9, question 4.
3. **It changes no point and no model.** Nothing is relabelled or rewritten; discovery never reads
   attachments, so the same data gives the same stocks, flows, equations and evidence with or
   without them. An attachment is never a **binding**: the word notes §9 item 8 uses for an
   effect's instrument ("an instrument is attached to each so discovery can find it") means a
   series discovery reads for a declared stock or effect, P2's `found_as` and P4's
   `record_measurement`. A machine attachment is never one.
4. **An attachment never makes a machine.** The direction is name → series. A new value of the
   instance label adds an instance under the machine the owner declared, never a machine.

**A declared id meets the observed names** by P2's alias (P2 §6.3): the machine's id is the
`source` it is expected under; when it is observed under another name (an observed `source`, or a
counted `<prefix>.<name>`), `alias {machine, observed}` joins them, a declaration, never inferred.
Joined, the observed facts win (rule 2), and the attachments stay.

**Reading a label is not inferring from it.** Rule 7 forbids inferring a machine's existence from
who wrote a series and associating a flow with a machine from a measurement's label. Here the owner
reads a label on purpose, in a declaration, to say which series measure the machine they declared
and how to count its replicas. Orchestra infers neither existence, nor activity, nor flows from it.

### 2.1 Instances, and when a series counts as measured

"They might say 'postgres database', but if they have one then you know they have more than one."
A name declares a machine; how many replicas it has is learned.

- **Per attachment, never unioned.** One exporter's `server="db-1"` and another's
  `instance="db-1:9187"` are the same replica under two spellings; Orchestra cannot know that, so
  each attachment's instances are listed under it, and the machine shows the largest count, never
  a sum or a union.
- **Replicas only.** An instance label names copies of one thing (`server`, `instance`, `pod`). A
  label of kinds (Jenkins' `job`) belongs in a match: two kinds are two attachments, or two
  declared machines.
- **A cap.** An attachment whose instance label has more than 50 values (`[intended]
  max_instances`) shows "N values: too many for instances" and no list.
- **The window.** A series, or one instance's series, is **measured** while its last point is
  within `max(1 h, active_within(cadence))`, where `cadence` is `orchestra/cadence.py`'s median
  gap over its last `BEATS` points: the rule bus activity uses, applied to points. A collector run
  every minute is measured for an hour after its last point; a series a nightly Jenkins job writes
  stays measured between runs. A value past its window is listed as **quiet**, not dropped.
- **Measured means data is arriving, not that the thing is up.** The last value is shown:
  `pg_up{server="db-2"} = 0` is measured, and the page says 0.

### 2.2 What the metrics store must answer

Today's interface cannot answer this cheaply: `series()` returns names and labels only, and
`latest()` and `dump()` on VictoriaMetrics export from `start=0`, the whole history
(`orchestra/metrics/victoria.py`). This proposal adds one method to `MetricsStore`, a **backend
contract change**:

```
recent(prefix, matchers, since, keep=1) -> [(name, labels, [(ts, value), …])]
```

every series whose name starts with `prefix`, matching `matchers` (equality and `=~`), with a point
at or after `since`, and its last `keep` points; bounded by `since` on every backend (an export
with `start=since` on VictoriaMetrics, the index on the file store). The reader asks with `since` =
now − 2.5 days (the longest window §2.1 can give) and `keep = BEATS`; a series with
fewer than two points in that span has no cadence and gets the hour. A conformance test in
`tests/metrics` runs it against every backend.

A **source** (a `[[sources]]` entry: the company's Prometheus) is read as counted traffic is: by the
web server's background reader, from the source's inferred definitions, in the web server's share
of the store's rate (`sources/limits.py`), under a `Budget`. Its series are never copied into the
metrics store (rule 5). An instance label that the definition's `by` sums away is refused when the
attachment is made, with that reason.

## 3. How it is recorded, and how it is shown

**Recorded** in P2's declared layer (`<state>/model/intended/`), never in `orchestra.toml`: the
instrument is configuration (it runs), the attachment a declaration (what the owner believes). The
ops P2 §6.3 lists for this proposal, `propose_attachment {machine, instrument, match?, instance_label?}` and
`revise_attachment {id, set}`, with P2's `confirm`, `discard` and `retract` taking `part:
"attachment"`; each carries P2 §4's provenance. An attachment is **proposed** or **declared** (P2
§3), versioned with the rest of the declared map in P2's `dN` (P2 §5), never with
equations. **Measured** is a flag the comparison derives on read (P2 §5), never stored or
versioned. A declared attachment that matches nothing is on P2's comparison as "attached, nothing
measured"; a declared machine with neither events nor a measured attachment as "declared, neither
heard nor measured".

**Confirming and discarding are the Supervisor's**, in the plugin. P2's page observations (§6.2,
`POST /api/intended/control`) refuse an attachment. The page's confirm and discard buttons, for
attachments as for declared machines, publish the person's request as an event
(`POST /api/intended/request`, `orchestra.intent.requested`) that the Supervisor acts on; no core
route writes, confirms or discards one.

**The Machines page.** The surface is today's machine dialog (`static/machine-dialog.js`), or P2's
details panel where P2 replaces it. A declared machine is drawn as P2 draws one (frame
E3-external). Its card's `seen` row reads "never heard · last measured 2 min ago". The dialog gains
a **Measured by** section after Instances and before Log: per attachment, the instrument and its
kind, the match, the instance label, the state, the series it matches (names and counts), and its
measured and quiet instances with their last values. Measured instances are a table there and a
"measured ×3" row on the card, apart from the bus's instance chips. The Flows section is unchanged.
A proposed attachment is drawn as P2 draws any proposal (dashed, "unconfirmed"), with no highlight
halo and no edges. `/api/machines` gains, per machine, `measured: {attachments: [...],
last_measured}`; the Dashboard's "what runs now" panel never lists a machine for being measured.

**The Instruments page.** Each row gains **hung on**: the declared machines it is attached to, with
their matches, and "shared" where two machines' matches select the same series (a host's CPU under
both: the owner's statement, not an error). The page still never runs or queries an instrument; the
series come from `recent()` and the sources' reader, read each minute under a time limit, as
counted traffic is (`web/traffic.py`). With the store down, attachments show "series unknown".

**The Dynamics page.** Nothing changes. Stocks come from discovery; no stock or flow is marked as a
machine's.

## 4. The Supervisor's part

The tools belong to P4 (`machine-design.md`). When the owner declares an existing machine ("we have
a Postgres cluster"), the Supervisor offers candidate series for it by name: it searches the
metrics store's series and the sources' inferred definitions for fitting names and label values
(`pg_*`, `job="postgres"`), under the same `Budget` and sampled with `limit`, and offers each as a
proposed attachment with what it matches and a sample of its values. Its label analysis proposes
an instance label and says why: labels with several stable values over the window, never one that
looks like occurrences (values without bound, one point each: a build number, a request id), never
one over the cap. When nothing fits, it proposes an instrument (P4's `add_instrument`, through
`project.config_edit`) and, once it records, offers it as a proposed attachment. It never names a
machine the owner did not give, and never proposes a machine from a series it found.

## 5. Invariants

Two rules change in wording, and the commit that builds this says so (AGENTS.md preamble).

**Rule 2.** After P2's added sentence on declared machines (P2 §8, "The owner may also declare
machines … and say nothing about flows."), add:

> Instruments may be attached to a declared machine (`docs/proposals/instruments-on-machines.md`):
> declared provenance saying which series measure it and which label counts its replicas. Being
> measured never makes a machine seen or active. Measured instances are counts of a label's values:
> never instances in the observed layer, never a `source`, never active.

**Rule 7.** After "and a flow is never associated with a machine from a measurement's label", add:

> Attaching an instrument to a declared machine is declared provenance, like the
> `instrument=<name>` label: it is kept in the declared layer, never written on a point, never read
> by discovery or by `sd/attribute.py`, and never binds a series to a stock, a flow or a machine's
> flow. An attachment never makes a machine; it only gives series to a machine the owner declared.

**SPEC follows** (C5): §5.2's "it is not on the Machines page" becomes "it is never a machine on the
Machines page; a declared machine's dialog names the instruments attached to it"; §10's "every
machine seen on the bus (never one a series names, never an instrument)" becomes "every machine
seen on the bus or counted, and every declared one (never one a series names, never an
instrument)"; `web/machines.py`'s docstring ("a machine exists because it shows up on the bus")
says the same, with declared and measured-never-heard machines placed by the declared layer.

**Rule 5** is P2's to amend (P2 §8): "the intended model through `ModelStore.intended()`
(`project.intended`), in `<state>/model/intended/`, whose journal and versions nothing else
opens". Attachments live there and need no wording of their own.

**Rule 6 and rule 7's core do not move.** Rule 6 already says "Nothing declares the association,
not configuration and not a plugin": an attachment is neither a flow nor an association, and test
3 holds it by behaviour. (P2 §8 adds a sentence to rule 6 on draft expected effects; nothing here
touches it.) Rule 7's core is that measurements are kept apart from machines so they
can test what we believe, and that stocks are discovered: the metrics are not changed, discovery's
inputs are not changed, and the attachment is a belief the observed layer can contradict (nothing
matched, the machine never heard). **Rule 9** holds: the core's pages show attachments and never
make, confirm or discard one.

## 6. Acceptance tests

Unit (core):

1. `propose_attachment` then `confirm` records machine, instrument, match, instance label, state
   and P2's provenance in a new `dN`; the metrics store's `dump()` is equal before and after;
   `orchestra.toml` and the overlay are unchanged.
2. An attachment to an undeclared machine, to an unknown instrument, or with an instance label a
   source definition's `by` drops, is refused with the reason.
3. Discovery over one fixture store with and without attachments gives equal models (stocks,
   flows, equations, origins, `flow.evidence["machines"]`), and `orchestra.sd.attribute` imports
   nothing from `orchestra.sd.intended` (checked on the module's imports).
4. `recent()` conformance, on every backend: only series with a point at or after `since`; the
   last `keep` points in order; `=` and `=~` matchers; nothing older is read on VictoriaMetrics
   (the request's `start`).
5. A declared machine with a measured attachment and no events: `/api/machines` has
   `last_seen` null, `active` false, `measured.last_measured` set; the Dashboard's running panel
   omits it; its dialog's Flows says "none hypothesised yet".
6. Instances and the window: `pg_up{server="db-1|db-2|db-3"}` every 60 s, instance label `server`,
   give three measured instances; a fourth value adds one with no new declaration; `db-3` silent
   for 61 min is listed quiet; a series written once a day stays measured 30 h after its last
   point; `pg_up=0` is measured with its value shown.
7. Two attachments on one machine, `server="db-1"` and `instance="db-1:9187"`: each lists one
   instance; the machine shows one, not two.
8. A label with 51 values shows "51 values: too many for instances".
9. One scrape, two machines: matches `job="jenkins"` and `job=~"deploy-.*"`; each machine shows
   only its own series; the instrument's row shows both under "hung on"; a series both select is
   listed under both and marked shared.
10. Aliases on a source fixture: series spelled `svc` and `service` both match `service="gate"`;
    after the gate's job is renamed, the old name's series go quiet and the new one's match.
11. The same machine heard on the bus (or joined by `alias` to a counted `<prefix>.<name>`):
    observed fields and activity win; the attachments stay.
12. A declared attachment whose match finds nothing is not measured and is on the comparison as
    "attached, nothing measured"; the flag is never in a `dN` or the journal.
13. With the metrics store unreachable, `/api/instruments` and `/api/machines` answer within their
    time limits, attachments listed, "series unknown".
14. `POST /api/intended/control` with `part: "attachment"` is refused with 400 (P2's test 15)
    and writes nothing; the button publishes a request event (`POST /api/intended/request`, one
    `orchestra.intent.requested`, no `dN`) and changes nothing itself; no core route creates,
    confirms or discards one.

End to end, on the agents' demo with a declared `managed: external` machine `postgres` and a `[[collect]]`
script printing `pg_connections{server="db-1"}` and `{server="db-2"}` every 10 s:

15. After one round, `/api/machines` shows `postgres` measured, never heard, two instances;
    `/api/instruments` shows the script hung on `postgres`; the dialog renders Measured by (checked
    by `ux-review`).
16. The script adds `server="db-3"`: within two background reads the dialog shows three.
17. After `orchestra sd discover`, no flow's hypotheses name `postgres`.

## 7. Out of scope

Bridges that publish a company system's events (they are observed already), the Supervisor's
instrument-writing (P4's `add_instrument`), and new mockup frames.

## 8. What this takes from P2

From P2 as merged (round 3); if P2 changes, this follows.

- **Declared machines** (P2 §2): id = the expected `source`; `kind` ∈ `universal | programmatic`,
  `managed: external` for machines Orchestra does not run (with any engagement).
- **Aliases** (§6.3): `alias {machine, observed}` joins a declared id to an observed or counted
  name.
- **Store, ops and provenance** (§4, §5, §6.3): P2 lists `propose_attachment` and
  `revise_attachment` on the same `apply`, and `part: "attachment"` for `confirm`, `discard`,
  `retract`.
- **Versioning** (§5): attachments in `dN`, apart from equations.
- **Derived on read** (§5): `measured` and `instances` computed by the comparison, never stored.
- **Persistence** (§3.3): a proposed attachment stays until confirmed or discarded.
- **The comparison**: two entry kinds, "attached, nothing measured" and "declared, neither heard
  nor measured".
- **The details panel** (§7): where P2 replaces the dialog, Measured by goes after Instances.
- **Rule 5** (§8): P2's amendment covers attachments.
- **Page controls:** P2 §6.2's controls send requests to the Supervisor for machines and
  attachments alike (the coordinator's rule); P2 states it.

## 9. Open questions

1. **A separate proposal, or a section of P2?** Recommended: keep this file, with P2 owning the
   store, schema and states, and this one owning what an attachment means, instances and the
   window, the new store method, the two pages' additions and the rule wording. The rule-7
   argument is the one most attacked in review and is easier to judge alone; P2 links here from
   its machines section.
2. **Attach to observed machines directly?** Proposed: no; declare first (one more Supervisor
   step for a scraped machine that also publishes).
3. **Cross-links on the Dynamics page.** A stock's drawer could say "its series is attached to
   postgres": provenance, not association, but the nearest thing to rule 7's line, and the mockups
   do not show it. Proposed: not in this step.
4. **Evidence from attached activity series.** A Jenkins `builds_total` attached to `jenkins`
   could be evidence for a flow hypothesis as bus events are. That would need its own amendment to
   rule 6, and is not proposed.
5. **Series → proposed machine.** Proposing a machine from an exporter nobody declared would need
   its own amendment to rule 7, and is not proposed.
