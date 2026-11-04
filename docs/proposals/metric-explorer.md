# The metric explorer

Status: proposed (2026-11-04, from the owner's first day on Chronosphere at work).

## Why

Discovery fits the dynamics of what it is given, deterministically, and that part works. What it is
given is the problem: which families to read, how to split them, which counts are flows, which latency
families imply a level, which PubSub series make a backlog, and what to call things. On a real store
that is open-ended judgement, and the families that would close a loop are usually ones nobody
configured. A program that ranks labels by behaviour (C18) is not enough; the owner spent a day doing
this judgement by hand.

So the judgement goes to an agent, and the fitting stays a program: **the explorer reads, discovery
concludes.** The explorer's output is configuration and hypotheses, both recorded with provenance;
discovery's verdicts on them are the explorer's only feedback. Its non-determinism stays in what is
read, never in what is concluded.

## Two scopes

- `match` (exists): what the model reads. Narrow and deliberate.
- `explore` (new, per source, set by the owner, never by the explorer): what the explorer may look at,
  wider, for example `explore = ['{namespace="payments"}', '{__name__=~"gcp_pubsub_.*", project_id="…"}']`.
  Inside it only bounded reads are allowed: the name index and label values with `match[]`, metadata
  per metric, a few sampled series per family, all counted against the store's `rate` and daily cap,
  logged in the request log with `by: explore`. A selector matching everything is refused, as today.

## The loop (one round, on a schedule)

1. **Read the state:** the latest discovery and its explain records, the run record and health, the
   left-out reasons, the request log's cost, and the experiment log (below).
2. **Look both ways.** Too strict: a level with no drivers ("1 form tried"), a flow with no stock,
   "no counters balance", an obvious partner family (same service, subscription, prefix) inside
   `explore` but outside `match`. Too loose: spurious stocks, low trust everywhere, series no fitted
   equation reads, high-cardinality families eating the budget, slowing runs.
3. **Probe** the candidates within `explore`, bounded.
4. **Propose one experiment:** a change to `match`, `split`, `kinds` or `names`, or an expected flow in
   the declared layer ("the backlog drives the ack rate"), with its expected effect in words.
5. **Apply** it on the owner's standing rule (for example: narrowing and naming without asking,
   widening `match` only on a yes) or ask in one sentence.
6. **Judge** it after the next N discovery rounds against the last: stocks kept, trust, fits, crossings,
   store cost. Keep or revert on that evidence, and record the verdict.

## The experiment log

`<state>/model/explorer.jsonl`, one entry per experiment: the change, its expected effect, the runs
before and after, the measured effect, the verdict (kept, reverted, inconclusive), and why. The explorer
reads it first each round, so it never retries what failed until the data changes; the Dynamics page's
run drawer shows it beside the discovery runs.

## Where it runs

- **On the work laptop now, with no plugin:** a prompt file (`docs/EXPLORER-PROMPT.md`) for a Claude
  Code session, run by hand or on a schedule (`claude -p` from cron or launchd), using Orchestra's
  commands: `orchestra sources explore` (new: the bounded survey of `explore`), `sources infer`,
  `sd discover`, the explain API, and `orchestra explorer log` (new: append and read experiments).
- **As a machine in the agents plugin later:** the same prompt and tools as a scheduled agent machine,
  on Sonnet or Haiku with a daily token budget; its stable rules graduate into inference code, as the
  `kinds` conventions did.

## What stays programmatic

Discovery, the fitting, R², refuted forms, trust, and the judgement of every experiment. The explorer
never edits a model, never binds a series to a stock (rule 7), never declares a machine without the
owner's yes (rule 2), and never widens its own `explore` scope.

## Build order

1. Core: the `explore` scope, `orchestra sources explore` (bounded, logged), the experiment log and its
   CLI, the run drawer showing experiments, docs in `orchestra/guide.md`.
2. The explorer prompt for a Claude Code session, tested against the kube-sim demo and a fake store.
3. The agents plugin's explorer machine, when the owner wants it.
