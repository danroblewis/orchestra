"""The model's own events (goal G12): Orchestra says when the model's structure changed, and when
the measured levels left its predictions, so other machines can listen (a pipeline manager, the
Desk). The host publishes them after each of its discoveries, as itself (``orchestra-host``):
they are Orchestra's own events, so Orchestra writes their ``data``.

``orchestra.model.changed``: stocks, flows or loops (``sd.loops``) were added or removed.
``data``: ``added`` and ``removed`` (each ``{"stocks", "flows", "loops"}``, lists of ids), the
``era`` the model is of, ``held`` (how many discoveries in a row found it) and ``first_seen``.

Discovery churns: a borderline stock comes and goes between runs, and the owner likes watching it
think. So a change is announced only when the same structure has been found in ``hold``
discoveries in a row (``[discovery] announce_hold``, default 3), compared with the structure last
announced (at the host's first discovery: the structure then, unannounced), and no sooner than
``gap_s`` after the last announcement (``[discovery] announce_gap``, default 30 min; a change
still held when the gap ends is announced then). A flip that comes back within the hold is never
announced. Saved model versions are unaffected: they are saved whenever the structure changes.

``orchestra.model.diverged``: stocks whose measured level has been outside the model's predicted
band for at least ``[discovery] diverge_after`` (``sd.diverge``). ``data``: ``stocks``, each
with its ``gap`` (the level less the central prediction, in half-widths of the band), its
``level``, the band (``lo``, ``hi``, ``central``), ``since`` and ``predicted_at``; ``diverged``,
every stock diverged now; the ``era`` and when it began (``era_start``), so a listener can tell a
divergence right after an announced change from an unexplained one. ``orchestra.model.returned``:
stocks back inside their band, the same fields, with ``diverged_since``. Divergence needs
``orchestra[sd]`` (the simulator); without it only structure changes and stalls are announced.

``orchestra.model.stalled``: a stock or a flow that stopped moving (``sd.stall``): a stock whose
level rose over the last ``[discovery] stall_after`` while every outflow drained less than
``[discovery] stall_share`` of its usual rate, or a flow usually above zero measured at zero for
that whole window. One event per item, its ``subject`` ``stock:<id>`` or ``flow:<id>``, so a
listener can wake on one item (``orchestra.model.stalled:stock:queue``). ``data``: ``kind``
(``stock`` or ``flow``), ``id``, ``name``, ``since``, ``window_s``, ``per`` (the model's time unit
the rates are in); a stock's ``level``, ``rose_by`` and ``outflows`` (each ``{flow, rate,
usual}``); a flow's ``rate`` and ``usual``; the ``era`` and ``era_start``. Announced once per
stall; ``orchestra.model.resumed`` (the same fields as its stall, with ``stalled_since``) when the
item moves again. Stalls read the series only, so they need no simulator.

The state (the structure last announced, the change being held, the predictions, which stocks are
out) is the model store's ``announce.json`` record."""

from __future__ import annotations

from .compare import diff, ids
from .diverge import judge, predict
from .model import Model
from .stall import step as stall_step
from .store import ModelStore

RECORD = "announce"
KEEP = 64           # predictions kept, at most


def structure_step(state: dict, model: Model, at: float, hold: int, gap_s: float) -> tuple[dict, dict | None]:
    """One discovery's part in announcing structure changes: the new state, and the data of an
    ``orchestra.model.changed`` to publish now, or None."""
    cur = ids(model)
    base = state.get("baseline")
    if base is None:
        return {**state, "baseline": cur, "pending": None}, None
    if cur == base:
        return {**state, "pending": None}, None
    pending = state.get("pending")
    pending = {**pending, "seen": pending["seen"] + 1} if pending and pending["ids"] == cur else {"ids": cur, "seen": 1, "since": at}
    last = state.get("last_changed_at")
    if pending["seen"] >= max(1, hold) and (last is None or at - last >= gap_s):
        d = diff(base, cur)
        data = {**d, "era": model.era, "held": pending["seen"], "first_seen": pending["since"]}
        return {**state, "baseline": cur, "pending": None, "last_changed_at": at}, data
    return {**state, "pending": pending}, None


def divergence_step(state: dict, model: Model, history: dict, at: float, after_s: float, every_s: float) -> tuple[dict, list, list]:
    """One discovery's part in announcing divergence: judge the levels now against the oldest
    prediction that reaches now, then predict from now. Returns the new state, the stocks that
    diverged and those that returned."""
    horizon = max(after_s, 2 * every_s)
    preds = [p for p in state.get("predictions") or [] if at - p["at"] <= p["horizon_s"]]
    levels = {sid: pts[-1][1] for sid, pts in (history.get("stocks") or {}).items() if pts}
    div, went, came = judge(state.get("divergence") or {}, preds, levels, at, after_s)
    if model.stocks and history.get("stocks"):
        preds = [*preds, predict(model, history, at, horizon)][-KEEP:]
    return {**state, "predictions": preds, "divergence": div}, went, came


def announce(store: ModelStore, publish, model: Model, at: float, history: dict | None, *, hold: int, gap_s: float,
             after_s: float, every_s: float, era_start: float | None = None, stall_after: float = 900.0,
             stall_share: float = 0.1, diverge: bool = True) -> list[str]:
    """After a discovery: publish what is due (``publish(type, data)``; a stall's with
    ``subject=``), keep the state, and say what was published. ``history`` None: neither divergence
    nor stalls are judged; ``diverge`` False: stalls only (no simulator)."""
    if (model.discovery or {}).get("not_saved"):
        return []                               # a source was missing: its stocks are not gone
    said = []
    with store.locked(RECORD):
        state = store.read_record(RECORD) or {}
        state, changed = structure_step(state, model, at, hold, gap_s)
        went = came = stopped = moving = []
        if history is not None:
            try:
                state, stopped, moving = stall_step(state, model, history, at, stall_after, stall_share)
                state.pop("stall_error", None)
            except Exception as e:  # noqa: BLE001 - a history it cannot read: the rest is still announced
                state = {**state, "stall_error": f"{type(e).__name__}: {e}"}
        if history is not None and diverge:
            try:
                state, went, came = divergence_step(state, model, history, at, after_s, every_s)
                state.pop("divergence_error", None)
            except Exception as e:  # noqa: BLE001 - a model the simulator cannot step: structure changes are still announced
                state = {**state, "divergence_error": f"{type(e).__name__}: {e}"}
        store.write_record(RECORD, state)
    if changed:
        publish("orchestra.model.changed", changed)
        said.append("orchestra.model.changed")
    now_diverged = sorted((state.get("divergence") or {}).get("diverged") or {})
    for kind, stocks in (("diverged", went), ("returned", came)):
        if stocks:
            publish(f"orchestra.model.{kind}", {"stocks": stocks, "diverged": now_diverged, "era": model.era, "era_start": era_start})
            said.append(f"orchestra.model.{kind}")
    for kind, items in (("stalled", stopped), ("resumed", moving)):
        for item in items:
            publish(f"orchestra.model.{kind}", {**item, "era": model.era, "era_start": era_start},
                    subject=f"{item['kind']}:{item['id']}")
            said.append(f"orchestra.model.{kind}")
    return said
