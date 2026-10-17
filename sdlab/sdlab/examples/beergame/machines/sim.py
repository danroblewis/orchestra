"""A seeded simulation of the beer distribution game: a retailer, a wholesaler, a distributor and a
brewery, one step a day for a year.

This is the *real system* behind the measured `beergame` model. The model is told only what each
tier's books show at the end of every day: cases in its warehouse (inventory) and cases it owes
the tier below (backlog: orders received and not yet shipped). Nobody counts the trucks on the
road, the beer in the brewery's tanks, the orders in the mail, or how each tier decides what to
order. That is the answer key (sdlab/examples/beergame/README.md, truth.json).

Every day, at every tier, in this order:

  receive    the shipment that left the tier above `SHIP_DAYS` ago arrives (the brewery: the
             batch it started brewing `BREW_DAYS` ago is ready)
  ship       the tier ships what it can of the orders on hand since yesterday: the smaller of its
             inventory and its backlog. Shipments go into a truck to the tier below (the
             retailer's go to its customers, out of the system)
  orders in  the orders the tier below placed yesterday arrive in the backlog (the retailer's
             customers order today; they are served tomorrow)
  order      the tier orders from the tier above (the brewery: starts brewing) by anchoring and
             adjustment (Sterman 1989): expected demand, plus a share of the gap between its
             desired and actual net stock (inventory - backlog), plus a smaller share of the gap
             in its supply line (orders placed and not yet received), never below zero. The
             order is in the mail for a day.

Customer demand is Poisson: 40 cases a day, 60 from day 100 (the step), and a summer promotion.
The brewery's capacity drops for two weeks of maintenance (an era).

Long runs (`run(seed, steps)` with steps > 365): the year repeats every 365 days with fresh random
demand. The demand step alternates: in even years (the first is year 0) demand is 40 a day and
steps up to 60 on day 100 of the year; in odd years it is 60 and steps down to 40 on day 100 (a
slump), so it stays between 40 and 60. The summer promotion (days 240-253 of the year, x1.4)
comes every year. From the second year on the brewery services a line twice a year, days 60-73
and 200-213 of the year (40 cases a day; eras). The first 365 days are exactly the default run.

    python sim.py [seed] [steps]  prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field

YEAR = 365                            # the schedule repeats every year
STEPS = YEAR                          # one step is one day
LONG_STEPS = 10 * YEAR                # ten years, for long discovery runs
SEED = 20261016

TIERS = ["retailer", "wholesaler", "distributor", "brewery"]          # downstream to upstream
UPSTREAM = {"retailer": "wholesaler", "wholesaler": "distributor", "distributor": "brewery"}
SHIP_DAYS = {"wholesaler": 2, "distributor": 3, "brewery": 4}         # days in a truck to the tier below
BREW_DAYS = 3

MEASURED_STOCKS = [f"inv_{t}" for t in TIERS] + [f"backlog_{t}" for t in TIERS]
HIDDEN_STOCKS = ["transit_retailer", "transit_wholesaler", "transit_distributor", "brewing", "mail"]

P = {
    "demand_before": 40.0,            # customer orders a day (Poisson mean) until day 99 (odd years: from day 100)
    "demand_after": 60.0,             # from day 100 (odd years: until day 99)
    "step_day": 100,                  # day of the year
    "promotion": (240, 254, 1.4),     # days of the year [from, to): demand x1.4
    "net_stock_goal": 80,             # desired inventory - backlog (equilibrium: 120 in stock, 40 owed)
    "alpha_stock": 0.20,              # share of the net-stock gap ordered each day
    "alpha_supply": 0.10,             # share of the supply-line gap (people underweight it)
    "theta": 0.25,                    # smoothing of expected demand
    "initial_demand": 40,
}

# eras: (first day, brewing capacity in cases a day, label)
DOWN, BACK = "Brewery: one line down for maintenance (40 cases a day)", "Brewery: both lines back (200 cases a day)"
CAPACITY = [(1, 200, "Start"), (200, 40, DOWN), (214, 200, BACK)]
LATER_CAPACITY = [(60, 40, DOWN), (74, 200, BACK), (200, 40, DOWN), (214, 200, BACK)]   # days of every later year


def schedule(steps: int = STEPS) -> list[tuple[int, int, str]]:
    """(first day, capacity, label) of every era in a run of `steps` days."""
    out = list(CAPACITY)
    for y in range(1, (steps + YEAR - 1) // YEAR):
        out += [(y * YEAR + d, c, label) for d, c, label in LATER_CAPACITY]
    return [e for e in out if e[0] <= steps]


def counter_ids() -> list[str]:
    """Every per-day counter the recording has (none of them is in the model)."""
    out = ["customer_orders", "brewed", "produced"]
    for t in TIERS:
        out += [f"shipped__{t}", f"received__{t}", f"orders_in__{t}", f"ordered__{t}"]
    return out


COUNTERS = counter_ids()


def year_day(day: int) -> tuple[int, int]:
    """(year from 0, day of the year from 1) of a day counted from 1."""
    return (day - 1) // YEAR, (day - 1) % YEAR + 1


def demand_mean(day: int) -> float:
    y, d = year_day(day)
    low, high = P["demand_before"], P["demand_after"]
    m = (low if d < P["step_day"] else high) if y % 2 == 0 else (high if d < P["step_day"] else low)
    a, b, x = P["promotion"]
    return m * x if a <= d < b else m


def capacity(day: int) -> int:
    y, d = year_day(day)
    c = CAPACITY[0][1]
    for first, cap, _ in CAPACITY if y == 0 else LATER_CAPACITY:
        if d >= first:
            c = cap
    return c


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method in chunks (exact for any mean, stdlib only)."""
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


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)       # stock -> end-of-day level, days 1..STEPS
    counters: dict[str, list[int]] = field(default_factory=dict)     # counter -> cases in each day
    eras: list[dict] = field(default_factory=list)                   # [{t, label}] t = first day of the era
    start: dict[str, int] = field(default_factory=dict)              # every stock's level before day 1


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    """`steps` days (any length >= 1; the year repeats). The default is the one-year run."""
    assert steps >= 1
    rng = random.Random(seed)
    d0 = P["initial_demand"]
    inv = {t: P["net_stock_goal"] + d0 for t in TIERS}               # equilibrium: 120 in stock, 40 owed
    backlog = {t: d0 for t in TIERS}
    trucks = {t: [d0] * SHIP_DAYS[UPSTREAM[t]] for t in UPSTREAM}    # trucks[t][0] arrives at t tomorrow
    tanks = [d0] * BREW_DAYS                                         # tanks[0] is ready tomorrow
    mail = {t: d0 for t in UPSTREAM}                                 # what t ordered yesterday, arriving upstream today
    expected = {t: float(d0) for t in TIERS}
    res = Result(seed=seed, counters={c: [0] * steps for c in COUNTERS},
                 levels={s: [] for s in MEASURED_STOCKS + HIDDEN_STOCKS})
    C = res.counters

    def hidden_levels() -> dict[str, int]:
        return {"transit_retailer": sum(trucks["retailer"]), "transit_wholesaler": sum(trucks["wholesaler"]),
                "transit_distributor": sum(trucks["distributor"]), "brewing": sum(tanks), "mail": sum(mail.values())}

    res.start = {**{f"inv_{t}": inv[t] for t in TIERS}, **{f"backlog_{t}": backlog[t] for t in TIERS}, **hidden_levels()}
    for i in range(steps):
        day = i + 1
        # receive
        for t in TIERS:
            got = tanks.pop(0) if t == "brewery" else trucks[t].pop(0)
            inv[t] += got
            C[f"received__{t}"][i] = got
        C["produced"][i] = C["received__brewery"][i]
        # ship what can be shipped of the orders on hand since yesterday
        for t in TIERS:
            s = min(inv[t], backlog[t])
            inv[t] -= s
            backlog[t] -= s
            C[f"shipped__{t}"][i] = s
            if t != "retailer":
                below = next(d for d, u in UPSTREAM.items() if u == t)
                trucks[below].append(s)
        # orders arrive
        incoming = {"retailer": poisson(rng, demand_mean(day))}
        C["customer_orders"][i] = incoming["retailer"]
        for t, u in UPSTREAM.items():
            incoming[u] = mail[t]
        for t in TIERS:
            backlog[t] += incoming[t]
            C[f"orders_in__{t}"][i] = incoming[t]
        # decide: anchoring and adjustment
        for t in TIERS:
            expected[t] += P["theta"] * (incoming[t] - expected[t])
            if t == "brewery":
                supply, lead = sum(tanks), BREW_DAYS
            else:
                u = UPSTREAM[t]
                supply, lead = backlog[u] + sum(trucks[t]), 1 + SHIP_DAYS[u]
            want = expected[t] + P["alpha_stock"] * (P["net_stock_goal"] - inv[t] + backlog[t]) \
                + P["alpha_supply"] * (expected[t] * lead - supply)
            order = max(0, int(round(want)))
            if t == "brewery":
                order = min(order, capacity(day))
                tanks.append(order)
                C["brewed"][i] = order
            else:
                mail[t] = order
            C[f"ordered__{t}"][i] = order
        for t in TIERS:
            res.levels[f"inv_{t}"].append(inv[t])
            res.levels[f"backlog_{t}"].append(backlog[t])
        for k, v in hidden_levels().items():
            res.levels[k].append(v)
    res.eras = [{"t": d, "label": label} for d, _, label in schedule(steps)]
    return res


def realised_k(res: Result, counter: str, stock: str) -> float:
    """Cases moved a day per unit of `stock` at the end of the day before."""
    lv = res.levels[stock]
    prev = [res.start[stock], *lv[:-1]]
    return round(sum(res.counters[counter]) / max(1, sum(prev)), 4)


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict, with the SD structure a perfect
    discovery would report."""
    mean = lambda xs: round(sum(xs) / len(xs), 3)   # noqa: E731
    lv, C = res.levels, res.counters
    n = len(lv["inv_retailer"])
    a_s, a_sl = P["alpha_stock"], P["alpha_supply"]
    hidden = []
    for below, up in UPSTREAM.items():
        hidden.append({"from": f"inv_{up}", "to": f"inv_{below}", "shape": "pipe", "delay": SHIP_DAYS[up],
                       "share": realised_k(res, f"shipped__{up}", f"inv_{up}"), "holds": mean(lv[f"transit_{below}"]),
                       "stock": f"transit_{below}", "rate": f"min(inv_{up}, backlog_{up} of the day before)",
                       "rate_driver": {"stock": f"backlog_{up}", "k": realised_k(res, f"shipped__{up}", f"backlog_{up}")},
                       "what": f"the {up} ships to the {below}: cases ride a truck for {SHIP_DAYS[up]} days (nobody counts trucks)"})
    outside = [
        {"to": "backlog_retailer", "form": "constant", "value": round(sum(C["customer_orders"]) / n, 3),
         "piecewise": [{"from_day": 1, "mean": P["demand_before"]}, {"from_day": P["step_day"], "mean": P["demand_after"]},
                       {"from_day": P["promotion"][0], "to_day": P["promotion"][1] - 1, "mean": P["demand_after"] * P["promotion"][2]}],
         "what": "customer orders (Poisson): 40 a day, 60 from day 100, x1.4 in the promotion"},
        {"from": "inv_retailer", "form": "proportional", "stock": "backlog_retailer",
         "k": realised_k(res, "shipped__retailer", "backlog_retailer"), "k_inventory": realised_k(res, "shipped__retailer", "inv_retailer"),
         "what": "sales: the retailer hands customers yesterday's orders, as far as its stock goes (k = 1 x backlog while stocked)"},
        {"to": "inv_brewery", "form": "pipe", "delay": BREW_DAYS, "value": round(sum(C["produced"]) / n, 3), "stock": "brewing",
         "what": "production: what the brewery started brewing 3 days before (its own order, capped by capacity)"},
    ]
    for t in TIERS:
        outside.append({"from": f"backlog_{t}", "form": "proportional", "k": realised_k(res, f"shipped__{t}", f"backlog_{t}"),
                        "k_nominal": 1.0, "what": f"orders the {t} filled (the same cases leave inv_{t}): all of yesterday's backlog while stocked"})
    links = []
    for below, up in UPSTREAM.items():
        for driver, k in ((f"backlog_{below}", a_s), (f"inv_{below}", -a_s)):
            links.append({"driver": driver, "into": f"backlog_{up}", "k": k, "delay": 1,
                          "what": f"the {below}'s orders reach the {up}'s backlog a day later: "
                                  f"expected demand + {a_s} x (80 - inv_{below} + backlog_{below}) + {a_sl} x supply-line gap"})
    for driver, k in (("backlog_brewery", a_s), ("inv_brewery", -a_s)):
        links.append({"driver": driver, "into": "inv_brewery", "k": k, "delay": BREW_DAYS,
                      "what": "the brewery's brewing decision, ready 3 days later (capped by capacity)"})
    return {
        "seed": res.seed,
        "steps": n,
        "step": "1 day",
        "parameters": {**P, "promotion": list(P["promotion"]), "ship_days": SHIP_DAYS, "brew_days": BREW_DAYS},
        "capacity": [{"from_day": d, "cases_per_day": c, "label": lab} for d, c, lab in schedule(n)],
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "hidden_stocks": {k: {"mean_level": mean(lv[k]), "max_level": max(lv[k])} for k in HIDDEN_STOCKS},
        "ordering_rule": "order = max(0, round(E + alpha_stock x (net_stock_goal - inventory + backlog) + alpha_supply x (E x lead - supply line))); "
                         "E += theta x (orders in - E); supply line = upstream backlog + cases in trucks (brewery: in the tanks); "
                         "lead = 1 day of picking + truck days (brewery: 3 brewing days)",
        "totals": {c: sum(v) for c, v in C.items()},
        "sd_structure": {
            "note": "In SD Lab terms, one day per step. There are no direct stock-to-stock moves: every shipment leaves a tier's "
                    "inventory, rides a truck nobody counts (a pipe delay) and arrives in the next tier's inventory (hidden). "
                    "The rate of a shipment is set by the shipper's backlog of the day before (min(inventory, backlog)), not by "
                    "its inventory: 'share' is shipments / inventory of the day before, realised, for comparison with a "
                    "proportional fit; 'rate_driver' gives the true driver. The same cases also leave the shipper's backlog "
                    "(outside flows from backlog_*). Orders are information: nothing leaves the tier that orders; the upstream "
                    "backlog gains a day later at a rate that rises with the orderer's backlog and falls with its inventory "
                    "(links, k = +-alpha_stock, plus expected demand and the supply-line term, which no measured stock carries).",
            "moves": [],
            "outside": outside,
            "links": links,
            "hidden": hidden,
            "echoes": [],
        },
        "mean_levels": {s: mean(lv[s]) for s in MEASURED_STOCKS},
        "max_levels": {s: max(lv[s]) for s in MEASURED_STOCKS},
        "min_levels": {s: min(lv[s]) for s in MEASURED_STOCKS},
        "eras": res.eras,
    }


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees of a run: the measured levels per day, the eras, and the daily counters.
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
    print(json.dumps({"mean_levels": g["mean_levels"], "max_levels": g["max_levels"], "min_levels": g["min_levels"],
                      "hidden": g["hidden_stocks"], "totals": g["totals"]}, indent=1))
