# Proposal: event sources (counted traffic on other buses, and bridges for things that are buses)

Status: draft, 2026-10-26. Nothing built. Sibling of `time-series-sources.md`, whose query
machinery it reuses.

The owner needs the bus for three things: **which machines exist**, **the event graph**, and
**communication between the machines our repository runs**. Company systems bring two problems:

- **Buses we cannot read.** GCP Pub/Sub carries too much data to consume, and the data is not
  ours. What can be pulled is aggregate: "this machine produced 15 events into the topic, this
  other machine consumed 11", treated "as if" 15 were published and 11 consumed.
- **Buses not called buses.** Jira, Slack, Confluence and Google Docs carry requests and answers
  between people and bots ("someone will @ ping me on Slack and be mad if I don't respond within
  15 minutes"). They must be polled or hooked to produce events.

The first yields machines and the graph from counts (§1–3). The second yields real events, so it
also serves communication: our machines can listen for `jira.issue.transitioned` (§4–5).

## 1. Counted traffic: a second kind of observation

| | Events | Counted traffic |
|---|---|---|
| What | One envelope per occurrence, on Orchestra's bus | A count per interval: producer → channel → consumer |
| Where | `orchestra.<key>.events` | Series read through `orchestra.sources`, or written by a collector |
| Identity | `id`, `time`, `subject`, `source` | None per occurrence |
| Feeds | Machines, map, hand-offs, event counters | Machines, map, counters, backlogs |

**No events are synthesized.** Writing 15 envelopes a minute would invent ids, times and
subjects, bring the volume problem back at company scale, and make replay lie. The count *is* the
observation: the map draws an edge carrying 15 a minute, and the model gets a counter that rose
by 15. That is the "as if", without fake events.

**Shape.** A traffic series is an ordinary counter (or backlog level) that a series definition
marks as traffic, as catalogue metadata, never a label convention (a user's own `channel` label
must not be misread):

```toml
[[series]]                                     # from the Pub/Sub preset (§2)
name = "pubsub_acked_total"
source = "gcp"                                 # Cloud Monitoring's PromQL endpoint
select = '{__name__="pubsub.googleapis.com/subscription/ack_message_count", monitored_resource="pubsub_subscription"}'
by = ["subscription_id"]
kind = "counter"
traffic = { direction = "in", channel = "{topic_id}", machine = "{service}" }
```

`direction` is `out` (produced) or `in` (consumed); a level marked `backlog` is a channel's
queue. `channel` and `machine` are label templates resolved after the source's aliases, prefix
and scripts. A count with no machine is **unattributed**, and drawn so.

## 2. GCP Pub/Sub through Cloud Monitoring

Metrics are sampled every 60 s and visible up to about 3 minutes later:

| Resource | Metric | Use |
|---|---|---|
| `pubsub_topic` (`topic_id`) | `topic/message_sizes` (a distribution; its count is messages) | **produced** (the deprecated `send_message_operation_count` points here) |
| | `topic/send_request_count` | publish requests (batches) |
| `pubsub_subscription` (`subscription_id`) | `subscription/ack_message_count` | **consumed** |
| | `subscription/sent_message_count` | delivered, redeliveries included |
| | `subscription/num_undelivered_messages` | **backlog**: a stock |
| | `subscription/oldest_unacked_message_age` | the oldest wait: a delay |
| | `dead_letter_message_count`, `expired_ack_deadlines_count`, `nack_requests` | leaks and retries |

Cloud Monitoring answers PromQL on a Prometheus-compatible endpoint
(`monitoring.googleapis.com/v1/projects/<p>/location/global/prometheus`), so a `prometheus`
source with `bearer_command = ["gcloud", "auth", "print-access-token"]` reads it with **the same
machinery** as Chronosphere: window, step, cache, partial failure, provenance, a settle age of
5 minutes, never a step under 60 s. Nothing Pub/Sub-specific enters Orchestra: the preset is a
configuration file shipped with the bridges (§7).

**The limits, plainly.**
- **Publishers are not identified.** No topic metric has a label for who published.
- **Subscription metrics do not name their topic.** A topology poller (a `[[collect]]` script,
  every ten minutes, over the admin API) prints
  `pubsub_subscription_info{subscription_id, topic_id, push_endpoint} 1`, and the catalogue joins
  a label from an info series by a shared key (the info-metric pattern, done in the catalogue
  because the two series live in different stores).
- **Delivery is at-least-once;** acked, not sent, is "consumed".

**Attributing machines**, best first, each recording its origin (rule 6):
1. **Publisher-side metrics** the services already write (a publish counter by topic in
   Chronosphere): real counts per service, joined by topic. Where they exist, the problem is gone.
2. **Declared** in the owner's transformation script or map (`topic → services`,
   `subscription → service`).
3. **Push endpoints:** a push subscription's URL host usually names the consuming service.
4. **Naming rules:** `orders-api-invoices-sub` → consumer `orders-api`.
5. **IAM bindings:** service accounts holding `roles/pubsub.publisher` on a topic or its project
   are **candidates**; permission is not proof. One candidate is probable; several leave the
   split unknown.
6. **Inferred split:** with several candidates and their own request rates measured, discovery
   may fit each one's share; a hypothesis, shown as one.

Rejected: Data Access audit logs name every publisher, but are off by default and at this volume
cost more than the answer is worth; at most a short diagnostic window. Consumers are easier: one
subscription per consuming service is the usual practice.

## 3. What counted traffic feeds

**Machines.** An attributed producer or consumer is a machine (`gcp.orders-api`), known by
observation: a source counted its traffic. Its card shows rates and backlogs, never events, with
a "counted" badge; last seen is its last interval with a nonzero count.

**The event map.** A channel is a node, like an event-type box (`gcp:orders`). Counted edges are
a **double line** labelled with the rate ("15/min, counted"), distinct from solid (publishes),
dashed (listens) and dotted (hand-offs). Unattributed traffic enters from a grey stub, so the gap
shows.

**The model.** Counts are counters, so flows; the backlog is a level, so a stock; and
`Δbacklog ≈ produced − acked` is the balance conservation discovery already searches for. Two
changes are needed in discovery:
- **Copies.** One topic's produced count fills *every* subscription's backlog. Today a counter
  flows from one stock to another; one counter feeding several stocks at once must be allowed and
  drawn as a copy, not a split.
- **Loose balances.** Retention expiry, dead-lettering and 60 s sampling keep balances inexact;
  the measured leaks are offered as counters, and a rough balance is kept with its R².

`oldest_unacked_message_age` is an auxiliary: the delay a consumer imposes.

**Other buses**, the same way once their exporters reach a store Orchestra can read:

| Bus | Produced | Consumed | Backlog | Attribution |
|---|---|---|---|---|
| Kafka (kafka_exporter) | growth of partition end offsets | committed offsets per group | consumer lag | consumers by group; producers only by brokers' per-client-id metrics |
| RabbitMQ (rabbitmq_prometheus) | published per queue or exchange | acked per queue | ready + unacked | consumers by queue; producers by connection name |
| NATS JetStream | stream messages | consumer acked | consumer pending | consumers by durable name |

## 4. Bridges: buses in all but name

A **bridge** is a machine outside Orchestra that polls a system (or takes its webhooks) and
publishes **real events** on Orchestra's bus, metadata only. Orchestra's event collector counts
them by type and source like any others, so flows come for free.

- **Source** is the actor: a person (`work.person.7f3a`) or bot (`work.bot.jira-automation`),
  so people and bots are machines and the map shows who hands work to whom. What the system
  itself originates (an SLA timer) has the system as source (`work.jira`). An identity map in the
  owner's configuration joins one person's Slack, Jira and Google accounts.
- **Subject** is the item: an issue key, a Slack thread, a document id. Hand-off inference already
  works from subjects: Bob pings in thread T, the owner answers, a hand-off from Bob to the owner.
- **Time and id** come from the system, the id stable across polls (`envelope(time=, id=)`), so
  overlapping polls never duplicate, and a bridge keeps no state: it resumes from its last event
  on the bus.
- **Data** is status from and to, issue type, project, channel id, document id, version. **Never
  text**: no summaries, comments, messages or document content.

| System | Events | Push | Pull (the default) | Access |
|---|---|---|---|---|
| Jira | `jira.issue.created`, `.transitioned`, `.assigned`, `jira.comment.added` | webhooks (public URL) | JQL `updated >= "-2m"` on `/rest/api/3/search/jql` with changelog, each minute | API token or PAT, read-only |
| Slack | `slack.ping.received`, `slack.ping.answered` | Events API (public URL); Socket Mode (behind NAT, needs an app the workspace approves) | `search.messages` for mentions and DMs, user token (`search:read`), each minute | user token |
| Confluence | `confluence.page.created`, `.updated`, `confluence.comment.added` | via an installed app only | CQL `lastmodified >= now("-5m")` | API token, read-only |
| Google Docs | `gdoc.edited`, `gdoc.commented`, `gdoc.shared` | `files.watch` (public URL) | Drive `changes.list` plus the Drive Activity API for who did what | `drive.metadata.readonly`, `drive.activity.readonly`: content unreadable |

**Polling first**, because this Mac has no public URL; webhooks later where a relay is allowed.
One poll a minute is far below every limit here (`search.messages` is about 20 a minute). Slack's
2025 cut of `conversations.history` and `replies` to one call a minute hits commercially
distributed non-Marketplace apps; internal apps keep the older limits, though Slack is vague about
internal apps created after 29 May 2025, so the bridge is built to work at one a minute. Every
bridge honours `Retry-After`.

**Privacy.** Slack search returns message text: the bridge keeps only ids, users and timestamps;
text passes through memory and is never written, logged or published. People as machines measures
individuals, so people are stable pseudonyms (a salted hash) by default; only names listed in
configuration (the owner, bots) are shown, and a team-only mode folds people into teams.

## 5. The 15-minute expectation as a stock

A **ping** is an @mention of the owner (optionally of their groups) or a DM. It is **answered** at
the owner's first message in the same thread (in the channel after it, when not threaded), or a
reaction if configured. The bridge publishes `slack.ping.received` (source the pinger, subject the
thread) and `slack.ping.answered` (source the owner), and serves, for a `[[scrape]]`:

- `slack_pings_unanswered`: **the stock** of people waiting;
- `slack_pings_oldest_unanswered_seconds`: the delay, as Pub/Sub's oldest unacked age;
- `slack_pings_answered_total{within="5m|15m|60m|over"}`: the response-time distribution as
  counters, since the collector keeps no histogram buckets.

Orchestra's counts of the two events are the inflow and outflow, a balance discovery should find.
Mean response time is the stock over the answer rate (Little's law); **the promise** is the share
answered within 15 minutes and the oldest age staying under 15. This measures user stories 13 and
3.3, and how pings compete with the owner's other work: a loop the model can find.

## 6. The rules

- **Rule 1:** bridges know issues and pings, so they live outside Orchestra. Counted traffic (a
  channel, a direction, a count) is a bus concept like an event type, fit for the core. Text:
  Orchestra has "an event bus, a metrics store, the sources it reads, ...".
- **Rule 2** gains: *"or the producer or consumer a series definition attributes counted traffic
  to on another system's bus: known by counts, never by events."*
- **Rule 3** stands, plus: *"Counted traffic is never turned into events."* Bridges publish full
  envelopes, and Orchestra still reads no `data`.
- **Rule 4:** counted traffic and bridged events enter the one bus, catalogue, map and model;
  prefixes label, never separate.
- **Rule 5:** only the sources proposal's sentence. Bridges keep no state.
- **Rule 9:** bridges only read; speaking into Slack or Jira is the outbox's proposal.
- **D10:** the preset and bridges are general, in their own repository; the owner's topics,
  channels, identity and attribution maps and credentials are the owner's configuration.

## 7. Where the code lives, and tests

**In Orchestra** (small): traffic metadata and the info-series join in `sources/catalogue.py`;
counted machines, channels and edges in `web/machines.py` and the map's renderer; copy flows in
`sd/`.

**A new repository, `~/orchestra-bridges`**, a plugin whose bridges are `processes` the launcher
runs, configured in `[bridges.<name>]` sections Orchestra ignores. Bridges publish through
`orchestra.events`, as the bakery does.

```
orchestra_bridges/
  pubsub/   preset.toml, topology.py (the [[collect]] script), simulator.py
  jira.py  slack.py  confluence.py  gdrive.py
  identity.py  envelope.py (stable ids, metadata-only data)
  fakes/
```

**Fakes speaking the real APIs:** Cloud Monitoring's PromQL endpoint (the sources proposal's fake
Prometheus at Google's path, demanding a bearer token) fed by the simulator; the Pub/Sub admin
API (subscriptions, IAM policies); Slack (`auth.test`, paginated `search.messages`, `ok: false`,
429 with `Retry-After`); Jira (`search/jql` with `nextPageToken` and changelogs); Confluence CQL;
Drive changes and Activity. **Contract tests**, opt-in by environment variable, call the real
services and compare only response shapes (keys and types, never content) with the fakes'.

**Properties tested:** a canary string in a fake message never reaches the bus, series or logs;
re-polling an overlap publishes nothing twice; pseudonyms are stable; no traffic series yields an
event; the simulator's backlogs are discovered as stocks with copy inflows.

## 8. Phased plan

**Test sources chosen with the owner (2026-10-26), which replace the stand-ins below where they differ.**
Pick sources where *consuming* is visible, not only publishing: someone replying, closing or
reverting is a consumer.
- **Counted traffic: RabbitMQ**, already running in Orchestra's dev Docker stack.
  - A small simulated fleet of publishing and consuming services runs against it, including one
    slow consumer whose backlog grows at peak.
  - Orchestra reads only RabbitMQ's own per-queue counts (published, delivered, acknowledged,
    backlog, consumers attached) through its built-in Prometheus endpoint, never a message.
  - This is Pub/Sub's shape (counts per topic and subscription, no payloads) on a real broker, so
    it tests the counts, which the Pub/Sub emulator cannot. The Pub/Sub simulator and emulator
    below stay for the GCP-specific topology and attribution.
- **First bridge: GitHub issues** on a busy public repository (e.g. `microsoft/vscode`), through
  the owner's `gh` login.
  - Producers: people opening issues. Consumers: people commenting, labelling, closing.
  - It is the closest public stand-in for Jira, including time to first response.
- **Second bridge: Bluesky's public Jetstream feed**, filtered to a few accounts or a hashtag.
  - Posts are produced; replies and likes consume them.
  - It is a high-volume stand-in for Slack's mention-to-reply time, where only aggregates are
    viable, so it also tests "too big to consume".
- **Considered and set aside:**
  - Wikipedia's edit stream (edits, with reverts and patrols as consumers): a good third.
  - IRC (Libera): a lighter Slack stand-in.
  - Discord: needs a bot invited to a server.
  - Reddit: API restricted.
  - Twitter: paid API.
  - Threshold events on a data stream (e.g. proton flux): produce events but have no external
    consumers, so they suit our own bus, not adaptor tests.


**Phase 1 (4 days, after the sources slice 1): counted traffic, locally.** A Pub/Sub simulator
(three topics, five publishing services, four subscriptions, one slow consumer whose backlog grows
at peak) writes Cloud Monitoring-shaped series into the sources rig's VictoriaMetrics behind the
bearer proxy, with publisher-side counters for three of the five; the topology poller reads the
fake admin API. *Done when* the Machines page shows producers, channels and consumers with
counted edges and two publishers' share unattributed; each backlog is a stock filled by its topic
and drained by its acks; the bus's volume is unchanged. *Honestly:* the Pub/Sub emulator serves
the admin and data APIs but no Cloud Monitoring metrics, so it can test the topology poller, not
the counts.

**Phase 2 (3 days): the owner's pings.** The Slack bridge and fake; then a free personal
workspace the owner creates (the real API, no company data); the work workspace only if policy
allows a user token. *Done when* the unanswered stock, oldest age and within-15 share are live
and the canary test passes against the real API.

**Phase 3 (4 days):** Jira, Confluence and Drive pollers; the identity map; hand-offs between
people and bots.

**Phase 4:** webhooks or Socket Mode where reachable; Kafka, RabbitMQ and NATS presets; IAM
candidates and the inferred split.

**Limits that stay:** counted traffic has no subjects, so no hand-offs or per-item delays, only
rates and backlogs; publishers without their own metrics are at best candidates; polling delays
bridged events by a minute (Slack, Jira) to five (Confluence).

## 9. Questions only the owner can answer

1. **Pub/Sub:** do services already count their own publishes in Chronosphere? How are
   subscriptions named? May Orchestra hold `monitoring.viewer` and `pubsub.viewer` in the projects
   that matter, and how many projects and topics are there?
2. **Slack:** may you create a user token in the work workspace, and may its metadata rest where
   Orchestra runs? What counts as answered, which pings count (you, your groups, DMs, `@here`),
   and does the 15 minutes run outside working hours?
3. **People as machines:** pseudonyms, names or teams only; does anyone need to agree?
4. **Jira and Confluence:** Cloud or Data Center; which projects and spaces?
5. **Google Docs:** which folders; does your Workspace admin allow third-party apps with Drive
   metadata scopes?
6. **Where it runs**, since this Mac cannot reach work: the same answer as the sources question.

### The owner's answers (2026-10-26, late evening)

1. **The latency statistic, label or suffix:** too detailed to say; assume a typical production
   Prometheus. So the design handles both spellings.
2. **Rollups:** yes, but by aggregate function (recording rules named like `:sum` and `:avg`), not
   by service. Discovery should recognise recording-rule names as views of their base metric.
3. **Where Orchestra runs:** on the owner's own machine, which is sometimes off. So:
   - every remote query is re-runnable for past ranges;
   - a model is built from whatever ranges answer;
   - discovery, bridges and counted-traffic pollers catch up after a gap instead of assuming
     continuity, and record the gap.
4. **Do services count their own Pub/Sub publishes?** Probably not. That would only cover expected
   Pub/Sub behaviour anyway, not buses in all but name. Publisher attribution therefore relies on
   the other methods (declared map, naming, IAM candidates, fitted split).
5. **Slack:** a user token is allowed. "Answered" usually means a checkmark emoji reaction, so
   that is the default rule, configurable.
6. **People:** by name, each with a team. Machines (people, bots, services) are grouped by team,
   as a label or a hierarchy. Grouping labels, never separates (rule 4).
