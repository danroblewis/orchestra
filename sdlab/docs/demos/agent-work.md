# Demo 13: Agent work as stocks

Tab **13. Agent work as stocks** on `/demos` (`?demo=agent-work`). Ideas 41-46 in `OPERATIONALIZATION.md`
(category G, AI agent orchestration).

## What it shows

This is a simulated team of AI agents working tickets. Tickets are stocks by state, and the agents are the machines
that move them. Discovery finds a model from the ticket counts alone. The demo then reads off what a manager wants to
know and puts the true model's answer beside each one:

- **Agent throughput:** the most tickets one agent gets done in a day (idea 42).
- **The rework loop:** the share of reviewed tickets that review sends back to the backlog (idea 44).
- **The merge gate:** the most tickets landed in a day, with 8 agents and with 16.
- **Agents needed to keep up:** arrivals ÷ (1 − rework share) ÷ tickets per agent, a flow balance (idea 45).
- **The bottleneck as agents are added:** for 2 to 20 agents, both models run two weeks on from day 30. The page
  shows tickets done a day, where the work piles up (theory of constraints) and the lead time by Little's law.
- **What-if:** add N agents (and optionally more arrivals) and run two weeks, found model beside true model.

## How it works

The simulated system lives only in `sdlab/demos/agent_work.py` (`truth_model()`). It is not a ladder case. One step
is one hour, and 30 days are measured with no noise.

| flow | true rate |
|---|---|
| outside → backlog | `arrivals` (a measured input: 1.8 + 1.2·sin(day) tickets an hour, 43.2 a day) |
| backlog → in_progress | `0.2 × backlog` |
| in_progress → in_review | `min(0.4 × in_progress, 0.5 × agents)` (each agent does at most 12 tickets a day) |
| in_review → merging | `0.24 × in_review` |
| in_review → backlog | `0.06 × in_review` (rework: a fifth of review's outflow) |
| merging → done | `min(0.5 × merging, 2.2)` (merge gate: at most 52.8 a day) |

`agents` is a measured stock set by hand, like `ready` in ladder case 306: 4 agents, then 8 from day 12. The change
is announced as an injection. The declared boundary says tickets enter only at the backlog, from an input.

The data comes from the ladder's engine (`ladder.data.simulate`). Discovery ran once per strategy through
`ladder.runner.discover`, the same call `run_item` makes, and the found models are cached in
`~/.cache/sdlab/demos/agent-work/found-<strategy>.json`, together with the strategy's code commit, its run time and
a hash of the true model. If the true model changes, the page marks the cache stale. To regenerate it
(single-threaded, about 2 minutes for milp and 2 s for earned_pieces):

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  nice -n 19 uv run python -m sdlab.demos.agent_work precompute milp earned_pieces
```

The readings evaluate the model's rates rather than parsing them, so any form a strategy writes can be read. The
same reading is applied to the true model.
- A cap on what leaves a stage is that stage's outflow when its pile is huge (1e5).
- Tickets per agent is the cap on in_progress at 8 agents, divided by 8. The cap is checked again at 16 agents to
  see whether it grows with the agents.
- The rework share is review → backlog divided by everything leaving review.

Forecasts start from the true levels at day 30. The found model runs free with the same arrivals and agent count as
the true model. The bottleneck of a forecast's last week is:
- the stage still growing (by at least 0.5 tickets a day);
- otherwise, the stage whose outflow runs at its cap for the largest share of hours (at least 5%);
- otherwise "none".

Endpoints: `GET /api/demos/agent-work/overview`, `/sweep?strategy=&extra=`, `/forecast?strategy=&add=&extra=`.
Each answers in about 1 s or less.

## What it found (2026-10-22, code 272adc6)

From `uv run python -c "from sdlab.demos import agent_work as A; print(A.overview()['models'])"` and `A.sweep(s, extra)`.

Six strategies were tried while choosing (lna, earned_pieces, mass_balance, numopt_powell, milp, engine_forms). Two
are cached:

| | true | milp (123 s) | earned_pieces (1.7 s) |
|---|---|---|---|
| tickets a day per agent | 12 | **12.0** | **12.0** |
| rework share | 0.20 | **0.20** | **0.20**, but review's other flows are split wrongly (in_review → done 0.185, → merging 0.055) |
| merge gate, 8 agents (a day) | 52.8 | 52.6 | **missed**: merging → done = 0.0071 × merging, no cap |
| merge gate, 16 agents (a day) | 52.8 | **103.6** (wrong) | missed |
| agents needed (flow balance) | 4.5 | 4.5 | 4.5 |

- **The agents' MIN cap is found exactly** by every strategy tried: `min(0.4 × in_progress, 0.5 × agents)`. The
  rework flow review → backlog `0.06 × in_review` is found by all of them too. lna and engine_forms also got it, but
  with other review flows that run backwards or skip merging.
- **The merge gate is not identifiable from this data.** The gate only bound after the dial went to 8 agents, and the
  number of agents never changed again. A fixed cap of 2.2 an hour and a cap of 0.275 × agents fit the data the same.
  milp chose a cap that grows with the agents (`min(0.478 × merging, 0.266 × agents)`, plus a small extra flow
  `min(0.161 × merging, 0.0127 × in_progress)`). earned_pieces, mass_balance, numopt_powell, lna and engine_forms
  found no gate at all.
  This is real evidence for agent orchestration: to learn a gate's capacity, the data needs the gate binding under
  different team sizes (or a deliberate experiment, idea 14).
- **The what-if.** At today's arrivals (43.2 a day), both found models agree with the truth: past 4 to 6 agents,
  more agents buy nothing, and all 43.2 tickets a day get done. In a busier month (+0.6 tickets an hour, 57.6 a day),
  the truth tops out at **52.8 a day from 6 agents on**, held by the merge gate, whose pile keeps growing. Both found
  models wrongly promise **57.6 a day** (milp from 10 agents, earned_pieces from 6), +9.1% and +8.1%, and say no stage
  is a bottleneck. The bottleneck stage agrees on 5 of 10 team sizes for milp (2 and 4 agents: in progress; 6 to 10:
  merging) and 3 of 10 for earned_pieces.
- **Lead time** (Little's law) at 8 agents and today's arrivals: true 15.5 h, milp 15.5 h, earned_pieces 20.7 h.

## Limits

- Noise-free data, fractional tickets. A counted (Poisson) variant was not run.
- The agents dial changes once (4 → 8). That is exactly why the merge gate is not identifiable. A dial that moves
  more often would probably fix it, but this was not tested.
- Real agent work has no fixed rate per agent: ticket sizes vary, and agents fail and retry. The fitted rate has no
  interval here (idea 42 asks for one).
- The bottleneck rule reads the model's own caps, so a model without a cap (earned_pieces' merge) cannot name that
  stage. That failure is reported, not hidden.
- Only two found models are cached. Others need a precompute (keep it within the CPU limits).
