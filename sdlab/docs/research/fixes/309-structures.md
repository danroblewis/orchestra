# 309 (k8s-pod-startup): structures, the noise-free and counts variants

**Status:** none-short and none-long pass; counts-short and counts-long fail on data limits. 2026-10-21, agent
structures-309 (structures lock held for the work, released after the commit).

## Before (store, code 4f04ce1)

`uv run sdlab-ladder show 309 --strategy structures --variant V`:

| variant | status | what was wrong |
|---|---|---|
| none-short | FAIL (14/18) | `ready -> outside = 0.1204 ready` (true `ready - desired`, floored at 0) and a spurious move `desired -> ready = 0.1176 desired`; with that move the controller (308's `controller.py`) refuses `desired` (it has a move), so `desired`'s two HPA flows stayed linear drifts (909%, 156%) |
| none-long | ERROR | the output-error refit (oefit) raised (`SystemError` from numba `_sens`; here, locally, `LinAlgError: SVD did not converge`): it ran because the drift fits above left non-white residuals |
| counts-short | FAIL (11/18) | retries split; `outside -> pending` a constant; `ready -> outside = 0.0026 ready` |
| counts-long | FAIL (11/18) | retries split; `outside -> pending` a bilinear proxy; `ready -> outside = 0.0029 ready` |

## Diagnosis (rule 4b)

`uv run sdlab-ladder analyse 309 --variant V`:

- **none-short and none-long: UNIDENTIFIABLE (p 0.000) only through the retries equivalence** (`retries -> queue` with a
  drain against a link reading retries, "the same levels with as many numbers"), the same verdict as 308 none-short,
  which structures passed. Every bound SE is below 1e-4 of the allowed error. They are achievable, and so they were the targets.
- **The failures there are a method fault.** In-process check (scratchpad `s309/look.py`): with the measured levels,
  `max(0, ready - desired)` reproduces ready's outside change to the data's rounding (5e-5), and `max(0, desired - pending - ready)`
  reproduces pending's. The engine floors every rate at 0, so the truth is the *linear* rates `ready - desired` and
  `desired - pending - ready` (the scorer's parts are those coefficients). The floor binds on 289 of 300 steps for ready's
  outflow (it moves only on 11), so a least-squares fit that treats the rate as linear everywhere cannot find it: it fits a
  small drift and routes the misfit through a move from `desired`.
- **counts-short: DATA-LIMITED, p 0.010** (retries -> outside p 0.28, outside -> pending [ready] p 0.28, ready -> outside p 0.30).
- **counts-long: DATA-LIMITED, p 0.253** (retries -> outside p 0.63, retries -> queue p 0.77, outside -> pending p 0.67,
  ready -> outside p 0.68). Neither counts variant is a target.

## Fixes kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| floored-rate | **Outside rates fitted under the engine's floor.** For each measured stock's outside side that the declared boundary estimates (with no declared boundary: a side that already has an outside flow), the side's flow is refitted as one floored linear rate `max(0, c + w . X)`, X among the measured levels and inputs (a link: may cross units; capmin's offered series excluded). Columns are chosen forward on BIC (the first step also tries every pair: a gap's floor binds only with both its sides, the stock and its goal), then backward. The fit is Gauss-Newton on the hinge (a floored rate counts only on the steps where it is above 0), started from the steps where the remainder moves, with the stock's own outside flows refitted with it (and, as a second candidate, its moves too). Each candidate is also offered with one of the stock's moves dropped (the move the misfit was routed through). A candidate is offered only when the floor explains the row: the floored fit beats the same columns fitted unfloored by 2 log n, and the floor binds on at least 3 steps. It is then also refitted under the floors on all stocks, for the flows touching the changed stock and a dropped move's ends (an input side's flow held at 1 x series). It replaces the model when combined's judge (`judge.score`, the one-step likelihood with the engine's floors, BIC price), with the controller forms applied to both, is lower by more than log T. The best change is taken; up to 4 rounds. | 3bf52d6, 13122fe | `structures/floor.py`, called in `__init__.identify` after the linear identify and before the output-error refit (`oefit.refit`) | copy `floor.py` (it needs a judge with `Data`, `one_step`, `score`, `simulate.Model`, and a controller pass; with none, pass an identity for `_post`) and call `floor.apply(result, stocks, run, opts, judge_opts=<opts the fit saw>)` on the linear answer *before* any output-error or measurement-error refit, which would otherwise read the drift's correlated residuals as measurement error. It is inert where no floor binds: a rate whose floor never binds is a linear rate, and those candidates are not offered. |
| refit-guard | the output-error refit no longer fails the whole answer when it raises (it keeps the answer it was given and records `oefit_error`) | 3bf52d6 | `structures/__init__.py` | wrap the strategy's own `oefit.refit` call the same way |

Found on 309 (in-process, the same commit, scratchpad `s309/full.py`): none-short and none-long
`ready -> outside = 1 ready - 1 desired` (the move `desired -> ready` dropped), none-long also
`outside -> pending = 1 desired - 1 ready - 1 pending` (from a constant-plus-drain proxy), and then the controller
gets `desired` (`max(0, min(16, ceil(cpu / 192.5)) - desired)` and `1 * (desired > ceil(cpu / 157.4))`), since it no
longer has a move. On counts-long the floor finds `ready -> outside = ready - desired` and
`outside -> pending = 1.011 desired - 1.012 ready - 1.42 pending` (inside the scorer's allowed error for pending's parts).

Unit test: `tests/test_structures_floor.py` (a surplus outflow that the floor shapes replaces a drift and a spurious move;
a rate whose floor never binds is left alone).

Two corrections between the commits (13122fe), both seen on counts-long in-process:

1. 3bf52d6 refitted the baseline globally. On a model that is missing the retries move, that refit moved
   `queue -> retries` from 0.078 to 0.053.
2. 3bf52d6 also accepted a floored `retries -> outside = 0.94 retries - 0.046 queue`. Its floor gains 0.8 nats against the
   same columns unfloored, which is no evidence for a floor.

The gain test and the local refit remove both.

## After (pool job 259, commit 13122fe)

`uv run sdlab-ladder submit --strategies structures --cases 309 --variants none-short,none-long,counts-short,counts-long --priority 400 --by structures-309 --check-tree strategies`,
`uv run sdlab-ladder job 259 --wait` (Mac workers):

| variant | status | notes |
|---|---|---|
| none-short | PASS (42 s) | |
| none-long | PASS (220 s), 18/18 parts | |
| counts-short | FAIL, 15/18 | retries split (data-limited); `outside -> cpu [ready]` missing: the search's hidden chain `outside~cpu~h1 -> cpu` replaced it (upstream of floor.py; the run at 4f04ce1 had 18.31 ready) |
| counts-long | FAIL, 16/18 | only the retries split (`retries -> queue` missing, `retries -> outside = 0.94`): data-limited |

Job 258 (commit 3bf52d6, the first version) also passed none-short and none-long (node2).

## Proposed, not made

| type | mechanism | how another strategy adopts it |
|---|---|---|
| chain-guard | counts-short: a hidden chain into `cpu` offered by the search replaced the link `20 x ready`. A chain should be offered only when it beats the measured links into the same stock that it displaces (here `ready`, measured), on the judge. | the search's chain offer compares against the best measured-link row |
