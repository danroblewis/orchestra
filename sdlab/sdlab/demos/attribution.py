"""Demo 10, before/after attribution (docs/demos/attribution.md; ideas 36, 37 of OPERATIONALIZATION.md).

A simulated SRE project lands at step T on an in-memory copy of the 310 scenario's true model (the retry rate halves,
the error rate halves, or timeouts halve). The found model's structure is kept; only its numbers are refitted:
- on the steps before T: the "before" model. Run free from the state at T on the after-period's traffic, it is the
  counterfactual (what would have happened without the project). Measured minus counterfactual is the project's
  effect on the outcomes. Its band: on noise-free data, block-bootstrap draws of the refit; with counted noise, the
  spread of the same measurement on placebo runs (no project, their own seeds), which also holds the service's own
  randomness and the model's misfit (the bootstrap alone is far too narrow there). The true effect is the true model run
  with and without the project (noise-free) on the same traffic.
- on the steps after T: the "after" model. The numbers that moved (before vs after, with intervals) are the
  structural attribution: which flow the project changed, and by how much. A number "moved" when its z (divided by
  its root-mean-square z on the placebo runs, at least 1) passes Z and it changed by more than 1%.

The refit (`refit`) is one-step weighted least squares with the structure fixed: every proportional or linear number
of the found model's flows (not its expressions, effect tables or constants), Gauss-Newton on the scorer's
simulator for found models. (sdlab/discovery/refine.py refits by multi-step error, but its simulator does not take
measured inputs or expression rates, which this model has, so it is not used here.)

Nothing here changes a case, a simulation, a strategy or the result store. Cache: ~/.cache/sdlab/demos/attribution/
(regenerate: `uv run python -m sdlab.demos.attribution`)."""

from __future__ import annotations

import copy
import functools
import json
import math
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from ..ladder import data as ladder_data
from ..ladder import sim as ladder_sim
from . import demos as D
from . import engine as E

SCEN = "memory-oom"
T = 1000                                   # the step the project lands (from this step on, the new rate)
CACHE = Path.home() / ".cache" / "sdlab" / "demos" / "attribution"
PROJECTS = {
    "slower-retries": {"label": "a client release retries half as fast (retry rate 0.6 → 0.3 a step)",
                       "flow": "retried", "rate": {"form": "proportional", "stock": "retries", "k": 0.3}},
    "fewer-errors": {"label": "a bug fix halves the error rate (0.03 → 0.015 of requests in flight a step)",
                     "flow": "errors", "rate": {"form": "proportional", "stock": "inflight", "k": 0.015}},
    "fewer-timeouts": {"label": "a longer timeout halves timeouts (0.08 → 0.04 of the queue a step)",
                       "flow": "timeouts", "rate": {"form": "proportional", "stock": "queue", "k": 0.04}},
}
OUTCOMES = {
    "errors_total": {"label": "failed requests (counter)", "how": "total"},
    "responses_total": {"label": "successful responses (counter)", "how": "total"},
    "queue": {"label": "requests waiting", "how": "mean"},
    "retries": {"label": "requests waiting to retry", "how": "mean"},
    "oom_kills_total": {"label": "pods OOM-killed (counter)", "how": "total"},
}
Z = 3.0                                    # |z| for "moved": about a 5% family-wise level over ~15 numbers (Bonferroni)
REL = 0.01                                 # and by at least 1% of its value (a statistically sure but tiny move is not news)
MIN_STEPS = 20                             # a number that moves nothing on fewer steps than this is not identified there


# ---- the refit: the found model's structure fixed, its proportional and linear numbers refitted ----

def slots(flows: list[dict], measured: list[str]) -> list[dict]:
    """The numbers a refit may move: each proportional k and linear term of a flow that touches a measured stock and
    is not the measured input itself."""
    out = []
    for n in E.numbers(flows):
        f = flows[n["flow"]]
        part = n["key"].split("/")[1]
        if part not in ("k", "terms") or f.get("input"):
            continue
        if not ({f.get("from"), f.get("to")} & set(measured)):
            continue
        out.append(n)
    return out


def _model(flows, ids, t, inputs):
    return ladder_sim.found_model(flows, ids, inputs={"t": list(t), "values": inputs} if inputs else None)


def refit(flows: list[dict], measured: list[str], t: list, levels: dict, inputs: dict, rows: tuple[int, int],
          boot: int = 200, block: int = 50, seed: int = 0) -> dict:
    """Refit the numbers (slots) on the one-step equations i in [rows[0], rows[1]) (levels[i] from levels[i-1]),
    every measured stock's equation weighted by its residual spread. levels must hold the hidden stocks too (as the
    model carries them). Returns {flows, nums: [{key, ends, label, start, value, se, lo, hi}], draws (boot x slots),
    keys}; the interval is the 2.5-97.5% of a block bootstrap (blocks of `block` steps) of the equations."""
    ids = E.found_ids(flows, measured)
    A = np.array([np.asarray(levels[s], float) for s in ids])
    tt = np.asarray(t, float)
    i0, i1 = max(1, rows[0]), min(len(t), rows[1])
    prev, nxt, tn = A[:, i0 - 1:i1 - 1], A[:, i0:i1], tt[i0:i1]
    m = len(measured)
    sl = slots(flows, measured)
    keys = [s["key"] for s in sl]
    theta0 = np.array([s["value"] for s in sl], float)
    cur = copy.deepcopy(flows)

    def put(x):
        nonlocal cur
        for k, v in zip(keys, x):
            cur = E.set_number(cur, k, float(v))

    def resid():
        mdl = _model(cur, ids, t, inputs)
        return (nxt - mdl.step(prev, tn))[:m]

    def jac():
        cols = []
        for s in sl:                                   # each number moves only its own flow: a model of that flow alone
            f = cur[s["flow"]]
            one = _model([f], ids, t, inputs).change(prev, tn)[:m]
            k = s["key"]
            v = _get(cur, k)
            dv = max(1e-6, 1e-4 * abs(v))
            bumped = E.set_number([f], f"0/{'/'.join(k.split('/')[1:])}", v + dv)
            two = _model(bumped, ids, t, inputs).change(prev, tn)[:m]
            cols.append((two - one) / dv)
        return np.stack(cols, axis=-1)                 # stocks x steps x slots

    theta = theta0.copy()
    put(theta)
    r = resid()
    w = 1.0 / np.maximum(r.std(axis=1), 1e-9 + 1e-6 * np.abs(nxt[:m]).mean(axis=1))[:, None]
    for _ in range(5):                                 # Gauss-Newton: the flows are linear in their numbers but for floors
        J = jac()
        Jw, rw = J * w[:, :, None], r * w
        XtX = np.einsum("smj,smk->jk", Jw, Jw)
        Xty = np.einsum("smj,sm->j", Jw, rw)
        step = _solve(XtX, Xty)
        theta = theta + step
        put(theta)
        r = resid()
        if np.all(np.abs(step) <= 1e-7 * np.maximum(1.0, np.abs(theta))):
            break
    # block bootstrap of the (linearised) equations at the fitted numbers
    J = jac()
    Jw, rw = J * w[:, :, None], r * w
    n = Jw.shape[1]
    nb = max(1, n // block)
    edges = np.linspace(0, n, nb + 1).astype(int)
    XtXb = np.array([np.einsum("smj,smk->jk", Jw[:, a:b_], Jw[:, a:b_]) for a, b_ in zip(edges[:-1], edges[1:])])
    Xtyb = np.array([np.einsum("smj,sm->j", Jw[:, a:b_], rw[:, a:b_]) for a, b_ in zip(edges[:-1], edges[1:])])
    rng = np.random.default_rng(seed)
    full = _solve(XtXb.sum(axis=0), Xtyb.sum(axis=0))         # ~0 at a converged fit; draws are centred on it
    draws = np.empty((boot, len(theta)))
    for j in range(boot):
        c = rng.multinomial(nb, np.full(nb, 1.0 / nb)).astype(float)
        draws[j] = theta + _solve(np.tensordot(c, XtXb, 1), np.tensordot(c, Xtyb, 1)) - full
    lo, hi = np.percentile(draws, [2.5, 97.5], axis=0)
    se = draws.std(axis=0)
    used = (np.abs(J) > 1e-12).any(axis=0).sum(axis=0)        # the steps where each number moves anything
    nums = [{"key": s["key"], "flow": s["flow"], "ends": s["ends"], "label": s["label"], "start": float(s["value"]),
             "value": float(v), "se": float(e), "lo": float(a), "hi": float(b_), "identified": bool(u >= MIN_STEPS), "steps": int(u)}
            for s, v, e, a, b_, u in zip(sl, theta, se, lo, hi, used)]
    return {"flows": cur, "nums": nums, "draws": draws, "keys": keys, "steps": int(i1 - i0)}


def _get(flows, key):
    return next(n["value"] for n in E.numbers(flows) if n["key"] == key)


def _solve(XtX, Xty):
    """The normal equations, each number scaled to its own size first (the numbers' equations differ by orders of
    magnitude: cpu in millicores beside a retry share), with a tiny ridge for numbers the window cannot tell apart."""
    d = np.sqrt(np.maximum(np.diag(XtX), 1e-300))
    M = XtX / d[:, None] / d[None, :]
    y = np.linalg.lstsq(M + 1e-9 * np.eye(len(M)), Xty / d, rcond=None)[0]
    return y / d


def with_numbers(flows: list[dict], keys: list[str], values) -> list[dict]:
    out = flows
    for k, v in zip(keys, values):
        out = E.set_number(out, k, float(v))
    return out


# ---- the simulated service ----

def run(truth: dict, change: dict | None = None, counts: bool = False, seed: int | None = None, edits: dict | None = None,
        steps: int | None = None) -> dict:
    """The true model run (a copy): change {t, flow, rate} from step t on; edits {flow: rate} from the start; counts:
    the ladder's counts noise (flows move whole things, Poisson) with this seed. {t, levels (every stock), inputs}."""
    if not counts:
        r = E.run_truth(truth, steps=steps, change=change, edits=edits)
        return {"t": r["t"], "levels": {k: np.asarray(v, float) for k, v in r["levels"].items()}, "inputs": r["inputs"]}
    m = copy.deepcopy(truth)
    if steps:
        m["steps"] = int(steps)
    for fid, rate in (edits or {}).items():
        for f in m["flows"]:
            if f["id"] == fid:
                f["rate"] = rate
    if change:
        m.setdefault("schedule", {}).setdefault("changes", []).append(
            {"t": int(change["t"]), "label": "demo change", "set": {change["flow"]: change["rate"]}})
    m["noise"] = {"counts": True}
    r = ladder_data.simulate(m, seed=seed)
    return {"t": list(r["t"]), "levels": {k: np.asarray(v, float) for k, v in r["all_levels"].items()},
            "inputs": {k: list(v) for k, v in (r.get("inputs") or {}).items()}}


def carried(flows: list[dict], measured: list[str], r: dict) -> dict:
    """The measured levels plus the found model's own hidden stocks as it carries them one step ahead."""
    o = E.one_step(flows, measured, r["t"], {s: list(r["levels"][s]) for s in measured}, r["inputs"])
    out = {s: np.asarray(r["levels"][s], float) for s in measured}
    out.update({h: np.asarray(v, float) for h, v in o["hidden"].items()})
    return out


def _free(flows, measured, r, lv, k0):
    """The found model run free from the levels at index k0 to the end, on the run's measured inputs."""
    ids = E.found_ids(flows, measured)
    start = {s: float(lv[s][k0]) for s in ids}
    got = E.free_run(flows, measured, r["t"][k0:], start, {k: v[k0:] for k, v in r["inputs"].items()})
    return {s: np.asarray(v, float) for s, v in got.items()}


def _r(xs, nd=4):
    return [None if not math.isfinite(float(v)) else round(float(v), nd) for v in xs]


def tol(x: float) -> float:
    """Rounding room for "inside the band" (a noise-free band can be a single number)."""
    return 1e-3 * abs(x) + 1e-6


def _zs(before: dict, after: dict) -> list:
    """Each number's move (after - before) in bootstrap standard errors; None where a window cannot tell it."""
    out = []
    for a, b in zip(before["nums"], after["nums"]):
        se = math.hypot(a["se"], b["se"])
        z = (b["value"] - a["value"]) / se if se > 0 else (0.0 if b["value"] == a["value"] else math.inf)
        out.append((z if math.isfinite(z) else 1e9) if a["identified"] and b["identified"] else None)
    return out


def _moved(before: dict, after: dict, factor: dict) -> list[dict]:
    rows = []
    for a, b, zr in zip(before["nums"], after["nums"], _zs(before, after)):
        f = factor.get(a["key"], 1.0)
        z = None if zr is None else zr / f
        big = abs(b["value"] - a["value"]) > REL * max(abs(a["value"]), 1e-12)
        rows.append({"key": a["key"], "ends": a["ends"], "label": a["label"], "stored": a["start"], "identified": zr is not None,
                     "before": {k: a[k] for k in ("value", "se", "lo", "hi")}, "after": {k: b[k] for k in ("value", "se", "lo", "hi")},
                     "z": z, "z_raw": zr, "factor": f, "moved": bool(z is not None and abs(z) > Z and big)})
    return rows


# ---- placebo runs: the same measurement on runs with no project (calibration seeds, never the test seeds) ----

PLACEBO_SEEDS = tuple(range(101, 113))
EVERY = 2                                   # the page's series keep every second step


def placebo(counts: bool) -> dict:
    """The method on runs of the service with no project (noise-free: one run; counts: PLACEBO_SEEDS): each outcome's
    'effect' (it should be 0) as a series and a summary, and each number's before-vs-after z (it should be small).
    Cached in a file. With counts the spread of these is the band; each number's z is divided by its root-mean-square
    placebo z (at least 1)."""
    b = D._base(SCEN)
    path = CACHE / f"placebo-{'counts' if counts else 'none'}-r{b['result'].get('id')}.json"
    if path.exists():
        return json.loads(path.read_text())
    truth, meas, flows0 = b["truth"], b["measured"], b["result"]["found"]
    effects = {s: [] for s in OUTCOMES}
    summ = {s: [] for s in OUTCOMES}
    zs = []
    for sd in (PLACEBO_SEEDS if counts else PLACEBO_SEEDS[:1]):
        r = run(truth, None, counts, sd)
        kT = r["t"].index(T)
        lv = carried(flows0, meas, r)
        before = refit(flows0, meas, r["t"], lv, r["inputs"], (1, kT), seed=sd)
        after = refit(flows0, meas, r["t"], lv, r["inputs"], (kT, len(r["t"])), seed=sd + 100)
        cf = _free(before["flows"], meas, r, lv, kT - 1)
        for s, o in OUTCOMES.items():
            act = r["levels"][s][kT - 1:]
            effects[s].append(_r((act - cf[s])[::EVERY]))
            summ[s].append(_stat(act, o["how"]) - _stat(cf[s], o["how"]))
        zs.append(_zs(before, after))
        keys = [n["key"] for n in before["nums"]]
    factor = {}
    for j, k in enumerate(keys):
        got = [z[j] for z in zs if z[j] is not None]
        factor[k] = max(1.0, math.sqrt(sum(v * v for v in got) / len(got))) if got else 1.0
    out = {"counts": counts, "seeds": list(PLACEBO_SEEDS if counts else PLACEBO_SEEDS[:1]), "effects": effects, "summary": summ, "factor": factor}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def _stat(x: np.ndarray, how: str) -> float:
    return float(x[-1] - x[0]) if how == "total" else float(np.mean(x))


@functools.lru_cache(maxsize=24)
def attribution(project: str, counts: bool = False, seed: int = 1, cf_draws: int = 30) -> dict:
    """The demo for one project (and, with counts, one noise seed). See the module doc."""
    b = D._base(SCEN)
    if project not in PROJECTS:
        raise KeyError(project)
    pj = PROJECTS[project]
    change = {"t": T, "flow": pj["flow"], "rate": pj["rate"]}
    truth, meas, flows0 = b["truth"], b["measured"], b["result"]["found"]
    actual = run(truth, change, counts, seed)
    no_pj = run(truth)                                      # the truth without the project (noise-free)
    with_pj = run(truth, change) if counts else actual      # the truth with it (noise-free)
    t = actual["t"]
    kT = t.index(T)
    k0 = kT - 1                                             # the last step before the project
    lv = carried(flows0, meas, actual)
    before = refit(flows0, meas, t, lv, actual["inputs"], (1, kT), seed=seed)
    after = refit(flows0, meas, t, lv, actual["inputs"], (kT, len(t)), seed=seed + 100)
    cf = _free(before["flows"], meas, actual, lv, k0)
    rng = np.random.default_rng(seed + 7)
    pick = rng.choice(len(before["draws"]), size=min(cf_draws, len(before["draws"])), replace=False)
    cfs = [_free(with_numbers(before["flows"], before["keys"], before["draws"][j]), meas, actual, lv, k0) for j in pick]
    pl = placebo(counts)
    moved = _moved(before, after, pl["factor"])
    mv = [x for x in moved if x["moved"]]
    pred = _free(with_numbers(before["flows"], [x["key"] for x in mv], [x["after"]["value"] for x in mv]), meas, actual, lv, k0) if mv else None
    tf = next(f for f in truth["flows"] if f["id"] == pj["flow"])
    every = EVERY
    ta = t[k0:]
    out = {}
    for s, o in OUTCOMES.items():
        how = o["how"]
        act = actual["levels"][s][k0:]
        eff = (act - cf[s])[::every]
        true_eff = (with_pj["levels"][s][k0:] - no_pj["levels"][s][k0:])[::every]
        est = _stat(act, how) - _stat(cf[s], how)
        tr = _stat(with_pj["levels"][s][k0:], how) - _stat(no_pj["levels"][s][k0:], how)
        p_sum = np.asarray(pl["summary"][s], float)
        if counts:                                     # the band: the spread of the placebo 'effects' (noise and misfit)
            pe = np.array(pl["effects"][s], float)[:, : len(eff)]
            q_lo, q_hi = np.percentile(pe, [2.5, 97.5], axis=0)
            lo, hi = eff - q_hi, eff - q_lo
            s_lo, s_hi = (float(x) for x in np.percentile(p_sum, [2.5, 97.5]))
            e_lo, e_hi = est - s_hi, est - s_lo
            corrected = est - float(np.median(p_sum))    # what the method reports with no project, taken off
        else:                                          # the band: the refit's bootstrap draws
            band = np.array([(act - c[s])[::every] for c in cfs])
            lo, hi = np.percentile(band, [2.5, 97.5], axis=0)
            ests = np.array([est + _stat(cf[s], how) - _stat(c[s], how) for c in cfs])
            e_lo, e_hi = (float(x) for x in np.percentile(ests, [2.5, 97.5]))
            corrected = est
        p = (_stat(pred[s], how) - _stat(cf[s], how)) if pred else None
        out[s] = {"label": o["label"], "how": how, "unit": b["units"].get(s),
                  "effect": _r(eff), "lo": _r(lo), "hi": _r(hi), "true_effect": _r(true_eff),
                  "actual": _r(act[::every]), "counterfactual": _r(cf[s][::every]), "true_counterfactual": _r(no_pj["levels"][s][k0:][::every]),
                  "predicted_effect": _r((pred[s] - cf[s])[::every]) if pred else None,
                  "summary": {"estimate": est, "corrected": corrected, "lo": e_lo, "hi": e_hi, "truth": tr, "predicted": p, "placebo": float(np.mean(p_sum)),
                              "inside": bool(e_lo - tol(tr) <= tr <= e_hi + tol(tr))}}
    return {"source": D._source(b), "project": {"key": project, **pj, "t": T, "ends": f"{tf.get('from') or 'outside'} → {tf.get('to') or 'outside'}",
                                                 "before": tf.get("rate")},
            "counts": counts, "seed": seed if counts else None, "t": ta[::every], "outcomes": out, "numbers": moved,
            "moved": [x["ends"] + " " + x["label"] for x in mv], "z": Z, "rel": REL, "cf_draws": len(cfs),
            "band": "placebo" if counts else "bootstrap", "placebo_runs": len(pl["seeds"]),
            "refit": {"before_steps": before["steps"], "after_steps": after["steps"], "boot": len(before["draws"]), "block": 50}}


# ---- the counts case across seeds (slow: cached in a file) ----

SEEDS = tuple(range(1, 9))


def _cache_file(project: str) -> Path:
    b = D._base(SCEN)
    return CACHE / f"seeds-{project}-r{b['result'].get('id')}.json"


def seeds(project: str, compute: bool = True) -> dict:
    """With counts: each seed's estimated effect (and band) beside the true effect, and the retry-style number's
    after-refit interval beside the true new value. Cached per project and stored result."""
    if project not in PROJECTS:
        raise KeyError(project)
    path = _cache_file(project)
    if path.exists():
        return json.loads(path.read_text())
    if not compute:
        return {"project": project, "rows": None}
    rows = []
    pj = PROJECTS[project]
    new_k = float(pj["rate"]["k"])
    for s in SEEDS:
        r = attribution.__wrapped__(project, True, s, 20)
        hit = next((x for x in r["numbers"] if x["ends"] == r["project"]["ends"]), None)
        rows.append({"seed": s, "outcomes": {k: v["summary"] for k, v in r["outcomes"].items()},
                     "number": hit and {"before": hit["before"], "after": hit["after"], "moved": hit["moved"], "true_new": new_k,
                                        "inside": bool(hit["after"]["lo"] <= new_k <= hit["after"]["hi"])},
                     "moved": r["moved"]})
    out = {"project": project, "rows": rows, "source": D._source(D._base(SCEN))}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# ---- routes (under /api/demos) ----

router = APIRouter()


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/attribution/projects")
def projects_route() -> dict:
    return {"projects": {k: v["label"] for k, v in PROJECTS.items()}, "t": T, "outcomes": {k: v["label"] for k, v in OUTCOMES.items()}}


@router.get("/attribution/run")
def run_route(project: str, counts: bool = False, seed: int = 1) -> dict:
    return _guard(attribution, project, counts, max(1, min(seed, 99)))


@router.get("/attribution/seeds")
def seeds_route(project: str) -> dict:
    return _guard(seeds, project)


if __name__ == "__main__":                      # precompute the seed tables: uv run python -m sdlab.demos.attribution
    for old in CACHE.glob(f"placebo-*-r{D._base(SCEN)['result'].get('id')}.json"):
        old.unlink()
    for p in PROJECTS:
        path = _cache_file(p)
        if path.exists():
            path.unlink()
        got = seeds(p)
        print(p, path, len(got["rows"]))
