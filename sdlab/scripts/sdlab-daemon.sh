#!/bin/sh
# Keeps SD Lab's ladder testing going with no agent (no tokens): the public server (which holds the CPU
# pool's job queue, docs/pool.md), this machine's pool worker (half its cores: 14 slots, nice 19, fewer
# while the agents load it), hourly backups of the store (scripts/sdlab-backup.sh; ~/.sdlab/backup.log),
# and the derived verdicts (long-run metrics, strict pass), refreshed every REFRESH seconds.
# Since 2026-10-20 the pool replaces the old watcher and node2's sync (scripts/sdlab-sync.sh, retired):
# the server's standing main-line job re-runs stale results, and node2 runs its own pool worker as a
# systemd --user service (docs/pool.md, "Deployment"). The main line queues nothing while
# ~/.sdlab/watch.paused exists; touch ~/.sdlab/pool-worker.paused to keep this machine's worker down.
#   start:  nohup sh scripts/sdlab-daemon.sh >> ~/.sdlab/daemon.log 2>&1 &
#   stop:   pkill -f sdlab-daemon.sh   (the server and worker keep running; stop them separately)
#   status: tail ~/.sdlab/daemon.log ~/.sdlab/pool-worker.log; uv run sdlab-ladder pool status; /ladder/pool
cd "$(dirname "$0")/.." || exit 1
REFRESH=${REFRESH:-3600}
BACKUP=${BACKUP:-3600}
SLOTS=${POOL_SLOTS:-14}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1
mkdir -p ~/.sdlab
last=0
backed=0
while true; do
  if ! lsof -nP -iTCP:8020 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "$(date '+%F %T') server down: starting it"
    nohup uv run --directory "$PWD" sdlab --port 8020 --host 0.0.0.0 >> ~/.sdlab/server.log 2>&1 &   # every interface: the pool's workers (docs/pool.md)
    sleep 20
  fi
  if [ ! -e ~/.sdlab/pool-worker.paused ] && ! pgrep -f "sdlab.ladder worker" >/dev/null; then
    echo "$(date '+%F %T') pool worker down: starting it ($SLOTS slots)"
    nohup uv run --directory "$PWD" sdlab-ladder worker --server http://127.0.0.1:8020 --slots "$SLOTS" --min-slots 2 \
      --max-mem-gb 96 --heavy-slots 2 --yield-load 24 --nice 19 --machine mac --home ~/.sdlab/pool/worker \
      >> ~/.sdlab/pool-worker.log 2>&1 < /dev/null &
  fi
  now=$(date +%s)
  if [ $((now - backed)) -ge "$BACKUP" ]; then
    backed=$now
    sh scripts/sdlab-backup.sh >> ~/.sdlab/backup.log 2>&1 &
  fi
  if [ $((now - last)) -ge "$REFRESH" ]; then
    echo "$(date '+%F %T') refreshing long-run metrics and strict verdicts"
    nice -n 19 uv run sdlab-ladder longrun >/dev/null 2>&1
    nice -n 19 uv run sdlab-ladder strict >/dev/null 2>&1
    echo "$(date '+%F %T') refreshed"
    last=$(date +%s)
  fi
  sleep 60
done
