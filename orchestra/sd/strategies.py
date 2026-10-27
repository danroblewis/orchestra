"""Discovery strategies: Orchestra's own conservation step, or any of SD Lab's (``orchestra.sdlab``).

``conservation`` (``sd.discover``) finds the stocks (levels that counters balance), the flows those
counters measure, the machines behind them, and fits each flow's rate itself.

Any other strategy is SD Lab's. Conservation still runs first, because Orchestra has what SD Lab
usually has to guess: counters that measure each flow and say where it goes. The SD Lab strategy
is then given only the stocks counters do not balance exactly (``handed``): those whose balance
leaves a residual, and the levels no counters balance at all that are stocks by their fitted net
flow (``sd.netflow``). Where counters balance every stock exactly it does not run: nothing is left
to explain, and a strategy that ignores what is known invents flows there. It works on a grid no
finer than the stocks it is given are read at (``sd.resolution``), from their levels, on the time
when every series involved was written, with the
other measured gauges (``sd.inputs``: levels that are not stocks or flags, one per machine) as its
``inputs``, and with the measured moves handed to it as what is already **known** about each step
(SD Lab's ``known`` option: the counters' changes per stock per step), so a strategy that reads it
explains only the residual: hidden stocks, unmeasured inflows and drains, inputs that drive them,
in its richer forms. Whether it did is read off its answer with SD Lab's own residual
(``explains_residual``): its flows fit the levels better with the known changes beside them, or
without. Its flows are then merged with the counters:

- when they describe the residual, every one is a flow no counter measures, kept as unmeasured
  (even between two ends a counter joins: the counter's flow is another), and every counter
  keeps conservation's own fit;
- otherwise they describe the whole change: an SD Lab flow with one counter between the same two
  ends gets that counter and its machine, unless the counter has fewer than ``MIN_EVENTS`` events
  (conservation's constant stays); several counters between the same ends (two outflows to
  outside look like one from the levels) become one flow, measured by all of them; a counter SD
  Lab found no flow for keeps conservation's own fit;
- either way, several SD Lab flows between the same ends (one per term it found) are one flow
  with one rate of several terms (``sd.rates.combine``), so every flow id is used once, and an
  unmeasured flow is kept only where it can carry anything: a stock whose counters balance it
  exactly (in ``FLAG_EXACT`` of the steps) has no unexplained change, and an unmeasured flow into
  or out of it is dropped and recorded (a strategy that ignores ``known`` invents them).

Its flows into or out of a stock with a fitted net flow take the place of conservation's (whose
ids stay in the stock's evidence, ``conservation_fit``), as SD Lab's richer forms of the same net
flow. Rates are per the model's time unit; SD Lab's are per step, and are scaled (``sd.rates``).

Strategies are named in ``[discovery] strategy`` in ``orchestra.toml``, with ``[discovery.options]``
passed to the strategy as they are. A ``deadline`` (seconds) becomes the time budget the
``combined`` family and ``kalman_lna`` read (``budget``, ``cap``, ``kalman_budget``), unless the
options already set them; strategies without a budget ignore it."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .bounded import Late, run_jobs
from .discover import FLAG_EXACT, MIN_EVENTS, UNITS, discover
from .inputs import offered_inputs
from .model import Equation, Flow, Model, Stock
from .rates import combine, numbers, reads, scale
from .resolution import steps_of
from .series import sample, series_key, sum_instances

CONSERVATION = "conservation"
DEFAULT = "kalman_lna"
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


def run_strategy(strategy: str, stocks: list[dict], run: dict, opts: dict) -> dict:
    """SD Lab's strategy on the request, its result JSON-safe."""
    from ..sdlab.discovery.api import jsonable
    from ..sdlab.discovery.strategies import load

    return jsonable(load(strategy)(stocks, run, opts))


def explains_residual(flows: list[dict], stocks: list[dict], run: dict, known: dict, inputs: dict) -> bool:
    """Whether the strategy's flows describe what the known changes leave (it read ``known``) or
    the whole change (it did not): by SD Lab's own residual per stock (drift and wobble), with the
    known changes run beside its flows and without. No flows at all, with changes known, is the
    residual explained: nothing remained."""
    if not known:
        return False
    ids = [s["id"] for s in stocks]
    flows = [f for f in flows if (f.get("from") in ids or f.get("from") is None) and (f.get("to") in ids or f.get("to") is None)]
    if not flows:
        return True
    from ..sdlab.discovery.api import unexplained
    from ..sdlab.discovery.matrix import known_flows

    def score(fl):
        u = unexplained(fl, stocks, run, inputs or None)
        return sum(abs(v["drift"]) + v["wobble"] for v in u.values())
    return score(flows + known_flows(known, ids, run["t"])) <= score(flows)


def budget_options(deadline: float | None) -> dict:
    """The time budget the strategies that read one are given for a deadline: the ``combined``
    family's whole budget and per-specialist cap, kalman_lna's filter budget."""
    if not deadline or deadline <= 0:
        return {}
    return {"budget": round(0.5 * deadline, 1), "cap": round(min(90.0, 0.25 * deadline), 1), "kalman_budget": round(0.5 * deadline, 1)}


def known_changes(base: Model, by_key: dict, n: int) -> dict[str, list[float]]:
    """What is already known about each stock's change at each of the ``n + 1`` grid times: the
    sum of its balance's counters, signed, that arrived in the step ending there (nothing at the
    first)."""
    out = {}
    for s in base.stocks:
        terms = [(by_key.get(b["series"]), b["sign"]) for b in s.evidence.get("balance") or []]
        if not terms or any(c is None for c, _ in terms):
            continue
        out[s.id] = [0.0] + [float(sum(sign * c.deltas[i] for c, sign in terms)) for i in range(n)]
    return out


def handed(base: Model) -> list[Stock]:
    """The stocks an SD Lab strategy is given: those whose counters do not balance them exactly
    (in ``FLAG_EXACT`` of the steps), and those no counters balance at all (``sd.netflow``). Where
    counters balance a stock exactly nothing is left to explain, and a strategy that ignores the
    known changes invents flows there."""
    return [s for s in base.stocks if s.series is not None and ("net_flow" in s.evidence or s.evidence.get("exact_steps", 0.0) < FLAG_EXACT)]


def read_by(base: Model, ids: list[str], inputs: dict[str, list[float]]) -> dict[str, list[float]]:
    """The inputs the model's flows into or out of these stocks read: what a strategy refitting a
    level's net flow is offered, rather than every measured gauge (with a hundred, a strategy takes
    minutes to find what conservation's fit already chose)."""
    names = {x[6:] for f in base.flows if f.src in ids or f.dst in ids for x in (f.current().inputs if f.current() else [])
             if x.startswith("input:")}
    return {k: v for k, v in inputs.items() if k in names}


def discover_with(dump, *, start: float, end: float, step: float, strategy: str = CONSERVATION,
                  options: dict | None = None, time_unit: str = "minute", deadline: float | None = None,
                  kinds: dict | None = None) -> Model:
    """The model the metrics imply, found with ``strategy``; how in ``model.discovery``. ``kinds``
    are the series' declared kinds (``sd.series.Declared``), by series key."""
    base = discover(dump, start=start, end=end, step=step, time_unit=time_unit, kinds=kinds)
    base.discovery["strategy"] = CONSERVATION
    if strategy == CONSERVATION or not base.stocks:
        return base
    given = handed(base)
    if not given:
        base.discovery.update(strategy=strategy, sdlab="not run: the counters balance every stock exactly, so nothing is left to explain")
        return base
    began = time.perf_counter()
    fit_start = base.discovery.get("fit_start") or start
    # on a grid no finer than the slowest-read of the stocks handed over allows: everything involved is that slow
    res = base.discovery.get("resolution") or {}
    k = min(steps_of(res.get(series_key(st.series.name, st.series.labels), {}).get("resolution_s"), step) for st in given)
    coarse = step * k
    n = max(2, int((end - fit_start) // coarse))
    series, _ = sum_instances(sample(dump, fit_start, coarse, n, kinds))
    by_key = {s.key: s for s in series}
    stock_ids = [s.id for s in given]
    stock_keys = {series_key(s.series.name, s.series.labels): s.id for s in base.stocks if s.series}
    levels = {sid: by_key[key].values for key, sid in stock_keys.items() if key in by_key and sid in stock_ids}
    inputs, input_refs = offered_inputs(series, set(stock_keys), base.discovery.get("left_out") or {})
    known = known_changes(Model(base.id, base.name, stocks=given), by_key, n)
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
    by_group: dict[str, list[Stock]] = {}
    for st in given:
        if st.id in levels:
            by_group.setdefault(root(st.id), []).append(st)
    jobs, parts = [], []
    for members in by_group.values():
        ids = [st.id for st in members]
        req = [{"id": st.id, "unit": st.unit, "group": root(st.id)} for st in members]
        run_g = {"t": list(range(n + 1)), "levels": {sid: levels[sid] for sid in ids}}
        known_g = {sid: known[sid] for sid in ids if sid in known}
        inputs_g = inputs if any("net_flow" not in st.evidence for st in members) else read_by(base, ids, inputs)
        opts = {"eras": None, **({"inputs": inputs_g} if inputs_g else {}), **({"known": known_g} if known_g else {}),
                **budget_options(deadline / len(by_group) if deadline else None), **(options or {})}
        jobs.append((strategy, req, run_g, opts))
        parts.append((ids, req, run_g, known_g, inputs_g))
    try:
        answers = run_jobs(jobs, deadline)
    except Late as e:
        base.discovery.update(strategy=strategy, sdlab=f"{e}: conservation's fits are kept", handed=[st.id for st in given])
        return base
    sd_flows, residual_of, chosen, methods, unexplained, across = [], {}, [], [], {}, []
    for (ids, req, run_g, known_g, inputs_g), r in zip(parts, answers):
        mine = [sf for sf in r.get("flows") or [] if all(e is None or e in ids or e not in stock_ids for e in (sf.get("from"), sf.get("to")))]
        across += [x for x in ({"from": sf.get("from"), "to": sf.get("to"), "why": "it joins stocks no measured flow joins"}
                               for sf in r.get("flows") or [] if sf not in mine) if x not in across]
        residual = explains_residual(mine, req, run_g, known_g, inputs_g)
        for sf in mine:
            residual_of[(sf.get("from"), sf.get("to"))] = residual
        sd_flows += mine
        chosen.append(r.get("chosen"))
        methods.append(r.get("method"))
        unexplained.update(r.get("unexplained") or {})
    f = UNITS[time_unit] / coarse                               # steps per time unit
    ref = lambda x: x if x in {st.id for st in base.stocks} else (f"input:{x}" if x in inputs else x)
    exact = {s.id for s in base.stocks if s.evidence.get("exact_steps", 0.0) >= FLAG_EXACT}

    # merge SD Lab's flows with the counters
    by_ends: dict[tuple, list[Flow]] = {}
    for bf in base.flows:
        if "net_flow_of" not in bf.evidence:                   # a counter's flow, which SD Lab's may be matched to
            by_ends.setdefault((bf.src, bf.dst), []).append(bf)
    net = {st.id for st in given if "net_flow" in st.evidence}
    replaced = {e for sf in sd_flows for e in (sf.get("from"), sf.get("to")) if e in net}
    sd_by_ends: dict[tuple, list[dict]] = {}
    for sf in sd_flows:
        sd_by_ends.setdefault((sf.get("from"), sf.get("to")), []).append(sf)
    owner = {fid: m.id for m in base.machines for fid in m.attributed}
    flows, used, attributed, dropped = [], set(), {m.id: [] for m in base.machines}, across
    hidden: dict[str, Stock] = {}
    for (src, dst), sfs in sd_by_ends.items():
        rate = scale(combine([sf.get("rate") or {} for sf in sfs]), f)
        matched = [] if residual_of[(src, dst)] else by_ends.get((src, dst), [])
        events = sum((m.current().quality.get("events", 0.0) if m.current() else 0.0) for m in matched)
        if matched and events < MIN_EVENTS:
            continue                                            # too few events to carry a form: conservation's constant stays
        if not matched and (src in exact or dst in exact):
            dropped.append({"from": src, "to": dst, "why": "no counter measures it, and its stock's counters balance it exactly"})
            continue
        for end_ in (src, dst):
            if end_ and end_ not in stock_ids and end_ not in hidden:
                hidden[end_] = Stock(end_, end_.replace("_", " "), "items", None, {"hidden": True, "strategy": strategy})
        if len(matched) == 1:
            fid, name, counter = matched[0].id, matched[0].name, matched[0].counter
        elif matched:
            fid, name, counter = "+".join(m.id for m in matched), " + ".join(m.name for m in matched), None
        else:
            fid = f"unmeasured:{src or 'outside'}>{dst or 'outside'}"
            name, counter = f"{(src or 'outside').replace('_', ' ')} → {(dst or 'outside').replace('_', ' ')} (unmeasured)", None
        if not matched and (src in net or dst in net):          # what it is judged on: the changes of the level it moves
            events = float(max(base.stock(e).evidence["net_flow"]["changes"] for e in (src, dst) if e in net))
        q = {"events": events, "steps": float(n), "per_step": float(sum(sf.get("perStep") or 0.0 for sf in sfs))}
        eq = Equation(rate.get("form", "unknown"), numbers(rate), "discovered", f"sdlab:{strategy}", (fit_start, fit_start + n * coarse),
                      None, q, [ref(x) for x in reads(rate)], rate)
        flows.append(Flow(fid, name, src, dst, counter, [eq], [m.counter for m in matched if m.counter],
                          matched[0].evidence if len(matched) == 1 else {}))
        used.update(m.id for m in matched)
        for m in matched:
            if owner.get(m.id):
                attributed[owner[m.id]].append(fid)
    for bf in base.flows:                                       # counters SD Lab found no flow for
        if bf.evidence.get("net_flow_of") in replaced:          # a net flow SD Lab found again in its own forms
            base.stock(bf.evidence["net_flow_of"]).evidence.setdefault("conservation_fit", []).append(bf.id)
            continue
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
    one = lambda xs: xs[0] if len(xs) == 1 else xs
    model.discovery = {**base.discovery, "strategy": strategy, "sd_flows": len(sd_flows), "options": options or {}, "steps": n,
                       "inputs": input_refs, "known": sorted(known), "dropped": dropped, "chosen": one(chosen), "method": one(methods),
                       "sdlab_explains": one(["residual" if residual_of.get((sf.get("from"), sf.get("to"))) else "whole change"
                                              for sf in sd_flows[:1]] or ["residual" if known else "whole change"]),
                       "unexplained": unexplained, "hidden": [h.id for h in hidden.values()], "groups": len(jobs),
                       "handed": stock_ids, "sdlab_step": coarse,
                       "deadline_s": deadline, "compute_ms": round(1000 * (time.perf_counter() - began))}
    return model
