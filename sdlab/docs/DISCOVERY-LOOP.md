# Improving discovery: experiments

How to work on discovery: strategies tried one at a time, each in its own branch and worktree,
measured against models we know exactly, with every attempt recorded in
[DISCOVERY-EXPERIMENTS.md](DISCOVERY-EXPERIMENTS.md). The target is in
[DISCOVERY-GOAL.md](DISCOVERY-GOAL.md).

## The rule that does not bend

**The simulations are fixed.** Never change `sdlab/sdtruth.py`, the equations it uses in
`sdlab/runner.py` (`desired_rate`, `multiplier`, `effect_value`), any `sdlab/examples/sd-*` file, or
the fingerprints in `tests/simulations.sha256`. Discovery works against them: a change that
"improves" a score by changing what generates the data proves nothing. Discovery sees only what the
page would give it: the measured stocks, their levels, and announced eras.

## What we measure

The ground-truth examples (`sdlab/examples/sd-*`) are system dynamics models. Their data is made by
stepping the model with SD Lab's own equations, with counting noise and changes nobody announces.

- **skill@H**: the share of the true model's movement over H steps that the found model predicts.
  Both models start from the same states at ~150 moments and are fed the same outside inflows (the
  truth's), so only their own dynamics differ. 100% = behaves as the truth; 0% = no better than
  assuming nothing changes; below 0 = worse. Two models that behave the same are equally good,
  whatever they look like.
- **parts**: parts of the true model recovered in the right form (a diagnostic, not the target).

The headline is mean skill@20 over every example at both lengths (each clipped at -100%), with
skill@100 and the number of runs meeting the goal next to it.

## Why experiments, not one long refinement

A method refined change by change, each kept because the bench went up, becomes a pile of rules that
happen to work together; nobody knows which one does what, and the next change fights the last.
So each idea is an **experiment**: one hypothesis, tried in isolation, with a test that shows the
mechanism does what it claims, and a bench run that shows what it does to behaviour. Ideas are
combined only after each has been measured alone, and a combination is its own experiment.

## An experiment

1. **A branch and a worktree of its own**, from the current main line of discovery:

   ```
   git worktree add ../sdlab-exp-<name> -b exp/<name>
   ```

   (or an agent started with worktree isolation). Experiments in different worktrees run at the
   same time; they share the dataset cache and the saved baselines, and each run records its branch,
   so comparisons do not cross by accident.
2. **State the hypothesis** in a sentence, with the evidence for it: which examples, which rows,
   what the data shows (score the true structure, print a row, look at residuals).
3. **A strategy**: `sdlab/discovery/strategies/<name>.py`, with `identify(stocks, run, opts)`. It may
   reuse the building blocks (`changes`, `regression`, `matrix`, `flows`, `simulate`) and add new ones,
   but it does not change the baseline strategy `matrix`, so the comparison stays clean. A switch on
   an existing step (an `opts` flag) is an experiment too: an ablation.
4. **A mechanism test first**: `tests/test_strategy_<name>.py`, on the smallest synthetic model where
   the answer is exact (`tests/synth.py` hands a model to the ground-truth engine), showing the
   mechanism does what it claims, and that the baseline does not. If the mechanism cannot be shown
   working in isolation, the bench number is luck.
5. **The bench**, against the shared baseline:

   ```
   uv run python tests/bench/evaluate.py --strategy <name> --baseline python --label "<name>: what"
   ```

   Read every row, not just the headline: a fix for one example often costs another.
6. **Record it** in DISCOVERY-EXPERIMENTS.md: hypothesis, mechanism test, bench numbers against the
   baseline, verdict (adopt / reject / needs a combination), and why. Failures are most of what we
   learn.
7. **Adopting**: a winner is folded into the main line (into `matrix`, or as the new default
   strategy) in one change that names the experiment, the locked-in tests move with it, and the
   baseline is saved again (`--save python`, or a new name). Every experiment after that starts from
   the new main line.

## Waves

Experiments run in waves: several independent hypotheses at once, each in its own worktree, each
measured against the same baseline. At the end of a wave, compare them side by side, adopt the
winners one at a time (re-running the bench after each, since two winners can overlap), and plan the
next wave from what was learned.

## Tests

- `uv run pytest -q`: everything, including `tests/test_discovery.py` (recovery locked in on
  ground-truth data; known failures marked `xfail(strict=True)` with the reason, so a fix shows up).
- `uv run ruff check sdlab tests`, `node --test tests/*.mjs` (the page).
- When the main line reaches a new level on an example, lock it in with a test.

## Useful commands

```
uv run python tests/bench/evaluate.py                           # everything, compared with this branch's last run
uv run python tests/bench/evaluate.py --baseline python         # compared with the shared baseline
uv run python tests/bench/evaluate.py --examples sd-orders --lengths default
uv run python tests/bench/evaluate.py --strategy <name>         # a strategy in sdlab/discovery/strategies
uv run python tests/bench/evaluate.py --goal                    # exit 0 only when the goal is met
uv run python tests/bench/datasets.py sd-saas --long            # path to a cached dataset
```

`identify(stocks, run, {"trace": "<stock id>"})` prints how a stock's row was fitted, pass by pass.

## Where things are

| | |
|---|---|
| Discovery (the matrix method) | `sdlab/discovery/` (`identify.py`: candidates and the judge; `matrix.py`: the rows, eras and conservation; `flows.py`: structure off the matrix; `changes.py`: inflow changes; `regression.py`; `simulate.py`) |
| Strategies | `sdlab/discovery/strategies/` (`matrix`: the main line) |
| Synthetic ground truth | `tests/synth.py` |
| Grading | `tests/bench/grade.py` (`grade`, `same_behaviour`) |
| Evaluation CLI | `tests/bench/evaluate.py` |
| Datasets | `tests/bench/datasets.py` (cache: `~/.cache/sdlab/bench`) |
| Ground truth | `sdlab/examples/sd-*/truth.model.json`, answer keys in `truth.json` |
| Experiment log | `docs/DISCOVERY-EXPERIMENTS.md` |

The page's Discover button still runs the older search in the browser (`sdlab/static/discover.js`,
graded by `tests/bench/discovery.bench.test.mjs` and `grade.mjs`); it moves to `sdlab/discovery`
behind a server endpoint once the method is settled.
