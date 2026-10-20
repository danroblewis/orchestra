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
  has its own checkout (`~/.sdlab/pool/slot-<n>/` on node2; on the Mac under `~/.sdlab/pool/`, never the
  agents' checkout), moved to each item's commit before it runs. Code comes only from the Mac's
  repository, through the server (git bundles; no GitHub, nothing pushed to origin).

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

Before submitting, an agent commits its strategy and keeps its branch up to date: a job runs a commit,
never a working tree.

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

The standing job replaces the watchers (`sdlab-ladder watch` here and on node2); while both run they
duplicate work. Stop the watchers when the pool's workers are up (`touch ~/.sdlab/watch.paused` here).

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
