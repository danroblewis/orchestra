# Demo 5: risk calendar

Tab "5. Risk calendar" on `/demos`. Code: `sdlab/demos/risk_calendar.py` (it uses the case and simulators in
`sdlab/demos/capacity.py`), `sdlab/static/demos-risk-calendar.js`, tests `tests/test_demos_risk_calendar.py`.
Idea 29 of `OPERATIONALIZATION.md`.

## What it shows

The next 30 days of known events on ladder case `311-k8s-node-pool`, run through a stored found model and
through the true model. A calendar (one cell per day, Monday first) is coloured by the day's worst level of a risk
stock against a limit (green under 70%, amber 70-100%, red over), the found model's calendar beside the true one.
The page lists the days flagged by both, the days the found model **misses** (red outline) and its **false
alarms** (dotted amber), and marks the days where the found model goes more than 5% past the highest level of a
stock in the data it was fitted on (dashed border: it is extrapolating there).

Events (all editable):
- the weekly pattern already in the case's traffic (`400 + 220 sin` with a daily period; weekends 120 lower);
- a **launch** (default day 16, a Tuesday): traffic +40% that day and +10% on every day after;
- a planned **node maintenance** (default day 23, 12:00-16:00): one node out, 3 ready pods back to pending (as the
  case's node failure does), the node back after the window;
- optionally the case's own node failures (Mon, Wed, Fri 10:50) repeated every week.

Risk stocks and default limits: requests waiting (queue) 6,000; pods pending 5; requests waiting to retry 500.
Nodes: 3 (the case), 4, 5, 6.

## How it works

A step is 5 minutes (the kubernetes ladder; the traffic's daily sine has period 288), so 30 days are 8,640 steps;
step 1 is Monday 00:05 (the case's failures at steps 130, 706, 1282 are Monday, Wednesday and Friday 10:50).
The traffic series and injections are built once and given to both models: the true model as an in-memory copy
(explicit traffic series, injections, node count) in the truth engine without noise, the found model run free from
the case's start levels. One request runs both (about 2.5 s) and is cached in memory.

Endpoint: `GET /api/demos/risk-calendar/days?strategy=milp&stock=queue&limit=6000&nodes=3&launch_day=15&launch_boost=0.4&after_boost=0.1&maint_day=22&maint_hour=12&maint_hours=4&failures=false`
(days are 0-based in the API, 1-based on screen; `-1` means no launch or no maintenance).

## What it found (2026-10-22, `risk_calendar.calendar(...)`, milp #386951)

- **3 nodes, defaults:** queue over 6,000 on day 16 (launch: true 10,596, found 10,601, 9 hours over the limit
  in both) and day 23 (maintenance at peak: true 9,146, found 9,157, 5 hours). No misses, no false alarms. Normal
  weekdays peak at about 3,600 before the launch and 5,300 after it. Pods pending over 5: day 23 only (true 8,
  found 9). Retries over 500: days 16 and 23 in both. All five strategies flag the same pending days.
  The launch and maintenance days are marked "past the data" (queue and retries above the data's highest levels):
  the found model extrapolates there, along the limits it did see, and is right.
- **5 nodes:** the found model **misses the launch day**: the truth's queue reaches 6,017 (over the limit for
  0.6 h) while the found model says 1,829. The found models have no autoscaler maximum (16 pods; the data never
  reached it), so with room for 20 pods they scale past 16 and serve the launch. Every day is marked "past the
  data" (ready and desired above the data's 12 and 15), and the page says the forecast is unsupported where the
  missing limit would bind. With 5 nodes and the pending risk, day 23 is a found-only false alarm (found 5, true 3).

## Limits

- Noise-free, from the case's start levels; the 30 days are the case's own traffic formula carried on, not a
  forecast. The maintenance always moves 3 pods (the case's failure size), whatever the node held.
- One found model fitted on one week (none-long); its behaviour outside that week's range is exactly what the
  "past the data" marks warn about.
