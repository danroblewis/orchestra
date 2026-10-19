"""Control metrics of a model (true or found) on the control cases (tag `control`): how the closed loop
answers a step, read off the model itself, so a found model is judged as a controller would judge it.

    metrics(flows, ids, x0, inputs, spec) -> {overshoot, settling, sse, gain, gm, pm, rho, zeta, ...}
    report(strategies, cases)             -> one row per latest result (true vs found)

**The step test.** All inputs are held at their operating values (the stepped input at its lowest
level on the run or the spec's `from`, every other at its mean), the time-varying parts of a found model (byTime
segments, outside inflow pieces) at their values at the run's last step, and the model is stepped
from the run's first levels (its own hidden stocks from 0) until it settles (the change in a step
below 1e-9 of the scale) or SETTLE_MAX steps. Then the stepped input (the setpoint, or for a case
without one the disturbance named in SPECS) moves up by `size` and the model runs RESPONSE steps.
From the controlled stock's response y:

- `overshoot`: how far y passes its final value, as a share of the change (0 when it never does);
- `settling`: steps until y stays within 2% of the change of its final value;
- `sse` (steady-state error): for a setpoint step, the share of the step that y falls short of in
  the end (1 - gain: 0 with integral action, 0.14 for 200's P control); for a disturbance step, the
  final shift of y per unit of the disturbance (what it leaves behind);
- `gain`: final change of y / size.

Settled means y's change and every other stock's change per step are constant (a stock that only
accumulates, like a final counter, drifts). A model whose level ends less than 5% of the step from where it was (`responds: False`: for a
setpoint step, a model that does not read the setpoint, or reads it only through a pure integrator
it does not close) gets no overshoot, settling or margins; its `sse` is still given (about 1).
A model that never settles gets `settles: False`; when
it stays bounded (on/off control's limit cycle) its `cycle` (y's swing, peak to peak, over the last
1,000 steps), `mean`, and `gain` (the mean's shift per unit of the step) are given instead.

**Margins** of the loop, from the model's linear part at the settled state (the one-step map's
Jacobian by central differences: A = dx'/dx, B = dx'/d input, the setpoint's column): the closed loop
from setpoint to y is T(z) = e_y (zI - A)^-1 B, and the equivalent unity-feedback loop is
L = T / (1 - T) (exact for a one-degree-of-freedom loop, where the controller sees only setpoint - y:
every control case but 202's derivative on the measurement and 207's cascade, where L is the loop a
single P/PI controller would need to give the same T). `gm`: 1 / |L| where L's phase crosses -180
degrees (inf when it never does); `pm`: 180 + L's phase where |L| crosses 1. `rho`: the spectral
radius of A (per step; above 1 unstable); `zeta`: the damping ratio of the slowest oscillating mode
(1 when no mode oscillates). A found model that does not read the setpoint has T = 0: no margins.

This is a report on the scorer's side (it reads the true model). It changes no status.
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

from ..discovery.observer import unmeasured
from ..discovery.simulate import Model
from ..skill import truth_by_time

SETTLE_MAX = 20_000
RESPONSE = 3_000
BAND = 0.02
NO_RESPONSE = 0.05          # a final change below 5% of the step: the model does not answer it

# the controlled stock, the input stepped, and the step's size, per control case (by id prefix)
SPECS = {
    "200": {"y": "T", "step": "setpoint", "size": 20},
    "201": {"y": "T", "step": "setpoint", "size": 20},
    "202": {"y": "H2", "step": "setpoint", "size": 20},
    "203": {"y": "V", "step": "setpoint", "size": 100},
    "204": {"y": "H", "step": "setpoint", "size": 20},
    "205": {"y": "T", "step": "setpoint", "size": 20},
    "206": {"y": "T", "step": "setpoint", "size": 20},
    "207": {"y": "H2", "step": "setpoint", "size": 20},
    "208": {"y": "H", "step": "demand", "size": 2, "disturbance": True},
    "209": {"y": "V", "step": "setpoint", "size": 100},
    "210": {"y": "T", "step": "outdoor", "size": 20, "disturbance": True},
    "211": {"y": "T", "step": "outdoor", "size": 20, "disturbance": True},
    "212": {"y": "Q", "step": "arrivals", "from": 11, "size": 2, "disturbance": True},     # in a rush: the controller holds Q
    "213": {"y": "Y", "step": "setpoint", "size": 20},
    "214": {"y": "Y", "step": "setpoint", "size": 20},
    "215": {"y": "Y", "step": "setpoint", "size": 20},
}


def spec_of(case_id: str) -> dict | None:
    for k, v in SPECS.items():
        if case_id.startswith(k):
            return v
    return None


def frozen(flows: list[dict], t: int) -> list[dict]:
    """The flows with their time-varying parts fixed at step t (a rate's byTime segment, an outside
    inflow piece): the model as it stands at the end of the run."""
    out = []
    for f in flows:
        f = dict(f)
        if f.get("byTime"):
            segs = f.pop("byTime")
            g = next((g for g in segs if g["from"] <= t <= g["to"]), segs[-1])
            f["rate"] = g["rate"]
        elif f.get("inflow"):
            segs = f.pop("inflow")
            g = next((g for g in segs if g["from"] <= t <= g["to"]), segs[-1])
            f["rate"] = {"form": "constant", "value": float(g["value"])}
        out.append(f)
    return out


class Loop:
    """A model's one-step map with its inputs held at given values."""

    def __init__(self, flows: list[dict], ids: list[str], ceilings: dict | None = None, watch: int = 0):
        self.flows, self.ids, self.ceilings, self.watch = flows, ids, ceilings, watch

    def model(self, u: dict) -> Model:
        return Model(self.flows, self.ids, inputs={"t": [0.0], "values": {k: [float(v)] for k, v in u.items()}} if u else None,
                     ceilings=self.ceilings)

    def run(self, x: np.ndarray, u: dict, steps: int, scale: float) -> tuple[np.ndarray, list[np.ndarray], bool]:
        """Step from x until it settles or `steps` run out: (last x, the path, settled)."""
        m = self.model(u)
        t = np.zeros(1)
        path = [x]
        last = None
        for _ in range(steps):
            nxt = m.step(x[:, None], t)[:, 0]
            path.append(nxt)
            if not np.all(np.isfinite(nxt)) or np.abs(nxt).max() > 1e9 * scale:
                return nxt, path, False
            d = nxt - x
            if last is not None and np.abs(d - last).max() < 1e-9 * scale and np.abs(d[self.watch]).max() < 1e-9 * scale:
                return nxt, path, True          # settled (a stock that only accumulates, e.g. a final counter, drifts)
            x, last = nxt, d
        return x, path, False

    def jacobian(self, x: np.ndarray, u: dict, name: str) -> tuple[np.ndarray, np.ndarray]:
        """A = dx'/dx and B = dx'/du[name] of one step at (x, u), by central differences."""
        t = np.zeros(1)
        n = len(x)
        A = np.zeros((n, n))
        m = self.model(u)
        for j in range(n):
            h = 1e-4 * max(1.0, abs(x[j]))
            xp, xm = x.copy(), x.copy()
            xp[j] += h
            xm[j] -= h
            A[:, j] = (m.step(xp[:, None], t)[:, 0] - m.step(xm[:, None], t)[:, 0]) / (2 * h)
        h = 1e-4 * max(1.0, abs(u[name]))
        mp, mm = self.model({**u, name: u[name] + h}), self.model({**u, name: u[name] - h})
        B = (mp.step(x[:, None], t)[:, 0] - mm.step(x[:, None], t)[:, 0]) / (2 * h)
        return A, B


def margins(A: np.ndarray, B: np.ndarray, iy: int) -> dict:
    """Gain and phase margins of L = T / (1 - T), T(z) = e_y (zI - A)^-1 B, on z = e^{iw}, 0 < w <= pi."""
    n = len(A)
    w = np.logspace(-5, math.log10(math.pi), 6000)
    eye = np.eye(n)
    T = np.array([np.linalg.solve(np.exp(1j * x) * eye - A, B)[iy] for x in w])
    if np.abs(T).max() < 1e-12:
        return {"gm": None, "pm": None, "reads_setpoint": False}
    L = T / (1 - T)
    mag, ph = np.abs(L), np.unwrap(np.angle(L))
    ph = ph - 2 * math.pi * round(ph[0] / (2 * math.pi))      # start in (-pi, pi]
    gm = math.inf
    for k in range(len(w) - 1):                                # phase crossing -180 degrees
        if (ph[k] + math.pi) * (ph[k + 1] + math.pi) <= 0 and ph[k] != ph[k + 1]:
            f = (-math.pi - ph[k]) / (ph[k + 1] - ph[k])
            gm = 1 / float(mag[k] + f * (mag[k + 1] - mag[k]))
            break
    pm = math.inf
    for k in range(len(w) - 1):                                # gain crossing 1
        if (mag[k] - 1) * (mag[k + 1] - 1) <= 0 and mag[k] != mag[k + 1]:
            f = (1 - mag[k]) / (mag[k + 1] - mag[k])
            pm = float(180 + math.degrees(ph[k] + f * (ph[k + 1] - ph[k])))
            break
    return {"gm": gm, "pm": pm, "reads_setpoint": True}


def modes(A: np.ndarray) -> dict:
    lam = np.linalg.eigvals(A)
    rho = float(np.abs(lam).max()) if len(lam) else 0.0
    osc = [x for x in lam if abs(x.imag) > 1e-9 and abs(x) > 1e-12]
    zeta = 1.0
    if osc:
        s = np.log(max(osc, key=abs))
        zeta = float(-s.real / abs(s))
    return {"rho": rho, "zeta": zeta}


CYCLE = 1_000


def cycle(loop: Loop, path: list[np.ndarray], u0: dict, name: str, size: float, iy: int, scale: float) -> dict:
    """A loop that never settles but stays bounded (on/off control's limit cycle): y's swing
    (peak to peak) and mean over the last CYCLE steps, and the mean's shift per unit of the step."""
    y = np.array([p[iy] for p in path[-CYCLE:]])
    if len(path) < CYCLE or not np.all(np.isfinite(y)) or np.abs(y).max() > 1e6 * scale:
        return {"cycle": None}
    _, after, _ = loop.run(path[-1], {**u0, name: u0[name] + size}, 3 * CYCLE, scale)
    y1 = np.array([p[iy] for p in after[-CYCLE:]])
    return {"cycle": float(y.max() - y.min()), "mean": float(y.mean()), "gain": float((y1.mean() - y.mean()) / size)}


def metrics(flows: list[dict], ids: list[str], x0: np.ndarray, u0: dict, spec: dict, scale: float,
            ceilings: dict | None = None) -> dict:
    """The step test and margins of one model (module docstring)."""
    iy = ids.index(spec["y"])
    loop = Loop(flows, ids, ceilings, watch=iy)
    name, size = spec["step"], float(spec["size"])
    x, path, ok = loop.run(np.asarray(x0, dtype=float), u0, SETTLE_MAX, scale)
    out: dict = {"settles": bool(ok)}
    if not ok:
        return {**out, **cycle(loop, path, u0, name, size, iy, scale)}
    A, B = loop.jacobian(x, u0, name)
    out.update(modes(A))
    if not spec.get("disturbance"):
        out.update(margins(A, B, iy))
    u1 = {**u0, name: u0[name] + size}
    xe, path, ok1 = loop.run(x, u1, RESPONSE * 10, scale)
    if not ok1:
        out["settles"] = False
        return out
    y = np.array([p[iy] for p in path[: RESPONSE + 1]])
    y0, yf = float(x[iy]), float(xe[iy])
    d = yf - y0
    out["gain"] = d / size
    out["sse"] = (1 - d / size) if not spec.get("disturbance") else d / size
    if abs(d) < NO_RESPONSE * size:
        # the level barely answers the step in the end: no overshoot or settling to speak of, and
        # for a setpoint step no loop to take margins of (L = T / (1 - T) with T(1) ~ 0)
        out["responds"] = False
        if not spec.get("disturbance"):
            out.update({"gm": None, "pm": None})
        return out
    out["responds"] = True
    rel = (y - y0) / d
    out["overshoot"] = float(max(0.0, rel.max() - 1))
    outside = np.nonzero(np.abs(rel - 1) > BAND)[0]
    out["settling"] = int(outside[-1] + 1) if len(outside) else 0
    return out


# ---- on the ladder's cases and results ----

def setup(case: dict, variant: str) -> dict:
    """The operating point of a case variant: inputs, start levels, the truth's flows and the scale."""
    from . import cases as casemod
    from . import data as datamod
    truth = casemod.truth_model(case, variant)
    d = datamod.load(case, variant)
    t = [int(x) for x in d["t"]]
    spec = spec_of(case["id"])
    ins = d.get("inputs") or {}
    u0 = {k: (float(spec.get("from", np.min(v))) if k == spec["step"] else float(np.mean(v))) for k, v in ins.items()}
    all_levels = d.get("all_levels") or d["levels"]
    measured = list(d["levels"])
    tflows, _ = truth_by_time(truth, [t[-1]])
    ceilings = {s["id"]: s["max"] for s in truth["stocks"] if s.get("max") is not None}
    scale = max(1.0, max(abs(float(v)) for lv in d["levels"].values() for v in lv))
    return {"spec": spec, "u0": u0, "t_end": t[-1], "measured": measured, "ids": list(all_levels),
            "x0": {k: float(v[0]) for k, v in all_levels.items()}, "truth": frozen(tflows, t[-1]), "scale": scale,
            "ceilings": ceilings}


def true_metrics(s: dict) -> dict:
    x0 = np.array([s["x0"][k] for k in s["ids"]])
    return metrics(s["truth"], s["ids"], x0, s["u0"], s["spec"], s["scale"], s["ceilings"])


def found_metrics(s: dict, found_flows: list[dict]) -> dict:
    flows = frozen(found_flows, s["t_end"])
    hidden = unmeasured(flows, s["measured"])
    ids = s["measured"] + hidden
    x0 = np.array([s["x0"][k] for k in s["measured"]] + [0.0] * len(hidden))
    if s["spec"]["y"] not in ids:
        return {"settles": False}
    return metrics(flows, ids, x0, s["u0"], s["spec"], s["scale"])


def report(strategies: list[str] | None, case_sel: str | None) -> list[dict]:
    from . import cases as casemod
    from . import runner, store
    cids = [c for c in (runner.select_cases(case_sel) if case_sel else casemod.case_ids()) if spec_of(c)]
    rows, cache = [], {}
    for r in store.latest(found=True):
        if r["case"] not in cids or (strategies and r["strategy"] not in strategies):
            continue
        key = (r["case"], r["variant"])
        if key not in cache:
            c = casemod.load(r["case"])
            if r["variant"] not in {v["name"] for v in c["variants"]}:     # a variant since dropped (prune.py archives such rows)
                cache[key] = None
            else:
                s = setup(c, r["variant"])
                cache[key] = (s, true_metrics(s))
        if cache[key] is None:
            continue
        s, tm = cache[key]
        found = r.get("found")
        flows = found.get("flows") if isinstance(found, dict) else found
        fm = found_metrics(s, flows) if flows else {"settles": False}
        rows.append({"case": r["case"], "variant": r["variant"], "strategy": r["strategy"], "status": r["status"],
                     "result": r["id"], "true": tm, "found": fm})
    return rows


def _f(v, fmt="{:.3g}") -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    return fmt.format(v)


def line(m: dict) -> str:
    if m.get("settles") and m.get("responds") is False:
        return f"does not answer the step (sse {_f(m.get('sse'))})"
    if not m.get("settles"):
        if m.get("cycle") is not None:
            return f"limit cycle: swing {_f(m['cycle'])} around {_f(m['mean'])}, mean shift per unit step {_f(m['gain'])}"
        return "does not settle"
    return (f"os {_f(100 * m['overshoot'], '{:.1f}') if 'overshoot' in m else '-'}% ts {_f(m.get('settling'))} "
            f"sse {_f(m.get('sse'))} gm {_f(m.get('gm'))} pm {_f(m.get('pm'), '{:.0f}')} rho {_f(m.get('rho'), '{:.4f}')} "
            f"zeta {_f(m.get('zeta'), '{:.2f}')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sdlab.ladder.control", description=__doc__.split("\n\n")[0])
    ap.add_argument("--strategies")
    ap.add_argument("--cases", default="tag:control")
    ap.add_argument("--truth", action="store_true", help="only the true models' metrics, per case and variant")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.truth:
        from . import cases as casemod
        from . import runner
        out = []
        for cid in runner.select_cases(a.cases):
            if not spec_of(cid):
                continue
            c = casemod.load(cid)
            for v in c["variants"]:
                s = setup(c, v["name"])
                out.append({"case": cid, "variant": v["name"], "true": true_metrics(s)})
        if a.json:
            print(json.dumps(out, indent=1, default=str))
        else:
            for o in out:
                print(f"{o['case']:40s} {o['variant']:13s} {line(o['true'])}")
        return 0
    rows = report(a.strategies.split(",") if a.strategies else None, a.cases)
    if a.json:
        print(json.dumps(rows, indent=1, default=str))
        return 0
    for r in rows:
        print(f"{r['case']:40s} {r['variant']:13s} {r['strategy']:12s} {r['status']:10s} found: {line(r['found'])}\n"
              f"{'':78s} true:  {line(r['true'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
