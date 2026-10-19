# Rules for research on SD Lab discovery

SD Lab's discovery engine reverse-engineers system dynamics models (stocks, flows, rates) from
measured stock levels. The research improves it by building strategies and testing them on the
ladder (`docs/LADDER.md`): tiny true models, each probing one mathematical property. These rules
keep the results trustworthy. Breaking one needs the user's approval, and the commit says so.

## Invariants

### Honest testing
1. **Discovery never sees the truth.** A strategy gets only what a page gets (`identify(stocks,
   run, opts)`: measured levels, announced eras, injections, units). It never reads the true
   model, the case file, the case id, the seed, or hidden stocks' levels. Nothing is tuned to one
   case or example.
2. **Simulations are fixed.** `sdlab/sdtruth.py`, the examples, their fingerprints, and what an
   existing ladder case means change only with the user's approval. Add a new case instead of
   changing one.
   Approved on 2026-10-18: adding features the engine lacks (measured input series, a smaller
   step `dt`, stock ceilings, delay and smoothing functions, and others the canonical and
   real-data sources need). A new feature must be additive: every existing case, example and
   fingerprint must give exactly the same numbers as before, with a test proving it.
3. **Cases are mathematical probes, not a record of outcomes.** Real-data cases (tag `real`)
   are the exception: they live on the ladder as additional information, separate from the formal
   functional tests. They are scored by held-out prediction and agreement with the published
   model, and never counted in the Tests pass rate. Each case tests one property and
   says which in `tests:`. Parametric cases (draws, sweeps) map where a method breaks. A failing
   draw is frozen into a fixed case so it stays tested.
4. **Hard failures become simple tests.** The minimal cases prove the methods work, but they
   are incomplete. When a model whose true structure is known (realistic, canonical, physics, or
   a real case's twin) fails, find why. Then write the smallest ladder case that shows that kind
   of failure (tag `distilled`; its `tests:` names the mechanism and the hard case it came from),
   and confirm it reproduces the same mistake. Fix the detector against the small case, then
   check that the fix carries back to the hard case.
4b. **A failure is diagnosed before it is fixed.** Is it the method's fault or the data's limit?
   That is decided by identifiability and the best achievable accuracy for that case and variant,
   not by guessing.
5. **Scoring changes are visible.** The scorer's hash re-scores stored results. A change that can
   turn a fail into a pass is reported to the user with before/after statuses, and a change to
   what counts as a pass (e.g. counting "equivalent" as a pass) needs the user's approval. A
   tolerance may widen only by a measured standard error, never to make a strategy pass.
6. **Comparisons are fair.** Strategies are compared on the same cases, variants and seeds, with
   paired comparisons and confidence intervals. Benches run single-threaded
   (`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1`).
   Results that weren't run are labelled "not run", never counted silently as fails or passes.
7. **Simpler models are preferred.** Every result reports its complexity against the truth's.
   Extra flows or pieces are a cost, not a free win.

### Honest reporting
8. **Every number told to the user comes from a command that can be rerun, on committed code.**
   Use the result store (`uv run sdlab-ladder status|show`, `sdlab.ladder.store`), the bench
   outputs, and git, not memory. Say which command produced it and when. Commit a strategy before
   quoting its numbers and give the commit, so the number can be reproduced.
9. **Report failures as plainly as successes.** This covers errors, timeouts, regressions, skipped
   steps, work in progress, and claims that turned out wrong. Correct a wrong claim in the next
   message to the user.
10. **Say "in progress" for what is in progress.** An agent that was started is not a result.

### How the work is organised
11. **Strategies are isolated, not a shared codebase** (the user, 2026-10-19). The strategies are
    a collection of independent options to choose from. A change to one must never change or break
    another. There is no stable interface or chaining pattern between strategies, so chains can't
    be trusted.
    - **Strategies are improved freely.** Agents refactor and modify a strategy in place to make
      it work better; the ladder keeps every version's history.
    - **No strategy imports another strategy.** A composite or derivative strategy (one built on
      lna, combined calling specialists, a `_v2`) contains its own copy of the implementation it
      builds on. Copy the other strategy's code into your package, and note where and at which
      commit it came from. Then changing the original never changes the copy.
      `tests/test_isolation.py` fails on any new cross-strategy import (by import or by
      `load("name")`). Its list of existing violations may only shrink (queue item 0c).
    - **The shared discovery library** (`sdlab/discovery/*.py`, outside `strategies/`) is a shared
      library. It may change only rarely, never its interface, and only with the user's approval.
      `tests/test_frozen.py` pins it. A strategy that needs different behaviour copies the module
      into its own package.
    - **The test harness** (`sdtruth.py`, `sdlab/ladder/`, `skill.py`) is not strategy code.
      Harness features go into harness modules, never into the discovery library.

    Work happens in this checkout on branch `sdlab`; there are no new git branches or worktrees.
12. **Agents own their files.** A strategy agent adds or edits only its own package, tests and doc.
    It does not edit the shared discovery library or another agent's strategy (invariant 11), the harness (`sdlab/ladder/`, `sdlab/skill.py`,
    `tests/bench/`, the server, static files) or another strategy; it reports the needed fix
    instead. An agent given a shared module owns only that module and edits others surgically.
    Commit only your own changes, never `git add -A`, and never push. Many agents share one
    checkout and one git index, so commit through a private index, which can't sweep up what
    others staged:
    ```sh
    IDX="$(git rev-parse --git-dir)/index.$RANDOM"
    GIT_INDEX_FILE="$IDX" git read-tree HEAD
    GIT_INDEX_FILE="$IDX" git add <your paths>          # or: git apply --cached <your hunks>.patch
    GIT_INDEX_FILE="$IDX" git commit -m "..."
    rm -f "$IDX"; git reset -q -- <your paths>          # sync the shared index for your paths
    ```
    Check `git show --stat HEAD` afterwards: it must list only your changes. Delete only your own
    index file (`rm -f "$IDX"`), never a glob of `.git/index.*`: other agents' indexes live there.
13. **Every strategy is documented.** `docs/research/<name>.md` gives its status, what it does,
    ladder and bench results, and a verdict, with a row in `docs/research/README.md`.
    `docs/research/tries.md` summarises all efforts. A new strategy also adds its entry to
    `sdlab/ladder/explanations.yaml` (plain language, shown on the ladder pages; a test checks it).
14. **Nothing is thrown away.** A slow strategy is parked (`sdlab/ladder/parked.yaml`, with a
    reason), not deleted. Parked strategies and earlier ideas are revisited on the ladder. A method
    held back by the judge or the old bench is not dismissed. When out of ideas, an ideation agent
    reads the research docs and every idea runs as a parallel experiment.
15. **The ladder stays current and fast.** Results are keyed by strategy, case and scorer hashes,
    so a change marks them stale. One supervised watcher re-runs stale results:
    `nice -n 19 uv run sdlab-ladder watch --strategies everything --every 300 --jobs 4 --timeout 300 --batch 2000`
    (every strategy, parked ones too; a run that errors or times out counts as not passing), logging to
    `~/.sdlab/ladder-watch.log`; check it with `pgrep -fl "sdlab-ladder watch"`. Agents run only
    their own strategy (`--strategies <name>`), never a full sync. When the watcher has a backlog,
    the board mixes versions: say so when quoting it. Leaderboard rates are over the cells a
    strategy has run, with its coverage shown. The public UI
    (`https://sdlab.dansproject.space/ladder`) must load in about a second. Restart the server after
    Python changes:
    `pkill -f "sdlab --port 8020"; nohup uv run --directory /Users/daniellewis/orchestra/sdlab sdlab --port 8020 >> ~/.sdlab/server.log 2>&1 &`.
    Check that the old process has gone (use `kill -9` if it hangs).
16. **Probing a real, live system needs the user's approval.**
