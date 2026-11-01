"""The ops on declared machines and their attachments (§2, §6.3; attachments are P5's §3).

A machine always enters ``proposed``; the core checks its envelope only and stores ``spec`` as
sent. Event types a machine names that nobody declared are declared implicitly, undescribed. A
machine's expected effect is a **draft prediction**, never an association (rule 6 as amended):
it adds no flow and no hypothesis. An alias joins a declared id to an observed name; it is never
inferred."""

from __future__ import annotations

from .attach import parse
from .checks import (
    LISTS,
    IntentError,
    envelope,
    envelope_field,
    make_slug,
    number,
    only,
    strings,
    text,
)
from .revise import revise

ENVELOPE_DEFAULTS = {"title": None, "description": None, "tags": [], "kind": "universal", "managed": "orchestra",
                     "engagement": {"mode": "ad hoc"}, "receives": [], "emits": [], "reads": [], "spec": {}}
ATTACH_FIELDS = ("instrument", "match", "instance_label")


def _machine(layer: dict, mid) -> dict:
    if mid not in layer["machines"]:
        raise IntentError(f"there is no declared machine {mid!r}")
    return layer["machines"][mid]


def _implicit_events(layer: dict, m: dict, ctx: dict) -> None:
    for t in [*(m.get("receives") or []), *(m.get("emits") or [])]:
        layer["events"].setdefault(t, {"type": t, "description": None, "implicit": True, "provenance": ctx["provenance"],
                                       "change": ctx["change"]})


def propose_machine(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    fields = {k: v for k, v in op.items() if k not in ("op", "guessed")}
    env = envelope(fields)
    mid = env.get("id")
    if mid is None:
        raise IntentError("a machine needs its id: the source it is expected to publish under")
    if mid in layer["machines"]:
        raise IntentError(f"machine {mid} is already in the declared layer: revise it")
    m = {**ENVELOPE_DEFAULTS, **env}
    m["title"] = m["title"] or mid
    m.update(state="proposed", provenance=ctx["provenance"], change=ctx["change"], guessed=strings(op.get("guessed"), "guessed"),
             pending=[], aliases=[], expected_effect=None, latest=None)
    layer["machines"][mid] = m
    _implicit_events(layer, m, ctx)
    return "machine", mid


def revise_machine(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("id", "set", "add", "remove"), "revise_machine")
    m = _machine(layer, op.get("id"))
    set_, add, remove = (op.get(k) or {} for k in ("set", "add", "remove"))
    if not all(isinstance(x, dict) for x in (set_, add, remove)):
        raise IntentError("set, add and remove are objects")
    if "id" in set_:
        raise IntentError("a machine's id is not revised: retract it and propose another")
    set_ = {k: envelope_field(k, v) for k, v in set_.items()}
    for what, d in (("add", add), ("remove", remove)):
        for k, v in d.items():
            if k not in LISTS:
                raise IntentError(f"{what} takes the list fields ({', '.join(LISTS)}), not {k}")
            strings(v, f"{what}.{k}")
    revise(m, set_, add, remove, strings(op.get("guessed"), "guessed"), ctx)
    _implicit_events(layer, m, ctx)
    return "machine", m["id"]


def set_expected_effect(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    from ..predictions import PredictionError, expectation, plain

    only(op, ("machine", "edits", "horizon_s"), "set_expected_effect")
    m = _machine(layer, op.get("machine"))
    edits = op.get("edits")
    if not isinstance(edits, list):
        raise IntentError("edits is a list, in the grammar of orchestra.prediction.made")
    try:
        checked = [plain(expectation(e)) for e in edits]
    except PredictionError as e:
        raise IntentError(f"edits: {e}") from None
    horizon = number(op.get("horizon_s"), "horizon_s")
    if horizon <= 0:
        raise IntentError("horizon_s must be above 0")
    prev = m.get("expected_effect") or {}
    m["expected_effect"] = {"edits": checked, "horizon_s": horizon, "prediction": prev.get("prediction"), "change": ctx["change"]}
    return "machine", m["id"]


def record_prediction(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("machine", "prediction"), "record_prediction")
    m = _machine(layer, op.get("machine"))
    if not m.get("expected_effect"):
        raise IntentError(f"machine {m['id']} has no expected effect to link a prediction to")
    m["expected_effect"]["prediction"] = text(op.get("prediction"), "prediction", required=True, limit=256)
    return "machine", m["id"]


def alias(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("machine", "observed"), "alias")
    m = _machine(layer, op.get("machine"))
    obs = text(op.get("observed"), "observed", required=True, limit=200)
    if obs not in m["aliases"]:
        m["aliases"].append(obs)
    return "machine", m["id"]


def _attachment_fields(op: dict) -> dict:
    out = {}
    if "instrument" in op:
        out["instrument"] = text(op["instrument"], "instrument", required=True, limit=200)
    if "match" in op:
        parse(op["match"])                              # refused here with the reason, never at read
        out["match"] = op["match"]
    if "instance_label" in op:
        out["instance_label"] = text(op["instance_label"], "instance_label", limit=100)
    return out


def _checked(att: dict, ctx: dict) -> None:
    """The instrument exists, and a source's definitions keep the instance label (``instruments.py``);
    unchecked for a store made without its project (a test's, a replay's)."""
    if ctx.get("instruments") is not None:
        ctx["instruments"].check(att)


def propose_attachment(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    """An attachment: these series measure that declared machine (P5 §2). Only a declared machine
    takes one; it is proposed, or declared when the owner asks for it (§3), and never makes a
    machine, a flow or a binding."""
    only(op, ("machine", *ATTACH_FIELDS), "propose_attachment")
    m = _machine(layer, op.get("machine"))
    fields = _attachment_fields(op)
    if "instrument" not in fields:
        raise IntentError("an attachment names its instrument")
    att = {"match": None, "instance_label": None, **fields}
    _checked(att, ctx)
    base = make_slug(f"{m['id']}_{fields['instrument']}")
    aid, n = base, 1
    while aid in layer["attachments"]:
        n += 1
        aid = f"{base}_{n}"
    layer["attachments"][aid] = {"id": aid, "machine": m["id"], **att, "state": "proposed", "provenance": ctx["provenance"],
                                 "change": ctx["change"], "guessed": strings(op.get("guessed"), "guessed"), "pending": []}
    return "attachment", aid


def revise_attachment(layer: dict, op: dict, ctx: dict) -> tuple[str, str]:
    only(op, ("id", "set"), "revise_attachment")
    a = layer["attachments"].get(op.get("id"))
    if a is None:
        raise IntentError(f"there is no attachment {op.get('id')!r}")
    set_ = op.get("set") or {}
    if not isinstance(set_, dict) or set(set_) - set(ATTACH_FIELDS):
        raise IntentError(f"set takes {', '.join(ATTACH_FIELDS)}")
    fields = _attachment_fields(set_)
    _checked({**{k: a.get(k) for k in ATTACH_FIELDS}, **fields}, ctx)
    revise(a, fields, {}, {}, strings(op.get("guessed"), "guessed"), ctx)
    return "attachment", a["id"]


OPS = {"propose_machine": propose_machine, "revise_machine": revise_machine, "set_expected_effect": set_expected_effect,
       "record_prediction": record_prediction, "alias": alias, "propose_attachment": propose_attachment,
       "revise_attachment": revise_attachment}
