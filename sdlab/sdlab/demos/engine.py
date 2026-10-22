"""The demos' simulations (docs/DEMOS.md): the true model of a case run by the truth engine, with an optional
change applied to an in-memory copy (never to the case), and a stored found model run by the scorer's simulator for
found models (ladder/sim.found_model), one step ahead from measured levels or free from a start.

Nothing here changes a case, a simulation, a strategy or the result store."""

from __future__ import annotations

import copy
import re

import numpy as np

from ..ladder import cases as casemod
from ..ladder import data as ladder_data
from ..ladder import sim as ladder_sim
from ..ladder import store

GOOD = ("pass", "equivalent", "fits")


def case_and_truth(case_id: str, variant: str) -> tuple[dict, dict]:
    c = casemod.load(case_id)
    return c, casemod.truth_model(c, variant)


def stored_model(case_id: str, variant: str, strategy: str) -> dict | None:
    """The strategy's latest stored result on the cell when it passed (or is equivalent / fits), else its most
    recent such result: {id, status, found, scores, code_commit, at}."""
    rows = store.latest(case_id, variant, strategy, found=True)
    r = next((x for x in rows if x.get("status") in GOOD), None)
    if r is None:
        con = store.connect() if hasattr(store, "connect") else None
        if con is not None:
            got = con.execute("SELECT id FROM results WHERE case_id = ? AND variant = ? AND strategy = ? AND status IN ('pass', 'equivalent', 'fits')"
                              " ORDER BY id DESC LIMIT 1", (case_id, variant, strategy)).fetchone()
            if got:
                r = store.get(int(got[0]), found=True)
    return r


def run_truth(truth: dict, steps: int | None = None, change: dict | None = None, seed: int | None = None,
              edits: dict | None = None, inputs_scale: float = 1.0) -> dict:
    """The true model's run, noise-free: {t, levels: {stock: [...]}} for every stock (hidden ones too). change:
    {t, flow, rate} (a schedule change from step t on); edits: {flow id: rate} replacing rates from the start;
    inputs_scale multiplies every measured input series."""
    m = copy.deepcopy(truth)
    if steps:
        m["steps"] = int(steps)
    for fid, rate in (edits or {}).items():
        for f in m["flows"]:
            if f["id"] == fid:
                f["rate"] = rate
    if change:
        sch = m.setdefault("schedule", {})
        sch.setdefault("changes", []).append({"t": int(change["t"]), "label": change.get("label") or "demo change",
                                              "set": {change["flow"]: change["rate"]}})
    if inputs_scale != 1.0 and m.get("inputs"):
        m["inputs"] = {k: _scaled_input(v, inputs_scale) for k, v in m["inputs"].items()}
    m["noise"] = {}                                             # noise-free; a demo adds its own
    r = ladder_data.simulate(m, seed=seed)
    return {"t": list(r["t"]), "levels": {k: list(v) for k, v in r["all_levels"].items()},
            "inputs": {k: list(v) for k, v in (r.get("inputs") or {}).items()}}


def _scaled_input(v, k: float):
    if isinstance(v, (int, float)):
        return v * k
    if isinstance(v, str):
        return f"{k} * ({v})"
    if isinstance(v, dict) and "expr" in v:
        return {**v, "expr": f"{k} * ({v['expr']})"}
    return v


def found_ids(flows: list[dict], measured: list[str]) -> list[str]:
    """The stocks a found model steps: the measured ones, then its own (hidden) ones."""
    own = []
    for f in flows:
        for s in (f.get("from"), f.get("to")):
            if s and s not in measured and s not in own:
                own.append(s)
    return list(measured) + own


def _model(flows: list[dict], ids: list[str], t: list, inputs: dict):
    return ladder_sim.found_model(flows, ids, inputs={"t": list(t), "values": inputs} if inputs else None)


def one_step(flows: list[dict], measured: list[str], t: list, levels: dict, inputs: dict, hidden0: dict | None = None) -> dict:
    """The found model's one-step-ahead prediction of every measured stock from the measured levels; its own hidden
    stocks are carried by the model itself (stepped from its own last prediction). {predicted: {stock: [...]},
    hidden: {stock: [...]}}; predicted[s][i] is the prediction for step i from step i - 1 (nan at i = 0)."""
    ids = found_ids(flows, measured)
    mdl = _model(flows, ids, t, inputs)
    n = len(t)
    H = [s for s in ids if s not in measured]
    h = np.array([float((hidden0 or {}).get(s, 0.0)) for s in H])
    pred = {s: [float("nan")] for s in measured}
    hid = {s: [float(h[j])] for j, s in enumerate(H)}
    for i in range(1, n):
        L = np.array([float(levels[s][i - 1]) for s in measured] + list(h))[:, None]
        nxt = mdl.step(L, np.array([t[i]]))[:, 0]                # levels[i] are after step t[i]: that step reads t[i]'s inputs
        for k, s in enumerate(measured):
            pred[s].append(float(nxt[k]))
        h = nxt[len(measured):]
        for j, s in enumerate(H):
            hid[s].append(float(h[j]))
    return {"predicted": pred, "hidden": hid}


def free_run(flows: list[dict], measured: list[str], t: list, start: dict, inputs: dict) -> dict:
    """The found model run free from the levels at t[0] (hidden stocks from start, else 0): {stock: [...]}."""
    ids = found_ids(flows, measured)
    mdl = _model(flows, ids, t, inputs)
    L = np.array([float(start.get(s, 0.0)) for s in ids])[:, None]
    out = {s: [float(L[k, 0])] for k, s in enumerate(ids)}
    for i in range(1, len(t)):
        L = mdl.step(L, np.array([t[i]]))
        for k, s in enumerate(ids):
            out[s].append(float(L[k, 0]))
    return out


# ---- the numbers of a found model, for what-if and leverage ----

NUM = re.compile(r"(?<![A-Za-z0-9_.])(\d+\.?\d*(?:[eE][-+]?\d+)?)")


def numbers(flows: list[dict]) -> list[dict]:
    """Every number in the found model's rates that a person could change: {key, flow, ends, label, value}. key is
    "i/path" (the flow's index and the path inside it), so set_number can write it back."""
    out = []
    for i, f in enumerate(flows):
        ends = f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'}"
        r = f.get("rate") or {}
        form = r.get("form")
        if form == "constant":
            out.append({"key": f"{i}/value", "flow": i, "ends": ends, "label": "constant", "value": float(r["value"])})
        elif form == "proportional":
            out.append({"key": f"{i}/k", "flow": i, "ends": ends, "label": f"× {r.get('stock')}", "value": float(r["k"])})
        elif form == "linear":
            if r.get("c"):
                out.append({"key": f"{i}/c", "flow": i, "ends": ends, "label": "constant", "value": float(r["c"])})
            for j, term in enumerate(r.get("terms") or []):
                out.append({"key": f"{i}/terms/{j}", "flow": i, "ends": ends, "label": f"× {term.get('stock')}", "value": float(term["k"])})
        elif form == "expr":
            for j, m in enumerate(NUM.finditer(r.get("expr") or "")):
                v = float(m.group(1))
                if v in (0.0, 1.0):
                    continue                                  # structure (max(0, ...), 1 * (...)), not a tunable number
                out.append({"key": f"{i}/expr/{j}", "flow": i, "ends": ends, "label": _term(r["expr"], m), "value": v})
    return out


def _term(expr: str, m) -> str:
    """The term a number sits in: from the number to the next + or - at the same depth (or a closing bracket),
    with what it divides or multiplies, e.g. "0.49999 * mem_hidden", "cpu / 192.5"."""
    i, depth, end = m.end(), 0, len(expr)
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                end = i
                break
            depth -= 1
        elif ch in "+-," and depth == 0 and expr[i - 1] == " ":
            end = i
            break
        i += 1
    before = expr[: m.start()].rstrip()
    lead = ""
    if before.endswith(("/", "*")):                         # "cpu / 192.5": the operand it divides or multiplies
        k = len(before) - 1
        j = k - 1
        while j >= 0 and expr[j] == " ":
            j -= 1
        while j >= 0 and (expr[j].isalnum() or expr[j] == "_"):
            j -= 1
        lead = expr[j + 1: k + 1] + " "
    return short((lead + expr[m.start(): end]).strip(), 34)


def short(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def set_number(flows: list[dict], key: str, value: float) -> list[dict]:
    """A copy of the flows with the number at key set to value."""
    out = copy.deepcopy(flows)
    parts = key.split("/")
    f = out[int(parts[0])]
    r = f["rate"]
    if parts[1] in ("value", "k", "c"):
        r[parts[1]] = float(value)
    elif parts[1] == "terms":
        r["terms"][int(parts[2])]["k"] = float(value)
    elif parts[1] == "expr":
        want, seen = int(parts[2]), [0]

        def sub(m):
            j = seen[0]
            seen[0] += 1
            return repr(float(value)) if j == want else m.group(0)
        r["expr"] = NUM.sub(sub, r["expr"])
    return out


def true_flow_between(truth: dict, a, b) -> dict | None:
    """The true flow between the same two stocks (outside is None), if there is exactly one."""
    hits = [f for f in truth["flows"] if (f.get("from") or None) == (a or None) and (f.get("to") or None) == (b or None)]
    return hits[0] if len(hits) == 1 else None


def scale_true_rate(rate, factor: float, stock: str | None = None):
    """The true flow's rate with its part that reads `stock` scaled by factor (all of it when stock is None or it is
    an expression); None when it cannot be done."""
    if isinstance(rate, (int, float)):
        return rate * factor
    if isinstance(rate, str):
        return f"{factor} * ({rate})"
    if not isinstance(rate, dict):
        return None
    r = copy.deepcopy(rate)
    if "rate" in r and isinstance(r["rate"], (str, dict)):          # {rate: "...", exact: true} or with effects
        inner = scale_true_rate(r["rate"], factor, stock)
        if inner is None:
            return None
        r["rate"] = inner
        return r
    form = r.get("form")
    if form == "constant":
        r["value"] = float(r["value"]) * factor
    elif form == "proportional":
        r["k"] = float(r["k"]) * factor
    elif form == "linear":
        hit = False
        for term in r.get("terms") or []:
            if stock is None or term.get("stock") == stock:
                term["k"] = float(term["k"]) * factor
                hit = True
        if not hit and r.get("c"):
            r["c"] = float(r["c"]) * factor
    elif form == "expr" or "expr" in r:
        r["expr"] = f"{factor} * ({r['expr']})"
    else:
        return None
    return r


def data_for(case: dict, variant: str) -> dict:
    return ladder_data.load(case, variant)
