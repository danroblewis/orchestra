#!/bin/sh
# Keeps SD Lab's ladder testing going with no agent (no tokens): the public server, the watcher that
# runs every missing or stale test (a strategy's results go stale when its directory's code changes),
# and the derived verdicts (long-run metrics, strict pass), refreshed every REFRESH seconds.
#   start:  nohup sh scripts/sdlab-daemon.sh >> ~/.sdlab/daemon.log 2>&1 &
#   stop:   pkill -f sdlab-daemon.sh   (the server and watcher keep running; stop them separately)
#   status: tail ~/.sdlab/daemon.log; uv run sdlab-ladder status; the runs panel on /ladder
cd "$(dirname "$0")/.." || exit 1
REFRESH=${REFRESH:-3600}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1
mkdir -p ~/.sdlab
last=0
while true; do
  if ! lsof -nP -iTCP:8020 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "$(date '+%F %T') server down: starting it"
    nohup uv run --directory "$PWD" sdlab --port 8020 >> ~/.sdlab/server.log 2>&1 &
  fi
  if ! ps aux | grep -v grep | grep -q "bin/sdlab-ladder watch"; then
    echo "$(date '+%F %T') watcher down: starting it"
    nohup nice -n 19 uv run --directory "$PWD" sdlab-ladder watch --strategies everything --every 300 \
      --jobs 4 --timeout 300 --batch 2000 --quiet >> ~/.sdlab/ladder-watch.log 2>&1 &
  fi
  now=$(date +%s)
  if [ $((now - last)) -ge "$REFRESH" ]; then
    echo "$(date '+%F %T') refreshing long-run metrics and strict verdicts"
    nice -n 19 uv run sdlab-ladder longrun >/dev/null 2>&1
    nice -n 19 uv run sdlab-ladder strict >/dev/null 2>&1
    echo "$(date '+%F %T') refreshed"
    last=$(date +%s)
  fi
  sleep 300
done
