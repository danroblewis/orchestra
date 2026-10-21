#!/bin/sh
# One agent edits a strategy package at a time (the user, 2026-10-21; sdlab/CLAUDE.md rule 12).
#   sh scripts/strategy-lock.sh acquire STRATEGY OWNER   exit 0: yours; exit 1: held by another (prints who and since when)
#   sh scripts/strategy-lock.sh release STRATEGY OWNER   after your commit
#   sh scripts/strategy-lock.sh list
# A lock older than 3 hours is stale and may be taken over (its holder has most likely finished or died).
D="${SDLAB_LOCKS:-$HOME/.sdlab/locks}"; mkdir -p "$D"
cmd=$1; name=$2; owner=$3; L="$D/$name.lock"
case "$cmd" in
  acquire)
    [ -n "$name" ] && [ -n "$owner" ] || { echo "usage: acquire STRATEGY OWNER" >&2; exit 2; }
    if mkdir "$L" 2>/dev/null; then echo "$owner $(date +%s)" > "$L/owner"; echo "locked $name for $owner"; exit 0; fi
    read -r who since < "$L/owner" 2>/dev/null
    if [ "$who" = "$owner" ]; then echo "already yours: $name"; exit 0; fi
    age=$(( $(date +%s) - ${since:-0} ))
    if [ "$age" -gt 10800 ]; then echo "$owner $(date +%s)" > "$L/owner"; echo "took over stale lock on $name (held by $who for ${age}s)"; exit 0; fi
    echo "$name is locked by $who since $(( age / 60 )) min ago: edit something else, or report what you need" >&2; exit 1 ;;
  release)
    read -r who since < "$L/owner" 2>/dev/null
    if [ "$who" = "$owner" ]; then rm -rf "$L"; echo "released $name"; else echo "not yours ($name held by ${who:-nobody})" >&2; exit 1; fi ;;
  list)
    for f in "$D"/*.lock; do [ -e "$f" ] || continue; read -r who since < "$f/owner"; echo "$(basename "$f" .lock) $who $(( ($(date +%s) - since) / 60 )) min"; done ;;
  *) echo "usage: acquire|release|list" >&2; exit 2 ;;
esac
