"""The declared layer's storage (§5): ``<state>/model/intended/``, beside the discovered versions.

::

    journal.jsonl     every accepted call: seq, at, provenance, ops with change ids (append-only)
    d0001.json …      the declared layer after each accepted call: one version
    diff/             cached structural diffs (``diff.py``)
    requests.jsonl    the owner's requests the web server published (``requests.py``)
    announced.json    the last seq the host announced (``announce.py``)

One call is one journal line and one version ``dN``: all of its ops apply or none, under
``ModelStore.locked("intended")``. A call's seq is its version's number, and its ops' change ids
are ``c<seq>.<i>``. The store, never the caller, sets a call's ``via`` and its time ``at``; a
call ``via: page`` is one control of rule 9's closed list (``controls.page_control``). A call
citing ``provenance.request`` must cite one of the owner's open requests (``requests.open_requests``,
a 422 otherwise); the ops are given them, so one that answers it is checked against what the owner
asked (``consent.py``), and the requests an op answered are written on the journal line
(``answered``): only those are answered, not every call that cites one. The ops are given the
owner's standing consent (``standing``, ``consent.standing``); a call that settled anything under
it has ``standing_consent`` (where the owner gave it) on its journal line's provenance.
``dN`` and ``vN`` are separate numberings: neither makes the other's versions (rule 4 as
amended). Only the host and the web server write here (rule 5 as amended); everything derived
(present, heard, recording, met, …) is computed on read and never stored.

``dN`` is written first, then its journal line. A crash between the two leaves a ``dN`` with no
journal line: ``current_version()`` is the larger of the journal's last seq and the newest
``dN``, so the next call never reuses that number, and ``versions()`` lists it too (with no
author). A ``dN`` that is missing is a 404; one that exists and cannot be parsed is reported as
unreadable (500), never as missing."""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

from . import lines
from .checks import IntentError
from .checks import provenance as checked_provenance
from .controls import page_control
from .ops import apply_op, empty
from .requests import open_requests

NAME = re.compile(r"^d(\d{4,})\.json$")
LOCK = "intended"


class IntendedStore:
    def __init__(self, models, project=None):
        """``project``: the project the store belongs to, whose ``[discovery] announce_hold``
        the comparison settles suggestions by, whose instruments an attachment is checked against
        (``attach``, ``instruments.py``) and whose metrics ``design()`` reads; a store made from the
        state directory alone is given ``hold`` by its caller, and stores attachments unchecked."""
        self.models = models
        self.project = project
        self.dir = Path(models.dir) / "intended"

    @property
    def hold(self) -> int | None:
        return self.project.config.announce_hold if self.project is not None else None

    @property
    def standing(self) -> dict | None:
        """The owner's standing consent (``[intended] settle_own``, read from the private overlay
        only, ``config.py``): ``{"authors", "from"}``, or None without it or without a project. Read
        again when the configuration changed (``fresh_config``): the owner gives or takes it back by
        hand while the host runs."""
        from ...config import fresh_config
        if self.project is not None:
            fresh_config(self.project)
        cfg = getattr(self.project, "config", None)
        authors = tuple(getattr(cfg, "settle_own", ()) or ())
        return {"authors": authors, "from": getattr(cfg, "settle_own_from", None)} if authors else None

    def _numbers(self) -> list[int]:
        try:
            return sorted(int(m.group(1)) for p in self.dir.iterdir() if (m := NAME.match(p.name)))
        except OSError:
            return []

    def _path(self, n: int) -> Path:
        return self.dir / f"d{n:04d}.json"

    def _load(self, n: int) -> dict | None:
        """``dN`` as stored, or None when there is none; raises ``IntentError`` (500) when the
        file exists and cannot be read."""
        try:
            text = self._path(n).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as e:
            raise IntentError(f"d{n} cannot be read: {e}", status=500) from None
        try:
            d = json.loads(text)
        except ValueError as e:
            raise IntentError(f"d{n} cannot be read: {e}", status=500) from None
        if not isinstance(d, dict):
            raise IntentError(f"d{n} cannot be read: not an object", status=500)
        return d

    def _journal_lines(self) -> list[dict]:
        return [e for e in lines.records(self.dir / "journal.jsonl") if isinstance(e.get("seq"), int)]

    def current_version(self) -> int | None:
        nums = self._numbers() + [e["seq"] for e in self._journal_lines()]
        return max(nums) if nums else None

    def read(self, version: int | None = None) -> dict:
        """The declared layer at ``version`` (the current by default): ``{version, at, layer}``;
        version 0 is the empty layer before any call."""
        n = self.current_version() if version is None else version
        if not n:
            return {"version": 0, "at": None, "layer": empty()}
        d = self._load(n)
        if d is None:
            raise IntentError(f"there is no declared version d{n}", status=404)
        return {"version": n, "at": d.get("at"), "layer": {**empty(), **(d.get("layer") or {})}}

    def at(self, t: float | None) -> int:
        """The version current at time ``t`` (browsing a past ``vN`` pairs it with this), from
        the journal's times in one read."""
        if t is None:
            return self.current_version() or 0
        return max((e["seq"] for e in self._journal_lines() if (e.get("at") or 0) <= t), default=0)

    def journal(self, after: int = 0) -> list[dict]:
        return [e for e in self._journal_lines() if e["seq"] > after]

    def versions(self) -> list[dict]:
        """Every ``dN``, from the journal, and any ``dN`` a crash left with no journal line."""
        out = {e["seq"]: {"version": e["seq"], "at": e.get("at"), "author": (e.get("provenance") or {}).get("author"),
                          "via": (e.get("provenance") or {}).get("via"), "changes": e.get("changes", [])}
               for e in self._journal_lines()}
        for n in self._numbers():
            if n not in out:
                try:
                    at = (self._load(n) or {}).get("at")
                except IntentError:
                    at = None
                out[n] = {"version": n, "at": at, "author": None, "via": None, "changes": []}
        return [out[n] for n in sorted(out)]

    def apply(self, ops, provenance: dict | None, via: str = "plugin") -> dict:
        """Apply one call: every op or none. Returns ``{"version", "changes"}``; raises
        ``IntentError`` with the refused op's ``index``."""
        if not isinstance(ops, list) or not ops:
            raise IntentError("ops is a non-empty list", status=400)
        prov = checked_provenance(provenance, via)
        if via == "page":
            page_control(ops)
        instruments = None
        if self.project is not None and any(isinstance(o, dict) and o.get("op") in ("propose_attachment", "revise_attachment")
                                            for o in ops):
            from .instruments import Instruments
            instruments = Instruments(self.project)
        with self.models.locked(LOCK):
            cur = self.read()
            asked = open_requests(self, cur["layer"]) if prov.get("request") else {}
            if prov.get("request") and prov["request"] not in asked:
                raise IntentError(f"provenance.request {prov['request']} is not one of the owner's unanswered requests")
            answered: set[str] = set()
            used: set[str] = set()
            standing = self.standing
            prov["at"] = time.time()
            layer = copy.deepcopy(cur["layer"])
            seq = (self.current_version() or 0) + 1
            changes = []
            for i, op in enumerate(ops):
                cid = f"c{seq}.{i}"
                try:
                    part, eid = apply_op(layer, op, {"provenance": prov, "change": cid, "requests": asked, "answered": answered,
                                                     "instruments": instruments, "standing": standing, "standing_used": used})
                except IntentError as e:
                    raise IntentError(str(e), index=i, status=e.status) from None
                changes.append({"op": op.get("op"), "part": part, "id": eid, "change": cid})
            self.dir.mkdir(parents=True, exist_ok=True)
            p = self._path(seq)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": seq, "at": prov["at"], "layer": layer}) + "\n", encoding="utf-8")
            tmp.replace(p)
            stamped = [{**op, "change": c["change"]} for op, c in zip(ops, changes)]
            said = {**prov, "standing_consent": min(used)} if used else prov
            lines.append(self.dir / "journal.jsonl", {"seq": seq, "at": prov["at"], "provenance": said, "ops": stamped,
                                                      "changes": changes, **({"answered": sorted(answered)} if answered else {})})
        return {"version": seq, "changes": changes}

    def _hold(self, hold: int | None) -> int:
        hold = hold if hold is not None else self.hold
        if hold is None:
            raise ValueError("the comparison needs announce_hold: give hold, or make the store with its project")
        return hold

    def diff(self, model=None, since=None, hold: int | None = None, **kw) -> dict:
        """The Dynamics comparison (``view.dynamics_block``); ``hold`` the project's
        ``announce_hold`` by default."""
        from .view import dynamics_block
        return dynamics_block(self, model=model, since=since, hold=self._hold(hold), **kw)

    def design(self, hold: int | None = None, observed: set[str] | None = None) -> dict:
        """The plugin's summary (``design.design``); ``observed``: the machine ids the Machines
        page has observed, when the caller has them."""
        from .design import design
        return design(self, self._hold(hold), observed=observed)
