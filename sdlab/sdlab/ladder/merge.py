"""Flows between the same two stocks are one flow (the user, 2026-10-20). In system dynamics the
material moving from A to B (outside counts as an end) is one flow whose rate is the sum of its parts;
several same-pair flows of the same form are one process split arbitrarily. Before scoring, counting
complexity and drawing, a found model's flows with the same (from, to) are merged into one flow whose
rate is the sum of their rates: terms reading the same stock combine into one coefficient, constants
add, and pieces (outside inflow pieces, byTime spans) are laid over the union of their spans, each
span the sum of what every flow does there.

Nothing attached to a flow is hidden: the merged flow carries every co-flow ("uses") of the flows it
merges, so each is still a part and still scored, and keeps the originals (`merged["flows"]`, with an
annotation `merged["note"]`: "merged from 2 flows: 0.249*inflight + 0.244*inflight"). A flow that
cannot be summed into one rate the scorer reads (effects multiply its rate; a hidden stock (`via`), a
ratio, a two-way flow, an expression or another rate that is not linear) stays a flow of its own, and
says so (`apart`). What runs the flows (the scorer's linear system and amounts, behaviour) uses the
originals (`members`), so the merge changes how a model is cut into parts and counted, never what it
computes.
"""

from __future__ import annotations

from .parts import linear_form

LINEAR = ("constant", "proportional", "gap", "linear")


def _num(v: float) -> str:
    return f"{v:.3g}"


def _why_apart(f: dict) -> str | None:
    """Why a flow cannot be summed with others into one rate, or None if it can."""
    if f.get("merged"):
        return None
    if f.get("via"):
        return "it runs through a hidden stock (via)"
    if f.get("effects"):
        return "its rate is multiplied by effects"
    if float(f.get("ratio") or 1) != 1:
        return f"it has a ratio of {_num(float(f['ratio']))}"
    if f.get("two_way") or f.get("whole"):
        return "it is a two-way or whole flow"
    if isinstance(f.get("delay"), dict):
        return "it is a stage of a delay"
    rates = [g.get("rate") for g in f.get("byTime") or []] if f.get("byTime") and not f.get("inflow") else [] if f.get("inflow") else [f.get("rate")]
    bad = [(r or {}).get("form") for r in rates if (r or {}).get("form") not in LINEAR]
    if bad:
        return f"its rate ({bad[0]}) is not a sum of terms"
    return None


def _text(c: float, ks: dict[str, float]) -> str:
    bits = [f"{_num(k)}*{j}" for j, k in ks.items()]
    if c or not bits:
        bits.insert(0, _num(c))
    return " + ".join(bits).replace("+ -", "- ")


def describe(f: dict) -> str:
    """A flow's rate in a few words (and its co-flows), for the annotation."""
    uses = "".join(f" (uses {_num(float(u.get('per') or 0))} {u.get('stock')})" for u in f.get("uses") or [])
    return _rate_words(f) + uses


def _rate_words(f: dict) -> str:
    if f.get("inflow"):
        return f"inflow in {len(f['inflow'])} pieces" if len(f["inflow"]) > 1 else _num(max(0.0, float(f["inflow"][0].get("value") or 0)))
    if f.get("byTime") and len(f["byTime"]) > 1:
        return f"by time ({len(f['byTime'])} spans)"
    rate = f["byTime"][0]["rate"] if f.get("byTime") else f.get("rate")
    lf = linear_form(rate)
    return _text(*lf) if lf else str((rate or {}).get("form"))


def _rate(c: float, ks: dict[str, float]) -> dict:
    ks = {j: k for j, k in ks.items() if k}
    if not ks:
        return {"form": "constant", "value": c}
    if not c and len(ks) == 1:
        (j, k), = ks.items()
        return {"form": "proportional", "stock": j, "k": k}
    return {"form": "linear", "c": c, "terms": [{"stock": j, "k": k} for j, k in ks.items()]}


def _segs(f: dict) -> list[dict] | None:
    return f.get("inflow") or f.get("byTime") or None


def _at(f: dict, t: int) -> tuple[float, dict[str, float]]:
    """A summable flow's linear form at step t (parts.form_over over one step)."""
    from .parts import form_over
    return form_over(f, t, t)


def _add(into: tuple[float, dict], lf: tuple[float, dict]) -> tuple[float, dict]:
    c, ks = into
    ks = dict(ks)
    for j, k in lf[1].items():
        ks[j] = ks.get(j, 0.0) + k
    return c + lf[0], ks


def _merge_group(group: list[dict]) -> dict:
    a, b = group[0].get("from") or None, group[0].get("to") or None
    pieced = [f for f in group if _segs(f)]
    out: dict = {"from": a, "to": b, "ratio": 1}
    if pieced:                                           # pieces laid over the union of their spans
        starts = sorted({int(g["from"]) for f in pieced for g in _segs(f)})
        end = max(int(g["to"]) for f in pieced for g in _segs(f))
        spans = []
        for i, s in enumerate(starts):
            lf: tuple[float, dict] = (0.0, {})
            for f in group:
                lf = _add(lf, _at(f, s))
            spans.append({"from": s, "to": starts[i + 1] - 1 if i + 1 < len(starts) else end, "rate": _rate(*lf)})
        out["byTime"] = spans
        out["rate"] = spans[0]["rate"]
    else:
        lf = (0.0, {})
        for f in group:
            lf = _add(lf, linear_form(f.get("rate")))
        out["rate"] = _rate(*lf)
    uses = [u for f in group for u in f.get("uses") or []]
    if uses:
        out["uses"] = uses
    members = [m for f in group for m in members_of(f)]
    note = f"merged from {len(members)} flows: " + " + ".join(describe(m) for m in members)
    out["merged"] = {"of": len(members), "note": note, "flows": members}
    out["note"] = note
    return out


def members_of(f: dict) -> list[dict]:
    """The original flows a (merged) flow stands for."""
    return list(f["merged"]["flows"]) if f.get("merged") else [f]


def members(flows: list[dict]) -> list[dict]:
    """The original flows of a model whose same-pair flows were merged (what runs them)."""
    return [m for f in flows or [] for m in members_of(f)]


def flows(found: list[dict] | None) -> list[dict]:
    """The flows with every same-pair group of summable flows merged into one (in the place of the
    group's first flow); a flow kept apart from others between the same stocks carries `apart`
    (why). Idempotent; a model with no same-pair flows comes back unchanged (the same list)."""
    found = found or []
    groups: dict[tuple, list[int]] = {}
    for i, f in enumerate(found):
        groups.setdefault((f.get("from") or None, f.get("to") or None), []).append(i)
    if all(len(ix) == 1 for ix in groups.values()):
        return found
    replace: dict[int, dict | None] = {}
    for (a, b), ix in groups.items():
        if len(ix) == 1 or (a is None and b is None):
            continue
        ok = [i for i in ix if _why_apart(found[i]) is None]
        apart = [i for i in ix if i not in ok]
        if len(ok) > 1:
            replace[ok[0]] = _merge_group([found[i] for i in ok])
            replace.update({i: None for i in ok[1:]})
        for i in apart:
            why = _why_apart(found[i])
            n = len(ix) - 1
            replace[i] = {**found[i], "apart": f"kept apart from the other {a or 'outside'} -> {b or 'outside'} flow{'s' if n > 1 else ''}: {why}"}
    out = []
    for i, f in enumerate(found):
        if i in replace:
            if replace[i] is not None:
                out.append(replace[i])
        else:
            out.append(f)
    return out


def notes(merged: list[dict]) -> list[str]:
    """What the merge did, one line per merged or kept-apart flow."""
    end = lambda x: x or "outside"  # noqa: E731
    return [f"{end(f.get('from'))} -> {end(f.get('to'))}: {f['merged']['note'] if f.get('merged') else f['apart']}"
            for f in merged if f.get("merged") or f.get("apart")]
