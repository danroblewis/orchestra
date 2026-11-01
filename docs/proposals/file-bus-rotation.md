# File-bus rotation

Status: proposal, not built (task C6 of `docs/roadmap/GOAL-2026-11-01-workflows.md`). Requested by
the Workflows plugin (`~/orchestra-workflows`, SPEC §2.6), which works without it: its history is
bounded by its item logs' retention. Moved here on 2026-11-01, because it specifies a change to
the core.

## The problem

The file bus has no rotation and grows without bound. Every reader that starts from offset 0
assumes the bus still holds everything.

## The change

*SPEC's bus section, replacing its sentence on the file bus:* "The file bus is a live segment,
`events.jsonl`, and sealed segments, `events.d/<base>.jsonl`, where `<base>` is the offset of the
segment's first event, zero-padded to twelve digits; `events.d/live.base` holds the live segment's
base. An offset is the number of events before a point in the whole stream, so a cursor stays valid
across rotations. When the live segment passes `[events] rotate_mb` it is sealed and a new one
begun; sealed segments older than `[events] keep_days`, or beyond `[events] keep_mb` in all, are
removed oldest first, never the live one. Appends and the rotation take an exclusive `flock` on
`events.lock`; reads take a shared one, so a reader sees a base with its segment. A file that
predates rotation is a live segment with base 0."

*A new method:* `EventBus.start() -> int`: "The offset of the first event the bus still holds: 0
until retention removes anything. `read(since)` with `since` below `start()` reads from `start()`;
a reader comparing the two knows it missed events, and how many." File: the oldest sealed
segment's base; Kafka: the partition's log start offset; Redis and RabbitMQ streams: what their
offset conversion gives the first entry still held, stated in each backend's docstring and checked
by a trimming test added to `tests/bus`.

*Settings and check:* `[events] rotate_mb` (unset: no rotation, today's behaviour), `keep_mb`,
`keep_days` (unset: keep all). Refused: a non-positive value, `keep_mb` below `rotate_mb`, any of
them with a server bus URL.

*Sealing, and writers without the lock:* `FileBus` opens the file for each append, so a writer
without the lock can reach a sealed segment only with a write already in flight at the rename.
Rotation renames the live segment under the exclusive lock, waits one second, counts its lines and
writes `events.d/<base>.lines`; readers trust that count. A sealed segment found longer than its
count (at the next rotation, or on start) is logged as a bus fault, and its extra lines are
re-appended to the live segment, where readers that already hold them skip them by id.

## The readers to change with it

Each reads from 0 and assumes the bus holds everything:

- `orchestra/host.py`, `Host._collect`: reads from 0, then rebuilds `orchestra_events_total` with
  `backfill(replace=True)` from what is held, so retention would erase its history. Persist the
  counts before `start()` as a base.
- `orchestra/cli.py`, `metrics backfill`: the same.
- `orchestra/web/app.py`, the `/api/events` websocket, and `orchestra/web/core_explore.py`,
  `Explorer._events`: they show what is held; say so.
- `orchestra/endpoint/server.py`, `start`: its idempotency ids come from `read(0, limit=SEEN_MAX)`,
  correct while `SEEN_MAX` events are held.
- A plugin's cursors (the agents' host, the Workflows recorder) stay valid, and must treat
  `start()` above a cursor as a gap.

## Acceptance

The bus conformance suite plus a rotation test; `orchestra_events_total` survives a restart after
retention.
