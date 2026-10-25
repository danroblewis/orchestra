"""Redis Streams backend. Needs ``redis`` (``orchestra[bus-redis]``).

The stream ``<name>`` holds the events; the key ``<name>:n`` counts them. A Lua script increments
the count and adds the event with the stream id ``<count>-0`` in one step, so ids are dense
integers in publish order however many processes publish at once, and an offset maps straight to
an id range."""

from __future__ import annotations

import json

from . import BusError

_APPEND = """
local n = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], n .. '-0', 'e', ARGV[1])
return n
"""


class RedisStreamsBus:
    name = "redis"

    def __init__(self, url: str, stream: str):
        try:
            import redis
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise BusError("the redis event bus needs the 'redis' package: install orchestra[bus-redis]") from e
        self._r = redis.Redis.from_url(url)
        self._key, self._count = stream, stream + ":n"
        self._append = self._r.register_script(_APPEND)

    def append(self, event: dict) -> None:
        self._append(keys=[self._key, self._count], args=[json.dumps(event)])

    def end(self) -> int:
        return int(self._r.get(self._count) or 0)

    def read(self, since: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        end = self.end()
        start = max(since, end - limit) if limit else end
        if start >= end:
            return [], end
        rows = self._r.xrange(self._key, f"{start + 1}-0", f"{end}-0")
        return [json.loads(fields[b"e"]) for _, fields in rows], end

    def close(self) -> None:
        self._r.close()
