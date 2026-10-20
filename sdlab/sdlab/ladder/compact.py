"""Small, cached responses made from the summary (api.summary), so a page never fetches the whole
matrix to show part of it.

    matrix(case?)      the matrix view's cells, only the fields its squares show, as rows of a table:
                       {version, strategies, fields, cases, variants, cells: [[case i, variant i, strategy i,
                       value per field]], totals, by_tag (without case)}; with case, only that case's cells
    respond(key, make, request)   a JSON response made once per key and summary version and kept
                       serialized and gzipped, so a repeated request costs no Python work; while a
                       newer one is made (in the background) the last one is served
"""

from __future__ import annotations

import gzip
import json
import threading
import time

from fastapi import Request, Response

from . import leaderboard

FIELDS = ("status", "stale", "recall", "right", "of", "spurious", "skill20", "fresh20", "error", "analysis", "achievable_p")
ERROR_CHARS = 200                     # the matrix's tooltip shows the first 200 characters of an error


def _value(cell: dict, k: str):
    v = cell.get(k)
    if k == "error" and isinstance(v, str):
        return v[:ERROR_CHARS]
    return v


def matrix(case: str | None = None) -> dict:
    sm, ix, version = leaderboard.current()
    cells = [c for c in sm["cells"] if c["case"] == case] if case else sm["cells"]
    cases, variants = {}, {}
    names = {s["name"]: i for i, s in enumerate(sm["strategies"])}
    rows = []
    for c in cells:
        ci = cases.setdefault(c["case"], len(cases))
        vi = variants.setdefault(c["variant"], len(variants))
        if c["strategy"] in names:
            rows.append([ci, vi, names[c["strategy"]], *(_value(c, k) for k in FIELDS)])
    out = {"version": version, "case": case, "strategies": sm["strategies"], "fields": list(FIELDS), "cases": list(cases),
           "variants": list(variants), "cells": rows}
    if not case:
        out.update(totals=sm["totals"], by_tag=sm["by_tag"])
    return out


_made: dict = {}                      # key -> (version, when, JSON bytes, gzipped bytes)
_busy: set = set()
_lock = threading.Lock()
KEEP = 64                             # responses kept
STALE_FOR = 60.0                      # seconds an older response may be served while a newer one is made


def _encode(value) -> tuple[bytes, bytes]:
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    return raw, gzip.compress(raw, 5)


def _made_for(key: tuple, version, make) -> tuple:
    """The response for key: made in line the first time (or when the last one is older than STALE_FOR);
    otherwise the last one made is served at once, and when the summary has changed since, one
    background thread per key makes the new one (the page polls the version and fetches it then)."""
    now = time.time()
    with _lock:
        got = _made.get(key)
        fresh = got is not None and (got[0] == version or now - got[1] < STALE_FOR)
        start = fresh and got[0] != version and key not in _busy
        if start:
            _busy.add(key)
    if not fresh:
        raw, gz = _encode(make())
        got = (version, now, raw, gz)
        with _lock:
            if len(_made) >= KEEP and key not in _made:
                _made.clear()
            _made[key] = got
        return got
    if start:
        threading.Thread(target=_remake, args=(key, version, make), daemon=True).start()
    return got


def _remake(key: tuple, version, make) -> None:
    try:
        raw, gz = _encode(make())
        with _lock:
            _made[key] = (version, time.time(), raw, gz)
    finally:
        with _lock:
            _busy.discard(key)


def _response(got: tuple, request: Request | None) -> Response:
    """The bytes, gzipped if the client takes it, with an ETag: a browser asks again with If-None-Match
    (Cache-Control: no-cache) and gets 304 while the response has not been made again."""
    zipped = request is not None and "gzip" in (request.headers.get("accept-encoding") or "")
    tag = f'"{got[0]}.{int(got[1] * 1000)}{".gz" if zipped else ""}"'
    headers = {"Cache-Control": "no-cache", "Vary": "Accept-Encoding", "ETag": tag}
    asked = (request.headers.get("if-none-match") or "") if request is not None else ""
    if tag in {t.strip().removeprefix("W/") for t in asked.split(",")}:               # a proxy may have weakened it
        return Response(status_code=304, headers=headers)
    headers |= {"Content-Encoding": "gzip"} if zipped else {}
    return Response(got[3] if zipped else got[2], media_type="application/json", headers=headers)


def respond(key: tuple, make, request: Request | None = None) -> Response:
    """make() as JSON, made once per summary version (see _made_for), serialized and gzipped."""
    from . import store
    return _response(_made_for((str(store.path()), *key), leaderboard.summary_now()[1], make), request)   # another store: its own


def respond_at(key: tuple, version, make, request: Request | None = None) -> Response:
    """make() as JSON, made once per version of its own (not the summary's): for a response that does not
    read the results, so a request never waits for the summary to be rebuilt."""
    return _response(_made_for(key, version, make), request)


def summary_response(names: list[str] | None, request: Request | None = None) -> Response:
    """The whole summary (api.summary) for /api/ladder/summary, serialized and gzipped once per value."""
    from . import api
    return respond(("summary", tuple(names or ())), lambda: api.summary(names), request)
