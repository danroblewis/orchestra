"""The CPU pool's server side (docs/pool.md): a job queue in the server, leased to workers on the Mac and
node2, whose results come back over HTTP into the result store.

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
"""
