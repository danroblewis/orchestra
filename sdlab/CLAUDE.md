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
3. **Cases are mathematical probes, not a record of outcomes.** Each case tests one property and
   says which in `tests:`. Parametric cases (draws, sweeps) map where a method breaks. A failing
   draw is frozen into a fixed case so it stays tested.
4. **A failure is diagnosed before it is fixed.** Is it the method's fault or the data's limit?
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
11. **Strategies are files, not branches.** One package or file per strategy under
    `sdlab/discovery/strategies/`, exposing `identify(stocks, run, opts)` and runnable alone.
    Work happens in this checkout on branch `sdlab`; there are no new git branches or worktrees.
    A strategy is improved in place for a fix, or copied into a new package for a different idea.
12. **Agents own their files.** A strategy agent adds or edits only its own package, tests and doc.
    It does not edit shared modules (`sdlab/discovery/*.py`, `sdlab/ladder/`, `sdlab/skill.py`,
    `tests/bench/`, the server, static files) or another strategy; it reports the needed fix
    instead. An agent given a shared module owns only that module and edits others surgically.
    Commit only your own files (`git add <paths>` or `-p`, never `-A`). Never push.
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
    `nice -n 19 uv run sdlab-ladder watch --strategies everything --every 300 --jobs 4 --timeout 300`
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
