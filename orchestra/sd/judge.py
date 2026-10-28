"""Judging predictions (goal G13): when, from what, and what is published. The rules themselves
are ``sd.verdict``; the record is ``sd.predictions``.

**When.** A prediction waits until its change has begun an era (the era whose ``cause`` is its
``change``) and the horizon has passed since, and the host has discovered the era after that
(its latest discovery is of the era and at least as late as the era's start plus the horizon).
While an expected edit still rests on the prior (the era has no evidence of its own on that flow)
it waits on, up to ``PATIENCE`` horizons from the change, and is then judged ``undecided``. When
another era begins before the horizon, it is judged at once ``interrupted``, from the era's last
saved model and the levels until the next change; what the rules would say from that is
``partial``.

**From what.** The era comparison the discovery made (``discovery["era_comparison"]``,
``sd.compare``: the previous era's model against this era's own evidence). The stocks' measured
levels from the change to the horizon, read as the Dynamics page reads them
(``web.background.history``). Their predicted runs: the prediction's own ``trajectories`` when it
carries them, else the previous era's model run forward from the change with the predicted edits
(``sd.experiments.forward`` on ``sd.experiments.expect.draft``, which needs ``orchestra[sd]``;
without it the stocks are judged by the level expectations alone, ``stocks.reason`` says why). An
expected equation is judged by its law over the era's measured levels and inputs
(``sd.verdict.text_law``).

**The false-change rate** (lifted-models §3.2: a null test is worth what the quiet-period diff
rate is). Each verdict reports the threshold (``z``: a number changed when it moved by ``Z``
standard errors) and the rate a normal error would cross it (``nominal``, per number). Where the
previous era is long enough (``SPLIT_STEPS`` discovery steps a half, within the discovery
window), its two halves are discovered apart and compared like two eras: nothing was announced
between them, so every flow flagged there is a false change, and ``measured`` is the share of
compared flows flagged, with ``expected`` the false changes that share predicts among the flows
this comparison compared.

**What is published.** ``orchestra.prediction.judged``, by the host: ``subject`` and
``causationid`` the prediction's id, ``correlationid`` the change's, so the change, its era
(``orchestra.era.started``) and the verdict are linked on the bus. Its ``data`` is the verdict as
recorded: numbers, ids and codes, no prose."""

from __future__ import annotations

import math

from . import eras as era_record
from . import predictions as record
from .compare import Z, compare
from .loops import loops
from .store import ModelStore
from .trust import spread
from .verdict import edit, law, level, outcome, stock_rows, unpredicted

PATIENCE = 2.0
SPLIT_STEPS = 10
NOMINAL = round(math.erfc(Z / math.sqrt(2)), 4)          # two-sided, per number


def reader(project, metrics):
    """``raw(ref, start, end)``: a series' points, from the own store or through its source; a
    remote definition read once per window, and only what the read cache does not keep. Reads the
    host's inference; never starts one."""
    from ..sources.catalogue import Catalogue

    cat = Catalogue(project, metrics, infer=False)
    readers: dict = {}

    def raw(ref, start, end):
        if ref.source and ref.source != "own":
            if (start, end) not in readers:
                readers[(start, end)] = cat.reader(start, end, project.config.discovery_step)
            return readers[(start, end)](ref)
        return metrics.raw(ref.name, ref.labels, start=start, end=end)
    return raw


def _era_model(store: ModelStore, era, end: float, interrupted: bool):
    """The model to judge from: the host's latest discovery when it is of the era and late enough;
    else (the era is over) the era's last saved version; None to wait."""
    cached = store.latest_discovery()
    if cached and cached[1].era == era.id:
        return cached[1] if interrupted or cached[0] >= end else None
    found = store.of_era(era.id)
    return found[1] if found else None


def measured_levels(models: list, raw, start: float, until: float, step: float) -> dict[str, list]:
    """Each measured stock of ``models`` (and, as ``input:<name>``, each measured input): its level
    from ``start`` to ``until``, as ``[seconds after start, level]``."""
    from ..web.background import history

    out: dict[str, list] = {}
    for m in models:
        if m is None:
            continue
        h = history(m, raw, until, step, span_s=until - start)
        for sid, pts in (h.get("stocks") or {}).items():
            out.setdefault(sid, [[t - start, v] for t, v in pts if start <= t <= until])
        for name, pts in (h.get("inputs") or {}).items():
            out.setdefault(f"input:{name}", [[t - start, v] for t, v in pts if start <= t <= until])
    return out


def predicted_laws(expect: list[dict], prior, model, measured: dict[str, list], span_s: float) -> dict[str, dict]:
    """Each flow an expectation gives a whole equation: its predicted equation's law over the era
    (``new``) and the previous era's (``old``), as ``sd.verdict.law`` reckons them."""
    from .discover import UNITS
    from .verdict import text_law

    if model is None:
        return {}
    unit = UNITS.get(model.time_unit, 60.0)
    out = {}
    for e in expect:
        if e["kind"] != "equation":
            continue
        a = next((f for f in model.flows if f.id == e["flow"]), None)
        b = next((f for f in (prior.flows if prior else []) if f.id == e["flow"]), None)
        if a is None or a.current() is None:
            continue
        rel = spread(b)[0] if b is not None else 0.1
        old = law(b.current(), b.src, a.current(), measured, span_s, unit, rel) if b is not None and b.current() else None
        out[e["flow"]] = {"new": text_law(e["equation"], e.get("params") or {}, a.current(), measured, span_s, unit, rel), "old": old}
    return out


def laws_of(prior, model, comparison: dict, measured: dict[str, list], span_s: float) -> dict[str, dict]:
    """Each flow whose form changed at the boundary: how well its previous law predicts its count in
    the era (``sd.verdict.law``)."""
    from .discover import UNITS

    if prior is None or model is None:
        return {}
    out = {}
    for row in comparison.get("flows") or []:
        if row["status"] != "form changed":
            continue
        b, a = next((f for f in prior.flows if f.id == row["id"]), None), next((f for f in model.flows if f.id == row["id"]), None)
        if b is None or a is None or b.current() is None or a.current() is None:
            continue
        if (held := law(b.current(), b.src, a.current(), measured, span_s, UNITS.get(prior.time_unit, 60.0), spread(b)[0])) is not None:
            out[row["id"]] = held
    return out


def simulated(prior, raw, expect: list[dict], start: float, horizon_s: float, step: float) -> tuple[dict | None, str | None]:
    """The previous era's model run forward from ``start`` with the predicted edits: trajectories,
    or the reason there are none."""
    from .strategies import sd_installed

    if prior is None or not prior.stocks:
        return None, "no_prior_model"
    if not sd_installed():
        return None, "no_simulator"
    from ..web.background import history
    from .experiments.expect import draft
    from .experiments.forward import forward, trajectories

    try:
        h = history(prior, raw, start, step)
        edited, _ = draft(prior, expect)
        r = forward(prior, edited, h, horizon_s=horizon_s, now=start, points=121)
    except Exception:  # noqa: BLE001 - a model the simulator cannot step is judged by its levels alone
        return None, "simulation_failed"
    return trajectories(r), None


def false_change(project, metrics, prev_start: float | None, start: float, comparison: dict) -> dict:
    """The false-change rate, as far as it can be measured (see above)."""
    from ..sources.catalogue import Catalogue
    from .rediscover import configured_strategy
    from .strategies import discover_with

    cfg = project.config
    out = {"z": Z, "nominal": NOMINAL}
    step = cfg.discovery_step
    a = max(prev_start if prev_start is not None else -math.inf, start - cfg.discovery_window)
    a = math.ceil(a / step) * step
    b = math.floor(start / step) * step
    mid = a + math.floor((b - a) / step / 2) * step
    if mid - a < SPLIT_STEPS * step or b - mid < SPLIT_STEPS * step:
        return {**out, "measured": None, "reason": "previous_era_too_short"}
    try:
        halves = []
        for s, e in ((a, mid), (mid, b)):
            reading = Catalogue(project, metrics, infer=False).read(s, e, step, keep=False)
            halves.append(discover_with(reading.dump, start=s, end=e, step=step, strategy=configured_strategy(project),
                                        options=cfg.discovery_options, deadline=0.4 * cfg.discovery_every, kinds=reading.kinds))
    except Exception:  # noqa: BLE001 - the rate is reported unmeasured
        return {**out, "measured": None, "reason": "discovery_failed"}
    c = compare(*halves)
    rows = [f for f in c["flows"] if f["status"] in ("changed", "unchanged")]
    nums = [n for f in rows for n in f.get("params") or []]
    if not rows:
        return {**out, "measured": None, "reason": "no_flow_in_both_halves"}
    rate = sum(f["status"] == "changed" for f in rows) / len(rows)
    here = sum(f["status"] in ("changed", "unchanged") for f in comparison.get("flows") or [])
    return {**out, "measured": round(rate, 4), "flows": len(rows), "flagged": sum(f["status"] == "changed" for f in rows),
            "numbers": len(nums), "numbers_flagged": sum(n["z"] is None or abs(n["z"]) >= Z for n in nums),
            "expected": round(rate * here, 2), "window": [a, mid, b]}


def judge_one(project, metrics, store: ModelStore, p: dict, eras: list, now: float, *, measure_false: bool = True) -> dict | None:
    """The verdict on one waiting prediction, or None while it waits."""
    era = next((e for e in eras if e.cause and e.cause == p.get("change")), None)
    if era is None:
        return None
    horizon = p["horizon_s"]
    end = era.start + horizon
    later = sorted((e for e in eras if e.start > era.start or (e.start == era.start and e.id > era.id)), key=lambda e: (e.start, e.id))
    nxt = later[0] if later else None
    interrupted = nxt is not None and nxt.start < end and nxt.start <= now
    if not interrupted and now < end:
        return None
    model = _era_model(store, era, end, interrupted)
    until = nxt.start if interrupted else end
    base = {"prediction": p["id"], "change": p["change"], "era": era.id, "era_start": era.start, "horizon_s": horizon,
            "until": until, "judged_at": now, "late": p.get("made_at") is not None and p["made_at"] > era.start, "z": Z}
    if interrupted:
        base["interrupted_by"] = nxt.id
    comparison = (model.discovery or {}).get("era_comparison") if model is not None else None
    if comparison is None:
        if interrupted:
            return {**base, "verdict": "interrupted", "partial": None, "reason": "no_model_of_the_era"}
        return None
    expect = p["expect"]
    edits = [e for e in expect if e["kind"] != "level"]
    taken: set[str] = set()
    statuses = [{**e, **edit(e, comparison, model, taken)} for e in edits]
    waiting = any(s["status"] == "waiting" for s in statuses)
    if waiting and not interrupted and now < era.start + PATIENCE * horizon:
        return None
    prior_found = store.of_era(comparison.get("from"))
    prior = prior_found[1] if prior_found else None
    raw = reader(project, metrics)
    step = min(15.0, project.config.discovery_step)
    span = until - era.start
    measured = measured_levels([model, prior], raw, era.start, until, step)
    laws = laws_of(prior, model, comparison, measured, span)
    predicted = predicted_laws(expect, prior, model, measured, span)
    taken = set()
    statuses = [{**e, **edit(e, comparison, model, taken, laws, predicted)} for e in edits]
    levels = [{**e, **level(e, measured, span)} for e in expect if e["kind"] == "level"]
    if p.get("trajectories"):
        traj, why, origin = p["trajectories"], None, "prediction"
    else:
        traj, why = simulated(prior, raw, expect, era.start, horizon, step)
        origin = "simulated" if traj else None
    rows = stock_rows(traj, measured, span) if traj else None
    loop_stocks = {lp["id"]: lp["stocks"] for m in (prior, model) if m is not None for lp in loops(m)}
    extra = unpredicted(expect, comparison, statuses, model, loop_stocks, laws)
    verdict = outcome(statuses, levels, extra, rows) or "undecided"
    out = {**base, "verdict": verdict, "expectations": statuses + levels, "unpredicted": extra,
           "stocks": {"from": origin, "rows": rows or [], **({"reason": why} if why else {})},
           "compared": {"from": comparison.get("from"), "to": comparison.get("to"),
                        "flows": sum(f["status"] in ("changed", "unchanged") for f in comparison.get("flows") or [])}}
    if measure_false:
        prev = era_record.previous(eras, era)
        out["false_change"] = false_change(project, metrics, prev.start if prev else None, era.start, comparison)
    if interrupted:
        out["partial"], out["verdict"] = verdict, "interrupted"
    return out


def judge_due(project, metrics, now: float, publish=None, *, events=None, measure_false: bool = True) -> list[dict]:
    """Judge every prediction that is due; record each verdict and publish it
    (``orchestra.prediction.judged``) when ``publish(type, data, **ext)`` is given. ``events``: sync
    the record from the bus first. Returns the verdicts made now."""
    store = ModelStore.for_state(project.state_dir)
    if events is not None:
        record.sync(store, events)
    eras = era_record.recorded(store)
    made = []
    for p in record.recorded(store):
        if p.get("status") != "waiting":
            continue
        era = next((e for e in eras if e.cause and e.cause == p.get("change")), None)
        if era is not None and p.get("era") != era.id:
            record.update(store, p["id"], lambda x, e=era: x.__setitem__("era", e.id))
        v = judge_one(project, metrics, store, p, eras, now, measure_false=measure_false)
        if v is None:
            continue

        def put(x, v=v):
            if x.get("status") != "waiting":
                return False
            x.update(status="judged", verdict=v)
        if record.update(store, p["id"], put) is None:
            continue                                    # judged meanwhile by another process
        made.append(v)
        if publish is not None:
            publish(record.JUDGED, v, subject=p["id"], causationid=p["id"], correlationid=p["change"])
    return made
