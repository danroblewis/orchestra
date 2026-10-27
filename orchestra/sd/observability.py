"""Which stocks the instruments determine: the model's observability, and what would complete it.

A hidden stock is a question about the system (rule 7): something no series measures, found from
how the measured levels change. This says, for the current model, whether each stock's level can
be determined from what is measured, through which instruments, and, when it cannot, which new
instrument would make it determinable. It is the check the state estimator (``kalman_lna``) does
not make (docs/proposals/control-theory.md §1, §7.1).

The method (linear systems theory; numpy only):

1. **Linearise** the model at its recent operating point (``sd.linearise``): ``dx/dt ≈ A x`` over
   every stock, measured or hidden.
2. **Sensors** are the rows of ``C``: a stock bound to a series is measured directly (a unit row);
   a flow with a counter measures its rate, which its equation ties to the levels it reads (its
   row of slopes). A counter on a flow whose rate reads nothing (a constant) tells nothing about
   any level.
3. **The unobservable subspace** is the largest subspace inside the null space of ``C`` that ``A``
   maps into itself: no measurement, now or later, changes when the levels move along it. It is
   found by shrinking ``null(C)`` until it is ``A``-invariant (the observability matrix
   ``[C; CA; …; CAⁿ⁻¹]`` has the same null space, but its powers of ``A`` are badly conditioned).
   A stock is **determined** when its own direction has no part in that subspace.
4. **Generically**, the same test with every slope replaced by random numbers on the same pattern
   (and the same stoichiometry): what the structure allows for almost any fitted numbers. A stock
   undetermined at the fitted numbers but determined generically is undetermined by a coincidence
   of values.
5. **Reasons and remedies**: the path from a determined stock to the nearest sensor; the sensors it
   relies on (removing one makes it undetermined); for an undetermined stock, each instrument that
   would determine it (a series on an unmeasured stock, a counter on an unmeasured flow).
6. **Parameters that appear only in combination**: unmeasured flows' numbers multiplying the same
   thing (a constant, or one level or input) whose flows move the determined stocks in dependent
   ways; only their combination shows in the levels. Numbers multiplying an undetermined stock
   cannot be identified while it is.
7. **Controllability, structural and weak**: which stocks the flows machines are hypothesised to
   affect (``Machine.attributed``) could move at all. Linear controllability ignores floors, caps
   and that a rate cannot be negative, which dominate these models; it says what is connected, not
   what can be steered.

All of it is local: for a rate that is not linear in the levels (an effect, an expression, a rate
floored at 0 here) the slopes hold only near the operating point, and the report names those flows.
Every equation is a hypothesis (rule 6), so a stock determined through a counter is determined
only as far as that flow's equation is right."""

from __future__ import annotations

from collections import deque

from .linearise import Linear, linearise
from .model import Model

TOL = 1e-9          # rank threshold, on matrices scaled to unit size
PART = 1e-6         # a direction has a part in a subspace when its projection is longer than this


def _null(M, n: int):
    """An orthonormal basis (n × d) of M's null space."""
    import numpy as np

    if M.shape[0] == 0:
        return np.eye(n)
    _, s, vh = np.linalg.svd(M, full_matrices=True)
    rank = int((s > TOL * max(1.0, s.max() if s.size else 0.0)).sum())
    return vh[rank:].T.copy()


def unobservable(A, C):
    """An orthonormal basis of the unobservable subspace of (A, C)."""
    import numpy as np

    n = A.shape[0]
    a = np.abs(A).max() if A.size else 0.0
    A = A / a if a > 0 else A
    V = _null(C, n)
    while V.shape[1]:
        Z = _null((np.eye(n) - V @ V.T) @ A @ V, V.shape[1])
        if Z.shape[1] == V.shape[1]:
            break
        V = V @ Z
        if V.shape[1]:
            V, _ = np.linalg.qr(V)
    return V


def controllable(A, B):
    """An orthonormal basis of the subspace reachable from B's columns."""
    import numpy as np

    n = A.shape[0]
    a = np.abs(A).max() if A.size else 0.0
    A = A / a if a > 0 else A
    K = np.zeros((n, 0))
    new = B
    for _ in range(n + 1):
        M = np.hstack([K, new])
        if not M.size:
            break
        u, s, _ = np.linalg.svd(M, full_matrices=False)
        r = int((s > TOL * max(1.0, s.max())).sum())
        if r == K.shape[1]:
            break
        K = u[:, :r]
        new = A @ K
    return K


def _undetermined(V, n: int) -> set[int]:
    import numpy as np

    return {i for i in range(n) if V.shape[1] and np.linalg.norm(V[i]) > PART}


def _rows(lin: Linear, sensors: list[dict], R=None):
    import numpy as np

    R = lin.R if R is None else R
    rows = []
    for s in sensors:
        rows.append(np.eye(len(lin.stocks))[lin.stocks.index(s["stock"])] if s["kind"] == "series" else R[lin.flows.index(s["flow"])])
    C = np.array(rows) if rows else np.zeros((0, len(lin.stocks)))
    norms = np.linalg.norm(C, axis=1, keepdims=True) if rows else np.ones((0, 1))
    return C / np.where(norms > 0, norms, 1.0)


def sensors_of(model: Model) -> list[dict]:
    """What is measured: each stock bound to a series, each flow with a counter."""
    out = [{"id": f"series:{s.series.name}", "kind": "series", "stock": s.id,
            "what": f"series {s.series.name} (the level of {s.id})"} for s in model.stocks if s.series]
    for f in model.flows:
        refs = f.measured_by or ([f.counter] if f.counter else [])
        if refs:
            names = " + ".join(dict.fromkeys(r.name for r in refs))
            what = f"counter {names}" + ("" if names == f.id else f" (flow {f.id})")
            out.append({"id": f"counter:{f.id}", "kind": "counter", "flow": f.id, "what": what})
    return out


def _generic_undetermined(lin: Linear, sensors: list[dict], draws: int = 3) -> set[int]:
    """The stocks undetermined for random slopes on the model's pattern (the fewest over a few draws)."""
    import numpy as np

    rng = np.random.default_rng(7)
    best = None
    for _ in range(draws):
        R = np.where(lin.pattern, rng.normal(size=lin.pattern.shape), 0.0)
        und = _undetermined(unobservable(lin.S @ R, _rows(lin, sensors, R)), len(lin.stocks))
        best = und if best is None or len(und) < len(best) else best
    return best or set()


def _graph(lin: Linear, sensors: list[dict]) -> dict[int, list[tuple[object, str]]]:
    """Who informs whom: stock i → stock j through flow f (f reads i and moves j), stock i → sensor."""
    edges: dict[int, list[tuple[object, str]]] = {i: [] for i in range(len(lin.stocks))}
    for fj, fid in enumerate(lin.flows):
        for i in range(len(lin.stocks)):
            if lin.R[fj, i] == 0:
                continue
            for j in range(len(lin.stocks)):
                if j != i and lin.S[j, fj] != 0:
                    edges[i].append((j, fid))
    for k, s in enumerate(sensors):
        for i in range(len(lin.stocks)):
            if (s["kind"] == "series" and lin.stocks[i] == s["stock"]) or (s["kind"] == "counter" and lin.R[lin.flows.index(s["flow"]), i] != 0):
                edges[i].append((("sensor", k), s["id"]))
    return edges


def _paths(lin: Linear, sensors: list[dict], edges, i: int) -> tuple[list[str], str | None]:
    """The sensors stock i reaches in the graph, and the shortest way to one, in words."""
    seen, prev, q, reached = {i}, {}, deque([i]), []
    first = None
    while q:
        x = q.popleft()
        for y, how in edges[x]:
            if isinstance(y, tuple):
                if how not in reached:
                    reached.append(how)
                    if first is None:
                        first = (x, how)
                continue
            if y not in seen:
                seen.add(y)
                prev[y] = (x, how)
                q.append(y)
    if first is None:
        return [], None
    x, how = first
    hops = []
    while x != i:
        p, fid = prev[x]
        hops.append(f"{lin.stocks[p]} drives {lin.stocks[x]} through flow {fid}")
        x = p
    sensor = next(s for s in sensors if s["id"] == how)
    at = lin.stocks[first[0]]
    if sensor["kind"] == "series":
        end = f"{at} is measured by {sensor['what']}"
    else:
        end = f"{at} sets the rate of flow {sensor['flow']} (its equation reads it), which {sensor['what'].split(' (flow')[0]} measures"
    return reached, "; ".join([*reversed(hops), end])


def _direction(lin: Linear, v) -> dict:
    import numpy as np

    big = np.abs(v).max()
    parts = {lin.stocks[i]: round(float(v[i] / big), 3) for i in range(len(v)) if abs(v[i]) > PART * 10 * big}
    if len(parts) == 1:
        text = f"the level of {next(iter(parts))} alone: no measurement changes when it does"
    else:
        text = "changing " + ", ".join(f"{s} by {c:+g}" for s, c in parts.items()) + " together changes no measurement"
    return {"stocks": parts, "text": text}


def _directions(lin: Linear, V) -> list[dict]:
    """The unobservable directions, simplified so each involves as few stocks as it can (row echelon)."""
    import numpy as np

    M = V.T.copy()
    rows, col = [], 0
    for r in range(M.shape[0]):
        while col < M.shape[1] and np.abs(M[r:, col]).max() <= PART:
            col += 1
        if col == M.shape[1]:
            break
        p = r + int(np.argmax(np.abs(M[r:, col])))
        M[[r, p]] = M[[p, r]]
        M[r] /= M[r, col]
        for q in range(M.shape[0]):
            if q != r:
                M[q] -= M[q, col] * M[r]
        rows.append(r)
        col += 1
    return [_direction(lin, M[r]) for r in rows]


def _combinations(model: Model, lin: Linear, sensors: list[dict], undetermined: set[int]) -> list[dict]:
    """Numbers of unmeasured flows that show in the determined levels only in combination."""
    import numpy as np

    counted = {s["flow"] for s in sensors if s["kind"] == "counter"}
    known = [i for i in range(len(lin.stocks)) if i not in undetermined]
    by_regressor: dict[str, list[tuple[str, str, int]]] = {}
    out = []
    for fid, params in lin.linear_in.items():
        if fid in counted:
            continue
        for name, x in params:
            if x in lin.stocks and lin.stocks.index(x) in undetermined:
                out.append({"params": [f"{fid}: {name}"], "why": f"it multiplies {x}, whose level is not determined"})
                continue
            by_regressor.setdefault(x, []).append((fid, name, lin.flows.index(fid)))
    for x, group in by_regressor.items():
        cols = np.array([lin.S[known, j] for _, _, j in group]).T if known else np.zeros((0, len(group)))
        if not cols.size or not np.abs(cols).sum(axis=0).all():
            for (fid, name, j) in group:
                if not known or not np.abs(lin.S[known, j]).any():
                    out.append({"params": [f"{fid}: {name}"], "why": "its flow moves no stock whose level is determined"})
        if len(group) < 2:
            continue
        N = _null(cols, len(group)) if cols.size else np.eye(len(group))
        for v in N.T:
            members = [f"{group[k][0]}: {group[k][1]}" for k in range(len(group)) if abs(v[k]) > PART]
            if len(members) > 1:
                what = "the constant" if x == "1" else x
                out.append({"params": members, "why": f"they multiply {what} and their flows move the measured levels "
                                                      "alike, so only their combination shows; a counter on one of them would separate them"})
    return out


def _control(model: Model, lin: Linear) -> dict:
    import numpy as np

    by_machine = {m.id: [f for f in m.attributed if f in lin.flows] for m in model.machines}
    flows = list(dict.fromkeys(f for fs in by_machine.values() for f in fs))
    note = ("structural and weak: linear controllability ignores floors, caps and that a rate cannot be negative, which dominate "
            "these models; it says which stocks the flows machines are hypothesised to affect connect to at all, not what can be steered")
    if not flows:
        return {"note": note, "flows": [], "movable": [], "unreachable": lin.stocks, "machines": {}}
    A = lin.A
    def reach(fs):
        K = controllable(A, lin.S[:, [lin.flows.index(f) for f in fs]])
        return [lin.stocks[i] for i in range(len(lin.stocks)) if K.shape[1] and np.linalg.norm(K[i]) > PART], K.shape[1]
    movable, rank = reach(flows)
    return {"note": note, "flows": flows, "rank": rank, "movable": movable,
            "unreachable": [s for s in lin.stocks if s not in movable],
            "machines": {m: reach(fs)[0] for m, fs in by_machine.items() if fs}}


def _modes(model: Model, lin: Linear) -> list[dict]:
    import numpy as np

    out = []
    for lam in sorted(np.linalg.eigvals(lin.A), key=lambda z: (z.real, z.imag)) if lin.stocks else []:
        re = float(lam.real)
        kind = ("integrates (no outflow depends on what it holds)" if abs(re) < 1e-12 else
                "decays" if re < 0 else "grows")
        out.append({"eigenvalue": [round(re, 6), round(float(lam.imag), 6)], "kind": kind,
                    **({"time_constant": round(-1.0 / re, 4)} if re < -1e-12 else {})})
    return out


def report(model: Model, levels: dict[str, float] | None = None, inputs: dict[str, float] | None = None,
           point: str = "") -> dict:
    """The observability report for ``model`` linearised at ``levels`` and ``inputs`` (``point``
    says where they came from)."""
    lin = linearise(model, levels, inputs)
    sensors = sensors_of(model)
    n = len(lin.stocks)
    V = unobservable(lin.A, _rows(lin, sensors))
    und = _undetermined(V, n)
    generic = _generic_undetermined(lin, sensors)
    edges = _graph(lin, sensors)
    hidden = {s.id for s in model.stocks if not s.series}
    candidates = [{"id": f"series on {s}", "kind": "series", "stock": s} for s in lin.stocks if s in hidden]
    counted = {s.get("flow") for s in sensors}
    candidates += [{"id": f"counter on {f}", "kind": "counter", "flow": f} for j, f in enumerate(lin.flows)
                   if f not in counted and lin.R[j].any()]
    fixes: dict[int, list[str]] = {i: [] for i in und}
    for c in candidates:
        now = _undetermined(unobservable(lin.A, _rows(lin, [*sensors, c])), n)
        for i in und - now:
            fixes[i].append(c["id"])
    relies: dict[int, list[str]] = {i: [] for i in range(n)}
    spare: dict[int, str | None] = {}           # a measured stock: how the other instruments determine it, if they do
    for k, s in enumerate(sensors):
        rest = sensors[:k] + sensors[k + 1:]
        without = _undetermined(unobservable(lin.A, _rows(lin, rest)), n)
        for i in without - und:
            relies[i].append(s["what"])
        if s["kind"] == "series":
            i = lin.stocks.index(s["stock"])
            spare[i] = None if i in without else _paths(lin, rest, _graph(lin, rest), i)[1]
    stocks = []
    for i, sid in enumerate(lin.stocks):
        reached, path = _paths(lin, sensors, edges, i)
        row = {"id": sid, "hidden": sid in hidden, "determined": i not in und,
               "through": [next(s["what"] for s in sensors if s["id"] == r) for r in reached], "relies_on": relies[i]}
        if i in spare:
            row["without_its_series"] = spare[i]
        if i not in und:
            row["why"] = path or "measured"
        else:
            row["why"] = ("no sensor reads it, directly or through the flows its level drives" if not reached else
                          "the sensors it reaches cannot tell it apart from other stocks (see the directions)")
            row["would_determine"] = fixes[i]
            if i not in generic:
                row["coincidence"] = ("generically determined: only the fitted numbers make it undetermined (two equal "
                                      "rates, a slope of 0 at this point)")
        stocks.append(row)
    caveats = [f"linearised at {point or 'the given levels'}; the answers hold near that point"]
    caveats += [f"flow {f}: {why}" for f, why in lin.nonlinear.items()]
    if lin.outside:
        caveats.append("no equation to read, so taken as outside inputs (what they might say about their ends is not used): "
                       + ", ".join(lin.outside))
    if hidden:
        caveats.append("hidden stocks' levels are unknown and were taken as 0: a slope there is the slope as the stock fills")
    unread = [s for s in lin.stocks if s not in hidden and (levels or {}).get(s) is None]
    if unread:
        caveats.append("no measured level at the operating point, so taken as 0: " + ", ".join(unread))
    empty = [s for s in lin.stocks if s not in hidden and s not in unread and lin.view.get(s, 0.0) <= 0.0
             and any(lin.S[lin.stocks.index(s), j] < 0 for j in range(len(lin.flows)))]
    if empty:
        caveats.append("empty at the operating point, so in fact their outflows are limited by what they hold, which the "
                       "linearisation ignores: " + ", ".join(empty))
    caveats.append("every equation is a hypothesis (rule 6): a stock determined through a counter is determined only as far as "
                   "that flow's equation is right")
    return {"ok": True, "stocks": stocks, "states": n, "hidden": sorted(hidden), "rank": n - V.shape[1],
            "observable": not und, "generic_rank": n - len(generic),
            "generically_observable": not generic,
            "sensors": [s["what"] for s in sensors], "directions": _directions(lin, V) if V.shape[1] else [],
            "combinations": _combinations(model, lin, sensors, und), "controllability": _control(model, lin),
            "modes": _modes(model, lin), "time_unit": model.time_unit,
            "operating_point": {"from": point, "levels": {s: lin.view.get(s, 0.0) for s in lin.stocks}},
            "caveats": caveats}


def lines(r: dict) -> list[str]:
    """The report as text, for the command line."""
    out = [f"observability: {r['rank']} of {r['states']} stock levels determined by what is measured"
           + ("" if r["observable"] else f"; {r['states'] - r['rank']} undetermined direction(s)"),
           f"  sensors: {len(r['sensors'])}; hidden stocks: {', '.join(r['hidden']) or 'none'}", ""]
    for s in r["stocks"]:
        tag = "hidden " if s["hidden"] else ""
        if s["determined"]:
            if s["hidden"]:
                out.append(f"  {tag}stock {s['id']}: determined — {s['why']}")
                if s["relies_on"]:
                    out.append(f"      relies on: {'; '.join(s['relies_on'])}")
            continue
        out.append(f"  {tag}stock {s['id']}: NOT determined — {s['why']}")
        if s.get("would_determine"):
            out.append(f"      measuring would fix it: {'; '.join(s['would_determine'])}")
        elif "would_determine" in s:
            out.append("      no single new series or counter fixes it")
        if s.get("coincidence"):
            out.append(f"      {s['coincidence']}")
    measured = [s for s in r["stocks"] if not s["hidden"]]
    if measured:
        out.append(f"  measured directly: {', '.join(s['id'] for s in measured)}")
        spare = [s for s in measured if s.get("without_its_series")]
        if spare:
            out.append("  determined even without their own series (through the counters and the equations):")
            out += [f"    {s['id']}: {s['without_its_series']}" for s in spare]
        only = [s["id"] for s in measured if "without_its_series" in s and not s["without_its_series"]]
        if only:
            out.append(f"  determined only by their own series (it is their only instrument): {', '.join(only)}")
    for d in r["directions"]:
        out.append(f"  undetermined: {d['text']}")
    if r["combinations"]:
        out += ["", "parameters that cannot be told apart:"]
        out += [f"  {', '.join(c['params'])}: {c['why']}" for c in r["combinations"]]
    c = r["controllability"]
    out += ["", "controllability (structural and weak: floors and caps are ignored; it says what is connected, not what can be steered):"]
    if c["flows"]:
        out.append(f"  the {len(c['flows'])} flows machines are hypothesised to affect connect to {len(c['movable'])} of "
                   f"{r['states']} stocks; not to: {', '.join(c['unreachable']) or 'none'}")
    else:
        out.append("  no machine is hypothesised to affect any flow")
    grows = [m for m in r["modes"] if m["kind"] != "decays"]
    if grows:
        out += ["", f"modes that do not decay: {len(grows)} ({'; '.join(sorted({m['kind'] for m in grows}))})"]
    out += ["", "caveats:"] + [f"  - {c}" for c in r["caveats"]]
    return out


def operating_point(history: dict | None) -> tuple[dict[str, float], dict[str, float], str]:
    """The mean of each stock's level and each input over a history (``web.background.history``)."""
    if not history:
        return {}, {}, "no history: every stock at 0"
    mean = lambda pts: sum(v for _, v in pts) / len(pts)
    levels = {k: mean(p) for k, p in (history.get("stocks") or {}).items() if p}
    inputs = {k: mean(p) for k, p in (history.get("inputs") or {}).items() if p}
    span = (history.get("at", 0) - history.get("start", 0)) / 60
    return levels, inputs, f"the mean levels and inputs over the last {span:g} min"
