#!/bin/sh
# One sync of the second machine (node2, sdlab/ladder/machines.yaml) with this one, without tokens:
#   1. code: when node2's checkout is not at this repository's `sdlab` commit, push the branch to the
#      bare repository there (git remote `node2`), reset node2's checkout to it and `uv sync` it;
#   2. watcher: start node2's watcher (`--cases machine:node2`) if it is not running;
#   3. results: export node2's results newer than the newest one imported here (`import --high-water`,
#      so a file lost on the way is sent again), copy the file back and import it (idempotent).
# The daemon (scripts/sdlab-daemon.sh) runs this every SYNC seconds (default 600); by hand:
#   sh scripts/sdlab-sync.sh            (log: ~/.sdlab/sync.log when run by the daemon)
# Uncommitted changes are never sent: node2 runs committed code only.
cd "$(dirname "$0")/.." || exit 1
NODE=${NODE:-node2}
HOST=${NODE2_SSH:-ubuntu@10.198.1.109}
RREPO=${NODE2_REPO:-sdlab}                 # node2's checkout of this repository, relative to its home
RUV="${NODE2_UV:-\$HOME/.local/bin/uv}"   # expanded on node2
LOCK="$HOME/.sdlab/sync.lock"
IN="$HOME/.sdlab/imports"
mkdir -p "$HOME/.sdlab" "$IN"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
    echo "$(date '+%F %T') sync: another sync is running (pid $(cat "$LOCK/pid")); skipped"; exit 0
  fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
r() { timeout 600 ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "$@"; }
say() { echo "$(date '+%F %T') sync: $*"; }
t0=$(date +%s)

# 1. code
here=$(git rev-parse sdlab) || exit 1
# node2's checkout is at `here` once ~/.sdlab/synced-head there says so (written after uv sync succeeds,
# so an update cut short is done again)
there=$(r "mkdir -p ~/.sdlab && touch ~/.sdlab/synced-head && echo x\$(cat ~/.sdlab/synced-head)" 2>/dev/null)
if [ -z "$there" ]; then say "cannot reach $HOST"; exit 1; fi
there=${there#x}
if [ "$here" != "$there" ]; then
  say "code: node2 at ${there:-?}, here ${here%"${here#????????????}"}: pushing"
  git push -q "$NODE" sdlab:sdlab || { say "push failed"; exit 1; }
  r "cd $RREPO && git fetch -q origin && git reset -q --hard origin/sdlab && cd sdlab && $RUV sync -q && echo $here > ~/.sdlab/synced-head" \
    || { say "updating node2's checkout failed"; exit 1; }
fi

# 2. node2's two watchers (each restarts itself when the ladder's code changes), split by memory: the heavy
#    case (sd-k8s-platform, ~15 GB per worker, up to 30 min a run) on 2 workers, the rest of node2's share on 20
start() {   # start NAME CASES JOBS TIMEOUT BATCH, if no watcher of those cases runs
  if ! r "pgrep -f '[b]in/sdlab-ladder watch .*--cases $2 ' >/dev/null"; then
    say "node2's $1 watcher is down: starting it"
    r "mkdir -p ~/.sdlab && cd $RREPO/sdlab && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
       nohup nice -n 10 $RUV run sdlab-ladder watch --strategies everything --cases $2 --every 300 --jobs $3 \
       --timeout $4 --batch $5 --quiet >> ~/.sdlab/watch-$1.log 2>&1 < /dev/null &"
  fi
}
start main "tag:realistic,tag:physics,tag:particles,tag:real,tag:canonical" "${NODE2_JOBS:-20}" 300 2000
start heavy "tag:heavy" "${NODE2_HEAVY_JOBS:-2}" 1800 200

# 3. results
since=$(uv run -q sdlab-ladder import --high-water "$NODE") || { say "reading the high-water mark failed"; exit 1; }
file=$(r "cd $RREPO/sdlab && $RUV run -q sdlab-ladder export --since-id $since" 2>/dev/null | tail -n 1)
case "$file" in
  *.jsonl.gz) ;;
  *) say "export on node2 failed"; exit 1 ;;
esac
local_file="$IN/$(basename "$file")"
timeout 600 scp -q -o BatchMode=yes "$HOST:$file" "$local_file" || { say "copying $file failed"; exit 1; }
out=$(uv run -q sdlab-ladder import "$local_file") || { say "import of $local_file failed"; exit 1; }
r "rm -f '$file'" >/dev/null 2>&1
find "$IN" -name '*.jsonl.gz' -mtime +14 -delete 2>/dev/null
say "$out ($(( $(date +%s) - t0 )) s)"
