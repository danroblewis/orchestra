"""The objective test's labels (objective_test.py): everything that reads the cached fits and says
what they mean, apart from the fits themselves. It is not in the cache key, so a fix here re-labels
the cached cells (`objective-test --relabel FOLDERS`) without refitting them.

- plausible(): is the truth's fitted noise character plausible for the variant (design, 7.5)?
- label(): each candidate group's label and the cell's (see objective_test's docstring).
- relabel(): one cached cell re-labelled with the current code: write-back of shared schedule slots,
  groups merged by the hidden-name-free signature, a group of the truth's own structure is right, a
  group whose refit fails the scorer is wrong, the sanity block's noise check, the labels, and a done
  cell's stale timeout flag dropped.
"""

from __future__ import annotations

import json

import numpy as np

ORDER = ["E", "P", "F", "S", "L", "TIE", "OK"]
RIGHT = ("pass", "equivalent")
# 2: write-back of tied slots, hidden-name-free groups, truth-structure and refit-fail rightness,
#    beats_scaled/refit_no_worse -> F, L before F, the meas check on the combined error, X out of A-bic
LABELS_VERSION = 2


def plausible(eta: dict, v: dict, grid) -> tuple[bool, str]:
    """Is the truth's fitted noise character plausible for the variant (section 7.5)? The process
    check follows the noise the engine ran with (`none` or `counts`: every observation kind sits on
    counts); the measurement check compares the fitted error variance alpha + rho2 E[x^2] with the
    one the data were made with, abs^2 + rel^2 E[x^2], within a factor 2 (alpha and rho2 trade
    against each other, so they are not checked one by one). Thresholds as declared in unified.md."""
    from .noise import engine_noise
    obs = v.get("observe") or {}
    q2 = {s: float(q) ** 2 for s, q in zip(grid.ids, grid.q)}
    sc2 = {s: float(x) ** 2 for s, x in zip(grid.ids, grid.scale)}
    small = lambda x, s: x <= max(0.1 * q2[s], 1e-4 * sc2[s])  # noqa: E731
    if engine_noise(v) == "none":
        ok = eta["phi"] < 0.05 and all(small(eta["tau"][s], s) and small(eta["alpha"][s], s) for s in grid.ids)
        return ok, f"none: phi {eta['phi']:.3g}, variances at their floor: {ok}"
    if not 0.7 <= eta["phi"] <= 1.4:
        return False, f"counting: phi {eta['phi']:.3g} outside [0.7, 1.4]"
    if obs.get("kind") == "meas":
        rel, ab = float(obs.get("rel", 0.05)), float(obs.get("abs", 1.0))
        bad = []
        for j, s in enumerate(grid.ids):
            col = grid.y[:, j]
            x2 = float(np.nanmean(col ** 2)) if np.isfinite(col).any() else 0.0
            want = ab ** 2 + rel ** 2 * x2
            got = eta["alpha"][s] + eta["rho2"][s] * x2
            floor = max(0.1 * q2[s], 1e-4 * sc2[s])
            ok = got <= floor if want <= floor else 0.5 * want <= got <= 2 * want
            if not ok:
                bad.append(s)
        return not bad, f"meas: error variance off by more than x2 on {bad}" if bad else "meas: ok"
    bad = [s for s in grid.ids if not small(eta["tau"][s], s)]
    return not bad, f"counts: tau not near 0 on {bad}" if bad else "counts: ok"


def mechanism(w: dict, t: dict) -> list[str]:
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
    if ew["phi"] > 2 * et["phi"] + 1e-9 or any(ew["tau"][s] > 4 * et["tau"].get(s, 0.0) + 1e-9 for s in ew["tau"]):
        out.append("noise absorbing structure (tau or phi)")
    return out


def is_right(g: dict) -> bool:
    """A group is right when it has the truth's own structure, or when every stored member passes or
    is equivalent AND its refit (the numbers J chose) does not re-score as a fail."""
    if g.get("truth_structure"):
        return True
    return all(s in RIGHT for s in g.get("statuses") or []) and g.get("refit_status") in (*RIGHT, None, "unscored")


def label(cell: dict, eps: float) -> None:
    T = cell["Tstar"]
    unident = cell.get("analysis") in ("unidentifiable",)
    limited = cell.get("analysis") in ("data-limited", "unidentifiable")
    checks = (cell.get("sanity") or {}).get("checks") or {}
    # T* is not at its optimum: did not converge, restarts disagree, a scaled copy of its numbers or
    # its own written numbers score better
    fitbad = not (T.get("converged") and T.get("restarts_agree")) or checks.get("beats_scaled") is False \
        or checks.get("refit_no_worse") is False
    labels, bic = [], []
    for g in cell.get("groups", {}).values():
        if "fit" not in g:
            continue
        d = g["delta"]
        g["right"] = is_right(g)
        g.pop("mechanism", None)
        if g["right"]:
            g["label"] = "right"
            continue
        if g.get("refit_status") in RIGHT:
            g["label"] = "X"
        elif d > eps:
            g["label"] = "OK"
        elif abs(d) <= eps:
            g["label"] = "TIE-known" if (g["source"] == "alternative" or unident) else "TIE-unexplained"
        elif limited:
            g["label"] = "L"
        elif fitbad:
            g["label"] = "F"
        else:
            g["label"] = "E-price" if g["delta_parts"]["D"] > 0 else "E"
            g["mechanism"] = mechanism(g, {"fit": T, **{k: T.get(k) for k in ("self_reinforcing", "links")}})
        labels.append(g["label"])
        if g["label"] != "X":                         # a cheaper equivalent is not a wrong winner under BIC either
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
    cell["winner_equivalent"] = bool(best is None or best["fit"]["J"] >= T["J"] or best.get("right") or best.get("refit_status") in RIGHT)


def outcome(cell: dict, eps: float = 0.5) -> str | None:
    """The cell's outcome as unified-objective-test.md counts it: "truth best" (no wrong group, X
    aside, beats T* by more than eps), else "equivalent winner" (the J-best is right or X), else
    "wrong winner"; None for a cell that is not judged (C, no wrong candidates, error, not done)."""
    if not cell.get("done") or cell.get("error") or cell.get("label") in ("C", "no wrong candidates", None):
        return None
    fitted = [g for g in (cell.get("groups") or {}).values() if "fit" in g]
    wrong = [g for g in fitted if not g.get("right") and g.get("label") != "X"]
    if all(g["delta"] >= -eps for g in wrong):
        return "truth best"
    best = min(fitted, key=lambda g: g["fit"]["J"])
    return "equivalent winner" if best.get("right") or best.get("label") == "X" else "wrong winner"


def merge_groups(groups: dict, key) -> dict:
    """Groups with the same key(g) (and the same source) as one: the lowest J's fit kept, every
    member's strategies and statuses pooled. A group without a fit counts only when none has one."""
    out: dict[str, dict] = {}
    for sig, g in groups.items():
        k = (g.get("source"), key(sig, g))
        name = k[1] if g.get("source") != "alternative" else sig
        if name not in out:
            out[name] = {**g, "merged": [sig]}
            continue
        h = out[name]
        better = "fit" in g and ("fit" not in h or g["fit"]["J"] < h["fit"]["J"])
        pooled = {"strategies": h["strategies"] + g["strategies"], "statuses": h["statuses"] + g["statuses"],
                  "merged": h["merged"] + [sig]}
        out[name] = {**(g if better else h), **pooled}
    return out


def relabel(cell: dict, eps: float | None = None) -> dict:
    """One cached cell re-labelled with the current code, without refitting (see the docstring)."""
    from ..discovery.strategies.unified.frontend import build, grid_of, write_back
    from ..discovery.strategies.unified.price import EPSILON
    from ..skill import truth_by_time
    from . import cases as casemod
    from . import data, score
    from .objective_test import canonical, signature, view_of

    cell = json.loads(json.dumps(cell))
    cell.setdefault("label_before", cell.get("label"))
    cell.setdefault("label_bic_before", cell.get("label_bic"))
    cell.setdefault("outcome_before", outcome(cell))
    if not cell.get("done") or cell.get("error") or cell.get("label") == "C":
        return cell
    cell.pop("timeout", None)
    c = casemod.load(cell["case"])
    v = casemod.variant(c, cell["variant"])
    tm = casemod.truth_model(c, cell["variant"])
    d = data.load(c, cell["variant"])
    view = view_of(tm, d)
    grid = grid_of(view)
    truth_flows, _ = truth_by_time(tm, [int(x) for x in grid.times])
    truth_flows = json.loads(json.dumps(truth_flows))
    measured = {s["id"] for s in view["stocks"]}
    known = measured | set(view.get("inputs") or {})
    opts = {"dt": float(tm.get("dt") or 1),
            "ceilings": {s["id"]: s["max"] for s in tm["stocks"] if s.get("max") is not None},
            "signed": {s["id"] for s in tm["stocks"] if s.get("signed")},
            "hidden_starts": {s["id"]: float(s.get("initial") or 0) for s in tm["stocks"] if s["id"] not in measured}}
    T = cell["Tstar"]
    T["flows"] = write_back(build(view, truth_flows, grid=grid, **opts), np.asarray(T["theta"], float))
    tsig = signature(truth_flows, known)
    rescored = 0
    for g in cell.get("groups", {}).values():
        if not g.get("numbers"):
            continue
        g["truth_structure"] = signature(g["numbers"][0], known) == tsig
        if "fit" not in g:
            continue
        new = json.loads(json.dumps(write_back(build(view, canonical(g["numbers"][0]), grid=grid), np.asarray(g["fit"]["theta"], float))))
        if new != g.get("refit_flows"):
            g["refit_flows"] = new
            g["refit_status_before"] = g.get("refit_status")
            try:
                g["refit_status"] = score.equations(c, v["noise"], tm, new, d)["status"]
            except Exception:  # noqa: BLE001
                g["refit_status"] = "unscored"
            rescored += 1
    cell["groups"] = merge_groups(cell.get("groups", {}), lambda sig, g: signature(g["numbers"][0], known) if g.get("numbers") else sig)
    san = cell.get("sanity")
    if san:
        ok, why = plausible(T["eta_read"], v, grid)
        san["checks"]["eta_plausible"] = ok
        san["eta_why"] = why
        san["ok"] = all(san["checks"].values())
    label(cell, EPSILON if eps is None else eps)
    cell["outcome"] = outcome(cell, EPSILON if eps is None else eps)
    cell["relabelled"] = {"version": LABELS_VERSION, "rescored_groups": rescored}
    return cell


def _relabel_one(item):
    path, out = item
    import pathlib
    cell = json.loads(pathlib.Path(path).read_text())
    try:
        new = relabel(cell)
        new["fitted_in"] = new.get("fitted_in") or pathlib.Path(path).parent.name
    except Exception as e:  # noqa: BLE001  (reported, the rest carry on)
        return {"case": cell.get("case"), "variant": cell.get("variant"), "relabel_error": f"{type(e).__name__}: {e}"}
    target = pathlib.Path(out) / pathlib.Path(path).name
    tmp = target.with_suffix(f".{__import__('os').getpid()}.tmp")
    from .objective_test import _jsonable
    tmp.write_text(json.dumps(new, default=_jsonable))
    tmp.replace(target)
    return new


def relabel_folders(sources: list[str], cells: set | None = None, jobs: int = 1) -> list[dict]:
    """Every done cell in the cache folders `sources` (names under objective_test/, later ones win for
    a cell that is in several), re-labelled and written to the current cache folder with
    `fitted_in` naming the folder its fits came from. `cells`: only these (case, variant)."""
    from concurrent.futures import ProcessPoolExecutor

    from .objective_test import cache_dir
    root = cache_dir().parent
    pick: dict = {}
    for name in sources:
        for p in sorted((root / name).glob("*.json")):
            try:
                c = json.loads(p.read_text())
            except ValueError:
                continue
            k = (c.get("case"), c.get("variant"))
            if c.get("done") and (cells is None or k in cells):
                pick[k] = p
    out = cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    items = [(str(p), str(out)) for _, p in sorted(pick.items())]
    if jobs <= 1:
        return [_relabel_one(it) for it in items]
    with ProcessPoolExecutor(max_workers=min(3, jobs)) as pool:
        return list(pool.map(_relabel_one, items))


def changes(cells: list[dict]) -> str:
    """Per set, the cell labels before -> after, and every cell whose label changed."""
    import collections

    from .objective_report import _set_of
    lines = []
    by = collections.defaultdict(list)
    for c in cells:
        by[_set_of(c)].append(c)
    for name, cs in sorted(by.items()):
        b = collections.Counter(c.get("label_before") for c in cs)
        a = collections.Counter(c.get("label") for c in cs)
        bb = collections.Counter(c.get("label_bic_before") for c in cs if c.get("label_bic_before"))
        ab = collections.Counter(c.get("label_bic") for c in cs if c.get("label_bic_before"))
        lines.append(f"== set {name}: {len(cs)} cells")
        for lab in sorted(set(a) | set(b), key=str):
            if a[lab] or b[lab]:
                lines.append(f"   {str(lab):22s} {b[lab]:4d} -> {a[lab]:4d}")
        lines.append(f"   A-bic: {dict(sorted(bb.items(), key=str))} -> {dict(sorted(ab.items(), key=str))}")
        ob_, oa = collections.Counter(c.get("outcome_before") for c in cs), collections.Counter(c.get("outcome") for c in cs)
        lines.append("   judged {} -> {}: ".format(sum(v for k, v in ob_.items() if k), sum(v for k, v in oa.items() if k))
                     + ", ".join(f"{k} {ob_[k]} -> {oa[k]}" for k in ("truth best", "equivalent winner", "wrong winner")))
    lines.append("")
    lines.append("changed cells: case variant before -> after")
    for c in sorted(cells, key=lambda c: (str(c.get("case")), str(c.get("variant")))):
        if c.get("relabel_error"):
            lines.append(f"  {c['case']} {c['variant']}: RELABEL ERROR {c['relabel_error'][:200]}")
        elif c.get("label_before") != c.get("label") or c.get("outcome_before") != c.get("outcome"):
            lines.append(f"  {c['case']} {c['variant']}: {c.get('label_before')} -> {c.get('label')}"
                         + (f" ({c.get('outcome_before')} -> {c.get('outcome')})" if c.get("outcome_before") != c.get("outcome") else ""))
    return "\n".join(lines)
