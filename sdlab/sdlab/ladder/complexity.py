"""How complicated a model is: one count, applied the same way to a case's true model and to a found
model, so a leaderboard can tell a strategy that recovers the truth from one that adds too much.

**Complexity** = flows + numbers, where the numbers are everything one has to write down to give
each flow's rate over the run:

- **flows**: 1 per flow (a found hidden stock written as one flow with `via` is 2 flows: into the
  stock and out of it);
- **terms**: the numbers of each flow's rate in its first piece: constant 1, proportional 1, gap 2
  (goal, time), linear 1 per stock it reads plus 1 for a non-zero constant (zero terms are not
  written), available 0; a `via` delay is 1 more;
- **pieces**: a rate that changes over the run (a found flow's outside inflow pieces or byTime
  segments; the truth's schedule laid out over the run) costs the numbers of every piece after the
  first; consecutive pieces with the same rate are one piece. A found inflow in 9 pieces is 9
  numbers, not 1;
- **other**: each effect's numbers (linear: normal, min, max = 3; table: 2 per point), 1 per
  co-flow use, 1 for a ratio other than 1, and 1 per stock the model has that is not measured
  (a hidden or inferred stock: its level is one more thing to know).

The truth is counted **on the run**, as a found model would have to write it: its schedule is laid
out over the steps the data covers (steps 2..N, where the found models' pieces start), so a periodic
schedule on a long run is as many pieces as it has changes in the run. A found model that writes the
true equations therefore counts exactly as much as the truth (extra 0).

Per result: **extra** = found - true (by part: flows, terms, pieces, other), and **ratio** =
found / true. The **Occam score** of a result trades accuracy against excess complexity:
fit x parsimony, where fit is 1 for a pass or an equivalent model, else the share of true numbers
right (right / of), and 0 for an error or timeout; and parsimony = true / found, at most 1 (the
share of the found model's complexity the truth needs). A model twice as complicated as the truth
keeps half its fit, one 10% over keeps 91%; a model simpler than the truth is not rewarded (its fit
already pays for what it misses).

Counting needs the found flows, which are large; `for_results` counts each stored result once and
keeps the count by result id (a stored result never changes), so the summary stays fast.
"""

from __future__ import annotations

import json
import math

from ..skill import truth_by_time
from . import cases as casemod
from . import store

PARTS = ("flows", "terms", "pieces", "other")


def _rate_numbers(rate: dict | None) -> int:
    r = rate or {}
    form = r.get("form")
    if form in ("constant", "proportional"):
        return 1
    if form == "gap":
        return 2
    if form == "linear":
        ks: dict = {}
        for x in r.get("terms") or []:
            ks[x.get("stock")] = ks.get(x.get("stock"), 0.0) + float(x.get("k") or 0)
        return int(bool(float(r.get("c") or 0))) + sum(1 for k in ks.values() if k)
    if form == "available":
        return 0
    return 1


def _readers(rate: dict | None) -> set:
    r = rate or {}
    return {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}


def _effect_numbers(e: dict) -> int:
    shape = e.get("shape")
    if shape == "linear":
        return 3
    if shape == "table":
        return 2 * len(e.get("points") or [])
    return sum(1 for k, v in e.items() if k not in ("stock", "shape") and isinstance(v, (int, float)))


def _pieces(flow: dict) -> list[int] | None:
    """The numbers of each piece of a rate that changes over the run (consecutive equal pieces
    merged), or None for a rate that holds still."""
    if flow.get("inflow"):
        vals = [g.get("value") for g in flow["inflow"]]
        return [1 for i, v in enumerate(vals) if i == 0 or v != vals[i - 1]]
    if flow.get("byTime"):
        rates = [g.get("rate") for g in flow["byTime"]]
        return [_rate_numbers(r) for i, r in enumerate(rates) if i == 0 or r != rates[i - 1]]
    return None


def count(flows: list[dict], measured: set) -> dict:
    """{flows, terms, pieces, other, total} for a model's flows; `measured`: the measured stocks."""
    out = dict.fromkeys(PARTS, 0)
    hidden = set()
    for f in flows or []:
        via = bool(f.get("via"))
        out["flows"] += 2 if via else 1
        segs = _pieces(f)
        if segs:
            out["terms"] += segs[0]
            out["pieces"] += sum(segs[1:])
        else:
            out["terms"] += _rate_numbers(f.get("rate"))
        out["terms"] += 1 if via else 0
        out["other"] += sum(_effect_numbers(e) for e in f.get("effects") or [])
        out["other"] += len(f.get("uses") or [])
        out["other"] += 1 if float(f.get("ratio") or 1) != 1 else 0
        refs = {f.get("from"), f.get("to")} | _readers(f.get("rate"))
        refs |= {e.get("stock") for e in (f.get("effects") or []) + (f.get("uses") or [])}
        for g in f.get("byTime") or []:
            refs |= _readers(g.get("rate"))
        hidden |= {s for s in refs if s and s not in measured}
        if via:
            hidden.add(("via", f.get("from"), f.get("to")))
    out["other"] += len(hidden)
    out["total"] = sum(out[k] for k in PARTS)
    return out


def measured(case: dict) -> set:
    return {s["id"] for s in case["model"]["stocks"] if s.get("measured", True)}


_truths: dict = {}


def of_truth(case: dict, variant_name: str) -> dict:
    """The true model's complexity on a variant's run (its schedule laid out over steps 2..N)."""
    key = (case["id"], case["hash"], variant_name)
    if key not in _truths:
        model = casemod.truth_model(case, variant_name)
        steps = int(casemod.variant(case, variant_name)["steps"])
        flows = truth_by_time(model, list(range(2, steps + 1)))[0] if model.get("schedule") else model["flows"]
        _truths[key] = count(flows, measured(case))
    return _truths[key]


def compare(true: dict, found: dict) -> dict:
    """{true, found, extra, ratio, by: {part: found - true}}."""
    return {"true": true["total"], "found": found["total"], "extra": found["total"] - true["total"],
            "ratio": found["total"] / true["total"] if true["total"] else None,
            "by": {k: found[k] - true[k] for k in PARTS}}


def of_result(row: dict, found: list[dict] | None = None, case: dict | None = None) -> dict | None:
    """The complexity comparison for one result (its found flows from `found` or the row), or None
    when it found nothing (error, timeout) or its case or variant is gone."""
    flows = found if found is not None else row.get("found")
    if flows is None or row.get("status") in ("error", "timeout"):
        return None
    try:
        case = case or casemod.load(row["case"])
        true = of_truth(case, row["variant"])
    except (KeyError, ValueError, FileNotFoundError):
        return None
    return compare(true, count(flows, measured(case)))


def attach(row: dict | None) -> dict | None:
    """The row with `complexity` added (a row that carries its found flows)."""
    if row is not None:
        row["complexity"] = of_result(row)
    return row


_by_id: dict = {}


def for_results(rows: list[dict]) -> dict[int, dict | None]:
    """{result id: comparison} for stored results (rows without found flows), each counted once."""
    where = str(store.path())
    todo = [r for r in rows if (where, r["id"]) not in _by_id]
    if todo:
        found = store.found_flows([r["id"] for r in todo])
        cs = {}
        for c in {r["case"] for r in todo}:
            try:
                cs[c] = casemod.load(c)
            except Exception:                 # a case that is gone (or does not load now): not counted, tried again next time
                pass
        for r in todo:
            raw = found.get(r["id"])
            if r["case"] in cs:
                _by_id[(where, r["id"])] = of_result(r, json.loads(raw), cs[r["case"]]) if raw else None
    return {r["id"]: _by_id.get((where, r["id"])) for r in rows}


def occam(status: str | None, right, of, cx: dict | None) -> float | None:
    """The Occam score of a result (see the module docstring); None when it was never run, or its
    found model could not be counted."""
    if status is None:
        return None
    if status in ("error", "timeout"):
        return 0.0
    if cx is None:
        return None
    fit = 1.0 if status in ("pass", "equivalent") else (right / of if of else 0.0)
    return fit * min(1.0, cx["true"] / cx["found"]) if cx["found"] else fit


def cell(row: dict | None, cx: dict | None) -> dict:
    """The complexity numbers a matrix cell carries."""
    if row is None:
        return {}
    out = {"occam": occam(row["status"], (row.get("scores") or {}).get("right"), (row.get("scores") or {}).get("of"), cx)}
    if cx:
        out.update(cx_true=cx["true"], cx_found=cx["found"], cx_extra=cx["extra"],
                   cx_ratio=cx["ratio"] if cx["ratio"] is not None and math.isfinite(cx["ratio"]) else None,
                   cx_by=[cx["by"][k] for k in PARTS])
    return out
