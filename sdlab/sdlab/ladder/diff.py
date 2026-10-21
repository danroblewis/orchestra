"""A found model as a git diff of the true one (the user, 2026-10-21): the truth is the original, the
found model the change. Made once, here, for agents (`sdlab-ladder diff`) and the page alike (GET
/api/ladder/diff/..., drawn by ladder-draw.js), so the two can never disagree.

    diff(case, found_flows, scores) -> {status, equivalent, stat, caption, lines, unchanged, hunk, flows, rows, extra_stocks, measured}

Signs: "-" removed (a true flow not found, a declared outside flow left unused), "+" added (in the
found model, not the truth: an invented flow or boundary, an extra term on a found flow, a stock only
the found model has), "~" in both but a number wrong (true -> found per number), "=" an equivalent
reading (the result is "equivalent": the same system read another way); unchanged lines are context
(" " found and right, "." too small to count or not scored). The hunk is what the differences
diagram draws at full strength: the changed flows, the stocks at their ends and every stock only the
found model has with its flows; everything else is faded.

This is the page's logic (ladder-compare.js: compare, diffLines; ladder-draw.js: diagrams, focus,
diffStat) ported line for line, read from the scorer's parts (score.py) and the found flows as the
scorer reads them (merge.py). found_flows: the merged flows (api's found_merged, else found).
"""

from __future__ import annotations

from .diff_text import OUT, UNDEF, equation, fmt, g, js_round, js_str, num, parse_key, part_name, readers, truthy

SIGN = {"✓": " ", "~": "~", "−": "-", "+": "+", "≈": "=", "·": "."}        # the page's glyphs -> ours
STAT = (("missed", "removed"), ("spurious", "added"), ("wrong", "wrong"), ("equiv", "equivalent"))
SAME = ("ok", "small", "plain", "unscored")                                   # unchanged: context lines
CHANGED = {"missed", "missing", "spurious", "wrong", "equiv", "claim"}        # drawn in the hunk


def _ends(a, b) -> str:
    return f"{js_str(a) if truthy(a) else OUT} -> {js_str(b) if truthy(b) else OUT}"


def compare(truth: dict, found: list, scores: dict | None) -> dict:
    """ladder-compare.js compare(): every true and found flow classed ok, wrong, missing, spurious,
    equiv, small or unscored, with the scorer's parts it owns."""
    scores = scores or {}
    found = found or []
    stocks = truth.get("stocks") or []
    measured = [s["id"] for s in stocks if g(s, "measured") is not False]
    mset = set(measured)
    status = scores.get("status") if truthy(scores.get("status")) else None
    equivalent = status == "equivalent"
    parts = [{**p, **(parse_key(g(p, "key")) or {})} for p in scores.get("parts") or []]
    spurious = [{**p, **(parse_key(g(p, "key")) or {})} for p in scores.get("spurious") or []]
    ids = [s["id"] for s in stocks]

    def hidden_of(i):
        return isinstance(i, str) and i not in mset and i in ids

    def found_hidden(i):
        return truthy(i) and i not in mset

    def mine(f, lst, hidden=hidden_of):
        fr, to = g(f, "from"), g(f, "to")
        if truthy(g(f, "via")):
            return [p for p in lst if g(p, "kind") == "hidden" and g(p, "from") == fr and g(p, "to") == to]
        if hidden(fr) or hidden(to):
            return [p for p in lst if g(p, "kind") == "hidden" and (g(p, "from") == fr if hidden(to) else g(p, "to") == to)]
        rd = readers(f)
        a, b = (fr if truthy(fr) else None), (to if truthy(to) else None)
        return [p for p in lst if g(p, "from") == a and g(p, "to") == b
                and (g(p, "reader") in rd if g(p, "kind") == "flow" else g(p, "kind") in ("uses", "effect"))]

    def class_of(ps, sp):
        if not ps and not sp:
            return None
        if not ps:
            cls = "spurious"
        elif all(truthy(g(p, "ok")) for p in ps) and not sp:
            cls = "ok"
        elif all(not truthy(g(p, "found")) for p in ps):
            cls = "missing"
        else:
            cls = "wrong"
        return "equiv" if cls != "ok" and equivalent else cls

    def why(ps, sp, side):
        return ([f"{js_str(g(p, 'key'))}: found {fmt(g(p, 'found_value'))}, true {fmt(g(p, 'true'))}" if truthy(g(p, "found"))
                 else f"{js_str(g(p, 'key'))}: not found (true {fmt(g(p, 'true'))})" for p in ps if not truthy(g(p, "ok"))]
                + [f"{js_str(g(p, 'key'))}: {'found too' if side == 'truth' else 'not in the truth'} ({fmt(g(p, 'value'))})" for p in sp])

    t_flows = []
    for f in truth.get("flows") or []:
        ps = mine(f, parts)
        cls = class_of(ps, []) or "unscored"
        off = [p for p in ps if not truthy(g(p, "ok")) and truthy(g(p, "found")) and g(p, "kind") == "flow"]

        def link_cls(kind, stock, ps=ps):
            p = next((q for q in ps if g(q, "kind") == kind and g(q, "stock") == stock), None)
            if p is None:
                return None
            c = "ok" if truthy(g(p, "ok")) else "wrong" if truthy(g(p, "found")) else "missing"
            return "equiv" if c != "ok" and equivalent else c

        reads = ([{"stock": g(e, "stock"), "kind": "effect", "cls": link_cls("effect", g(e, "stock"))} for e in (g(f, "effects") or [])]
                 + [{"stock": g(u, "stock"), "kind": "uses", "per": g(u, "per"), "cls": link_cls("uses", g(u, "stock"))} for u in (g(f, "uses") or [])])
        t_flows.append({"flow": f, "cls": cls, "parts": ps, "equation": equation(f, truth.get("schedule")), "notes": why(ps, [], "truth"),
                        "badge": f"found {', '.join(fmt(g(p, 'found_value')) for p in off)}" if off else "not found" if cls == "missing" else "",
                        "reads": reads})
    found_parts = [p for p in parts if truthy(g(p, "found"))]
    f_flows = []
    for f in found:
        ps, sp = mine(f, found_parts, found_hidden), mine(f, spurious, found_hidden)
        cls = class_of(ps, sp) or "small"
        off = [p for p in ps if not truthy(g(p, "ok")) and g(p, "kind") != "effect"]
        f_flows.append({"flow": f, "cls": cls, "parts": ps, "spurious": sp, "equation": equation(f), "notes": why(ps, sp, "found"),
                        "badge": ", ".join(f"true {fmt(g(p, 'true'))}" for p in off) if off else "extra term" if sp and ps else ""})
    # the equations side by side, one row per pair of ends (truth order first)
    rows: list[dict] = []
    by_key: dict[str, dict] = {}

    def at(k):
        if k not in by_key:
            by_key[k] = {"ends": k, "truth": [], "found": []}
            rows.append(by_key[k])
        return by_key[k]

    tf = truth.get("flows") or []
    for i, t in enumerate(t_flows):
        f = t["flow"]
        if hidden_of(g(f, "from")) or hidden_of(g(f, "to")):
            if hidden_of(g(f, "to")):
                a = g(f, "from")
                b = g(next((x for x in tf if g(x, "from") == g(f, "to")), {}), "to")
            else:
                up = next((x for x in tf if g(x, "to") == g(f, "from")), None)
                a, b = (g(up, "from") if up is not None else UNDEF), g(f, "to")
            at(f"{js_str(a)} → (hidden) → {js_str(b)}")["truth"].append(i)
        else:
            at(_row_key(f))["truth"].append(i)
    for k, x in enumerate(f_flows):
        f = x["flow"]
        if not truthy(g(f, "via")) and (found_hidden(g(f, "from")) or found_hidden(g(f, "to"))):    # a chain through a stock the found model infers
            if found_hidden(g(f, "to")):
                a, b = g(f, "from"), g(next((y for y in found if g(y, "from") == g(f, "to")), {}), "to")
            else:
                a, b = g(next((y for y in found if g(y, "to") == g(f, "from")), {}), "from"), g(f, "to")
            at(f"{js_str(a) if truthy(a) else OUT} → (hidden) → {js_str(b) if truthy(b) else OUT}")["found"].append(k)
        else:
            at(_row_key(f))["found"].append(k)
    rank = {"missing": 5, "spurious": 5, "wrong": 4, "equiv": 3, "unscored": 2, "small": 1, "ok": 0}
    for r in rows:
        every = [t_flows[i]["cls"] for i in r["truth"]] + [f_flows[k]["cls"] for k in r["found"]]
        r["cls"] = sorted(every, key=lambda c: -rank.get(c, 0))[0] if every else "ok"
    extra: list[str] = []
    for f in found:
        for x in (g(f, "from"), g(f, "to")):
            if truthy(x) and x not in ids and x not in extra:
                extra.append(x)
    book = g(g(scores, "algebra") or {}, "bookkeeping") if equivalent else None     # (2026-10-21) how a proven equivalent drawing differs
    return {"status": status, "equivalent": equivalent, "truth": t_flows, "found": f_flows, "rows": rows, "measured": measured, "extra_stocks": extra,
            "bookkeeping": book if truthy(book) else None}


def _row_key(f) -> str:
    if truthy(g(f, "via")):
        return f"{js_str(g(f, 'from'))} → (hidden) → {js_str(g(f, 'to'))}"
    return _ends(g(f, "from"), g(f, "to")).replace(" -> ", " → ")


def _number(p: dict, found_side: bool = False) -> dict:
    if found_side:
        return {"part": js_str(g(p, "key")), "true": None, "found": g(p, "value") if g(p, "value") is not UNDEF else None, "rel_error": None, "ok": False}
    v = lambda k: None if g(p, k) is UNDEF else g(p, k)  # noqa: E731
    return {"part": js_str(g(p, "key")), "true": v("true"), "found": v("found_value") if truthy(g(p, "found")) else None,
            "rel_error": v("error"), "ok": truthy(g(p, "ok")), "found_it": truthy(g(p, "found"))}


def lines(cmp: dict) -> list[dict]:
    """ladder-compare.js diffLines(): one line per true flow, then one per found flow that is
    invented, a re-reading, carries an extra term, or is too small to count."""
    out = []
    t_ends = lambda f: (f"{js_str(g(f, 'from'))} -> (hidden) -> {js_str(g(f, 'to'))}" if truthy(g(f, "via")) else _ends(g(f, "from"), g(f, "to")))  # noqa: E731

    def found_for(t):
        keys = {g(q, "key") for q in t["parts"]}
        return [x for x in cmp["found"] if any(g(p, "key") in keys for p in x["parts"])]

    def direction(p):
        a, b = num(g(p, "found_value")), num(g(p, "true"))
        if a is not None and b is not None and truthy(b):
            return f" ({js_str(js_round(100 * abs(a - b) / abs(b)))}% {'low' if a < b else 'high'})"
        return ""

    for i, t in enumerate(cmp["truth"]):
        fs = found_for(t)
        feq = "; ".join(x["equation"] for x in fs)
        off = [p for p in t["parts"] if truthy(g(p, "found")) and not truthy(g(p, "ok"))]
        miss = [p for p in t["parts"] if not truthy(g(p, "found"))]
        sign, note, cls = "·", "not scored", t["cls"]
        if cls == "ok":
            sign, note = "✓", f"found {feq}" if feq else "found"
        elif cls == "missing":
            sign, note = "−", "missed"
        elif cls == "wrong":
            sign = "~"
            bits = ([f"{part_name(g(p, 'key')) + ' ' if g(p, 'kind') in ('effect', 'hidden') else ''}{fmt(g(p, 'found_value'))} for {fmt(g(p, 'true'))}{direction(p)}" for p in off]
                    + [f"missed {part_name(g(p, 'key'))}" for p in miss])
            note = f"{'found ' + feq if feq else 'found'}: {'; '.join(bits)}"
        elif cls == "equiv":
            sign = "≈"
            note = (f"{'found ' + feq + '; ' if feq else ''}{'missed ' + ', '.join(part_name(g(p, 'key')) for p in miss) + ', ' if miss else ''}"
                    + (f"the same equations drawn another way (proven equivalent: {cmp['bookkeeping']})" if cmp.get("bookkeeping")
                       else "read another way with the same behaviour (equivalent)"))
        f = t["flow"]
        out.append({"sign": SIGN[sign], "cls": "missed" if cls == "missing" else cls, "ends": t_ends(f), "side": "truth", "index": i,
                    "true_id": js_str(g(f, "id")), "true_eq": t["equation"], "found_eq": feq, "truth": f"{js_str(g(f, 'id'))} {t['equation']}",
                    "numbers": [_number(p) for p in t["parts"]], "note": note})
    missed_names = [part_name(g(p, "key")) for t in cmp["truth"] for p in t["parts"] if not truthy(g(p, "found"))]
    for k, x in enumerate(cmp["found"]):
        f, cls = x["flow"], x["cls"]
        base = {"ends": t_ends(f), "side": "found", "index": k, "true_id": "", "true_eq": "", "found_eq": x["equation"], "truth": ""}
        if cls == "spurious":
            out.append({**base, "sign": "+", "cls": "spurious", "numbers": [_number(p, True) for p in x["spurious"]], "note": f"invented {x['equation']}"})
        elif cls == "equiv" and not x["parts"]:
            out.append({**base, "sign": "=", "cls": "equiv", "numbers": [_number(p, True) for p in x["spurious"]],
                        "note": f"read as {x['equation']}{' (equivalent to ' + ', '.join(missed_names) + ')' if missed_names else ' (equivalent)'}"
                                + (f"; {cmp['bookkeeping']}" if cmp.get("bookkeeping") else "")})
        elif x["spurious"] and x["parts"]:
            terms = ", ".join(f"{part_name(g(p, 'key'))} {fmt(g(p, 'value'))}" for p in x["spurious"])
            out.append({**base, "sign": "+", "cls": "equiv" if cls == "equiv" else "spurious", "numbers": [_number(p, True) for p in x["spurious"]],
                        "note": f"extra term on {x['equation']}: {terms}"})
        elif cls == "small":
            out.append({**base, "sign": ".", "cls": "small", "numbers": [], "note": f"too small to count: {x['equation']}"})
    return out


def stat(ls: list[dict]) -> dict:
    """ladder-draw.js diffStat(): the lines counted by class, like git diff --stat."""
    n = {name: sum(1 for x in ls if x["cls"] == cls) for cls, name in STAT}
    return n


def caption(n: dict) -> str:
    bits = [n["removed"] and f"{n['removed']} removed", n["added"] and f"{n['added']} added",
            n["wrong"] and f"{n['wrong']} value{'s' if n['wrong'] > 1 else ''} wrong", n["equivalent"] and f"{n['equivalent']} equivalent"]
    bits = [b for b in bits if b]
    return f"Differences: {' · '.join(bits) if bits else 'none'}"


def drawn(case: dict, cmp: dict) -> tuple[list[dict], list[str]]:
    """ladder-draw.js diagrams(): the differences diagram's flows ({side, index, from, to, cls}, a found
    flow through its own hidden stock as two) and the stocks only the found model has."""
    boundary = case.get("boundary") if truthy(case.get("boundary")) else None
    truth_ids = [s["id"] for s in case["model"]["stocks"]]

    def side_of(f):
        fr, to = g(f, "from"), g(f, "to")
        return (to, "in") if not truthy(fr) and truthy(to) else (fr, "out") if truthy(fr) and not truthy(to) else None

    def kind_at(f):
        sd = side_of(f)
        if not sd or boundary is None or not truthy(g(boundary, sd[0])):
            return None
        ks = g(boundary[sd[0]], sd[1])
        return ks[0] if isinstance(ks, list) and ks else None

    def crossing(f):
        return None if not side_of(f) else "claim" if boundary is None else "declared" if truthy(kind_at(f)) else "invented"

    d_flows = []
    for i, t in enumerate(cmp["truth"]):
        cls = "missed" if t["cls"] == "missing" else "plain" if t["cls"] == "unscored" else t["cls"]
        d_flows.append({"side": "truth", "index": i, "from": g(t["flow"], "from"), "to": g(t["flow"], "to"), "cls": cls})
    vias = [f"via:{k}" for k, x in enumerate(cmp["found"]) if truthy(g(x["flow"], "via"))]
    for k, x in enumerate(cmp["found"]):
        f = x["flow"]
        invented, reread, extra = x["cls"] == "spurious", x["cls"] == "equiv" and not x["parts"], bool(x["spurious"]) and bool(x["parts"])
        if not invented and not reread and not extra:
            continue
        cr = crossing(f)
        cls = "equiv" if reread or x["cls"] == "equiv" else "claim" if cr == "claim" and not extra else "spurious"
        if truthy(g(f, "via")):
            vid = f"via:{k}"
            start = g(f, "from") if truthy(g(f, "from")) else g(f["via"], "echo")
            d_flows += [{"side": "found", "index": k, "from": start, "to": vid, "cls": cls}, {"side": "found", "index": k, "from": vid, "to": g(f, "to"), "cls": cls}]
        else:
            d_flows.append({"side": "found", "index": k, "from": g(f, "from"), "to": g(f, "to"), "cls": cls})
    return d_flows, [s for s in [*cmp["extra_stocks"], *vias] if s not in truth_ids]


def hunk(case: dict, cmp: dict) -> dict:
    """ladder-draw.js focus(): what the differences diagram draws at full strength. flows: {side, index,
    ends, cls}; stocks: ids, the truth's first (a found flow's own hidden stock is "via:k")."""
    d_flows, new = drawn(case, cmp)
    truth_ids = [s["id"] for s in case["model"]["stocks"]]
    vias = [s for s in new if s.startswith("via:")]
    shown = lambda f: f["cls"] in CHANGED or f["from"] in new or f["to"] in new  # noqa: E731
    keep: list = []
    flows: list[dict] = []
    for f in d_flows:
        if shown(f):
            keep += [x for x in (f["from"], f["to"]) if truthy(x)]
            if not any(h["side"] == f["side"] and h["index"] == f["index"] for h in flows):
                fl = cmp[f["side"]][f["index"]]["flow"]
                ends = (f"{js_str(g(fl, 'from'))} -> (hidden) -> {js_str(g(fl, 'to'))}" if truthy(g(fl, "via")) else _ends(g(fl, "from"), g(fl, "to")))
                flows.append({"side": f["side"], "index": f["index"], "ends": ends, "cls": f["cls"]})
    keep += new
    order = [*truth_ids, *[s for s in [*cmp["measured"], *cmp["extra_stocks"], *vias] if s not in truth_ids]]
    return {"stocks": [s for s in dict.fromkeys(order) if s in keep], "flows": flows}


def _flow_view(x: dict, found_side: bool) -> dict:
    keys = lambda ps: [js_str(g(p, "key")) for p in ps]  # noqa: E731
    out = {"cls": x["cls"], "parts": keys(x["parts"]), "notes": x["notes"], "badge": x["badge"], "equation": x["equation"]}
    if found_side:
        out["spurious"] = keys(x["spurious"])
    else:
        out["reads"] = x["reads"]
    return out


def diff(case: dict, found_flows: list | None, scores: dict | None) -> dict:
    """The found model as a diff of the truth. case: the case (model, boundary); found_flows: the
    found flows as the scorer reads them (merged); scores: the result's scores."""
    cmp = compare(case["model"], found_flows or [], scores)
    ls = lines(cmp)
    n = stat(ls)
    return {"status": cmp["status"], "equivalent": cmp["equivalent"], "stat": n, "caption": caption(n),
            "lines": [x for x in ls if x["cls"] not in SAME], "unchanged": [x for x in ls if x["cls"] in SAME],
            "hunk": hunk(case, cmp),
            "flows": {"truth": [_flow_view(t, False) for t in cmp["truth"]], "found": [_flow_view(x, True) for x in cmp["found"]]},
            "rows": cmp["rows"], "extra_stocks": cmp["extra_stocks"], "measured": cmp["measured"]}
