"""Import a system dynamics model (Vensim .mdl, XMILE .xmile/.stmx) as an SD Lab ladder case, through
PySD's parser; and check the import by simulating both.

    uv run --with pysd --with sympy python -m sdlab.ladder.pysd_import MODEL.mdl     # the case body, or what blocks it

    conv = convert(path)          # Conversion: .text (YAML: stocks, flows, dt, inputs) or .blocked [(feature, where)]
    eq = equivalent(conv)         # Equivalence: .ok, .error {stock: max |difference|}, .reason

pysd and sympy are optional (not dependencies of SD Lab): this module imports them only when called.

How a model becomes a case (sdlab/ladder/canonical/: read.py reads, match.py matches rates):

1. PySD parses the file; every auxiliary and constant is inlined into the flows, so each flow's rate
   is an expression in the stocks and TIME. A flow subtracted from A and added to B is a move A -> B.
2. Time. A recorded step is one model time unit when the model's TIME STEP is 1/n (the case gets
   `dt: 1/n`), else one TIME STEP (rates are then per TIME STEP). Rates become per recorded step.
3. A flow whose whole rate is DELAY1/DELAY3(x, T) fills its stock through a material delay: with
   the flow that drains x from A it becomes `A -> B: delay3(x, T, initial=...)`, else
   `outside -> B: delay3(...)`. A DELAY anywhere else is information: DELAY1 is SMOOTH and DELAY3 is
   SMOOTH3 exactly; SMOOTH/SMOOTH3 of one stock or input become `smooth(Y, T, initial=...)`. A
   DELAY N / SMOOTH N of another whole order n is written out as the case format compiles delay3 and
   smooth3: n hidden stocks (`<flow>_d1..dn` in a material chain at n / T each; `SM_k_1..n` stages
   with exact flows, the last read by the rate).
4. Every part of a rate that reads only TIME (STEP, PULSE, PULSE TRAIN, RAMP, SIN, a lookup of
   time, ...) is an outside driver: a measured input (`inputs:`), as a formula when SD Lab's input
   terms give PySD's values at every Euler step, else as one value per recorded step (then a
   recorded step is one Euler step).
5. Each rate is matched onto constant, proportional, gap, linear and effects (match.py). What does
   not match is reported with the feature SD Lab lacks.

Since queue item 2d (2026-10-19; the engine's expressions, signed stocks and two-way flows):

6. A rate that has no linear form (a ratio of stocks, MIN / MAX, SQRT, a power, IF THEN ELSE, EXP, ABS,
   XIDZ / ZIDZ, trigonometry, a lookup of an expression, a nonlinear polynomial) is written as an
   expression (match.expr_text). A flow whose rate goes negative on PySD's run (or is written
   negative) is two-way (`A <-> B`); a stock that starts or goes below 0 on PySD's run is `signed`.
   When SD Lab's floor still makes the runs differ (an outflow that empties a stock within a step, a
   drain faster than a step), convert_checked marks the stocks the floor emptied `signed` (no floor,
   as Vensim has none) and checks again.
7. DELAY FIXED: its order is fixed at the start (read.py); of a function of TIME it is a measured
   input, as a whole rate of anything else `delay_fixed(x, time, initial=...)` (a pipe of hidden
   stages). A material DELAY out of a measured stock (Vensim's pipeline stock, `Population =
   INTEG(Births - DELAY3(Births, T))`) is read as the information delay it computes, the SMOOTH of the
   same order (exactly equal). TREND and FORECAST are a SMOOTH and an expression (read.py).

A model is accepted only if PySD's own run (Euler at the model's TIME STEP) and SD Lab's engine with no
noise give the same levels at every recorded step (`equivalent`): within 1e-4 + 1e-7 x the stock's
largest level (the engine records levels rounded to 4 decimals). Where they differ, the reason is named
when it can be: a stock that goes negative in PySD, or a flow whose rate goes negative (SD Lab floors
every rate and level at 0).

Arrays, macros and external data are read away by the reader (canonical/read.py): one stock or flow
per element of a subscripted variable, macros inlined, data read through PySD into numbers, lookups
and measured inputs.

A model with no stocks (most of SDXorg/test-models' one-function tests) is wrapped: each auxiliary
nothing else reads gets an accumulator stock `acc_<name> = INTEG(aux)`, so the function under test
becomes a flow.
"""

from __future__ import annotations

import math
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ATOL, RTOL = 1e-4, 1e-7
F_TWO_WAY = "a two-way flow (a rate goes negative)"
F_NEG_STOCK = "a stock that goes negative"
F_EMPTIED = "an outflow larger than the stock within one step (the engine's floor ignores the step's inflows)"
F_FAST = "a drain faster than one step (k x dt > 1: the engine's floor caps it at the level, Euler overshoots)"


@dataclass
class Conversion:
    path: Path
    text: str | None = None                       # the case body (YAML), when nothing blocks it
    blocked: list = field(default_factory=list)   # [(feature, where)]
    notes: list = field(default_factory=list)
    stocks: dict = field(default_factory=dict)    # SD Lab id -> the model's name
    scale: float = 1.0                            # model time units per recorded step
    dt: float = 1.0                               # SD Lab sub-step (in recorded steps)
    steps: int = 0                                # recorded steps in the model's own run
    wrapped: bool = False                         # accumulators added (a model with no stocks)
    uses_values: bool = False                     # an input given as values, not a formula
    two_way: set = field(default_factory=set)     # the model's flows (keys) written two-way (2d)
    drivers: list = field(default_factory=list)   # the functions of TIME made measured inputs (STEP, PULSE, LOOKUP, ...)
    parts: dict | None = None                     # dt, stocks, inputs, flows: what render() writes
    pysd_levels: dict = field(default_factory=dict)   # SD Lab id -> PySD's level at t0 + k x scale, k = 0..steps
    euler: dict = field(default_factory=dict)         # SD Lab id -> PySD's level at every Euler step
    model: object = None

    @property
    def features(self) -> list[str]:
        """The missing features, each once, in the order met."""
        return list(dict.fromkeys(f for f, _ in self.blocked))


@dataclass
class Equivalence:
    ok: bool
    error: dict = field(default_factory=dict)
    reason: str = ""


def _scale(dt: float) -> tuple[float, float]:
    """(model time per recorded step, SD Lab dt)."""
    if dt <= 0:
        return 1.0, 1.0
    n = round(1 / dt)
    if dt <= 1 and n >= 1 and abs(n * dt - 1) < 1e-9:
        return 1.0, 1.0 / n
    return dt, 1.0


def _flow_id(name: str, taken: set[str]) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower() or "flow"
    if s[0].isdigit():
        s = "f_" + s
    out, i = s, 2
    while out in taken:
        out, i = f"{s}_{i}", i + 1
    taken.add(out)
    return out


def pysd_run(path: Path, columns: list[str], t0: float, final: float, dt: float, folder: bool = False) -> dict:
    """PySD's run (Euler at the model's TIME STEP) at every Euler step: {column: [values]} (folder: copy
    the model's whole folder, for a model that reads data files beside it)."""
    import numpy as np
    import pysd

    from .canonical.external import copy_folder

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / path.name
        if folder:
            copy_folder(path, Path(d))
        else:
            shutil.copy(path, p)
        model = pysd.read_vensim(str(p)) if path.suffix.lower() == ".mdl" else pysd.read_xmile(str(p))
        n = math.floor((final - t0) / dt + 1e-9)
        times = t0 + dt * np.arange(n + 1)
        df = model.run(return_timestamps=times, return_columns=columns, progress=False)
        return {c: [float(x) for x in df[c].to_numpy()] for c in columns}


def convert_checked(path) -> tuple[Conversion, Equivalence | None]:
    """convert, then equivalent; when the runs differ, SD Lab's floor may be why (Vensim has none: an
    outflow larger than the stock within a step, a drain faster than a step). Then the stocks whose
    floor binds on the Euler path (every stock that has an outflow made signed, so SD Lab follows
    PySD's path, and the ones whose outflows exceed their level on it kept) are made signed and the
    model converted and checked again (2d)."""
    conv = convert(path)
    if conv.text is None:
        return conv, None
    eq = equivalent(conv)
    if eq.ok:
        return conv, eq
    model = sdlab_model(conv.text, conv.steps)
    have = {s["id"] for s in model["stocks"] if s.get("signed")}
    ids = {s["id"] for s in model["stocks"]}                    # (hidden stages too: a stage faster than a step)
    cands = {f["from"] for f in model["flows"] if f.get("from") in ids} | {f["to"] for f in model["flows"] if f.get("two_way") and f.get("to") in ids}
    if not cands - have:
        return conv, eq
    loose = convert(path, signed=cands | have)
    eq_loose = equivalent(loose) if loose.text is not None else None
    if eq_loose is None or not eq_loose.ok:
        return conv, eq
    need = _binding(loose) | have
    again = convert(path, signed=need)
    eq2 = equivalent(again) if again.text is not None else None
    if eq2 is None or not eq2.ok:                                # (a floor that binds within a step only: every candidate)
        loose.notes.append(f"signed so that SD Lab's floor does not cut them where Euler does not: {', '.join(sorted(cands - have))}")
        return loose, eq_loose
    again.notes.append(f"signed so that SD Lab's floor does not cut them where Euler does not: {', '.join(sorted(need - have))}")
    return again, eq2


def _binding(conv: Conversion) -> set[str]:
    """The stocks whose outflows in a step exceed what they hold at its start, on this conversion's
    run (noise none): where SD Lab's floor would cut them."""
    from .data import simulate

    model = sdlab_model(conv.text, conv.steps)
    run = simulate(model, steps=conv.steps)
    out = set()
    first = {s["id"]: float(s["initial"]) for s in model["stocks"]}
    for s in first:
        if s not in run["all_levels"]:
            continue
        lv = [first[s]] + run["all_levels"][s]
        for k in range(conv.steps):
            take = 0.0
            for f in model["flows"]:
                q = run["counters"][f["id"]][k]
                if f.get("from") == s and q > 0:
                    take += q * float(f.get("ratio") or 1)
                if f.get("to") == s and q < 0:
                    take -= q
                for u in f.get("uses") or []:
                    if u.get("stock") == s and q > 0:
                        take += q * float(u.get("per") or 0)
            if take > lv[k] + 1e-9:
                out.add(s)
                break
    return out


def convert(path, wrap: bool = True, signed: set | None = None) -> Conversion:
    """The model as a case body, or what blocks it (see the module docstring); signed: stocks to make
    signed whatever PySD's run does (convert_checked)."""
    import sympy as sp

    from .canonical import match, timefns
    from .canonical.read import DELAY, DELAYF, SMOOTH, TIME, Blocked, Flow, at_start, read, running

    path = Path(path)
    m = read(path)
    conv = Conversion(path=path, model=m, blocked=list(m.blocked))
    if not m.stocks and wrap and m.sinks:
        conv.wrapped = True
        taken = set()
        for py in m.sinks:
            sid = re.sub(r"[^A-Za-z0-9]+", "_", f"acc_{py}").strip("_")
            while sid in taken:
                sid += "_2"
            taken.add(sid)
            m.stocks[sid] = {"name": sid, "py": None, "initial": 0.0, "of": py}
            m.flows.append(Flow(key=py, name=m.element_names.get(py, py), dst=sid, expr=m.aux[py]))
    if not m.stocks:
        if not conv.blocked:
            conv.blocked.append(("no stocks", path.name))
        return conv
    conv.stocks = {sid: s["name"] for sid, s in m.stocks.items()}
    negative_start = {sid for sid, s in m.stocks.items() if s["initial"] is not None and s["initial"] < 0}   # signed (2d), no longer blocked

    # PySD's own run, at every Euler step
    try:
        cols = [s.get("column", s["name"]) for s in m.stocks.values() if s.get("py") or s.get("column")]
        aux_cols = [m.element_names[s["of"]] for s in m.stocks.values() if s.get("of")]
        run = pysd_run(path, list(dict.fromkeys(cols + aux_cols)), m.t0, m.final, m.dt, folder=getattr(m, "external", False))
    except Exception as e:                                                        # noqa: BLE001
        conv.blocked.append(("PySD cannot run it", f"{type(e).__name__}: {str(e)[:120]}"))
        return conv
    euler = {}
    for sid, s in m.stocks.items():
        if s.get("hidden"):
            conv.notes.append(f"{s['name']}: a stock inside a macro that no variable of the model shows (not compared)")
            continue
        if s.get("of"):
            vals, acc = run[m.element_names[s["of"]]], [0.0]
            for v in vals[:-1]:
                acc.append(acc[-1] + m.dt * v)
            euler[sid] = acc
        else:
            euler[sid] = run[s.get("column", s["name"])]
    signed = set(signed or ()) | negative_start | {sid for sid, v in euler.items() if v and min(v) < -1e-9}
    negative = _negative_flows(m, euler, run, path)                # flows whose rate goes negative on PySD's run: two-way (2d)
    sym = {sid: sp.Symbol(sid, real=True) for sid in m.stocks}
    start = {sid: s["initial"] or 0.0 for sid, s in m.stocks.items()}
    scale_of = {sym[sid]: max([abs(x) for x in v] + [abs(start[sid])]) for sid, v in euler.items()}

    def attempt(scale: float, dt_sd: float):
        """(text, blocked, notes, uses_values) for one choice of recorded step."""
        steps = math.floor((m.final - m.t0) / scale + 1e-9)
        grid = timefns.Grid(m.t0, scale, dt_sd, steps)
        blocked, notes = [], []
        inputs: dict = {}                  # expr -> (symbol, name, spec)
        smooths: dict = {}                 # key -> (symbol, text)
        hidden: list = []                  # (id, initial): the stages of a DELAY N / SMOOTH N written out
        auxes: list = []                   # (name, expression): what a SMOOTH or DELAY of an expression smooths (2d)
        low = {sym[sid]: min(v + [start[sid]]) for sid, v in euler.items()}   # each reader's lowest value (2d: signed smoothings)
        two_hidden: set = set()            # hidden stages that may hold a negative amount (2d)
        chains: list = []                  # their flows: (key, text, exact)
        readers = {sym[sid]: sid for sid in m.stocks}
        sc = dict(scale_of)
        needs_values = [False]
        drv.clear()
        flow_keys = {f.key for f in m.flows}
        input_names = {}
        for py, v in getattr(m, "aux_values", {}).items():         # an auxiliary's name, not a flow's
            if py not in flow_keys or sp.srepr(v) not in input_names:
                input_names[sp.srepr(v)] = py
        taken_inputs = set(m.stocks)

        def initial_of(e):
            e = at_start(e).subs({sym[s]: start[s] for s in m.stocks})
            return timefns.evaluate(e, m.t0, m.dt, m.lookups)

        def as_input(e):
            key = sp.srepr(e)
            if key in inputs:
                return inputs[key][0]
            name = input_names.get(key) or f"u{len(inputs) + 1}"
            name = re.sub(r"[^A-Za-z0-9_]", "_", name)
            while name in taken_inputs:
                name += "_2"
            taken_inputs.add(name)
            try:
                terms = timefns.formula(e, grid, m.dt, m.lookups)
                timefns.series(e, grid, m.dt, m.lookups)
            except (ZeroDivisionError, OverflowError, ValueError) as err:
                raise Blocked("a number that is not finite", f"{str(e)[:60]}: {err}") from None
            if terms is not None:
                spec = {"formula": terms}
                vals = [timefns.evaluate(e, T, m.dt, m.lookups) for _, _, T in grid.points()]
            else:
                vals = timefns.series(e, grid, m.dt, m.lookups)
                spec = {"values": vals}
                needs_values[0] = True
            s = sp.Symbol(name, real=True)
            inputs[key] = (s, name, spec)
            drv.update(type(a).__name__.removeprefix("F_").upper() if type(a).__name__ not in m.lookups else "LOOKUP"
                       for a in e.atoms(sp.Function))
            drv.add("TIME") if not e.atoms(sp.Function) else None
            readers[s] = name
            sc[s] = max([abs(v) for v in vals] + [0.0])
            low[s] = min(vals + [0.0]) if vals else 0.0
            return s

        named = sorted(((v, py) for py, v in getattr(m, "aux_values", {}).items() if timefns.time_only(v)),
                       key=lambda x: -sp.count_ops(x[0]))

        def drivers(e):
            """Replace each largest part that reads only TIME by an input (a number times it, kept out);
            a named auxiliary of TIME first, so an input keeps the model's name (customer_demand): when
            the rate's terms that read TIME are r times the auxiliary's, the rate is (rate - r aux) + r input."""
            if e.has(TIME) and not e.has(DELAY, SMOOTH):
                ex = sp.expand(e)
                et = sp.Add(*[t for t in sp.Add.make_args(ex) if t.has(TIME)])
                for v, py in named:
                    vx = sp.expand(v)
                    vt = sp.Add(*[t for t in sp.Add.make_args(vx) if t.has(TIME)])
                    if vt == 0 or not _maybe_proportional(et, vt):
                        continue
                    r = sp.simplify(et / vt)
                    if r is not None and r.is_number and r != 0:
                        return _drivers(sp.expand(ex - r * vx) + r * as_input(v))
            return _drivers(e)

        def _maybe_proportional(a, b) -> bool:
            """False when a / b is surely not a constant (their values on a few Euler steps say so):
            a cheap test before sympy's simplify, which is slow on large models."""
            n = max(1, math.floor((m.final - m.t0) / m.dt + 1e-9))
            ratio = None
            for k in sorted({0, n // 7, n // 3, n // 2, (2 * n) // 3, n}):
                T = m.t0 + k * m.dt
                try:
                    x, y = timefns.evaluate(a, T, m.dt, m.lookups), timefns.evaluate(b, T, m.dt, m.lookups)
                except Exception:                                               # noqa: BLE001
                    return True
                if y == 0:
                    if x != 0:
                        return False
                    continue
                if ratio is None:
                    ratio = x / y
                elif not math.isclose(x / y, ratio, rel_tol=1e-9, abs_tol=1e-12):
                    return False
            return True

        def _drivers(e):
            if timefns.time_only(e):
                coef, rest = e.as_coeff_Mul()
                return coef * as_input(rest)
            if not e.args or e.is_Symbol or e.is_Number:
                return e
            return e.func(*[_drivers(a) for a in e.args])

        def smoothing(e):
            """SMOOTH and information DELAY placeholders as smooth(Y, T) readers (and an information DELAY
            FIXED of a stock as a delayed(Y, T) reader, 2d)."""
            if not e.args or e.is_Symbol or e.is_Number:
                return e
            if e.func == DELAYF and not timefns.time_only(e):
                _, x, order, init, _t0 = e.args
                x = drivers(smoothing(x))
                coef, y = x.as_coeff_Mul()
                if y not in readers or coef == 0 or x.has(SMOOTH, DELAY, DELAYF):
                    raise Blocked("fixed delay (DELAY FIXED) of an expression (not one stock or input)", str(e)[:80])
                t_sd = int(order) * m.dt / scale
                v0 = initial_of(init) / float(coef)
                s = sp.Symbol(f"DF_{len(smooths) + 1}", real=True)
                key = ("delayed", readers[y], t_sd, v0)
                if key not in smooths:
                    smooths[key] = (s, f"delayed({readers[y]}, {match.fmt(t_sd)}, initial={match.fmt(v0)})")
                    readers[s] = smooths[key][1]
                    sc[s] = sc.get(y, 1.0)
                return coef * smooths[key][0]
            if e.func in (SMOOTH, DELAY):
                x, T, init, n = e.args
                x = drivers(smoothing(x))
                if x.has(SMOOTH, DELAY):
                    raise Blocked("a smoothing of a smoothing", str(e)[:60])
                coef, y = x.as_coeff_Mul()
                if (y not in readers or coef == 0) and not x.has(TIME):   # 2d: an expression is smoothed as an auxiliary
                    name = _fresh(f"aux{len(auxes) + 1}", taken_ids | {a for a, _ in auxes} | set(readers.values()))
                    auxes.append((name, match.expr_text(x, readers, m.lookups)))
                    y, coef = sp.Symbol(name, real=True), sp.Integer(1)
                    readers[y] = name
                    sc[y] = max([sc.get(z, 1.0) for z in x.free_symbols] + [1.0])
                    low[y] = -1.0                                        # (its values are not known here: signed stages)
                if y not in readers or coef == 0:
                    raise Blocked("SMOOTH or DELAY of an expression (not one stock or input)", str(e)[:80])
                v0 = initial_of(init) / float(coef)
                t_sd = float(T) / scale
                key = (readers[y], t_sd, v0, int(n))
                if key not in smooths:
                    s = sp.Symbol(f"SM_{len(smooths) + 1}", real=True)
                    if low.get(y, 0.0) < 0 or v0 < 0:   # 2d: what it smooths goes negative: stages written out, signed, two-way
                        before = len(hidden)
                        smooths[key] = (s, smooth_chain(s.name, readers[y], int(n), t_sd, v0, hidden, chains, taken_ids, two=True))
                        two_hidden.update(h for h, _ in hidden[before:])
                    elif int(n) in (1, 3):
                        fn = "smooth" if int(n) == 1 else "smooth3"
                        smooths[key] = (s, f"{fn}({readers[y]}, {match.fmt(t_sd)}, initial={match.fmt(v0)})")
                    else:                  # SMOOTH N: n hidden stages, as smooth/smooth3 compile (exact flows)
                        smooths[key] = (s, smooth_chain(s.name, readers[y], int(n), t_sd, v0, hidden, chains, taken_ids))
                    readers[s] = smooths[key][1]
                    sc[s] = sc.get(y, 1.0)
                return coef * smooths[key][0]
            return e.func(*[smoothing(a) for a in e.args])

        flows = [f for f in m.flows if f.expr is not None and f.expr is not sp.nan and not (isinstance(f.expr, sp.Basic) and f.expr.has(sp.nan))]
        texts = []
        merged: set[str] = set()
        ids: set[str] = set()
        taken_ids = set(m.stocks) | ids
        for f in flows:
            if f.blocked:
                continue
            e = running(sp.sympify(f.expr))
            delay = None
            coef, core = e.as_coeff_Mul()
            if core.func == DELAYF and not timefns.time_only(core) and f.src is None:   # DELAY FIXED as a whole rate into a stock (2d): a pipe
                _, x, order, init, _t0 = core.args
                src = None
                for g in flows:
                    if g is not f and g.dst is None and g.src is not None and g.key not in merged and not g.blocked \
                            and sp.simplify(sp.sympify(g.expr) - coef * x) == 0:
                        src, merged_key = g.src, g.key
                        break
                if src is not None:
                    merged.add(merged_key)
                delay = {"order": "fixed", "time": int(order) * m.dt / scale, "initial": initial_of(coef * init) * scale, "src": src}
                texts.append((f, coef * x, delay))
                continue
            if core.func == DELAY and f.src is not None:                # Vensim's pipeline stock: the information delay it computes (2d)
                texts.append((f, e, None))
                continue
            if core.func == DELAY:
                x, T, init, n = core.args
                if T.free_symbols:
                    blocked.append(("a delay or smoothing whose time changes", f.name))
                    continue
                src = None
                for g in flows:
                    if g is not f and g.dst is None and g.src is not None and g.key not in merged and not g.blocked \
                            and sp.simplify(sp.sympify(g.expr) - coef * x) == 0:
                        src, merged_key = g.src, g.key
                        break
                if src is not None:
                    merged.add(merged_key)
                delay = {"order": int(n), "time": float(T) / scale, "initial": initial_of(coef * init) * float(T) / int(n), "src": src}
                e = coef * x
            texts.append((f, e, delay))
        out_flows = []
        for f, e, delay in texts:
            if f.key in merged:
                continue
            core_c, core = sp.sympify(e).as_coeff_Mul()
            if type(core).__name__ == "F_max" and len(core.args) == 2 and 0 in core.args and core_c > 0:
                e = core_c * next(a for a in core.args if a != 0)          # MAX(0, x) as a whole rate: SD Lab floors every rate at 0
                notes.append(f"{f.name}: MAX(0, x) read as x (every rate is floored at 0)")
            if sp.sympify(e) == 0:
                notes.append(f"{f.name} is always 0: left out")
                continue
            two = f.key in negative
            try:
                e = drivers(smoothing(sp.sympify(e) * sp.Rational(match.fmt(scale))))
                src = delay["src"] if delay else f.src
                try:
                    text = match.rate_text(e, src, readers, sc, m.lookups, two_way=two)
                except Blocked as b:
                    if b.feature == match.F_NEGATIVE:                  # written negative: a two-way flow (2d)
                        two = True
                        two_way_keys.add(f.key)
                        text = match.rate_text(e, src, readers, sc, m.lookups, two_way=True)
                    elif b.feature in match.EXPRESSIBLE:               # no linear form: an expression (2d)
                        text = match.expr_text(e, readers, m.lookups)
                    else:
                        raise
            except Blocked as b:
                blocked.append((b.feature, f"{f.name}: {b.where}" if b.where else f.name))
                continue
            fid = _flow_id(f.name, ids)
            if delay and delay["order"] not in (1, 3, "fixed"):     # DELAY N: n hidden stocks, as delay1/delay3 compile
                taken_ids.update(ids)
                before = len(hidden)
                out_flows += delay_chain(fid, src, f.dst, text, delay, hidden, taken_ids, two=two)
                if two:
                    two_hidden.update(h for h, _ in hidden[before:])
                ids.update(taken_ids)
                continue
            if delay and delay["order"] == "fixed":
                text = f"delay_fixed({text}, {match.fmt(delay['time'])}, initial={match.fmt(delay['initial'])})"
            elif delay:
                fn = "delay1" if delay["order"] == 1 else "delay3"
                text = f"{fn}({text}, {match.fmt(delay['time'])}, initial={match.fmt(delay['initial'])})"
            out_flows.append((f"{src or 'outside'} {'<->' if two else '->'} {f.dst or 'outside'} as {fid}", text))
        if blocked:
            return None, blocked, notes, needs_values[0], steps
        parts = {"dt": dt_sd if dt_sd < 1 else None, "signed": sorted(signed | two_hidden), "auxiliaries": auxes,
                 "stocks": [(sid, s["initial"] or 0) for sid, s in m.stocks.items()],
                 "hidden": hidden + [(sid, s["initial"] or 0) for sid, s in m.stocks.items() if s.get("hidden")],
                 "inputs": [(name, f"\"{_formula_text(spec['formula'])}\"" if "formula" in spec
                             else f"[{', '.join(match.fmt(v) for v in spec['values'])}]") for _, name, spec in inputs.values()],
                 "flows": out_flows + chains}
        return parts, blocked, notes, needs_values[0], steps

    drv: set[str] = set()
    two_way_keys: set = set()
    scale, dt_sd = _scale(m.dt)
    try:
        text, blocked, notes, values, steps = attempt(scale, dt_sd)
        if text is not None and values and dt_sd < 1:              # an input given per step: one Euler step per recorded step
            scale, dt_sd = m.dt, 1.0
            text, blocked, notes, values, steps = attempt(scale, dt_sd)
    except Blocked as b:
        text, blocked, notes, values, steps = None, [(b.feature, b.where)], [], False, 0
    conv.blocked += blocked
    conv.notes += notes
    conv.scale, conv.dt, conv.steps, conv.uses_values = scale, dt_sd, steps, values
    conv.drivers = sorted(drv)
    conv.two_way = negative | two_way_keys
    every = round(scale / m.dt)
    conv.pysd_levels = {sid: v[::every][: steps + 1] for sid, v in euler.items()}
    conv.euler = euler
    if not conv.blocked:
        conv.parts = text
        conv.text = render(text)
    return conv


def render(parts: dict, words: dict | None = None) -> str:
    """The case body (YAML) from a conversion's parts; words: {stock id: "hidden" | "final" | ...}."""
    from .canonical.match import fmt

    words = dict(words or {})
    hidden = dict(parts.get("hidden") or [])
    words.update({sid: "hidden" for sid in hidden if sid not in words})
    for sid in parts.get("signed") or []:                       # 2d: a stock that may go negative
        words[sid] = f"{words[sid]} signed" if words.get(sid) else "signed"
    lines = [f"dt: {fmt(parts['dt'])}"] if parts.get("dt") else []
    lines.append("stocks:")
    for sid, v in [x for x in parts["stocks"] if x[0] not in hidden] + list(hidden.items()):
        w = words.get(sid)
        lines.append(f"  {sid}: {fmt(v)}{' ' + w if w else ''}")
    if parts["inputs"]:
        lines.append("inputs:")
        lines += [f"  {name}: {text}" for name, text in parts["inputs"]]
    if parts.get("auxiliaries"):
        lines.append("auxiliaries:")
        lines += [f"  {name}: \"{text}\"" for name, text in parts["auxiliaries"]]
    lines.append("flows:")
    for key, text, *exact in parts["flows"]:
        lines.append(f"  {key}: {{rate: \"{text}\", exact: true}}" if exact and exact[0] else f"  {key}: \"{text}\"")
    return "\n".join(lines) + "\n"


def _fresh(base: str, taken: set[str]) -> str:
    out, i = base, 2
    while out in taken:
        out, i = f"{base}_{i}", i + 1
    taken.add(out)
    return out


def delay_chain(fid: str, src: str | None, dst: str | None, text: str, delay: dict, hidden: list, taken: set[str], two: bool = False) -> list:
    """DELAY N(rate, T) from src to dst written out as the case format compiles delay1/delay3: src -> H1
    at the rate (the flow keeps its id), then H1 -> H2 ... Hn -> dst, each n / T x its hidden stock
    (two: two-way flows, 2d)."""
    from .canonical.match import fmt

    n, k = delay["order"], delay["order"] / delay["time"]
    hs = [_fresh(f"{fid}_d{i}", taken) for i in range(1, n + 1)]
    hidden += [(h, delay["initial"]) for h in hs]
    arrow = "<->" if two else "->"
    out = [(f"{src or 'outside'} {arrow} {hs[0]} as {fid}", text)]
    for i, h in enumerate(hs, start=1):
        out.append((f"{h} {arrow} {hs[i] if i < n else (dst or 'outside')} as {_fresh(f'{fid}_{i}', taken)}", f"{fmt(k)} * {h}"))
    return out


def smooth_chain(name: str, of: str, n: int, time: float, initial: float, hidden: list, chains: list, taken: set[str], two: bool = False) -> str:
    """SMOOTH N(x, T) written out as the case format compiles smooth/smooth3: n hidden stages, stage i
    filled from outside at n / T x stage i-1 (x for the first) and drained at n / T x its own level,
    each flow exact (information, not material). The last stage's id (what a rate reads)."""
    from .canonical.match import fmt

    k = fmt(n / time)
    prev = of
    for i in range(1, n + 1):
        h = _fresh(f"{name}_{i}", taken)
        hidden.append((h, initial))
        arrow = "<->" if two else "->"                             # (two: what it smooths goes negative, 2d)
        chains.append((f"outside {arrow} {h} as {_fresh(h + '_in', taken)}", f"{k} * {prev}", True))
        chains.append((f"{h} {arrow} outside as {_fresh(h + '_out', taken)}", f"{k} * {h}", True))
        prev = h
    return prev


def _formula_text(terms: list[dict]) -> str:
    from .canonical.match import fmt

    out = []
    for t in terms:
        fn = t["fn"]
        if fn == "constant":
            out.append(fmt(t["value"]))
            continue
        keys = {"step": ("height", "start"), "pulse": ("height", "start", "width"), "ramp": ("slope", "start", "end"),
                "pulse_train": ("height", "first", "width", "every", "last"), "sin": ("amplitude", "period", "phase")}[fn]
        out.append(f"{fn}({', '.join(fmt(t[k]) for k in keys if k in t)})")
    return " + ".join(out) if out else "0"


def sdlab_model(text: str, steps: int) -> dict:
    """A case body as the engine's truth model (no noise)."""
    from .caseformat import compile_case

    spec = compile_case("title: import\nlevel: 1\ntags: []\ntests: import\n" + text, "<import>")
    m = spec["model"]
    return {"id": "import", "name": "import", "time_unit": "step", "seed": 1, "steps": steps, "noise": {},
            **{k: m[k] for k in ("schedule", "injections", "dt", "inputs", "auxiliaries") if m.get(k)},
            "stocks": [{"name": s["id"], "unit": "things", **s} for s in m["stocks"]],
            "flows": [{"name": f["id"], **f} for f in m["flows"]]}


def equivalent(conv: Conversion) -> Equivalence:
    """Do PySD's run and SD Lab's engine (noise none) give the same levels at every recorded step?"""
    from .data import simulate

    if conv.text is None:
        return Equivalence(False, reason="not converted: " + "; ".join(conv.features))
    model = sdlab_model(conv.text, conv.steps)
    run = simulate(model, steps=conv.steps)
    err, bad = {}, []
    for sid, want in conv.pysd_levels.items():
        got = [float(next(s["initial"] for s in model["stocks"] if s["id"] == sid))] + run["all_levels"][sid]
        top = max(abs(x) for x in want)
        e = max(abs(a - b) for a, b in zip(want, got))
        err[sid] = e
        if not all(math.isfinite(x) for x in want) or e > ATOL + RTOL * top:
            bad.append(sid)
    if not bad:
        return Equivalence(True, err)
    signed = {s["id"] for s in model["stocks"] if s.get("signed")}
    neg = [sid for sid in conv.euler if min(conv.euler[sid]) < -1e-9 and sid not in signed]
    emptied = [sid for sid in conv.pysd_levels if any(x == 0 for x in run["all_levels"][sid]) and min(conv.pysd_levels[sid]) > 0]
    fast = [f["id"] for f in model["flows"] if f.get("from") and f.get("rate", {}).get("form") == "proportional"
            and f["rate"].get("stock") == f["from"] and f["rate"]["k"] * (model.get("dt") or 1) > 1]
    reason = F_TWO_WAY if _negative_rate(conv) else F_NEG_STOCK if neg else F_EMPTIED if emptied else F_FAST if fast else "the runs differ"
    return Equivalence(False, err, reason)


def _negative_flows(m, euler: dict, run: dict, path: Path | None = None) -> set:
    """The keys of the flows whose rate goes below 0 on PySD's run: evaluated on its levels, or (an
    accumulated auxiliary, a flow that holds a DELAY, SMOOTH or DELAY FIXED) PySD's own values of it."""
    import sympy as sp

    from .canonical import timefns
    from .canonical.read import DELAY, DELAYF, SMOOTH, Blocked

    out = set()
    n = len(next(iter(euler.values()))) if euler else 0
    acc = {s["of"]: m.element_names[s["of"]] for s in m.stocks.values() if s.get("of")}
    stateful = [f for f in m.flows if f.key not in acc and f.expr is not None and sp.sympify(f.expr).has(DELAY, SMOOTH, DELAYF)]
    seen = dict(run)
    if stateful and path is not None:
        folder = getattr(m, "external", False)
        try:                                                                      # one run for all of them, else one by one
            seen.update(pysd_run(path, [f.name for f in stateful], m.t0, m.final, m.dt, folder=folder))
        except Exception:                                                         # noqa: BLE001 (a name that is not a column PySD shows)
            for f in stateful:
                try:
                    seen.update(pysd_run(path, [f.name], m.t0, m.final, m.dt, folder=folder))
                except Exception:                                                 # noqa: BLE001
                    pass
    for f in m.flows:
        col = acc.get(f.key) or (f.name if f in stateful else None)
        if col and col in seen:
            if min(seen[col]) < -1e-9:
                out.add(f.key)
            continue
        e = sp.sympify(f.expr) if f.expr is not None else None
        if e is None or e.has(DELAY, SMOOTH, DELAYF) or e.has(sp.nan):
            continue
        for k in range(n):
            env = {sid: v[k] for sid, v in euler.items()}
            try:
                if timefns.evaluate(e, m.t0 + k * m.dt, m.dt, m.lookups, env) < -1e-9:
                    out.add(f.key)
                    break
            except (Blocked, ValueError, ZeroDivisionError, OverflowError, TypeError):
                break
    return out


def _negative_rate(conv: Conversion) -> bool:
    """Does any flow's rate go negative on PySD's run (where it can be evaluated)?"""
    import sympy as sp

    from .canonical import timefns
    from .canonical.read import DELAY, SMOOTH, Blocked

    m = conv.model
    n = len(next(iter(conv.euler.values())))
    for f in m.flows:
        e = sp.sympify(f.expr) if f.expr is not None else None
        if e is None or e.has(DELAY, SMOOTH) or e.has(sp.nan) or f.key in conv.two_way:   # (2d: a two-way flow may go negative)
            continue
        for k in range(n):
            env = {sid: v[k] for sid, v in conv.euler.items()}
            try:
                if timefns.evaluate(e, m.t0 + k * m.dt, m.dt, m.lookups, env) < -1e-9:
                    return True
            except (Blocked, ValueError, ZeroDivisionError, OverflowError):
                break
    return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m sdlab.ladder.pysd_import MODEL.mdl|.xmile|.stmx ...")
        return 2
    for p in argv:
        conv = convert(p)
        print(f"# {p}")
        if conv.text is None:
            for feat, where in conv.blocked:
                print(f"#   blocked: {feat} ({where})")
            continue
        eq = equivalent(conv)
        print(f"# scale {conv.scale}, dt {conv.dt}, steps {conv.steps}; equivalent to PySD: {eq.ok} {eq.reason}")
        print(conv.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
