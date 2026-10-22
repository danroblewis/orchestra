"""z3robust's passes after its linear search (docs/research/fixes/port-z3robust.md, 2026-10-22).

Copies of milp's post-program passes, taken from the sdlab branch at 7c3fb13 (milp's files last changed at
a72bb0d): steps.py, hinge.py, room.py, effects.py, polish.py, pairs.py, hidden.py, delay.py, tidy.py,
conserve.py and quantized.py, unchanged except that the flow ids they write start "z3robust:" instead of
"milp:". Strategies are isolated (CLAUDE.md rule 11): changing milp never changes these copies.

They work on an answer's flows alone (the SD Lab flow format) and read only what a page gets, so they apply
to z3robust's answer as they do to milp's program answer. The fix ledger's types they carry
(docs/research/fix-ledger.md): 2 (quantized.py, whole-unit controllers; their rows are taken out of the Z3
problem first, as milp takes them out of its program), 3 and 9 (hinge.py: floored gap flows, active-set
refits, the move bound), 6 and 7 (effects.py: counted moves, table effects), 11 (hidden.py: a hidden
integrator written as the model's own stock), 12 (room.py: room-limited moves), 14 (delay.py), 15 (steps.py:
injection-aware rows), 16-18 (tidy.py, conserve.py) and 10's guards (`_guarded`).

`after` is milp's `_after_program` (milp/__init__.py at a72bb0d) without its output-error refit (oefit.py:
z3robust's numbers are least squares on every step, and the noise-free and counts variants carry no
measurement error for it to remove).
"""

from __future__ import annotations

from . import conserve, delay, effects, hidden, hinge, negligible, pairs, polish, quantized, room, tidy


def _guarded(fn):
    """A pass that raises leaves its input as it was (refit-guard, fix ledger type 10)."""
    def run(flows, *a, **k):
        try:
            return fn(flows, *a, **k)
        except Exception as e:                                  # noqa: BLE001
            return flows, {"error": f"{type(e).__name__}: {e}"[:200]}
    return run


def after(result: dict, stocks: list[dict], run: dict, opts: dict | None, known: dict, notes) -> dict:
    """The passes after the linear search, in milp's order."""
    opts = opts or {}
    pairs_refine, polish_refine, delay_refine, prune = (_guarded(pairs.refine), _guarded(polish.refine), _guarded(delay.refine),
                                                        _guarded(effects.prune))
    room_refine, room_counted = _guarded(room.refine), _guarded(room.counted)
    hinge_refine, effects_refine = _guarded(hinge.refine), _guarded(effects.refine)
    if known:
        result = {**result, "flows": quantized.put(result.get("flows") or [], known)}
    flows, revised = pairs_refine(result.get("flows") or [], stocks, run, opts, skip=known)
    revised = revised if revised.get("pairs") else {}
    flows, rooms = room_refine(flows, stocks, run, opts, skip=known)
    rooms = rooms if rooms.get("rooms") else {}
    if rooms:
        flows, _ = hinge_refine(flows, stocks, run, opts, skip=known)
        flows, more = room_refine(flows, stocks, run, opts, skip=known)
        rooms = {"rooms": rooms["rooms"] + (more.get("rooms") or [])}
    if revised:
        flows, _ = polish_refine(flows, stocks, run, opts, skip=known)
    flows, eff = effects_refine(flows, stocks, run, opts, skip=known)
    eff = eff if eff.get("effects") else {}
    if rooms:
        flows, cm = room_counted(flows, stocks, run, opts, skip=known)
        rooms.update({k: v for k, v in cm.items() if k != "error"})
    flows, gaps = hinge_refine(flows, stocks, run, opts, skip=known)
    if revised and gaps.get("used"):
        flows, more = pairs_refine(flows, stocks, run, opts, skip=known)
        if more.get("pairs"):
            revised = {"pairs": revised["pairs"] + more["pairs"]}
    if gaps.get("used"):
        if revised:
            flows, _ = polish_refine(flows, stocks, run, opts, skip=known)
        flows, more = effects_refine(flows, stocks, run, opts, skip=known)
        if more.get("effects"):
            eff = {"effects": (eff.get("effects") or []) + more["effects"]}
            flows, gaps = hinge_refine(flows, stocks, run, opts, skip=known)
    if not rooms:
        flows, rooms = room_refine(flows, stocks, run, opts, skip=known)
        rooms = rooms if rooms.get("rooms") else {}
        if rooms:
            flows, gaps = hinge_refine(flows, stocks, run, opts, skip=known)
            flows, more = room_refine(flows, stocks, run, opts, skip=known)
            rooms["rooms"] += more.get("rooms") or []
            flows, cm = room_counted(flows, stocks, run, opts, skip=known)
            rooms.update({k: v for k, v in cm.items() if k != "error"})
            flows, gaps = hinge_refine(flows, stocks, run, opts, skip=known)
    if rooms:
        flows, more = room_refine(flows, stocks, run, opts, skip=known)
        rooms["rooms"] += more.get("rooms") or []
    flows, pr = prune(flows, stocks, run, opts, skip=known)
    if pr:
        eff = {**(eff or {}), **pr}
    joint = {}
    if rooms and eff:
        flows, joint = polish_refine(flows, stocks, run, opts, skip=known, tables=True)
    result = {**result, "flows": flows, "gaps": gaps, **({"effects": eff} if eff else {}), **({"room": rooms} if rooms else {}),
              **({"pairs": revised} if revised else {}), **({"joint_polish": joint} if joint else {})}
    if known:
        result = {**result, "flows": quantized.put(result.get("flows") or [], known)}
    flows, td = _guarded(tidy.refine)(result.get("flows") or [], stocks, run, opts, skip=known)
    if td:
        result = {**result, "flows": flows, "tidy": td}
    flows, hid = _guarded(hidden.refine)(result.get("flows") or [], stocks, run, opts, skip=known)
    if hid:
        result = {**result, "flows": flows, "hidden": hid}
    flows, dl = delay_refine(result.get("flows") or [], stocks, run, opts, skip=known)
    if dl:
        result = {**result, "flows": flows, "delay": dl}
    flows, cv = _guarded(conserve.refine)(result.get("flows") or [], stocks, run, opts, skip=known)
    if cv:
        result = {**result, "flows": flows, "conserve": cv}
    flows, ng = _guarded(negligible.refine)(result.get("flows") or [], stocks, run, opts)   # (z3robust's own) moves of next
    if ng:                                                                                   # to nothing dropped
        result = {**result, "flows": flows, "negligible": ng}
    return {**result, "quantized": notes} if notes else result
