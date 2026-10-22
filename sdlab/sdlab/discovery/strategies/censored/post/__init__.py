"""The kubernetes climb's post-stages, ported to censored (2026-10-22, docs/research/fixes/port-censored.md).

Copied from structures at dd9d8d1 (its package as of sdlab 7c3fb13), unchanged but for the import paths:
controller.py, floor.py, counted.py, hidden.py, room.py, repair.py, rebuild.py, moves.py, delay.py, steps.py,
exprs.py and capmin.py (only its `readers` and `_min_text` are used here: censored's own capmin.py makes the
offer), and its vendored copy of combined's judge.py, params.py and deadline.py (structures/_vendored/combined at
the same commit). The fix ledger's types they carry (docs/research/fix-ledger.md): 2 controller (controller.py),
3 and 4 floored outside rates and the actuator's smeared moves (floor.py), 6 counted move (counted.py), 9 row repair
(repair.py), 11 hidden integrator (hidden.py), 12 room-limited move (room.py), 13 forced cross-unit move and 16
best-subset rows (moves.py, rebuild.py), 14 delay stage (delay.py), 15 injection- and expression-aware rows
(steps.py, exprs.py, judge.Model), 17 coflow-earn (moves.coflows), 0 declared-last and 10 stage budgets
(declared_last, timed below).

censored's own rewrites (floors, caps, gaps, exact rows) run first, as before; these stages then run in
structures' order: rows rebuilt and paired into moves, outside rates refitted under the floor, the output-error
refit, the MIN written back, then the controller, room, repair, counted move, hidden stock, room polish, delay
stage, a final repair and the declared sides filled.
"""

from __future__ import annotations

from .deadline import Overrun, deadline, outer_left

RESERVE = 90.0       # seconds of the caller's timer each optional stage leaves for the stages after it
OEFIT_SHARE = 0.25   # the output-error refit's most of the time left


def timed(stage, r, *args, share: float = 1.0, **kw):
    """(structures' _timed, dd9d8d1) An optional stage run under what is left of the caller's timer less RESERVE;
    past it the answer stands as it came (the stage's name noted). With no timer, the stage just runs. A stage that
    raises leaves the answer as it was (ledger type 10, refit-guard)."""
    left = outer_left()
    name = f"{getattr(stage, '__module__', '').rsplit('.', 1)[-1]}.{getattr(stage, '__name__', 'stage')}"
    try:
        if left is None:
            return stage(r, *args, **kw)
        if left <= RESERVE + 1.0:
            return {**r, "skipped": [*(r.get("skipped") or []), name]} if isinstance(r, dict) else r
        with deadline(min(left - RESERVE, share * left)):
            return stage(r, *args, **kw)
    except Overrun:
        return {**r, "skipped": [*(r.get("skipped") or []), f"{name} (stopped)"]} if isinstance(r, dict) else r
    except Exception as e:                                # noqa: BLE001
        if not isinstance(r, dict):
            raise
        return {**r, "post_errors": [*(r.get("post_errors") or []), f"{name}: {type(e).__name__}: {e}"[:300]]}


def declared_last(r: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """(structures' _declared_last, dd9d8d1; ledger type 0 declared-last) A declared side later stages dropped is
    filled again (boundary.fill_declared); where the data leave it nothing to carry it is written at 0."""
    from .. import boundary

    if not isinstance(r, dict) or not r.get("flows") or not boundary.Boundary(run).declared:
        return r
    b = boundary.Boundary(run)
    data = boundary.Data(stocks, run, opts or {})
    log: list[str] = []
    before = {id(f) for f in r["flows"]}
    flows = boundary.fill_declared(r["flows"], stocks, b, data, log)
    if not log:
        return r
    out = []
    for f in flows:
        rt = f.get("rate") or {}
        if id(f) not in before and rt.get("form") in ("proportional", "constant") and float(rt.get("k", rt.get("value", 1.0)) or 0.0) <= 1e-6:
            rt = {**rt, ("k" if rt.get("form") == "proportional" else "value"): 0.0}
            f = {**f, "rate": rt, "rates": [rt]}
        out.append(f)
    return {**r, "flows": out, "declared_last": log}


def before_refit(r: dict, stocks: list[dict], run: dict, opts: dict | None, o: dict) -> dict:
    """The stages structures runs between its fit and the output-error refit (o: the opts with the offered MIN)."""
    from . import floor, moves, rebuild

    r = timed(moves.coflows, timed(moves.apply, r, stocks, run, o), stocks, run, o)
    r = timed(moves.apply, r, stocks, run, o, every=True)
    r = timed(rebuild.apply, r, stocks, run, o)
    return timed(floor.apply, r, stocks, run, opts, judge_opts=o)


def after_restore(r: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The stages structures runs after the MIN is written back."""
    from . import controller, counted, delay, hidden, repair, room

    r = timed(controller.apply, r, stocks, run, opts)
    r = timed(room.apply, r, stocks, run, opts)
    r = timed(repair.apply, r, stocks, run, opts)
    if isinstance(r, dict) and "repair" in r:
        r = {**{k: v for k, v in r.items() if k != "repair"}, "repair_before_counted": r["repair"]}
    r = timed(counted.apply, r, stocks, run, opts)
    r = timed(hidden.apply, r, stocks, run, opts)
    r = timed(room.polish, r, stocks, run, opts)
    r = timed(delay.apply, r, stocks, run, opts)
    r = timed(repair.apply, r, stocks, run, opts)
    r = timed(room.earn, r, stocks, run, opts)          # (censored port, type 17) a room that stood in for later stages
    return declared_last(r, stocks, run, opts)
