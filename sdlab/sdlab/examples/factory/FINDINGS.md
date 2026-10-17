# Discovering Orchestra's flows from its ticket counts

**The data.** `factory.json` has one stock per ticket state: OPEN, IN_PROGRESS, READY_FOR_REVIEW, IN_REVIEW, APPROVED, MERGING, REJECTED, BLOCKED, DONE and CANCELLED. It has no flows. The `history` program replays the factory's `events.jsonl` (a created ticket goes to OPEN, and each transition moves it) into ticket counts per state at the end of every 15-minute step. That gives 440 steps, about 110 hours, from 2026-10-11 20:23 to 2026-10-16 10:20 UTC. Its final counts match `tickets.json`: 21 DONE, 14 CANCELLED, 4 OPEN, 2 APPROVED and 1 IN_PROGRESS.

**The truth (discovery never sees it).** 1,666 transitions, of which the largest:

| Transition | Count |
|---|---|
| OPEN → IN_PROGRESS | 372 |
| IN_PROGRESS → OPEN | 283 |
| READY_FOR_REVIEW → IN_REVIEW | 172 |
| IN_PROGRESS → READY_FOR_REVIEW | 166 |
| REJECTED → IN_PROGRESS | 143 |
| APPROVED → MERGING | 87 |
| IN_REVIEW → APPROVED | 84 |
| IN_REVIEW → REJECTED | 82 |
| IN_PROGRESS → BLOCKED | 65 |
| BLOCKED → OPEN | 63 |
| MERGING → REJECTED | 61 |
| MERGING → DONE | 21 |

**What discovery found** (whole history, 5-step windows, which is the page's default):

| Discovered | Per 15 minutes | What it really is |
|---|---|---|
| outside → DONE | 0.080 (35 in all) | 42 tickets created into OPEN, plus 21 MERGING → DONE: everything that ended in DONE or CANCELLED |
| DONE → CANCELLED | 0.032 (14 in all) | Not a real flow, because DONE is final. The amount is exactly the real cancellations (12 from OPEN, 2 from BLOCKED) |

It found none of the 17 real transitions as itself. It reported no persistent unexplained drift and no hidden-stock hint. Windows of 3, 4 and 6 steps give the same two flows.

## Other views of the same history

| Run | What discovery found |
|---|---|
| First hour dropped | OPEN → DONE: the whole pipeline as one arrow. Also MERGING → IN_PROGRESS, which is the gate sending work back through REJECTED; REJECTED itself is too brief to see. |
| Eras at the operator's capacity cuts (steps 51 and 236) | The drain into DONE is fast before the cut to 3 workers, slow after it, and stops after the cut to 2. That matches the cuts. |
| 1-minute steps | The forward chain OPEN → IN_PROGRESS → IN_REVIEW → MERGING → IN_PROGRESS, and IN_PROGRESS → BLOCKED, at 5 to 50 times below the real rates |
| 60-minute steps | Only the arrivals into DONE and CANCELLED, plus an invented REJECTED → APPROVED |

What a perfect observer of the step ends could see at 15 minutes:
- OPEN → IN_PROGRESS: 372 real transitions, but only 19 show at step ends.
- IN_PROGRESS → IN_REVIEW: 99 show, by way of READY_FOR_REVIEW.
- IN_REVIEW → IN_PROGRESS: 82 show, by way of REJECTED.
- MERGING → DONE: none show. Those tickets appear to reach DONE from IN_PROGRESS (11), IN_REVIEW (7) or APPROVED (2).

## Why it found so little

1. **Most of the real flow is loops.** A worker times out, the ticket goes back to OPEN, and it's picked up again within the second. The review and rejection loop works the same way. A ticket that goes round a loop between two measurements changes no level. So these flows can't be identified from levels at any step size, and discovery's price on movement leaves them out by design.
2. **The step is longer than most stays.** READY_FOR_REVIEW, REJECTED, APPROVED and MERGING are usually left within seconds or a minute. They are empty at 95–99% of step ends, so their flows merge into arrows that skip them.
3. **The system is small and nearly steady.** The middle stocks hold 0 to 6 tickets. Only DONE and CANCELLED move steadily, and they dominate the fit.
4. **Creation came in a burst.** 29 tickets were created and 8 cancelled in the first quarter hour, so one flow from outside explains everything.
5. **Nothing warns you.** Because the missing flows are loops, they leave no drift, and the page shows no warning even though more than 1,600 transitions went unseen.

## What would recover it

Discovery from levels sees only *net* movement between measurements. For a fast, loopy system like this one, you also have to measure the flows: for example, a sensor that reports the transition counts per step as the run's measured flows. Discovery would then explain only what those don't. Levels alone show what accumulates; to see what circulates, you have to measure the flows.

The DONE → CANCELLED and CANCELLED → DONE suggestions show that a "final stock" marker would help: a final stock can't feed another stock.
