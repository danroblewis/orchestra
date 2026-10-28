"""The repository's query script: company specifics live in the target repository, never in
Orchestra (D10). Once per inference round the script gets the candidates as JSON on standard
input and returns rewrites on standard output; nobody imports Orchestra (D16).

In:  ``{"source": "work", "candidates": [{"id", "family", "stat", "view", "group_by", "kind",
"unit", "resolution_s", "labels", "query"}]}``

Out: a list of ``{"id", "queries": [{"name", "query", "kind"?, "unit"?, "labels"?}], "reason"?,
"pin"?}``. An empty ``queries`` drops the candidate (the reason is kept); a candidate not
mentioned is kept; ``"id": null`` adds a definition of the script's own. For a counter read from
raw samples (view ``increments``) the query is the selector, and a rewrite of it stays one unless
it names another kind.

The script runs from the repository root with a timeout, like a ``[[collect]]`` command: any
executable (a ``.py`` file that is not executable runs with this Python). A failure (non-zero
exit, timeout, output that is not the shape above) fails the round with the reason; nothing is
half-applied."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from ..launcher import child_env
from .spec import KINDS, NAME, SourceSpec
from .views import Definition


class TransformError(Exception):
    pass


def script_id(path: Path) -> str:
    """``queries.py@1a2b3c4d``: the script and the hash of its content, for every origin."""
    return f"{path.name}@{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"


def _payload(spec: SourceSpec, defs: list[Definition]) -> dict:
    return {"source": spec.name, "candidates": [
        {"id": d.id, "family": d.family, "stat": d.stat, "view": d.view, "group_by": d.group_by, "kind": d.kind,
         "unit": d.unit, "resolution_s": d.resolution_s, "labels": d.labels_info, "query": d.query} for d in defs]}


def run(path: Path, repo_root: Path, payload: dict, timeout: float) -> list[dict]:
    cmd = [str(path)] if os.access(path, os.X_OK) else ([sys.executable, str(path)] if path.suffix == ".py" else None)
    if cmd is None:
        raise TransformError(f"{path} is not executable")
    try:
        p = subprocess.run(cmd, check=False, cwd=repo_root, env=child_env(), input=json.dumps(payload), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TransformError(f"{path.name} took longer than {timeout:g} s") from None
    except OSError as e:
        raise TransformError(f"{path.name} could not start: {e}") from None
    if p.returncode != 0:
        raise TransformError(f"{path.name} exited {p.returncode}: {p.stderr.strip()[-400:]}")
    try:
        out = json.loads(p.stdout or "[]")
    except ValueError as e:
        raise TransformError(f"{path.name} printed something that is not JSON: {e}") from None
    if not isinstance(out, list) or not all(isinstance(x, dict) and "id" in x for x in out):
        raise TransformError(f"{path.name} must print a list of {{\"id\", \"queries\"}}")
    return out


def _from_script(base: Definition, q: dict, n: str, who: str, spec: SourceSpec) -> Definition:
    """One query of an answer as a definition: ``<candidate id>.<n>`` for a rewrite, ``script.<n>``
    for one the script added (``n`` then names the answer and the query, so no two collide)."""
    name, query, kind = str(q.get("name") or ""), q.get("query"), q.get("kind")
    if not NAME.match(name) or not isinstance(query, str) or not query.strip() or (kind is not None and kind not in KINDS):
        raise TransformError(f"{who}: a rewrite needs a name (lower-case letters, digits, _), a query, and a kind in {sorted(KINDS)}")
    raw_counter = base.view == "increments" and kind in (None, "counter")
    return replace(base, id=f"{base.id}.{n}" if base.id else f"script.{n}", name=name, query=query,
                   kind=kind or base.kind, unit=q.get("unit") or base.unit, view=base.view if raw_counter else "script",
                   extra_labels={str(k): str(v) for k, v in (q.get("labels") or {}).items()},
                   origin=[*base.origin, f"rewritten by {who}" if base.id else f"added by {who}"],
                   flags=list(base.flags), rename=dict(base.rename) or spec.aliases())


def apply(spec: SourceSpec, repo_root: Path, defs: list[Definition]) -> tuple[list[Definition], list[Definition], str]:
    """Run the source's query script over ``defs``: (kept and added definitions, dropped ones with
    their reason, the script's id)."""
    path = (Path(repo_root) / spec.queries_script).resolve()
    if not path.is_file():
        raise TransformError(f"the query script {spec.queries_script} does not exist")
    who = script_id(path)
    answers = run(path, Path(repo_root), _payload(spec, defs), spec.script_timeout)
    by_id = {d.id: d for d in defs}
    kept, dropped, touched = [], [], set()
    blank = Definition(id="", source=spec.name, name="", family="script", view="script", kind="level", query="")
    for i, a in enumerate(answers):
        cid = a.get("id")
        if cid is not None and cid not in by_id:
            raise TransformError(f"{who}: no candidate {cid!r}")
        base = by_id[cid] if cid is not None else replace(blank, id="", origin=[])
        queries = a.get("queries")
        if not isinstance(queries, list):
            raise TransformError(f"{who}: {cid!r} needs \"queries\": a list (empty to drop it)")
        touched.add(cid)
        if cid is not None and not queries:
            dropped.append(replace(base, why=f"dropped by {who}" + (f": {a['reason']}" if a.get("reason") else "")))
            continue
        for n, q in enumerate(queries):
            d = _from_script(base, q, f"{n}" if cid is not None else f"{i}.{n}", who, spec)
            d.pin = bool(a.get("pin", False))
            if cid is None:
                d.family = f"script:{d.name}"
            kept.append(d)
    kept = [d for d in defs if d.id not in touched] + kept
    return kept, dropped, who

