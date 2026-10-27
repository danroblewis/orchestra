"""``orchestra sd whatif``: interventions from the command line's words, and the answer as a table
(``sd.whatif``)."""

from __future__ import annotations


def _pair(s: str, what: str) -> tuple[str, str]:
    name, sep, value = s.rpartition("=")
    if not sep or not name:
        raise ValueError(f"{what}: expected NAME=VALUE, got {s!r}")
    return name, value


def interventions(flow: str | None = None, scale: float | None = None, add: float | None = None,
                  set_stock: list[str] = (), inputs: list[str] = (), input_scale: list[str] = (),
                  params: list[str] = ()) -> list[dict]:
    """The interventions the command line names: ``--flow F --scale X --add C``, ``--set-stock
    S=LEVEL``, ``--input NAME=VALUE``, ``--input-scale NAME=FACTOR``, ``--param FLOW.PARAM=VALUE``."""
    out = []
    if (scale is not None or add is not None) and not flow:
        raise ValueError("--scale and --add need --flow")
    if flow and scale is None and add is None:
        raise ValueError("--flow needs --scale or --add")
    if scale is not None:
        out.append({"kind": "scale_flow", "flow": flow, "factor": scale})
    if add is not None:
        out.append({"kind": "add_flow", "flow": flow, "amount": add})
    for s in set_stock:
        sid, v = _pair(s, "--set-stock")
        out.append({"kind": "set_stock", "stock": sid, "level": v})
    for s in inputs:
        name, v = _pair(s, "--input")
        out.append({"kind": "set_input", "input": name, "value": v})
    for s in input_scale:
        name, v = _pair(s, "--input-scale")
        out.append({"kind": "scale_input", "input": name, "factor": v})
    for s in params:
        target, v = _pair(s, "--param")
        fid, dot, param = target.rpartition(".")
        if not dot or not fid:
            raise ValueError(f"--param: expected FLOW.PARAM=VALUE, got {s!r}")
        out.append({"kind": "set_param", "flow": fid, "param": param, "value": v})
    return out


def bounds(specs: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """``--bound STOCK=LO:HI`` (either side may be empty)."""
    out = {}
    for s in specs:
        sid, rng = _pair(s, "--bound")
        lo, sep, hi = rng.partition(":")
        if not sep:
            raise ValueError(f"--bound: expected STOCK=LO:HI, got {s!r}")
        out[sid] = (float(lo) if lo.strip() else None, float(hi) if hi.strip() else None)
    return out


def _dur(s: float) -> str:
    return f"{s / 3600:g} h" if s >= 3600 and s % 360 == 0 else f"{s / 60:g} min" if s >= 60 else f"{s:g} s"


def _iv(iv: dict) -> str:
    k = iv["kind"]
    return {"scale_flow": f"flow {iv.get('flow')} × {iv.get('factor')}", "add_flow": f"flow {iv.get('flow')} + {iv.get('amount')}",
            "set_stock": f"stock {iv.get('stock')} = {iv.get('level')}", "set_input": f"input {iv.get('input')} = {iv.get('value')}",
            "scale_input": f"input {iv.get('input')} × {iv.get('factor')}",
            "set_param": f"flow {iv.get('flow')} {iv.get('param')} = {iv.get('value')}"}.get(k, k)


def table(r: dict) -> list[str]:
    """The answer, for a reader: what was changed, each stock now and at the horizon (baseline,
    intervention, difference, each with its band), the limits, and what is not trusted."""
    unit = r["time_unit"]
    m = r["model"]
    which = f"version {m['version']}" if m.get("version") else "the latest discovery"
    lines = [f"what if {', '.join(_iv(i) for i in r['interventions']) or 'nothing changes'}",
             (f"  model: {which}; {_dur(r['horizon_s'])} ahead in {r['step_s']:g} s steps; "
             f"band: 10th–90th percentile of {r['band']['members']} runs with the fitted rates perturbed by their recorded error"), ""]
    w = max([len("stock"), *(len(s) for s in r["stocks"])])
    lines.append(f"  {'stock':<{w}}  {'now':>9}  {'baseline':>22}  {'with change':>22}  {'difference':>24}  trusted")
    for sid, s in r["stocks"].items():
        def cell(b: dict, sign: bool = False) -> str:
            f = "+.2f" if sign else ".2f"
            return f"{b['central'][-1]:{f}} [{b['lo'][-1]:{f}}, {b['hi'][-1]:{f}}]"
        now = s["start"]["baseline"] if s["start"]["baseline"] == s["start"]["intervention"] else f"{s['start']['baseline']:g}→{s['start']['intervention']:g}"
        lines.append(f"  {sid:<{w}}  {now:>9}  {cell(s['baseline']):>22}  {cell(s['intervention']):>22}  {cell(s['difference'], True):>24}  "
                     f"{'yes' if s['trusted'] else 'NO'}")
    for fid, x in r["flows"].items():
        seen = f"; seen {x['observed'][0]:.4g}–{x['observed'][1]:.4g}" if x["observed"] else ""
        lines.append(f"  flow {fid} now: {x['baseline']:.4g} → {x['intervention']:.4g} per {unit}{seen}")
    if r["limits"]:
        lines += ["", "limits:"]
        for x in r["limits"]:
            when = f"at +{_dur(x['at_s'])}" if x["at_s"] is not None else "not in the central run"
            what = "reaches 0 (the floor)" if x["kind"] == "floor" else f"{x['kind']} {x['bound']:g}"
            lines.append(f"  {x['stock']} {what} in the {x['run']} {when}; in {x['members']:.0%} of the runs"
                         + ("  (new with the change)" if x.get("new") else ""))
    if r["not_trusted"]:
        lines += ["", "not trusted here:"]
        lines += [f"  {x['kind']} {x['id']}: {'; '.join(x['why'])}" for x in r["not_trusted"]]
    lines += ["", "verdict: " + ("the model is trusted for these stocks" if r["trusted"] else "NOT TRUSTED HERE: read the reasons above")]
    return lines
