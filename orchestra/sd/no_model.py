"""Why there is no model: from the latest discovery's record, one paragraph and the same facts as
a dict. The Dynamics page, the CLI and the model reads (``sd.reads``, which machines call) all say
it from here, so a person and an agent are told the same thing.

``NoModel`` is what a read raises when there is no model: ``.text`` the paragraph, ``.reason``
the dict. It is a ``ReadError`` (status 404), so a caller that catches those still does."""

from __future__ import annotations

import re
from collections import Counter
from contextlib import contextmanager

from .. import runtime
from .reads import ReadError

EARLY = ("Orchestra's own", "named orchestra_", "no longer written", "not written", "too new")   # the reasons a series is left out before it is considered (sd.discover)
AGAIN = "It looks again every few minutes."
NO_HOST = "No orchestra run is running, so discovery will not run again until it starts."
HOST_UNKNOWN = "The bootstrap host (`orchestra run`) discovers it from the metrics store every few minutes."


def host_running(project) -> bool:
    """Whether an ``orchestra run`` is running for the project, by the runtime record (as the
    Instruments page judges it): only then does discovery run again by itself."""
    record = runtime.read(project)
    return runtime.launcher(record) is not None or bool(runtime.hosts(record))


def looked_at(discovery: dict) -> int:
    """How many series a discovery looked at: every one sampled (``sampled``), of which ``series``
    were considered and the rest left out at once (Orchestra's own, or not being written).
    Discoveries before 2026-10-26 recorded only ``series``: the ones left out at once are counted
    from their reasons."""
    if "sampled" in discovery:
        return int(discovery["sampled"])
    early = sum(1 for why in (discovery.get("left_out") or {}).values() if why.startswith(EARLY))
    return int(discovery.get("series") or 0) + early


def kind_of(why: str) -> str:
    """A left-out reason without its particulars, so like reasons count together: an early reason
    by its prefix, otherwise its first clause with every number as ``n``."""
    early = next((e for e in EARLY if why.startswith(e)), None)
    if early:
        return early
    if why.startswith("the same as "):
        return "the same as another series"
    head = re.split(r": | \(|; |, ", why, maxsplit=1)[0]
    head = re.sub(r"\b1 (event|step|time|point|value)\b", r"1 \1s", head)     # "1 event" counts with "3 events"
    return re.sub(r"\d+(\.\d+)?", "n", head).strip()


def no_model_reason(d: dict, where: str = "below") -> str:
    """Why a discovery found no stocks, in one clause, from what it left out: a missing source;
    none of the series could be judged (every one left out before it was considered: the
    commonest reason, 'newer than one step' when that is it); or some were judged and nothing
    balances yet. ``where`` says where the rest of the reasons are."""
    if d.get("not_saved"):
        return f"a source was missing ({d['not_saved']})"
    left = d.get("left_out") or {}
    if left and not d.get("series"):
        n = looked_at(d)
        kinds = Counter(next((e for e in EARLY if why.startswith(e)), why.split(":")[0]) for why in left.values())
        kind, k = kinds.most_common(1)[0]
        if kind == "too new":
            return (f"none could be judged yet: all {n} series are newer than one step" if k == n
                    else f"none could be judged yet: {k} of the {n} series are newer than one step, the rest left out {where}")
        return f"none could be judged yet: {k} of the {n} series were left out as {kind}" + ("" if k == n else f", the rest {where}")
    return "nothing balances yet"


def _num(x) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


def reason(discovery: dict | None, host: bool | None = None) -> dict:
    """The facts behind the paragraph: whether a discovery has run, the series it looked at and
    considered, how many it left out and how many for each kind of reason, the most events any
    moving counter counted against the minimum a balance needs, and the missing source."""
    out: dict = {"discovered": discovery is not None, "host_running": host}
    if discovery is None:
        return out
    left = discovery.get("left_out") or {}
    out.update(looked_at=looked_at(discovery), considered=int(discovery.get("series") or 0), left_out=len(left),
               by_reason=dict(Counter(kind_of(w) for w in left.values()).most_common()),
               summary=no_model_reason(discovery, where="for the other reasons listed"),
               counter_events=discovery.get("counter_events"), missing_source=discovery.get("not_saved"),
               too_young=bool(discovery.get("too_young")))
    return out


def first_sentence(r: dict) -> str:
    """The paragraph's first sentence, from ``reason``: the headline."""
    if not r["discovered"]:
        return "There is no model yet: no discovery has run yet."
    if r.get("too_young"):
        return "There is no model yet: the current era is too young to discover from."
    return (f"There is no model yet: the last discovery found no stocks among the {r['looked_at']} series it looked at "
            f"({r['summary']}).")


def text(r: dict) -> str:
    """The paragraph, from ``reason``."""
    parts = [first_sentence(r)]
    if r["discovered"] and r.get("left_out"):
        groups = "; ".join(f"{kind} ({k})" for kind, k in r["by_reason"].items())
        parts.append(f"It left out {r['left_out']} of them: {groups}.")
    ce = r.get("counter_events") if r["discovered"] else None
    if ce and ce.get("counters"):
        most, needed = ce["most"], ce["needed"]
        parts.append(f"Too few events: at most {_num(most)} per counter, {needed} needed." if most < needed
                     else f"Events per counter: up to {_num(most)} ({needed} needed for a balance).")
    elif ce is not None:
        parts.append("No counter moved in the window, so nothing could balance a level.")
    parts.append(AGAIN if r.get("host_running") else NO_HOST if r.get("host_running") is False else HOST_UNKNOWN)
    return " ".join(parts)


class NoModel(ReadError):
    """There is no model: ``text`` says why in one paragraph, ``reason`` the same as a dict.
    ``host``: whether discovery runs again by itself (None: not known here)."""

    def __init__(self, discovery: dict | None, host: bool | None = None):
        self.discovery = discovery
        self.reason = reason(discovery, host)
        self.text = text(self.reason)
        self.reason["headline"] = first_sentence(self.reason)
        super().__init__(self.text, 404)

    def answer(self) -> dict:
        """The JSON a reader gets: ``error`` is always "no model"."""
        return {"ok": False, "error": "no model", "text": self.text, "reason": self.reason}



@contextmanager
def for_project(project):
    """Raise a ``NoModel`` from within with whether the project's host is running (a read of the
    store alone cannot tell)."""
    try:
        yield
    except NoModel as e:
        if e.reason.get("host_running") is not None:
            raise
        raise NoModel(e.discovery, host_running(project)) from None
