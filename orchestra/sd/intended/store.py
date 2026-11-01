"""The declared layer's storage (§5): ``<state>/model/intended/``, beside the discovered versions.

::

    journal.jsonl     every accepted call: seq, at, provenance, ops with change ids (append-only)
    d0001.json …      the declared layer after each accepted call: one version
    diff/             cached structural diffs (``diff.py``)
    requests.jsonl    the owner's requests the web server published (``requests.py``)
    announced.json    the last seq the host announced (``announce.py``)

One call is one journal line and one version ``dN``: all of its ops apply or none, under
``ModelStore.locked("intended")``. A call's seq is its version's number, and its ops' change ids
are ``c<seq>.<i>``. ``dN`` and ``vN`` are separate numberings: neither makes the other's versions
(rule 4 as amended). Only the host and the web server write here (rule 5 as amended); everything
derived (present, heard, recording, met, …) is computed on read and never stored."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .checks import IntentError
from .checks import provenance as checked_provenance
from .ops import apply_op, empty

NAME = re.compile(r"^d(\d{4,})\.json$")
LOCK = "intended"


class IntendedStore:
    def __init__(self, models):
        self.models = models
        self.dir = Path(models.dir) / "intended"

    # ---- reading ----
    def _numbers(self) -> list[int]:
        try:
            return sorted(int(m.group(1)) for p in self.dir.iterdir() if (m := NAME.match(p.name)))
        except OSError:
            return []

    def _path(self, n: int) -> Path:
        return self.dir / f"d{n:04d}.json"

    def _load(self, n: int) -> dict | None:
        try:
            return json.loads(self._path(n).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def current_version(self) -> int | None:
        nums = self._numbers()
        return nums[-1] if nums else None

    def read(self, version: int | None = None) -> dict:
        """The declared layer at ``version`` (the current by default): ``{version, at, layer}``;
        version 0 is the empty layer before any call."""
        n = self.current_version() if version is None else version
        if not n:
            return {"version": 0, "at": None, "layer": empty()}
        d = self._load(n)
        if d is None:
            raise IntentError(f"there is no declared version d{n}", status=404)
        return {"version": n, "at": d.get("at"), "layer": {**empty(), **d.get("layer", {})}}

    def at(self, t: float | None) -> int:
        """The version current at time ``t`` (browsing a past ``vN`` pairs it with this)."""
        best = 0
        if t is None:
            return self.current_version() or 0
        for n in self._numbers():
            d = self._load(n)
            if d and (d.get("at") or 0) <= t:
                best = n
        return best

    def journal(self, after: int = 0) -> list[dict]:
        try:
            lines = (self.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("seq", 0) > after:
                out.append(e)
        return out

    def versions(self) -> list[dict]:
        return [{"version": e["seq"], "at": e.get("at"), "author": (e.get("provenance") or {}).get("author"),
                 "via": (e.get("provenance") or {}).get("via"), "changes": e.get("changes", [])} for e in self.journal()]

    # ---- writing ----
    def apply(self, ops, provenance: dict | None, via: str = "plugin") -> dict:
        """Apply one call: every op or none. Returns ``{"version", "changes"}``; raises
        ``IntentError`` with the refused op's ``index``."""
        if not isinstance(ops, list) or not ops:
            raise IntentError("ops is a non-empty list", status=400)
        prov = checked_provenance(provenance, via)
        with self.models.locked(LOCK):
            cur = self.read()
            layer = copy.deepcopy(cur["layer"])
            seq = cur["version"] + 1
            changes = []
            for i, op in enumerate(ops):
                cid = f"c{seq}.{i}"
                try:
                    part, eid = apply_op(layer, op, {"provenance": prov, "change": cid})
                except IntentError as e:
                    raise IntentError(str(e), index=i, status=e.status) from None
                changes.append({"op": op.get("op"), "part": part, "id": eid, "change": cid})
            self.dir.mkdir(parents=True, exist_ok=True)
            p = self._path(seq)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": seq, "at": prov["at"], "layer": layer}) + "\n", encoding="utf-8")
            tmp.replace(p)
            stamped = [{**op, "change": c["change"]} for op, c in zip(ops, changes)]
            with open(self.dir / "journal.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"seq": seq, "at": prov["at"], "provenance": prov, "ops": stamped, "changes": changes}) + "\n")
        return {"version": seq, "changes": changes}

    # ---- the comparison and the summary ----
    def diff(self, model=None, since=None, **kw) -> dict:
        from .view import dynamics_block
        return dynamics_block(self, model=model, since=since, **kw)

    def design(self) -> dict:
        from .design import design
        return design(self)
