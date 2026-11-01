# Instruments on machines: the integration step

Status: draft for review, 2026-11-01. Nothing built. Proposal 5 of `design-backwards.md` §7, written
from that file's §5 and `design-backwards-notes.md` §9 (items 7 and 12, and "the invariants this
touches") and §13.1. It depends on proposal 2 (`intended-model.md`, written in parallel), which
defines declared machines and the declared layer; what this one needs from it is listed in §7.

## 1. Purpose

The machines that matter most at work already exist, and none of them will ever publish an event on
Orchestra's bus: a Jenkins job pipeline, a Postgres cluster, the company's merge gate, SAIL. Today
Orchestra cannot show them at all. The Machines page lists only what the bus has heard (rule 2), and
an instrument that measures one of them is, rightly, not a machine (rule 7). So the series are in
the metrics store and on the Dynamics page, and the thing they measure is nowhere on the map.

The owner, on the map: "The existing Machines will need to be mapped, and this is where the fun
part happens, because this is the integration step. Because the Machines aren't likely to emit
their actual metrics, and because we would want to incorporate and model existing machines, we
need to attach our measurement instruments to Machines. This is where we would do it."

So an existing machine is **declared** (proposal 2) as a placeholder on the map, and **instruments
are attached to it**: the owner says, through the Supervisor, which collected series measure which
declared machine, and which of their labels counts its instances. The instrument still measures;
the declared machine is where the measurement is hung on the map. That is all this proposal adds.

## 2. What "attached" means, and what it does not

An **attachment** is one declaration: *these series measure that declared machine*. It has four
parts:

- **the machine**: a declared machine's id (proposal 2). Only a declared machine takes an
  attachment. A machine the bus already knows is declared first (proposal 2's "confirm"), which
  costs nothing and keeps one path.
- **the instrument**: the name of a `[[collect]]`, a `[[scrape]]`, a plugin's collector
  (`<plugin>.<name>`) or a `[[sources]]` entry, exactly as the Instruments page names it.
- **the match**, optional: a series-name prefix and label equalities (`job = "postgres"`) that
  narrow the instrument's series to this machine's. These are what `MetricsStore.series(prefix,
  labels)` already takes, so nothing new is asked of a backend. With no match, every series the
  instrument writes is this machine's.
- **the instance label**, optional: the label whose distinct values are the machine's instances
  (`server`, `instance`, `pod`). The owner picks it; the Supervisor proposes it (§4).

It means **declared provenance**, of the same kind as the `instrument=<name>` label: "this is
what was measured, and where on the map the owner hangs it". Nothing more. In particular:

1. **It never makes a machine exist in the observed layer.** A declared machine with attachments
   and no events is *measured, never heard*. It has no "last seen" and is never "active": activity
   stays the bus's alone (rule 2, SPEC §10, never by a write to a series). Its last measured point
   is shown, under its own name, as *last measured*.
2. **It never binds the machine to a flow.** `orchestra/sd/attribute.py` is untouched and never
   reads an attachment. A machine that publishes nothing has no flow hypotheses, and the page says
   so in the words it uses today: no flow associated. The link between a machine and a flow stays
   an inferred hypothesis (rule 6). The owner's wish to say what a machine is expected to change is
   a prediction (notes §13.3, proposal 2 and `orchestra.prediction.made`), not an attachment.
3. **It changes no point and no model.** Nothing is relabelled or rewritten in the store; no new
   label is written on collection; discovery never reads attachments, so the stocks, flows,
   equations and evidence found from the same data are the same with or without them (rule 7:
   stocks are discovered).
4. **It never creates a machine from a series.** The direction is always name → series: a declared
   machine is given series. A series is never turned into a machine, declared or proposed, and a
   new value of the instance label adds an instance under the machine the owner declared, never a
   new machine.

**Instances come from a label.** "They might say 'postgres database', but if they have one then you
know they have more than one." A name declares a kind; how many there are is learned. The
machine's *measured instances* are the distinct values of its instance label among the matched
series that have a point within the last hour (the window the Machines page already uses for
counted traffic), each with its last point. A value that stops reporting drops out after the hour;
a new one appears without anyone declaring it. Measured instances are shown apart from bus
instances (`<machine>/<instance>` sources): one is counted from measurements, the other heard.

**Several instruments per machine.** A database cluster may have an exporter scrape, a backup
script and a source on the company's Prometheus. Each is one attachment; the machine's series are
their union, and its measured instances the union of each attachment's instance values (the
attachments name their own instance label, since one exporter says `server` where another says
`instance`).

**One instrument, several machines.** A scrape of a federation endpoint, or a source on the
company's Prometheus, serves Jenkins, Postgres and the gate at once. Each machine's attachment
names the same instrument with a different match (`job = "jenkins"`, `job = "postgres"`). A series
matched by two machines' attachments (a host's CPU under both) is shown under both and flagged on
the Instruments page as shared; that is the owner's statement, not an error.

**Reading a label is not inferring from it.** Rule 7 forbids inferring a machine's existence from
who wrote a series and associating a flow with a machine from a measurement's label. Here the
owner reads a label on purpose, in a declaration, to say which series measure the machine they
declared and how to count its instances. Orchestra infers nothing from it: not existence (the
machine was declared), not activity, not flows.

## 3. How it is recorded, and how it is shown

**Recorded** in proposal 2's declared layer, beside the declared machine, never in
`orchestra.toml`: the instrument is configuration (it runs), the attachment is a declaration (it
says what the owner believes). Each attachment carries the provenance proposal 2 gives every
declaration (who, when, from which Supervisor turn) and one of its states:

| State | Meaning |
|---|---|
| proposed | the Supervisor offered it (§4); drawn as the darker variant until the owner confirms |
| declared | the owner confirmed it |
| measured | declared, and its match found series with a point in the last hour |

"Measured" is observed, from the store; a declared attachment that matches nothing (an instrument
renamed, a label changed, an exporter down) is a difference between the declared layer and the
observed one, and goes on proposal 2's work list as "attached, nothing measured". Discarding an
attachment removes it from the view and keeps its record, like any declaration.

**The Machines page.** A declared machine with attachments is drawn on the map as proposal 2 draws
a declared machine (mockup frame E3-external: "not managed by `orchestra run`: a continuous machine
with no command"), with the mark *measured, never heard* on its node and card. Its drawer gains a
**Measured by** section: each attachment (instrument, kind, match, instance label, state), the
series it matches (names and counts, not values), the measured instances with their last points,
and *last measured*. The drawer's flows section is unchanged and still reads only `sd.attribute`.
Once the machine is heard on the bus under its id, the observed fields win (rule 2) and the
attachments stay. The `/api/machines` entry gains `measured` (attachments, instances,
`last_measured`); the Dashboard's "what runs now" panel never lists a machine for being measured.

**The Instruments page.** Each instrument's row gains **hung on**: the declared machines it is
attached to, each with its match, and "shared" where two matches overlap. An instrument attached
to nothing says nothing new. The page still never runs or queries an instrument; the series per
attachment come from the metrics store's `series()` (and, for a source, through `orchestra.sources`
only while a page asks, rule 5), read by the web server's background reader each minute under a
time limit, as counted traffic is (`web/traffic.py`). With the store down, the page shows the
attachments with "series unknown".

**The Dynamics page.** Nothing changes. Stocks still come from discovery; a stock's drawer still
shows its series, source, query and origin. No stock or flow is marked as a machine's. Whether a
stock's drawer may say "this series is attached to postgres" is open (§8, question 3).

## 4. The Supervisor's part

The tools belong to proposal 4 (`machine-design.md`); this is what they must do for this step. When
the owner declares an existing machine by name ("we have a Postgres cluster"), the Supervisor
offers candidate series for it by name: it searches the metrics store's series and the sources'
inferred definitions for names and label values that fit (`pg_*`, `job = "postgres"`), and offers
each as a *proposed* attachment with what it matches and a sample of its values. For each
candidate it runs a label analysis: which labels have several stable values over the window
(`server`, `instance`, `pod`), how many, and whether they look like replicas; it proposes the best
as the instance label and says why, and the owner picks. When nothing fits, it proposes an
instrument (proposal 4's `add_instrument`, through `project.config_edit`) and attaches it once it
records. It writes the attachment through the core's declared-layer API, never by hand, and never
proposes a machine from a series it found (§2, item 4).

## 5. Invariants

Two rules change in wording; the commit that builds this says so (AGENTS.md preamble).

**Rule 2**, the sentence on placeholders, becomes (new text in *italics*):

> The exceptions are what an instance announces in `orchestra.machine.started`: its mode, what it
> listens for, its kind (program, agent, person, service), where its log is and which package it
> belongs to (the rest of the announcement is passed on to that package's card, unread), and the
> machines a plugin declares (`Plugin.machines`) *or the owner declares through the Supervisor (the
> declared layer, `docs/proposals/intended-model.md`)*: placeholders that only fill in machines not
> seen yet, never override what is observed, *never make a machine exist in the observed layer*,
> and say nothing about flows. *Instruments may be attached to a declared machine
> (`docs/proposals/instruments-on-machines.md`): declared provenance saying which series measure it
> and which label counts its instances. A measured machine is never heard by it: never seen, never
> active.*

**Rule 7**, after "and a flow is never associated with a machine from a measurement's label",
gains:

> *Attaching an instrument to a declared machine is declared provenance, like the
> `instrument=<name>` label: it is kept in the declared layer, never written on a point, never read
> by discovery or by `sd/attribute.py`, and never makes the machine observed or binds it to a flow.
> A series never makes a machine, declared or proposed; an attachment only gives series to a
> machine the owner declared.*

The sentence "they are not machines, are not announced on the bus, and are shown on the
Instruments page" stands; SPEC §5.2's "it is not on the Machines page" becomes "it is never a
machine on the Machines page; a declared machine's drawer names the instruments attached to it".

**Why nothing of rule 6 or rule 7's core moves.** Rule 6 already says "Nothing declares the
association, not configuration and not a plugin": an attachment is neither a flow nor an
association, so the rule needs no new words, and the test in §6 (item 3) holds it. Rule 7's core
is that measurements are kept apart from machines so they can test what we believe, and that stocks
are discovered. Both hold: the metrics are not changed, discovery's inputs are not changed, and the
attachment is a belief about the map, which the observed layer (series found, instances counted,
the machine heard or not) can contradict. Rule 9 holds too: the pages show attachments and never
make one.

## 6. Acceptance tests

Unit (core):

1. Attaching records the machine, instrument, match, instance label, state and provenance (who,
   when, turn) in the declared layer; `orchestra.toml`, the overlay and the metrics store are
   unchanged byte for byte.
2. An attachment to a machine that is not declared, or to an instrument name that is not valid, is
   refused with the reason.
3. Discovery over the same fixture store with and without attachments gives identical models:
   stocks, flows, equations, origins and `flow.evidence["machines"]`. `git diff main --
   orchestra/sd/attribute.py` is empty.
4. A declared machine with an attachment and no events: `/api/machines` lists it with
   `last_seen` null, `active` false, `measured.last_measured` set; the Dashboard's running panel
   omits it.
5. Instances: series `pg_up{server="db-1"}`, `{server="db-2"}`, `{server="db-3"}` with instance
   label `server` give three measured instances; a fourth value adds one with no new declaration;
   a value with no point in the last hour is not counted.
6. Two attachments on one machine (labels `server` and `instance`) give the union of their series
   and of their instance values.
7. One instrument, two machines: series `{job="jenkins"}` and `{job="postgres"}` under one scrape,
   two attachments with those matches; each machine shows only its own; the instrument's row
   shows both under "hung on"; a series matched by both is listed under both and marked shared.
8. The same machine id later heard on the bus: observed fields win, `active` follows the bus, the
   attachments stay.
9. A declared attachment whose match finds nothing is state "declared", not "measured", and is on
   the declared-vs-observed list as "attached, nothing measured".
10. With the metrics store unreachable, `/api/instruments` and `/api/machines` still answer within
    their time limits, attachments listed, series "unknown".
11. No web route creates, changes or discards an attachment (rule 9); only the core's Python API
    does.

End to end, on the agents' demo with a declared external machine `postgres` and a `[[collect]]`
script printing `pg_connections{server="db-1"}` and `{server="db-2"}` every 10 s:

12. After one round, `/api/machines` shows `postgres` measured, never heard, with two instances;
    `/api/instruments` shows the script hung on `postgres`; the Machines page drawer renders the
    Measured by section (checked by `ux-review`).
13. The script starts printing `server="db-3"`; within two background reads the drawer shows three
    instances.
14. After `orchestra sd discover`, no flow's hypotheses name `postgres`, and the Dynamics page
    shows whatever stocks discovery found from the series, with nothing marked as `postgres`'s.

## 7. Needs from P2

- **The declared machine**: its id and how it is matched to a bus `source` (same id, or an alias),
  its kind, and an engagement of *external* (E3-external) for machines Orchestra does not run.
- **The declared layer's store and API**: where declarations live (state directory, rule 5),
  how a sub-record such as an attachment hangs off a declared machine, and the Python call the
  Supervisor's tool uses.
- **Provenance and states**: the who/when/turn fields and the proposed/declared states, applied to
  attachments as they are to machines; whether "measured" is a third state or a derived flag.
- **Versioning**: whether attachments belong to the intended model's versions ("changes since vN"
  lists an attachment added or discarded) or are kept outside them. This proposal assumes inside.
- **The comparison**: an entry kind for "attached, nothing measured" and for "declared, neither
  heard nor measured", so the work list carries them.
- **The machine drawer's layout** for a declared machine, so Measured by has a place in it.

## 8. Open questions

1. **A separate proposal, or a section of P2?** Recommended: keep this file, short, with P2 owning
   the store, schema and states and this one owning what an attachment means, the instance rule,
   the two pages' additions and the rule wording. The rule-7 argument is the one most likely to be
   attacked in review, and it is easier to judge on its own; P2 links here from its declared
   machines section.
2. **Attach to observed machines directly?** Proposed: no; declare first. A bakery oven that
   publishes and is also scraped would need one extra Supervisor step.
3. **Cross-links to the Dynamics page.** A stock's drawer could say "its series is attached to
   postgres". It is provenance, not association, but it is the nearest thing to the line rule 7
   draws, and the mockups do not show it. Proposed: not in this step.
4. **The instance window.** One hour, as for counted traffic; a nightly Jenkins job's instances
   would drop out between runs. Perhaps the window should follow the series' own cadence, as
   activity does on the bus.
5. **Series → proposed machine.** Proposing a machine from series the Supervisor finds (an
   exporter nobody declared) would be useful and is excluded here, because it makes a machine from
   a series. If wanted, it needs its own amendment to rule 7.
