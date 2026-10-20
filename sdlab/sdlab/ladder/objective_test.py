"""The objective test (docs/research/unified-design.md, section 7): on each cell, does the TRUE model
score better under the unified objective J than every wrong stored model, when all are refitted the
same way from the discovery view? It tells objective failures from search failures.

    uv run sdlab-ladder objective-test --cases 003,009 [--variants counts-short] [--jobs 4] [--timeout 900]
    uv run sdlab-ladder objective-test --sets p0 --out p0.json
    uv run sdlab-ladder objective-test --sets p1 --report-only

The harness side (this module) reads the truth and the store; the evaluator
(sdlab/discovery/strategies/unified/) gets only the discovery view (its loader asserts it) and flows.

Per cell (case, variant):
- the truth T (skill.truth_by_time on the evaluator's grid; its hidden starts, ceilings, dt, signed
  stocks): T0 = its written numbers with only eta fitted; T* = refitted from them and 4 starts
  perturbed by up to +-30% (fixed seed), the lowest J kept;
- every distinct stored found model (store.latest(found=True), errors and empty ones dropped),
  grouped by structure (numbers stripped, piece places kept): refitted from the first two members'
  numbers and from the lean start, the lowest J kept (W*). A stored status from an older scorer is
  re-scored. Wrong = fail; right = pass or equivalent;
- the hard negatives analysis.alternatives(): structures with no more numbers than the truth that
  make the same mean change, graded by score.equations;
- the sanity block on T (S), and the label of every wrong candidate by delta = J(W*) - J(T*):
  OK (> eps), X (its refitted numbers re-score as right), TIE (|delta| <= eps; known if an alternative
  or the cell is unidentifiable), F (T* did not converge or its restarts disagree), L (data-limited
  or unidentifiable cell), E (objective failure: split into its D, P_num and P_struct parts, E-price
  when D favours the truth; with what the winner has that the truth lacks). C (class gap: the truth
  cannot be expressed yet) is a cell label of its own. P (the particle referee) is not built: never
  given. The cell takes its worst label (E > P > F > S > L > TIE > OK).
- the same labels under plain one-step BIC (D + 1/2 k ln N, the A-bic arm) for comparison.

Results go to a study cache, $SDLAB_LADDER_CACHE/objective_test/<code table>-<evaluator hash>/, one
JSON per cell, written after every candidate, so a run resumes where it stopped. Never to the store.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import time
import traceback
from pathlib import Path

import numpy as np

from . import cases as casemod
from .data import cache_root

EVALUATOR = Path(__file__).resolve().parent.parent / "discovery" / "strategies" / "unified"
ORDER = ["E", "P", "F", "S", "L", "TIE", "OK"]
OBSERVE_GAPS = ("lag", "weekly", "bias")     # observation choices (lag, span, scale) are not built in v1
SETS = {
    # P0: the named rows of section 7.6 (the ones the class can hold today run; the rest are C)
    "p0": "056,sd-eras,080,sd-population,sd-webshop-stock,sd-hidden-chain,009,045,046,010,016,033,085,088#2,part-stirred-chambers,phys-mass-spring-damper",
    "p1": "tag:chain,tag:link,tag:loop,tag:move,tag:inflow,tag:outflow",
    "p2": "tag:noisy",
    "p3": "tag:hidden",
    "p4": "tag:effect,tag:coflow,tag:nonlinear",
    "p5": "tag:realistic,tag:physics,tag:particles,tag:real",
}
P0_VARIANTS = {"056": "counts-long", "sd-eras": "counts-long", "080": "bias-short", "010": "counts-short", "016": "counts-short"}


def evaluator_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(EVALUATOR.glob("*.py")):
        h.update(p.read_bytes())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:10]


def cache_dir() -> Path:
    from ..discovery.strategies.unified.price import CODE_TABLE
    return cache_root() / "objective_test" / f"{CODE_TABLE}-{evaluator_hash()}"


def _cell_path(cid: str, variant: str, where: Path | None = None) -> Path:
    return (where or cache_dir()) / f"{cid.replace('#', '_')}__{variant}.json"


def view_of(model: dict, d: dict) -> dict:
    """The discovery view, exactly as runner.discover builds it."""
    v = {"stocks": casemod.page_stocks(model), "t": d["t"], "levels": d["levels"]}
    if len(d.get("eras") or []) > 1:
        v["eras"] = d["eras"]
    if d.get("injections"):
        v["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
    if d.get("inputs"):
        v["inputs"] = {k: list(x) for k, x in d["inputs"].items()}
    return v


def _skeleton(f: dict) -> dict:
    """One flow with every number stripped and piece places kept."""
    from ..discovery.strategies.unified.frontend import NotExpressible, _segments
    try:
        segs = [(s[0], sorted(str(k) for k in s[1])) for s in _segments(f)]
    except NotExpressible:
        segs = [("expr", json.dumps(f.get("rate"), sort_keys=True))]
    return {"from": f.get("from"), "to": f.get("to"), "ratio": float(f.get("ratio") or 1), "two_way": bool(f.get("two_way")),
            "signed": f.get("signed"), "segs": segs,
            "uses": sorted(u.get("stock") for u in f.get("uses") or [] if float(u.get("per") or 0) > 0),
            "effects": [(e.get("stock"), e.get("shape"), [round(float(p[0]), 9) for p in e.get("points") or []],
                         sorted(k for k in ("normal", "min", "max") if e.get(k) is not None)) for e in f.get("effects") or []]}


def canonical(flows: list[dict]) -> list[dict]:
    """The flows in a fixed order (by skeleton), so two models of one structure lay out the same slots."""
    return sorted(flows, key=lambda f: json.dumps(_skeleton(f), sort_keys=True, default=str))


def signature(flows: list[dict]) -> str:
    """A found model's structure: its flows with every number stripped and piece places kept."""
    out = [_skeleton(f) for f in flows]
    out.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _score_hash(c: dict) -> str:
    from . import particles, physics, score
    from . import sim as _sim
    sh = score.score_hash()
    shc = particles.score_hash(sh) if particles.is_particles(c) else physics.score_hash(sh) if physics.is_physics(c) else sh
    return _sim.code_hash(shc) if _sim.uses_new(c.get("model") or {}) else shc


def _plausible(eta: dict, v: dict, grid) -> tuple[bool, str]:
    """Is the truth's fitted noise character plausible for the variant (section 7.5)?"""
    noise = v.get("noise")
    obs = v.get("observe") or {}
    q2 = {s: float(q) ** 2 for s, q in zip(grid.ids, grid.q)}
    sc2 = {s: float(x) ** 2 for s, x in zip(grid.ids, grid.scale)}
    small = lambda x, s: x <= max(0.1 * q2[s], 1e-4 * sc2[s])  # noqa: E731
    if noise == "none":
        ok = eta["phi"] < 0.05 and all(small(eta["tau"][s], s) and small(eta["alpha"][s], s) for s in grid.ids)
        return ok, f"none: phi {eta['phi']:.3g}, variances at their floor: {ok}"
    if not 0.7 <= eta["phi"] <= 1.4:
        return False, f"counting: phi {eta['phi']:.3g} outside [0.7, 1.4]"
    if obs.get("kind") == "meas":
        rel, ab = float(obs.get("rel", 0.05)), float(obs.get("abs", 1.0))
        bad = [s for s in grid.ids if not (0.5 * ab ** 2 <= eta["alpha"][s] + 1e-12 <= 2 * ab ** 2 or ab == 0)
               or not (0.5 * rel ** 2 <= eta["rho2"][s] <= 2 * rel ** 2 or rel == 0)]
        return not bad, f"meas: alpha/rho2 off by more than x2 on {bad}" if bad else "meas: ok"
    bad = [s for s in grid.ids if not small(eta["tau"][s], s)]
    return not bad, f"counts: tau not near 0 on {bad}" if bad else "counts: ok"


def _mechanism(w: dict, t: dict) -> list[str]:
    """What the winner W has that the truth T lacks (E subtypes)."""
    out = []
    cw, ct = w["fit"]["complexity"], t["fit"]["complexity"]
    if cw["cuts"] > ct["cuts"]:
        out.append("extra pieces")
    if cw["flows"] > ct["flows"]:
        out.append("extra flows")
    if cw["numbers"] < ct["numbers"]:
        out.append("fewer numbers")
    if w.get("self_reinforcing") and not t.get("self_reinforcing"):
        out.append("self-reinforcing reading")
    if (w.get("links") or 0) > (t.get("links") or 0):
        out.append("spurious link")
    ew, et = w["fit"]["eta_read"], t["fit"]["eta_read"]
    if ew["phi"] > 2 * et["phi"] + 1e-9 or any(ew["tau"][s] > 4 * et["tau"][s] + 1e-9 for s in ew["tau"]):
        out.append("noise absorbing structure (tau or phi)")
    return out


def _shape(flows: list[dict]) -> dict:
    """Readings that the E subtypes name: an inflow reading its own destination with a positive k
    (self-reinforcing) and flows reading a stock other than their source (links)."""
    from ..discovery.strategies.unified.frontend import _segments
    sr, links = False, 0
    for f in flows:
        for _, nf, _ in _segments(f):
            for r, k in nf.items():
                if r is not None and r == f.get("to") and f.get("from") != r and k > 0:
                    sr = True
            if any(r is not None and r != f.get("from") for r in nf):
                links += 1
                break
    return {"self_reinforcing": sr, "links": links}


class _Clock:
    def __init__(self, seconds: float | None):
        self.end = time.time() + seconds if seconds else None

    def left(self) -> bool:
        return self.end is None or time.time() < self.end


def run_cell(cid: str, variant: str, timeout: float | None = 900.0, max_groups: int = 40, where: Path | None = None) -> dict:
    """Compute (or resume) one cell; the cell's JSON (also written to the cache: `where`, fixed by the
    caller when the run starts, so an edit to the evaluator during a run cannot split its cells)."""
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    path = _cell_path(cid, variant, where)
    path.parent.mkdir(parents=True, exist_ok=True)
    cell = {}
    if path.exists():
        try:
            cell = json.loads(path.read_text())
        except ValueError:
            cell = {}
    if cell.get("done"):
        return cell
    clock = _Clock(timeout)
    cell.update({"case": cid, "variant": variant, "evaluator": (where or cache_dir()).name})

    def save():
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cell, default=_jsonable))
        tmp.replace(path)

    try:
        _compute(cell, cid, variant, clock, save, max_groups)
    except Exception:  # noqa: BLE001  (a cell that breaks is reported, the run carries on)
        cell["error"] = " ".join(traceback.format_exc().strip().splitlines()[-3:])[:2000]
    save()
    return cell


def _jsonable(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, set):
        return sorted(x)
    raise TypeError(type(x))


def _compute(cell: dict, cid: str, variant: str, clock: _Clock, save, max_groups: int) -> None:
    from ..discovery.strategies.unified import objective as ob
    from ..discovery.strategies.unified.frontend import NotExpressible, grid_of
    from ..discovery.strategies.unified.price import EPSILON
    from ..skill import truth_by_time
    from . import analysis, data, particles, physics, score, store
    from . import sim as _sim

    c = casemod.load(cid)
    v = casemod.variant(c, variant)
    cell["noise"] = v["noise"]
    cell["tags"] = c.get("tags") or []
    a = analysis.get(cid, variant, compute=False) if not (c.get("real") or physics.is_physics(c) or particles.is_particles(c)) else None
    cell["analysis"] = (a or {}).get("label") or "not analysed"
    reason = None
    if c.get("real") or physics.is_physics(c) or particles.is_particles(c):
        reason = "no proxy truth yet (physics, particles, real: section 7.3, step 3)"
    elif (v.get("observe") or {}).get("kind") in OBSERVE_GAPS:
        reason = f"observation choice {(v.get('observe') or {}).get('kind')} (lag, span, scale) not built in v1"
    tm = casemod.truth_model(c, variant)
    if reason is None and _sim.uses_new(tm):
        reason = "a 2d engine feature (expression, switch, auxiliary, signed stock, two-way flow)"
    if reason:
        cell.update(label="C", why=reason, done=True)
        return
    d = data.load(c, variant)
    view = view_of(tm, d)
    grid = grid_of(view)
    times = [int(x) for x in grid.times]
    truth_flows, _ = truth_by_time(tm, times)
    truth_flows = json.loads(json.dumps(truth_flows))
    measured = {s["id"] for s in view["stocks"]}
    opts = {"dt": float(tm.get("dt") or 1),
            "ceilings": {s["id"]: s["max"] for s in tm["stocks"] if s.get("max") is not None},
            "signed": {s["id"] for s in tm["stocks"] if s.get("signed")},
            "hidden_starts": {s["id"]: float(s.get("initial") or 0) for s in tm["stocks"] if s["id"] not in measured}}
    try:
        mt = ob.prepare(view, truth_flows, grid=grid, **opts)
    except NotExpressible as e:
        cell.update(label="C", why=f"the truth is not expressible: {e}", done=True)
        return
    cell["reports"] = grid.n_reports
    th0 = mt.theta0
    if "T0" not in cell:
        cell["T0"] = _brief(ob.fit(mt, [th0], fit_theta=False))
        save()
    if "Tstar" not in cell:
        rng = np.random.default_rng(20261019)
        starts = [th0] + [th0 * rng.uniform(0.7, 1.3, size=th0.shape) for _ in range(4)]
        r = ob.fit(mt, starts)
        cell["Tstar"] = {**_brief(r), "flows": ob.fitted_flows(mt, r["theta"]), **_shape(truth_flows)}
        save()
    T = cell["Tstar"]
    if "sanity" not in cell:
        cell["sanity"] = _sanity(cell, mt, th0, v, grid, ob)
        save()
    if not clock.left():
        cell["timeout"] = True
        return
    # candidates: stored found models, grouped by structure; then the hard negatives
    sh = _score_hash(c)
    groups: dict[str, dict] = cell.setdefault("groups", {})
    if "listed" not in cell:
        rows = [r for r in store.latest(cid, variant, found=True) if r["status"] not in ("error", "timeout") and r.get("found")]
        for r in rows:
            status = r["status"]
            if r["score_hash"] != sh:
                try:
                    status = score.equations(c, v["noise"], tm, r["found"], d)["status"]
                except Exception:  # noqa: BLE001
                    status = "unscored"
            sig = signature(r["found"])
            g = groups.setdefault(sig, {"sig": sig, "source": "store", "strategies": [], "statuses": [], "numbers": []})
            g["strategies"].append(r["strategy"])
            g["statuses"].append(status)
            if len(g["numbers"]) < 2 and r["found"] not in g["numbers"]:
                g["numbers"].append(r["found"])
        for i, (why, alt) in enumerate(analysis.alternatives(tm, measured)):
            af, _ = truth_by_time(alt, times)
            af = json.loads(json.dumps(af))
            try:
                status = score.equations(c, v["noise"], tm, af, d)["status"]
            except Exception:  # noqa: BLE001
                status = "unscored"
            sig = "alt" + str(i) + "-" + signature(af)
            groups[sig] = {"sig": sig, "source": "alternative", "why": why, "strategies": [], "statuses": [status], "numbers": [af]}
        cell["listed"] = True
        save()
    order = sorted(groups.values(), key=lambda g: (g["source"] != "alternative", -len(g["strategies"])))
    for n, g in enumerate(order):
        if "fit" in g or "error" in g:
            continue
        if n >= max_groups:
            g["error"] = f"not run: past --max-groups {max_groups}"
            continue
        if not clock.left():
            cell["timeout"] = True
            return
        g["right"] = all(s in ("pass", "equivalent") for s in g["statuses"])
        try:
            members = [ob.prepare(view, canonical(nums), grid=grid) for nums in g["numbers"]]
        except NotExpressible as e:
            g["error"] = f"not expressible: {e}"
            save()
            continue
        except Exception as e:  # noqa: BLE001
            g["error"] = f"{type(e).__name__}: {e}"
            save()
            continue
        mw = members[0]
        layout = [(sl.kind, sl.path[2] if sl.kind == "coef" else None) for sl in mw.st.slots]
        starts = [m.theta0 for m in members if [(sl.kind, sl.path[2] if sl.kind == "coef" else None) for sl in m.st.slots] == layout]
        starts.append(ob.lean_start(mw))
        r = ob.fit(mw, starts)
        g["fit"] = _brief(r)
        g.update(_shape(g["numbers"][0]))
        refit = ob.fitted_flows(mw, r["theta"])
        g["refit_flows"] = refit
        try:
            g["refit_status"] = score.equations(c, v["noise"], tm, refit, d)["status"]
        except Exception:  # noqa: BLE001
            g["refit_status"] = "unscored"
        g["delta"] = g["fit"]["J"] - T["J"]
        g["delta_parts"] = {"D": g["fit"]["D"] - T["D"], "P_num": g["fit"]["P_num"] - T["P_num"], "P_struct": g["fit"]["P_struct"] - T["P_struct"]}
        N = max(1, cell["reports"])
        g["delta_bic"] = (g["fit"]["D"] + 0.5 * g["fit"]["numbers"] * math.log(N)) - (T["D"] + 0.5 * T["numbers"] * math.log(N))
        g.pop("numbers_fitted", None)
        save()
    _label(cell, EPSILON)
    cell["done"] = True


def _brief(r: dict) -> dict:
    keep = ("J", "D", "P_num", "P_struct", "theta", "eta", "eta_read", "gnorm", "converged", "restarts_agree", "start_J", "message",
            "numbers", "complexity", "seconds", "diagnostics", "P_struct_items")
    return {k: r[k] for k in keep if k in r}


def _sanity(cell: dict, mt, th0, v: dict, grid, ob) -> dict:
    T, T0 = cell["Tstar"], cell["T0"]
    checks = {"refit_no_worse": T["J"] <= T0["J"] + 1e-6}
    worse = {}
    best = np.asarray(T["theta"])
    for f in (0.7, 0.9, 1.1, 1.3):
        r = ob.fit(mt, [best * f], fit_theta=False)
        worse[str(f)] = r["J"] - T["J"]
    checks["beats_scaled"] = all(x > 0 for x in worse.values())
    ok, why = _plausible(T["eta_read"], v, grid)
    checks["eta_plausible"] = ok
    dg = T.get("diagnostics") or {}
    checks["innovations"] = (dg.get("dispersion_z") is None or abs(dg["dispersion_z"]) <= 3) and (dg.get("ljung_box_z") is None or dg["ljung_box_z"] <= 3)
    return {"ok": all(checks.values()), "checks": checks, "scaled_minus_T": worse, "eta_why": why, "diagnostics": dg}


def _label(cell: dict, eps: float) -> None:
    T = cell["Tstar"]
    unident = cell.get("analysis") in ("unidentifiable",)
    limited = cell.get("analysis") in ("data-limited", "unidentifiable")
    fitbad = not (T.get("converged") and T.get("restarts_agree"))
    labels, bic = [], []
    for g in cell.get("groups", {}).values():
        if "fit" not in g:
            continue
        d = g["delta"]
        if g.get("right"):
            g["label"] = "right"
            continue
        if g.get("refit_status") in ("pass", "equivalent"):
            g["label"] = "X"
        elif d > eps:
            g["label"] = "OK"
        elif abs(d) <= eps:
            g["label"] = "TIE-known" if (g["source"] == "alternative" or unident) else "TIE-unexplained"
        elif fitbad:
            g["label"] = "F"
        elif limited:
            g["label"] = "L"
        else:
            g["label"] = "E-price" if g["delta_parts"]["D"] > 0 else "E"
            g["mechanism"] = _mechanism(g, {"fit": T, **{k: T.get(k) for k in ("self_reinforcing", "links")}})
        labels.append(g["label"])
        db = g["delta_bic"]
        bic.append("OK" if db > eps else ("TIE" if abs(db) <= eps else "E"))
    worst = "OK"
    rank = lambda lab: ORDER.index(lab.split("-")[0]) if lab.split("-")[0] in ORDER else len(ORDER)  # noqa: E731
    for lab in labels:
        if lab != "X" and rank(lab) < rank(worst):
            worst = lab
    if not cell.get("sanity", {}).get("ok", True) and rank("S") < rank(worst):
        worst = "S"
    cell["label"] = worst if labels or worst == "S" else "no wrong candidates"
    cell["label_bic"] = min(bic, key=lambda x: ["E", "TIE", "OK"].index(x)) if bic else "no wrong candidates"
    wrong = [g for g in cell.get("groups", {}).values() if "fit" in g and not g.get("right")]
    right = [g for g in cell.get("groups", {}).values() if "fit" in g and g.get("right")]
    cell["min_delta"] = min((g["delta"] for g in wrong), default=None)
    cell["truth_rank"] = 1 + sum(1 for g in wrong if g["fit"]["J"] < T["J"])
    cell["right_abs_delta"] = [abs(g["delta"]) for g in right]
    best = min(wrong + right, key=lambda g: g["fit"]["J"], default=None)
    cell["winner_equivalent"] = bool(best is None or best["fit"]["J"] >= T["J"] or best.get("right") or best.get("refit_status") in ("pass", "equivalent"))


def cells_for(spec: str | None, sets: str | None, variants: str | None) -> list[tuple[str, str]]:
    from .runner import select_cases
    parts = [spec] if spec else []
    named_variants: dict[str, str] = {}
    for s in (sets or "").split(","):
        s = s.strip()
        if not s:
            continue
        if s not in SETS:
            raise SystemExit(f"unknown set {s!r} (have: {', '.join(SETS)})")
        parts.append(SETS[s])
        if s == "p0":
            named_variants.update(P0_VARIANTS)
    ids = []
    for p in parts:
        for one in p.split(","):
            try:
                ids += select_cases(one)
            except SystemExit:
                continue
    ids = list(dict.fromkeys(ids))
    want = [x.strip() for x in variants.split(",")] if variants else None
    out = []
    for cid in ids:
        c = casemod.load(cid)
        for v in c["variants"]:
            pinned = next((nv for k, nv in named_variants.items() if cid.startswith(k)), None)
            if want and v["name"] not in want and v["noise"] not in want and v["length"] not in want:
                continue
            if not want and pinned and v["name"] != pinned:
                continue
            out.append((cid, v["name"]))
    return out


def _one(item):
    cid, variant, timeout, max_groups, where = item
    try:
        os.nice(19)                                  # the machine is shared; JAX's CPU runtime uses ~2-3 threads
    except OSError:
        pass
    return run_cell(cid, variant, timeout, max_groups, where)


def run(cells: list[tuple[str, str]], jobs: int = 4, timeout: float = 900.0, max_groups: int = 40, on_done=None) -> list[dict]:
    """Every cell, in a pool of at most 4 workers (single-threaded each); the pool is shut down
    before returning, also on an interrupt."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    jobs = max(1, min(4, jobs))
    out = []
    where = cache_dir()
    items = [(cid, v, timeout, max_groups, where) for cid, v in cells]
    if jobs == 1:
        for it in items:
            out.append(_one(it))
            if on_done:
                on_done(out[-1], len(out), len(items))
        return out
    pool = ProcessPoolExecutor(max_workers=jobs)
    old = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        futs = {pool.submit(_one, it): it for it in items}
        for f in as_completed(futs):
            try:
                cell = f.result()
            except Exception as e:  # noqa: BLE001
                cid, v = futs[f][:2]
                cell = {"case": cid, "variant": v, "error": f"worker failed: {type(e).__name__}: {e}"}
            out.append(cell)
            if on_done:
                on_done(cell, len(out), len(items))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        signal.signal(signal.SIGTERM, old)
    return out


def load_cells(cells: list[tuple[str, str]]) -> list[dict]:
    out = []
    for cid, v in cells:
        p = _cell_path(cid, v)
        if p.exists():
            try:
                out.append(json.loads(p.read_text()))
                continue
            except ValueError:
                pass
        out.append({"case": cid, "variant": v, "label": "not run"})
    return out


def main(a) -> int:
    from .objective_report import report
    cells = cells_for(a.cases, a.sets, a.variants)
    if not cells:
        print("no cells", flush=True)
        return 2
    print(f"objective test: {len(cells)} cells, cache {cache_dir()}", flush=True)
    got = None
    if not a.report_only:
        t0 = time.time()

        def done(cell, n, total):
            print(f"[{n}/{total}] {cell['case']} {cell['variant']}: {cell.get('label', '?')}"
                  + (f" ({cell['why']})" if cell.get("why") else "") + (f" ERROR {cell['error']}" if cell.get("error") else "")
                  + (" (timed out: resumable)" if cell.get("timeout") else "") + f"  {time.time() - t0:.0f}s", flush=True)
        got = run(cells, a.jobs or 2, a.timeout, a.max_groups, done)
    got = got if got is not None else load_cells(cells)
    text, summary = report(got)
    print(text)
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "cells": got}, default=_jsonable, indent=1))
        print(f"written {a.out}")
    return 0
