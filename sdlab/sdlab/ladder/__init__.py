"""The ladder: tiny ground-truth models, simplest first, one new feature per rung, on which every
discovery strategy is tested in isolation for whether it recovers the true equations.

    cases/*.yaml   the cases (caseformat.py: the YAML format; cases.py: loading, variants, hashes)
    data.py        each case's data, made by the ground-truth engine and cached
    score.py       equation recovery (parts, tolerance, pass / equivalent / fail) and behaviour (skill@H)
    catalog.py     the strategies (every module in sdlab/discovery/strategies) and their hashes
    store.py       results in SQLite, with history and live progress
    runner.py      what is stale, and running it in parallel
    api.py         the read API (the server's /api/ladder endpoints)
    cli.py         sdlab-ladder run | sync | status | show | watch | check | new
    noise.py       the noises laid on the recorded levels (meas, gaps, weekly, lag, outliers, bias), opt-in per case

See docs/LADDER.md.
"""
