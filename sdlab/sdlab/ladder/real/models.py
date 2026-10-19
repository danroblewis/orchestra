"""The published structures of the real cases, as SD Lab models, and the case-format text that writes them.

Each family turns numbers into a truth model (the engine's JSON: stocks, flows, injections) and
`text()` writes that model in the ladder's compact case format (docs/LADDER.md, "The format"), so the
committed case file is readable and compiles back to the same model (build.py checks it does, by
simulating both).

| family | published model | in SD Lab's parts |
|---|---|---|
| `markov3` | the three-state labour market (Blanchard and Diamond 1990, Shimer 2012): each gross flow is a transition rate x the stock it leaves | 6 proportional moves; per stock a constant inflow from outside (new entrants to the 16+ population) and a proportional outflow (deaths, ageing out) |
| `glv` | generalised Lotka-Volterra, as gauseR's `gause_wrapper` fits it: dX_i/dt = X_i (r_i + sum_j a_ij X_j) | per species: r_i X_i (an inflow if r_i > 0, else a drain), and a_ij X_i x effect(X_j, linear) (an inflow if a_ij > 0, else a drain) |
| `sir_bc` | the boarding-school SIR with two observed recovery stages (pomp's bsflu model): S -> I -> B (bed) -> C (convalescent) -> out | S and I hidden; infection beta S x effect(I, linear, normal=N); three proportional moves |
| `bass` | Bass diffusion with a market potential m (share of households, %): adoption = (p + q A / m) (m - A) | N (households without, = 100 - A) -> A: innovation p (N - (100 - m)) and imitation (q/m) (N - (100 - m)) x effect(A, linear) |

Every rate is per data step (one sample is one engine step, dt = 1): a month (BLS), a day or a week
(lab populations), a year (adoption, Isle Royale). That choice is the case's, and is recorded in it
(docs/research/case-study-sources.md, "Recommendation" 3).
"""

from __future__ import annotations

import math


def fmt(x: float) -> str:
    """A number for a case file: 6 significant digits, never an exponent (the case format reads none)."""
    import numpy as np

    x = float(x)
    if x == 0:
        return "0"
    return np.format_float_positional(x, precision=6, unique=False, fractional=False, trim="-")


_EXACT = [False]


class exact:
    """Within it, models keep their numbers unrounded (a fit needs derivatives that rounding would flatten)."""

    def __enter__(self):
        _EXACT.append(True)

    def __exit__(self, *exc):
        _EXACT.pop()


def rnd(x: float) -> float:
    """The number as the case file writes it (so a fitted model and its file agree exactly)."""
    return float(x) if _EXACT[-1] else float(fmt(x))


def prop(stock: str, k: float) -> dict:
    return {"form": "proportional", "stock": stock, "k": rnd(k)}


def const(v: float) -> dict:
    return {"form": "constant", "value": rnd(v)}


def lin(c: float, terms: dict[str, float]) -> dict:
    return {"form": "linear", "c": rnd(c), "terms": [{"stock": s, "k": rnd(k)} for s, k in terms.items()]}


def eff(stock: str, normal: float, mx: float) -> dict:
    return {"stock": stock, "shape": "linear", "normal": rnd(normal), "max": rnd(mx)}


def flow(fid: str, a: str | None, b: str | None, rate: dict, effects: list[dict] | None = None) -> dict:
    f = {"id": fid, "from": a, "to": b, "rate": rate}
    if effects:
        f["effects"] = effects
    return f


# ---- the families ----

def markov3(initial: dict, k: dict, inflow: dict, outflow: dict, injections: list[dict], unit: str) -> dict:
    """E, U, N with the six moves k[(X, Y)] x X, outside -> X: inflow[X], X -> outside: outflow[X] x X."""
    ids = list(initial)
    flows = [flow(f"{a.lower()}{b.lower()}", a, b, prop(a, k[(a, b)])) for a in ids for b in ids if a != b]
    flows += [flow(f"{x.lower()}_in", None, x, const(inflow[x])) for x in ids]
    flows += [flow(f"{x.lower()}_out", x, None, prop(x, outflow[x])) for x in ids]
    return {"stocks": [{"id": x, "initial": rnd(initial[x]), "unit": unit} for x in ids], "flows": flows, "injections": injections}


def glv(initial: dict, r: dict, a: dict, cap: dict, unit: str, injections: list[dict] | None = None) -> dict:
    """Generalised Lotka-Volterra: r[i] and a[(i, j)] signed; cap[j] is the linear effect's max (above any level)."""
    ids = list(initial)
    flows = []
    for i in ids:
        flows.append(flow(f"{i.lower()}_r", None if r[i] >= 0 else i, i if r[i] >= 0 else None, prop(i, abs(r[i]))))
        for j in ids:
            v = a[(i, j)]
            flows.append(flow(f"{i.lower()}_{j.lower()}", None if v >= 0 else i, i if v >= 0 else None, prop(i, abs(v)), [eff(j, 1, cap[j])]))
    return {"stocks": [{"id": x, "initial": rnd(initial[x]), "unit": unit} for x in ids], "flows": flows, "injections": injections or []}


def sir_bc(n: float, i0: float, b0: float, c0: float, beta: float, gamma: float, mu1: float, mu2: float) -> dict:
    """S -> I -> B -> C -> outside; S and I hidden; infection beta S x I / n."""
    s0 = n - i0 - b0 - c0
    flows = [flow("si", "S", "I", prop("S", beta), [eff("I", n, 1)]),
             flow("ib", "I", "B", prop("I", gamma)),
             flow("bc", "B", "C", prop("B", mu1)),
             flow("c_out", "C", None, prop("C", mu2))]
    stocks = [{"id": "S", "initial": rnd(s0), "unit": "boys", "measured": False}, {"id": "I", "initial": rnd(i0), "unit": "boys", "measured": False},
              {"id": "B", "initial": rnd(b0), "unit": "boys"}, {"id": "C", "initial": rnd(c0), "unit": "boys"}]
    return {"stocks": stocks, "flows": flows, "injections": []}


def bass(a0: float, p: float, q: float, m: float) -> dict:
    """N = 100 - A (households without, %) -> A (with, %): p (m - A) + (q / m) (m - A) A, with m - A = N - (100 - m)."""
    off = 100.0 - m
    if abs(off) < 1e-6:                                # m = 100: (m - A) is N itself
        flows = [flow("innovation", "N", "A", prop("N", p)), flow("imitation", "N", "A", prop("N", q / m), [eff("A", 1, 101)])]
    else:
        flows = [flow("innovation", "N", "A", lin(-p * off, {"N": p})),
                 flow("imitation", "N", "A", lin(-(q / m) * off, {"N": q / m}), [eff("A", 1, 101)])]
    return {"stocks": [{"id": "N", "initial": rnd(100 - a0), "unit": "% of households"}, {"id": "A", "initial": rnd(a0), "unit": "% of households"}],
            "flows": flows, "injections": []}


# ---- the case-format text ----

def rate_text(rate: dict) -> str:
    form = rate["form"]
    if form == "constant":
        return fmt(rate["value"])
    if form == "proportional":
        return f"{fmt(rate['k'])} * {rate['stock']}"
    if form == "linear":
        body = " + ".join([fmt(rate["c"])] * (rate.get("c") not in (None, 0)) + [f"{fmt(t['k'])} * {t['stock']}" for t in rate["terms"]])
        body = body.replace("+ -", "- ")
        return f"max(0, {body})" if rate.get("c", 0) < 0 else body
    raise ValueError(f"no text for rate form {form}")


def flow_text(f: dict) -> str:
    rate = rate_text(f["rate"])
    if f.get("effects") and f["rate"]["form"] == "linear" and not rate.startswith("max("):
        rate = f"({rate})"
    for e in f.get("effects") or []:
        rate += f" * effect({e['stock']}, linear, normal={fmt(e['normal'])}, max={fmt(e['max'])})"
    return f"  {f['from'] or 'outside'} -> {f['to'] or 'outside'} as {f['id']}:\n    rate: {rate}"


def stock_text(s: dict) -> str:
    extra = ", hidden: true" if s.get("measured") is False else ""
    return f"  {s['id']}: {{initial: {fmt(s['initial'])}, unit: \"{s['unit']}\"{extra}}}"


def text(model: dict) -> str:
    """The model's stocks, flows, injections and announced eras in the case format."""
    out = ["stocks:"] + [stock_text(s) for s in model["stocks"]] + ["flows:"] + [flow_text(f) for f in model["flows"]]
    if model.get("injections"):
        out.append("injections:")
        out += [f"  - {{t: {j['t']}, stock: {j['stock']}, amount: {fmt(j['amount'])}}}" for j in model["injections"]]
    return "\n".join(out) + "\n"


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
