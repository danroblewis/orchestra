"""A seeded, stochastic simulation of a small SaaS business, day by day for one year.

This is the *real system* behind the measured `saas` model. The model is told only what the
growth dashboard shows at the end of every day: the ad budget not yet spent, the website's active
visitors, the trials in progress, the paying customers and the running total of customers who
cancelled. It is never told how they are connected; that is the answer key
(sdlab/examples/saas/README.md, truth.json).

How it works (every count is a binomial or Poisson draw from the start-of-day state, applied at
the end of the day):

  ad budget      the team releases a fixed amount into the ad account every day (it changes in
                 eras); the ad platform paces its spending at about a seventh of what is left
                 each day (x0.85 to x1.15)
  visitors       new visitors come from the ads (0.8 per dollar spent that day) and from search
                 and word of mouth (250 a day), plus a viral spike on day 150. A visitor stays
                 "active" until they start a trial (1.2% a day) or go quiet (25% a day)
  trials         every trial lasts exactly 14 days: on day 14 it converts to a paying customer
                 (22%, 15% after the price rise) or expires
  paying         each customer cancels with a daily probability of 0.5%; 3.5% in the five days
                 between announcing a 30% price rise and applying it; 0.75% after. A cancelled
                 customer is added to the cumulative churned count
  win-backs      90 days after a customer cancels, a win-back offer goes out, and 30% take it
                 and come back as paying customers that day (a fixed 90-day delay).
                 They stay in the churned count

The simulation runs 200 days of history before day 1, so the business is already going when the
year starts; the churned total counts from launch.

Long runs (`run(steps=...)`, `measured(steps=...)`, years of days): the first 365 days are always
the year above, draw for draw. Every later year draws its own plan from its own random stream (so
the first year never changes): it opens with new plans that bring the old prices back, a spring
campaign, a budget cut, a price rise announced around day 200 and applied five days later, a new
budget and a holiday campaign (the amounts and days drawn per year), and one or two viral spikes on
random days. Pricing only ever takes the three states above (old, announced, new), so churn and
conversion keep the same three/two values; the structure is the same at any length.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field

DAYS = 365
STEPS = DAYS                          # one step is one day
LONG_STEPS = 5 * DAYS                 # five years, for the discovery test bed
SEED = 20261016
WARMUP = 200                          # days simulated before day 1

MEASURED_STOCKS = ["ad_budget", "visitors", "trials", "paying", "churned"]

# every true flow: id -> (from, to); None is outside. All are counted (see COUNTERS).
FLOWS = {
    "budget_released": (None, "ad_budget"),
    "ad_spend": ("ad_budget", None),
    "ad_visits": (None, "visitors"),          # driven by today's ad spend (a link from the budget)
    "organic_visits": (None, "visitors"),
    "trial_starts": ("visitors", "trials"),
    "gone_quiet": ("visitors", None),
    "conversions": ("trials", "paying"),
    "trials_expired": ("trials", None),
    "cancellations": ("paying", "churned"),
    "win_backs": (None, "paying"),            # an echo of cancellations months earlier
}
COUNTERS = list(FLOWS)

P = {
    "spend_share": 1 / 7,             # of the remaining budget spent each day (x0.85-1.15)
    "visits_per_dollar": 0.8,
    "organic_per_day": 250,
    "p_trial": 0.012,                 # an active visitor starts a trial, per day
    "p_quiet": 0.25,                  # an active visitor goes quiet, per day
    "trial_days": 14,                 # exactly
    "p_convert": 0.22,                # at the end of a trial (before the price rise)
    "p_convert_new_price": 0.15,
    "churn_per_day": 0.005,
    "churn_per_day_announced": 0.035,  # the five days between announcing the new prices and applying them
    "churn_per_day_new_price": 0.0075,
    "p_win_back": 0.30,               # of cancellations
    "win_back_days": 90,              # days after cancelling: the offer goes out, and those who take it come back that day
}

PRICE_DAY = 200                       # new prices announced (new sign-ups pay them at once)

# (first day, label, budget released per day, pricing: "old" | "announced" | "new"): the eras
ERAS = [(1, "Ad budget $1,000 a day", 1000, "old"),
        (61, "Spring campaign: $2,500 a day", 2500, "old"),
        (121, "Budget cut: $600 a day", 600, "old"),
        (PRICE_DAY, "Price rise announced: +30% in five days", 600, "announced"),
        (PRICE_DAY + 5, "New prices apply to every customer", 600, "new"),
        (241, "Ad budget $1,500 a day", 1500, "new"),
        (301, "Holiday campaign: $3,000 a day", 3000, "new")]
CHURN = {"old": P["churn_per_day"], "announced": P["churn_per_day_announced"], "new": P["churn_per_day_new_price"]}
VIRAL = {150: 3000, 151: 1800, 152: 900, 153: 400}   # extra visitors: a post went viral

INITIAL = {"ad_budget": 7000, "visitors": 4000, "paying": 1500}


def year_plan(seed: int, year: int) -> tuple[list[tuple], dict[int, int]]:
    """The eras and viral spikes of year `year` (0 is the first: ERAS and VIRAL); every later year
    is drawn from its own stream, in the same shape as the first."""
    if year == 0:
        return ERAS, VIRAL
    rng = random.Random(f"saas:{seed}:{year}")
    d0 = year * DAYS
    budget = lambda lo, hi: rng.randrange(lo, hi + 1, 100)       # noqa: E731
    base, spring, after, holiday = budget(800, 1500), budget(2000, 3500), budget(1000, 2000), budget(2500, 4000)
    cut = budget(400, min(900, base - 200))
    d_spring, d_cut, d_price = rng.randint(51, 71), rng.randint(111, 131), rng.randint(185, 215)
    d_after, d_holiday = rng.randint(231, 251), rng.randint(291, 311)
    eras = [(d0 + 1, f"New plans: the old prices are back; ad budget ${base:,} a day", base, "old"),
            (d0 + d_spring, f"Spring campaign: ${spring:,} a day", spring, "old"),
            (d0 + d_cut, f"Budget cut: ${cut:,} a day", cut, "old"),
            (d0 + d_price, "Price rise announced: +30% in five days", cut, "announced"),
            (d0 + d_price + 5, "New prices apply to every customer", cut, "new"),
            (d0 + d_after, f"Ad budget ${after:,} a day", after, "new"),
            (d0 + d_holiday, f"Holiday campaign: ${holiday:,} a day", holiday, "new")]
    viral = {}
    for _ in range(rng.choice([1, 1, 2])):
        day, size = d0 + rng.randint(10, 355), rng.uniform(0.5, 1.5)
        for j, v in enumerate(VIRAL.values()):
            viral[day + j] = viral.get(day + j, 0) + round(v * size)
    return eras, viral


def plan(seed: int, steps: int) -> tuple[list[tuple], dict[int, int]]:
    """Every era that starts within `steps` days, and the viral spikes."""
    eras, viral = [], {}
    for y in range((steps - 1) // DAYS + 1):
        e, v = year_plan(seed, y)
        eras += [x for x in e if x[0] <= steps]
        viral |= v
    return eras, viral


def era_at(day: int) -> tuple:
    cur = ERAS[0]
    for e in ERAS:
        if day >= e[0]:
            cur = e
    return cur


def binom(rng: random.Random, n: int, p: float) -> int:
    return rng.binomialvariate(n, p) if n > 0 and p > 0 else 0


def poisson(rng: random.Random, lam: float) -> int:
    """Poisson by a fine binomial (stdlib has no Poisson draw)."""
    return binom(rng, int(lam * 20), 0.05) if lam > 0 else 0


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)    # stock -> end-of-day level, days 1..STEPS
    counters: dict[str, list[int]] = field(default_factory=dict)  # flow -> amount that day
    start: dict[str, int] = field(default_factory=dict)           # levels at the end of day 0
    win_back_delays: list[int] = field(default_factory=list)      # days from cancelling to coming back
    eras: list[dict] = field(default_factory=list)


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    assert steps >= 1
    eras, viral = plan(seed, steps)
    era = iter(eras[1:])
    cur, nxt = eras[0], next(era, None)
    rng = random.Random(seed)
    x = {s: 0 for s in MEASURED_STOCKS} | INITIAL
    starts: dict[int, int] = {}                       # trials started on day d
    returns: dict[int, int] = {}                      # win-backs due on day d
    res = Result(seed=seed, levels={s: [] for s in MEASURED_STOCKS}, counters={f: [] for f in FLOWS})
    for day in range(1 - WARMUP, steps + 1):
        if nxt and day >= nxt[0]:
            cur, nxt = nxt, next(era, None)
        _, _, released, pricing = cur
        if day < 1:
            released, pricing = 900, "old"
        spend = min(x["ad_budget"], round(x["ad_budget"] * P["spend_share"] * rng.uniform(0.85, 1.15)))
        ad_visits = poisson(rng, P["visits_per_dollar"] * spend)
        organic = poisson(rng, P["organic_per_day"] + viral.get(day, 0))
        trial_starts = binom(rng, x["visitors"], P["p_trial"])
        quiet = binom(rng, x["visitors"] - trial_starts, P["p_quiet"])
        ending = starts.pop(day - P["trial_days"], 0)
        conversions = binom(rng, ending, P["p_convert"] if pricing == "old" else P["p_convert_new_price"])
        cancels = binom(rng, x["paying"], CHURN[pricing])
        win_backs = returns.pop(day, 0)
        for _ in range(binom(rng, cancels, P["p_win_back"])):
            d = P["win_back_days"]
            returns[day + d] = returns.get(day + d, 0) + 1
            if day >= 1:
                res.win_back_delays.append(d)
        starts[day] = trial_starts
        x["ad_budget"] += released - spend
        x["visitors"] += ad_visits + organic - trial_starts - quiet
        x["trials"] += trial_starts - ending
        x["paying"] += conversions + win_backs - cancels
        x["churned"] += cancels
        assert min(x.values()) >= 0, (day, x)
        if day == 0:
            res.start = dict(x)
        if day < 1:
            continue
        for f, v in (("budget_released", released), ("ad_spend", spend), ("ad_visits", ad_visits), ("organic_visits", organic),
                     ("trial_starts", trial_starts), ("gone_quiet", quiet), ("conversions", conversions),
                     ("trials_expired", ending - conversions), ("cancellations", cancels), ("win_backs", win_backs)):
            res.counters[f].append(v)
        for s in MEASURED_STOCKS:
            res.levels[s].append(x[s])
    res.eras = [{"t": d, "label": label} for d, label, _, _ in eras]
    return res


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees over `steps` days (after the warm-up): the dashboard's five levels (what
    history.py prints for the default length), the eras, and the simulator's daily counter of
    every true flow."""
    res = run(seed, steps)
    return {"t": list(range(1, steps + 1)), "levels": {s: res.levels[s] for s in MEASURED_STOCKS},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras], "counters": res.counters}


def fit_k(flow: list[int], level: list[int], days=None) -> float:
    """Least-squares k in flow(t) = k x level(t - 1): what a proportional equation would read."""
    days = days or range(2, len(flow) + 1)
    pairs = [(flow[t - 1], level[t - 2]) for t in days if t >= 2]
    den = sum(b * b for _, b in pairs)
    return round(sum(a * b for a, b in pairs) / den, 5) if den else 0.0


def era_ranges() -> list[tuple[int, range]]:
    return [(d, range(d, ERAS[i + 1][0] if i + 1 < len(ERAS) else DAYS + 1)) for i, (d, *_) in enumerate(ERAS)]


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict."""
    C, L = res.counters, res.levels
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None    # noqa: E731
    total = {f: sum(v) for f, v in C.items()}
    old, new = range(2, PRICE_DAY), range(PRICE_DAY + 5, DAYS + 1)
    trial_days = P["trial_days"]
    # the link: visits from ads follow the budget left, through the spending pace
    k_link = round(P["visits_per_dollar"] * P["spend_share"], 4)
    lx = [(C["ad_visits"][t - 1], L["ad_budget"][t - 2]) for t in range(2, DAYS + 1)]
    k_link_fit = round(sum(a * b for a, b in lx) / sum(b * b for _, b in lx), 4)
    sd = {
        "note": "In SD Lab terms, per day. 'moves' are real flows between measured stocks (ratio 1). trials is a "
                "pipe: everything that enters leaves exactly 14 days later (k_proportional is the linear reading, "
                "share / 14). 'links': outside -> visitors at k x ad_budget (the ads spend about a seventh of the "
                "budget a day and bring 0.8 visitors a dollar; nothing leaves the budget for the visitors). "
                "'echoes': win-backs arrive in paying, timed by churned's gains exactly 90 days earlier (a pipe); churned is a "
                "cumulative count and keeps them. No hidden stocks.",
        "moves": [
            {"from": "visitors", "to": "trials", "form": "proportional", "k": P["p_trial"],
             "k_fitted": fit_k(C["trial_starts"], L["visitors"]), "what": "active visitors start a 14-day trial"},
            {"from": "trials", "to": "paying", "form": "pipe", "delay": trial_days,
             "share": P["p_convert"], "share_new_price": P["p_convert_new_price"],
             "k_proportional": round(P["p_convert"] / trial_days, 5), "k_proportional_new_price": round(P["p_convert_new_price"] / trial_days, 5),
             "k_fitted": fit_k(C["conversions"], L["trials"], old), "k_fitted_new_price": fit_k(C["conversions"], L["trials"], new),
             "what": "trials convert on day 14 (a fixed delay)"},
            {"from": "paying", "to": "churned", "form": "proportional", "k": P["churn_per_day"],
             "k_announced": P["churn_per_day_announced"], "k_new_price": P["churn_per_day_new_price"],
             "k_fitted": fit_k(C["cancellations"], L["paying"], old), "k_fitted_new_price": fit_k(C["cancellations"], L["paying"], new),
             "k_fitted_announced": fit_k(C["cancellations"], L["paying"], range(PRICE_DAY, PRICE_DAY + 5)),
             "per_era": [{"from_day": d, "k": CHURN[pr], "label": lab} for d, lab, _, pr in ERAS],
             "what": "paying customers cancel"},
        ],
        "outside": [
            {"to": "ad_budget", "form": "constant", "value": "per era",
             "per_era": [{"from_day": d, "per_day": b, "label": lab} for d, lab, b, _ in ERAS],
             "what": "the team releases the ad budget (set in eras)"},
            {"from": "ad_budget", "form": "proportional", "k": round(P["spend_share"], 4),
             "k_fitted": fit_k(C["ad_spend"], L["ad_budget"]), "what": "the ad platform spends the budget"},
            {"to": "visitors", "form": "constant", "value": P["organic_per_day"],
             "viral_spike": {str(d): v for d, v in VIRAL.items()}, "what": "organic visitors (search, word of mouth), plus a viral spike"},
            {"from": "visitors", "form": "proportional", "k": round(P["p_quiet"] * (1 - P["p_trial"]), 4),
             "k_fitted": fit_k(C["gone_quiet"], L["visitors"]), "what": "visitors go quiet"},
            {"from": "trials", "form": "pipe", "delay": trial_days, "share": round(1 - P["p_convert"], 2),
             "share_new_price": round(1 - P["p_convert_new_price"], 2),
             "k_proportional": round((1 - P["p_convert"]) / trial_days, 5), "what": "trials expire unconverted on day 14"},
        ],
        "links": [
            {"driver": "ad_budget", "into": "visitors", "k": k_link, "k_fitted": k_link_fit,
             "what": "ads bring visitors: 0.8 a dollar, spending ~1/7 of the budget a day"},
        ],
        "hidden": [],
        "echoes": [
            {"source": "churned", "into": "paying", "delay": P["win_back_days"], "shape": "pipe", "share": P["p_win_back"], "realised_mean_delay": mean(res.win_back_delays),
             "what": "cancelled customers come back months later"},
        ],
    }
    return {
        "seed": res.seed,
        "steps": STEPS,
        "step": "1 day",
        "warmup_days": WARMUP,
        "parameters": P,
        "eras": res.eras,
        "viral_spike": {str(d): v for d, v in VIRAL.items()},
        "start_levels": res.start,
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "counters": {f: {"from": a, "to": b, "total": total[f], "per_day_mean": round(total[f] / STEPS, 3)}
                     for f, (a, b) in FLOWS.items()},
        "sd_structure": sd,
        "mean_levels": {s: mean(L[s]) for s in MEASURED_STOCKS},
        "max_levels": {s: max(L[s]) for s in MEASURED_STOCKS},
    }


_cache: dict[tuple[int, int], Result] = {}


def cached(seed: int = SEED, steps: int = STEPS) -> Result:
    if (seed, steps) not in _cache:
        _cache[seed, steps] = run(seed, steps)
    return _cache[seed, steps]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED)
    g = ground_truth(r)
    print(json.dumps({k: g[k] for k in ("start_levels", "mean_levels", "max_levels", "counters")}, indent=1))
    for i in range(0, STEPS, 15):
        print(i + 1, {s: r.levels[s][i] for s in MEASURED_STOCKS})
