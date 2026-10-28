"""When an inference round runs, and what is kept of it.

The round's result is cached in ``<state>/sources/<name>.json`` with the window it was inferred
over, and reused for ``infer_every`` (an hour by default) while the source's settings and the
script are unchanged (``infer.settings_key``).

- **Only one caller infers.** ``definitions(…, infer=False)`` reads the cache and never starts a
  round: the web server, the judge and ``orchestra sd show`` read so; the host's discovery and
  ``orchestra sources infer`` infer. A cache that is old is still used, and says so (``error``);
  with no cache at all the source has no definitions yet.
- **One round at a time,** across processes: a round holds ``<name>.lock``. A caller that finds it
  held waits (up to its deadline) for that round and uses what it saved.
- **A failure is not retried at once.** A round that fails, or is partial, records when the next
  may run (``<name>.attempt.json``): ``RETRY_FIRST`` after the first, four times as long after
  each next, up to ``infer_every`` (a partial round) or ``RETRY_LAST`` (a failed one). Until then
  the cached definitions stand, with the failure noted, or the source is missing with the reason
  and when it will be tried again. A full round clears it.
- **Failing rounds stop.** After ``STOP_AFTER`` rounds under the same settings that failed for
  what they cost (the round's budget or deadline spent), or one that was refused as too big to list (``listing.TooManyNames``: it would fail the same way every
  time), no round runs until the source's settings or its script change (``infer.settings_key``),
  or ``orchestra sources infer`` asks for one: a store that cannot be inferred is not paid for
  again and again.
- **A narrower round never replaces a broader one.** A round over a shorter window than the
  cached one's sees less (a deployment that did not move in 15 minutes moved in the hour); the
  cached definitions stand. Nor does a round that keeps fewer than half the definitions the
  cached one kept (a store that answered but held little: a laptop that slept). ``refresh`` (the
  CLI's ``sources infer``) accepts either."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

from . import PastDeadline, Source, SourceError
from .infer import Inference, _declared, infer, settings_key
from .listing import TooManyNames
from .spec import DeclaredSeries, SourceSpec
from .transform import TransformError

RETRY_FIRST = 300.0
RETRY_GROWTH = 4            # each next failed round waits this many times longer
RETRY_LAST = 6 * 3600.0     # at most, between failed rounds
STOP_AFTER = 3              # failed rounds under the same settings, then none until they change
NARROWER = 0.95             # of the cached window's span: a round over less is narrower


def inferred(inf: Inference) -> int:
    """How many of its kept definitions the round inferred (the declared ones are kept anyway)."""
    return sum(1 for d in inf.kept if not d.id.startswith("declared."))


def _dir(state_dir: Path) -> Path:
    return Path(state_dir) / "sources"


def cached(state_dir: Path, name: str) -> Inference | None:
    p = _dir(state_dir) / f"{name}.json"
    try:
        return Inference.from_json(json.loads(p.read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path: Path, body: str) -> None:
    """Written whole and then moved into place, from a temporary file of this write's own."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(state_dir: Path, inf: Inference) -> None:
    _write(_dir(state_dir) / f"{inf.source}.json", json.dumps(inf.to_json(), indent=1))


def attempt(state_dir: Path, name: str) -> dict:
    """The last failed or partial round: ``failures``, ``at``, ``next`` (when one may run), ``error``."""
    try:
        return json.loads((_dir(state_dir) / f"{name}.attempt.json").read_text())
    except (OSError, ValueError):
        return {}


def _failed(state_dir: Path, spec: SourceSpec, why: str, key: str = "", *, partial: bool = False, costly: bool = False,
            final: bool = False) -> dict:
    """Records a failed or partial round. ``costly``: it failed for what it cost (its budget or
    deadline spent, the store too big to list), so the next waits longer and, after
    ``STOP_AFTER`` (or at once when ``final``), none runs under these settings; a store that did
    not answer costs nothing to ask again later."""
    a = attempt(state_dir, spec.name)
    n = (int(a.get("failures") or 0) if a.get("key", key) == key else 0) + 1
    if costly:
        wait = min(max(spec.infer_every, RETRY_LAST), RETRY_FIRST * RETRY_GROWTH ** (n - 1))
    else:
        wait = min(spec.infer_every, RETRY_FIRST * (RETRY_GROWTH if partial else 2) ** (n - 1))
    rec = {"failures": n, "at": time.time(), "next": time.time() + wait, "error": why, "key": key,
           "stopped": costly and (final or n >= STOP_AFTER)}
    _write(_dir(state_dir) / f"{spec.name}.attempt.json", json.dumps(rec))
    return rec


def stopped(a: dict, key: str) -> bool:
    """Whether failed rounds stopped inference under these settings (``STOP_AFTER``)."""
    return bool(a.get("stopped")) and a.get("key") == key


def _stopped_why(a: dict) -> str:
    return (f"inference stopped after {a.get('failures')} failed round{'s' if a.get('failures', 1) != 1 else ''} (the last at "
            f"{_when(a['at'])}: {a.get('error')}); none runs until the [[sources]] entry changes (narrow match, or "
            "infer = false with [[series]]) or `orchestra sources infer` asks for one")


def _cleared(state_dir: Path, name: str) -> None:
    (_dir(state_dir) / f"{name}.attempt.json").unlink(missing_ok=True)


class _Lock:
    """``<name>.lock``, held while a round runs; ``acquire`` waits for it until ``until``."""

    def __init__(self, state_dir: Path, name: str):
        _dir(state_dir).mkdir(parents=True, exist_ok=True)
        self.fh = open(_dir(state_dir) / f"{name}.lock", "a+")  # noqa: SIM115 - held across the round

    def acquire(self, until: float | None) -> bool:
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if until is not None and time.monotonic() > until:
                    return False
                time.sleep(0.5)

    def release(self) -> None:
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def _when(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def _fresh(inf: Inference | None, key: str, spec: SourceSpec) -> bool:
    return inf is not None and inf.key == key and not inf.partial and time.time() - inf.at < spec.infer_every


def definitions(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path, state_dir: Path,
                start: float, end: float, *, refresh: bool = False, until: float | None = None, infer_ok: bool = True) -> Inference:
    """The source's definitions (see the module's docstring). Raises ``SourceError`` when there
    are none to read."""
    key = settings_key(spec, declared, repo_root)
    if not spec.infer:                     # only what is declared: nothing to infer, nothing to cache
        return Inference(spec.name, time.time(), key, _declared(spec, declared),
                         notes=["infer = false: only the declared series are read, never the schema"])
    old = cached(state_dir, spec.name)
    same = old is not None and old.key == key        # older definitions under other settings would not be what was asked for
    if _fresh(old, key, spec) and not refresh:
        return old
    if not infer_ok:
        if not same:
            raise SourceError(f"{spec.where()}: not inferred yet under these settings: the host infers at its next discovery "
                              "(or run `orchestra sources infer`)")
        if time.time() - old.at >= spec.infer_every or old.partial:
            old.error = old.error or f"inferred at {_when(old.at)}; the host infers again at its next discovery"
        return old
    a = attempt(state_dir, spec.name)
    if not refresh and stopped(a, key):
        if same:
            old.error = old.error or _stopped_why(a)
            return old
        raise SourceError(_stopped_why(a))
    if not refresh and a and a.get("key", key) == key and time.time() < float(a.get("next") or 0):
        why = f"the last round at {_when(a['at'])} failed or was partial ({a.get('error')}); the next is not before {_when(a['next'])}"
        if same:
            old.error = old.error or why
            return old
        raise SourceError(why)
    if same and not refresh and old.span() and end - start < NARROWER * old.span():
        old.error = (f"a round over {(end - start) / 60:g} min would replace one over {old.span() / 60:g} min, which saw more: "
                     f"using the definitions inferred at {_when(old.at)}")
        return old
    lock = _Lock(state_dir, spec.name)
    if not lock.acquire(until if until is not None else time.monotonic() + spec.deadline):
        lock.fh.close()
        if same:
            old.error = old.error or "another process is inferring this source; using the definitions it had"
            return old
        raise SourceError("another process is inferring this source and has not finished")
    try:
        now = cached(state_dir, spec.name)           # a round another process just finished
        if _fresh(now, key, spec) and not refresh and (old is None or now.at > old.at):
            return now
        known = {f["name"]: f for f in (old.families if same else [])}
        try:
            inf = infer(source, spec, declared, repo_root, start, end, until, known, old.remembered if old else None)
        except Exception as e:
            said = str(e) if isinstance(e, (SourceError, TransformError)) else f"{type(e).__name__}: {e}"
            costly = isinstance(e, (PastDeadline, TooManyNames)) or "probes could not be made" in said
            rec = _failed(state_dir, spec, said, key, costly=costly, final=isinstance(e, TooManyNames))
            if not same:
                raise
            then = "no next try until the settings change" if rec["stopped"] else f"the next try after {_when(rec['next'])}"
            old.error = f"inference failed ({said}); using the definitions inferred at {_when(old.at)}; {then}"
            return old
        if same and not refresh and inferred(inf) < inferred(old) / 2:
            # A store that answered but held little in the window (a laptop that slept, a server
            # restarted empty) must not replace what was seen; the next discovery tries again.
            old.error = (f"the last round kept {inferred(inf)} definitions where the one at {_when(old.at)} kept {inferred(old)}; "
                         "using those (`orchestra sources infer` accepts the new round)")
            return old
        if inf.partial:
            rec = _failed(state_dir, spec, next((n for n in inf.notes if "could not" in n or "not probed" in n), "partial"), key,
                          partial=True)
            inf.error = f"a partial round: what could not be read is noted; the next try after {_when(rec['next'])}"
        else:
            _cleared(state_dir, spec.name)
        save(state_dir, inf)
        return inf
    finally:
        lock.release()
