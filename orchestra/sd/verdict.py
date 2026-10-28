"""The rules a prediction is judged by (goal G13; docs/rationale/lifted-models.md §3.1 and §3.2).
Pure: given the era comparison (``sd.compare``: the previous era's model against this era's), the
era's model, the stocks' measured levels and their predicted runs, it says what happened. Who
gathers those, and when, is ``sd.judge``.

**Each expected edit** is ``met``, ``absent`` (no edit appeared), ``different`` (an edit appeared,
but not the one predicted) or ``waiting`` (the era has no evidence of its own on it yet):

- a **factor** r on a flow: the comparison's numbers of the flow (or the one named): the edit
  appeared when one moved (``|z| ≥ Z``, the comparison's own threshold), and is the predicted one
  when every number is within ``Z`` standard errors of r times its value before:
  ``|after − r·before| / hypot(r·se_before, se_after) < Z``. Moved but not so: ``different``;
  the flow appearing or disappearing: ``different``. A flow the era carries from its prior, or
  fits on its prior's numbers alone, is ``waiting``;
- a flow whose **form changed** (discovery chose another equation, or another stock to read) is
  judged by its law instead (``law``): the previous era's equation, run over this era's measured
  levels, predicts how many events the flow counts in the era; the count it did count is ``z``
  standard errors from that (Poisson, widened by the fit's dispersion and the previous numbers'
  own error). Discovery's choice of form churns on noise, so a form change whose old law still
  predicts the count (``|z| < Z``) is no change, and a factor r is met when r times the old law
  predicts it and the old law does not;
- **unchanged**: met when the flow is compared ``unchanged``;
- an **equation** (the flow's whole rate, in the equation language): judged by its law, as a form
  change is: the predicted equation run over the era's measured levels and inputs predicts the
  count; met when the count is within ``Z`` standard errors of that, absent when it is not but
  the previous era's law still predicts it, different when neither does (``waiting`` when the
  equation reads something not measured, so it cannot be run);
- **appears** / **disappears**: the part is reported appeared (disappeared) at the boundary; a
  new flow named by its ends matches any appeared flow between them; a flow still ``carried``
  (not found in the era since it began) counts as gone;
- a stock's level **below** / **above** x: the mean of its measured level over the horizon's
  second half.

**Unpredicted changes** are every other flow that changed, changed form (unless its old law still
holds, or cannot be run: then it counts), appeared or disappeared,
and every stock or loop that appeared or disappeared, except the stocks at the ends of a flow
predicted to appear or disappear and the loops through them.

**The stocks move as simulated** when each stock's mean measured level over the horizon's second
half is within ``Z`` standard errors of the predicted run's central level there (``stock_rows``).
The standard error combines the run's band (its 10–90% width, from the fitted numbers'
uncertainty) and the spread of the measured readings about the run: the band one reading would
fall in, not the narrower one of their mean. Readings of a stock a few minutes apart are far
from independent, and an error of the mean estimated from them is too small: on synthetic queues
it called a stock that moved as simulated out of its band in a third of the runs. So a stock
must clearly leave its simulated course to count, and a slow drift within its noise does not. At
least ``FLOOR_SHARE`` of the level, and a quarter of an item.

**The verdict** (lifted-models §3.1):

| verdict | when |
|---|---|
| ``side effect`` | any expected edit is ``different``, or any change was not predicted |
| ``no effect`` | otherwise, an expected edit is ``absent`` |
| ``passed`` | every expected edit is met, every level expectation holds and every stock is within its band (the null test, which expects no edit, passes when nothing changed) |
| ``model wrong elsewhere`` | every expected edit is met, but a level expectation fails or a stock left its band |

``None`` while any expected edit is ``waiting`` (``sd.judge`` waits, then says ``undecided``).
Without simulated runs the stocks are judged by the level expectations alone, and the verdict
says so."""

from __future__ import annotations

import math

from .compare import Z

Z10 = 1.2816                # the 90th percentile of the standard normal: a 10–90% band is ±Z10 standard deviations
FLOOR_SHARE = 0.025
FLOOR = 0.25
CHANGES = ("changed", "form changed", "appeared", "disappeared")
NO_EVIDENCE = ("carried", "prior")


def _flows(comparison: dict) -> dict[str, dict]:
    return {f["id"]: f for f in comparison.get("flows") or []}


def _r(x, n: int = 4):
    return round(x, n) if isinstance(x, (int, float)) and math.isfinite(x) else None


def law(before, src: str | None, after, measured: dict[str, list], span_s: float, unit_s: float, rel: float) -> dict | None:
    """How well the previous era's equation ``before`` predicts the count of this era's ``after``:
    the events it expects over the era's measured levels (``[[seconds after the change, level],
    …]`` up to ``span_s``) for the time the flow was live, the events counted, and what the
    count's error is made of. None when the form cannot be run here."""
    q = after.quality or {}
    n = q.get("events")
    if n is None:
        return None
    if before.form not in ("constant", "proportional", "linear"):
        from .experiments.forms import Names, text_of
        from .experiments.language import EquationError

        try:
            text, params = text_of(before, src, Names([k for k in measured if not k.startswith("input:")],
                                                      [k[6:] for k in measured if k.startswith("input:")]))
        except EquationError:
            return None
        return text_law(text, params, after, measured, span_s, unit_s, rel)
    p = before.params
    if before.form == "constant":
        mean = max(0.0, float(p.get("c", 0.0)))
    else:
        x = (before.inputs or [src])[0]
        pts = [v for t, v in measured.get(x) or [] if 0 <= t <= span_s]
        if not pts:
            return None
        c = float(p.get("c", 0.0)) if before.form == "linear" else 0.0
        mean = sum(max(0.0, c + float(p.get("k", 0.0)) * v) for v in pts) / len(pts)
    return _held(mean, q, span_s, unit_s, rel)


def _held(mean: float, q: dict, span_s: float, unit_s: float, rel: float) -> dict:
    live_s = 60.0 * q["live_minutes"] if q.get("live_minutes") else span_s
    return {"expected": round(mean * live_s / unit_s, 3), "events": float(q["events"]), "dispersion": max(1.0, q.get("dispersion") or 1.0),
            "rel": rel}


def text_law(text: str, params: dict, after, measured: dict[str, list], span_s: float, unit_s: float, rel: float) -> dict | None:
    """``law`` for an equation written in the equation language (``sd.experiments.language``):
    its rate evaluated at every reading of what it reads (``measured``: stocks by id, inputs as
    ``input:<name>``), each held until the next. None when it reads something not measured, a
    flow's own measured rate, or a delay or smooth (they need the run before the era)."""
    import math as _m

    import numpy as np

    from .experiments.compile import Frame, compile_rate
    from .experiments.language import STATEFUL, EquationError, parse

    q = (after.quality or {}) if after is not None else {}
    if q.get("events") is None:
        return None
    stocks = [k for k in measured if not k.startswith("input:")]
    inputs = [k[6:] for k in measured if k.startswith("input:")]
    try:
        parsed = parse(text, stocks=stocks, inputs=inputs, params=params)
    except EquationError:
        return None
    if parsed.observed or set(parsed.functions) & set(STATEFUL):
        return None
    reads = parsed.reads()
    series = {r: sorted((t, v) for t, v in measured.get(r) or [] if 0 <= t <= span_s) for r in reads}
    if any(not pts for pts in series.values()):
        return None
    times = sorted({t for pts in series.values() for t, _ in pts}) or [0.0]
    index = {(f"stock:{r}" if not r.startswith("input:") else r): i for i, r in enumerate(reads)}
    fr = Frame(index, 1.0, 1)
    fr.params["law"] = dict(parsed.params)
    fn = compile_rate(parsed, "law")
    pos = {r: 0 for r in reads}
    total = 0.0
    with np.errstate(all="ignore"):
        for t in times:
            for i, r in enumerate(reads):
                pts = series[r]
                while pos[r] + 1 < len(pts) and pts[pos[r] + 1][0] <= t:
                    pos[r] += 1
                fr.R[i, 0] = pts[pos[r]][1]
            v = float(np.asarray(fn(fr), dtype=float).reshape(-1)[0])
            total += max(0.0, v) if _m.isfinite(v) else 0.0
    return _held(total / len(times), q, span_s, unit_s, rel)


def _law_z(held: dict, r: float = 1.0) -> float:
    e = r * held["expected"]
    var = e * held["dispersion"] + (held["rel"] * e) ** 2
    return (held["events"] - e) / math.sqrt(var) if var > 0 else (0.0 if held["events"] == e else math.inf)


def law_holds(held: dict | None) -> bool | None:
    """Whether the old law still predicts the flow's count (None: it could not be run)."""
    return None if held is None else abs(_law_z(held)) < Z


def _by_law(held: dict | None, r: float | None) -> dict:
    if held is None:
        return {"status": "different", "compared": "form changed", "reason": "law_not_run"}
    z_old = _law_z(held)
    row = {"compared": "form changed", "law": {**held, "z": _r(z_old, 2)}}
    if r is None:
        return {"status": "met" if abs(z_old) < Z else "different", **row}
    z_new = _law_z(held, r)
    row["law"]["z_predicted"] = _r(z_new, 2)
    return {"status": "absent" if abs(z_old) < Z else "met" if abs(z_new) < Z else "different", **row}


def _factor(e: dict, f: dict | None, held: dict | None = None) -> dict:
    if f is None:
        return {"status": "absent", "reason": "not_in_model"}
    if f["status"] in NO_EVIDENCE:
        return {"status": "waiting", "reason": f["status"]}
    if f["status"] == "form changed":
        return _by_law(held, e["factor"]) if "param" not in e else {"status": "different", "compared": f["status"]}
    if f["status"] != "changed" and f["status"] != "unchanged":
        return {"status": "different", "compared": f["status"]}
    nums = [n for n in f.get("params") or [] if "param" not in e or n["param"] == e["param"]]
    if not nums:
        return {"status": "absent", "reason": "no_such_param"}
    r, rows, moved, fits = e["factor"], [], False, True
    for n in nums:
        se = math.hypot(r * n["se_before"], n["se_after"])
        want = r * n["before"]
        zc = (n["after"] - want) / se if se > 0 else (0.0 if n["after"] == want else math.inf)
        moved = moved or n["z"] is None or abs(n["z"]) >= Z
        fits = fits and abs(zc) < Z
        rows.append({"param": n["param"], "before": n["before"], "after": n["after"], "ratio": n["ratio"], "z": n["z"],
                     "predicted": _r(want, 6), "z_predicted": _r(zc, 2)})
    return {"status": "met" if moved and fits else "absent" if not moved else "different", "params": rows}


def _ends(model, fid: str) -> tuple[str | None, str | None] | None:
    f = next((x for x in (model.flows if model else []) if x.id == fid), None)
    return (f.src, f.dst) if f else None


def _equation(f: dict | None, held: dict | None) -> dict:
    """A flow expected to follow a whole new equation: met when the equation, run over the era's
    measured levels, predicts the count the era counted (``|z| < Z``); absent when it does not
    but the previous era's law still does; different when neither does."""
    if f is None:
        return {"status": "absent", "reason": "not_in_model"}
    if f["status"] in NO_EVIDENCE:
        return {"status": "waiting", "reason": f["status"]}
    if f["status"] == "disappeared":
        return {"status": "different", "compared": f["status"]}
    if held is None:
        return {"status": "pending", "compared": f["status"]}       # its law is reckoned once the era is judged (sd.judge)
    if held.get("new") is None:
        return {"status": "waiting", "reason": "law_not_run", "compared": f["status"]}
    z_new = _law_z(held["new"])
    row = {"compared": f["status"], "law": {**held["new"], "z": _r(z_new, 2)}}
    z_old = None
    if held.get("old") is not None:
        z_old = _law_z(held["old"])
        row["old_law"] = {**held["old"], "z": _r(z_old, 2)}
    if abs(z_new) < Z:
        return {"status": "met", **row}
    return {"status": "absent" if z_old is not None and abs(z_old) < Z else "different", **row}


def edit(e: dict, comparison: dict, model=None, taken: set[str] | None = None, laws: dict | None = None,
         predicted: dict | None = None) -> dict:
    """One expected edit against the comparison (``model``: the era's, for a new flow's ends;
    ``laws``: each form-changed flow's ``law``; ``predicted``: each equation expectation's flow,
    its predicted equation's law (``new``) and the previous era's (``old``))."""
    flows = _flows(comparison)
    laws = laws or {}
    if e["kind"] == "equation":
        return _equation(flows.get(e["flow"]), (predicted or {}).get(e["flow"]))
    if e["kind"] == "factor":
        return _factor(e, flows.get(e["flow"]), laws.get(e["flow"]))
    if e["kind"] == "unchanged":
        f = flows.get(e["flow"])
        if f is None:
            return {"status": "absent", "reason": "not_in_model"}
        if f["status"] in NO_EVIDENCE:
            return {"status": "waiting", "reason": f["status"]}
        if f["status"] == "form changed":
            return _by_law(laws.get(e["flow"]), None)
        return {"status": "met" if f["status"] == "unchanged" else "different", "compared": f["status"],
                **({"params": [{k: n[k] for k in ("param", "before", "after", "ratio", "z")} for n in f.get("params") or []]}
                   if f.get("params") else {})}
    kind, part = e["kind"], e["part"]
    if part == "flow" and e.get("id") is None:                    # a new flow, named by its ends
        for fid, f in flows.items():
            if f["status"] == "appeared" and fid not in (taken or set()) and _ends(model, fid) == (e["from"], e["to"]):
                if taken is not None:
                    taken.add(fid)
                return {"status": "met", "flow": fid}
        return {"status": "absent"}
    if part == "flow":
        f = flows.get(e["id"])
        status = f["status"] if f else None
        if kind == "appears":
            return {"status": "met"} if status == "appeared" else {"status": "absent", "compared": status}
        if status in ("disappeared", "carried"):
            return {"status": "met", "compared": status}
        return {"status": "absent", "compared": status}
    group = (comparison.get("stocks") if part == "stock" else comparison.get("loops")) or {}
    if e["id"] in group.get("appeared" if kind == "appears" else "disappeared", []):
        return {"status": "met"}
    if kind == "disappears" and e["id"] in group.get("carried", []):
        return {"status": "met", "compared": "carried"}
    return {"status": "absent"}


def level(e: dict, measured: dict[str, list] | None, horizon_s: float) -> dict:
    """A level expectation against the stock's measured levels (``[[seconds after the change,
    level], …]``) over the horizon's second half."""
    pts = [v for t, v in (measured or {}).get(e["stock"]) or [] if horizon_s / 2 <= t <= horizon_s]
    if not pts:
        return {"status": "waiting", "reason": "no_levels"}
    mean = sum(pts) / len(pts)
    ok = ("below" not in e or mean < e["below"]) and ("above" not in e or mean > e["above"])
    return {"status": "met" if ok else "missed", "level": _r(mean), "readings": len(pts)}


def unpredicted(expect: list[dict], comparison: dict, statuses: list[dict], model=None,
                loop_stocks: dict[str, list[str]] | None = None, laws: dict | None = None) -> list[dict]:
    """The changes at the boundary that no expectation named (``loop_stocks``: each loop's stocks,
    from either model)."""
    named = {e["flow"] for e in expect if "flow" in e}
    named |= {e["id"] for e in expect if e["kind"] in ("appears", "disappears") and e["part"] == "flow" and e.get("id")}
    named |= {s["flow"] for s in statuses if s.get("flow")}       # new flows matched by their ends
    stocks = {e["id"] for e in expect if e.get("part") == "stock"} | {e["stock"] for e in expect if e["kind"] == "level"}
    moved = [e for e in expect if e["kind"] in ("appears", "disappears") and e["part"] == "flow"]
    for e in moved:
        stocks |= {x for x in (e.get("from"), e.get("to")) if x}
        if e.get("id") and (ends := _ends(model, e["id"])):
            stocks |= {x for x in ends if x}
    for s in statuses:
        if s.get("flow") and (ends := _ends(model, s["flow"])):
            stocks |= {x for x in ends if x}
    loops = {e["id"] for e in expect if e.get("part") == "loop"}
    out = []
    for f in comparison.get("flows") or []:
        if f["status"] in CHANGES and f["id"] not in named:
            held = (laws or {}).get(f["id"])
            if f["status"] == "form changed" and law_holds(held):
                continue                                # discovery chose another form; the old law still holds
            row = {"part": "flow", "id": f["id"], "status": f["status"]}
            if held is not None:
                row["law"] = {**held, "z": _r(_law_z(held), 2)}
            if f.get("params"):
                n = max(f["params"], key=lambda n: math.inf if n["z"] is None else abs(n["z"]))
                row.update(param=n["param"], before=n["before"], after=n["after"], ratio=n["ratio"], z=n["z"])
            out.append(row)
    for kind in ("appeared", "disappeared"):
        out += [{"part": "stock", "id": s, "status": kind} for s in (comparison.get("stocks") or {}).get(kind, []) if s not in stocks]
    for kind in ("appeared", "disappeared"):
        out += [{"part": "loop", "id": x, "status": kind} for x in (comparison.get("loops") or {}).get(kind, [])
                if x not in loops and not set((loop_stocks or {}).get(x) or []) & stocks]
    return out


def _interp(ts: list[float], xs: list[float], t: float) -> float:
    if t <= ts[0]:
        return xs[0]
    for (t0, x0), (t1, x1) in zip(zip(ts, xs), zip(ts[1:], xs[1:])):
        if t <= t1:
            return x0 + (x1 - x0) * (t - t0) / (t1 - t0) if t1 > t0 else x1
    return xs[-1]


def stock_rows(trajectories: dict, measured: dict[str, list], horizon_s: float) -> list[dict]:
    """Each predicted stock against its measured levels over the horizon's second half: the mean
    gap from the run's central level, its standard error and ``z``; ``out`` when ``|z| ≥ Z``."""
    out = []
    ts = trajectories["t"]
    for sid, band in sorted(trajectories["stocks"].items()):
        pts = [(t, v) for t, v in measured.get(sid) or [] if horizon_s / 2 <= t <= min(horizon_s, ts[-1])]
        if len(pts) < 3:
            continue
        c = [_interp(ts, band["central"], t) for t, _ in pts]
        res = [v - x for (_, v), x in zip(pts, c)]
        n = len(res)
        mean = sum(res) / n
        var = sum((x - mean) ** 2 for x in res) / (n - 1)
        half = sum(_interp(ts, band["hi"], t) - _interp(ts, band["lo"], t) for t, _ in pts) / (2 * n)
        level_mean = sum(v for _, v in pts) / n
        se = max(math.hypot(half / Z10, math.sqrt(var)), FLOOR_SHARE * abs(level_mean), FLOOR)
        z = mean / se
        out.append({"stock": sid, "central": _r(sum(c) / n), "level": _r(level_mean), "se": _r(se), "z": _r(z, 2),
                    "readings": n, "out": abs(z) >= Z})
    return out


def outcome(edits: list[dict], levels: list[dict], unpredicted_: list[dict], stocks: list[dict] | None) -> str | None:
    """The verdict from the parts (see the table above); None while an edit waits for evidence."""
    if any(s["status"] == "waiting" for s in edits):
        return None
    if unpredicted_ or any(s["status"] == "different" for s in edits):
        return "side effect"
    if any(s["status"] == "absent" for s in edits):
        return "no effect"
    if any(s["status"] == "missed" for s in levels) or any(r["out"] for r in stocks or []):
        return "model wrong elsewhere"
    return "passed"
