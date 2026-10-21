"""How the ladder writes numbers, rates, equations and part names: a faithful port of the page's
sdlab/static/ladder-compare.js (fmt, parseKey, readers, rateText, equation, partName), so a diff made
in Python (diff.py) reads exactly as the page draws it. JavaScript's semantics are kept where they
show: number to string, toPrecision, Math.round, truthiness, `+x`, and `${undefined}` / `${null}`.
Pure functions; tests/test_ladder_diff.py checks them against the page's own outputs.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

OUT = "outside"


class _Undefined:
    """JavaScript's undefined: a key the object does not have (null is None)."""

    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEF = _Undefined()


def g(d, k):
    """d[k], or UNDEF when d is not an object or has no k (JavaScript's d.k)."""
    return d.get(k, UNDEF) if isinstance(d, dict) else UNDEF


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def truthy(v) -> bool:
    if v is None or v is UNDEF or v is False:
        return False
    if is_num(v):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True                                     # objects and arrays, even empty


def plus(v) -> float:
    """JavaScript's +v."""
    if v is None:
        return 0.0
    if v is UNDEF or isinstance(v, dict):
        return math.nan
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if is_num(v):
        return float(v)
    if isinstance(v, list):
        return 0.0 if not v else plus(js_str(v)) if len(v) == 1 else math.nan
    s = str(v).strip()
    if s == "":
        return 0.0
    if s.lstrip("+") == "Infinity":
        return math.inf
    if s == "-Infinity":
        return -math.inf
    return float(s) if _NUMBER.fullmatch(s) else math.nan


_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def num_str(x) -> str:
    """JavaScript's String(number): the shortest round-trip digits, positional for 1e-7 <= |x| < 1e21."""
    if isinstance(x, bool):
        return "true" if x else "false"
    x = float(x)
    if x != x:
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign, digits, exp = Decimal(repr(abs(x))).as_tuple()
    ds = "".join(map(str, digits)).rstrip("0") or "0"
    exp += len(digits) - len(ds)                   # value = ds x 10^exp
    k, n = len(ds), len(ds) + exp                   # value = 0.ds x 10^n
    neg = "-" if x < 0 else ""
    if k <= n <= 21:
        return neg + ds + "0" * (n - k)
    if 0 < n <= 21:
        return neg + ds[:n] + "." + ds[n:]
    if -6 < n <= 0:
        return neg + "0." + "0" * (-n) + ds
    e = n - 1
    return neg + ds[0] + ("." + ds[1:] if k > 1 else "") + "e" + ("+" if e > 0 else "-") + str(abs(e))


def js_str(v) -> str:
    """JavaScript's String(v) / `${v}`."""
    if v is UNDEF:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool) or is_num(v):
        return num_str(v)
    if isinstance(v, list):
        return ",".join("" if x is None or x is UNDEF else js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def to_precision(x: float, p: int) -> float:
    """+x.toPrecision(p): rounded to p significant digits, a tie to the larger magnitude."""
    if x != x or math.isinf(x) or x == 0:
        return x
    d = Decimal(abs(x))
    r = d.quantize(Decimal(1).scaleb(d.adjusted() - p + 1), rounding=ROUND_HALF_UP)
    return math.copysign(float(r), x)


def js_round(x: float) -> float:
    """Math.round."""
    if x != x or math.isinf(x):
        return x
    return float(math.floor(x + 0.5))


def fmt(v) -> str:
    if v is None or v is UNDEF:
        return "–"
    if is_num(v):
        if v != v or math.isinf(v):
            return num_str(v)
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 1000:
            n = format(Decimal(repr(js_round(float(v)))), "f").split(".")[0]      # toLocaleString: the shortest digits, then zeros
            neg, n = ("-", n[1:]) if n.startswith("-") else ("", n)
            return neg + f"{int(n):,}"
        return num_str(to_precision(float(v), 4 if a >= 1 else 3))
    if isinstance(v, dict):
        if isinstance(v.get("per_window"), list):
            return " / ".join(fmt(x) for x in v["per_window"])
        if "k_in" in v:
            return f"k {fmt(g(v, 'k_in'))}, delay {fmt(g(v, 'delay'))}"
        if "delay" in v:
            return f"delay {fmt(v['delay'])}"
        if v.get("shape") == "linear":
            return f"linear (normal {fmt(g(v, 'normal'))}, max {fmt(g(v, 'max'))})"
        if v.get("shape") == "table":
            return f"table ({len(v.get('points') or [])} points)"
        if "mean" in v:
            return fmt(v["mean"])
    return js_str(v)


def num(v):
    """A number, or an object's mean; None otherwise."""
    if is_num(v):
        return v
    if isinstance(v, dict) and is_num(v.get("mean")):
        return v["mean"]
    return None


_VIA = re.compile(r"outside -> \(hidden\) -> (.+?) \[(.+)\]")
_VIAEFFECT = re.compile(r"effect (\S+) on outside -> \(hidden\) -> (.+)")
_HIDDEN = re.compile(r"(.+?) -> \(hidden\) -> (.+)")
_LINK = re.compile(r"(uses|effect) (\S+) on (.+?) -> (.+)")
_FLOW = re.compile(r"(.+?) -> (.+?) \[(.+)\]")


def parse_key(key) -> dict | None:
    """A part's key (score.py's labels) as {kind, from, to, reader?, stock?}; outside is None."""
    if not isinstance(key, str):
        return None
    end = lambda x: None if x == OUT else x  # noqa: E731
    if m := _VIA.fullmatch(key):
        return {"kind": "via", "from": None, "to": m[1], "reader": m[2]}
    if m := _VIAEFFECT.fullmatch(key):
        return {"kind": "viaeffect", "stock": m[1], "from": None, "to": m[2]}
    if m := _HIDDEN.fullmatch(key):
        return {"kind": "hidden", "from": end(m[1]), "to": end(m[2])}
    if m := _LINK.fullmatch(key):
        return {"kind": m[1], "stock": m[2], "from": end(m[3]), "to": end(m[4])}
    if m := _FLOW.fullmatch(key):
        return {"kind": "flow", "from": end(m[1]), "to": end(m[2]), "reader": m[3]}
    return None


def _items(v) -> list:
    return v if isinstance(v, list) else []


def readers(f: dict) -> set:
    """What an equation reads: "const" and stock ids (byTime spans and inflow pieces included)."""
    out: set = set()

    def one(r):
        r = r if truthy(r) else {}
        form = g(r, "form")
        if form == "constant":
            out.add("const")
        elif form in ("proportional", "available"):
            if truthy(g(r, "stock")):
                out.add(g(r, "stock"))
        elif form == "gap":
            out.add("const")
            out.add(g(r, "stock"))
        elif form == "linear":
            if truthy(plus(g(r, "c"))):
                out.add("const")
            for t in _items(g(r, "terms")) if truthy(g(r, "terms")) else []:
                out.add(g(t, "stock"))

    if truthy(g(f, "inflow")) and len(_items(f["inflow"])):
        out.add("const")
    elif truthy(g(f, "byTime")) and len(_items(f["byTime"])):
        for s in f["byTime"]:
            one(g(s, "rate"))
    else:
        one(g(f, "rate"))
    return out


def rate_text(r) -> str:
    r = r if truthy(r) else {}
    form = g(r, "form")
    if form == "constant":
        return fmt(plus(g(r, "value")))
    if form == "proportional":
        return f"{fmt(plus(g(r, 'k')))}·{js_str(g(r, 'stock'))}"
    if form == "gap":
        t = plus(g(r, "time"))
        return f"({fmt(plus(g(r, 'goal')))} − {js_str(g(r, 'stock'))}) / {fmt(t if truthy(t) else 1)}"
    if form == "available":
        return f"all of {js_str(g(r, 'stock')) if truthy(g(r, 'stock')) else 'it'}"
    if form == "linear":
        t = [f"{fmt(plus(g(x, 'k')))}·{js_str(g(x, 'stock'))}" for x in (_items(g(r, "terms")) if truthy(g(r, "terms")) else [])]
        c = plus(g(r, "c"))
        head = [fmt(c if truthy(c) else 0)] if truthy(c) or not t else []
        return " + ".join(head + t).replace("+ -", "− ")
    return js_str(form) if truthy(form) else "?"


def equation(f: dict, schedule: dict | None = None) -> str:
    """A flow's whole equation in a line: its rate, then how it changes over time, effects, co-flows,
    a hidden stock. schedule: the case's schedule (true flows), whose changes set rates by flow id."""
    inflow, by_time = g(f, "inflow"), g(f, "byTime")
    if truthy(inflow) and len(_items(inflow)) > 1:
        vals = [plus(g(p, "value")) for p in inflow]
        lens = [max(1, (plus(g(p, "to")) if truthy(plus(g(p, "to"))) else 0) - (plus(g(p, "from")) if truthy(plus(g(p, "from"))) else 0) + 1) for p in inflow]
        tot = n_all = 0.0
        for v, n in zip(vals, lens):                 # left to right, as reduce does (sum() compensates since 3.12)
            tot += v * n
            n_all += n
        mean = tot / n_all
        s = f"≈ {fmt(mean)} on average, in {len(inflow)} pieces ({fmt(min(vals))} to {fmt(max(vals))})"
    elif truthy(by_time) and len(_items(by_time)) > 1:
        seen: list[str] = []
        for sp in by_time:
            t = rate_text(g(sp, "rate"))
            if t not in seen:
                seen.append(t)
        s = f"by time: {' | '.join(seen[:4])}{' | …' if len(seen) > 4 else ''} ({len(by_time)} spans)"
    else:
        s = rate_text(g(f, "rate"))
    fid = g(f, "id")
    changes = _items(g(schedule, "changes")) if truthy(schedule) and truthy(g(schedule, "changes")) else []
    ch = [c for c in changes if truthy(g(c, "set")) and truthy(g(c["set"], js_str(fid)))]
    if ch:
        s = (", ".join(f"{js_str(g(c, 'label')) if truthy(g(c, 'label')) else 't' + js_str(g(c, 't'))}: {rate_text(c['set'][js_str(fid)])}" for c in ch)
             + (f" (repeats every {js_str(schedule['every'])})" if truthy(g(schedule, "every")) else "")
             + (", announced" if any(truthy(g(c, "announce")) for c in ch) else ""))
    for e in _items(g(f, "effects")) if truthy(g(f, "effects")) else []:
        s += f" × effect({js_str(g(e, 'stock'))})"
    for u in _items(g(f, "uses")) if truthy(g(f, "uses")) else []:
        s += f", uses {fmt(plus(g(u, 'per')))} {js_str(g(u, 'stock'))} each"
    if truthy(g(f, "via")):
        s += f" via a hidden stock (delay {fmt(plus(g(f['via'], 'delay')))})"
    ratio = g(f, "ratio")
    if truthy(ratio) and ratio != 1:
        s += f" ({fmt(plus(ratio))} in per 1 out)"
    if truthy(g(f, "merged")) and truthy(g(f["merged"], "note")):
        s += f" [{js_str(f['merged']['note'])}]"
    if truthy(g(f, "apart")):
        s += f" [{js_str(f['apart'])}]"
    return s


def part_name(key) -> str:
    """A part in words: "the move A → B", "the drain of B", "the inflow to A", "the link B ⇒ A", ..."""
    k = parse_key(key) or {}
    kind, fr, to = g(k, "kind"), g(k, "from"), g(k, "to")
    end = lambda x: js_str(x) if truthy(x) else "outside"  # noqa: E731
    if kind == "hidden":
        return f"the hidden stock between {js_str(fr)} and {js_str(to)}"
    if kind == "uses":
        return f"the co-flow ({js_str(fr)} → {js_str(to)} uses {js_str(g(k, 'stock'))})"
    if kind == "effect":
        return f"the effect of {js_str(g(k, 'stock'))} on {end(fr)} → {end(to)}"
    if kind != "flow":
        return js_str(key)
    r = "" if k["reader"] == "const" else k["reader"]
    if truthy(fr) and truthy(to):
        return f"the move {fr} → {to}" + (f" (reading {r})" if r and r != fr else "")
    if truthy(to):
        return f"the link {r} ⇒ {to}" if r else f"the inflow to {to}"
    return f"the outflow from {js_str(fr)} reading {r}" if r and r != fr else f"the drain of {js_str(fr)}{'' if r else ' (constant)'}"
