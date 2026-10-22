"""Scoring a found model against a case's true model: did discovery recover the true equations?

**Parts.** Every flow is cut into parts, one per number in its equation, keyed by where it goes and
what it reads. A flow's rate in a linear form (constant, proportional, gap, linear) is
c + sum k_j x level_j: its parts are (from, to, "1") = c and (from, to, j) = k_j, with from / to the
measured stock or outside. The kind follows from the key: a **move** (measured to measured), an
**outside inflow** (from outside, reading nothing), a **link** (from outside, reading a stock), an
**outside outflow** (to outside). A flow's co-flow is a part (uses, from, to, stock) = per; an
effect is a part (effect, from, to, stock); a hidden stock between measured A and B (A -> H -> B, H
not measured) is one part (hidden, A, B) = {k_in, delay}; a hidden path fed from outside into B is
(hidden, None, B) = {delay} with its inflow's numbers as (via, None, B, reader) parts (and its
effects as (viaeffect, None, B, stock), compared as a whole); a rate that reads an information
smoothing of X (SMOOTH / SMOOTHn of a measured stock or input, or a found model's own smoothing stock)
is (smooth, from, to, X) = {gain, delay}: the gain compared as a number reading X, the delay within
rel (2026-10-19). Found and true parts with the same key
are summed (two links into one stock from the same driver are one number in the data).

**Same-pair flows are one flow** (the user, 2026-10-20; merge.py). Before it is cut into parts, a found
model's flows with the same (from, to) (outside counts as an end) are merged into one flow whose rate
is the sum of theirs (terms reading the same stock one coefficient, constants added, pieces laid over
the union of their spans). Their co-flows ride on the merged flow and are still parts (scored, and
spurious if the truth lacks them); a flow whose rate cannot be summed with the others (effects, a
hidden stock, a ratio, a rate that is not linear) stays apart and says so in the notes. The linear
system, the amounts and behaviour run the originals, so the merge changes how the model is cut into
parts (a hidden chain or a smoothing written as two same-pair flows is now seen as one), never what it
computes.

**A truth at a sub-step** (dt < 1) is compared by its per-recorded-step equivalents (substep.py): a
drain k recorded every 1/dt sub-steps is 1 - (1 - k dt)^(1/dt) per step.

**Windows.** A rate that changes (announced eras, unannounced schedule changes) is compared in
every window where the truth's equations hold still: the found flow's numbers are averaged over
the window (its byTime segments or outside inflow pieces), and a part must be right in every one.

**Tolerance.** A number k is right when |found - true| <= max(rel x |true|, floor / mean level of
what it reads, z x its standard error), with rel 10% (2% without noise), floor 1% (0.2% without
noise) of the median size of the true parts (size: |k| x the mean level it reads, a flow amount per
step), and z = 3 standard errors of the oracle (oracle.py: the truth's own structure fitted by least
squares on the run, so a short noisy run is not asked for more than it can tell; for a truth with a
hidden stock, hidden_oracle.py: its structure fitted by the Kalman filter's likelihood on the
measured data, which also gives the delay's SE; a hidden part's delay is right within
max(rel x delay, z x SE)). A flow with
effects is compared as a whole: its amount on the run's states (rate x effects) against the found
flows between the same stocks, as relative rms error within rel. Override per case: "tolerance":
{"rel", "rel_exact", "floor", "floor_exact", "spurious", "z"}.

**Scores.** recall = true parts whose key the found model has (right kind and ends); precision =
found parts above the size threshold whose key is true; pass = every true part right and no
spurious part (a found part the truth lacks, larger than "spurious", 5% of the median true part
size, and with an oracle, larger than z standard errors of that term added to the truth's fit). When not
a pass, the data cannot tell the found model from the truth when the found flows make the same linear
system (every stock's change the same function of the levels, the measured inputs and the outside, within
tolerance; births and deaths seen as their difference, a gap seen as an inflow and a drain), or for a
truth with effects compute the same change of every stock on the run's states (_same_function); not
checked for a truth with hidden stocks. Since 2026-10-21 (the user) such a model is **equivalent** only
when algebra.py proves every stock's net rate the truth's for every state (births and deaths as their
difference, a move as a link and an outflow; the note says how the drawings differ), else it **fits**
(not proven: the gap's floor, which the run never reached; the note names where it differs). Neither is
a pass. A found move between stocks of different units standing for the truth's link and outflow fails;
the conserving drawing of a truth's link and outflow (a found move of one unit) stays equivalent unless
CONSERVING_PASS.

**The boundary** (the user, 2026-10-20). A case that declares its boundary (caseformat.boundary_spec;
per measured stock, its outside inflows and outflows) is told it, and outside flows are a modelling
decision, not something discovery may invent: a found part with an outside end (an outside inflow, a
link, an outside outflow, a hidden path fed from outside, their co-flows and effects) on a stock and
side the boundary does not have is a spurious part of kind "invented boundary", whatever its size
(only an exactly zero one is not), and so is an outside flow that reaches a measured stock through the
found model's own unmeasured stocks. The result fails (never equivalent: "A -> outside" plus
"outside -> B" is not the move A -> B) with the note "invented boundary: ...". Declared outside flows
are scored as before; a case with no boundary is scored exactly as before. Since 2026-10-21 (the user):
a declared side holds at most as many found outside flows as it declares (after same-pair flows are
merged; a second one is an "invented boundary"), and a side declared "input" (the inflow IS a measured
series) must be fed by exactly 1 x the input, with no extra term or constant where every inflow it
declares is an input; otherwise the result fails with the note "input altered" (never equivalent).

**Hidden stocks of a found model** (the user, 2026-10-21; hidden_match.py). A found hidden stock that no
older path reads (not a path between measured stocks, not a smoothing) is matched to at most one such true
hidden stock by its connections and behaviour (its trajectory against the truth's level, up to scale and
offset), written in the truth's coordinates, and scored as a measured stock (its flows and those reading it).
A fitted time schedule standing in for hidden state is not robust: where a true flow reads a hidden stock
and the found flow on its ends is a schedule of more pieces than the run announces eras, the result is
"fits" (note "fits, not robust: ..."), never a pass (_schedule_stand_ins).

**Behaviour.** skill@20 and skill@100 (sdlab/skill.py) on the run discovery saw and on a fresh run
(another seed), each with a 95% bootstrap interval over the start moments. Only the truth's truly
exogenous inflows are swapped in (skill.exogenous); a found model with a two-way flow or a signed
stock is run unfloored where it says so (sim.SignedModel).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from ..runner import multiplier
from ..skill import same_behaviour, truth_by_time, truth_runs
from .noise_oracle import make_hidden_oracle, make_oracle
from .parts import ONE, _hidden_chains, form_over, kind, label, linear_system, outside_end, outside_ends, parts, windows
from .substep import per_step
from . import hidden_match as _hidden_match
from . import merge as _merge
from . import sim as _sim

# A found move between stocks of one unit where the truth draws a link into B and an outflow from A of the
# same amount is the conserving drawing (algebra.bookkeeping). The user prefers it (2026-10-21), but the link
# cases (007, 045, 046, 054, 055, 010, ...) say in their `tests:` that the link IS the answer, so counting the
# move as the pass would change what those cases mean (CLAUDE.md rule 2): off until the user decides. It is
# then "equivalent" with the note; a truth's move drawn as a link and an outflow is "equivalent" too.
CONSERVING_PASS = False
DEFAULTS = {"rel": 0.10, "rel_exact": 0.02, "floor": 0.01, "floor_exact": 0.002, "spurious": 0.05, "z": 3.0}
HORIZONS = (20, 100)


def score_hash() -> str:
    """The scoring code: a change re-scores stored results (without re-running discovery)."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in (here / "score.py", here / "algebra.py", here / "parts.py", here / "merge.py", here / "hidden_match.py", here / "oracle.py", here / "hidden_oracle.py",
              here / "noise_oracle.py", here / "noise_kf.py", here / "substep.py", here / "sim.py", here.parent / "skill.py", here.parent / "sdtruth_expr.py", here.parent / "discovery" / "simulate.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---- the comparison ----

def _tolerances(case: dict, noise: str) -> dict:
    t = {**DEFAULTS, **(case.get("tolerance") or {})}
    exact = noise == "none"
    return {"rel": t["rel_exact"] if exact else t["rel"], "floor": t["floor_exact"] if exact else t["floor"], "spurious": t["spurious"], "z": t["z"]}


def _size(key: tuple, value, means: dict, among: dict) -> float:
    """A part's size: its flow amount per step (|k| x the mean level it reads; a co-flow's per x
    the amount of its flow; an effect counts as large)."""
    if key[0] in ("flow", "via"):
        return abs(value) * (1.0 if key[3] == ONE else means.get(key[3], 0.0))
    if key[0] == "hidden":
        if "k_in" not in value:                              # fed from outside: the amount through it
            return sum(_size(k, v, means, among) for k, v in among.items() if k[0] == "via" and k[2] == key[2])
        return abs(value["k_in"]) * means.get(key[1], 0.0)
    if key[0] == "smooth":                                   # reads a smoothing of x: about gain x x
        return abs(value["gain"]) * means.get(key[3], 0.0)
    if key[0] == "uses":
        return abs(value) * sum(_size(k, v, means, among) for k, v in among.items() if k[0] == "flow" and k[1:3] == key[1:3])
    return math.inf


def _levels_at(data: dict) -> list[dict]:
    """The state at the start of every step: every stock's level, and each measured input's value
    during the step (read as a stock is; the oracle's convention)."""
    lv = data.get("all_levels") or data["levels"]
    n = len(data["t"])
    ins = {k: v for k, v in (data.get("inputs") or {}).items() if k not in lv}
    return [{**{s: v[i] for s, v in lv.items()}, **{k: v[i + 1] for k, v in ins.items() if i + 1 < len(v)}} for i in range(n - 1)]


def _flow_amounts(flows: list[dict], data: dict, states: list[dict] | None = None) -> np.ndarray | None:
    """The amount per step of these flows together on the run's states (rate x effects, floored at 0
    as the engine does; no cap); None when a rate is not linear."""
    t = data["t"]
    states = states if states is not None else _levels_at(data)
    total = np.zeros(len(t) - 1)
    for f in [m for g in flows for m in ([g] if g.get("whole") else _merge.members_of(g))]:   # a merged flow as its originals
        if f.get("whole"):                                    # 2d: the engine's own rate (sim.py)
            total += _sim.amounts(f, data, states)
            continue
        for i, level in enumerate(states):
            lf = form_over(f, t[i + 1], t[i + 1])
            if lf is None:
                return None
            rate = max(0.0, lf[0] + sum(k * level.get(j, 0.0) for j, k in lf[1].items()))
            total[i] += rate * multiplier(f, level)
    return total


def _amounts(flows: list[dict], ends: tuple, measured: set, data: dict, net: bool = False) -> np.ndarray | None:
    """The amount per step of the flows between `ends` on the run's states (rate x effects, floored
    at 0 as the engine does; no cap); net (a two-way flow, 2d): less the flows the other way."""
    at = lambda f: ((f.get("from") if f.get("from") in measured else None), (f.get("to") if f.get("to") in measured else None))  # noqa: E731
    sel = [f for f in flows if not f.get("via") and at(f) == ends]
    out = _flow_amounts(sel, data)
    if net and out is not None:
        back = _flow_amounts([f for f in flows if not f.get("via") and at(f) == ends[::-1]], data)
        out = None if back is None else out - back
    return out


def _path_inflow(flows: list[dict], b: str, measured: set) -> list[dict]:
    """The flows that feed a hidden path from outside into b (a chain's first flow, or a found `via`
    flow from outside)."""
    chains, _ = _hidden_chains(flows, measured)
    out = list((chains.get((None, b)) or {}).get("in") or [])
    return out + [f for f in flows if f.get("via") and not f.get("from") and f.get("to") == b]


def _close(true: float, found: float, reader: str | None, tol: dict, means: dict, scale: float, se: float | None = None) -> tuple[bool, float]:
    """Within tolerance (relative, the floor, or z standard errors of the oracle), and the relative
    error (absolute when the true number is 0)."""
    level = 1.0 if reader in (None, ONE) else max(1e-9, means.get(reader, 0.0))
    allowed = max(tol["rel"] * abs(true), tol["floor"] * scale / level, tol["z"] * (se or 0.0))
    err = abs(found - true)
    return err <= allowed + 1e-12, (err / abs(true) if true else err)


def equations(case: dict, noise: str, truth_model: dict, found_flows: list[dict], data: dict) -> dict:
    """Equation recovery: {status, pass, equivalent, fits, recall, precision, parts: [...], spurious: [...],
    notes, algebra?}. status is "pass", "equivalent", "fits" or "fail"."""
    tol = _tolerances(case, noise)
    notes: list[str] = []
    measured = set(data["levels"])
    ids = list(data["levels"])
    lv = data.get("all_levels") or data["levels"]
    means = {s: float(np.mean(v)) if len(v) else 0.0 for s, v in lv.items()}
    inputs = set(data.get("inputs") or {}) - set(lv)          # measured inputs: read as stocks are
    means.update({k: float(np.mean(v)) if len(v) else 0.0 for k, v in (data.get("inputs") or {}).items() if k in inputs})
    t = data["t"]
    wins = windows(truth_model, t)
    truth_flows, _ = truth_by_time(truth_model, t)
    truth_flows, _ = per_step(truth_flows, data, truth_model)      # a truth at a sub-step: its per-recorded-step numbers (substep.py)
    truth_flows = _sim.mark(truth_flows, truth_model)             # 2d's expression, two-way, auxiliary and switch flows: compared as a whole
    # (2026-10-21, the user) a found model's own hidden stock matched to the truth's (hidden_match.py): written in its
    # coordinates and scored as a measured stock is; `seen` is the measured stocks and the matched hidden ones
    found_flows, hmatch, hnotes = _hidden_match.match(truth_flows, found_flows, data, measured, inputs)
    notes += hnotes
    seen = measured | set(hmatch)
    found_flows = _merge.flows(found_flows)                         # flows between the same two stocks are one flow (merge.py)
    notes += [f"found: {x}" for x in _merge.notes(found_flows)]
    found_flows = _sim.mark_found(found_flows, truth_model)
    effect_ends = {(f.get("from") if f.get("from") in seen else None, f.get("to") if f.get("to") in seen else None)
                   for f in truth_model["flows"] if f.get("effects")}
    ends_of = lambda f: (f.get("from") if f.get("from") in seen else None, f.get("to") if f.get("to") in seen else None)  # noqa: E731
    whole_ends = {ends_of(f) for f in truth_flows if f.get("whole")}
    two_way_ends = {ends_of(f) for f in truth_flows if f.get("whole") and f.get("two_way")}
    loose = whole_ends | {e[::-1] for e in two_way_ends}          # found parts on these ends are compared within the whole, never spurious
    effect_ends = effect_ends | whole_ends
    true_w, found_w = [], []
    for w in wins:
        tp, tn = parts(truth_flows, seen, w, inputs)
        fp, fn = parts(found_flows, seen, w, inputs)
        true_w.append(tp)
        found_w.append(fp)
        notes += [f"truth: {x}" for x in tn] + [f"found: {x}" for x in fn]
    weights = np.array([b - a + 1 for a, b in wins], dtype=float)
    weights /= weights.sum()
    true_keys = list(dict.fromkeys(k for tp in true_w for k in tp))
    found_keys = list(dict.fromkeys(k for fp in found_w for k in fp))
    sizes = [sum(wt * _size(k, tp[k], means, tp) for wt, tp in zip(weights, true_w) if k in tp) for k in true_keys]
    finite = [s for s in sizes if math.isfinite(s) and s > 0]
    scale = float(np.median(finite)) if finite else 1.0

    oracle = make_oracle(truth_flows, data, wins)                  # noise_oracle.py: the Kalman-scaled one for noise.py's variants
    hidden = make_hidden_oracle(truth_flows, data, wins, noise) if not oracle.ok and any(k[0] == "hidden" for k in true_keys) else None
    function_check: dict[tuple, tuple[bool, float]] = {}
    for ends in effect_ends:
        want = _amounts(truth_flows, ends, seen, data, net=ends in two_way_ends)
        try:
            got = _amounts(found_flows, ends, seen, data, net=ends in two_way_ends)
        except Exception:                                          # noqa: BLE001 (a found rate reading a stock the run does not have:
            got = None                                             # its own hidden stock, unmatched; hidden_match.py)
        if want is None or got is None:
            function_check[ends] = (False, math.inf)
            continue
        err = float(np.sqrt(np.mean((got - want) ** 2)) / max(1e-9, np.sqrt(np.mean(want ** 2))))
        function_check[ends] = (err <= tol["rel"], err)
    # a hidden path fed from outside by a flow with effects: what feeds it compared as a whole
    for b in {k[2] for k in true_keys if k[0] == "viaeffect"}:
        want = _flow_amounts(_path_inflow(truth_flows, b, measured), data)
        got = _flow_amounts(_path_inflow(found_flows, b, measured), data)
        if want is None or got is None:
            function_check[("via", b)] = (False, math.inf)
            continue
        err = float(np.sqrt(np.mean((got - want) ** 2)) / max(1e-9, np.sqrt(np.mean(want ** 2))))
        function_check[("via", b)] = (err <= tol["rel"], err)

    rows = []
    for k in true_keys:
        row = {"key": label(k), "kind": kind(k), "found": k in found_keys}
        if k[0] == "whole":                                       # 2d: any found flow between its stocks (either way for a two-way one)
            row["found"] = any(fk[0] in ("flow", "uses", "effect", "whole") and ((fk[1], fk[2]) == (k[1], k[2]) or ((k[1], k[2]) in two_way_ends
                                                                                                    and (fk[1], fk[2]) == (k[2], k[1]))) for fk in found_keys)
            ok, err = function_check[(k[1], k[2])]
            row.update(true=_show(true_w[0].get(k)), found_value=None, ok=bool(row["found"] and ok), error=err,
                       compared="as a whole flow (an expression, a two-way flow, or one that reads an auxiliary or a switch)")
        elif k[0] == "effect" or (k[0] in ("flow", "uses") and (k[1], k[2]) in effect_ends):
            ok, err = function_check[(k[1], k[2])]
            row.update(true=_show(true_w[0].get(k)), found_value=_show(next((fp[k] for fp in found_w if k in fp), None)),
                       ok=bool(row["found"] and ok), error=err, compared="as a whole flow (effects)")
        elif k[0] == "viaeffect" or (k[0] == "via" and ("via", k[2]) in function_check):
            ok, err = function_check[("via", k[2])]
            row.update(true=_show(true_w[0].get(k)), found_value=_show(next((fp[k] for fp in found_w if k in fp), None)),
                       ok=bool(row["found"] and ok), error=err, compared="as a whole flow (effects on a hidden path's inflow)")
        elif k[0] == "smooth":                                     # a rate reading a smoothing: its gain as a number, its delay within rel
            oks, errs = [], []
            for tp, fp in zip(true_w, found_w):
                if k not in tp:
                    continue
                if k not in fp:
                    oks.append(False)
                    continue
                o1, e1 = _close(tp[k]["gain"], fp[k]["gain"], k[3], tol, means, scale)
                o2 = abs(fp[k]["delay"] - tp[k]["delay"]) <= tol["rel"] * tp[k]["delay"] + 1e-9
                oks.append(o1 and o2)
                errs.append(max(e1, abs(fp[k]["delay"] - tp[k]["delay"]) / max(1e-9, tp[k]["delay"])))
            row.update(true=true_w[0].get(k), found_value=next((fp[k] for fp in found_w if k in fp), None), ok=bool(oks) and all(oks),
                       error=max(errs) if errs else None, compared="gain and delay of the smoothing the rate reads")
        elif k[0] == "hidden":
            oks, errs, ses = [], [], []
            for w, (tp, fp) in enumerate(zip(true_w, found_w)):
                if k not in tp:
                    continue
                hse = (hidden.hidden_se(k, w) if hidden else None) or {}
                ses.append(hse or None)
                if k not in fp:
                    oks.append(False)
                    continue
                if "k_in" in tp[k]:
                    o1, e1 = _close(tp[k]["k_in"], fp[k].get("k_in", 0.0), k[1], tol, means, scale, hse.get("k_in"))
                else:                                       # fed from outside: its inflow's numbers are parts of their own ("via")
                    o1, e1 = True, 0.0
                allowed = max(tol["rel"] * tp[k]["delay"], tol["z"] * (hse.get("delay") or 0.0)) if math.isfinite(tp[k]["delay"]) else -1.0
                o2 = abs(fp[k]["delay"] - tp[k]["delay"]) <= allowed + 1e-9
                oks.append(o1 and o2)
                errs.append(max(e1, abs(fp[k]["delay"] - tp[k]["delay"]) / max(1e-9, tp[k]["delay"])))
            row.update(true=true_w[0].get(k), found_value=next((fp[k] for fp in found_w if k in fp), None), ok=bool(oks) and all(oks),
                       error=max(errs) if errs else None, se_hidden=ses[0] if hidden and hidden.ok and ses else None)
        else:
            oks, errs, ses = [], [], []
            for w, (tp, fp) in enumerate(zip(true_w, found_w)):
                se = oracle.part_se(k, true_keys, w) if oracle.ok else hidden.part_se(k, w) if hidden else None
                ok, err = _close(float(tp.get(k, 0.0)), float(fp.get(k, 0.0)), k[3] if k[0] in ("flow", "via") else None, tol, means, scale, se)
                oks.append(ok)
                errs.append(err)
                ses.append(se)
            tv = [float(tp.get(k, 0.0)) for tp in true_w]
            fv = [float(fp.get(k, 0.0)) for fp in found_w]
            row.update(true=_one(tv, weights), found_value=_one(fv, weights) if row["found"] else None,
                       ok=bool(row["found"] and all(oks)), error=max(errs), windows=len(wins) if len(wins) > 1 else None,
                       se=_one([x if x is not None else math.nan for x in ses], weights) if oracle.ok or (hidden and hidden.ok) else None)
        rows.append(row)

    spurious, extra = [], []
    boundary = case.get("boundary")                                # declared (2026-10-20): outside flows only where it has them
    declared = None if boundary is None else {(st, side) for st, e in boundary.items() for side in ("in", "out") if e.get(side)}
    invented: set[tuple[str, str]] = set()
    altered: list[tuple[str, str]] = []
    for k in found_keys:
        if k in true_keys or (k[0] in ("flow", "uses", "effect") and (k[1], k[2]) in loose):
            continue
        size = sum(wt * _size(k, fp[k], means, fp) for wt, fp in zip(weights, found_w) if k in fp)
        # an extra term is spurious when it is large, and (with an oracle) clearly more than the data's
        # noise could make of a term that is not there: |k| above z standard errors in every window it is in
        if k[0] == "flow" and oracle.ok:
            ses = [oracle.part_se(k, true_keys, w) for w, fp in enumerate(found_w) if k in fp]
            noise_only = all(s is not None and abs(fp[k]) <= tol["z"] * s for s, fp in zip(ses, [fp for fp in found_w if k in fp]))
        else:
            noise_only = False
        entry = {"key": label(k), "kind": kind(k), "value": _show(_one([float(fp.get(k, 0.0)) for fp in found_w], weights) if k[0] in ("flow", "uses", "via")
                                                                   else next(fp[k] for fp in found_w if k in fp)), "size": size}
        end = outside_end(k) if declared is not None else None
        if end and end[0] in measured and end not in declared and size != 0:   # an outside flow the boundary lacks (a hidden stock is inside it)
            invented.add(end)
            spurious.append({**entry, "kind": "invented boundary"})
            continue
        (spurious if size > tol["spurious"] * scale and not noise_only else extra).append(entry)
    if declared is not None:                                       # outside flows reaching a measured stock through the found model's own unmeasured stocks
        direct = lambda f: (not f.get("from") and f.get("to") in measured) or (not f.get("to") and f.get("from") in measured)  # noqa: E731
        for end in sorted(outside_ends([f for f in found_flows if not direct(f)], measured) - declared - invented):
            invented.add(end)
            spurious.append({"key": f"outside -> (unmeasured) -> {end[0]}" if end[1] == "in" else f"{end[0]} -> (unmeasured) -> outside",
                             "kind": "invented boundary", "value": None, "size": None})
        notes += [f"invented boundary: an outside {'inflow to' if side == 'in' else 'outflow from'} {st}, which the case's boundary does not have"
                  for st, side in sorted(invented)]
        # (2026-10-21, the user) one found outside flow per declared flow: a second one on a declared side is invented
        internal = [f for f in found_flows if f.get("from") and f.get("to")]
        count: dict = {}
        for f in found_flows:
            if bool(f.get("from")) != bool(f.get("to")):
                for end in outside_ends([f] + internal, measured):
                    count[end] = count.get(end, 0) + 1
        for (st, side), n in sorted(count.items()):
            allowed = len((boundary.get(st) or {}).get(side) or [])
            if allowed and n > allowed and (st, side) not in invented:
                invented.add((st, side))
                spurious.append({"key": f"{n} outside {'inflows to' if side == 'in' else 'outflows from'} {st}", "kind": "invented boundary",
                                 "value": None, "size": None})
                notes.append(f"invented boundary: {n} outside {'inflows to' if side == 'in' else 'outflows from'} {st}, which the case's "
                             f"boundary declares {allowed} of (one flow per declared side)")
        altered = _input_altered(boundary, truth_model, true_w, found_w, inputs)
        notes += [f"input altered: the outside inflow to {st} {why}" for st, why in altered]
    big_found = [k for k in found_keys if k in true_keys] + [e for e in spurious]
    recall = sum(r["found"] for r in rows) / len(rows) if rows else 1.0
    precision = (sum(1 for k in found_keys if k in true_keys) / len(big_found)) if big_found else (1.0 if not rows else 0.0)
    passed = all(r["ok"] for r in rows) and not spurious and not altered
    equivalent = False
    if not passed and effect_ends and not any(k[0] == "hidden" for k in true_keys):
        equivalent = _same_function(truth_flows, found_flows, ids, data, tol)
    elif not passed and not effect_ends and not any(k[0] == "hidden" for k in true_keys):
        equivalent = True
        cols = ids + sorted(inputs)                                # a measured input is a column as a level is
        for w in wins:
            T, F = linear_system(truth_flows, cols, w), linear_system(found_flows, cols, w)
            if T is None or F is None or not _same_system(T, F, ids, cols, tol, means, scale, oracle, wins.index(w)):
                equivalent = False
                break
    if invented or altered:                                        # never equivalent: "A -> outside" + "outside -> B" is not the move A -> B,
        equivalent = False                                         # and a rescaled input is not the measured series
    # (the user, 2026-10-21) the data cannot tell them apart; equivalent only when every net rate is proven
    # the truth's for every state (algebra.py), else "fits"; the conserving drawing of a proven one is the pass
    proof, book, fits = None, None, False
    if equivalent:
        proof, book = _prove(truth_model, truth_flows, found_flows, ids, wins, inputs, data, tol, means, scale, oracle, true_w, found_w)
        if not proof["equivalent"]:
            equivalent, fits = False, True
            notes.append("fits, not proven equivalent: " + _why_not(proof))
        elif book["unit_moves"]:
            equivalent = False
            notes.append("units: " + book["note"])
        elif book["conserving"] and CONSERVING_PASS:
            equivalent, passed = False, True
            notes.append("pass by the conserving drawing: " + book["note"])
        else:
            notes.append("equivalent (proven): " + book["note"])
    # (2026-10-21, the user) a fitted time schedule standing in for hidden state is not robust: "fits", never a pass
    stand_ins = _schedule_stand_ins(truth_model, truth_flows, found_flows, seen, inputs, data)
    if stand_ins and (passed or equivalent):
        passed, equivalent, fits = False, False, True
        notes += [f"fits, not robust: {x}" for x in stand_ins]
    status = "pass" if passed else "equivalent" if equivalent else "fits" if fits else "fail"
    out = {"status": status, "pass": passed, "equivalent": equivalent, "fits": fits, "recall": recall, "precision": precision,
           "right": sum(r["ok"] for r in rows), "of": len(rows), "parts": rows, "spurious": spurious, "negligible": extra,
           "windows": len(wins), "tolerance": tol, "scale": scale, "notes": sorted(set(notes))}
    if proof is not None:
        out["algebra"] = {k: proof[k] for k in ("equivalent", "proven", "method", "regions", "differences", "notes")}
        if book is not None:
            out["algebra"]["bookkeeping"] = book["note"]
            out["algebra"]["conserving"] = book["conserving"]
    if hmatch:
        out["hidden_match"] = hmatch
    if stand_ins:
        out["schedule_stand_ins"] = stand_ins
    if declared is not None:                                       # an undeclared case's scores are as before
        out.update(boundary_declared=True, invented_boundary=len(invented))
        if altered:
            out["input_altered"] = len(altered)
    return out


def _truth_reads(f: dict, aux) -> set[str]:
    """The names a true flow reads, through its auxiliaries too (an auxiliary's expression read in turn)."""
    exprs = {}
    for a in (aux.items() if isinstance(aux, dict) else ((x.get("id"), x) for x in aux or [])):
        name, v = a
        exprs[name] = v if isinstance(v, str) else str((v or {}).get("expr") or (v or {}).get("rate") or v)
    out, todo = set(), list(_hidden_match._reads(f))
    while todo:
        x = todo.pop()
        if x in out:
            continue
        out.add(x)
        if x in exprs:
            todo += _hidden_match.re.findall(r"[A-Za-z_][A-Za-z0-9_]*", exprs[x])
    return out


def _schedule_stand_ins(truth_model, truth_flows, found_flows, seen, inputs, data) -> list[str]:
    """(2026-10-21, the user) The true flows that read a hidden stock the found model does not read in its place
    (not one of its own hidden stocks matched to it), drawn by a found flow between the same ends as a schedule
    in time of more pieces than the run announces eras (or the truth's own schedule of that flow has): such a
    schedule fits the one run it was fitted on and cannot predict another (kalman_lna's 30 blocks for 310's
    leak). Notes, one per such flow."""
    hidden = set(data.get("all_levels") or {}) - set(data["levels"]) - set(inputs)
    if not hidden:
        return []
    eras = max(1, len(data.get("eras") or []))
    aux = truth_model.get("auxiliaries") or {}
    ends = lambda f: (f.get("from") if f.get("from") in seen else None, f.get("to") if f.get("to") in seen else None)  # noqa: E731
    out = []
    for f in truth_flows:
        reads = _truth_reads(f, aux) & hidden
        if not reads or (f.get("from") in hidden and f.get("from") not in seen) or (f.get("to") in hidden and f.get("to") not in seen):
            continue
        allowed = max(eras, len(f.get("byTime") or []) or 1)
        for g in found_flows:
            if ends(g) != ends(f) or g.get("via"):
                continue
            pieces = len(g.get("byTime") or g.get("inflow") or [])
            own = _hidden_match._reads(g) & seen & reads
            if pieces > allowed and not own:
                a, b = ends(f)
                out.append(f"{a or 'outside'} -> {b or 'outside'} reads hidden {', '.join(sorted(reads))} in the truth; the found flow "
                           f"stands in for it with a schedule of {pieces} pieces in time (the run announces {eras} era"
                           f"{'s' if eras != 1 else ''}), which fits this run and cannot predict another")
    return sorted(set(out))


def _prove(truth_model, truth_flows, found_flows, ids, wins, inputs, data, tol, means, scale, oracle, true_w, found_w) -> tuple[dict, dict | None]:
    """algebra.check with the scorer's tolerance for each coefficient (a linear one as _same_system compares it,
    with the oracle's standard error; a product's against the product of the mean levels it reads), and, when
    proven, algebra.bookkeeping on the parts."""
    from . import algebra as _algebra

    def coef_close(row: str, mono: tuple, a: float, b: float, w: int) -> bool:
        if not mono:
            return _close(a, b, None, tol, means, scale, oracle.se(row, ONE, w))[0]
        if len(mono) == 1 and not mono[0].startswith("@"):
            return _close(a, b, mono[0], tol, means, scale, oracle.se(row, mono[0], w))[0]
        level = max(1e-9, float(np.prod([means.get(m, 1.0) if not m.startswith("@") else 1.0 for m in mono])))
        return abs(a - b) <= max(tol["rel"] * abs(a), tol["floor"] * scale / level) + 1e-12

    def part_close(key: tuple, a: float, b: float) -> bool:
        return _close(a, b, key[3] if key[0] in ("flow", "via") else None, tol, means, scale)[0]

    signed = {s["id"] for s in truth_model.get("stocks") or [] if s.get("signed")} | _sim.signed_stocks(found_flows)
    proof = _algebra.check(truth_flows, found_flows, ids, wins, inputs=sorted(inputs), states=_levels_at(data), close=coef_close,
                           rel=tol["rel"], aux=truth_model.get("auxiliaries"), signed=signed)
    if not proof["equivalent"]:
        return proof, None
    units = {s["id"]: s.get("unit") for s in truth_model.get("stocks") or []}
    return proof, _algebra.bookkeeping(true_w, found_w, units, part_close)


def _why_not(proof: dict) -> str:
    if not proof["proven"]:
        return f"not covered by the algebra ({'; '.join(proof['notes']) or proof['method']})"
    d = proof["differences"][0]
    at = ", ".join(f"{k}={v:.4g}" for k, v in sorted(d.get("at", {}).items()))
    if d.get("exact"):
        return f"the net rate of {d['stock']} differs in the region around {at}"
    return (f"the net rate of {d['stock']} differs in the region around {at} (window {d['window'][0]}-{d['window'][1]}): "
            f"its {d['term']} term is {d['truth']:.4g} in the truth, {d['found']:.4g} found")


INPUT_REL = 1e-6       # an "input" inflow's gain is 1 up to float rounding (2026-10-21, the user)


def own_gain(truth_model: dict, stock: str, name: str) -> float:
    """What the truth's input inflows into stock carry of input name per unit of it (their count)."""
    from .caseformat import input_inflows
    return float(sum(1 for f in input_inflows(truth_model, stock)
                     if ((f.get("rate") or {}).get("stock") or ((f.get("rate") or {}).get("terms") or [{}])[0].get("stock")) == name))


def _input_altered(boundary: dict, truth_model: dict, true_w: list[dict], found_w: list[dict], inputs: set) -> list[tuple[str, str]]:
    """(2026-10-21, the user) A side declared "input" is fed by the measured series itself, exactly 1 x it:
    per such stock, the found model's gain on the input of each of the truth's "input" inflows there must
    equal the truth's (1) within INPUT_REL in every window (an input another true inflow on the side reads
    too is left to the ordinary tolerance), and, where every inflow declared on the side is an "input",
    the found inflows there may hold nothing else (no constant, piece, other term, effect or co-flow).
    Returns [(stock, why)] for the sides that break it."""
    from .caseformat import input_inflows
    out = []
    for st, e in sorted(boundary.items()):
        kinds = e.get("in") or []
        if "input" not in kinds:
            continue
        only = all(k == "input" for k in kinds)
        own = {(f.get("rate") or {}).get("stock") or ((f.get("rate") or {}).get("terms") or [{}])[0].get("stock") for f in input_inflows(truth_model, st)}
        why = None
        for tp, fp in zip(true_w, found_w):
            gains = {k: v for k, v in tp.items() if k[0] == "flow" and k[1] is None and k[2] == st and k[3] in inputs & own
                     and abs(float(v) - own_gain(truth_model, st, k[3])) <= 1e-12}
            for k, v in gains.items():
                got = fp.get(k)
                if got is None or abs(float(got) - float(v)) > INPUT_REL * max(1.0, abs(float(v))):
                    why = f"reads {k[3]} x {got if got is None else f'{float(got):.6g}'}, not x {float(v):.6g}"
                    break
            if why is None and only:
                extra = [k for k, v in fp.items() if outside_end(k) == (st, "in") and k not in gains
                         and not (isinstance(v, (int, float)) and abs(float(v)) <= 1e-12)]
                if extra:
                    why = f"has {label(extra[0])} beside the input"
            if why:
                break
        if why:
            out.append((st, why))
    return out


def _changes(flows: list[dict], ids: list[str], data: dict, states: list[dict]) -> tuple[np.ndarray, np.ndarray] | None:
    """Every measured stock's change per step that these flows make on the run's states, and the gross
    amount through it (every flow in or out, summed); None when a flow touches a stock that is not
    measured or a rate is not linear."""
    idx = {s: i for i, s in enumerate(ids)}
    change, gross = np.zeros((len(ids), len(states))), np.zeros((len(ids), len(states)))
    for f in _merge.members(flows):                                   # a merged flow as its originals: each co-flow on its own flow
        if f.get("via") or (f.get("from") and f["from"] not in idx) or (f.get("to") and f["to"] not in idx):
            return None
        q = _flow_amounts([f], data, states)
        if q is None:
            return None
        signs = [(f.get("to"), 1.0), (f.get("from"), -float(f.get("ratio") or 1))]
        signs += [(u.get("stock"), -float(u.get("per") or 0)) for u in f.get("uses") or [] if u.get("stock") in idx]
        for st, sign in signs:
            if st:
                change[idx[st]] += sign * q
                gross[idx[st]] += abs(sign) * q
    return change, gross


def _same_function(truth_flows: list[dict], found_flows: list[dict], ids: list[str], data: dict, tol: dict) -> bool:
    """Equivalence for a truth with effects (the user, 2026-10-19): the found flows compute the same
    change of every measured stock as the truth's on the run's states (rate x effects, floored at 0;
    measured inputs read as levels), within the relative tolerance of that stock's change:
    rms(found change - true change) <= rel x rms(true change). Two parametrisations of one function
    (a product with its roles swapped, a move seen as an outflow and an inflow of the same amount)
    are equivalent. (Measured against the gross amount through a stock instead, a model with no flows
    at all came within 10% of a logistic stock whose births and deaths nearly cancel: too loose.)"""
    states = _levels_at(data)
    T = _changes(truth_flows, ids, data, states)
    if T is None:
        return False
    try:
        F = _changes(found_flows, ids, data, states)
    except Exception:                                              # noqa: BLE001 (reads a stock the run does not have)
        return False
    if F is None:
        return False
    (ct, _), (cf, _) = T, F
    for i in range(len(ids)):
        g = float(np.sqrt(np.mean(ct[i] ** 2)))
        if float(np.sqrt(np.mean((cf[i] - ct[i]) ** 2))) > tol["rel"] * g + 1e-12:
            return False
    return True


def _same_system(T, F, ids, cols, tol, means, scale, oracle, w) -> bool:
    """Every measured stock's change the same function of the levels, the measured inputs and the
    outside (rows: the measured stocks; columns: the levels, then the inputs)."""
    (Bt, ut), (Bf, uf) = T, F
    for i, row in enumerate(ids):
        if not _close(ut[i], uf[i], None, tol, means, scale, oracle.se(row, ONE, w))[0]:
            return False
        for j, s in enumerate(cols):
            if not _close(Bt[i, j], Bf[i, j], s, tol, means, scale, oracle.se(row, s, w))[0]:
                return False
    return True


def _one(values: list[float], weights: np.ndarray):
    """One number for a part over the windows: the value if it never changes, else per window."""
    if all(abs(v - values[0]) < 1e-12 for v in values):
        return values[0]
    return {"mean": float(np.dot(values, weights)), "per_window": values if len(values) <= 12 else None}


def _show(v):
    if isinstance(v, dict) and v.get("shape"):
        return {k: v[k] for k in ("shape", "normal", "max", "min", "points") if k in v}
    return v


# ---- behaviour ----

def behaviour(truth_model: dict, found_flows: list[dict], data: dict, fresh: dict | None, inferred: dict | None = None) -> dict:
    """skill@20 / @100 with 95% bootstrap intervals, in-sample and (if given) on a fresh run. A found
    model's own unmeasured stocks start from its estimate of their levels (`inferred`) on the run it
    saw, and from the estimate it gives from the fresh run's levels on the fresh run."""
    out = {}
    for name, d in (("in_sample", data), ("fresh", fresh)):
        if d is None:
            continue
        res = {}
        for h in HORIZONS:
            if len(d["t"]) < h + 10:
                continue
            tr = truth_runs(truth_model, d, horizon=h)
            result = {"flows": found_flows, **({"inferred_levels": inferred} if inferred and name == "in_sample" else {})}
            b = same_behaviour(result, truth_model, d, horizon=h, truth=tr, ci=True, own_run=name == "in_sample")
            res[str(h)] = {"skill": _finite(b["skill"]), "ci": [_finite(x) for x in b["ci"]] if b.get("ci") else None, "moved": _finite(b["moved"])}
        out[name] = res
    return out


def _finite(x):
    x = float(x)
    return x if math.isfinite(x) else None


def score(case: dict, noise: str, truth_model: dict, found_flows: list[dict], data: dict, fresh: dict | None = None,
          inferred: dict | None = None) -> dict:
    """Everything the ladder records for one found model: equations and behaviour."""
    eq = equations(case, noise, truth_model, found_flows, data)
    return {**eq, "behaviour": behaviour(truth_model, found_flows, data, fresh, inferred)}
