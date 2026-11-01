"""A discovery's input written to a directory, and discovery replayed from it.

``write`` keeps every series one discovery read (the catalogue's reading: the own store's series
as ``MetricsStore.dump`` gave them, and each remote source's read for the window) in one plain
format, so a run can be discovered again later, after a fix to discovery, without the store or the
sources that served it::

    <dir>/manifest.json         the window (start, end, window_s), the step, the strategy and its
                                options, the deadline, the project and both commits (the project's
                                and Orchestra's), each source's status, and the series files in the
                                order discovery read them
    <dir>/series/NNNNN.json     one per series: name, labels, key, its declared kind, provenance
                                and counted traffic (when its source said so), and every point
                                [[ts, value], ...] as read

Every point read is kept, not only those in the window: discovery measures a series' resolution
and liveness from all of them. ``replay`` reads such a directory and discovers from it exactly as
``sd.rediscover`` did from the reading (``sd.simulated.discovered``, then ``sd.provenance``), with
the simulated instruments the live run allowed (recorded in the manifest). It is a read-only input:
nothing is written to a metrics store or a model store. What a replay does not repeat is what
depends on the model store at the time: the merge with an era's prior and each stock's persistence.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from ..sources.catalogue import Reading
from .model import Model
from .series import Declared, series_key

FORMAT = 1
MANIFEST = "manifest.json"
SERIES = "series"


def commit(repo: Path | str | None) -> str | None:
    """The commit checked out at ``repo`` (``+dirty`` when it has changes), or None."""
    if repo is None:
        return None
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        if head.returncode:
            return None
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=10, check=False)
        return head.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


def simulated_allowed(project, reading: Reading, collectors: list | None = None) -> list[str] | None:
    """The simulated instruments discovery allows, asked only when an own series is simulated
    (as ``sd.simulated.select`` asks); None when none is."""
    from .simulated import configured, is_simulated

    own_sim = any(is_simulated(labels) and series_key(name, labels) not in reading.provenance
                  for name, labels, _ in reading.dump)
    return sorted(configured(project, collectors)) if own_sim else None


def write(directory: Path | str, reading: Reading, *, start: float, end: float, step: float, strategy: str,
          options: dict | None = None, deadline: float | None = None, window_s: float | None = None,
          project=None, simulated: list[str] | None = None) -> Path:
    """Write ``reading`` (what discovery read over [start, end] on ``step``) to ``directory``,
    replacing a snapshot already there."""
    d = Path(directory)
    (d / SERIES).mkdir(parents=True, exist_ok=True)
    for old in (d / SERIES).glob("*.json"):
        old.unlink()
    files = []
    for i, (name, labels, pts) in enumerate(reading.dump):
        key = series_key(name, labels)
        kind = reading.kinds.get(key)
        rec = {"name": name, "labels": dict(labels), "key": key, "kind": asdict(kind) if kind else None,
               "provenance": reading.provenance.get(key), "traffic": reading.traffic.get(key),
               "points": [[t, v] for t, v in pts]}
        f = f"{SERIES}/{i:05d}.json"
        (d / f).write_text(json.dumps(rec))
        files.append(f)
    listed = {series_key(n, labels) for n, labels, _ in reading.dump}
    manifest = {
        "format": FORMAT, "written_at": time.time(),
        "window": {"start": start, "end": end, "window_s": window_s if window_s is not None else end - start},
        "step": step, "method": {"strategy": strategy, "options": options or {}, "deadline": deadline},
        "project": getattr(project, "key", None),
        "commit": {"project": commit(getattr(project, "repo_root", None)), "orchestra": commit(Path(__file__).resolve().parents[2])},
        "simulated_instruments": simulated,
        "sources": {"status": reading.status, "missing": reading.missing},
        # provenance of series not in the dump (an instrument's view of a series it did not print)
        "provenance_extra": {k: v for k, v in reading.provenance.items() if k not in listed},
        "series": files,
    }
    (d / MANIFEST).write_text(json.dumps(manifest, indent=1))
    return d


def read(directory: Path | str) -> tuple[Reading, dict]:
    """The reading a snapshot holds, and its manifest."""
    d = Path(directory)
    manifest = json.loads((d / MANIFEST).read_text())
    out = Reading(status=dict(manifest["sources"]["status"]), missing=dict(manifest["sources"]["missing"]))
    out.provenance.update(manifest.get("provenance_extra") or {})
    for f in manifest["series"]:
        rec = json.loads((d / f).read_text())
        name, labels = rec["name"], rec["labels"]
        key = series_key(name, labels)
        out.dump.append((name, labels, [(t, v) for t, v in rec["points"]]))
        if rec.get("kind"):
            out.kinds[key] = Declared(**rec["kind"])
        if rec.get("provenance") is not None:
            out.provenance[key] = rec["provenance"]
        if rec.get("traffic") is not None:
            out.traffic[key] = rec["traffic"]
    return out, manifest


def replay(directory: Path | str, *, strategy: str | None = None, options: dict | None = None,
           deadline: float | None = None) -> Model:
    """The model discovery finds in a snapshot, with the window, step and method it records
    (``strategy``, ``options`` or ``deadline`` given: those instead). Writes nothing."""
    from .provenance import annotate
    from .simulated import discovered

    reading, man = read(directory)
    method = man["method"]
    allowed = set(man.get("simulated_instruments") or [])
    m = discovered(None, reading, collectors=[], start=man["window"]["start"], end=man["window"]["end"], step=man["step"],
                   strategy=strategy or method["strategy"], options=method.get("options") if options is None else options,
                   deadline=method.get("deadline") if deadline is None else deadline, provenance=reading.provenance,
                   allowed=lambda: allowed)
    annotate(m, reading.provenance)
    m.discovery.update(window_s=man["window"]["window_s"], step_s=man["step"], replayed_from=str(Path(directory)))
    return m
