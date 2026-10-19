"""From a cached table to a case's series: what one real case measures.

A series is {"t": [0, 1, ..., n-1] (one step per sample), "time": the samples' own times (a month,
a day, a year), "levels": {stock: [level per sample]}, "injections": [{t, stock, amount}] (announced
additions, at the start of step t: between samples t-1 and t), "flows": {"A->B": [amount moved in
the step to sample i; None at i = 0]} (only BLS measures flows)}.

A case names its source and a selector (`real: {source, select}`); `series(source, select)` is the
only way data reach a case. Each loader keeps the longest run of consecutive samples (one step
apart) in which every stock is measured: no filling in, and t stays one step per sample.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict

from . import sources

MOVES = ("EU", "EN", "UE", "UN", "NE", "NU")        # BLS's six gross flows between the labour force states


def series(source: str, select: dict) -> dict:
    if source == "bls":
        return bls(select)
    if source == "gauseR":
        return gauser(select)
    if source == "pomp":
        return bsflu(select)
    if source == "owid":
        return owid(select)
    raise ValueError(f"unknown real source {source!r}")


def _longest_run(times: list, present: list[bool], step: float) -> tuple[int, int]:
    """[i, j) of the longest run of present samples whose times are `step` apart."""
    best, start = (0, 0), None
    for i in range(len(times) + 1):
        ok = i < len(times) and present[i] and (start is None or abs(times[i] - times[i - 1] - step) < 1e-6 * max(1, step))
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = i if i < len(times) and present[i] else None
    return best


# ---- BLS: labour force levels and flows ----

def bls(select: dict) -> dict:
    """E, U, N (thousands, 16+, seasonally adjusted) from `first` to `last` (YYYY-MM), the six gross
    flows, and BLS's January population-control adjustments as announced injections."""
    rows = [r for r in sources.bls_rows() if select.get("first", "0000") <= r["month"] <= select.get("last", "9999")]
    ids = ("E", "U", "N")
    for a, b in zip(rows, rows[1:]):
        if _month_index(b["month"]) != _month_index(a["month"]) + 1:
            raise ValueError(f"BLS months not consecutive: {a['month']} -> {b['month']} (choose first/last inside a run)")
    if any(r[x] is None for r in rows for x in ids) or any(r[m] is None for r in rows[1:] for m in MOVES):
        raise ValueError("BLS rows with missing values inside the window")
    n = len(rows)
    flows = {f"{m[0]}->{m[1]}": [None] + [rows[i][m] for i in range(1, n)] for m in MOVES}
    # what leaves each state for outside the 16+ population (BLS's flows from a state add up to its
    # level the month before; the rest left the population) and what enters it ("other" inflows)
    other_in = {x: [None] + [rows[i][f"O{x}"] for i in range(1, n)] for x in ids}
    other_out = {x: [None] + [rows[i - 1][x] - sum(rows[i][f"{x}{y}"] for y in ids) for i in range(1, n)] for x in ids}
    flows.update({f"outside->{x}": other_in[x] for x in ids})
    flows.update({f"{x}->outside": other_out[x] for x in ids})
    # January: BLS introduces new population controls (the footnote "Data affected by changes in
    # population controls"); the jump shows as excess "other" flows. Announced as an injection: the
    # month's net other flow minus the median of the other months' (relative to the level, for outflows).
    jan = [i for i in range(1, n) if rows[i]["month"].endswith("-01")]
    rest = [i for i in range(1, n) if i not in jan]
    injections = []
    for x in ids:
        med_in = statistics.median(other_in[x][i] for i in rest)
        med_out = statistics.median(other_out[x][i] / rows[i - 1][x] for i in rest)
        for i in jan:
            amount = (other_in[x][i] - med_in) - (other_out[x][i] - med_out * rows[i - 1][x])
            if abs(amount) >= 1:
                injections.append({"t": i, "stock": x, "amount": round(amount, 1)})
    injections.sort(key=lambda j: (j["t"], j["stock"]))
    return {"t": list(range(n)), "time": [r["month"] for r in rows], "time_unit": "month",
            "levels": {x: [r[x] for r in rows] for x in ids}, "injections": injections, "flows": flows}


def _month_index(m: str) -> int:
    y, mo = m.split("-")
    return int(y) * 12 + int(mo) - 1


# ---- gauseR: lab populations ----

def gauser(select: dict) -> dict:
    """select: {table, time (column), step (time between samples), stocks: {id: {value: column, where: {column: value}}},
    injections?: {flag: column, when: value, amounts: {stock: amount}}, at_least?: points}."""
    rows = sources.table("gauseR", select["table"])
    tcol, step = select["time"], float(select.get("step", 1))
    per: dict[str, dict[float, list[float]]] = {}
    for sid, spec in select["stocks"].items():
        got: dict[float, list[float]] = defaultdict(list)
        for r in rows:
            if all(_same(r.get(k), v) for k, v in (spec.get("where") or {}).items()) and r.get(tcol) is not None and r.get(spec["value"]) is not None:
                got[round(float(r[tcol]) / step) * step].append(float(r[spec["value"]]))
        per[sid] = {t: sum(v) / len(v) for t, v in got.items()}      # a time digitised twice: the mean
    times = sorted(set().union(*[set(v) for v in per.values()]))
    present = [all(t in per[s] for s in per) for t in times]
    i, j = _longest_run(times, present, step)
    times = times[i:j]
    flags = set()
    inj = select.get("injections")
    if inj:
        for r in rows:
            if _same(r.get(inj["flag"]), inj["when"]) and r.get(tcol) is not None:
                flags.add(round(float(r[tcol]) / step) * step)
    # immigration flagged at a sample shows in the next sample: an injection at the start of that step
    injections = [{"t": k + 1, "stock": s, "amount": float(a)} for k, tm in enumerate(times[:-1]) if tm in flags
                  for s, a in (inj or {}).get("amounts", {}).items()]
    return {"t": list(range(len(times))), "time": times, "time_unit": select.get("unit", "day"),
            "levels": {s: [per[s][t] for t in times] for s in per}, "injections": injections}


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


# ---- pomp: the 1978 boarding-school influenza ----

def bsflu(select: dict) -> dict:
    rows = sorted(sources.table("pomp", "bsflu"), key=lambda r: r["day"])
    return {"t": list(range(len(rows))), "time": [int(r["day"]) for r in rows], "time_unit": "day",
            "levels": {"B": [float(r["B"]) for r in rows], "C": [float(r["C"]) for r in rows]}, "injections": []}


# ---- OWID: technology adoption ----

def owid(select: dict) -> dict:
    """select: {entity}. A = share of households with it (%), N = 100 - A; the longest run of consecutive years."""
    rows = sources.table("owid", "technology-adoption")
    col = next(k for k in rows[0] if k not in ("entity", "year", "code"))
    by = {int(r["year"]): float(r[col]) for r in rows if r["entity"] == select["entity"] and r[col] not in ("", None)}
    years = sorted(by)
    i, j = _longest_run(years, [True] * len(years), 1)
    years = years[i:j]
    a = [by[y] for y in years]
    return {"t": list(range(len(years))), "time": years, "time_unit": "year",
            "levels": {"N": [round(100 - x, 6) for x in a], "A": a}, "injections": []}


def series_sha(s: dict) -> str:
    """The series' fingerprint: t, levels, injections and measured flows (canonical JSON, levels to 6 decimals)."""
    body = {"t": s["t"], "levels": {k: [round(float(x), 6) for x in v] for k, v in s["levels"].items()},
            "injections": s.get("injections") or [], "flows": {k: [None if x is None else round(float(x), 6) for x in v] for k, v in (s.get("flows") or {}).items()}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
