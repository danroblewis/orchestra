"""The model over HTTP, served by the events endpoint (``server.py``) with the same token: what
``sd.reads.ModelReads`` does from Python, for a machine in any language. (The ``/experiments``
routes were removed on 2026-11-01 with the experiments, the owner.)

Reads (``GET``):

| path | answers |
|---|---|
| ``/language`` | the equation language: syntax, functions, limits |
| ``/model?version=&raw=`` | the model (default: the current era's latest), equations in the language |
| ``/model/versions`` | every saved version |
| ``/eras`` | the eras, each era's versions, what changed at the last boundary |
| ``/observability?version=`` | which stocks what is measured determines |
| ``/series?ids=a,b&start=&end=&span_s=&points=&limit=&after=`` | series summarised, and their points on request (paged) |
| ``/predictions``, ``/predictions/<id>`` | predictions and their verdicts |
| ``/intended?version=``, ``/intended/design`` | the intended model's declared layer, and its summary (``sd.intended``) |

Writes (``POST``, a JSON object):

| path | body |
|---|---|
| ``/equations/check`` | ``equation``, ``params``, ``version``: does it parse, what it reads |
| ``/intended`` | ``source``, ``author``, ``turn``, ``message``, ``quote``, ``reason``, ``request``, ``ops``: one call to the declared layer, applied whole or refused (422, with ``index``) |

Every answer is ``{"ok": true, ...}`` or ``{"ok": false, "error": ...}`` with a status: 400 a bad
request, 404 not found, 422 an edit refused."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

ROUTES = [
    ("GET", r"/language", "language"), ("GET", r"/model", "model"), ("GET", r"/model/versions", "versions"),
    ("GET", r"/eras", "eras"), ("GET", r"/observability", "observability"), ("GET", r"/series", "series"),
    ("GET", r"/predictions", "predictions"), ("GET", r"/predictions/([^/]+)", "prediction_one"),
    ("POST", r"/equations/check", "check"),
    ("GET", r"/intended", "intended"), ("POST", r"/intended", "declare"), ("GET", r"/intended/design", "design"),
]
INTENDED = ("intended", "declare", "design")
COMPILED = [(m, re.compile(f"^{p}$"), name) for m, p, name in ROUTES]


def known(path: str) -> bool:
    return any(rx.match(path) for _, rx, _ in COMPILED)


def _q(query: dict, key: str, kind=str, default=None):
    if key not in query:
        return default
    v = query[key][-1]
    try:
        if kind is bool:
            return v.lower() in ("1", "true", "yes")
        return kind(v)
    except ValueError:
        raise _Bad(f"{key}: not a {kind.__name__}") from None


class _Bad(ValueError):
    pass


def handle(project, method: str, path: str, query: str, body: bytes, metrics=None) -> tuple[int, dict]:
    """One request: its status and its JSON answer."""
    from ..sd.reads import ModelReads, ReadError

    route = next(((name, rx.match(path)) for m, rx, name in COMPILED if m == method and rx.match(path)), None)
    if route is None:
        allowed = sorted({m for m, rx, _ in COMPILED if rx.match(path)})
        return 405, {"ok": False, "error": f"{path} takes {' and '.join(allowed)}"}
    name, match = route
    q = parse_qs(query or "", keep_blank_values=True)
    data: dict = {}
    if method == "POST":
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return 400, {"ok": False, "error": "the body must be a JSON object"}
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "the body must be a JSON object"}
    if name in INTENDED:
        return _intended(project, name, q, data)
    try:
        return 200, _call(ModelReads(project, metrics=metrics), name, match.groups(), q, data)
    except ReadError as e:
        return e.status, {"ok": False, "error": str(e)}
    except _Bad as e:
        return 400, {"ok": False, "error": str(e)}


def _intended(project, name: str, q: dict, d: dict) -> tuple[int, dict]:
    """The declared layer (``sd.intended``): read, summarised, or one call applied."""
    from ..sd.intended import IntentError

    store = project.intended
    try:
        if name == "intended":
            return 200, {"ok": True, **store.read(_q(q, "version", int))}
        if name == "design":
            return 200, {"ok": True, **store.design()}
        # every field but ops is provenance, so a misspelt one is refused (checks.PROVENANCE), never dropped
        prov = {k: v for k, v in d.items() if k != "ops" and v is not None}
        return 200, {"ok": True, **store.apply(d.get("ops"), prov, via="endpoint")}
    except IntentError as e:
        return e.status, {"ok": False, "error": str(e), **({"index": e.index} if e.index is not None else {})}
    except _Bad as e:
        return 400, {"ok": False, "error": str(e)}


def _call(x, name: str, ids: tuple, q: dict, d: dict) -> dict:
    version = _q(q, "version", int)
    if name == "language":
        return x.language()
    if name == "model":
        return x.model(version, _q(q, "raw", bool, False))
    if name == "versions":
        return x.versions()
    if name == "eras":
        return x.eras()
    if name == "observability":
        return x.observability(version)
    if name == "series":
        return x.series(_q(q, "ids", str, ""), start=_q(q, "start", float), end=_q(q, "end", float), span_s=_q(q, "span_s", float),
                        points=_q(q, "points", bool, False), limit=_q(q, "limit", int, 500), after=_q(q, "after", float), version=version)
    if name == "predictions":
        return x.predictions()
    if name == "prediction_one":
        return x.predictions(ids[0])
    return x.check_equation(d.get("equation"), d.get("params"), d.get("version"))
