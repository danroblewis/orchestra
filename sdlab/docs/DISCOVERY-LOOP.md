# The discovery improvement loop

How to work on discovery: one change at a time, measured against models we know exactly, with every
attempt recorded in [DISCOVERY-EXPERIMENTS.md](DISCOVERY-EXPERIMENTS.md).

## The rule that does not bend

**The simulations are fixed.** Never change `sdlab/sdtruth.py`, the equations it uses in
`sdlab/runner.py` (`desired_rate`, `multiplier`), any `sdlab/examples/sd-*/` file (truth models,
schedules, wrappers), or the long-run tests of them (`tests/test_sd_examples.py`). Discovery is
working against them: a change that "improves" a score by changing what generates the data proves
nothing. Everything else is open: `sdlab/static/identify.js` (the matrix method),
`sdlab/static/discover.js` (the old search), the graders in `tests/bench/`, new features, new forms.

## What we measure

The ground-truth examples (`sdlab/examples/sd-*`) are system dynamics models. Their data is made by
stepping the model with SD Lab's own equations, with counting noise and changes nobody announces.
The example shows only the measured stocks; discovery has to find the rest.

- **parts**: parts of the true model recovered in the right form (each relationship between stocks
  with the right kind - move, link, hidden stock, echo - and each flow to or from outside).
- **skill@H**: the share of the true model's movement over H steps that the found model predicts.
  Both models start from the same states at ~150 moments across the run and are fed the same outside
  inflows (the truth's), so only their own dynamics differ. 100% = behaves as the truth; 0% = no better
  than assuming nothing changes; below 0 = worse than that (it runs off on its own). Two models that
  behave the same are equally good, whatever they look like.

The **headline is mean skill@20** over every example at both lengths (each clipped at -100% so one
runaway does not hide everything else), with parts and skill@100 next to it.

Each example is run at its default length (the first months) and its long length (years): more data
must not make discovery worse.

## The loop

1. **Run the evaluation** and keep its output:

   ```
   node tests/bench/evaluate.mjs --label "what I am trying"
   ```

   It runs every ground-truth example at both lengths (datasets are generated once and cached in
   `~/.cache/sdlab/bench`, rebuilt only if a simulation's code changes, which it must not), compares
   with the previous run, and saves the run under `~/.cache/sdlab/bench/runs`. `--examples a,b` and
   `--lengths default` make it quicker while exploring; always finish with a full run.
2. **Pick the worst thing**: the lowest skill, or a part that is never found. Look at what discovery
   returns for it next to the truth (`sdlab/examples/<id>/truth.model.json`):

   ```
   node -e 'const {identify}=require("./sdlab/static/identify.js"); ...'   # or a scratch script
   ```

   `identify(stocks, run, {trace: "<stock id>"})` prints how a stock's row was fitted, pass by pass.
3. **Form one hypothesis** about why, and check it directly before changing code: score the true
   structure, print a row's coefficients, look at the residual. Most early guesses here were wrong
   (see the experiment log).
4. **Change one thing.** Keep it explainable in a sentence; prefer a principle (conservation, units,
   uncertainty) over a threshold tuned to one example.
5. **Re-run the evaluation.** Read every row, not just the headline: a fix for one example often
   costs another.
6. **Record it** in DISCOVERY-EXPERIMENTS.md: what, why, the numbers before and after, kept or
   reverted. Record failures too; they are most of what we learn.
7. **Keep the tests green**: `node --test tests/*.mjs`, `uv run pytest -q`, `uv run ruff check sdlab tests`.
   When an example reaches a new level, lock it in (`tests/identify.test.mjs`).
8. When the overall numbers reach a new best, save a baseline: `--save best`, and compare later work
   with `--baseline best`.

## Useful commands

```
node tests/bench/evaluate.mjs                                  # everything, compared with the last run
node tests/bench/evaluate.mjs --baseline start                 # compared with the first baseline
node tests/bench/evaluate.mjs --examples sd-orders --lengths default,long
node tests/bench/evaluate.mjs --strict                         # exit 1 on a regression of 2 points
node tests/bench/evaluate.mjs --engine discover                # the old search, for comparison
node --test tests/bench/*.test.mjs                             # the long-run bench (slices, consistency)
uv run python tests/bench/datasets.py sd-saas --long           # path to a cached dataset
```

## Where things are

| | |
|---|---|
| The matrix method | `sdlab/static/identify.js` |
| The old search | `sdlab/static/discover.js` (see docs/DISCOVERY.md) |
| Grading | `tests/bench/grade.mjs` (`grade`, `sameBehaviour`) |
| Evaluation CLI | `tests/bench/evaluate.mjs` |
| Datasets | `tests/bench/datasets.py` (cache: `~/.cache/sdlab/bench`) |
| Ground truth | `sdlab/examples/sd-*/truth.model.json`, answer keys in `truth.json` |
| Experiment log | `docs/DISCOVERY-EXPERIMENTS.md` |
