"""SD Lab's rates (the ``rate`` of a flow it found), as Orchestra reads them: scaled to the
model's time unit, what they read, their numbers, and several rates between the same two ends
combined into one."""

from __future__ import annotations

LINEAR_FORMS = ("constant", "proportional", "linear")


def scale(rate: dict, f: float) -> dict:
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
    elif form == "sum":
        r["parts"] = [scale(p, f) for p in r.get("parts") or []]
    return r


def reads(rate: dict) -> list[str]:
    """What a rate reads: the stock or input of its form, its terms, its effects and its parts."""
    out = [rate["stock"]] if rate.get("stock") else []
    out += [t["stock"] for t in rate.get("terms") or [] if t.get("stock")]
    out += [e["stock"] for e in rate.get("effects") or [] if e.get("stock")]
    for p in rate.get("parts") or []:
        out += reads(p)
    return list(dict.fromkeys(out))


def numbers(rate: dict) -> dict[str, float]:
    out = {k: float(v) for k, v in rate.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for i, t in enumerate(rate.get("terms") or []):
        if isinstance(t.get("k"), (int, float)):
            out[f"k{i + 1}"] = float(t["k"])
    for i, p in enumerate(rate.get("parts") or []):
        out.update({f"p{i + 1}_{k}": v for k, v in numbers(p).items()})
    return out


def combine(rates: list[dict]) -> dict:
    """Several rates between the same two ends (SD Lab writes one flow per term it found) as
    one rate: when every one is constant, proportional or linear, one linear rate whose constant is
    their constants' sum and whose terms are all of theirs; otherwise a ``sum`` of the parts, which
    is kept whole (the simulator does not step it)."""
    if len(rates) == 1:
        return rates[0]
    if all(r.get("form") in LINEAR_FORMS for r in rates):
        c, terms = 0.0, []
        for r in rates:
            if r["form"] == "constant":
                c += float(r.get("value", 0.0))
            elif r["form"] == "proportional":
                terms.append({"stock": r.get("stock"), "k": float(r.get("k", 0.0))})
            else:
                c += float(r.get("c", 0.0))
                terms += [dict(t) for t in r.get("terms") or []]
        return {"form": "linear", "c": c, "terms": terms, "combined": len(rates)}
    return {"form": "sum", "parts": [dict(r) for r in rates], "combined": len(rates)}
