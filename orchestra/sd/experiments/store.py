"""Experiments in the state directory (AGENTS.md rule 5): ``<state>/experiments/<id>.json``, the
record, and ``<state>/experiments/<id>.runs/<run>.json``, each run's full result.

A record:

- ``id``, ``owner`` (the machine's source that made it: only it edits, runs, commits or discards
  it; anyone reads it), ``title``, ``purpose``, ``status`` (``draft``, ``committed``,
  ``discarded``), ``created_at``, ``updated_at``;
- ``base``: the model it was copied from, whole (so the diff and the replay never move when the
  model does), with ``label`` (``version``, or the latest discovery's time) and ``era``;
- ``draft``: the model as edited;
- ``scenario``: what a forward run assumes of the inputs (``inputs``: hold, step, ramp or a given
  series) and of the starting levels (``levels``);
- ``log``: every batch of edits, accepted or refused (with why), with who and when;
- ``runs``: each run's id, mode, time and summary (the full result is in its own file);
- ``prediction``: once committed, the prediction it became (``sd.predictions``);
- ``origin``: for a draft the inverse solver made, the experiment and run it came from.

Writes are atomic (a temporary file renamed), and each experiment is changed under a lock, so two
processes (the host's endpoint, a machine's Python) never interleave."""

from __future__ import annotations

import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ID = re.compile(r"^x-[0-9a-f]{12}$")
RUN = re.compile(r"^r-[0-9a-f]{12}$")
MAX_LOG = 500
STATUSES = ("draft", "committed", "discarded")


class NotFound(LookupError):
    pass


class ExperimentStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    @classmethod
    def for_state(cls, state_dir: Path) -> ExperimentStore:
        return cls(Path(state_dir) / "experiments")

    @staticmethod
    def new_id() -> str:
        return f"x-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_run_id() -> str:
        return f"r-{uuid.uuid4().hex[:12]}"

    def _path(self, eid: str) -> Path:
        if not isinstance(eid, str) or not ID.match(eid):
            raise NotFound(f"no experiment {eid!r}: an experiment's id is x- and 12 hex digits")
        return self.dir / f"{eid}.json"

    def _write(self, p: Path, body: dict) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps(body) + "\n", encoding="utf-8")
        tmp.replace(p)

    def get(self, eid: str) -> dict:
        p = self._path(eid)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotFound(f"no experiment {eid}") from None

    def put(self, rec: dict) -> dict:
        rec["updated_at"] = time.time()
        rec["log"] = rec.get("log", [])[-MAX_LOG:]
        self._write(self._path(rec["id"]), rec)
        return rec

    def all(self) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("x-*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda r: r.get("created_at") or 0)

    @contextmanager
    def locked(self, eid: str):
        self._path(eid)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / f".{eid}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def put_run(self, eid: str, run: dict) -> None:
        self._write(self.dir / f"{eid}.runs" / f"{run['id']}.json", run)

    def get_run(self, eid: str, rid: str) -> dict:
        self._path(eid)
        if not isinstance(rid, str) or not RUN.match(rid):
            raise NotFound(f"no run {rid!r}: a run's id is r- and 12 hex digits")
        try:
            return json.loads((self.dir / f"{eid}.runs" / f"{rid}.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotFound(f"no run {rid} of experiment {eid}") from None
