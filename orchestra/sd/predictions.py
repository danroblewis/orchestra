"""Predictions: a change states its effect before it is made, and the system judges it (goal G13,
the intended-effect test of docs/rationale/lifted-models.md §3.1, and the null test of §3.2).

**How a prediction is made.** The machine making a change (or a person, through the Supervisor)
publishes ``orchestra.prediction.made`` before the change. It is Orchestra's own type, like
``orchestra.machine.started``: Orchestra defines what its ``data`` holds and reads it (AGENTS.md
rule 3 forbids reading the data of other machines' event types; this one is Orchestra's
contract, published by the machine that predicts, so its ``source`` says who). It goes on the bus
rather than into a file so that one path serves every machine (in process through ``Predictions``,
from a shell through ``orchestra sd predict``, from any language through the events endpoint) and
the event log itself shows the prediction came before the change. ``data``:

- ``change``: the id of the event that makes the change. The machine may choose it before the
  change exists (``Predictions.record`` makes one when not given) and publish the change with
  that ``id``. The change must begin an era (``system.changed``, or what ``[discovery] eras_from``
  names, ``sd.eras``); the prediction is matched to the era whose ``cause`` it is;
- ``expect``: the predicted effect as edits of the model, each one of
  ``{"flow": F, "factor": r}`` (the rate times r; ``"param": p`` for one of its numbers; a factor
  of 0 is the flow disappearing), ``{"flow": F, "unchanged": true}``,
  ``{"flow" | "stock" | "loop": id, "appears" | "disappears": true}``,
  ``{"from": A, "to": B, "appears": true}`` (a new flow between two stocks, ``null`` for outside,
  when its id is not known yet), and ``{"stock": S, "below": x}`` / ``{"stock": S, "above": x}``
  (its level over the horizon's second half). An empty list is the **null test**: the change
  should change nothing;
- ``horizon_s``: how long after the change to judge it (``horizon``, a duration such as ``"30m"``,
  is accepted too);
- optionally ``trajectories``: what the predictor's own "what if" (G5, ``sd.whatif``) said the
  stocks would do, as ``{"t": [seconds after the change], "stocks": {id: {"central", "lo",
  "hi"}}}`` (``trajectories_from`` makes it from a ``what_if`` result). Without them Orchestra
  simulates the previous era's model with the predicted edits when it judges.

**The record.** ``sync`` follows the bus from where it last stopped and records each prediction
once, by its event's id, in the model store's ``predictions.json`` (in the state directory): its
``source``, when it was made, the checked data, and ``status``: ``waiting``, ``judged`` (with
its ``verdict``, ``sd.judge``) or ``invalid`` (with ``why``: data that does not parse is kept,
so the machine can be told). The host syncs as it follows the bus, and ``Predictions.record``
syncs after publishing, so its caller can read the record back at once.

Nothing here changes a machine, the model or a metric: a prediction is a statement about the
model, judged later (AGENTS.md rule 9 allows observations)."""

from __future__ import annotations

import math
import uuid

from ..events import event_time
from .store import ModelStore

MADE = "orchestra.prediction.made"
JUDGED = "orchestra.prediction.judged"
RECORD = "predictions"
PARTS = ("flow", "stock", "loop")
MAX_EXPECT = 64
MAX_ID = 256


class PredictionError(ValueError):
    pass


def _id(v, name: str) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > MAX_ID:
        raise PredictionError(f"{name} must be a non-empty string (at most {MAX_ID} characters), not {v!r}")
    return v.strip()


def _number(v, name: str, low: float | None = None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise PredictionError(f"{name} must be a number, not {v!r}")
    if low is not None and v < low:
        raise PredictionError(f"{name} must be at least {low:g}, not {v!r}")
    return float(v)


def _end(v, name: str) -> str | None:
    return None if v is None else _id(v, name)


def plain(e: dict) -> dict:
    """An expectation in its one shape (``kind``) written back as ``expect`` takes it."""
    k = e.get("kind")
    if k == "factor":
        return {"flow": e.get("flow"), "factor": e.get("factor"), **({"param": e["param"]} if "param" in e else {})}
    if k == "unchanged":
        return {"flow": e.get("flow"), "unchanged": True}
    if k in ("appears", "disappears"):
        if e.get("part") == "flow" and e.get("id") is None:
            return {"from": e.get("from"), "to": e.get("to"), k: True}
        return {e.get("part") or "flow": e.get("id"), k: True}
    if k == "level":
        return {"stock": e.get("stock"), **{w: e[w] for w in ("below", "above") if w in e}}
    raise PredictionError(f"unknown kind {k!r} in {e!r}")


def expectation(e) -> dict:
    """One expected edit, checked and put in its one shape (``kind`` and its fields); one already
    in that shape is checked again."""
    if not isinstance(e, dict):
        raise PredictionError(f"an expectation is an object, not {e!r}")
    if "kind" in e:
        if e.get("part") not in (None, *PARTS):
            raise PredictionError(f"unknown part {e.get('part')!r} in {e!r}")
        return expectation(plain(e))
    known = {"flow", "stock", "loop", "param", "factor", "unchanged", "appears", "disappears", "from", "to", "below", "above"}
    if extra := sorted(set(e) - known):
        raise PredictionError(f"unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)} in {e!r}")
    named = [p for p in PARTS if p in e]
    if "factor" in e:
        if named != ["flow"]:
            raise PredictionError(f"a factor is a flow's: {e!r}")
        r = _number(e["factor"], "factor", 0.0)
        if r == 0 and "param" not in e:
            return {"kind": "disappears", "part": "flow", "id": _id(e["flow"], "flow")}
        out = {"kind": "factor", "flow": _id(e["flow"], "flow"), "factor": r}
        if "param" in e:
            out["param"] = _id(e["param"], "param")
        return out
    if e.get("unchanged") is True:
        if named != ["flow"]:
            raise PredictionError(f"unchanged is said of one flow: {e!r} (an empty expect is the null test: nothing changes)")
        return {"kind": "unchanged", "flow": _id(e["flow"], "flow")}
    for kind in ("appears", "disappears"):
        if e.get(kind) is True:
            if len(named) == 1:
                return {"kind": kind, "part": named[0], "id": _id(e[named[0]], named[0])}
            if not named and kind == "appears" and ("from" in e or "to" in e):
                a, b = _end(e.get("from"), "from"), _end(e.get("to"), "to")
                if a is None and b is None:
                    raise PredictionError(f"a new flow has at least one end in a stock: {e!r}")
                return {"kind": "appears", "part": "flow", "from": a, "to": b}
            raise PredictionError(f"{kind} names one flow, stock or loop{' (or a new flow from and to stocks)' if kind == 'appears' else ''}: {e!r}")
    if "below" in e or "above" in e:
        if named != ["stock"]:
            raise PredictionError(f"below and above are said of a stock's level: {e!r}")
        out = {"kind": "level", "stock": _id(e["stock"], "stock")}
        for k in ("below", "above"):
            if k in e:
                out[k] = _number(e[k], k)
        return out
    raise PredictionError(f"say what is expected of it (factor, unchanged, appears, disappears, below or above): {e!r}")


def _trajectories(t) -> dict:
    if not isinstance(t, dict) or not isinstance(t.get("t"), list) or not isinstance(t.get("stocks"), dict) or not t["t"]:
        raise PredictionError("trajectories are {\"t\": [seconds after the change], \"stocks\": {id: {\"central\", \"lo\", \"hi\"}}}")
    ts = [_number(x, "t") for x in t["t"]]
    if ts != sorted(ts) or ts[0] < 0:
        raise PredictionError("trajectories: t must rise from 0 or later")
    stocks = {}
    for sid, band in t["stocks"].items():
        if not isinstance(band, dict) or not all(isinstance(band.get(k), list) and len(band[k]) == len(ts) for k in ("central", "lo", "hi")):
            raise PredictionError(f"trajectories: stock {sid!r} needs central, lo and hi, one number for each t")
        stocks[_id(sid, "stock")] = {k: [_number(x, k) for x in band[k]] for k in ("central", "lo", "hi")}
    return {"t": ts, "stocks": stocks}


def check(data) -> dict:
    """A prediction's data, checked: ``change``, ``expect`` (each in its one shape),
    ``horizon_s`` and, when given, ``trajectories``. Raises PredictionError saying what is wrong."""
    from ..config import ConfigError, parse_duration

    if not isinstance(data, dict):
        raise PredictionError("a prediction's data is an object with change, expect and horizon_s")
    if extra := sorted(set(data) - {"change", "expect", "horizon_s", "horizon", "trajectories"}):
        raise PredictionError(f"unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")
    expect = data.get("expect")
    if not isinstance(expect, list) or len(expect) > MAX_EXPECT:
        raise PredictionError(f"expect is a list of at most {MAX_EXPECT} expected edits ([] for the null test: nothing changes)")
    if "horizon_s" in data:
        horizon = _number(data["horizon_s"], "horizon_s")
    else:
        try:
            horizon = parse_duration(data.get("horizon"), 0.0) if isinstance(data.get("horizon"), str) else 0.0
        except ConfigError as e:
            raise PredictionError(f"horizon: {e}") from None
    if horizon <= 0:
        raise PredictionError("horizon_s, how long after the change to judge it, must be above 0")
    out = {"change": _id(data.get("change"), "change"), "expect": [expectation(e) for e in expect], "horizon_s": horizon}
    if data.get("trajectories") is not None:
        out["trajectories"] = _trajectories(data["trajectories"])
    return out


def recorded(store: ModelStore) -> list[dict]:
    """Every prediction recorded, in the order made."""
    return list((store.read_record(RECORD) or {}).get("predictions") or [])


def entry(ev: dict) -> dict:
    """The record of one ``orchestra.prediction.made``."""
    out = {"id": ev.get("id"), "source": ev.get("source"), "made_at": event_time(ev), "subject": ev.get("subject")}
    try:
        return {**out, **check(ev.get("data")), "status": "waiting"}
    except PredictionError as e:
        return {**out, "status": "invalid", "why": str(e)}


def sync(store: ModelStore, events) -> tuple[list[dict], list[dict]]:
    """Read what is new on the bus and record each prediction once; returns every prediction and
    the new ones. A bus read again from its start (it was replaced) keeps the verdicts."""
    with store.locked(RECORD):
        rec = store.read_record(RECORD) or {}
        if rec.get("offset", 0) > events.end():
            rec["offset"] = 0
        preds = list(rec.get("predictions") or [])
        have = {p["id"] for p in preds}
        evs, offset = events.after(rec.get("offset", 0))
        new = []
        for ev in evs:
            if ev.get("type") == MADE and ev.get("id") and ev["id"] not in have:
                new.append(entry(ev))
                have.add(ev["id"])
        store.write_record(RECORD, {**rec, "offset": offset, "predictions": preds + new})
    return preds + new, new


def update(store: ModelStore, pid: str, change) -> dict | None:
    """Change one recorded prediction under the record's lock: ``change(prediction)`` edits it in
    place, or returns False to leave it. Returns the prediction as written, or None."""
    with store.locked(RECORD):
        rec = store.read_record(RECORD) or {}
        for p in rec.get("predictions") or []:
            if p.get("id") == pid:
                if change(p) is False:
                    return None
                store.write_record(RECORD, rec)
                return p
    return None


def of_era(predictions: list[dict], era) -> list[dict]:
    """The predictions about the change that began ``era``."""
    return [p for p in predictions if era is not None and p.get("change") and p.get("change") == era.cause]


def interventions(expect: list[dict], flows: set[str] | None = None) -> list[dict]:
    """The predicted edits a "what if" (``sd.whatif``) can run: a factor on a whole flow's rate,
    and a flow that disappears (its rate times 0); only on ``flows`` when given."""
    out = []
    for e in expect:
        if e["kind"] == "factor" and "param" not in e:
            out.append({"kind": "scale_flow", "flow": e["flow"], "factor": e["factor"]})
        elif e["kind"] == "disappears" and e["part"] == "flow" and e.get("id"):
            out.append({"kind": "scale_flow", "flow": e["id"], "factor": 0.0})
    return [iv for iv in out if flows is None or iv["flow"] in flows]


def trajectories_from(what_if_result: dict) -> dict:
    """A prediction's ``trajectories`` from a ``sd.whatif.what_if`` result: each stock's run with
    the interventions, from the time the change is made."""
    return {"t": list(what_if_result["t"]),
            "stocks": {sid: {k: list(s["intervention"][k]) for k in ("central", "lo", "hi")} for sid, s in what_if_result["stocks"].items()}}


class Predictions:
    """The Python API (plugins, and the machines that use Orchestra as a library): record a
    prediction for the machine ``source`` and read verdicts, through Orchestra's objects only.

        p = Predictions(project, source="curator")
        made = p.record([{"flow": "first_try_passed_total", "factor": 1.3}], horizon="2h")
        events.publish("system.changed", {...}, id=made["change"])      # the change, carrying the id
        ...
        p.get(made["id"])["verdict"]                                    # once judged
    """

    def __init__(self, project, source: str, events=None):
        from ..events import Events

        self.project = project
        self.source = _id(source, "source")
        self.events = events or Events.for_project(project, source=self.source)
        self.store = ModelStore.for_state(project.state_dir)

    def record(self, expect: list[dict], horizon: float | str, change: str | None = None, trajectories: dict | None = None,
               subject: str | None = None) -> dict:
        """Publish the prediction (``orchestra.prediction.made``) and return its record, with the
        ``change`` id the change must carry (a new one when not given)."""
        data = {"change": change or uuid.uuid4().hex, "expect": [plain(expectation(e)) for e in expect],
                **({"horizon_s": horizon} if isinstance(horizon, (int, float)) else {"horizon": horizon})}
        if trajectories is not None:
            data["trajectories"] = trajectories
        check(data)
        ev = self.events.publish(MADE, data, source=self.source, **({"subject": subject} if subject else {}))
        sync(self.store, self.events)
        return self.get(ev["id"]) or entry(ev)

    def all(self) -> list[dict]:
        return recorded(self.store)

    def get(self, pid: str) -> dict | None:
        return next((p for p in recorded(self.store) if p.get("id") == pid), None)

    def about(self, change: str) -> list[dict]:
        """The predictions about one change."""
        return [p for p in recorded(self.store) if p.get("change") == change]

    def verdict(self, pid: str) -> dict | None:
        p = self.get(pid)
        return (p or {}).get("verdict")


def parse(text: str) -> dict:
    """One expectation as ``orchestra sd predict --expect`` writes it, checked (``expectation``):

    - ``FLOW x2`` (or ``×2``, ``*2``): the flow's rate times 2;
    - ``FLOW unchanged``;
    - ``flow ID appears`` (``stock``, ``loop``; ``disappears``), or ``flow A->B appears`` for a
      new flow between two stocks (``outside`` for none);
    - ``STOCK below 6``, ``STOCK above 6``;
    - a JSON object, as in ``expect`` (``{"flow": "f", "param": "k", "factor": 2}``)."""
    import json

    t = (text or "").strip()
    if t.startswith("{"):
        try:
            return expectation(json.loads(t))
        except ValueError as e:
            raise PredictionError(f"{text!r}: {e}") from None
    w = t.split()
    try:
        if len(w) == 2 and w[1][:1] in ("x", "×", "*") and len(w[1]) > 1:
            return expectation({"flow": w[0], "factor": float(w[1][1:])})
        if len(w) == 2 and w[1] == "unchanged":
            return expectation({"flow": w[0], "unchanged": True})
        if len(w) == 3 and w[0] in PARTS and w[2] in ("appears", "disappears"):
            if w[0] == "flow" and "->" in w[1] and w[2] == "appears":
                a, b = (None if x in ("outside", "") else x for x in w[1].split("->", 1))
                return expectation({"from": a, "to": b, "appears": True})
            return expectation({w[0]: w[1], w[2]: True})
        if len(w) == 3 and w[1] in ("below", "above"):
            return expectation({"stock": w[0], w[1]: float(w[2])})
    except ValueError as e:
        if isinstance(e, PredictionError):
            raise
        raise PredictionError(f"{text!r}: {e}") from None
    raise PredictionError(f"{text!r}: expected 'FLOW x2', 'FLOW unchanged', 'flow|stock|loop ID appears|disappears', "
                          "'flow A->B appears', 'STOCK below|above X', or a JSON object")
