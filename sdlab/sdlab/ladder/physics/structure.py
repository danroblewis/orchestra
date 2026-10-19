"""Structure agreement for the physics cases: which stocks (and measured inputs) a model's change of
each stock depends on, with what sign and in what shape, read from the model's Jacobian over the
run's states and compared with the couplings the physics declares.

For a found model (SD Lab flows), p_XY(state) = d(one-step change of X) / d(level of Y), by central
differences of `simulate.Model.change` at every state of the run (the measured levels and the
inputs' values of each step). For the physics, the same from the ODE's right-hand side (per unit
time; a step is one unit). The representation does not matter: a move and a link with a drain, or
births and deaths of one stock, have the same Jacobian, so the coupling graph is what the data can
say whatever flows a strategy wrote.

A coupling X <- Y:
  strength  sqrt(mean p^2) x sd(Y): how much X's change moves when Y moves by its typical amount
  present   strength >= REL (10%) of the strongest coupling into X. The threshold is not 0 because
            sampling continuous time makes the exact one-step map read stocks the ODE does not, at
            O(step / time constant) (a damped oscillator's position reads itself at about w^2 / 2);
            the cases keep their time constants >= 10 steps so those terms stay under it
  sign      "+" when p > 0 on >= 90% of the states where it is not ~0, "-" likewise, else "±"
  shape     linear      p constant (sd <= 5% of |mean|)
            piecewise   p sits at two levels (>= 90% of states within 5% of its min or max, each
                        >= 5%): a switch, or a floor that binds (a rate at 0)
            product     p follows another variable (R^2 >= 0.5): X's change reads Y times it
            concave     p follows Y itself, |p| falling as Y grows (sqrt-like); convex: rising
            other       none of these (e.g. numbers that change with time)
The physics' shapes map to these: linear -> linear, sqrt -> concave, product -> product,
switch -> piecewise.
"""

from __future__ import annotations

import numpy as np

from ...discovery.simulate import Model

REL = 0.10
SIGN_SHARE = 0.9
SHAPE_CLASS = {"linear": "linear", "sqrt": "concave", "product": "product", "switch": "piecewise"}


def variables(data: dict, inputs: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """(names, values: variables x states, times) of the run: the measured stocks, then the inputs."""
    ids = list(data["levels"])
    lv = data.get("all_levels") or data["levels"]
    names = ids + [k for k in inputs if k in (data.get("inputs") or {})]
    V = np.array([np.asarray(lv[s], dtype=float) for s in ids] + [np.asarray(data["inputs"][k], dtype=float) for k in names[len(ids):]])
    return names, V, np.asarray(data["t"], dtype=float)


def found_jacobian(flows: list[dict], data: dict, inputs: list[str]) -> tuple[list[str], list[str], np.ndarray]:
    """(receivers, sources, p: receivers x sources x states) of a found model on the run's states. The
    model's own unmeasured stocks are held at 0 (a coupling through one is not counted)."""
    names, V, t = variables(data, inputs)
    ids = list(data["levels"])
    hidden = sorted({s for f in flows for s in (f.get("from"), f.get("to")) if s and s not in names})
    allnames = names + hidden
    model = Model(_plain(flows), allnames)                    # inputs read as levels: they are rows of L
    L = np.vstack([V, np.zeros((len(hidden), V.shape[1]))])
    n_r = len(ids)
    p = np.zeros((n_r, len(names), V.shape[1]))
    for j in range(len(names)):
        h = 1e-4 * max(float(np.std(V[j])), 1e-3 * max(1.0, float(np.mean(np.abs(V[j])))))
        up, dn = L.copy(), L.copy()
        up[j] += h
        dn[j] = np.maximum(dn[j] - h, np.minimum(dn[j], 0.0))     # one-sided at 0: a level never goes below it (the rate floor)
        p[:, j, :] = (model.change(up, t)[:n_r] - model.change(dn, t)[:n_r]) / (up[j] - dn[j])
    return ids, names, np.nan_to_num(p)


def _plain(flows: list[dict]) -> list[dict]:
    """Flows as the simulator steps them: a hidden path (`via`) is read as the direct flow it delays."""
    return [{k: v for k, v in f.items() if k != "via"} for f in flows]


def physics_jacobian(system, p: dict, drive, x: np.ndarray, t: np.ndarray, modes=None) -> np.ndarray:
    """p[receiver, source, state] of the ODE's right-hand side at states x (stocks x states) and
    times t; sources are the stocks then the system's inputs (an input's derivative by moving its
    value: the right-hand side reads it through the drive)."""
    n, m = x.shape
    names = system.ids + list(system.inputs)
    out = np.zeros((n, len(names), m))
    for k in range(m):
        mode = bool(modes[k]) if modes is not None else None
        for j in range(len(names)):
            h = 1e-5 * max(1.0, abs(float(x[j, k])) if j < n else 1.0)
            if j < n:
                up, dn = x[:, k].copy(), x[:, k].copy()
                up[j] += h
                dn[j] -= h
                out[:, j, k] = (system.rhs(t[k], up, p, drive, mode) - system.rhs(t[k], dn, p, drive, mode)) / (2 * h)
            else:
                name = names[j]
                base = drive.funcs[name]
                drive.funcs[name] = lambda tt, b=base: b(tt) + h
                a = system.rhs(t[k], x[:, k], p, drive, mode)
                drive.funcs[name] = lambda tt, b=base: b(tt) - h
                c = system.rhs(t[k], x[:, k], p, drive, mode)
                drive.funcs[name] = base
                out[:, j, k] = (a - c) / (2 * h)
    return out


def couplings(receivers: list[str], sources: list[str], p: np.ndarray, V: np.ndarray) -> list[dict]:
    """Every coupling X <- Y with its strength, relative strength, sign and shape (module docstring)."""
    sd = np.array([max(float(np.std(V[j])), 1e-12) for j in range(len(sources))])
    out = []
    for i, x in enumerate(receivers):
        st = np.sqrt(np.mean(p[i] ** 2, axis=1)) * sd
        top = float(st.max()) if len(st) else 0.0
        for j, y in enumerate(sources):
            rel = float(st[j] / top) if top > 0 else 0.0
            out.append({"receiver": x, "source": y, "strength": float(st[j]), "rel": rel, "present": rel >= REL and st[j] > 1e-12,
                        "sign": sign(p[i, j]), "shape": shape(p[i, j], V, j)})
    return out


def sign(p: np.ndarray) -> str:
    big = float(np.max(np.abs(p))) if len(p) else 0.0
    if big <= 0:
        return "0"
    pos, neg = int((p > 0.02 * big).sum()), int((p < -0.02 * big).sum())
    if pos >= SIGN_SHARE * (pos + neg):
        return "+"
    if neg >= SIGN_SHARE * (pos + neg):
        return "-"
    return "±"


def shape(p: np.ndarray, V: np.ndarray, j: int) -> str:
    m, s = float(np.mean(p)), float(np.std(p))
    if s <= 0.05 * abs(m) + 1e-15:
        return "linear"
    lo, hi = float(p.min()), float(p.max())
    r = hi - lo
    near_lo, near_hi = p <= lo + 0.05 * r, p >= hi - 0.05 * r
    if np.mean(near_lo | near_hi) >= 0.9 and np.mean(near_lo) >= 0.05 and np.mean(near_hi) >= 0.05:
        return "piecewise"
    r2 = [_r2(p, V[k]) for k in range(V.shape[0])]
    best = int(np.argmax(r2))
    if r2[best] < 0.5:
        return "other"
    if best != j:
        return "product"
    return "concave" if np.corrcoef(np.abs(p), V[j])[0, 1] < 0 else "convex"


def _r2(p: np.ndarray, z: np.ndarray) -> float:
    if np.std(z) <= 0 or np.std(p) <= 0:
        return 0.0
    c = float(np.corrcoef(p, z)[0, 1])
    return c * c if np.isfinite(c) else 0.0


def compare(expected: list[tuple[str, str, str, str]], found: list[dict]) -> dict:
    """The found couplings against the physics': {couplings: one row per expected coupling, spurious:
    present couplings the physics lacks, ok (graph and signs right, nothing spurious), right (expected
    couplings present with the right sign), of, shape_right, shape_of, recall, precision}."""
    by = {(c["receiver"], c["source"]): c for c in found}
    rows, keys = [], set()
    for x, y, sg, shp in expected:
        keys.add((x, y))
        c = by.get((x, y)) or {"present": False, "sign": "0", "shape": None, "rel": 0.0, "strength": 0.0}
        sign_ok = bool(c["present"]) and (c["sign"] == sg or (sg == "±" and c["sign"] in "+-±"))
        want = SHAPE_CLASS.get(shp, shp)
        rows.append({"receiver": x, "source": y, "key": f"{x} <- {y}", "sign_true": sg, "shape_true": shp, "class_true": want,
                     "present": bool(c["present"]), "sign_found": c["sign"] if c["present"] else None,
                     "shape_found": c["shape"] if c["present"] else None, "rel": c["rel"],
                     "sign_ok": sign_ok, "shape_ok": bool(c["present"]) and c["shape"] == want})
    spurious = [{"receiver": c["receiver"], "source": c["source"], "key": f"{c['receiver']} <- {c['source']}", "sign": c["sign"],
                 "shape": c["shape"], "rel": c["rel"]} for c in found if c["present"] and (c["receiver"], c["source"]) not in keys]
    right = sum(r["sign_ok"] for r in rows)
    present = sum(1 for c in found if c["present"])
    return {"couplings": rows, "spurious": spurious, "ok": right == len(rows) and not spurious, "right": right, "of": len(rows),
            "shape_right": sum(r["shape_ok"] for r in rows), "shape_of": len(rows),
            "recall": right / len(rows) if rows else 1.0, "precision": right / present if present else (1.0 if not rows else 0.0)}
