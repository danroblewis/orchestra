#!/bin/sh
# Run the ladder's backlog with no AI agents (docs/WEEKEND.md). Thin wrapper around the daemon, the CPU
# pool and sdlab-ladder; nothing here changes code, cases or the scorer.
#
#   sh scripts/backlog.sh status              what is running, the queue, and how big the backlog is
#   sh scripts/backlog.sh start [--all-cores] start everything and queue the backlog (kubernetes first)
#   sh scripts/backlog.sh stop                stop queueing new work (running items finish)
#   sh scripts/backlog.sh refresh             recompute derived verdicts (long run, strict) for new results
#   sh scripts/backlog.sh node2 start|stop|status
#
# --all-cores: no agents are using the Mac, so its pool worker takes 26 of its 28 cores (default 14).
cd "$(dirname "$0")/.." || exit 1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1
NODE2=${NODE2:-ubuntu@10.198.1.109}
L=uv
say() { printf '%s\n' "$*"; }

daemon_up() { pgrep -f "[s]dlab-daemon.sh" >/dev/null; }
server_up() { curl -s -o /dev/null --max-time 10 http://127.0.0.1:8020/api/ladder/version; }

start_daemon() {
  slots=$1
  if daemon_up; then
    if [ -n "$slots" ]; then                       # restart it so the Mac worker gets the new slot count
      pkill -f "[s]dlab-daemon.sh"; pkill -TERM -f "[s]dlab.ladder worker"; sleep 5
    else return 0; fi
  fi
  rm -f ~/.sdlab/pool-worker.paused
  POOL_SLOTS=${slots:-14} nohup sh scripts/sdlab-daemon.sh >> ~/.sdlab/daemon.log 2>&1 &
  say "daemon started (server, Mac pool worker with ${slots:-14} slots, hourly backups, hourly refresh)"
}

case "$1" in
  status)
    daemon_up && say "daemon: running" || say "daemon: NOT running (sh scripts/backlog.sh start)"
    server_up && say "server: answering on :8020" || say "server: NOT answering (the daemon restarts it within a minute)"
    [ -e ~/.sdlab/watch.paused ] && say "main line: PAUSED (~/.sdlab/watch.paused exists; start removes it)" || say "main line: on"
    $L run sdlab-ladder pool status 2>/dev/null | head -20
    say ""; say "backlog (stale results of every active strategy; times from stored runs):"
    $L run sdlab-ladder cost --strategies all --stale 2>/dev/null | grep -E "^Cost|wall time|by set" | head -4
    ;;
  start)
    slots=""; [ "$2" = "--all-cores" ] && slots=26
    start_daemon "$slots"
    rm -f ~/.sdlab/watch.paused
    say "main line on: the server queues every stale result of the sdlab branch's HEAD (priority 0) within a minute"
    say "queueing the kubernetes ladder first (priority 300; already-current results are reused, not re-run):"
    $L run sdlab-ladder submit --strategies roster:kubernetes --cases tag:kubernetes --stale --priority 300 \
      --by coordinator --note "weekend backlog: kubernetes first" --check-tree none 2>&1 | tail -3
    say "follow it: sh scripts/backlog.sh status, or https://sdlab.dansproject.space/ladder/pool and /ladder?view=now"
    ;;
  stop)
    touch ~/.sdlab/watch.paused
    say "main line paused: nothing new is queued. Queued work stays; to drop it: uv run sdlab-ladder pool status, then"
    say "  uv run sdlab-ladder pool cancel JOB   (running items finish first)"
    ;;
  refresh)
    say "long-run metrics of new results ..."; nice -n 19 $L run sdlab-ladder longrun
    say "strict verdicts ..."; nice -n 19 $L run sdlab-ladder strict --set all
    ;;
  node2)
    case "$2" in
      start|stop|status) ssh -o ConnectTimeout=10 "$NODE2" "systemctl --user $2 sdlab-pool-worker --no-pager" ;;
      *) say "usage: sh scripts/backlog.sh node2 start|stop|status"; exit 2 ;;
    esac ;;
  *)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
