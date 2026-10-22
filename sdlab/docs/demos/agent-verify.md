# Demo 16: Verify an AI agent's effect

Tab **16. Verify an AI agent's effect** on `/demos` (`?demo=agent-verify`). Ideas 42 and 43 in
`OPERATIONALIZATION.md` (category G, AI agent orchestration): before deploying an agent, state how it should change
the model; after deploying it, check through the model whether it did.

## What it shows

- A support system simulated by a **discrete-event simulation**, not by system dynamics equations.
- A **best-effort SD model** discovered from that system's counts. It is not verifiably correct, since there is no
  SD truth, and the page measures how wrong it is.
- An **AI agent**: a separate program that joins on day 21 and emits its own events into the simulation.
- The **design's intended effect**, written as an edit to the found model, which predicts the next three weeks.
- **After deployment**, the agent's effect measured through the found model, beside the **true effect** from the
  event log.
- **Plain verdicts:** did the agent do what was intended (yes / partly / no), with which side effect, and did the
  model's view reach the same verdict?

There are three agent variants: one that works as designed, a weak one, and one that closes many items wrongly.
The design's claims are the same for all three; what differs is how each agent really behaves.

## The system (`sdlab/demos/agent_verify_des.py`)

The simulation keeps a heap of timed events. Time is in hours. Each item (an alert or a ticket) is an entity with its
own seeded random draws.

- **Arrivals** follow a non-homogeneous Poisson process, drawn by thinning. Weekdays average 4.6 an hour, with a
  day/night swing of ±60%. Weekends get 60% of a weekday's arrivals. That is about 100 new items a day.
- **On-call engineers** follow a shift schedule: 4 from 08:00 to 20:00 on weekdays (5 in the 19:00-20:00
  handover), 2 by day at weekends, and 1 at night. Each engineer triages one item at a time, oldest first. Triage
  takes a lognormal time, 27 minutes on average (coefficient of variation 0.6). An engineer whose shift ends
  finishes the item in hand.
- **Fixes:** 30% of triaged items need a fix. The dev team works fixes in parallel, taking a lognormal 4 hours on
  average. The other items are resolved at triage.
- **Rework:** 5% of resolved items reopen after an exponential delay (24 hours on average) and go back to the
  queue.
- **The log:** every event is written to an event log (hour, who, what, which item).
- **What monitoring sees:** every 15 minutes, the number of items queued (waiting for triage), in triage, in fix
  and resolved (net of reopens), plus the new items and the mean engineers on shift in that step. Discovery gets
  only these counts, with the new items and engineers as measured inputs. The declared boundary says items enter only
  at the queue, as exactly the new items.

**The agent** (class `Agent`) is a separate program. The simulation tells it about new items and freed slots. It
decides by its own rules and schedules its own events. From day 21 it takes each new item (never a reopened one)
while it has a free slot: 3 slots, a lognormal 4.2 minutes per item. Then it does one of three things:
- resolves the item;
- closes it wrongly (a misroute: the item reopens after an exponential 6 hours);
- hands it to the humans with a triage note that multiplies their triage time by the note factor.

| variant | resolves | closes wrongly | note factor |
|---|---|---|---|
| good (as designed) | 35% | 2% | 0.7 |
| weak | 10% | 2% | 0.95 |
| misrouting | 20% | 18% | 0.7 |

**Common random numbers.** The arrivals and each item's draws come from streams that do not depend on other items. So
the run with the agent and the run without it see the same items, and before day 21 the two runs are identical (a
test checks this). The true effect is the difference between the two runs, read from the event logs.

## The design and its edit

The design says:
- the agent resolves 35% of new items itself;
- its notes make human triage 30% shorter;
- it closes at most 2% wrongly.

So the queue should fall by about 50%, the hours an item is open by about 30%, and reopens should rise by at most
2.5 a day (2% of about 100 new items, plus a quarter for slack).

Written as an edit of the found model (`design_edit`):
- a new flow `queued → resolved = min(0.35 × new_items, 10.7 a step)`, the cap being 3 slots ÷ 4.2 minutes;
- the humans' triage numbers divided by 0.7. These are every number the model multiplies `engineers` by, and every
  share of `in_triage` that leaves it in a step. They are read from the text after each number, because
  `engine.numbers`' label can run past a comma inside `min(...)`.

The prediction is the edited model, run free from the measured state on day 21 with the after-period's inputs. Its
effect is measured against the unedited model on the same inputs.

## Measuring the effect through the model

- **Counterfactual:** the found model, unedited, run free from day 21 on the after-period's new items and engineers.
  Measured minus counterfactual gives the effect on the queue and on the hours open. Hours open use Little's law:
  items open ÷ new items an hour.
- **Closes the model cannot explain:** the measured change in `resolved` minus the model's one-step prediction, regressed on
  the new items in that step plus a constant. The slope after deployment minus the slope before is the share of new
  items that something the model lacks closes quickly. The same regression on the same weeks of the run without the
  agent gives the noise: ±1.4 points.
- **What was tried and dropped.** First, a refit of all 13 numbers of the found model by one-step least squares. It
  moved even the input's gain of 1 (to 0.64), so the numbers meant nothing. Second, a refit of three levers: the
  triage speed, a constant rework flow and the agent's share. Even before the agent, it put the triage speed at
  ×0.43, and the rework constant at −45 a day on both sides. Neither result was usable, so the page does not
  measure the notes' speed-up or the rework through the model. It says "cannot see" instead.

## The found models

Discovery ran once per strategy, on the first 21 days (2016 steps), through `ladder.runner.discover`, the same call
`run_item` makes. The found models are cached in `~/.cache/sdlab/demos/agent-verify/found-<strategy>.json`, with the
strategy's commit, its run time and a hash of the data it saw. The page marks a stale cache. Each variant's analysis
is cached beside them (`analysis-<strategy>-<variant>.json`), keyed by the code and the found model.

Seven strategies were tried on the same data. The two with the smallest free-run error are cached:

| strategy | seconds | queue free-run error | in triage | in fix |
|---|---|---|---|---|
| **censored** | 39 | 5.79 | 0.79 | 2.75 |
| **engine_forms** | 64 | 6.00 | 1.59 | 2.32 |
| combined2 | 81 | 6.15 | 2.26 | 4.87 |
| lna | 42 | 7.29 | 2.35 | 2.43 |
| milp | 36 | 9.93 | 2.44 | 2.20 |

earned_pieces and mass_balance were tried too, while choosing the sampling. They are not in the table because their
fit was not kept.

**Why 15-minute samples.** At hourly sampling, most items are triaged within one step, and every strategy tried
(earned_pieces, lna, mass_balance, censored) wrote the queue's inflow wrongly:
- with the boundary kind `input`: `min(queued, 0.86 × engineers)`;
- with the kind `measured`: 0.36-0.48 × new_items.

With `measured` at 15 minutes, earned_pieces and lna still gave 0.93 and 0.78 × new_items. So the cache uses
15-minute samples and the `input` kind, which holds the inflow at exactly 1 × new_items.

Errors are root-mean-square, in items, over days 0-21. The measured means are queue 6.34, in triage 2.04 and in fix
5.14.

**What the model gets wrong** (censored):
- **Its structure is not the system's.** It writes `queued → in_fix = min(0.9997 queued, 0.603 engineers)` and
  `in_fix → in_triage`, and items "resolved" straight from the queue. In the simulation every item passes through
  triage. These flows are its way of writing triage that starts and ends within a quarter hour.
- **It has no reopening.** Its only flow back into the queue is `in_fix → queued = 0.036 × in_fix`.
- **Its free run is too low on the queue:** a mean of 3.86 against 6.34 measured. After deployment, its
  counterfactual puts 4.17 items in the queue where the true counterfactual has 5.99, and 2.38 hours open per item
  where the truth has 3.16.
- **One step ahead it is fair:** an error of 1.08 items on the queue.

## What it found (2026-10-22)

From `uv run python -m sdlab.demos.agent_verify analyse`, which reads the cache, or `GET
/api/demos/agent-verify/verify?strategy=censored&variant=...`.

The after-period is days 21-42: 2,116 new items, about 101 a day.

| variant | claim | intended | predicted (model + edit) | through the model | true (event log) |
|---|---|---|---|---|---|
| good | resolves itself | 35% | 35% | 40.5% (counts every close) | **33.6%** (+2.0% wrong) |
| good | queue | −50% | −67% | −82% | **−87%** |
| good | hours open | −30% | −47% | −46% | **−59%** |
| good | reopens a day | ≤ +2.5 | 0 | cannot see | **+1.8** |
| weak | resolves itself | 35% | 35% | 13.4% | **9.7%** |
| weak | queue | −50% | −67% | −13% | **−39%** |
| weak | hours open | −30% | −47% | +2% | **−23%** |
| misrouting | resolves itself | 35% | 35% | **37.2%** | **19.0%** (+17.2% wrong) |
| misrouting | queue | −50% | −67% | −58% | **−71%** |
| misrouting | hours open | −30% | −47% | −26% | **−44%** |
| misrouting | reopens a day | ≤ +2.5 | 0 | cannot see | **+17.5** (5.3 → 22.8) |

The triage speed-up is true ×1.37 (good), ×1.05 (weak) and ×1.28 (misrouting), against ×1.43 intended. The model
cannot see it.

Verdicts, censored model:
- **good: yes** in truth (6 of 6 claims met) and **yes** through the model. The model's view is right, but it
  undercounts the effect: −82% against −87% on the queue, and −46% against −59% on the hours open. Its own
  prediction was more cautious than the outcome (−67%).
- **weak: partly** in truth (the queue −39%, the hours −23%, both short of the targets but more than half) and **no**
  through the model (−13%, +2%). The model sees the low resolve share correctly (13% against 10% true), but
  underrates the weak agent's real benefit by about two thirds.
- **misrouting: no** in truth: a harmful side effect, with 17.5 more reopened items a day, 7 times the allowance.
  Through the model it is **yes, a wrong verdict**. In the counts, a wrong close looks like a resolution (the model
  sees 37% closed, the truth is 19% right and 17% wrong), and the queue still falls by 58%. The found model has no
  reopen flow, so the harm is invisible to it. Only the ticket system's reopen counter shows it (4.9 a day before,
  22.8 after). That counter is not given to discovery.

The engine_forms model reaches the same truth verdicts. Its views differ:
- **good:** "partly", because it sees only 29.6% closed by the agent;
- **weak:** "no";
- **misrouting:** "partly", seeing 27.7% closed. That catches the shortfall but not the harm.

**The lesson for operations.** A model discovered from counts can confirm that an agent moves work as planned. It
cannot tell a right close from a wrong one: that needs a measured rework metric (a reopen counter, or reopens
as their own flow) before the agent ships. That is idea 53, "find missing metrics", applied to agents. The model's
counterfactual is also biased, because it free-runs the queue low, so the size of an effect read through it is off
by 5-30 points even when the verdict is right.

## Endpoints and commands

- `GET /api/demos/agent-verify/overview`: the design, the system's numbers and the cached strategies.
- `GET /api/demos/agent-verify/verify?strategy=censored|engine_forms&variant=good|weak|misrouting`: the analysis
  and the verdicts, read from the cache in well under a second.
- Regenerate the cache. This is single-threaded and takes about 2 minutes: 39 s for censored, 64 s for engine_forms,
  and a few seconds per variant.
  ```sh
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
    nice -n 19 uv run python -m sdlab.demos.agent_verify precompute [strategy ...]
  ```
- Tests: `uv run pytest -q tests/test_demos_agent_verify.py`. They cover the simulation's determinism, item
  conservation, common random numbers, the agent's log, the true shares, the design edit, the verdict rules and the
  routes. The routes test is skipped without the cache.

## Limits

- **One seed, one deployment day.** There is no interval on any number. The ±1.4 points of noise on the close share
  come from one placebo window.
- **The thresholds are the demo's own choices.** A share must be within 10% of plan; a cut must reach 80% of its
  target; "no" means less than half the target, or reopens above 3× the allowance. They are stated on the page.
- **The true "hours open"** is each item's open time from the log (every item opened in the after-period closed
  within the 3 days simulated past the end). The model's "hours open" comes from Little's law on the counts. Both
  exclude the time an item sits resolved before it reopens.
- **What the found models miss.** They never had a reopen flow, so the demo cannot show what a model with one would
  have caught. Giving discovery the reopen counter as its own measured stock was not tried.
- **What the page does not measure.** The notes' speed-up and the rework are not measured through the model (see
  "What was tried and dropped"). The page says so rather than showing a number.
- **The agent's slots never bind** at about 100 items a day, so the design's cap is untested.
