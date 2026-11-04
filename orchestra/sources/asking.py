"""The Core page's reads of a source: an instant or a range query, label names and label values,
each bounded as ``console.py`` says, and logged.

Each read is made by a ``PrometheusSource`` of its own, drawing on the web server's share of the
store's rate and daily cap (``limits.for_store`` at ``web_share``), so the page can never take more
of the store than any of the web server's reads, with a request timeout of at most ``TIMEOUT_S`` and
the whole read done within ``DEADLINE_S``. The transport carries the source's auth and scopes every
request within its ``match`` (``prometheus.py``) on top of the conjunction made here.

Every request this makes, and every refusal, is appended to ``<state>/sources/<name>.asked.jsonl``
with ``reader`` (the page), beside what the source's other reads keep under ``<state>/sources/``
(the inference, the read cache, the history): what was asked, of what window, with what limit, how
many requests it took, and how it ended. ``asked`` reads it back."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from . import PastDeadline, SourceError
from .console import (
    Refused,
    conjoined,
    limit,
    match_matchers,
    matcher_text,
    resets,
    selectors,
    step,
    window,
)
from .limits import DailyCap, for_store
from .prometheus import PrometheusSource
from .spec import SourceSpec

TIMEOUT_S = 6.0               # one request, at most (the source's own timeout when shorter)
DEADLINE_S = 7.0              # one read from the page, all its requests told
LOG_MAX = 1_000_000           # bytes of the asked log before it is rotated
READER = "core page"


def source_for(spec: SourceSpec) -> PrometheusSource:
    """A reader of the source at the web server's share of the store, with the page's timeout."""
    quick = replace(spec, timeout=min(spec.timeout, TIMEOUT_S))
    return PrometheusSource(quick, for_store(spec, spec.web_share))


def log_path(state_dir: Path, name: str) -> Path:
    return Path(state_dir) / "sources" / f"{name}.asked.jsonl"


def note(state_dir: Path, name: str, entry: dict) -> None:
    p = log_path(state_dir, name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > LOG_MAX:
            p.replace(p.with_suffix(".jsonl.1"))
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), **entry}, ensure_ascii=False) + "\n")
    except OSError:
        pass                                    # the log never stops a read


def asked(state_dir: Path, name: str, lines: int = 200) -> list[dict]:
    """The last ``lines`` entries of the asked log, oldest first."""
    try:
        with log_path(state_dir, name).open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 600 * lines))
            raw = f.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _why(e: Exception) -> str:
    if isinstance(e, DailyCap):
        return f"{e}; {resets()}"
    if isinstance(e, PastDeadline):
        return f"{e} (the page waits at most {DEADLINE_S:g} s for a read)"
    return str(e)


def _run(state_dir: Path, spec: SourceSpec, what: str, entry: dict, fn) -> dict:
    """``fn(src, until)`` -> dict, its failure as ``{"ok": False, "error"}``, logged either way."""
    src = source_for(spec)
    until = time.monotonic() + DEADLINE_S
    began = time.monotonic()
    try:
        out = {"ok": True, **fn(src, until)}
    except Refused as e:
        out = {"ok": False, "refused": True, "error": str(e)}
    except SourceError as e:
        out = {"ok": False, "error": _why(e), **({"cap": True} if isinstance(e, DailyCap) else {})}
    out["requests"] = src.requests
    note(state_dir, spec.name, {"reader": READER, "what": what, **entry, "requests": src.requests, "ok": out["ok"],
                                "seconds": round(time.monotonic() - began, 3),
                                **({"error": out["error"]} if not out["ok"] else {"results": out.get("matched", len(out.get("values") or []))})})
    return out


def _check_size(src: PrometheusSource, q: str, start: float, end: float, n: int, until: float) -> None:
    """Each selector of ``q`` counted over the window with a bounded listing (``limit`` + 1):
    ``Refused`` when one selects more than ``n`` series."""
    for sel in dict.fromkeys(selectors(q)):
        if time.monotonic() > until:
            raise PastDeadline("past the page's deadline while counting the selectors' series")
        got = src.series([sel], start, end, limit=n + 1, narrow=False)
        if len(got) > n:
            raise Refused(f"{sel} selects more than {n} series in the window: narrow it (a label matcher more), "
                          f"or raise the limit (at most the source's max_series, {src.spec.max_series})")


def query(state_dir: Path, spec: SourceSpec, expr: str, *, instant: bool = False, minutes: float | None = None,
          limit_n: int | None = None, now: float | None = None) -> dict:
    """``expr`` within the source's match, over the bounded window (a range query) or at its end
    (an instant one), at most ``limit`` series; refused with the reason when the guard says so."""
    n = limit(limit_n, spec)
    start, end = window(minutes, now)
    end -= spec.settle
    start -= spec.settle
    entry = {"query": expr, "mode": "instant" if instant else "range", "start": round(start, 3), "end": round(end, 3), "limit": n}

    def go(src: PrometheusSource, until: float) -> dict:
        q = conjoined(expr, spec.match)
        entry["sent"] = q
        _check_size(src, q, start, end, n, until)
        if instant:
            res = src.instant(q, end, until)
            st = None
        else:
            st = step(end - start)
            res = src.query_range(q, start, end, st, until, names=True, narrow=False)
        lines = [{"labels": lab, "points": [[t, v] for t, v in pts]} for lab, pts in res]
        return {"query": q, "lines": lines[:n], "matched": len(lines), "limit": n, "step": st, "start": start, "end": end,
                "instant": instant}
    return _run(state_dir, spec, "query" if instant else "query_range", entry, go)


def _match(expr: str, spec: SourceSpec) -> list[str]:
    """The ``match[]`` of a labels request: the selector conjoined with the source's match; with
    none, the source's match; ``Refused`` when that selects everything: a labels request naming
    nothing would read the store's whole index, and is never sent."""
    if expr.strip():
        return [conjoined(expr, spec.match)]
    scope = match_matchers(spec.match)
    if not scope:
        raise Refused("name a metric or a label matcher: the source's match selects everything, and a labels request "
                      "that names nothing would read the whole store's index")
    return ["{" + ",".join(matcher_text(*x) for x in scope) + "}"]


def labels(state_dir: Path, spec: SourceSpec, selector: str = "", *, minutes: float | None = None,
           limit_n: int | None = None, now: float | None = None) -> dict:
    """Label names within the source's match and ``selector``, over the window, at most ``limit``."""
    n = limit(limit_n, spec)
    start, end = window(minutes, now)
    entry = {"selector": selector, "start": round(start, 3), "end": round(end, 3), "limit": n}

    def go(src: PrometheusSource, until: float) -> dict:
        m = _match(selector, spec)
        entry["match"] = m
        return {"values": src.label_names(m, start, end, n), "match": m, "limit": n}
    return _run(state_dir, spec, "labels", entry, go)


def values(state_dir: Path, spec: SourceSpec, label: str, selector: str = "", *, minutes: float | None = None,
           limit_n: int | None = None, now: float | None = None) -> dict:
    """A label's values within the source's match and ``selector``, over the window, at most ``limit``."""
    n = limit(limit_n, spec)
    start, end = window(minutes, now)
    entry = {"label": label, "selector": selector, "start": round(start, 3), "end": round(end, 3), "limit": n}

    def go(src: PrometheusSource, until: float) -> dict:
        m = _match(selector, spec)
        entry["match"] = m
        return {"label": label, "values": src.label_values(label, m, start, end, n), "match": m, "limit": n}
    return _run(state_dir, spec, "label_values", entry, go)
