"""The explorer's experiment log: ``<state>/model/explorer.jsonl`` (``ModelStore.explorer()``),
one entry per experiment (``docs/proposals/metric-explorer.md``).

An experiment is one change the explorer made or proposes to what discovery is given (``match``,
``split``, ``kinds``, ``names``, an expected flow in the declared layer), recorded **before** its
effect is known: ``id``, ``t``, ``by``, ``change`` (a JSON object, as the explorer wrote it),
``expect`` (the effect expected, in words) and ``before`` (the last discovery run then, from the
run record, ``sd/runs.py``). Judging it adds ``judged``, ``judged_by``, ``verdict`` (``kept``,
``reverted``, ``inconclusive``), ``why``, ``after`` (the latest discovery run since, the same
summary), ``rounds`` (the ids of every discovery run since) and ``effect`` (after less before:
stocks, flows, mean stock trust, fitted flows, their mean R², the store requests). A run's
summary: ``id``, ``ended``, ``outcome``, ``stocks``, ``flows``, ``left_out``, ``trust``,
``fitted``, ``r2`` and ``requests`` (per source, from its cost).

``kept`` and ``reverted`` need a discovery run after the experiment: discovery's rounds judge it,
never the explorer's hope. The log is the explorer's memory (it reads it first each round, so it
never retries what failed until the data changes) and is shown in the Dynamics page's run drawer
among the runs. It records; it changes nothing. Written whole on a judgement, atomically, under a
lock."""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .runs import new_id

VERDICTS = ("kept", "reverted", "inconclusive")
SUMMARY = ("stocks", "flows", "left_out", "trust", "fitted", "r2")


class ExperimentError(ValueError):
    """An experiment that cannot be recorded or judged as asked, with why."""


def summary(run: dict | None) -> dict | None:
    """What the log keeps of a discovery run record."""
    if not run:
        return None
    res = run.get("result") or {}
    return {"id": run.get("id"), "ended": run.get("ended"), "outcome": run.get("outcome"),
            **{k: res.get(k) for k in SUMMARY},
            "requests": {name: c.get("requests") for name, c in (run.get("cost") or {}).items()}}


def effect(before: dict | None, after: dict | None) -> dict | None:
    """After less before, for each number both have; the requests summed over sources."""
    if not before or not after:
        return None
    out = {}
    for k in SUMMARY:
        if isinstance(before.get(k), (int, float)) and isinstance(after.get(k), (int, float)):
            out[k] = round(after[k] - before[k], 4)
    rb, ra = before.get("requests") or {}, after.get("requests") or {}
    if rb or ra:
        out["requests"] = sum(v or 0 for v in ra.values()) - sum(v or 0 for v in rb.values())
    return out


class ExperimentLog:
    def __init__(self, directory: Path | str, runs=None):
        self.dir = Path(directory)
        self.path = self.dir / "explorer.jsonl"
        self._runs = runs                      # the model store's RunLog

    def _discoveries(self) -> list[dict]:
        return [r for r in (self._runs.recent(0) if self._runs is not None else []) if r.get("kind") == "discovery"]

    @contextmanager
    def _locked(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.dir / "explorer.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def entries(self) -> list[dict]:
        """Every experiment, oldest first."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out = []
        for line in raw:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("id"):
                out.append(e)
        return out

    def _write(self, entries: list[dict]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in entries), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, change, expect: str, by: str = "explorer", now: float | None = None) -> dict:
        """Record an experiment before its effect is known, with the last discovery run as ``before``."""
        if isinstance(change, str):
            try:
                change = json.loads(change)
            except ValueError as e:
                raise ExperimentError(f"--change is not JSON: {e}") from None
        if not isinstance(change, dict) or not change:
            raise ExperimentError('--change is a JSON object saying what changes, e.g. {"source": "chrono", "match": ["..."]}')
        if not str(expect or "").strip():
            raise ExperimentError("--expect says the effect expected, in words, before it is known")
        t = time.time() if now is None else now
        before = [r for r in self._discoveries() if (r.get("ended") or 0) <= t]
        e = {"id": "x" + new_id(t), "t": round(t, 3), "by": str(by or "explorer"), "change": change, "expect": str(expect).strip(),
             "before": summary(before[-1] if before else None), "verdict": None}
        with self._locked(), self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
        return e

    def judge(self, exp_id: str, verdict: str, why: str, by: str = "explorer", now: float | None = None) -> dict:
        """Judge an experiment by the discovery runs since it was recorded (the module's docstring)."""
        if verdict not in VERDICTS:
            raise ExperimentError(f"--verdict is one of {', '.join(VERDICTS)}")
        if not str(why or "").strip():
            raise ExperimentError("--why says what in discovery's runs decided it")
        with self._locked():
            entries = self.entries()
            e = next((x for x in entries if x["id"] == exp_id), None)
            if e is None:
                raise ExperimentError(f"no experiment {exp_id} in {self.path}")
            since = [r for r in self._discoveries() if (r.get("ended") or 0) > e["t"]]
            if verdict != "inconclusive" and not since:
                raise ExperimentError(f"no discovery run has ended since {exp_id} was recorded: discovery's next rounds judge it "
                                      "(run `orchestra sd discover`, or wait for the host's), or judge it inconclusive")
            after = summary(since[-1] if since else None)
            e.update(judged=round(time.time() if now is None else now, 3), judged_by=str(by or "explorer"), verdict=verdict,
                     why=str(why).strip(), after=after, rounds=[r.get("id") for r in since], effect=effect(e.get("before"), after))
            self._write(entries)
        return e

    def recent(self, n: int = 200) -> list[dict]:
        return self.entries()[-n:] if n else self.entries()
