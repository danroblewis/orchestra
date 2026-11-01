"""The expected set's entries as the Dynamics page reads them (§3.2, §6.1): each declared stock,
effect and flow and each mark, with what is derived on read (present, measured, the chosen
option's recording, candidates, the target's verdict). Candidates are display only: a stock the
chosen instrument records is listed, never linked (``link`` is the plugin's, rule 7 as amended).
A target on an effect found only as an input an equation reads is judged on that input's series.
A declared stock or effect whose chosen option is simulated reads ``simulated: true``, as does one
found as a simulated stock; its recording says so (``recording.simulated``), and ``measured``
stays true once it has points, so the page tags them as placeholder numbers."""

from __future__ import annotations

import copy

from ..simulated import is_simulated
from .diff import input_refs
from .facts import judged
from .revise import pending_view

COMMON = ("provenance", "state", "guessed", "change")


def _simulated(part) -> bool:
    return bool(part is not None and (part.evidence or {}).get("simulated"))


def _stock(keys, key):
    sid = keys.stocks.get(key) if key else None
    return next((s for s in keys.model.stocks if s.id == sid), None) if sid and keys.model else None


def _flow(keys, key):
    fid = keys.flows.get(key) if key else None
    return next((f for f in keys.model.flows if f.id == fid), None) if fid and keys.model else None


def is_mark(entry: dict) -> bool:
    """Whether an expected entry is a discovered part's mark (``mark_entry``), matched by key,
    rather than a declared element, matched by id."""
    return "since_version" in entry


def target_of(t: dict | None, part: str, key: str | None, keys, facts) -> dict | None:
    """A target judged on the shown model's part with ``key`` (unknown when it is absent); a key
    only an equation's input has is judged on that input's series."""
    if not t:
        return None
    if part == "flow":
        f = _flow(keys, key)
        refs = ([f.counter] if f and f.counter else list(f.measured_by or [])) if f else []
        mean = facts.count(refs, t["over_s"], f"target {key}") if refs else None
        return judged(t, mean, _simulated(f))
    s = _stock(keys, key)
    if s is None and key and (ref := input_refs(keys.model).get(key)) is not None:
        return judged(t, facts.mean_level(ref, t["over_s"], f"target {key}"), is_simulated(ref.labels))
    mean = facts.mean_level(s.series, t["over_s"], f"target {key}") if s and s.series else None
    return judged(t, mean, _simulated(s))


def _candidates(el: dict, keys, chosen_instrument: str | None) -> list[dict]:
    if not chosen_instrument or keys.model is None:
        return []
    out = []
    for s in keys.model.stocks:
        if s.series and (s.series.labels or {}).get("instrument") == chosen_instrument:
            k = keys.stock_of_id[s.id]
            if k != el.get("found_as"):
                out.append({"key": k, "id": s.id, "why": "recorded by the chosen instrument"})
    return out


def level_entry(el: dict, row: dict, keys, facts, version_label: str) -> dict:
    measure = copy.deepcopy(el.get("measure"))
    chosen, placeholder = None, False
    if measure and measure.get("chosen"):
        opt = next((o for o in measure["options"] if o.get("key") == measure["chosen"]), None)
        chosen = (opt or {}).get("instrument")
        placeholder = bool((opt or {}).get("simulated"))
        measure["recording"] = facts.recording(chosen) if chosen else None
        if measure["recording"] is not None:
            measure["recording"]["simulated"] = placeholder
    rec = (measure or {}).get("recording") or {}
    present = row["present"]
    found = _stock(keys, el.get("found_as"))
    out = {"part": el["part"], "id": el["id"], "key": el.get("found_as"), "name": el["name"],
           "declared": el.get("state") == "declared", "present": present,
           "measured": present or bool(rec.get("points")), "near": el.get("near"), "note": el.get("note"),
           "unit": el.get("unit"), "linked": el.get("linked"), "found_id": found.id if found else None,
           "simulated": placeholder or _simulated(found), "target": target_of(el.get("target"), "stock", el.get("found_as"), keys, facts),
           "candidates": _candidates(el, keys, chosen) if not present else [], "measure": measure,
           **{k: el.get(k) for k in COMMON}, "pending": pending_view(el)}
    if not present:
        out["why"] = f"expected · not in {version_label}" + ("" if out["measured"] else " · not measured")
    return out


def flow_entry(el: dict, row: dict, keys, facts, version_label: str) -> dict:
    f = _flow(keys, row["key"])
    out = {"part": "flow", "id": el["id"], "key": row["key"], "name": el["name"], "from": el.get("from"), "to": el.get("to"),
           "declared": el.get("state") == "declared", "present": row["present"], "found_id": f.id if f else None,
           "note": el.get("note"), "simulated": _simulated(f),
           "target": target_of(el.get("target"), "flow", row["key"], keys, facts),
           "candidates": [{"key": k, "id": keys.flows.get(k), "why": "between its ends"} for k in row.get("flow_candidates") or []],
           **{k: el.get(k) for k in COMMON}, "pending": pending_view(el)}
    if not row["present"]:
        out["why"] = f"expected · not in {version_label}"
    return out


def mark_entry(mk: dict, row: dict, keys, facts, status: dict | None, target: dict | None, version_label: str) -> dict:
    part = mk["part"]
    pid = keys.of(part).get(mk["key"])
    out = {"part": part, "key": mk["key"], "id": pid, "declared": False, "present": row["present"],
           "since_version": (status or {}).get("since"), "provenance": mk["provenance"], "change": mk.get("change"),
           "simulated": _simulated(_stock(keys, mk["key"]) if part == "stock" else _flow(keys, mk["key"])),
           "target": target_of(target, part, mk["key"], keys, facts)}
    if not row["present"]:
        out["why"] = f"expected · not in {version_label}"
    return out
