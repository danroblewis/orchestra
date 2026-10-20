#!/bin/sh
# A backup of the ladder's result store (~/.cache/sdlab/ladder/results.sqlite), without tokens: a
# consistent snapshot made with SQLite's online backup API while the watcher writes, compressed with
# zstd, kept under ~/.sdlab/backups/ (24 h hourly, 14 days daily, 8 weeks weekly; sdlab/ladder/backup.py).
# The daemon (scripts/sdlab-daemon.sh) runs it every BACKUP seconds (default 3600). By hand:
#   sh scripts/sdlab-backup.sh                       one backup now, then rotation
#   uv run sdlab-ladder restore [FILE] --to PATH     decompress one (default: the newest) and check its row counts
# To put a backup back as the live store: stop the daemon, the watcher and the server, then
#   uv run sdlab-ladder restore FILE --to ~/.cache/sdlab/ladder/results.sqlite --replace
cd "$(dirname "$0")/.." || exit 1
LOCK="$HOME/.sdlab/backup.lock"
mkdir -p "$HOME/.sdlab"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
    echo "$(date '+%F %T') backup: another backup is running; skipped"; exit 0
  fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
echo "$(date '+%F %T') $(nice -n 10 uv run -q sdlab-ladder backup 2>&1 | tail -n 1)"
