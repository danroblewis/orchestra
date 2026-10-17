"""A seeded, per-item simulation of a software team's kanban board, one step a day for six months.

This is the *real system* behind the measured `kanban` model. The model is told only what the
board shows at the end of every day: cards in Backlog, In development, In review, In testing and
Done, and open bugs. It is never told how cards move, how long each column holds them, or where
bugs come from. That is the answer key (sdlab/examples/kanban/README.md, truth.json).

Every day (the team works every day; a step is a working day), in this order:

  sprint      every 14 days (days 1, 15, 29, ...) planning adds a batch of new cards to the
              Backlog (Poisson, mean `sprint_mean`)
  reports     defects that have been in production long enough are noticed: a bug card opens
  triage      each open bug is picked up with probability `p_triage` and goes straight into
              development (bugs jump the queue)
  develop     each developer works one day on one card in development (bugs and rework first,
              then the oldest); a card is ready for review when its effort is used up. Ready
              cards wait in development until the review column has room
  review      each card in review is approved with probability `p_review`; approved cards go to
              testing. Then ready cards move from development into review up to the WIP limit
  test        each card in testing finishes with probability `p_test`; `p_reject` of those go back
              to development for rework, the rest to Done (during the release freeze they stay
              in testing, passed, and go to Done when the freeze lifts)
  defects     every card that reaches Done carries a defect with probability `p_defect`; the bug
              is noticed `defect_days` later (uniform), and nobody counts defects until then
  pull        each Backlog card becomes ready to start (refined, unblocked) with probability
              `p_pull`; ready cards are started, oldest first, as long as development holds no
              more than `dev_wip_per_dev` cards per developer (the development WIP limit)

A card moves at most one column a day. Nine developers join in month 3 and the release freeze is
a week in month 5 (eras).

Long runs (`run(seed, steps)` with steps > 182): the half-year repeats every 182 days with fresh
random draws. Each later half-year starts with the nine contractors leaving (15 developers, an
era), they join again on its day 92 (24 developers), and the release freeze is again its days
141-147. Sprints keep their 14-day rhythm (182 is 13 sprints). The first 182 days are exactly the
default run.

    python sim.py [seed] [steps]  prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field

PERIOD = 182                          # six months: the schedule repeats every PERIOD days
STEPS = PERIOD                        # one step is a (working) day: six months
LONG_STEPS = 10 * PERIOD              # five years, for long discovery runs
SEED = 20261016

MEASURED_STOCKS = ["backlog", "dev", "review", "testing", "done", "bugs"]
HIDDEN_STOCKS = ["defects"]           # defects shipped and not yet noticed
STOCKS = MEASURED_STOCKS + HIDDEN_STOCKS

# every true flow: id -> (from, to); None is outside. `defects` is filled by done cards that carry
# a defect (the card stays in Done: a co-flow, not a move) and drained by bug reports.
FLOWS = {
    "planned": (None, "backlog"),
    "pulled": ("backlog", "dev"),
    "to_review": ("dev", "review"),
    "approved": ("review", "testing"),
    "rejected": ("testing", "dev"),
    "released": ("testing", "done"),
    "triaged": ("bugs", "dev"),
    "shipped_defect": (None, "defects"),
    "reported": ("defects", "bugs"),
}
COUNTERS = list(FLOWS)

P = {
    "sprint_days": 14,
    "sprint_mean": 76.0,              # new cards per sprint (Poisson)
    "effort_mean": 1.8,               # developer-days for a new card (lognormal)
    "effort_cv": 0.6,
    "bug_effort_mean": 1.5,           # developer-days to fix a bug
    "rework_effort_mean": 1.0,        # developer-days to fix what testing found
    "p_triage": 0.2,                  # per open bug per day
    "p_review": 0.7,                  # per card in review per day (mean 1.4 days)
    "review_wip": 18,                  # review column limit
    "p_test": 0.4,                    # per card in testing per day (mean 2.5 days)
    "p_reject": 0.2,                  # of tested cards, back to development
    "p_defect": 0.25,                 # of cards reaching Done, a defect that comes back as a bug
    "defect_days": (7, 21),           # uniform: days until the defect is noticed
    "dev_wip_per_dev": 2,             # development holds at most this many cards per developer
    "p_pull": 0.15,                   # per Backlog card per day: ready to start
}

# eras: (first day, developers, release freeze?, label)
ERAS = [(1, 15, False, "Start"),
        (92, 24, False, "Nine developers join (24 developers)"),
        (141, 24, True, "Release freeze: nothing goes to Done"),
        (148, 24, False, "Freeze lifted")]
LATER_ERAS = [(1, 15, False, "Nine developers leave (15 developers)"),   # days of every later half-year
              (92, 24, False, "Nine developers join (24 developers)"),
              (141, 24, True, "Release freeze: nothing goes to Done"),
              (148, 24, False, "Freeze lifted")]


def schedule(steps: int = STEPS) -> list[tuple[int, int, bool, str]]:
    """(first day, developers, release freeze?, label) of every era in a run of `steps` days."""
    out = list(ERAS)
    for k in range(1, (steps + PERIOD - 1) // PERIOD):
        out += [(k * PERIOD + d, n, f, label) for d, n, f, label in LATER_ERAS]
    return [e for e in out if e[0] <= steps]

DEV_STAGES = ("new", "bug", "rework")


def config(day: int) -> tuple[int, bool]:
    k, d0 = (day - 1) // PERIOD, (day - 1) % PERIOD + 1               # half-year from 0, its day from 1
    devs, freeze = ERAS[0][1], ERAS[0][2]
    for d, n, f, _ in ERAS if k == 0 else LATER_ERAS:
        if d0 >= d:
            devs, freeze = n, f
    return devs, freeze


def poisson(rng: random.Random, lam: float) -> int:
    n = 0
    while lam > 30:
        n += poisson(rng, 30.0)
        lam -= 30.0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return n + k
        k += 1


def lognormal(rng: random.Random, mean: float, cv: float) -> float:
    s2 = math.log(1 + cv * cv)
    return rng.lognormvariate(math.log(mean) - s2 / 2, math.sqrt(s2))


@dataclass
class Card:
    cid: int
    kind: str                         # "feature" or "bug"
    where: str = "outside"
    effort: float = 0.0               # developer-days left before review
    passed: bool = False              # tested and waiting for the freeze to lift
    moved: int = 0                    # the day it last moved (one column a day)
    urgent: bool = False              # bug or rework: worked on first


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)       # stock -> end-of-day level, days 1..STEPS
    counters: dict[str, list[int]] = field(default_factory=dict)     # flow -> cards moved each day
    eras: list[dict] = field(default_factory=list)                   # [{t, label}] t = first day of the era
    defect_delays: list[int] = field(default_factory=list)           # days from Done to the bug report
    cards: int = 0


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    """`steps` days (any length >= 1; the half-year repeats). The default is the six-month run."""
    assert steps >= 1
    rng = random.Random(seed)
    cards: list[Card] = []
    cols: dict[str, list[Card]] = {s: [] for s in MEASURED_STOCKS}
    defects: dict[int, int] = {}                                     # day noticed -> defects
    res = Result(seed=seed, levels={s: [] for s in STOCKS}, counters={f: [0] * steps for f in FLOWS})
    C = res.counters

    def new_card(kind: str, effort: float, day: int) -> Card:
        c = Card(cid=len(cards), kind=kind, effort=effort, urgent=kind == "bug", moved=day)
        cards.append(c)
        return c

    def move(c: Card, to: str, flow: str, day: int, i: int) -> None:
        assert FLOWS[flow] == (None if c.where == "outside" else c.where, to), (flow, c.where, to)
        if c.where != "outside":
            cols[c.where].remove(c)
        cols[to].append(c)
        c.where, c.moved = to, day
        C[flow][i] += 1

    for i in range(steps):
        day = i + 1
        devs, freeze = config(day)
        # sprint planning
        if (day - 1) % P["sprint_days"] == 0:
            for _ in range(poisson(rng, P["sprint_mean"])):
                move(new_card("feature", lognormal(rng, P["effort_mean"], P["effort_cv"]), day), "backlog", "planned", day, i)
        # defects noticed: bug cards open
        n = defects.pop(day, 0)
        for _ in range(n):
            c = new_card("bug", lognormal(rng, P["bug_effort_mean"], P["effort_cv"]), day)
            c.where = "bugs"                                         # out of the defects nobody counts
            cols["bugs"].append(c)
            C["reported"][i] += 1
        # triage: bugs go straight into development
        for c in list(cols["bugs"]):
            if c.moved < day and rng.random() < P["p_triage"]:
                move(c, "dev", "triaged", day, i)
        # develop: one day of effort per developer, urgent cards first, then the oldest
        working = [c for c in cols["dev"] if c.effort > 0]
        working.sort(key=lambda c: (not c.urgent, c.cid))
        for c in working[:devs]:
            c.effort -= 1
        # review: approvals go to testing, then ready cards fill the column up to its limit
        for c in list(cols["review"]):
            if c.moved < day and rng.random() < P["p_review"]:
                move(c, "testing", "approved", day, i)
        ready = sorted((c for c in cols["dev"] if c.effort <= 0 and c.moved < day), key=lambda c: c.cid)
        for c in ready[:max(0, P["review_wip"] - len(cols["review"]))]:
            move(c, "review", "to_review", day, i)
        # test: reject back to development, or release to Done (held during the freeze)
        for c in list(cols["testing"]):
            if c.moved >= day:
                continue
            if not c.passed:
                if rng.random() >= P["p_test"]:
                    continue
                if rng.random() < P["p_reject"]:
                    c.effort, c.urgent = lognormal(rng, P["rework_effort_mean"], P["effort_cv"]), True
                    move(c, "dev", "rejected", day, i)
                    continue
                c.passed = True
            if freeze:
                continue
            move(c, "done", "released", day, i)
            if rng.random() < P["p_defect"]:
                d = rng.randint(*P["defect_days"])
                defects[day + d] = defects.get(day + d, 0) + 1
                res.defect_delays.append(d)
                C["shipped_defect"][i] += 1
        # pull: cards become ready to start (refined, unblocked) at random; ready cards are started,
        # oldest first, as long as development is within its WIP limit
        room = devs * P["dev_wip_per_dev"] - len(cols["dev"])
        ready = [c for c in sorted(cols["backlog"], key=lambda c: c.cid) if c.moved < day and rng.random() < P["p_pull"]]
        for c in ready[:max(0, room)]:
            move(c, "dev", "pulled", day, i)
        for s in MEASURED_STOCKS:
            res.levels[s].append(len(cols[s]))
        res.levels["defects"].append(sum(defects.values()))
    res.cards = len(cards)
    res.eras = [{"t": d, "label": label} for d, _, _, label in schedule(steps)]
    return res


def realised_k(res: Result, flow: str, stock: str) -> float:
    """Cards moved a day per card in `stock` at the end of the day before."""
    lv = res.levels[stock]
    return round(sum(res.counters[flow][1:]) / max(1, sum(lv[:-1])), 4)


def era_k(res: Result, flow: str, stock: str, a: int, b: int) -> float:
    """realised_k over days a..b-1."""
    lv = res.levels[stock]
    moved = sum(res.counters[flow][max(1, a - 1):b - 1])
    return round(moved / max(1, sum(lv[max(0, a - 2):b - 2])), 4)


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict, with the SD structure a perfect
    discovery would report."""
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None   # noqa: E731
    lv, C = res.levels, res.counters
    steps = len(lv["backlog"])
    eras = schedule(steps)
    per_day = lambda f: round(sum(C[f]) / steps, 3)   # noqa: E731
    lo, hi = P["defect_days"]
    p_done = P["p_test"] * (1 - P["p_reject"])
    moves = [
        {"from": "backlog", "to": "dev", "form": "proportional", "k": P["p_pull"], "k_realised": realised_k(res, "pulled", "backlog"),
         "wip_limit": [{"from_day": d, "cards": n * P["dev_wip_per_dev"]} for j, (d, n, _, _) in enumerate(eras)
                       if j == 0 or n != eras[j - 1][1]],
         "days_at_wip_limit": sum(1 for d, x in enumerate(lv["dev"], 1) if x >= config(d)[0] * P["dev_wip_per_dev"]),
         "what": f"{P['p_pull']:.0%} of Backlog cards a day become ready and are started, unless development is at its WIP limit "
                 f"({P['dev_wip_per_dev']} cards per developer); before the hiring it often is"},
        {"from": "dev", "to": "review", "form": "capacity-limited", "value": per_day("to_review"), "k_realised": realised_k(res, "to_review", "dev"),
         "per_era": [{"from_day": d, "developers": n, "k_realised": era_k(res, "to_review", "dev", a, b)}
                     for (d, n, _, _), a, b in zip(eras, [e["t"] for e in res.eras], [e["t"] for e in res.eras[1:]] + [steps + 1])],
         "days_review_full": sum(1 for x in lv["review"] if x >= P["review_wip"]),
         "what": f"each developer works one card a day (effort ~{P['effort_mean']} developer-days a card, bugs ~{P['bug_effort_mean']}, "
                 f"rework ~{P['rework_effort_mean']}); finished cards move to review while it holds fewer than {P['review_wip']} (its WIP limit). "
                 "Proportional while development holds fewer cards than developers; at most developers / effort a day when it holds more"},
        {"from": "review", "to": "testing", "form": "proportional", "k": P["p_review"], "k_realised": realised_k(res, "approved", "review"),
         "what": "approved: each card in review has a 70% chance a day (mean 1.4 days)"},
        {"from": "testing", "to": "done", "form": "proportional", "k": round(p_done, 4), "k_realised": realised_k(res, "released", "testing"),
         "what": "tested and released: 40% of cards in testing finish a day, 80% of those pass (none during the freeze, then all held cards at once)"},
        {"from": "testing", "to": "dev", "form": "proportional", "k": round(P["p_test"] * P["p_reject"], 4), "k_realised": realised_k(res, "rejected", "testing"),
         "what": "rework: 20% of finished tests send the card back to development"},
        {"from": "bugs", "to": "dev", "form": "proportional", "k": P["p_triage"], "k_realised": realised_k(res, "triaged", "bugs"),
         "what": "triaged bugs jump the queue into development"},
    ]
    outside = [
        {"to": "backlog", "form": "constant", "value": per_day("planned"),
         "pulses": {"every_days": P["sprint_days"], "first_day": 1, "mean_cards": P["sprint_mean"],
                    "cards": [C["planned"][d] for d in range(0, steps, P["sprint_days"])]},
         "what": "sprint planning: a batch of new cards every 14 days"},
    ]
    echo_share = round(sum(C["shipped_defect"]) / max(1, sum(C["released"])), 4)
    echoes = [{"source": "done", "into": "bugs", "shape": "uniform (between erlang and pipe)", "delay": (lo + hi) / 2,
               "delay_range": [lo, hi], "realised_delay": mean(res.defect_delays), "share": P["p_defect"], "share_realised": echo_share,
               "holds": mean(lv["defects"]), "stock": "defects",
               "what": "25% of cards reaching Done carry a defect; it is noticed 7-21 days later and opens a bug card (the card stays in Done)"}]
    return {
        "seed": res.seed,
        "steps": steps,
        "step": "1 working day",
        "cards": res.cards,
        "parameters": {**P, "defect_days": list(P["defect_days"])},
        "eras": res.eras,
        "configuration": [{"from_day": d, "developers": n, "release_freeze": f, "label": lab} for d, n, f, lab in eras],
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "hidden_stocks": {"defects": {"between": {"timed_by_gains_of": "done", "into": "bugs"}, "mean_level": mean(lv["defects"]),
                                      "max_level": max(lv["defects"]), "realised_delay": mean(res.defect_delays)}},
        "flows": {f: {"from": a, "to": b, "total": sum(C[f]), "per_step_mean": round(sum(C[f]) / steps, 4)} for f, (a, b) in FLOWS.items()},
        "sd_structure": {
            "note": "In SD Lab terms, one working day per step. Cards move left to right; testing sends some back to development; "
                    "bugs are a delayed echo of Done: things that ended come back later as new arrivals into Open bugs, through a "
                    "stock nobody counts (defects not yet noticed), and Done keeps its cards. Pulling from the Backlog and moving "
                    "into review are capacity-limited (idle developers, the review WIP limit), so the closest linear forms are a "
                    "constant per era or a share of the source; k_realised = cards moved / cards in the source the day before.",
            "moves": moves,
            "outside": outside,
            "links": [],
            "hidden": [],
            "echoes": echoes,
        },
        "mean_levels": {s: mean(lv[s]) for s in STOCKS},
        "max_levels": {s: max(lv[s]) for s in STOCKS},
    }


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees of a run: the board's columns per day, the eras, and the daily counters.
    The levels and eras are exactly what history.py prints."""
    res = cached(seed) if steps == STEPS else run(seed, steps)
    return {"t": list(range(1, steps + 1)),
            "levels": {s: res.levels[s] for s in MEASURED_STOCKS},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras],
            "counters": res.counters}


_cache: dict[int, Result] = {}


def cached(seed: int = SEED) -> Result:
    if seed not in _cache:
        _cache[seed] = run(seed)
    return _cache[seed]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED, int(sys.argv[2]) if len(sys.argv) > 2 else STEPS)
    g = ground_truth(r)
    print(json.dumps({"cards": r.cards, "mean_levels": g["mean_levels"], "max_levels": g["max_levels"],
                      "totals": {f: v["total"] for f, v in g["flows"].items()}}, indent=1))
