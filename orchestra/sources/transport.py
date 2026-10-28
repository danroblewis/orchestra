"""One request to a Prometheus-API store, as a busy managed store needs it asked.

- Every request carries the source's auth (``auth.py``) and timeout, takes a token from the
  source's rate limit (``limits.RateLimit``) and is counted against the round's budget
  (``limits.Budget``), retries included.
- **429, 502, 503, 504** are waited out and asked again, at most ``RETRIES`` times: after the
  server's ``Retry-After`` (seconds or an HTTP date, believed up to ``MAX_WAIT``) plus a little
  jitter, and a 429 holds every reader of the source for that long; without one, after an
  exponential pause with jitter (``BACKOFF``·2ⁿ, between half and all of it), so many readers
  refused at once do not come back at once. A dropped connection is asked again the same way, and
  a timeout once. Never past the round's deadline: a wait that would end after it raises
  ``PastDeadline`` at once.
- **422, or a 4xx that says "too many"** is the store's size limit: ``TooBig``, never retried as
  it is (the caller asks for less). The limit it names (``over the limit of 2500 series``) is
  kept in ``series_limit`` so later reads are sized under it. A refusal for the **series** a read
  touches (``TooBig.by_series``) is helped by a shorter time range only when the series churn:
  callers halve it once and go on only while that sheds series (``time_helps``).
- Other 4xx and 5xx raise ``SourceError`` at once, named by the server and what it said (a load
  balancer's HTML page by its status only), never a credential."""

from __future__ import annotations

import email.utils
import http.client
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import PastDeadline, SourceError
from .auth import Auth
from .limits import Budget, RateLimit
from .spec import SourceSpec

RETRY = {429, 502, 503, 504}         # busy or rate-limited: wait and ask again
RETRIES = 4
BACKOFF = 1.0                        # seconds, doubled each attempt, without a Retry-After
MAX_WAIT = 30.0                      # the longest single wait a Retry-After is believed for
TOO_BIG = re.compile(r"(?i)too many|exceed|limit of|maximum number|max(imum)?[ _]?series|unique (time)?series")
LIMIT_OF = re.compile(r"(?i)limit of (\d+) series")


SERIES = re.compile(r"(?i)series")
COUNT = re.compile(r"(?i)(\d[\d,]*) (?:unique |time ?)?series")
CHURN_GAIN = 0.9             # a half of a refused read touching at least this share of its series: time does not help


class TooBig(SourceError):
    """The store refused a read for its size (a per-query series limit): narrow it, do not retry it."""

    @property
    def by_series(self) -> bool:
        """Refused for the series it touches (not its samples or points)."""
        return bool(SERIES.search(str(self)))

    @property
    def matched(self) -> int | None:
        """The series the store said the read touched, when it said (not the limit it named)."""
        nums = [int(x.replace(",", "")) for x in COUNT.findall(str(self))]
        limit = LIMIT_OF.search(str(self))
        out = [n for n in nums if not limit or n != int(limit[1])]
        return out[0] if out else None


def time_helps(e: TooBig, before: TooBig | None) -> bool:
    """Whether a read refused (``e``) may fit over a shorter time range: refused for its samples
    or points, yes; for its series, only while halving the range sheds series (they churn): the
    first refusal is halved once, and a half that still touches ``CHURN_GAIN`` of the series the
    whole did (or says no count) is not halved again, so a stable metric over the limit costs two
    refusals, not one per halving."""
    if not e.by_series or before is None:
        return True
    if e.matched is None or before.matched is None:
        return False
    return e.matched < CHURN_GAIN * before.matched

def retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header: a number of seconds or an HTTP date."""
    if not value:
        return None
    v = value.strip()
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(v).timestamp()
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, when - (time.time() if now is None else now))


def _origin(url: str) -> tuple:
    u = urllib.parse.urlsplit(url)
    return u.scheme.lower(), (u.hostname or "").lower(), u.port or {"http": 80, "https": 443}.get(u.scheme.lower())


class SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to the same scheme, host and port. urllib's default copies every
    header, the credentials included, to wherever a redirect points (another host, or https to
    http); this refuses instead, so they never leave the server they were meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if _origin(target) != _origin(req.full_url):
            s, h, p = _origin(target)
            raise urllib.error.HTTPError(req.full_url, code, f"redirected to {s}://{h}:{p}, another server; not followed, "
                                         "so the credentials are not sent there", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Transport:
    def __init__(self, spec: SourceSpec, limiter: RateLimit | None = None):
        self.spec = spec
        self.name = spec.name
        self.auth = Auth(spec.auth, spec.insecure)
        self.limiter = limiter or RateLimit(spec.rate, spec.burst)
        self.budget: Budget | None = None     # the round's, set by whoever runs one
        self.requests = 0
        self.points = 0
        self.retries = 0                      # requests asked again after a 429/5xx or a dropped connection
        self.throttled = 0                    # 429s the store answered
        self.narrowed = 0                     # reads split because the store refused their size
        self.series_limit: int | None = None  # the per-query series limit the store named, once it refused one
        self._sleep = time.sleep
        self._opener: urllib.request.OpenerDirector | None = None

    def _open(self, req: urllib.request.Request):
        if self._opener is None:
            self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.auth.ssl_context()),
                                                       SameOriginRedirects())
        return self._opener.open(req, timeout=self.spec.timeout)

    def _deadline(self, until: float | None) -> float | None:
        b = self.budget.until if self.budget else None
        return min(x for x in (until, b) if x is not None) if (until is not None or b is not None) else None

    def _in_time(self, until: float | None) -> None:
        u = self._deadline(until)
        if u is not None and time.monotonic() > u:
            raise PastDeadline(f"{self.spec.where()}: past the deadline")

    def _call(self, path: str, form: dict | None = None, *, post: bool = True, until: float | None = None) -> dict | list:
        url = self.spec.url + path
        body = None
        if form is not None and post:
            body = urllib.parse.urlencode(form, doseq=True).encode()
        elif form is not None:
            url += "?" + urllib.parse.urlencode(form, doseq=True)
        where = f"{self.spec.where()}{path}"
        timeouts = 0
        for attempt in range(RETRIES + 1):
            u = self._deadline(until)
            if u is not None and time.monotonic() > u:
                raise PastDeadline(f"{where}: past the deadline")
            if self.budget is not None:
                self.budget.spend(where)
            self.limiter.take(u, where)
            headers = {"Accept": "application/json", **self.auth.headers()}
            if body is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
            self.requests += 1
            try:
                with self._open(req) as r:
                    raw = r.read()
                break
            except urllib.error.HTTPError as e:
                self.throttled += e.code == 429
                if e.code in RETRY and attempt < RETRIES:
                    self._wait(e, attempt, where, u)
                    continue
                said = self._said(e)
                if e.code == 422 or (400 <= e.code < 500 and e.code not in (401, 403, 404, 429) and TOO_BIG.search(said)):
                    if m := LIMIT_OF.search(said):
                        self.series_limit = min(int(m[1]), self.series_limit or int(m[1]))
                    raise TooBig(f"{where}: {said}") from None
                raise SourceError(f"{where}: {said}") from None
            except (TimeoutError, ConnectionResetError, http.client.RemoteDisconnected, http.client.IncompleteRead) as e:
                timed_out = isinstance(e, TimeoutError)
                timeouts += timed_out
                if attempt < RETRIES and timeouts <= 1:
                    self._pause(attempt, where, u)
                    continue
                raise SourceError(f"{where}: " + (f"no answer within the source's timeout of {self.spec.timeout:g} s (set timeout "
                                  "on the [[sources]] entry, or narrow the read)" if timed_out else f"the connection dropped ({e})")) from None
            except OSError as e:
                reason = getattr(e, "reason", None)
                if isinstance(reason, (TimeoutError, ConnectionResetError)) and attempt < RETRIES and timeouts < 1:
                    timeouts += isinstance(reason, TimeoutError)
                    self._pause(attempt, where, u)
                    continue
                if isinstance(reason, TimeoutError):
                    raise SourceError(f"{where}: no answer within the source's timeout of {self.spec.timeout:g} s "
                                      "(set timeout on the [[sources]] entry, or narrow the read)") from None
                raise SourceError(f"{where}: {reason or e}") from None
            except ValueError:                  # the HTTP library refusing a header: its message would carry the value
                raise SourceError(f"{where}: invalid request header (a credential is malformed)") from None
        try:
            doc = json.loads(raw)
        except ValueError as e:
            raise SourceError(f"{where}: the answer is not JSON ({e})") from None
        if not isinstance(doc, dict) or doc.get("status") != "success":
            raise SourceError(f"{where}: {doc.get('error') if isinstance(doc, dict) else 'not a Prometheus answer'}")
        return doc.get("data")

    def _sleep_until(self, wait: float, why: str, where: str, until: float | None) -> None:
        if until is not None and time.monotonic() + wait > until:
            raise PastDeadline(f"{where}: {why}, and waiting {wait:.1f} s to ask again would pass the deadline")
        self.retries += 1
        if self.budget is not None:
            self.budget.retries += 1
        self._sleep(wait)

    def _pause(self, attempt: int, where: str, until: float | None, why: str = "no answer") -> None:
        """An exponential pause with jitter: between half and all of ``BACKOFF``·2ⁿ."""
        full = min(MAX_WAIT, BACKOFF * 2 ** attempt)
        self._sleep_until(full / 2 + random.uniform(0, full / 2), why, where, until)

    def _wait(self, e: urllib.error.HTTPError, attempt: int, where: str, until: float | None) -> None:
        """Wait out a 429 or 5xx: the server's Retry-After (capped) plus up to a fifth of it, a
        429's for every reader of the source; else an exponential pause with jitter."""
        told = retry_after(e.headers.get("Retry-After") if e.headers else None)
        try:
            e.read()                            # the body (HTML from a load balancer, often) is not needed
        except (OSError, AttributeError):
            pass
        if told is None:
            return self._pause(attempt, where, until, f"HTTP {e.code}")
        wait = min(MAX_WAIT, told)
        if e.code == 429:
            self.limiter.hold(wait)
        self._sleep_until(wait + random.uniform(0, min(1.0, 0.2 * wait)), f"HTTP {e.code}", where, until)

    @staticmethod
    def _said(e: urllib.error.HTTPError) -> str:
        if 300 <= e.code < 400:
            return f"HTTP {e.code}: {e.msg}"
        if e.code in (401, 403):
            return f"HTTP {e.code}: the server refused the credentials (check the token or certificate)"
        try:
            doc = json.loads(e.read())
            err = doc.get("error") if isinstance(doc, dict) else None
        except (ValueError, AttributeError, OSError):
            err = None                          # an HTML page from a proxy: named by its status only
        return f"HTTP {e.code}" + (f": {err}" if err else "")
