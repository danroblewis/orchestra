"""What would make a found model right: the scorer's comparison (score.py) read as a list of repairs,
for the strategy page (/ladder/strategy). Pure: from a result's scores and, when there is one, the
case's analysis (analysis.py: the best achievable accuracy and the equivalent structures).

    repairs(scores, analysis=None) -> {count, by, headline, items, equivalence, label}

**Items**, one per repair, each with a plain-language `text` (what was found first, then what it should be)
and a `short` label for a diagram:

- `number`: right structure, wrong number: "B → outside: 0.356·B, should be 0.2·B (+0.156, +78%)": the
  signed difference found − true and its share of the true number. `z` is the miss in standard errors
  of the best achievable estimate (the Cramér–Rao bound from the analysis, else the scorer's oracle
  SE); `limit` is "data-limited" when the miss is within 3 of them (an estimator at the bound misses
  by that much: the data cannot do much better), else "method error";
- `add` / `remove`: a true flow (or term) the found model lacks, or a found one the truth lacks:
  "add: outside → C (20)", "remove: C → A (0.066·C)"; on a flow that is otherwise there, "add term" /
  "remove term";
- `form`: a missing and an invented part on the same ends (the same edge, read another way):
  "change form: A → outside: 0.1·B, should be 0.2·A".

**Equivalence** (status "equivalent"): which of the analysis' equivalent structures the repairs touch
(e.g. a link and a drain read as a move) and whether the data can tell them apart at all ("unidentifiable");
every item's `limit` is then "equivalent" (the difference is the other reading, not an error in a number).
Negligible found parts (below the scorer's spurious threshold) are not repairs.
"""

from __future__ import annotations

import math
import re

Z_LIMIT = 3.0
WORDS = {"number": ("number", "numbers"), "add": ("add", "add"), "remove": ("remove", "remove"), "form": ("change form", "change form")}


def fmt(v) -> str:
    """A number as the ladder page shows it (ladder-compare.js fmt)."""
    if v is None:
        return "–"
    if isinstance(v, dict):
        if "k_in" in v:
            return f"k {fmt(v['k_in'])}, delay {fmt(v['delay'])}"
        if "delay" in v:
            return f"delay {fmt(v['delay'])}"
        if "mean" in v:
            return fmt(v["mean"])
        if v.get("shape"):
            return str(v["shape"])
        return "?"
    v = float(v)
    if not math.isfinite(v):
        return str(v)
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        return f"{round(v):,}"
    out = f"{v:.4g}" if a >= 1 else f"{v:.3g}"
    return out


def signed(v: float) -> str:
    s = fmt(abs(v))
    return ("+" if v > 0 else "−" if v < 0 else "±") + s


def signed_pct(r: float) -> str:
    a = abs(r) * 100
    s = f"{a:.0f}" if a >= 10 else f"{a:.1f}"
    return ("+" if r > 0 else "−" if r < 0 else "±") + s + "%"


def parse(key: str) -> dict:
    """A part's key (parts.label) as {kind, from, to, reader | stock}; from / to None for outside."""
    end = lambda x: None if x == "outside" else x  # noqa: E731
    m = re.match(r"^outside -> \(hidden\) -> (.+?) \[(.+)\]$", key)          # what feeds a hidden path from outside
    if m:
        return {"kind": "via", "from": None, "to": m[1], "reader": m[2]}
    m = re.match(r"^effect (\S+) on outside -> \(hidden\) -> (.+)$", key)
    if m:
        return {"kind": "viaeffect", "stock": m[1], "from": None, "to": m[2]}
    m = re.match(r"^(.+?) -> \(hidden\) -> (.+)$", key)
    if m:
        return {"kind": "hidden", "from": end(m[1]), "to": end(m[2])}
    m = re.match(r"^(uses|effect) (\S+) on (.+?) -> (.+)$", key)
    if m:
        return {"kind": m[1], "stock": m[2], "from": end(m[3]), "to": end(m[4])}
    m = re.match(r"^(.+?) -> (.+?) \[(.+)\]$", key)
    if m:
        return {"kind": "flow", "from": end(m[1]), "to": end(m[2]), "reader": m[3]}
    return {"kind": "other", "from": None, "to": None}


def ends(k: dict) -> str:
    a, b = k.get("from") or "outside", k.get("to") or "outside"
    return f"{a} → (hidden) → {b}" if k["kind"] in ("hidden", "via", "viaeffect") else f"{a} → {b}"


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict) and isinstance(v.get("mean"), (int, float)):
        return float(v["mean"])
    return None


def term(k: dict, v) -> str:
    """One number of a flow in its place: 20, 0.066·C, uses 0.5 R each, the effect of C, a hidden stock."""
    if k["kind"] in ("flow", "via"):
        return fmt(v) if k["reader"] == "const" else f"{fmt(v)}·{k['reader']}"
    if k["kind"] == "uses":
        return f"uses {fmt(v)} {k['stock']} each"
    if k["kind"] == "effect":
        return f"effect of {k['stock']}"
    if k["kind"] == "hidden":
        return f"a hidden stock ({fmt(v)})"
    return fmt(v)


def _se(key: str, part: dict, analysis: dict | None) -> tuple[float | None, str | None, float | None]:
    """The standard error of the best achievable estimate of a part (the bound's, else the oracle's), its
    source, and the tolerance the scorer allowed (from the analysis)."""
    rows = [r for r in (analysis or {}).get("parts") or [] if r.get("part") == key]
    ses = [r["crb_se"] for r in rows if isinstance(r.get("crb_se"), (int, float)) and math.isfinite(r["crb_se"])]
    allowed = [r["allowed"] for r in rows if isinstance(r.get("allowed"), (int, float))]
    al = max(allowed) if allowed else None
    if ses:
        return max(ses), "bound", al
    se = _num(part.get("se"))
    return (se, "oracle", al) if se and math.isfinite(se) else (None, None, al)


def _number(p: dict, k: dict, analysis: dict | None) -> dict:
    item = {"type": "number", "key": p["key"], "from": k["from"], "to": k["to"], "kind": p.get("kind")}
    f, t = p.get("found_value"), p.get("true")
    if p.get("compared"):                                    # a flow with effects, compared as a whole
        e = p.get("error")
        item.update(text=f"{ends(k)} (with {term(k, None) if k['kind'] == 'effect' else 'effects'}): its amount is "
                         f"{'' if e is None or not math.isfinite(e) else f'{100 * e:.0f}% '}off (rms over the run)",
                    short=f"{100 * e:.0f}% off" if e is not None and math.isfinite(e) else "off", rel=e)
        return item
    if k["kind"] == "hidden" and isinstance(f, dict) and isinstance(t, dict) and "k_in" not in t:     # fed from outside: the delay only
        dd = f["delay"] - t["delay"]
        rd = dd / t["delay"] if t["delay"] and math.isfinite(t["delay"]) else 0.0
        item.update(found=f, true=t, rel=rd, text=f"{ends(k)}: delay {fmt(f['delay'])}, should be {fmt(t['delay'])} ({signed(dd)}, {signed_pct(rd)})",
                    short=f"delay {signed_pct(rd)}")
        return item
    if k["kind"] == "hidden" and isinstance(f, dict) and isinstance(t, dict):
        dk, dd = f["k_in"] - t["k_in"], f["delay"] - t["delay"]
        rk = dk / t["k_in"] if t["k_in"] else 0.0
        rd = dd / t["delay"] if t["delay"] and math.isfinite(t["delay"]) else 0.0
        item.update(found=f, true=t, rel=rk if abs(rk) >= abs(rd) else rd,
                    text=f"{ends(k)}: k {fmt(f['k_in'])}, delay {fmt(f['delay'])}, should be k {fmt(t['k_in'])}, delay {fmt(t['delay'])}"
                         f" (k {signed(dk)}, {signed_pct(rk)}; delay {signed(dd)}, {signed_pct(rd)})",
                    short=f"k {signed_pct(rk)}, delay {signed_pct(rd)}")
        return item
    fv, tv = _num(f), _num(t)
    if fv is None or tv is None:
        item.update(text=f"{ends(k)}: {term(k, f)}, should be {term(k, t)}", short=f"{fmt(f)} ≠ {fmt(t)}")
        return item
    diff = fv - tv
    rel = diff / abs(tv) if tv else None
    windows = len(t["per_window"]) if isinstance(t, dict) and t.get("per_window") else None
    se, source, allowed = _se(p["key"], p, analysis)
    z = abs(diff) / se if se else None
    item.update(found=fv, true=tv, diff=diff, rel=rel, se=se, se_source=source, allowed=allowed, z=z,
                limit=None if z is None else "data-limited" if z <= Z_LIMIT else "method error",
                text=f"{ends(k)}: {term(k, fv)}, should be {term(k, tv)} ({signed(diff)}"
                     f"{'' if rel is None else ', ' + signed_pct(rel)})" + (f", on average over {windows} windows" if windows else ""),
                short=signed(diff) + ("" if rel is None else f" ({signed_pct(rel)})"))
    return item


def repairs(scores: dict | None, analysis: dict | None = None) -> dict:
    """The repairs that turn a found model into the truth (see the module docstring)."""
    label = (analysis or {}).get("label")
    if not scores or "parts" not in scores:
        return {"count": None, "by": {}, "headline": "no model to repair", "items": [], "equivalence": None, "label": label}
    parts, spurious = scores.get("parts") or [], scores.get("spurious") or []
    groups: dict[tuple, dict] = {}
    extras: list[dict] = []                                   # co-flows and effects: they ride on a flow
    items: list[dict] = []
    for p in parts:
        k = parse(p["key"])
        g = groups.setdefault((k["from"], k["to"]), {"missing": [], "spurious": [], "present": False}) if k["kind"] in ("flow", "hidden") else None
        if p.get("found"):
            if g is not None:
                g["present"] = True
            if not p.get("ok"):
                items.append(_number(p, k, analysis))
        elif g is not None:
            g["missing"].append((p, k))
        else:
            extras.append({"type": "add", "key": p["key"], "from": k["from"], "to": k["to"], "kind": p.get("kind"),
                           "text": f"add: {ends(k)} {term(k, p.get('true'))}", "short": f"add {term(k, p.get('true'))}"})
    for s in spurious:
        k = parse(s["key"])
        if k["kind"] in ("flow", "hidden"):
            groups.setdefault((k["from"], k["to"]), {"missing": [], "spurious": [], "present": False})["spurious"].append((s, k))
        else:
            extras.append({"type": "remove", "key": s["key"], "from": k["from"], "to": k["to"], "kind": s.get("kind"),
                           "text": f"remove: {ends(k)} {term(k, s.get('value'))}", "short": f"remove {term(k, s.get('value'))}"})
    structural = []
    for (a, b), g in groups.items():
        miss, spur = g["missing"], g["spurious"]
        if not miss and not spur:
            continue
        k0 = (miss or spur)[0][1]
        where = ends(k0) if all(k["kind"] == k0["kind"] for _, k in miss + spur) else f"{a or 'outside'} → {b or 'outside'}"
        want = " + ".join(term(k, p.get("true")) for p, k in miss)
        have = " + ".join(term(k, s.get("value")) for s, k in spur)
        base = {"from": a, "to": b, "keys": [p["key"] for p, _ in miss] + [s["key"] for s, _ in spur]}
        if miss and spur:
            structural.append({**base, "type": "form", "text": f"change form: {where}: {have}, should be {want}", "short": f"{have} → {want}"})
        elif miss:
            on = g["present"]
            structural.append({**base, "type": "add", "text": f"add term to {where}: {want}" if on else f"add: {where} ({want})",
                               "short": f"add {want}"})
        else:
            on = g["present"]
            structural.append({**base, "type": "remove", "text": f"remove term from {where}: {have}" if on else f"remove: {where} ({have})",
                               "short": f"remove {have}"})
    order = {"remove": 0, "add": 1, "form": 2, "number": 3}
    items = sorted(structural + extras, key=lambda x: order[x["type"]]) + sorted(items, key=lambda x: -abs(x.get("rel") or 0))
    by: dict[str, int] = {}
    for it in items:
        by[it["type"]] = by.get(it["type"], 0) + 1
    n = len(items)
    headline = "no repairs" if not n else f"{n} repair{'s' if n != 1 else ''}: " + ", ".join(
        f"{by[t]} {WORDS[t][by[t] != 1]}" for t in ("remove", "add", "form", "number") if by.get(t))
    equivalence = None
    if scores.get("status") == "equivalent":
        equivalence = _equivalence(items, analysis)
        for it in items:                                     # every difference is part of the equivalent reading
            it["limit"] = "equivalent"
    return {"count": n, "by": by, "headline": headline, "items": items, "label": label,
            "negligible": len(scores.get("negligible") or []), "equivalence": equivalence}


def _equivalence(items: list[dict], analysis: dict | None) -> dict:
    """Which equivalent structure the found model is (from the analysis' list, by the ends the repairs
    touch), and whether the data can tell it from the truth at all."""
    touched = {f"{it.get('from') or 'outside'} -> {it.get('to') or 'outside'}" for it in items}
    texts = (analysis or {}).get("equivalences") or []
    hits = [(sum(e in t for e in touched), t) for t in texts]
    best = max((h for h, _ in hits), default=0)
    chosen = [t.split(": the same")[0].replace("->", "→") for h, t in hits if best and h == best]
    label = (analysis or {}).get("label")
    if label == "unidentifiable":
        tell = "The data cannot tell them apart: only an equivalent model is possible here (unidentifiable)."
    elif label:
        tell = "The data can in principle tell them apart (only through the noise): parsimony or the likelihood should pick the truth."
    else:
        tell = "Not analysed: whether the data can tell them apart is unknown."
    return {"texts": chosen, "unidentifiable": label == "unidentifiable", "label": label,
            "text": "Equivalent: the found flows give every stock the same equation for its change as the truth. "
                    + (chosen[0][0].upper() + chosen[0][1:] + ". " if chosen else "") + tell}
