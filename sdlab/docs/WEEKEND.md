# Running SD Lab with no AI tokens

What is waiting for the weekend, and the Saturday-morning steps: docs/SATURDAY.md.

Everything here runs without an agent: the CPU pool re-runs the backlog of stale results while you are
away, and the pages show them as they land. Nothing below changes code, cases or the scorer.

## Start (one command)

```sh
cd ~/orchestra/sdlab
sh scripts/backlog.sh start --all-cores
```

This:
1. starts (or keeps) the daemon: the server, the Mac's pool worker, hourly backups, hourly derived verdicts;
2. with `--all-cores`, gives the Mac's worker 26 of its 28 cores (the default 14 leaves room for agents);
3. turns the **main line** on (removes `~/.sdlab/watch.paused`): the server queues every stale result of the
   `sdlab` branch's latest commit, at the lowest priority, and keeps doing so as long as it runs;
4. queues the **kubernetes ladder first** (priority 300), so its results are current soonest.

node2's worker is a service that runs on its own; check it with `sh scripts/backlog.sh node2 status`.

## Check

```sh
sh scripts/backlog.sh status
```

prints whether the daemon and server are up, whether the main line is on, the pool's workers and queue, and
the size of the backlog. In the browser:

| page | what |
|---|---|
| https://sdlab.dansproject.space/ladder/pool | workers, slots, the queue by job, throughput |
| https://sdlab.dansproject.space/ladder?view=now | the newest results live, the run-time chart (click a bar), previous / next |
| https://sdlab.dansproject.space/ladder?view=cases&set=kubernetes | each case coloured by how many strategies pass; click a square for true / found / differences |
| https://sdlab.dansproject.space/ladder/leaderboard | strategies ranked per set |

## How long

The backlog on 2026-10-21 was about 49,700 results (`sdlab-ladder cost --strategies all --stale`), about
93 CPU-hours from stored run times: Tests 48 h, realistic 28 h, physics 9 h, noisy 5 h, canonical 3 h, real
data 0.5 h (single-worker hours). The pool has 37 slots (node2 23, Mac 14) or 49 with `--all-cores`, so
expect roughly **3 to 6 hours** of wall time; the realistic cases are the slow tail. Kubernetes 300-317 alone
is about 2,900 results and 46 CPU-hours (about an hour on the pool).

## Stop

```sh
sh scripts/backlog.sh stop          # nothing new is queued; work already queued keeps running
uv run sdlab-ladder pool status     # to drop queued work: uv run sdlab-ladder pool cancel JOB
```

To give the Mac back to agents: `sh scripts/backlog.sh start` (no `--all-cores`) restores 14 slots.

## Refresh the derived verdicts

The daemon does this hourly. By hand, after a big batch has landed:

```sh
sh scripts/backlog.sh refresh       # long-run metrics, then strict pass, for new results
```

## Reading the results without an agent

| command | what it tells you |
|---|---|
| `uv run sdlab-ladder status --strategies roster:kubernetes` | the strategy x case matrix and what is stale |
| `uv run sdlab-ladder diff 306,307,308 --summary --strategies roster:kubernetes` | the most common mistakes across rungs: the broad causes to fix next |
| `uv run sdlab-ladder diff 308 --strategy milp --variant counts-short` | one result as a git diff of the truth (+ added, - removed, ~ values wrong) |
| `uv run sdlab-ladder diff CASE --strategy S --variant V --between REF_A REF_B` | what changed in a result between two commits |
| `uv run sdlab-ladder show CASE --strategy S --variant V` | true vs found, part by part, with the numbers |
| `uv run sdlab-ladder analyse CASE --variant V` | whether the data can deliver a pass at all (data-limited, unidentifiable) |
| `uv run sdlab-ladder ident CASE --variant none-short` | Z3: is the structure identifiable from noise-free data, and the rivals if not |
| `uv run sdlab-ladder evidence --strategies S --cases C` | push test, likelihood, bound and no-truth checks beside the pass |
| `uv run sdlab-ladder job ID --wait` | one pool job's results as they finish |

Where the research stands, for picking up later: `docs/research/kubernetes-ladder.md` (the rungs),
`docs/research/k8s-306.md` .. `k8s-309.md` (each rung's fixes), `docs/research/fixes/` and
`docs/research/fix-ledger.md` (every fix by type, to port to the other strategies), `docs/research/journal.md`.

## When something goes wrong

| symptom | what to do |
|---|---|
| `status` says the daemon is not running | `sh scripts/backlog.sh start` |
| the pages do not load, the server does not answer | wait a minute (the daemon restarts it). If it is running but stuck: `curl -s -H "X-Pool-Token: $(cat ~/.sdlab/pool.token)" localhost:8020/api/pool/debug/threads > ~/hang.json`, then `pkill -9 -f "sdlab --port 8020"` (the daemon starts it again; queued work is kept in the store) |
| a worker is not live in `pool status` | Mac: `rm -f ~/.sdlab/pool-worker.paused` (the daemon starts it); node2: `sh scripts/backlog.sh node2 start`, logs `ssh ubuntu@10.198.1.109 journalctl --user -u sdlab-pool-worker -n 50` |
| items keep timing out | every item gets at least 7200 s (2 h) since 2026-10-24; a timeout under a shorter limit than today's runs again by itself |
| node2 runs out of memory | its service is capped (47 GB soft, 49 GB hard); an item is killed and retried once on a machine with more room |
| the disk fills | the store is `~/.cache/sdlab/ladder/results.sqlite`; backups are `~/.sdlab/backups/` (hourly, about 85 MB each): delete old backups first |
| you want the store back as it was | stop the daemon and server first (`pkill -f sdlab-daemon.sh; pkill -f "sdlab --port 8020"`), then `uv run sdlab-ladder restore` (unpacks the newest backup in `~/.sdlab/backups/` to a file and checks its row counts) and `uv run sdlab-ladder restore --replace` to put it in place of the store; then `sh scripts/backlog.sh start` |

Logs: `~/.sdlab/daemon.log`, `~/.sdlab/server.log`, `~/.sdlab/pool-worker.log` (Mac), and on node2
`journalctl --user -u sdlab-pool-worker`; each item's output in `~/.sdlab/pool/worker/logs/` on its machine.

## Notes

- The pool runs **committed** code only. Anything an agent left uncommitted in the checkout is ignored,
  so a half-finished agent edit cannot break the weekend's runs.
- Nothing needs `git` over the weekend; results go to the store (the source of truth), backed up hourly.
- The noisy (measurement-error) variants are part of the backlog: they re-run, but most strategies still
  fail them; fixing them is research for when agents are back (see `docs/research/k8s-306.md`).
