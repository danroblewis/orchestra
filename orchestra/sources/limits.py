"""How hard Orchestra may lean on another company's store: a request rate, a daily cap and a
budget per round.

- **Rate** (``RateLimit``): a token bucket per **store**, ``rate`` requests a second with bursts
  of ``burst``, shared by every thread and, through a small file under Orchestra's home
  (``<home>/stores/<store key>/``, ``store_dir``), by every process on the machine that reads the
  store: the host and the web server, every project, every ``[[sources]]`` entry and trial
  reader pointing at it. The store is its base URL and the headers that name a tenant
  (``store_key``), never a credential. A 429's ``Retry-After`` holds the whole bucket for that long
  (``hold``), so the other readers wait it out too rather than spending the tenant's quota on
  refusals.
- **Daily cap** (``per_day``): the most requests the bucket gives out in one UTC day, counted in
  the same file; past it, ``DailyCap`` (a ``SourceError``) says so and when reads resume.
- **Share** (``parent``): a bucket of its own, at a fraction of the store's rate and cap, taken
  from before the store's: the web server's reads come from one, so they can never take more than
  that share of the store from discovery and inference.
- **Budget** (``Budget``): the most requests one round may make (an inference, or one
  discovery's reads), retries included, and the time it must be done by. Past either, the next
  request raises ``OverBudget`` (a ``PastDeadline``): the round keeps what it read and says what it
  did not.

Neither ever waits past the round's deadline: a wait that would end after it raises at once."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import PastDeadline, SourceError


class OverBudget(PastDeadline):
    """A round made as many requests as it may (``Budget``)."""


class DailyCap(SourceError):
    """The store's daily request cap is reached: no request until the next UTC day."""


def store_key(url: str, headers: list[dict] | None = None) -> str:
    """Which store a URL reads: its scheme, host, port and path, and the literal headers (a
    tenant's ``X-Scope-OrgID``; never a credential, which is never written inline), hashed."""
    u = urlsplit(url)
    port = u.port or {"http": 80, "https": 443}.get(u.scheme.lower())
    tenant = sorted((str(h.get("name", "")).lower(), str(h["value"])) for h in headers or [] if isinstance(h, dict) and "value" in h)
    body = json.dumps([u.scheme.lower(), (u.hostname or "").lower(), port, u.path.rstrip("/"), tenant])
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def store_dir(key: str) -> Path:
    """Where every process on this machine keeps a store's shared bucket and daily count."""
    from ..config import home
    return home() / "stores" / key


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


class RateLimit:
    def __init__(self, rate: float, burst: float, path: Path | None = None, *, per_day: int | None = None,
                 parent: RateLimit | None = None, what: str = "the store", sleep=time.sleep, clock=time.time):
        self.rate, self.burst = max(0.01, float(rate)), max(1.0, float(burst))
        self.path = Path(path) if path else None
        self.per_day = int(per_day) if per_day else None
        self.parent, self.what = parent, what
        self._mem = {"tokens": self.burst, "t": clock(), "hold": 0.0, "day": _day(clock()), "count": 0}
        self._lock = threading.Lock()
        self._sleep, self._clock = sleep, clock
        self.waited = 0.0                        # seconds this process waited for the bucket

    def _state(self, fh) -> dict:
        try:
            fh.seek(0)
            d = json.loads(fh.read() or "{}")
            return {"tokens": float(d["tokens"]), "t": float(d["t"]), "hold": float(d.get("hold", 0.0)),
                    "day": str(d.get("day") or _day(self._clock())), "count": int(d.get("count") or 0)}
        except (ValueError, KeyError, TypeError):
            return {"tokens": self.burst, "t": self._clock(), "hold": 0.0, "day": _day(self._clock()), "count": 0}

    def _save(self, fh, st: dict) -> None:
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(st))
        fh.flush()

    def _with_state(self, fn):
        """``fn(state) -> result`` under the bucket's locks; the state is written back."""
        with self._lock:
            if self.path is None:
                return fn(self._mem)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, "r+") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    st = self._state(fh)
                    out = fn(st)
                    self._save(fh, st)
                    return out
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _try(self, st: dict) -> float:
        """Take a token: 0 when taken, else how long to wait for one; -1 when the day's cap is spent."""
        now = self._clock()
        if st.get("day") != _day(now):
            st["day"], st["count"] = _day(now), 0
        if self.per_day is not None and st.get("count", 0) >= self.per_day:
            return -1.0
        st["tokens"] = min(self.burst, st["tokens"] + max(0.0, now - st["t"]) * self.rate)
        st["t"] = now
        if now < st["hold"]:
            return st["hold"] - now
        if st["tokens"] >= 1.0 - 1e-6:
            st["tokens"] = max(0.0, st["tokens"] - 1.0)
            st["count"] = st.get("count", 0) + 1
            return 0.0
        return max(0.001, (1.0 - st["tokens"]) / self.rate)

    def take(self, until: float | None = None, where: str = "") -> None:
        """Wait for a token, from this bucket and then its parent's; ``PastDeadline`` when the
        wait would end after ``until`` (``time.monotonic()``), ``DailyCap`` when the day's cap
        is spent."""
        while True:
            wait = self._with_state(self._try)
            if wait < 0:
                raise DailyCap(f"{where}: {self.what} made its {self.per_day} requests today (max_requests_per_day on the "
                               "[[sources]] entry, shared by every reader of this store on this machine); no more are made "
                               f"until 00:00 UTC. Narrow what is read (match, max_series, fewer [[series]]) or read less often "
                               "(discovery every, infer_every)")
            if wait == 0:
                break
            if until is not None and time.monotonic() + wait > until:
                raise PastDeadline(f"{where}: past the deadline (waiting {wait:.1f} s for the source's request rate)")
            self.waited += wait
            self._sleep(min(wait, 5.0))
        if self.parent is not None:
            self.parent.take(until, where)

    def hold(self, seconds: float) -> None:
        """No request from any reader for ``seconds``: the server asked for that (Retry-After)."""
        def fn(st):
            st["hold"] = max(st["hold"], self._clock() + seconds)
        self._with_state(fn)
        if self.parent is not None:
            self.parent.hold(seconds)

    def today(self) -> int:
        """Requests given out today (UTC) by this bucket, every process counted."""
        def fn(st):
            return st.get("count", 0) if st.get("day") == _day(self._clock()) else 0
        return self._with_state(fn)


def for_store(spec, share: float | None = None) -> RateLimit:
    """The shared bucket of the store ``spec`` reads (``store_key``), with its daily cap; with
    ``share``, a bucket of that fraction of its rate and cap, drawn from before the store's (the
    web server's)."""
    key = store_key(spec.url, getattr(spec.auth, "headers", None))
    d = store_dir(key)
    per_day = getattr(spec, "max_requests_per_day", None)
    store = RateLimit(spec.rate, spec.burst, d / "rate", per_day=per_day, what=f"the store at {spec.where()}")
    if not share:
        return store
    return RateLimit(spec.rate * share, max(1.0, spec.burst * share), d / "web.rate",
                     per_day=max(1, int(per_day * share)) if per_day else None, parent=store,
                     what=f"the web server's share ({share:.0%}) of the store at {spec.where()}")


class Budget:
    def __init__(self, requests: int | None = None, until: float | None = None, what: str = "this round"):
        self.requests, self.until, self.what = requests, until, what
        self.used = 0
        self.retries = 0
        self._lock = threading.Lock()

    def spend(self, where: str = "") -> None:
        with self._lock:
            if self.requests is not None and self.used >= self.requests:
                raise OverBudget(f"{where}: {self.what} made its {self.requests} requests (its budget); the rest is not read")
            if self.until is not None and time.monotonic() > self.until:
                raise OverBudget(f"{where}: past the deadline of {self.what}")
            self.used += 1

    def left(self) -> float | None:
        return None if self.until is None else self.until - time.monotonic()
