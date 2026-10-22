# Demo 2: daily model diff

Ideas 1 and 7 of `OPERATIONALIZATION.md` (T2, comparison: the same method on both days, so its bias cancels). Page:
`/demos?demo=daily-diff`. Code: `sdlab/demos/daily_diff.py`, `sdlab/static/demos-daily-diff.js`, tests
`tests/test_demos_daily_diff.py`.

## What it shows

A service on two "days". **Day 1** is a stored, passing found model. **Day 2** is a simulated day with other traffic
(430 + 250 sin(…) requests a step against day 1's 400 + 220 sin(…)) and, on top, one real change made to an in-memory
copy of the true model. Day 2's model was discovered once by the same strategy. The page diffs the two **found** models
against each other, using no truth, as a git-style list and a diagram. Then it holds the diff beside the true change:
each edit is **right** (the true change found), **false** (an edit where nothing really changed), or the true change is
**missed**. It also says whether day 2's discovery passed against day 2's own true model. If day 2 failed, its edits
may be the strategy's mistakes rather than changes in the service.

Two services:
- **two-services** (case 313, lna; day 1 = result #386450, code bab9156). The changes: catalog called 50% more per
  request, a slower catalog, a new client-retry flow, a new frontend cache, and the quiet day.
- **memory-oom** (case 310, engine_forms; day 1 = result #386890, code 7e7bd2b). The changes: more retries / fewer
  give-ups, slower pod starts, a new response cache, and the quiet day.

## How it works

- **Edges.** The diff compares edges: a pair of ends (from → to, with outside as one end). Flows a model splits
  between the same ends are summed. An edge's amount each step is computed with the scorer's simulator for found models
  (`ladder/sim.found_model`, one step of a model made of just that edge's flows) on the states of both days. Each model
  carries its own hidden stocks along those states. Day 2's hidden stocks are matched to day 1's by what they touch, with
  no truth needed.
- **Kinds.** An edge is *changed* when the mean |day 1 − day 2| amount, divided by its size, is beyond its tolerance.
  It is *added* or *removed* when only one model has it. It is *redrawn* when it is written differently (another form,
  split flows) but moves the same amounts. Otherwise it is *same*. Comparing amounts rather than equations is what tells
  a cosmetic redrawing from a real change. (`algebra.check` is not used: it does not cover hidden stocks, which 310
  has.)
- **Tolerance.** Per edge: 3× the same comparison on the quiet day (same service, other traffic, no change), and never
  below 2%. An edge added or removed on the quiet day too is not counted again on a change day. It is labelled
  "redrawn: how this strategy redraws the model".
- **Against the truth.** An edit is right when a true change has the same ends (a found hidden stock takes the name of
  the truth's stock that day 1's scorer matched it to). A false edit that shares a stock with a missed change is flagged
  "shares a stock with the missed change".
- **Cache.** `~/.cache/sdlab/demos/daily-diff/<scenario>-<key>.json` holds the found flows, seconds, the status against
  day 2's truth, and the code commit. `day1-again` is day 1 re-run at the precompute's commit, as a check.
  Regenerate it with:
  `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 nice -n 19 uv run python -m sdlab.demos.daily_diff precompute [two-services|memory-oom] [key ...] [--force]`
  (two-services takes seconds; memory-oom took about 7 CPU-minutes).
- **API.** `GET /api/demos/daily-diff/changes`; `GET /api/demos/daily-diff/diff?scenario=…&change=…` (0.1-0.6 s).

## What it found (2026-10-22, from `daily_diff.diff(scenario, change)` on the cache above)

**two-services / lna** (day 1 re-run at HEAD: identical to the stored model; the quiet day's largest edge difference
is under 0.001%, so the 2% floor sets the tolerance):

| day 2 | day 2 vs its truth | right | false | missed | what the diff says |
|---|---|---|---|---|---|
| quiet | pass | 0 | 0 | 0 | no edits |
| catalog called 50% more | pass | 1 | 0 | 0 | `~ outside → catalog_queue` 0.3 → 0.45 × frontend_inflight |
| slower catalog | pass | 1 | 0 | 0 | `~ catalog_inflight → catalog_responses_total` 0.5 → 0.3 |
| new frontend cache | pass | 1 | 0 | 0 | `+ frontend_queue → frontend_responses_total` 0.1 × frontend_queue |
| new client retry | **fail** | 0 | 2 | 1 | lna drew the new 0.05 × frontend_inflight as a move into catalog_queue and cut the catalog link 0.3 → 0.25. The true frontend_inflight → frontend_queue is missed. |

**memory-oom / engine_forms**: engine_forms **fails every day 2 tried** against that day's own truth (quiet 45 s,
retries 188 s, slow starts 63 s, cache 54 s). With other traffic it loses the hidden leak and rewrites the memory, retry
and pod flows. Even the quiet day has 12 false edits (largest edge difference 190%). Results: retries 0 right, 6 false,
2 missed; slow starts 1 right (pending → ready 0.5 → 0.186, true 0.2) and 4 false; cache 1 right (queue →
responses_total 0.1 × queue) and 7 false. The page shows this as it is: a diff is only as good as both days'
discovery. The day 1 re-run at HEAD is identical to the stored model, so the cause is day 2's data, not a code change.

## Limits

- Noise-free data only (none-short variants). With counted data the quiet-day spread, and so the tolerance, would be
  much larger. That would need several quiet days, not one.
- The amounts are compared on the two days' states only. Two models that agree there but differ elsewhere (an effect
  table beyond the levels seen) count as the same.
- Right / false is judged by ends. An edit drawn between other stocks that carries the true amount (313's client
  retry) is counted false plus missed, with a "shares a stock" hint.
- The 310 diagram layout is fixed for the two scenarios' stocks. Any other stock goes in spare cells below.
- One discovery run per day: there is no run-to-run spread for a strategy with randomness (lna and engine_forms are
  deterministic here).
