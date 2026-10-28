"""The model and experiments over HTTP, served by the events endpoint (``server.py``) with the same
token: what ``sd.experiments.api.Experiments`` does from Python, for a machine in any language.

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
| ``/experiments?owner=&status=&era=`` | the experiments, each with its latest run and its verdict |
| ``/experiments/<id>?base=`` | one: its draft (equations in the language), scenario, log, runs, prediction |
| ``/experiments/<id>/diff`` | what its draft changed of its base |
| ``/experiments/<id>/runs``, ``/experiments/<id>/runs/<run>`` | its runs, and one in full |
| ``/experiments/<id>/prediction`` | the prediction it became, and its verdict |

Writes (``POST``, a JSON object with ``source``, the machine's CloudEvents source):

| path | body |
|---|---|
| ``/equations/check`` | ``equation``, ``params``, ``experiment`` or ``version``: does it parse, what it reads (no source needed) |
| ``/experiments`` | ``title``, ``purpose``, ``version``: a new draft |
| ``/experiments/<id>/edits`` | ``edits``: a batch, applied whole or refused (422, with ``index``) |
| ``/experiments/<id>/runs`` | ``mode`` (forward, replay, inverse) and its options |
| ``/experiments/<id>/commit`` | ``horizon``, ``change``, ``subject``: the prediction |
| ``/experiments/<id>/discard`` | nothing more |

Every answer is ``{"ok": true, ...}`` or ``{"ok": false, "error": ...}`` with a status: 400 a bad
request, 403 not the owner, 404 not found, 409 not a draft, 422 an edit or equation refused."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

EXP = r"(x-[0-9a-f]{12})"
RUN = r"(r-[0-9a-f]{12})"
ROUTES = [
    ("GET", r"/language", "language"), ("GET", r"/model", "model"), ("GET", r"/model/versions", "versions"),
    ("GET", r"/eras", "eras"), ("GET", r"/observability", "observability"), ("GET", r"/series", "series"),
    ("GET", r"/predictions", "predictions"), ("GET", r"/predictions/([^/]+)", "prediction_one"),
    ("POST", r"/equations/check", "check"),
    ("GET", r"/experiments", "list"), ("POST", r"/experiments", "create"),
    ("GET", rf"/experiments/{EXP}", "get"), ("GET", rf"/experiments/{EXP}/diff", "diff"),
    ("POST", rf"/experiments/{EXP}/edits", "edit"),
    ("GET", rf"/experiments/{EXP}/runs", "runs"), ("POST", rf"/experiments/{EXP}/runs", "run"),
    ("GET", rf"/experiments/{EXP}/runs/{RUN}", "run_result"),
    ("POST", rf"/experiments/{EXP}/commit", "commit"), ("POST", rf"/experiments/{EXP}/discard", "discard"),
    ("GET", rf"/experiments/{EXP}/prediction", "prediction"),
]
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
    from ..sd.experiments.api import ExperimentError, Experiments
    from ..sd.experiments.reads import ReadError

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
    try:
        x = Experiments(project, data.get("source") if name not in ("check",) else None, metrics=metrics)
        return 200 if name not in ("create",) else 201, _call(x, name, match.groups(), q, data)
    except (ExperimentError, ReadError) as e:
        return e.status, {"ok": False, "error": str(e), **getattr(e, "extra", {})}
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
    if name == "check":
        return x.check_equation(d.get("equation"), d.get("params"), d.get("experiment"), d.get("version"))
    if name == "list":
        return x.list(_q(q, "owner"), _q(q, "status"), _q(q, "era"))
    if name == "create":
        return x.create(d.get("title"), d.get("purpose") or "", d.get("version"))
    eid = ids[0]
    if name == "get":
        return x.get(eid, _q(q, "base", bool, False))
    if name == "diff":
        return x.diff(eid)
    if name == "edit":
        return x.edit(eid, d.get("edits"))
    if name == "runs":
        return x.runs(eid)
    if name == "run":
        opts = {k: v for k, v in d.items() if k not in ("source", "mode")}
        return x.run(eid, d.get("mode"), **opts)
    if name == "run_result":
        return x.run_result(eid, ids[1])
    if name == "commit":
        return x.commit(eid, d.get("horizon", d.get("horizon_s")), d.get("change"), d.get("subject"))
    if name == "discard":
        return x.discard(eid)
    return x.prediction(eid)
