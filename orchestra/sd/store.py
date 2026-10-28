"""The model store: the one system dynamics model, with its history.

There is one model of the system. Each change to it (declaring structure, fitting equations) is
saved as a new **version**, ``<state>/model/v0001.json``, ``v0002.json``, …, and the highest is the
current model. Past versions stay readable, so the model can be compared with what it was.
Prospective versions (proposed changes, tested before they are adopted) will live beside these.

**The latest discovery** is cached in ``<state>/model/discovered.json``: the bootstrap host
rediscovers the model in the background, writes it here every time, and saves it as a new version
only when its structure (stocks, flows, forms and influences) changed. Readers (the web UI) read
the cache; nothing rediscovers on request.

Declared structure and fitted equations live together in each version; every equation carries
its origin, so a reader can always tell a fit from an assumption.

**Eras** (``sd.eras``): each version records the era it is the model of (``Model.era``). When an
era begins, the previous era's last discovery is saved as a version before anything of the new
era is, so every past era stays readable (``of_era``), and the new era's prior is the latest
version of another era (``prior_for``). Beside the versions the store keeps two small records:
``eras.json``, the eras recorded from the bus (``sd.eras.sync``), and ``announce.json``, what
the host last announced about the model (``sd.announce``)."""

from __future__ import annotations

import fcntl
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

from .model import Model

NAME = re.compile(r"^v(\d{4,})\.json$")


class ModelStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._import_legacy()

    @classmethod
    def for_state(cls, state_dir: Path) -> ModelStore:
        return cls(Path(state_dir) / "model")

    def _path(self, version: int) -> Path:
        return self.dir / f"v{version:04d}.json"

    def _numbers(self) -> list[int]:
        if not self.dir.exists():
            return []
        return sorted(int(m.group(1)) for p in self.dir.iterdir() if (m := NAME.match(p.name)))

    def _read(self, version: int) -> dict | None:
        p = self._path(version)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def save(self, model: Model, note: str = "") -> int:
        """Save the model as the next version, and return its number. Saving a model identical to
        the current one adds nothing and returns the current number."""
        errs = model.check()
        if errs:
            raise ValueError("; ".join(errs))
        nums = self._numbers()
        body = model.to_json()
        if nums and (cur := self._read(nums[-1])) and cur["model"] == body:
            return nums[-1]
        n = (nums[-1] if nums else 0) + 1
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(n)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": n, "saved_at": time.time(), "note": note, "model": body}, indent=1) + "\n",
                       encoding="utf-8")
        tmp.replace(p)
        return n

    def load(self, version: int | None = None) -> Model | None:
        """The current model, or a past version of it."""
        nums = self._numbers()
        if not nums:
            return None
        d = self._read(nums[-1] if version is None else version)
        return Model.from_json(d["model"]) if d else None

    def current_version(self) -> int | None:
        nums = self._numbers()
        return nums[-1] if nums else None

    def versions(self) -> list[dict]:
        """Every version, oldest first: its number, when and why it was saved, and its size."""
        out = []
        for n in self._numbers():
            d = self._read(n) or {}
            m = d.get("model", {})
            flows = m.get("flows", [])
            out.append({"version": n, "saved_at": d.get("saved_at"), "note": d.get("note", ""), "era": m.get("era"),
                        "stocks": len(m.get("stocks", [])), "flows": len(flows),
                        "fitted": sum(1 for f in flows if f.get("equations")), "machines": len(m.get("machines", []))})
        return out

    def of_era(self, era: str | None) -> tuple[int, Model] | None:
        """The latest version of an era's model (``None``: before any era began), with its number."""
        for n in reversed(self._numbers()):
            d = self._read(n)
            if d and d.get("model", {}).get("era") == era:
                return n, Model.from_json(d["model"])
        return None

    def prior_for(self, era: str | None) -> Model | None:
        """The model an era starts from (``sd.prior``): the latest version of any other era."""
        for n in reversed(self._numbers()):
            d = self._read(n)
            if d and d.get("model", {}).get("era") != era:
                return Model.from_json(d["model"])
        return None

    def read_record(self, name: str) -> dict | None:
        """One of the store's small records (``eras``, ``announce``), or None."""
        try:
            return json.loads((self.dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_record(self, name: str, record: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / f"{name}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(record) + "\n", encoding="utf-8")
        tmp.replace(p)

    @contextmanager
    def locked(self, name: str):
        """A record held for reading and writing, across processes."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / f"{name}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def write_discovery(self, model: Model, at: float | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / "discovered.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": at or time.time(), "model": model.to_json()}) + "\n", encoding="utf-8")
        tmp.replace(p)

    def latest_discovery(self) -> tuple[float, Model] | None:
        p = self.dir / "discovered.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d["at"], Model.from_json(d["model"])
        except (OSError, ValueError, KeyError):
            return None

    def _import_legacy(self) -> None:
        """Before 2026-10-25 models were stored by id under ``<state>/models/``; the one that existed
        becomes version 1."""
        legacy = self.dir.parent / "models" / "tickets.json"
        if self._numbers() or not legacy.exists():
            return
        d = json.loads(legacy.read_text(encoding="utf-8"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(1).write_text(json.dumps({"version": 1, "saved_at": legacy.stat().st_mtime,
                                             "note": "imported from models/tickets.json", "model": d}, indent=1) + "\n",
                                 encoding="utf-8")
