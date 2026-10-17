"""A seeded simulation of a valley's water: rain on a catchment, three reservoirs in a cascade and
a town's water tower, over 90 days in 1-hour steps.

This is the *real system* behind the measured `reservoirs` model. The model is told only what the
water board's telemetry shows at the end of every hour, all in megalitres (ML): the rain that fell
on the catchment in the last hour, the water held in the catchment's soil, the three reservoirs
and the town's water tower. Two stretches of river hold water too, and nothing measures them:

  rain       exogenous: storms in the wet weeks, a three-week dry spell, one big storm. The gauge
             reads what fell over the catchment in the last hour; that water soaks into the soil
             during the next hour (all of it: rain -> soil at k = 1).
  soil       loses water to evapotranspiration (proportional to what it holds, by day only) and
             runs off into the upper reservoir in proportion to what it holds above field capacity
             (k x (soil - field capacity), nothing below it).
  reservoir  each one releases toward its target level: (level - target) / time per hour, but at
             least an environmental minimum of 1.5 ML/h (scaled down by level / target below the
             target), with 4% noise in the gate setting; a spillway takes half of anything above
             the crest every hour. Both go down the river. Evaporation takes a share of what it
             holds, by day only. The middle dam releases nothing in the maintenance week (its
             spillway still works).
  river      upper -> middle: two linear stretches of 3 h each (an erlang delay, mean 6 h);
             middle -> lower: a 6-hour pipe (everything arrives 6 hours after it left). Hidden.
  tower      pumps from the lower reservoir close the tower's gap to its target over 4 hours
             (at most 8 ML an hour); the town draws from the tower with a daily cycle. The lower
             reservoir's own release leaves the valley.

Everything is computed from the levels at the start of each hour (an explicit Euler step), so a
flow in hour t depends on the levels at the end of hour t - 1. `run()` returns the end-of-hour
level of every stock (exact, and the measured ones rounded to 0.1 ML as the telemetry reports
them) and the amount of every flow in every hour.

Long runs (`run(steps=...)`, `measured(steps=...)`, years of hours): the run is a series of 90-day
seasons, cycling spring, summer, autumn, winter. The first is always the 90 days above, draw for
draw. Every later season draws its own weather and operations from its own random stream (so the
first never changes; the hourly gate and demand noise continue on the main stream): storms
(more often in autumn and winter, rarer in summer), a dry spell (longest in summer; a hot summer
can run the lower reservoir and the tower nearly dry), a big storm at the end of the dry spell or
up to two weeks later, and the middle dam's maintenance week. Every rule and
coefficient stays as above; only the weather and the maintenance calendar recur.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field

DAYS = 90
STEPS = DAYS * 24                     # one step is one hour
SEASON = DAYS * 24                    # long runs: a new 90-day season every 2160 hours
LONG_STEPS = 3 * 365 * 24             # three years, for the discovery test bed
SEED = 20261016

MEASURED_STOCKS = ["rain", "soil", "upper", "middle", "lower", "tower"]
HIDDEN_STOCKS = ["river_um1", "river_um2", "river_ml"]
STOCKS = MEASURED_STOCKS + HIDDEN_STOCKS

# every true flow: id -> (from, to); None is outside
FLOWS = {
    "rainfall": (None, "rain"),               # what fell on the catchment this hour
    "soak": ("rain", "soil"),                 # last hour's rain soaks in
    "soil_et": ("soil", None),                # evapotranspiration
    "runoff": ("soil", "upper"),              # above field capacity
    "upper_release": ("upper", "river_um1"),
    "upper_spill": ("upper", "river_um1"),
    "upper_evap": ("upper", None),
    "river_um_mid": ("river_um1", "river_um2"),
    "river_um_arrive": ("river_um2", "middle"),
    "middle_release": ("middle", "river_ml"),
    "middle_spill": ("middle", "river_ml"),
    "middle_evap": ("middle", None),
    "river_ml_arrive": ("river_ml", "lower"),
    "lower_release": ("lower", None),         # leaves the valley
    "lower_spill": ("lower", None),
    "lower_evap": ("lower", None),
    "pumping": ("lower", "tower"),
    "town_use": ("tower", None),
}
COUNTERS = list(FLOWS)

P = {
    "catchment_km2": 40,                       # 1 mm of rain = 40 ML
    "field_capacity_ml": 3500.0,
    "runoff_k": 0.03,                          # per hour, of soil above field capacity
    "et_k": 0.0012,                            # per hour, of soil (daily mean; by day only)
    "evap_k": 0.00025,                          # per hour, of a reservoir (daily mean; by day only)
    "spill_share": 0.5,                        # of what is above the crest, every hour
    "env_min_ml_per_h": 1.5,                   # environmental release, at least
    "release_noise_cv": 0.04,                  # gate settings are not exact
    "reach_um_stage_h": 3.0,                   # upper -> middle: two linear stretches (erlang, mean 6 h)
    "reach_ml_pipe_h": 6,                      # middle -> lower: a pipe
    "pump_time_h": 4.0,                        # the tower's gap closes over 4 hours
    "pump_max_ml_per_h": 8.0,
    "town_mean_ml_per_h": 2.5,
    "town_noise_cv": 0.08,
}
RESERVOIRS = {   # id: (name, crest capacity ML, target ML, release time h, initial ML)
    "upper": ("Upper reservoir", 1800.0, 150.0, 60.0, 900.0),
    "middle": ("Middle reservoir", 3000.0, 400.0, 120.0, 1900.0),
    "lower": ("Lower reservoir", 2400.0, 300.0, 90.0, 1300.0),
}
TOWER = {"target_ml": 30.0, "initial_ml": 26.0}
SOIL0 = 5200.0
NEXT_REACH = {"upper": "river_um1", "middle": "river_ml", "lower": None}

# weather and operations: (first day, label, what)
ERAS = [(0, "Start"),
        (18, "Dry spell"),
        (40, "Storm"),
        (43, "After the storm"),
        (60, "Maintenance week: the middle dam's gates are closed"),
        (67, "Middle dam back in service")]
MAINTENANCE = (60 * 24, 67 * 24)              # hours the middle reservoir releases nothing
DRY = (18 * 24, 40 * 24)
BIG_STORM = (40 * 24 + 6, 30, 230.0)          # (start hour, hours, mean ML per hour)


def daylight(h: int) -> float:
    """The sun's share of evaporation in hour h: zero at night, mean 1 over a day."""
    return math.pi * max(0.0, math.sin(2 * math.pi * ((h % 24) - 6) / 24))


def town_profile(h: int) -> float:
    """The town's draw in hour h relative to its daily mean: low at night, a morning and an evening peak."""
    x = h % 24
    return max(0.25, 1 + 0.55 * math.exp(-((x - 7.5) ** 2) / 3) * 2 + 0.45 * math.exp(-((x - 19) ** 2) / 4) * 2 - 0.6 * (x < 5 or x >= 23))


_TOWN_MEAN = sum(town_profile(h) for h in range(24)) / 24


def rainfall(rng: random.Random, dry: tuple = DRY, storm: tuple | None = BIG_STORM, gap: float = 30.0,
             scale: float = 1.0) -> list[float]:
    """ML falling on the catchment in each hour of a season: random storms (one every `gap` hours on
    average), none in the dry spell, maybe one big storm. The defaults are the first season."""
    rain = [0.0] * SEASON
    h = 0.0
    calm = (storm[0] - 24, storm[0] + storm[1] + 24) if storm else (0, 0)
    while True:
        wet = h < dry[0]
        h += rng.expovariate(1 / gap)
        if h >= SEASON:
            break
        if dry[0] <= h < dry[1] or calm[0] <= h < calm[1]:
            continue
        dur = rng.randint(3, 14)
        peak = (rng.uniform(40, 160) if wet else rng.uniform(30, 130)) * scale
        for j in range(dur):
            k = int(h) + j
            if k < SEASON and not dry[0] <= k < dry[1]:
                shape = math.sin(math.pi * (j + 0.5) / dur)
                rain[k] += peak * shape * rng.gammavariate(2.0, 0.5)
    if storm:
        s, n, mean = storm
        for j in range(n):
            rain[s + j] += mean * 1.6 * math.sin(math.pi * (j + 0.5) / n) * rng.gammavariate(4.0, 0.25)
    return rain


# long runs: (name, hours between storms on average, storm size x, dry spell days (min, max), big storm ML/h (min, max))
SEASONS = [("Spring rains", 30.0, 1.0, (15, 25), (180.0, 260.0)),
           ("Summer", 38.0, 0.9, (20, 32), (120.0, 200.0)),
           ("Autumn rains", 26.0, 1.1, (8, 18), (200.0, 280.0)),
           ("Winter storms", 22.0, 1.2, (4, 12), (180.0, 280.0))]


def season_plan(seed: int, n: int) -> tuple[list[tuple[int, str]], dict]:
    """Season n's eras [(day within the season, label)] and its weather and maintenance (hours
    within the season). Season 0 is the first 90 days (ERAS); every later one is drawn from its own
    stream: a dry spell, a big storm at its end or up to two weeks later, and a maintenance week."""
    if n == 0:
        return ERAS, {"dry": DRY, "storm": BIG_STORM, "gap": 30.0, "scale": 1.0, "maintenance": MAINTENANCE}
    rng = random.Random(f"reservoirs:{seed}:{n}")
    name, gap, scale, (lo, hi), (s_lo, s_hi) = SEASONS[n % len(SEASONS)]
    dry0 = rng.randint(8, 30)
    dry1 = dry0 + rng.randint(lo, hi)
    day = dry1 + rng.choice([0, 0, rng.randint(2, 14)])
    storm = (day * 24 + 6, rng.randint(20, 36), round(rng.uniform(s_lo, s_hi), 1))
    eras = [(0, name), (dry0, "Dry spell")] + ([(dry1, "Rain returns")] if day > dry1 else [])
    eras += [(day, "Storm"), (day + 3, "After the storm")]
    taken = {d for d, _ in eras}
    m = rng.choice([d for d in range(40, 83) if d not in taken and d + 7 not in taken])
    eras += [(m, "Maintenance week: the middle dam's gates are closed"), (m + 7, "Middle dam back in service")]
    weather = {"dry": (dry0 * 24, dry1 * 24), "storm": storm, "gap": gap, "scale": scale, "maintenance": (m * 24, (m + 7) * 24)}
    return sorted(eras), weather


@dataclass
class Result:
    seed: int
    true: dict[str, list[float]] = field(default_factory=dict)      # every stock, exact, end of hour
    levels: dict[str, list[float]] = field(default_factory=dict)    # measured stocks, as reported (0.1 ML)
    flows: dict[str, list[float]] = field(default_factory=dict)     # flow -> ML moved in each hour
    eras: list[dict] = field(default_factory=list)                  # [{t, label}] t = first step of the era
    counters: dict[str, list[float]] = field(default_factory=dict)  # flows rounded to 0.001 ML


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    assert steps >= 1
    rng = random.Random(seed)
    rain = rainfall(rng)                                  # the first season, from the main stream
    shut = bytearray(steps)                               # hours the middle dam releases nothing
    eras: list[dict] = []
    for n in range((steps - 1) // SEASON + 1):
        plan, w = season_plan(seed, n)
        h0 = n * SEASON
        if n:
            rain += rainfall(random.Random(f"reservoirs:{seed}:{n}:rain"), w["dry"], w["storm"], w["gap"], w["scale"])
        for h in range(h0 + w["maintenance"][0], min(steps, h0 + w["maintenance"][1])):
            shut[h] = 1
        eras += [{"t": h0 + day * 24 + 1, "label": label} for day, label in plan if h0 + day * 24 + 1 <= steps]
    lv = {s: 0.0 for s in STOCKS}
    lv["soil"] = SOIL0
    for r, (_, _, _, _, v0) in RESERVOIRS.items():
        lv[r] = v0
    lv["tower"] = TOWER["initial_ml"]
    # rivers start with what the rules were sending down them
    lv["river_um1"] = lv["river_um2"] = (RESERVOIRS["upper"][4] - RESERVOIRS["upper"][2]) / RESERVOIRS["upper"][3] * P["reach_um_stage_h"]
    pipe = [(RESERVOIRS["middle"][4] - RESERVOIRS["middle"][2]) / RESERVOIRS["middle"][3]] * P["reach_ml_pipe_h"]
    lv["river_ml"] = sum(pipe)
    res = Result(seed=seed, true={s: [] for s in STOCKS}, flows={f: [0.0] * steps for f in FLOWS})
    F = res.flows
    for h in range(steps):
        q: dict[str, float] = {}
        q["rainfall"] = rain[h]
        q["soak"] = lv["rain"]
        q["soil_et"] = P["et_k"] * daylight(h) * lv["soil"]
        q["runoff"] = P["runoff_k"] * max(0.0, lv["soil"] - P["field_capacity_ml"])
        for r, (_, crest, target, time, _) in RESERVOIRS.items():
            v = lv[r]
            rule = max(P["env_min_ml_per_h"] * min(1.0, v / target), (v - target) / time) * max(0.0, 1 + P["release_noise_cv"] * rng.gauss(0, 1))
            if r == "middle" and shut[h]:
                rule = 0.0
            spill = P["spill_share"] * max(0.0, v - crest)
            evap = P["evap_k"] * daylight(h) * v
            if r == "lower":
                pump = min(P["pump_max_ml_per_h"], max(0.0, (TOWER["target_ml"] - lv["tower"]) / P["pump_time_h"]))
                pump = min(pump, v)
                q["pumping"] = pump
                v -= pump
            rule = min(rule, max(0.0, v - spill - evap))
            q[f"{r}_release"], q[f"{r}_spill"], q[f"{r}_evap"] = rule, spill, evap
        q["river_um_mid"] = lv["river_um1"] / P["reach_um_stage_h"]
        q["river_um_arrive"] = lv["river_um2"] / P["reach_um_stage_h"]
        q["river_ml_arrive"] = pipe.pop(0)
        pipe.append(q["middle_release"] + q["middle_spill"])
        demand = P["town_mean_ml_per_h"] * town_profile(h) / _TOWN_MEAN * max(0.0, 1 + P["town_noise_cv"] * rng.gauss(0, 1))
        q["town_use"] = min(demand, lv["tower"])
        for f, (a, b) in FLOWS.items():
            F[f][h] = q[f]
            if a:
                lv[a] -= q[f]
            if b:
                lv[b] += q[f]
        for s in STOCKS:
            res.true[s].append(lv[s])
    res.levels = {s: [round(x, 1) for x in res.true[s]] for s in MEASURED_STOCKS}
    res.counters = {f: [round(x, 3) for x in F[f]] for f in FLOWS}
    res.eras = eras
    return res


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees over `steps` hours: the telemetry's six levels at 0.1 ML (what history.py
    prints for the default length), the eras, and every true flow per hour at 0.001 ML (the rivers'
    own levels never appear)."""
    res = run(seed, steps)
    return {"t": list(range(1, steps + 1)), "levels": res.levels,
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras], "counters": res.counters}


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least squares y = a + b x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - b * mx, b


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict (summaries; the per-hour series
    are in the recording and the test fixture)."""
    r4 = lambda x: round(x, 4)                     # noqa: E731
    mean = lambda xs: round(sum(xs) / len(xs), 3)  # noqa: E731
    T, F = res.true, res.flows
    prev = {s: [None] + T[s][:-1] for s in STOCKS}

    def k_real(flow: str, stock: str, excess: float = 0.0) -> float:
        """Realised share per hour: what the flow moved / what (above `excess`) the stock held the hour before."""
        num = sum(F[flow][1:])
        den = sum(max(0.0, x - excess) for x in prev[stock][1:])
        return r4(num / den) if den else 0.0

    total = {f: round(sum(v), 1) for f, v in F.items()}
    per_h = {f: r4(sum(v) / STEPS) for f, v in F.items()}
    moves = [
        {"from": "rain", "to": "soil", "form": "proportional", "k": 1.0, "k_realised": k_real("soak", "rain"), "flow": "soak",
         "what": "last hour's rain soaks into the soil (all of it, one hour later). Equivalently a link outside -> soil at "
                 "1 x the gauge plus the gauge emptying to outside at k = 1; as a move it costs nothing to outside."},
        {"from": "soil", "to": "upper", "form": "linear (gap on the source)", "k": P["runoff_k"], "c": r4(-P["runoff_k"] * P["field_capacity_ml"]),
         "threshold": P["field_capacity_ml"], "flow": "runoff", "k_realised_above_threshold": k_real("runoff", "soil", P["field_capacity_ml"]),
         "share_of_hours_running": r4(sum(1 for x in F["runoff"] if x > 0) / STEPS),
         "what": "runoff: k x (soil - field capacity) per hour, nothing below field capacity (it stops in the dry spell)"},
        {"from": "lower", "to": "tower", "form": "gap", "stock": "tower", "goal": TOWER["target_ml"], "time": P["pump_time_h"],
         "k": r4(1 / P["pump_time_h"]), "value_max": P["pump_max_ml_per_h"], "flow": "pumping",
         "what": "the town pumps from the lower reservoir to close the tower's gap to 30 ML over 4 hours (at most 8 ML/h)"},
    ]

    def release_rule(r: str) -> dict:
        _, crest, target, time, _ = RESERVOIRS[r]
        shut = range(*MAINTENANCE) if r == "middle" else range(0)
        linear = [h for h in range(1, STEPS) if (prev[r][h] - target) / time > P["env_min_ml_per_h"] and prev[r][h] <= crest and h not in shut]
        c, k = _fit([prev[r][h] for h in linear], [F[f"{r}_release"][h] for h in linear])
        return {"form": "linear (gap on the source)", "k": r4(1 / time), "c": r4(-target / time), "goal": target, "time": time,
                "value_min": P["env_min_ml_per_h"], "crest": crest, "spill_share": P["spill_share"],
                "hours_spilling": sum(1 for x in F[f"{r}_spill"] if x > 0), "hours_at_minimum": sum(1 for h in range(1, STEPS) if (prev[r][h] - target) / time <= P["env_min_ml_per_h"] and h not in shut),
                "hours_shut": len(shut), "fit_where_linear": {"k": r4(k), "c": round(c, 2)},
                "k_if_proportional": k_real(f"{r}_release", r),
                "rule": f"release = max({P['env_min_ml_per_h']} x min(1, level / {target:g}), (level - {target:g}) / {time:g}) per hour, x (1 + 4% noise)"
                        + (", nothing in the maintenance week" if shut else "")
                        + f"; spill = {P['spill_share']} x (level - {crest:g}) above the crest"}

    outside = [
        {"to": "rain", "form": "constant", "value": per_h["rainfall"], "flow": "rainfall",
         "what": "rain on the catchment: exogenous storms and a dry spell (mean shown; it is anything but constant)"},
        {"from": "soil", "form": "proportional", "k": P["et_k"], "k_realised": k_real("soil_et", "soil"), "flow": "soil_et",
         "what": "evapotranspiration, by day only (daily mean k)"},
    ]
    for r in RESERVOIRS:
        outside.append({"from": r, "form": "proportional", "k": P["evap_k"], "k_realised": k_real(f"{r}_evap", r), "flow": f"{r}_evap",
                        "what": f"evaporation from the {r} reservoir, by day only (daily mean k)"})
    crest = RESERVOIRS["lower"][1]
    outside += [
        {"from": "lower", **release_rule("lower"), "flow": "lower_release",
         "what": "the lower dam's release leaves the valley: (level - target) / time, at least the environmental minimum (scaled by level / target below the target)"},
        {"from": "lower", "form": "spillway (nonlinear)", "k": P["spill_share"], "threshold": crest, "flow": "lower_spill",
         "hours_spilling": sum(1 for x in F["lower_spill"] if x > 0), "what": "spillway: half of what is above the crest each hour"},
        {"from": "tower", "form": "constant", "value": per_h["town_use"], "flow": "town_use",
         "what": "the town draws from the tower with a daily cycle (mean shown) and noise"},
    ]
    reach_um = [a + b for a, b in zip(T["river_um1"], T["river_um2"])]
    sent_um = [a + b for a, b in zip(F["upper_release"], F["upper_spill"])]
    sent_ml = [a + b for a, b in zip(F["middle_release"], F["middle_spill"])]

    hidden = [
        {"from": "upper", "to": "middle", "shape": "erlang", "delay": 2 * P["reach_um_stage_h"], "share": 1.0,
         "holds": mean(reach_um), "holds_max": round(max(reach_um), 1), "stocks": ["river_um1", "river_um2"],
         "flow_in_per_h": r4(sum(sent_um) / STEPS), **release_rule("upper"),
         "what": "the river from the upper to the middle dam: two linear stretches of 3 h each (mean 6 h)"},
        {"from": "middle", "to": "lower", "shape": "pipe", "delay": P["reach_ml_pipe_h"], "share": 1.0,
         "holds": mean(T["river_ml"]), "holds_max": round(max(T["river_ml"]), 1), "stocks": ["river_ml"],
         "flow_in_per_h": r4(sum(sent_ml) / STEPS), **release_rule("middle"),
         "what": "the river from the middle to the lower dam: everything arrives 6 hours after it left"},
    ]
    return {
        "seed": res.seed,
        "steps": STEPS,
        "step": "1 hour",
        "unit": "ML (megalitres)",
        "parameters": P,
        "reservoirs": {r: {"name": n, "crest_ml": c, "target_ml": tg, "release_time_h": tm, "initial_ml": v0}
                       for r, (n, c, tg, tm, v0) in RESERVOIRS.items()},
        "tower": TOWER,
        "soil_initial_ml": SOIL0,
        "weather": {"dry_spell_hours": list(DRY), "big_storm": {"start_hour": BIG_STORM[0], "hours": BIG_STORM[1]},
                    "rain_total_ml": total["rainfall"], "rain_hours": sum(1 for x in F["rainfall"] if x > 0)},
        "maintenance_hours": list(MAINTENANCE),
        "eras": res.eras,
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "flows": {f: {"from": a, "to": b, "total_ml": total[f], "per_step_mean": per_h[f]} for f, (a, b) in FLOWS.items()},
        "sd_structure": {
            "note": "In SD Lab terms, per hour, in ML. 'moves' are flows between measured stocks; 'outside' flows to and from "
                    "outside; 'hidden' flows from one measured stock to another through a river nobody measures (release and "
                    "spill both go down it); no links and no echoes (nothing here is final). Gap forms on the source "
                    "(release toward a target, runoff above field capacity) are 'linear' in discovery's terms: c + k x source, c < 0.",
            "moves": moves,
            "outside": outside,
            "links": [],
            "hidden": hidden,
            "echoes": [],
        },
        "mean_levels": {s: mean(T[s]) for s in STOCKS},
        "max_levels": {s: round(max(T[s]), 1) for s in STOCKS},
        "min_levels": {s: round(min(T[s]), 1) + 0.0 for s in STOCKS},
    }


_cache: dict[tuple[int, int], Result] = {}


def cached(seed: int = SEED, steps: int = STEPS) -> Result:
    if (seed, steps) not in _cache:
        _cache[seed, steps] = run(seed, steps)
    return _cache[seed, steps]


if __name__ == "__main__":
    g = ground_truth(run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED))
    print(json.dumps({"weather": g["weather"], "mean_levels": g["mean_levels"], "min_levels": g["min_levels"], "max_levels": g["max_levels"],
                      "per_hour": {f: v["per_step_mean"] for f, v in g["flows"].items()},
                      "hidden": [{k: h[k] for k in ("from", "to", "holds", "hours_spilling", "hours_at_minimum", "fit_where_linear")} for h in g["sd_structure"]["hidden"]]}, indent=1))
