"""Discovery strategies: Orchestra's own conservation step, or any of SD Lab's (``orchestra.sdlab``).

``conservation`` (``sd.discover``) finds the stocks (levels that counters balance), the flows those
counters measure, the machines behind them, and fits each flow's rate itself.

Any other strategy is SD Lab's. Conservation still runs first, because Orchestra has what SD Lab
usually has to guess: counters that measure each flow and say where it goes. Then the SD Lab
strategy works from the stocks' levels, on the time when every series involved was written, with
the other measured gauges (levels that are not stocks: a rating, a demand, the weather) as its
``inputs``, and finds the flows' equations (its richer forms: gap, linear in several stocks or
inputs, expressions, effects), hidden stocks, and regimes where it looks for them. Its flows are
then merged with the counters:

- an SD Lab flow with one counter between the same two ends gets that counter and its machine;
- several counters between the same ends (two outflows to outside look like one from the levels)
  become one flow, measured by all of them;
- an SD Lab flow no counter measures is kept, as unmeasured;
- a counter SD Lab found no flow for keeps conservation's own fit.

Rates are per the model's time unit; SD Lab's are per step, and are scaled.

Strategies are named in ``[discovery] strategy`` in ``orchestra.toml``, with ``[discovery.options]``
passed to the strategy as they are."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .discover import UNITS, discover, regular, sample
from .model import Equation, Flow, Model, Stock

CONSERVATION = "conservation"
DEFAULT = "kalman_lna"
# Orchestra's own plumbing: measured, but never a driver of anyone's flows
PLUMBING = re.compile(r"^orchestra_(core_|host_up)")
README = Path(__file__).resolve().parent.parent / "sdlab" / "discovery" / "strategies" / "README.md"


def sd_installed() -> bool:
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        return True
    except ImportError:
        return False


def available() -> dict:
    """The strategies there are, with SD Lab's one-line description of each."""
    desc = {CONSERVATION: "Orchestra's own: stocks by conservation over counters, rates fitted by the exact point-process likelihood"}
    names = [CONSERVATION]
    try:
        for line in README.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\|\s*`([a-z0-9_]+)`\s*\|\s*(.+?)\s*\|", line)
            if m:
                desc[m.group(1)] = re.sub(r"\s*\(\*research\*[^)]*\)", " (research)", m.group(2))
    except OSError:
        pass
    if sd_installed():
        from ..sdlab.discovery.strategies import names as sd_names
        names += [n for n in sd_names() if not n.startswith("_")]
    return {"sd_installed": sd_installed(), "default": DEFAULT if sd_installed() else CONSERVATION,
            "strategies": [{"name": n, "description": desc.get(n, "")} for n in names]}


def _scale(rate: dict, f: float) -> dict:
    """An SD Lab rate per step, as a rate per time unit (f steps per unit)."""
    r = dict(rate)
    form = r.get("form")
    if form == "constant" and "value" in r:
        r["value"] = r["value"] * f
    elif form == "proportional" and "k" in r:
        r["k"] = r["k"] * f
    elif form == "linear":
        r["c"] = r.get("c", 0.0) * f
        r["terms"] = [{**t, "k": t.get("k", 0.0) * f} for t in r.get("terms") or []]
    elif form == "gap" and "time" in r:
        r["time"] = r["time"] / f
    elif form == "expr":
        r["per_step_of_time_unit"] = 1.0 / f       # an expression is left per step; this says how long a step is
    return r


def _reads(rate: dict) -> list[str]:
    """What a rate reads: the stock or input of its form, its terms and its effects."""
    out = [rate["stock"]] if rate.get("stock") else []
    out += [t["stock"] for t in rate.get("terms") or [] if t.get("stock")]
    out += [e["stock"] for e in rate.get("effects") or [] if e.get("stock")]
    return list(dict.fromkeys(out))


def _numbers(rate: dict) -> dict[str, float]:
    out = {k: float(v) for k, v in rate.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for i, t in enumerate(rate.get("terms") or []):
        if isinstance(t.get("k"), (int, float)):
            out[f"k{i + 1}"] = float(t["k"])
    return out


def discover_with(dump, *, start: float, end: float, step: float, strategy: str = CONSERVATION,
                  options: dict | None = None, time_unit: str = "minute") -> Model:
    """The model the metrics imply, found with ``strategy``; how in ``model.discovery``."""
    base = discover(dump, start=start, end=end, step=step, time_unit=time_unit)
    base.discovery["strategy"] = CONSERVATION
    if strategy == CONSERVATION or not base.stocks:
        return base
    from ..sdlab.discovery.api import jsonable
    from ..sdlab.discovery.strategies import load

    began = time.perf_counter()
    fit_start = base.discovery.get("fit_start") or start
    n = max(2, int((end - fit_start) // step))
    series = sample(dump, fit_start, step, n)
    key = lambda name, labels: (name, tuple(sorted(labels.items())))
    by_ref = {key(s.name, s.labels): s for s in series}
    stock_ids = [s.id for s in base.stocks]
    levels = {s.id: by_ref[key(s.series.name, s.series.labels)].values for s in base.stocks
              if s.series and key(s.series.name, s.series.labels) in by_ref}
    # inputs: measured levels that are not stocks (and not Orchestra's plumbing), that move
    taken = {key(s.series.name, s.series.labels) for s in base.stocks if s.series}
    inputs, input_refs = {}, {}
    for s in series:
        k = key(s.name, s.labels)
        if s.counter or k in taken or PLUMBING.match(s.name) or not any(s.deltas) or not regular(s.points):
            continue
        name = "_".join([s.name, *[re.sub(r"\W+", "_", v) for kk, v in sorted(s.labels.items()) if kk not in ("project", "machine")]])
        inputs[name] = s.values
        input_refs[name] = {"name": s.name, "labels": s.labels}
    # groups: stocks joined by a measured flow can exchange material; SD Lab proposes flows only
    # within a group, so it never links stocks of different kinds (orders and customers)
    group = {s.id: s.id for s in base.stocks}
    def root(x):
        while group[x] != x:
            x = group[x]
        return x
    for bf in base.flows:
        if bf.src in group and bf.dst in group:
            group[root(bf.src)] = root(bf.dst)
    stocks_req = [{"id": s.id, "unit": s.unit, "group": root(s.id)} for s in base.stocks if s.id in levels]
    run = {"t": list(range(n + 1)), "levels": levels}
    opts = {"eras": None, **({"inputs": inputs} if inputs else {}), **(options or {})}
    r = jsonable(load(strategy)(stocks_req, run, opts))
    f = UNITS[time_unit] / step                                 # steps per time unit
    ref = lambda x: x if x in stock_ids else (f"input:{x}" if x in inputs else x)

    # merge SD Lab's flows with the counters
    by_ends: dict[tuple, list[Flow]] = {}
    for bf in base.flows:
        by_ends.setdefault((bf.src, bf.dst), []).append(bf)
    owner = {fid: m.id for m in base.machines for fid in m.attributed}
    flows, used, attributed = [], set(), {m.id: [] for m in base.machines}
    hidden: dict[str, Stock] = {}
    for sf in r.get("flows") or []:
        src, dst, rate = sf.get("from"), sf.get("to"), _scale(sf.get("rate") or {}, f)
        for end_ in (src, dst):
            if end_ and end_ not in stock_ids and end_ not in hidden:
                hidden[end_] = Stock(end_, end_.replace("_", " "), "items", None, {"hidden": True, "strategy": strategy})
        matched = by_ends.get((src, dst), [])
        if len(matched) == 1:
            fid, name, counter = matched[0].id, matched[0].name, matched[0].counter
        elif matched:
            fid, name, counter = "+".join(m.id for m in matched), " + ".join(m.name for m in matched), None
        else:
            fid = f"unmeasured:{src or 'outside'}>{dst or 'outside'}"
            name, counter = f"{(src or 'outside').replace('_', ' ')} → {(dst or 'outside').replace('_', ' ')} (unmeasured)", None
        q = {"events": sum((m.current().quality.get("events", 0.0) if m.current() else 0.0) for m in matched),
             "steps": float(n), "per_step": float(sf.get("perStep") or 0.0)}
        eq = Equation(rate.get("form", "unknown"), _numbers(rate), "discovered", f"sdlab:{strategy}", (fit_start, fit_start + n * step),
                      None, q, [ref(x) for x in _reads(rate)], rate)
        flows.append(Flow(fid, name, src, dst, counter, [eq], [m.counter for m in matched if m.counter]))
        used.update(m.id for m in matched)
        for m in matched:
            if owner.get(m.id):
                attributed[owner[m.id]].append(fid)
    for bf in base.flows:                                       # counters SD Lab found no flow for
        if bf.id not in used:
            if bf.current():
                bf.current().quality["no_flow_from_levels"] = 1.0
            flows.append(bf)
            if owner.get(bf.id):
                attributed[owner[bf.id]].append(bf.id)
    for m in base.machines:
        m.attributed = list(dict.fromkeys(attributed[m.id]))
    model = Model(base.id, base.name,
                  f"Discovered by SD Lab's {strategy} from the stocks' levels, with Orchestra's counters attached to its flows.",
                  time_unit, base.stocks + list(hidden.values()), flows, base.machines)
    model.discovery = {**base.discovery, "strategy": strategy, "sd_flows": len(r.get("flows") or []), "options": options or {}, "steps": n,
                       "inputs": input_refs, "chosen": r.get("chosen"), "method": r.get("method"),
                       "unexplained": r.get("unexplained") or {}, "hidden": [h.id for h in hidden.values()],
                       "compute_ms": round(1000 * (time.perf_counter() - began))}
    return model
