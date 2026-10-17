"""Coverage and selection: every candidate graded, the judge's rank of the best, and why a run fails.

identify() tries several variants and its judge (data only) keeps one. With opts["candidates"] it
lists every candidate; here each is graded against the truth as the chosen model is (skill@20 and
@100, grade.same_behaviour), which separates a coverage gap (no candidate is good) from a selection
gap (a good one existed, the judge kept another).

best candidate: the one that meets the goal, else the highest clipped skill@20 + skill@100; of those
within TIE (half a point, in that sum) of the top, the one the judge rates best. judge rank: 1 + the
candidates the judge rates strictly better than it (1 = the judge picked the best, or one as good).

failure class, for a run that misses the goal (DISCOVERY-GOAL.md):
- "not chosen": some candidate meets the goal, the judge kept another (a selection failure);
- "not supported": no candidate meets it, and the true model itself (its true numbers, its true
  outside inflows, its hidden stocks started from their true levels) scores no clearly better on the
  judge's own measure than the model chosen (not MARGIN = 5% below the chosen model's error): on this
  data the judge cannot prefer the truth, so adding the true structure to the candidates would not
  be enough (more data, a better judge or a prior is);
- "not representable": no candidate meets it, and the judge rates the truth clearly better than the
  chosen model: the right model would be picked if some generator proposed it (a coverage failure);
- "error": discovery raised.
The truth is used only here, in grading. The truth's judge score is a proxy for "the true structure
refitted by our own fitter" (which needs a fixed-structure fit mode the main line does not have): the
true numbers, and true hidden levels, are more than any fit could have, so the proxy leans towards
"not representable"; a run called "not supported" is not supported even then.
"""

from __future__ import annotations

import json
import math

import numpy as np
from grade import same_behaviour, truth_by_time, truth_runs

from sdlab.discovery.simulate import Model, levels_array, starts_for

GOAL_SKILL20, GOAL_SKILL100 = 0.9, 0.8
CLASSES = ("not representable", "not chosen", "not supported", "error")
TIE = 0.005
MARGIN = 0.05


def _clip(v: float) -> float:
    return max(-1.0, v) if math.isfinite(v) else -1.0


def meets_goal(skill: dict) -> bool:
    return skill["20"] >= GOAL_SKILL20 and skill["100"] >= GOAL_SKILL100


def truth_judge_error(truth_model: dict, data: dict, horizons=(5, 20, 100), starts: int = 80, flows: list | None = None) -> float | None:
    """identify.judge's score for the true model: its runs from ~80 moments, against the measured
    levels h steps later, summed over the measured stocks in their level spread, relative to how far
    the data moved, averaged over the horizons the judge uses. Hidden stocks start from their true
    levels; the outside inflows are the truth's schedule."""
    t, measured = data["t"], list(data["levels"])
    all_levels = data.get("all_levels")
    hs = [h for h in horizons if h < len(t) / 4]
    if not all_levels or not hs:
        return None
    ids = list(all_levels)
    flows = flows if flows is not None else truth_by_time(truth_model, t)[0]
    A = levels_array(all_levels, ids)
    m = [ids.index(k) for k in measured]
    sd = A[m].std(axis=1)
    sd[sd == 0] = 1
    tt = np.asarray(t, dtype=float)
    model, errs = Model(flows, ids), []
    for h in hs:
        s0 = starts_for(A.shape[1], h, starts)
        if not len(s0):
            return None
        end = model.run(A[:, s0 - 1], tt[s0[None, :] + np.arange(h)[:, None]])[m]
        obs = A[m][:, s0 + h - 1]
        e = ((end - obs) / sd[:, None]) ** 2
        e[~np.isfinite(e)] = 1e6
        moved = (((obs - A[m][:, s0 - 1]) / sd[:, None]) ** 2).sum()
        errs.append(float(e.sum() / max(1e-9, moved)))
    return sum(errs) / len(errs)


def grade_candidates(candidates: list[dict], truth_model: dict, data: dict, truth: dict | None = None) -> list[dict]:
    """Each candidate's name, judge error and skill@20 / @100 on the run it was found on (truth: the
    truth's runs by horizon, grade.truth_runs, when the caller has them)."""
    out, seen = [], {}
    truth = truth or {}
    truth = {h: truth.get(h) or truth_runs(truth_model, data, horizon=h) for h in (20, 100)} if candidates else {}
    for c in candidates:
        key = json.dumps(c["flows"], sort_keys=True, default=str)       # variants often find the same model
        if key not in seen:
            seen[key] = {str(h): same_behaviour({"flows": c["flows"]}, truth_model, data, horizon=h, truth=truth[h])["skill"] for h in (20, 100)}
        out.append({"name": c["name"], "judge": c["error"], "skill": dict(seen[key])})
    return out


def best_of(graded: list[dict]) -> dict | None:
    """The best-graded candidate, with the judge's rank of it."""
    if not graded:
        return None
    score = lambda c: (meets_goal(c["skill"]), _clip(c["skill"]["20"]) + _clip(c["skill"]["100"]))  # noqa: E731
    top = max(score(c) for c in graded)
    judge = lambda c: math.inf if c["judge"] is None else c["judge"]  # noqa: E731
    best = min((c for c in graded if score(c)[0] == top[0] and score(c)[1] >= top[1] - TIE), key=judge)
    rank = 1 + sum(1 for c in graded if judge(c) < judge(best))
    return {"name": best["name"], "skill": best["skill"], "rank": rank, "of": len(graded), "meets": meets_goal(best["skill"])}


def classify(x: dict) -> str | None:
    """The failure class of a bench result (None: it meets the goal, or nothing to classify by)."""
    if x.get("error"):
        return "error"
    if meets_goal(x["skill"]):
        return None
    best = x.get("best")
    if best is None:
        return None
    if best["meets"]:
        return "not chosen"
    if x.get("truth_better") is None:
        return None
    return "not representable" if x["truth_better"] else "not supported"


def instrument(r: dict, truth_model: dict, data: dict, truth: dict | None = None) -> dict:
    """The bench columns for one discovery result r (from identify with opts["candidates"])."""
    graded = grade_candidates(r.get("candidates") or [], truth_model, data, truth)
    chosen = next((c["judge"] for c in graded if c["name"] == r.get("chosen")), None)
    tj = truth_judge_error(truth_model, data, flows=next(iter((truth or {}).values()), {}).get("flows"))
    better = None if tj is None or chosen is None else bool(tj < chosen * (1 - MARGIN))
    for c in graded:
        c["judge"] = _finite(c["judge"])
    return {"candidates": graded, "best": best_of(graded), "chosen_judge": _finite(chosen), "truth_judge": _finite(tj), "truth_better": better}


def counts(results: list[dict]) -> dict:
    """Runs per failure class, and how often the judge picked the best-graded candidate."""
    graded = [x for x in results if x.get("best")]
    by = {c: sum(1 for x in results if x.get("failure") == c) for c in CLASSES}
    return {"runs": len(results), "short": sum(1 for x in results if x.get("error") or not meets_goal(x["skill"])), **by,
            "graded": len(graded), "picked": sum(1 for x in graded if x["best"]["rank"] == 1),
            "best_meets": sum(1 for x in graded if x["best"]["meets"]),
            "best20": sum(_clip(x["best"]["skill"]["20"]) for x in graded) / len(graded) if graded else None,
            "best100": sum(_clip(x["best"]["skill"]["100"]) for x in graded) / len(graded) if graded else None}


def headline(results: list[dict]) -> list[str]:
    c = counts(results)
    if not c["graded"]:
        return ["Candidates: not graded (the strategy does not list them)"]
    classes = ", ".join(f"{c[k]} {k}" for k in CLASSES if c[k] or k != "error")
    other = c["short"] - sum(c[k] for k in CLASSES)
    return [f"Candidates: the best candidate's mean skill@20 {100 * c['best20']:.1f}%, skill@100 {100 * c['best100']:.1f}%, meeting the goal in "
            f"{c['best_meets']} of {c['graded']}; the judge picked the best candidate in {c['picked']} of {c['graded']} runs",
            f"Failure classes of the {c['short']} runs missing the goal: {classes}" + (f", {other} unclassified" if other else "")]


def _finite(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None
