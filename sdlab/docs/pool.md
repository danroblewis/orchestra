# The CPU pool

CPU, not agents, is what limits the ladder (the user, 2026-10-20). So the machines' cores are one pool
of test runners fed by one job queue:

- **The Mac Studio** (10.198.1.131, 28 cores) runs the agents, the server, the result store (SQLite,
  `~/.cache/sdlab/ladder/results.sqlite`, the single source of truth) and the job queue, inside the
  server (`sdlab --port 8020 --host 0.0.0.0`). Half its CPU is pool slots (at most 14, `nice 19`), and
  its worker gives slots back when the machine's load is high, so the agents stay usable.
- **node2** (ubuntu@10.198.1.109, 24 cores, 62 GB) gives the pool all its CPU, but only as much memory
  as it has: 20 workers of `sd-k8s-small` (~10 GB each) once ran it out of memory and every run crashed.
  Workers therefore admit an item only when its expected peak memory fits (see *Memory*).
- **Workers** pull items, run them and post the results. They never write a database. Each worker slot
  has its own checkout (`~/.sdlab/pool/worker/slot-<n>/`, on the Mac too: never the agents' checkout),
  moved to each item's commit before it runs. Code comes only from the Mac's repository, through the
  server (git bundles; no GitHub, nothing pushed to origin). See *Workers* below.

The server side lives in `sdlab/ladder/pool/` (tables in the result store's file, endpoints under
`/api/pool`, the page `/ladder/pool`); the command line is `uv run sdlab-ladder pool ...`.

## Small tests stay local; sweeps go to the pool

An agent may run a small test itself on the Mac (`uv run sdlab-ladder run --strategies <its own>
--cases ...`) when it is **at most 40 items and at most 2 CPU-minutes** by `uv run sdlab-ladder cost
--strategies X --cases Y` (its "busy time"). Anything larger (a strategy on a whole tag, a sweep over
strategies or variants, every case) is submitted to the pool: `uv run sdlab-ladder pool submit` prints
the same estimate first and says when a job is small enough to run locally. The threshold comes from
`sdlab-ladder cost` on 2026-10-20: `--strategies matrix --cases 001,...,007` is 28 items, 18 s of busy
time (local); `--strategies lna` over every case is 1484 items, 58 CPU-minutes (the pool; its 62
realistic items alone are 30 minutes).

Since 2026-10-20 this is enforced and made the default path (`sdlab/ladder/pool/agent.py`):
`sdlab-ladder run` and `sync` plan first and refuse above the limit, printing the submit command (exit
code 3; `--local` runs it here anyway and appends it to `~/.sdlab/local-runs.log`). The agents' commands
are `uv run sdlab-ladder submit` (the run/sync selectors; `--stale` for sync's "only what is stale",
otherwise every cell again as `run`, sent as `fresh`) and `uv run sdlab-ladder job ID [--wait] [--json]`
(progress, each item as it finishes, then `run`'s summary line). `pool submit|status|results|cancel`
stay for the rest.

Before submitting, an agent commits its strategy and keeps its branch up to date: a job runs a commit,
never a working tree. Agents may work on feature branches (the user, 2026-10-20). `submit` defaults to
the checkout's branch, refuses while the job's code has uncommitted changes in the agent's own checkout
(the client checks its checkout, so a worktree on a feature branch is checked too; the server checks
its own), and refuses a branch that lacks the `sdlab` HEAD (`--behind-ok` for an older commit on
purpose). Results of a commit other than the `sdlab` HEAD stay in the job; they reach the main line only
when their hashes equal the HEAD's.

## Jobs

A job is a set of items, the cells strategies x cases x variants, run at one commit. Its states:

| state      | meaning |
|------------|---------|
| `planning` | the server is working out its items and their hashes at the job's commit (the planner) |
| `queued`   | items wait; none has been handed out yet |
| `running`  | some items are leased or done, some still wait |
| `done`     | every item is done, an error, or cancelled |
| `cancelled`| cancelled (`DELETE`): waiting items are dropped, leased ones are told to stop |
| `failed`   | planning failed (an unknown strategy, a case spec that matches nothing, a commit that cannot be checked out); `error` says why |

An item's states: `queued`, `leased` (a worker holds it), `done` (a result is stored), `reused` (a result
with exactly these hashes was already stored: not run again unless the job asked for `fresh`), `error`
(it could not be run: crashed twice, its hashes never matched, its lease was lost three times),
`cancelled`.

**Planning.** The server keeps a checkout of its own (`~/.sdlab/pool/planner/`), moves it to the job's
commit and asks that commit's own code for the hashes (`runner.select_strategies`,
`runner.select_cases`, `runner.plan(..., force=True)`): every item is promised the case hash, strategy
hash and score hash its commit gives. The working tree never enters a hash. Plans are cached per commit
and spec in `~/.sdlab/pool/plans/`.

**Priorities.** Each job has a priority (0..1000; agents' jobs 100 by default). Items are handed out by
job priority, then by job age, then slow items first within a job (the realistic and heavy cases, long
variants: the same order as `runner.execute`, so a job's tail is short).

**The standing main-line job** (priority 0, `kind: mainline`) is what the watcher does today: it keeps
the latest results of the `sdlab` branch's HEAD current. It is planned at HEAD (every active strategy,
parked and retired ones left out; every case but `tag:kubernetes`, plus `tag:heavy`: the two
`sd-k8s` cases node2's heavy watcher runs today, kept to their own concurrency by the admission rules
below) and holds the items that are stale against the store
(`store.staleness`: new, case/strategy/scorer changed, a re-score, a crashed worker). Because every
agent job outranks it, it runs only when the pool is otherwise idle. It is planned again when HEAD
moves, and every 10 minutes when it has nothing left, and only while some worker is live. A cell
whose last pool attempt at the same hashes ended in an error is not queued again until a hash changes
(no endless retries of a cell that always crashes).

The standing job replaces the watchers (`sdlab-ladder watch` here and on node2). Since 2026-10-20 nothing
starts a watcher (the daemon keeps the Mac's pool worker up instead, and node2's watchers are gone), and
the main line queues nothing while `~/.sdlab/watch.paused` exists: `rm ~/.sdlab/watch.paused` starts it
(within a minute, while a worker is live), `touch ~/.sdlab/watch.paused` stops it queuing (what is queued
still runs; `sdlab-ladder pool cancel JOB` drops it).

## Results, and the main line's latest

Every result a worker posts is stored in `pool_results` with its job, item, commit, machine, worker,
slot, peak RSS, and the full row (status, scores, found flows, times), and stays queryable by job
(`GET /api/pool/jobs/{id}/results`, `sdlab-ladder pool results JOB`).

A pool result becomes the main line's latest (a row in `results` with `latest = 1`, shown on the
leaderboard) **only if its case hash, strategy hash and score hash equal the main line's current hashes
for that cell** (the plan of the `sdlab` branch's HEAD) and the cell's latest result is stale against
them. A result from a feature branch or an older commit whose strategy differs from the main line's is
therefore stored and never shown as latest; one whose code is identical to the main line's is the
same test and counts. A promoted row records the worker's machine and the commit; `pool_results.promoted_id`
links the two. This keeps the store's existing guarantee: staleness is keyed by the hashes, whoever ran
the item. When HEAD moves, results not yet promoted are checked against the new HEAD's hashes.

## Memory

Every result posts the item's peak RSS (MB). The expected peak of an item is 1.2 x the largest peak
recorded for its case and strategy, else for its case under any strategy, else a conservative default
by tag (`heavy` 16000 MB, `realistic` 10000, `physics`/`particles`/`canonical`/`real` 3000, anything
else 1000). The server hands an item to a worker only if its expected peak plus a margin (1024 MB)
fits in the memory the worker says it can still promise (`free_mb`), and a `heavy` item only while the
worker has a heavy slot free (`heavy_free`; node2: 2 heavy slots). Workers also set a hard per-process
memory limit (the expected peak x 2, at least 4 GB, at most half the machine) so one item cannot take
the machine down.

A crashed item (the worker process died: `BrokenProcessPool`, killed by the OOM killer, the hard limit)
is retried once, only on a worker that can promise more memory than the one it crashed on had; a
second crash is recorded as an error result.

## The token

Every endpoint that writes, or hands out work or code, needs the shared secret in a header:

    X-Pool-Token: <the contents of ~/.sdlab/pool.token>

The server makes the file (32 random bytes, url-safe base64, mode 0600) on its first start; copy it to
each worker machine's `~/.sdlab/pool.token` (0600). A missing or wrong token gets 401. The public site
(`https://sdlab.dansproject.space`) proxies to this server, so this is what keeps strangers from
submitting jobs, taking work, posting results or downloading the code. The read-only endpoints (job
status and results, the workers' status, the page) need no token, like the rest of the ladder.

## Endpoints

All bodies are JSON. `T` marks the endpoints that need the token.

### Jobs

`POST /api/pool/jobs` T: submit a job.

```json
{"ref": "sdlab", "strategies": "lna,lna_v2", "cases": "tag:realistic", "exclude_cases": null,
 "variants": "counts-long", "priority": 100, "by": "agent-lna", "note": "lna on the realistic set",
 "check_tree": "all", "fresh": false, "timeout": 300}
```

- `ref`: a branch, tag or commit of the Mac's repository (default `sdlab`); the job records the commit
  it resolves to.
- `strategies`, `cases`, `exclude_cases`, `variants`: the `sdlab-ladder run` syntax (`all`,
  `everything`, `roster:NAME`; ids, `tag:`, `level:`, `machine:`), resolved by the commit's own code.
- `check_tree` (`all`, the default; `strategies`; `none`): when the commit is the checkout's HEAD, the
  job is refused (409) if the working tree has uncommitted changes in the code the job uses: the
  strategies' own packages (modified or untracked files) and, with `all`, the shared discovery code and
  the harness (`sdlab/discovery/*.py`, `sdlab/ladder/`, `sdlab/sdtruth*.py`, `sdlab/skill.py`; tracked
  files). Uncommitted code would not be what the job runs. `none` is recorded with the job.
- `fresh`: run every item even when a result with exactly its hashes is already stored (default: such
  items are `reused`). An item whose stored result has the same case and strategy hash but another score
  hash is re-scored from the stored flows, as the watcher does.
- `timeout`: seconds per item (a realistic case's own timeout still applies).

Answer (202): `{"job": {"id": 12, "state": "planning", "commit": "3f1c...", ...}}`. 400: a bad field;
404: an unknown ref; 409: a dirty tree (the answer lists the files).

`GET /api/pool/jobs?limit=50`: the newest jobs with their item counts by state.

`GET /api/pool/jobs/{id}`: one job: `{id, kind, by, note, priority, ref, commit, spec, state, created,
started, finished, error, counts {queued, leased, done, reused, error, cancelled}, statuses {pass, fail,
...}, total, per_hour, eta_seconds}`.

`GET /api/pool/jobs/{id}/results?full=0`: its results, one per item: `{item_id, case, variant, strategy,
status, seconds, wall_seconds, peak_rss_mb, machine, worker, slot, commit, promoted_id, at}`; `full=1`
adds `scores`, `found` and `error`. Reused items point at the stored result (`result_id`).

`DELETE /api/pool/jobs/{id}` T: cancel it. The standing job cannot be cancelled.

### Work

`POST /api/pool/claim` T: a worker asks for up to `slots` items.

```json
{"worker": "node2-pool", "machine": "node2", "slots": 3, "free_mb": 30500, "heavy_free": 2,
 "commits": ["3f1c..."]}
```

Answer: `{"lease_seconds": 120, "items": [{"item_id": 991, "lease_id": "b1e...", "lease_expires":
"2026-10-20T12:00:00.000Z", "job_id": 12, "commit": "3f1c...", "case": "305-...", "variant":
"counts-long", "strategy": "lna", "case_hash": "...", "strategy_hash": "...", "score_hash": "...",
"mode": "run", "prev": null, "timeout": 300, "heavy": false, "expected_peak_mb": 1200}]}`. `mode:
"rescore"` items carry `prev` (`found`, `seconds`, `code_commit`, `code_dirty` of the stored result
whose flows are scored again). An empty list means there is nothing the worker can take now (none
waits, or none fits its memory); it asks again after a few seconds. `commits` (optional) are the
commits the worker's slots already have: items at those commits are preferred, other things equal.

**Leases.** An item is leased to one worker at a time: nothing runs twice concurrently. A lease lasts
`lease_seconds` (120) and is renewed by heartbeats. A lease that expires puts its item back in the queue
(the worker is presumed dead); an item whose lease is lost three times becomes an error.

`POST /api/pool/heartbeat` T: every 30 seconds, from each worker; it registers the worker and renews its
leases.

```json
{"worker": "node2-pool", "machine": "node2", "slots": 20, "busy": 7, "cpus": 24, "load": 21.5,
 "mem_total_mb": 63400, "mem_free_mb": 30500, "heavy_slots": 2, "leases": ["b1e...", "..."]}
```

Answer: `{"renewed": [...], "lost": [...], "cancel": [...]}`: `lost` are leases this worker no longer
holds (expired and given to another, or the item is done): it should stop those items and not post
them; `cancel` are items of a cancelled job: stop them.

`POST /api/pool/release` T: a stopping worker gives leases back: `{"worker": "node2-pool", "leases":
["b1e...", ...]}` -> `{"released": [...]}`. The items wait again at once, and it does not count as a lost
lease; only the worker that holds a lease can release it.

`POST /api/pool/results` T: one finished item.

```json
{"worker": "node2-pool", "machine": "node2", "slot": 4, "item_id": 991, "lease_id": "b1e...",
 "commit": "3f1c...", "outcome": "result", "hashes": {"case_hash": "...", "strategy_hash": "...",
 "score_hash": "..."}, "peak_rss_mb": 1630, "free_mb": 29000, "row": { ...runner.run_item's row... }}
```

`outcome` is `result` (the item ran; its `row` holds `status` pass/equivalent/fail/error/timeout, the
scores, found flows and times) or `crashed` (the worker process died; `error` says how). `hashes` are
what the worker's checkout computed for the item (its own plan), and `row` carries the strategy hash
of the code it imported (provenance.py).

Acceptance rules, in order:

1. An unknown item: 404.
2. An item that already has a result: 200 `{"accepted": false, "duplicate": true, "result_id": n}`.
   Posts are idempotent: the same item posted twice is stored once.
3. A cancelled item: 200 `{"accepted": false, "cancelled": true}`.
4. A commit other than the job's, or any hash (in `hashes` or `row`) other than the item's promised
   ones: 409 `{"accepted": false, "rejected": "..."}`; the item goes back to the queue, and becomes an
   error after its second rejection. A wrong result is never stored.
5. `crashed`: the first crash puts the item back in the queue for a worker that can promise more
   memory than `free_mb`; the second is stored as an error result.
6. Otherwise the result is stored (200 `{"accepted": true, "result_id": n, "promoted_id": n|null}`),
   whether or not the poster's lease is still current (the first valid result wins; a later one is a
   duplicate), and promoted to the main line's latest by the rule above.

### Workers and code

`GET /api/pool/status`: what the page shows: the workers (live: a heartbeat in the last 90 seconds;
machine, slots, busy, load, memory), the queue by job, the main line (HEAD, stale items queued),
throughput (results per hour by machine, last hour), and totals. No token; nothing secret in it.

`GET /api/pool/workers`: the worker registry (every worker ever seen, with its last heartbeat).

`GET /api/pool/code/head` T: `{"branch": "sdlab", "commit": "..."}`, the branch the main line follows.

`GET /api/pool/code/bundle?want=<commit>&have=<commit>,<commit>` T: a git bundle (application/
octet-stream) holding `want` as `refs/pool/want`, without what the `have` commits already hold (a full
bundle when `have` is empty or unknown). A slot that lacks a job's commit runs:

    curl -fsS -H "X-Pool-Token: $TOKEN" "$SERVER/api/pool/code/bundle?want=$C&have=$(git rev-parse HEAD)" -o c.bundle
    git fetch -q c.bundle refs/pool/want && git checkout -q --detach "$C" && rm c.bundle
    git diff --quiet "$OLD" "$C" -- sdlab/uv.lock || uv sync -q    # when the lock changed

The bundles are made from a bare mirror the server keeps (`~/.sdlab/pool/mirror.git`), so the
repository's own refs are never touched.

## Workers

    uv run sdlab-ladder worker --server http://10.198.1.131:8020 --slots N [--home ~/.sdlab/pool/worker]
        [--max-mem-gb G] [--heavy-slots 2] [--yield-load L] [--nice 19] [--machine NAME] [--name NAME]

The code is `sdlab/ladder/pool/worker.py` (the supervisor), `slot.py` (a slot), `child.py` (the item
process), `repo.py` (bundles and checkouts), `outbox.py`, `host.py` (memory and load) and `client.py`.

**Its home** (`--home`, default `~/.sdlab/pool/worker`; never inside the agents' checkout):

| path | what |
|------|------|
| `repo.git` | a bare object store fed only by the server's bundles (each commit kept as `refs/pool/c/<sha>`) |
| `self/` | the supervisor's own checkout, at the main line's HEAD |
| `slot-<n>/` | slot n's checkout (`git clone --shared` of `repo.git`), with its own venv (`sdlab/.venv`) |
| `cache/slot-<n>/` | slot n's ladder cache (`SDLAB_LADDER_CACHE`): an empty store of its own; the parts named by hash (`data`, `draws`, `real`, `physics`, `particles`) are links to `--cache` (default `~/.cache/sdlab/ladder`, the machine's own) |
| `outbox/` | results not yet answered by the server (`refused/`: posts it refused for good, with its answer) |
| `logs/slot-<n>.log` | what the item processes printed |

**Running an item.** A slot whose checkout is at another commit fetches it (a bundle of what `repo.git`
lacks), checks it out (`checkout -f --detach`, `clean -fd`; ignored files such as the venv stay) and runs
`uv sync --all-extras` when `uv.lock` or `pyproject.toml` changed. It then runs the item in an item
process: the checkout's own python running a snippet that uses only what every commit's runner has
(`select_strategies`, `plan(force=True)`, `run_item`), so a job runs its commit's code, with the same
environment as today's runs (`OMP/OPENBLAS/MKL/VECLIB/NUMBA_NUM_THREADS=1`, JAX's `XLA_FLAGS`, `nice
19`). The process works out the item's hashes from its own plan and does not run an item whose promised
hashes differ (the server then rejects the post). A re-score is handed the stored flows (`prev`). The
process stays up for the next item of the same commit and is restarted after an item that left it over
3 GB, after a heavy item, and every 200 items. It exits when its supervisor is gone.

**Memory.** The worker claims only what fits: it promises the lesser of its budget (`--max-mem-gb`,
default 85% of the machine) less what its items hold or are expected to reach, and the OS's available
memory less the growth its items are still expected to make and a reserve (`--reserve-gb`, default
the larger of 2 GB and 5%). The server adds its own 1 GB margin per item, and `heavy` items need a free
heavy slot (`--heavy-slots`). Every item has a hard limit (its expected peak x 2, at least 4 GB, at most
half the machine): the slot samples its resident memory every second and kills it past the limit,
posting it `crashed` (retried once where there is more memory). Peak RSS is posted with every result:
on Linux the exact high-water mark (`/proc/self/clear_refs` reset before the item, `VmHWM` after), on
macOS the highest sample (or `ru_maxrss` for a fresh process).

**Time.** `run_item`'s own timeout covers discovery; scoring is unbounded, so the slot also stops an item
after twice its timeout plus 15 minutes and posts it as a timeout.

**Load.** With `--yield-load L` the worker takes fewer slots while the 1-minute load is above L (one
fewer per unit over); running items finish. This is what keeps the Mac usable for its agents.

**Leases.** A heartbeat every 30 s renews the leases of the running items; one the server calls lost or
cancelled is killed and not posted.

**Outbox.** Every result is written to `outbox/` before it is posted and deleted once the server has
answered; while the server is down they wait there and are resent every 15 s and at the next start.

**Shutdown.** SIGTERM, SIGINT or SIGHUP: no new items; running items finish (up to `--grace`, 600 s).
Past that, or on a second signal, they are killed and their leases released (`POST /api/pool/release`).

**Self-update.** Started from any checkout, the worker first moves to `self/` at the main line's HEAD and
restarts from there. Every 2 minutes it asks the server for HEAD; when its own code (`sdlab/ladder/pool/`,
`uv.lock`, `pyproject.toml`) differs there, it stops claiming, lets its items finish, and restarts from
the new commit. `--no-self-update` runs it from the checkout it was started in (the tests do).

**Starting them.** See "Deployment" below for the two that run. By hand: copy the token first
(`~/.sdlab/pool.token`, mode 0600), then `sdlab-ladder worker --server URL --slots N ...` from any checkout.

Stop one with `pkill -TERM -f "sdlab.ladder worker"` (the pattern matches both `sdlab-ladder worker` and,
once it runs from `self/`, `python -m sdlab.ladder worker`). Tests: `uv run pytest tests/test_pool_worker.py`; `SDLAB_POOL_E2E=1` adds the end-to-end test
(a test server on a temporary store, the real planner, a real worker with two slots: about 4 minutes).

## Deployment (2026-10-20)

**node2** (`ubuntu@10.198.1.109`, 24 cores, 62 GB, shared with other work of the user's): a systemd
`--user` service, `sdlab-pool-worker` (lingering is on, so it starts at boot without a login, and
`Restart=always` brings it back 30 s after a failure). `scripts/pool/install-node2.sh` installs or
re-installs it from here: the token (`~/.sdlab/pool.token`, 0600), `~/.sdlab/machine` (`node2`), a boot
checkout cloned from the server's bundle (`~/.sdlab/pool/boot`, no remote: no GitHub, no push), its venv,
and the unit (`scripts/pool/sdlab-pool-worker.service`). The worker then follows the main line's HEAD by
itself (`self/`). Settings: 23 slots (all cores but one, for the supervisor and the machine's other
work), `--max-mem-gb 50`, `--heavy-slots 2`, nice 19, and a cgroup ceiling for the whole service
(`MemoryHigh=53G`, `MemoryMax=55G`): past it the kernel kills an item, which is posted as crashed. Change
them with `SLOTS=.. MEMGB=.. HEAVY=.. sh scripts/pool/install-node2.sh`.

    ssh ubuntu@10.198.1.109 systemctl --user status sdlab-pool-worker     # or: journalctl --user -u sdlab-pool-worker
    ssh ubuntu@10.198.1.109 tail -f ~/.sdlab/pool-worker.log
    ssh ubuntu@10.198.1.109 systemctl --user stop sdlab-pool-worker       # items finish (600 s), then are released

**The Mac**: `scripts/sdlab-daemon.sh` starts it when it is not running (`pgrep -f "sdlab.ladder worker"`):
14 slots (half of 28 cores), `--min-slots 2 --yield-load 24` (one slot fewer per unit of 1-minute load
over 24), `--max-mem-gb 96 --heavy-slots 2`, nice 19, home `~/.sdlab/pool/worker` (beside the server's
`planner/` and `mirror.git`, never the agents' checkout), log `~/.sdlab/pool-worker.log`. `touch
~/.sdlab/pool-worker.paused` keeps it down; `pkill -TERM -f "sdlab.ladder worker"` stops it (the daemon
starts it again within a minute unless paused).

**What it replaced.** node2's two watchers, its checkout `~/sdlab`, bare repository `~/sdlab.git`, store
`~/.cache/sdlab` and `~/.sdlab` were removed (all 2275 of its results were already in the store here; a
copy of its store and logs is in `~/.sdlab/node2-retired/`). The Mac's `node2` git remote, the daemon's
sync and watcher, and `machines.yaml`'s split are gone; `scripts/sdlab-sync.sh` only says it is retired.

**Measured on 2026-10-20** (`sqlite3 ~/.cache/sdlab/ladder/results.sqlite "select machine, case_id,
strategy, peak_rss_mb from pool_results"`): peak RSS of an item is 0.2 to 0.45 GB on the small cases, up to
9.1 GB on a realistic case (sd-ci, kalman_lna, counts-long), about 7 GB on sd-k8s-small (kalman_lna), and
over 33 GB on sd-k8s-platform (kalman_lna, killed at its 32 GB hard limit on the first try): that one fits
only the Mac (an item's hard limit is at most half its machine: 31 GB on node2). The smoke job (job 4:
matrix and kalman_lna on cases 001 to 020, all variants, 160 items) took 2.5 minutes: node2 ran 108 items
(13.5 s of wall time each on average), the Mac 52 (5.4 s each).

**The main line** is paused while `~/.sdlab/watch.paused` exists (it was left in place for the boundary
workflow). To start it: `rm ~/.sdlab/watch.paused`; the server queues the stale cells of the `sdlab` HEAD
within a minute (`uv run sdlab-ladder pool status` shows a `main line @ <commit>` job).
