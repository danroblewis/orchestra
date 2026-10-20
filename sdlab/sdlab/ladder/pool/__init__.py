"""The CPU pool (docs/pool.md): a job queue in the server, leased to workers on the Mac and node2, whose
results come back over HTTP into the result store.

The server side:

    auth.py      the shared token (~/.sdlab/pool.token) and the check every writing endpoint makes
    db.py        the pool's tables (jobs, items, results, workers) in the result store's SQLite file
    gitcode.py   the repository: refs, the checkout's dirty files, bundles from a bare mirror
    planner.py   a checkout of the server's own, moved to a job's commit, asked for the items' hashes
    jobs.py      submitting, planning, cancelling, the standing main-line job, job status
    leases.py    claims (priority, memory admission), heartbeats, expired leases
    accept.py    posted results: the acceptance rules and promotion to the main line's latest
    memory.py    an item's expected peak memory
    routes.py    the endpoints under /api/pool
    cli.py       `sdlab-ladder pool ...`: submit, status, results, cancel

The worker (`sdlab-ladder worker`, docs/pool.md "Workers"):

    worker.py    the supervisor: claims, heartbeats, memory promise, load yielding, shutdown, self-update
    slot.py      one slot: its checkout at the item's commit, its item process, the hard memory limit
    child.py     the item process (the checkout's own python running that commit's run_item)
    repo.py      the worker's object store (bundles from the server) and its checkouts and venvs
    outbox.py    results kept on disk until the server has answered them
    host.py      the machine's memory, load, and its processes' resident memory
    client.py    HTTP to the server, with the token
"""
