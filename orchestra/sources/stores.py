"""What the Core page shows of each ``[[sources]]`` entry, read from files only, never from the store.

For each source: its name, type, URL (``redact``: without a password, though the spec refuses one
anyway), its auth form (``Auth.describe``: the kinds, where each credential comes from and whether
it is there, never a value nor a file's contents), ``match``, its series cap and request rate, the
store's shared bucket (``limits.RateLimit.peek``: today's requests against the daily cap, the
store's and the web server's share), the last read and the last error (the cached inference, the
last failed round, the read cache's last write, the request log), how many series definitions
Orchestra keeps of it (the cached inference), and the request log (``reqlog.py``): the last
``LAST`` requests made of the store and today's count, by who asked. A refused entry is listed with why."""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from . import reqlog
from .auth import Auth
from .cache import attempt, cached, inferred
from .limits import RateLimit, store_dir, store_key
from .spec import SourceSpec, for_project

LAST = 20                     # requests shown on a store's row


def redact(url: str) -> str:
    """A URL without its password, for display (as the Core page shows the metrics store's)."""
    if not url or "://" not in url:
        return url
    p = urllib.parse.urlsplit(url)
    netloc = p.hostname or ""
    if p.port:
        netloc += f":{p.port}"
    if p.username:
        netloc = f"{p.username}:•••@{netloc}"
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path, "", ""))


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def bucket(spec: SourceSpec) -> dict:
    """The store's shared bucket and the web server's share of it, as they are now."""
    d = store_dir(store_key(spec.url, spec.auth.headers))
    store = RateLimit(spec.rate, spec.burst, d / "rate", per_day=spec.max_requests_per_day)
    web = RateLimit(spec.rate * spec.web_share, max(1.0, spec.burst * spec.web_share), d / "web.rate",
                    per_day=max(1, int(spec.max_requests_per_day * spec.web_share)))
    return {"store": store.peek(), "web": web.peek(), "web_share": spec.web_share}


def row(spec: SourceSpec, state_dir: Path) -> dict:
    inf = cached(state_dir, spec.name)
    failed = attempt(state_dir, spec.name)
    reads = _mtime(Path(state_dir) / "sources" / f"{spec.name}.reads.json")
    log = reqlog.last(state_dir, spec.name, 200)
    page_ok = next((x for x in reversed(log) if not x.get("error")), None)
    page_err = next((x for x in reversed(log) if x.get("error") and not str(x["error"]).endswith("asked again")), None)
    ok_at = max((t for t in (reads, inf.at if inf and not inf.error else None, page_ok and page_ok.get("t")) if t), default=None)
    errors = [(failed.get("at"), failed.get("error"), "the last inference round")] if failed.get("error") else []
    if inf and inf.error:
        errors.append((inf.at, inf.error, "the cached inference"))
    if page_err:
        errors.append((page_err.get("t"), page_err.get("error"), "this page" if page_err.get("by") == "page" else f"a request ({page_err.get('by', '?')})"))
    last_error = max((e for e in errors if e[0]), key=lambda e: e[0], default=None)
    return {
        "name": spec.name, "type": spec.type, "url": redact(spec.url), "where": spec.where(), "prefix": spec.prefix,
        "auth": Auth(spec.auth, spec.insecure).describe(), "match": list(spec.match),
        "max_series": spec.max_series, "rate": spec.rate, "burst": spec.burst, "per_day": spec.max_requests_per_day,
        "bucket": bucket(spec),
        "last_ok": ok_at, "last_error": ({"at": last_error[0], "error": last_error[1], "from": last_error[2]} if last_error else None),
        "inferred": ({"definitions": len(inf.kept), "inferred": inferred(inf), "at": inf.at, "left_out": len(inf.left_out)}
                     if inf else None),
        "requests": {"last": log[-LAST:], "today": reqlog.today(state_dir, spec.name)},
    }


def status(project) -> dict:
    """Every ``[[sources]]`` entry's row, and the refused entries with why."""
    t0 = time.perf_counter()
    specs = for_project(project)
    rows = [row(s, Path(project.state_dir)) for s in specs.sources]
    return {"ok": True, "stores": rows, "refused": [{"name": k, "error": v} for k, v in specs.refused.items()],
            "read_ms": round((time.perf_counter() - t0) * 1000, 1)}
