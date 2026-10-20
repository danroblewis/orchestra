#!/bin/sh
# Retired on 2026-10-20: the CPU pool replaces node2's watchers and this sync (docs/pool.md). node2 now runs
# a pool worker that posts its results to the server here, and its old checkout, bare repository and store
# are gone. The last working version is in git (`git log -- sdlab/scripts/sdlab-sync.sh`, before this
# change); docs/LADDER.md, "Two machines and backups", describes it as history.
echo "scripts/sdlab-sync.sh is retired (2026-10-20): the CPU pool replaces it (docs/pool.md)" >&2
exit 1
