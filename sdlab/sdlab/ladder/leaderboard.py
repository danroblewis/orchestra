"""The leaderboard's rows (/ladder/leaderboard), computed on the server from the summary (api.summary)
so the page fetches a few kilobytes instead of every cell.

    rows(sm, variant, level, kind, set_, age, ages)   one row per strategy that has run a kept cell
    view(variant, level, kind, set_, age)             {version, rows, levels, kinds}, cached per summary and filter

A port of what leaderboard.html computed in the browser until 2026-10-19, number for number: the same
filters (variant: "all" or a substring of the variant's name; level: 0 for every level; kind: all,
draws or fixed; set: all, tests, realistic or physics; age: "", "o<hours>" older than, "n<hours>"
added in the last), the same sums in the same order, JavaScript's toFixed for the tooltips' numbers
and the same seeded bootstrap for the 95% intervals. A number the browser showed as NaN (nothing to
average) is null here; the page reads null as NaN. tests/test_ladder_leaderboard.py checks the rows
against the old page's code run in node over a full summary.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Context, Decimal

import numpy as np

from ..discovery.api import jsonable

NAN = float("nan")
PARTS = ("flows", "terms", "pieces", "other")


# ---- JavaScript's arithmetic and formatting, where the page relied on it ----

def _js(x):
    """A JSON value as JavaScript's arithmetic reads it: null is 0, true 1, a missing value NaN."""
    if x is None:
        return 0
    if x is True or x is False:
        return int(x)
    return x


def _mean(a: list) -> float:
    if not a:
        return NAN
    s = 0
    for x in a:
        s = s + _js(x)
    return s / len(a)


def _div(a, b) -> float:
    a, b = _js(a), _js(b)
    if b == 0:
        return NAN if a == 0 or a != a else math.copysign(math.inf, a)
    return a / b


def _clip(v):
    return None if v is None else max(-1, v)


def _finite(v) -> bool:
    return v is not None and not isinstance(v, bool) and math.isfinite(v)


_CTX = Context(prec=60)


def fixed(x, d: int) -> str:
    """Number.prototype.toFixed(d)."""
    if x != x:
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if abs(x) >= 1e21:
        return repr(float(x))
    if x == 0:
        x = 0.0
    q = Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP, context=_CTX)
    return format(q, "f")


def pct(v) -> str:
    return "–" if v is None or v != v else fixed(100 * v, 1) + "%"


_lcg: list = [np.empty(0, dtype=np.int64)]
_draws: dict = {}


def _indices(n: int) -> np.ndarray:
    """The page's bootstrap draws for n values: 1000 x n indices from its Park-Miller generator (seed 1,
    restarted for every interval, so every n reads a prefix of one sequence)."""
    if n not in _draws:
        seq = _lcg[0]
        if len(seq) < 1000 * n:
            seed, more = int(seq[-1]) if len(seq) else 1, []
            for _ in range(1000 * n - len(seq)):
                seed = (seed * 16807) % 2147483647
                more.append(seed)
            seq = _lcg[0] = np.concatenate([seq, np.asarray(more, dtype=np.int64)])
        _draws[n] = np.floor((seq[:1000 * n] / 2147483647) * n).astype(np.int64).reshape(1000, n)
    return _draws[n]


def ci_text(v: list) -> str:
    """95% bootstrap interval of a mean, as the page drew it (the sums in the same order)."""
    if len(v) < 2:
        return "–"
    x = np.asarray([_js(a) for a in v], dtype=float)[_indices(len(v))]
    ms = np.sort(np.cumsum(x, axis=1)[:, -1] / len(v))
    return f"[{fixed(100 * float(ms[25]), 1)}, {fixed(100 * float(ms[974]), 1)}]"


# ---- the case kinds ----

def is_real(c: dict) -> bool:
    return bool(c.get("example") or "realistic" in (c.get("tags") or []))


def kind_of(c: dict) -> str:
    return "real" if c.get("real") else "realistic" if is_real(c) else "physics" if c.get("physics") else "tests"


def _age_ok(age: str, ages: dict | None):
    """The page's case-age filter, as a function of a case id (None: no filter)."""
    if not age or not ages or age[0] not in "on":
        return None
    try:
        hrs = float(age[1:])
    except ValueError:
        return None
    now = _ms(ages["now"])

    def ok(cid: str) -> bool:
        at = ages["added"].get(cid.split("#")[0])
        h = (now - _ms(at)) / 3.6e6 if at else math.inf
        return h >= hrs if age[0] == "o" else h < hrs
    return ok


def _ms(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000


# ---- the columns ----

def _complexity(cs: list) -> dict:
    with_cx = [c for c in cs if c.get("cx_extra") is not None]
    ratios = [c["cx_ratio"] for c in with_cx if c.get("cx_ratio") is not None and c["cx_ratio"] > 0]
    by = [_mean([c["cx_by"][i] for c in with_cx]) for i in range(len(PARTS))]
    tip = ""
    if with_cx:
        tip = (f"mean true {fixed(_mean([c['cx_true'] for c in with_cx]), 1)}, found {fixed(_mean([c['cx_found'] for c in with_cx]), 1)}; extra by part: "
               + ", ".join(f"{p} {'+' if by[i] > 0 else ''}{fixed(by[i], 1)}" for i, p in enumerate(PARTS)) + f" (over {len(with_cx)} runs)")
    return {"occam": _mean([c.get("occam") or 0 for c in cs]), "extra": _mean([c["cx_extra"] for c in with_cx]),
            "ratio": math.exp(_mean([math.log(r) for r in ratios])) if ratios else NAN, "extraTip": tip}


def _long_run(lr: dict, name: str, vf: str, lv: int) -> dict:
    a = [0, 0, 0, 0, 0, 0, 0]
    for variant, by_level in (lr.get(name) or {}).items():
        if vf != "all" and vf not in variant:
            continue
        for level, x in sorted(by_level.items(), key=lambda kv: int(kv[0])):    # integer keys: JavaScript's order
            if not lv or int(level) == lv:
                for i, v in enumerate(x):
                    a[i] = a[i] + v
    n, far, eq, eq_n, tau, tau_n, bad = a
    return {"lrFar": far / n if n else NAN, "lrEq": eq / eq_n if eq_n else NAN, "lrTau": tau / tau_n if tau_n else NAN,
            "lrBad": bad / n if n else NAN,
            "lrTip": f"{bad} of {n} runs with long-run metrics diverge" if n else "long-run metrics not computed yet (sdlab-ladder longrun)"}


def _achievable(cs: list) -> dict:
    ach = [c for c in cs if c.get("analysis") == "achievable"]
    by = lambda lab: sum(1 for c in cs if c.get("analysis") == lab)    # noqa: E731
    return {"passAch": sum(1 for c in ach if c["status"] == "pass") / len(ach) if ach else NAN,
            "achTip": f"{len(ach)} achievable cells; {by('data-limited')} data-limited, {by('unidentifiable')} unidentifiable, "
                      f"{sum(1 for c in cs if not c.get('analysis'))} not analysed"}


def _strict(cs: list) -> dict:
    known = [c for c in cs if c.get("strict") is not None]
    n = sum(1 for c in known if c["strict"] == 1)
    passes = [c for c in cs if c["status"] == "pass"]
    lost = [c for c in passes if c.get("strict") == 0 and c.get("strict") is not None]
    why = lambda w: sum(1 for c in lost if w in (c.get("strict_why") or "").split(","))    # noqa: E731
    return {"strict": n / len(known) if known else NAN, "strictCover": len(known) / len(cs) if cs else NAN,
            "strictTip": f"{n} strict passes of {len(known)} cells with a strict verdict ({len(cs)} run; "
                         f"{sum(1 for c in passes if c.get('strict') is None)} passes not computed yet). "
                         f"{len(lost)} of {len(passes)} passes fail strict: extra complexity {why('extra')}, long run {why('longrun')}, "
                         f"fresh run {why('fresh')} (a pass can fail on several)"}


def _realistic(mine: list, meta: dict, vf: str) -> dict:
    rc = [c for c in mine if meta[c["case"]]["real"] and (vf == "all" or vf in c["variant"])]
    rr = [c for c in rc if c["status"]]
    sk = lambda k: [v for v in (_clip(c.get(k)) for c in rr) if _finite(v)]    # noqa: E731
    goals = sum(1 for c in rr if c.get("goal"))
    s20, out = sk("skill20"), sum(1 for c in rr if c["status"] == "timeout")
    secs = [c["seconds"] for c in rr if c.get("seconds") is not None]
    t = 0
    for x in secs:
        t = t + x
    return {"rSkill20": _mean(s20), "rFresh20": _mean(sk("fresh20")), "rGoals": goals / len(rc) if rc else NAN, "rGoalsN": goals, "rOf": len(rc),
            "rTime": t if secs else NAN,
            "rTip": (f"{len(rr)} of {len(rc)} realistic runs done, {len(s20)} graded ({out} timeouts, {sum(1 for c in rr if c['status'] == 'error')} errors: no skill); "
                     f"{goals} meet the goal (fresh run: {sum(1 for c in rr if c.get('goal_fresh'))}); 95% interval of the mean skill@20 {ci_text(s20)}")
            if rc else "not run on the realistic examples yet",
            "rTimeTip": f"over {len(secs)} finished runs; slowest {fixed(max(secs), 0)} s; {out} timed out" if secs else ""}


def _nums(cs: list, k: str) -> list:
    return [c[k] for c in cs if _finite(c.get(k))]


def _physics(mine: list, meta: dict, vf: str) -> dict:
    pc = [c for c in mine if meta[c["case"]]["phys"] and (vf == "all" or vf in c["variant"])]
    pr = [c for c in pc if c["status"]]
    graded = [c for c in pr if c.get("ph_of") is not None]
    pass_n = sum(1 for c in pr if c["status"] == "pass")
    struct_n = sum(1 for c in graded if c.get("ph_structure") == 1)
    div = sum(1 for c in graded if c.get("ph_diverges"))
    return {"pPass": pass_n / len(pc) if pc else NAN, "pPassN": pass_n, "pOf": len(pc), "pStruct": struct_n / len(pc) if pc else NAN, "pStructN": struct_n,
            "pCoup": _mean([_div(c.get("ph_right", NAN), c["ph_of"]) for c in graded]), "pShape": _mean(_nums(graded, "ph_shape")),
            "pGap": _mean(_nums(graded, "ph_gap20")), "pLr": _mean(_nums(graded, "ph_lr")),
            "pTip": f"{len(pr)} of {len(pc)} physics runs done ({len(pr) - len(graded)} errors or timeouts); {pass_n} pass, {struct_n} with the physics' coupling graph and signs; "
                    f"{div} diverge in the long run" if pc else "not run on the physics cases yet",
            "pRefTip": f"mean fresh skill@20 {pct(_mean([_clip(c['fresh20']) for c in graded if c.get('fresh20') is not None]))} vs the reference's {pct(_mean(_nums(graded, 'ref_fresh20')))}"
                       if graded else "",
            "pLrTip": f"the reference (best SD model): {pct(_mean(_nums(graded, 'ref_lr')))}; {div} runs diverge" if graded else ""}


def _particles(mine: list, meta: dict, vf: str) -> dict:
    pc = [c for c in mine if meta[c["case"]]["part"] and (vf == "all" or vf in c["variant"])]
    pr = [c for c in pc if c["status"]]
    graded = [c for c in pr if c.get("pt_tier")]
    sc = [c for c in graded if c.get("pt_eq")]
    eq_n = sum(1 for c in sc if c["pt_eq"] == "pass")
    fresh = lambda k: [_clip(c[k]) for c in graded if c.get(k) is not None]    # noqa: E731
    pred = [c for c in graded if not c.get("pt_eq")]
    return {"qEq": eq_n / len(sc) if sc else NAN, "qEqN": eq_n, "qScored": len(sc), "qGap20": _mean(_nums(graded, "pt_gap20")),
            "qGap100": _mean(_nums(graded, "pt_gap100")), "qLr": _mean(_nums(graded, "pt_lr")),
            "qTip": f"{len(pr)} of {len(pc)} particle runs done ({len(pr) - len(graded)} errors or timeouts); equations scored on {len(sc)}: {eq_n} pass, "
                    f"{sum(1 for c in sc if c['pt_eq'] == 'equivalent')} equivalent; prediction-only runs within 5 points of the mean-field model at @20 and @100: "
                    f"{sum(1 for c in pred if c.get('pt_near'))} of {len(pred)}" if pc else "not run on the particle cases yet",
            "qRefTip": f"mean fresh skill@20 {pct(_mean(fresh('fresh20')))} vs the mean-field model's {pct(_mean(_nums(graded, 'ref_fresh20')))}; "
                       f"@100 {pct(_mean(fresh('fresh100')))} vs {pct(_mean(_nums(graded, 'ref_fresh100')))}" if graded else "",
            "qLrTip": f"the mean-field model: {pct(_mean(_nums(graded, 'ref_lr')))}; {sum(1 for c in graded if c.get('pt_diverges'))} runs diverge" if graded else ""}


def _real_data(mine: list, meta: dict) -> dict:
    cs = [c for c in mine if meta[c["case"]]["rd"]]
    real = [c for c in cs if c["variant"] == "real" and c["status"]]
    twin = [c for c in cs if c["variant"] == "twin" and c["status"]]
    g = [c for c in real if c.get("heldout") is not None and c.get("heldout_published") is not None]
    ag = [c for c in real if c.get("agree_recall") is not None]
    fl = [c for c in real if c.get("flows_of")]
    n_real, n_twin = sum(1 for c in cs if c["variant"] == "real"), sum(1 for c in cs if c["variant"] == "twin")
    tw = sum(1 for c in twin if c["status"] in ("pass", "equivalent"))

    def total(xs, k):
        s = 0
        for c in xs:
            s = s + (c.get(k) or 0)
        return s
    beat = sum(1 for c in g if c.get("beats_published"))
    held = [_clip(c["heldout"]) for c in g]
    return {"dHeld": _mean(held), "dGraded": len(g), "dBeatN": beat, "dBeat": beat / len(g) if g else NAN,
            "dAgree": _mean([c["agree_recall"] for c in ag]),
            "dFlowsN": total(fl, "flows_matched"), "dFlowsOf": total(fl, "flows_of"),
            "dFlows": _div(total(fl, "flows_matched"), total(fl, "flows_of")) if fl else NAN,
            "dTwin": tw / len(twin) if twin else NAN,
            "dTip": (f"{len(real)} of {n_real} real runs done ({sum(1 for c in real if c['status'] in ('error', 'timeout'))} error or timeout), {len(g)} graded "
                     f"(a flat held-out part has no skill); {sum(1 for c in real if c.get('found_nothing'))} found nothing (most strategies need 21 samples; "
                     f"many lab series are shorter), which scores as persistence (0); the published model on the same runs: "
                     f"{pct(_mean([_clip(c['heldout_published']) for c in g]))}; 95% interval of the mean {ci_text(held)}")
            if real else "not run on the real data yet (or not downloaded: python -m sdlab.ladder.real fetch)",
            "dAgreeTip": f"mean recall {pct(_mean([c['agree_recall'] for c in ag]))}, precision {pct(_mean([c.get('agree_precision', NAN) for c in ag]))}; "
                         f"{sum(1 for c in real if c.get('agrees'))} of {len(real)} runs agree exactly with the published structure" if ag else "",
            "dFlowsTip": f"{total(fl, 'flows_found')} of {total(fl, 'flows_of')} measured gross flows found at all; median relative error "
                         f"{pct(_mean([c.get('flows_error', NAN) for c in fl]))}" if fl else "",
            "dTwinTip": f"{tw} of {len(twin)} twin runs pass or are equivalent ({sum(1 for c in twin if c['status'] == 'pass')} pass); {n_twin} twin cells" if twin else ""}


# ---- the rows ----

def index(sm: dict) -> dict:
    """What every filter needs of a summary, worked out once: each strategy's cells and each case's kind."""
    meta = {c["id"]: {"level": c["level"], "drawn": bool(c.get("draw")), "kind": kind_of(c), "real": is_real(c),
                      "phys": bool(c.get("physics")) and not c.get("particles"), "part": bool(c.get("particles")), "rd": bool(c.get("real"))}
            for c in sm["cases"]}
    by: dict[str, list] = {s["name"]: [] for s in sm["strategies"]}
    for c in sm["cells"]:
        if c["strategy"] in by:
            by[c["strategy"]].append(c)
    return {"meta": meta, "by": by, "levels": sorted({c["level"] for c in sm["cases"]}),
            "kinds": {c["id"].split("#")[0]: kind_of(c) for c in sm["cases"]}}


def rows(sm: dict, ix: dict, variant: str = "all", level: int = 0, kind: str = "all", set_: str = "all",
         age: str = "", ages: dict | None = None, memo: dict | None = None) -> list[dict]:
    """With memo (kept by the caller for one filter): a strategy whose cells are the very same objects as
    last time (summary_build.py keeps a cell that did not change), with the same long-run numbers and
    case list, keeps its row instead of adding it up again."""
    meta, vf, lv = ix["meta"], variant, level
    if memo is not None and memo.get("meta") != meta:
        memo.clear()
        memo["meta"] = meta
    age_ok = _age_ok(age, ages)

    def keep(c):
        m = meta[c["case"]]
        return (not m["rd"] and (vf == "all" or vf in c["variant"]) and (not lv or m["level"] == lv)
                and (kind == "all" or (kind == "draws") == m["drawn"]) and (set_ == "all" or set_ == m["kind"])
                and (age_ok is None or age_ok(c["case"])))
    out = []
    for s in sm["strategies"]:
        name, mine = s["name"], ix["by"][s["name"]]
        lr = (sm.get("longrun") or {}).get(name)
        had = memo.get(name) if memo is not None else None
        if had and had[1] == lr and len(had[0]) == len(mine) and all(a is b for a, b in zip(had[0], mine)):
            if had[2] is not None:
                out.append(had[2])
            continue
        row = _row(name, mine, [c for c in mine if keep(c)], sm, meta, vf, lv)
        if memo is not None:
            memo[name] = (mine, lr, row)
        if row is not None:
            out.append(row)
    return out


def _row(name: str, mine: list, kept: list, sm: dict, meta: dict, vf: str, lv: int) -> dict | None:
    """One strategy's row over the cells kept by the filter (None when it ran none of them)."""
    cs = [c for c in kept if c["status"]]
    if not cs:
        return None
    n = len(cs)
    k = lambda st: sum(1 for c in cs if c["status"] == st)    # noqa: E731
    num = lambda key: [v for v in (_clip(c.get(key)) for c in cs) if _finite(v)]    # noqa: E731
    secs = 0
    for c in cs:
        secs = secs + (c.get("seconds") or 0)
    p, e, fl = k("pass"), k("equivalent"), k("fail")
    return {"name": name, "runs": n, "of": len(kept), "cover": n / len(kept), "p": p, "e": e, "fl": fl, "o": n - p - e - fl,
            "pass": p / n, "passeq": (p + e) / n, "recall": _mean(num("recall")), "precision": _mean(num("precision")),
            "skill20": _mean(num("skill20")), "fresh20": _mean(num("fresh20")), "skill100": _mean(num("skill100")), "seconds": secs,
            **_complexity(cs), **_long_run(sm.get("longrun") or {}, name, vf, lv), **_achievable(cs), **_strict(cs),
            **_realistic(mine, meta, vf), **_physics(mine, meta, vf), **_particles(mine, meta, vf), **_real_data(mine, meta)}


_cache: dict = {"sm": None, "ix": None, "views": {}, "version": 0}
_memos: dict = {}                                       # per filter: each strategy's row and the cells it came from
_lock = threading.Lock()


def current() -> tuple[dict, dict, int]:
    """The summary now (api.summary: cached, refreshed in the background), its index and its version (a
    number that changes whenever the summary does)."""
    sm, version = summary_now()
    with _lock:
        if _cache["sm"] is sm and _cache["ix"] is not None:
            return sm, _cache["ix"], version
    ix = index(sm)                                      # outside the lock: /version never waits on it
    with _lock:
        if _cache["sm"] is sm:
            _cache["ix"] = ix
    return sm, ix, version


def summary_now() -> tuple[dict, int]:
    """The summary now and its version, without indexing it (what /api/ladder/version needs)."""
    from . import api
    sm = api.summary()
    with _lock:
        if _cache["sm"] is not sm:
            _cache.update(sm=sm, ix=None, views={}, version=_cache["version"] + 1)
        return sm, _cache["version"]


def ages() -> dict | None:
    """{now, added: {file id: when}} (as /api/ladder/newest/ages gives the page), or None if unknown."""
    try:
        from . import case_dates
        return {"now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "added": {k: case_dates.added_at(v) for k, v in case_dates.dates().items()}}
    except Exception:                                   # noqa: BLE001  (no dates: the filter keeps every case, as the page did)
        return None


def view(variant: str = "all", level: int = 0, kind: str = "all", set_: str = "all", age: str = "") -> dict:
    sm, ix, version = current()
    ag = ages() if age else None
    kept = None
    if age and ag:
        ok = _age_ok(age, ag)
        kept = frozenset(i for i in ix["meta"] if ok is None or ok(i))
    key = (variant, level, kind, set_, age, kept)
    with _lock:
        got = _cache["views"].get(key) if _cache["sm"] is sm else None
    if got is None:
        with _lock:
            if len(_memos) > 32 and key not in _memos:
                _memos.clear()
            memo = _memos.setdefault(key, {})
        got = jsonable(rows(sm, ix, variant, level, kind, set_, age, ag, memo))
        with _lock:
            if _cache["sm"] is sm:
                _cache["views"][key] = got
    return {"version": version, "rows": got, "levels": ix["levels"], "kinds": ix["kinds"]}
