"""A seeded, per-ride simulation of a city bike share: 6 docking stations, 200 bikes and one
rebalancing van, over two weeks in 5-minute steps.

This is the *real system* behind the measured `bikeshare` model. The model is told only what the
operator's dashboard shows at the end of every 5 minutes: bikes docked at each station and bikes
on the rebalancing van. It is never told who rides where, how long a ride takes, or how the van
chooses its stops; that is the answer key (sdlab/examples/bikeshare/README.md, truth.json).

How it works (5-minute steps, ride times in continuous minutes):

  rides         every bike docked at a station at the end of a step is taken in the next step
                with a probability (the station's hazard, 3 to 4.5% a step) times the time of
                day: x0.35 at night, x1 in the day, x1.3 in the weekday rush hours, x0.8 at
                weekends; a rain day halves it. A rider picks one of the station's two or three
                destinations; on weekdays the shares follow the commute (towards Business Park
                and University in the morning, back in the evening); weekends head for Old Town
                and the Waterfront. The rider leaves at a uniform moment of the step and rides
                for a lognormal time (the pair's mean, 10 to 25 minutes, cv 0.2). Bikes being
                ridden are not docked anywhere: nobody counts them (one hidden stock per pair).
  full docks    a rider who finds the destination full docks at its fixed neighbour instead
                (the next one along when that is full too).
  closed        a closed station takes no rides and no bikes: riders headed there go to its
                neighbour; the bikes docked there stay locked in.
  the van       during the crew's shift the van rebalances without a break: it goes to the
                fullest station (by share of docks, if above 60%), loads 5 bikes a step (up to
                20, down to half the docks), drives to the emptiest station (if below 40%) and
                unloads 5 a step there (up to 60% of the docks); what does not fit stays on
                the van for its next run. With nothing worth moving it looks again 15 minutes
                later.

`run(seed, steps)` runs any number of steps. The two-week schedule recurs every two weeks (always
starting on a Monday): the extra docks are taken away again and the van goes back to the day
shift, then the rain day, the extra docks, the Waterfront's closure and the late van shift come
round again, each moved by a day or so (drawn from a generator of its own, so the rides' random
draws are untouched). The first two weeks are always exactly the original ones; the structure
and every parameter stay the same at any length.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field

DAYS = 14
STEP_MIN = 5
STEPS_PER_DAY = 24 * 60 // STEP_MIN    # 288
STEPS = DAYS * STEPS_PER_DAY           # 4032 steps of 5 minutes; day 0 is a Monday
SEED = 20261016
PERIOD = STEPS                         # the schedule recurs every two weeks
LONG_STEPS = 182 * STEPS_PER_DAY       # 26 weeks (52,416 steps): the long run for the discovery test bed

# id: (name, docks, bikes at the start, neighbour a rider goes to when it is full or closed)
STATIONS = {
    "riverside": ("Riverside", 65, 40, "old_town"),
    "old_town": ("Old Town", 65, 44, "central"),
    "central": ("Central Station", 75, 48, "old_town"),
    "waterfront": ("Waterfront", 50, 26, "old_town"),
    "university": ("University", 70, 26, "central"),
    "business_park": ("Business Park", 44, 16, "university"),
}
IDS = list(STATIONS)
VAN = "van"
BIKES = sum(v[2] for v in STATIONS.values())     # 200 docked + 0 on the van at the start
MEASURED_STOCKS = [*IDS, VAN]

# mean ride minutes between stations (symmetric): 10 to 25 minutes
_RIDE = {
    ("riverside", "old_town"): 10, ("riverside", "central"): 15, ("riverside", "waterfront"): 13,
    ("riverside", "university"): 20, ("riverside", "business_park"): 25,
    ("old_town", "central"): 10, ("old_town", "waterfront"): 11, ("old_town", "university"): 15,
    ("old_town", "business_park"): 21,
    ("central", "waterfront"): 12, ("central", "university"): 13, ("central", "business_park"): 17,
    ("waterfront", "university"): 18, ("waterfront", "business_park"): 23,
    ("university", "business_park"): 12,
}
RIDE_MIN = {**_RIDE, **{(b, a): m for (a, b), m in _RIDE.items()}}
RIDE_CV = 0.2
PAIRS = [(a, b) for a in IDS for b in IDS if a != b]

# hazard: the share of a station's docked bikes taken in one 5-minute step, before the time of day
HAZARD = {"riverside": 0.033, "old_town": 0.039, "central": 0.045, "waterfront": 0.030,
          "university": 0.036, "business_park": 0.033}

PERIODS = ["night", "morning", "midday", "evening"]


def period(step: int) -> str:
    h = (step % STEPS_PER_DAY) * STEP_MIN / 60
    if h < 6 or h >= 21:
        return "night"
    if h < 10.5:
        return "morning"
    if h < 15.5:
        return "midday"
    return "evening"


# where riders go: each station sends bikes to two or three others; on weekdays the shares follow
# the commute (towards Business Park and University in the morning, back in the evening)
DEST = {
    "riverside": {"morning": {"business_park": 0.7, "old_town": 0.3}, "midday": {"business_park": 0.4, "old_town": 0.6},
                  "evening": {"business_park": 0.2, "old_town": 0.8}, "night": {"business_park": 0.2, "old_town": 0.8}},
    "old_town": {"morning": {"university": 0.6, "central": 0.3, "riverside": 0.1}, "midday": {"university": 0.3, "central": 0.4, "riverside": 0.3},
                 "evening": {"university": 0.1, "central": 0.4, "riverside": 0.5}, "night": {"university": 0.1, "central": 0.4, "riverside": 0.5}},
    "central": {"morning": {"business_park": 0.6, "waterfront": 0.1, "old_town": 0.3}, "midday": {"business_park": 0.3, "waterfront": 0.4, "old_town": 0.3},
                "evening": {"business_park": 0.1, "waterfront": 0.4, "old_town": 0.5}, "night": {"business_park": 0.1, "waterfront": 0.3, "old_town": 0.6}},
    "waterfront": {"morning": {"central": 0.7, "old_town": 0.3}, "midday": {"central": 0.5, "old_town": 0.5},
                   "evening": {"central": 0.4, "old_town": 0.6}, "night": {"central": 0.4, "old_town": 0.6}},
    "university": {"morning": {"business_park": 0.6, "old_town": 0.4}, "midday": {"business_park": 0.3, "old_town": 0.7},
                   "evening": {"business_park": 0.1, "old_town": 0.9}, "night": {"business_park": 0.1, "old_town": 0.9}},
    "business_park": {"morning": {"university": 0.6, "central": 0.2, "riverside": 0.2}, "midday": {"university": 0.4, "central": 0.3, "riverside": 0.3},
                      "evening": {"university": 0.1, "central": 0.4, "riverside": 0.5}, "night": {"university": 0.1, "central": 0.4, "riverside": 0.5}},
}
WEEKEND_DEST = {
    "riverside": {"business_park": 0.1, "old_town": 0.9},
    "old_town": {"university": 0.1, "central": 0.5, "riverside": 0.4},
    "central": {"business_park": 0.05, "waterfront": 0.7, "old_town": 0.25},
    "waterfront": {"central": 0.5, "old_town": 0.5},
    "university": {"business_park": 0.1, "old_town": 0.9},
    "business_park": {"university": 0.3, "central": 0.4, "riverside": 0.3},
}

RAIN_DAY = (2, 0.5)                    # day 2 (a Wednesday): it rains all day, rides x0.5
DOCKS_ERA = (4, "business_park", 64)   # from day 4: Business Park gets 20 more docks
CLOSED = (8, 9, "waterfront")          # Waterfront closed for a festival from day 8 to day 9
VAN_ERA = 11                           # from day 11 the van crew also works a late shift
VAN_SHIFT = {"day": (6.5, 19.0), "day and late": (6.5, 23.5)}   # hours of the day the van works
VAN_RULES = {"capacity": 20, "per_step": 5, "load_down_to": 0.5, "unload_up_to": 0.6,
       "full_above": 0.6, "empty_below": 0.4, "idle_steps": 3}
VAN_DRIVE_MIN = 0.8                    # the van drives at about ride time x 0.8, at least 2 steps

ERAS = [(0, "Start"),
        (DOCKS_ERA[0], "Business Park: 20 more docks (44 to 64)"),
        (CLOSED[0], "Waterfront closed for a festival"),
        (CLOSED[1], "Waterfront reopened"),
        (VAN_ERA, "The van crew works a late shift too (until 23:30)")]


RESET_LABEL = "Business Park back to 44 docks; the van crew back to the day shift"


def schedule(seed: int, k: int) -> dict:
    """Period k's events (the k-th two weeks), in absolute days: the rain day, the extra docks,
    the closure [from, to) and the late van shift, and its eras [(day, label)]. Period 0 is the
    original schedule; later ones start by undoing what the last one changed and move each event
    by a day or so."""
    if k == 0:
        return {"rain": RAIN_DAY[0], "docks": DOCKS_ERA[0], "closed": CLOSED[:2], "van": VAN_ERA, "eras": list(ERAS)}
    r, off = random.Random(seed * 1_000_003 + k), k * DAYS
    rain = r.randint(0, DAYS - 1)
    more = DOCKS_ERA[0] + r.randint(-2, 2)
    shut = CLOSED[0] + r.randint(-1, 1)
    reopen = shut + r.randint(1, 2)
    van = r.randint(max(VAN_ERA - 1, reopen + 1), DAYS - 1)
    days = [0, more, shut, reopen, van]
    labels = [RESET_LABEL] + [label for _, label in ERAS[1:]]
    return {"rain": off + rain, "docks": off + more, "closed": (off + shut, off + reopen), "van": off + van,
            "eras": [(off + d, label) for d, label in zip(days, labels)]}


def calendar(seed: int, steps: int) -> list[dict]:
    """What each day of a run of `steps` steps is like: Business Park's docks, whether the
    Waterfront is closed, the rain factor and the van's shift."""
    out = []
    for k in range(-(-steps // PERIOD)):
        sc = schedule(seed, k)
        for d in range(k * DAYS, (k + 1) * DAYS):
            out.append({"bp_docks": DOCKS_ERA[2] if d >= sc["docks"] else STATIONS[DOCKS_ERA[1]][1],
                        "closed": sc["closed"][0] <= d < sc["closed"][1],
                        "rain": RAIN_DAY[1] if d == sc["rain"] else 1.0,
                        "shift": "day and late" if d >= sc["van"] else "day"})
    return out


_CAL = calendar(SEED, STEPS)                   # the original two weeks (the same for every seed)


def docks(station: str, step: int, cal: list[dict] | None = None) -> int:
    if station != DOCKS_ERA[1]:
        return STATIONS[station][1]
    return (cal or _CAL)[step // STEPS_PER_DAY]["bp_docks"]


def closed(station: str, step: int, cal: list[dict] | None = None) -> bool:
    return station == CLOSED[2] and (cal or _CAL)[step // STEPS_PER_DAY]["closed"]


def weekend(step: int) -> bool:
    return (step // STEPS_PER_DAY) % 7 >= 5


def shape(step: int) -> float:
    """Time of day: quiet at night (x0.35), busy in the day, x1.3 in the rush hours on weekdays."""
    h = (step % STEPS_PER_DAY) * STEP_MIN / 60
    up, down = (h - 5.5) / 2, (22 - h) / 2           # ramps 05:30-07:30 and 20:00-22:00
    day = 0.35 + 0.65 * max(0.0, min(1.0, up, down))
    if weekend(step):
        return 0.8 * day
    return day + 0.3 * math.exp(-((h - 8) / 1.0) ** 2) + 0.3 * math.exp(-((h - 17.5) / 1.2) ** 2)


def hazard(station: str, step: int, cal: list[dict] | None = None) -> float:
    return HAZARD[station] * shape(step) * (cal or _CAL)[step // STEPS_PER_DAY]["rain"]


def destinations(station: str, step: int) -> dict[str, float]:
    return WEEKEND_DEST[station] if weekend(step) else DEST[station][period(step)]


def van_working(step: int, cal: list[dict] | None = None) -> bool:
    a, b = VAN_SHIFT[(cal or _CAL)[step // STEPS_PER_DAY]["shift"]]
    h = (step % STEPS_PER_DAY) * STEP_MIN / 60
    return a <= h < b


def counter_ids() -> list[str]:
    """Every per-step counter the recording has (none of them is in the model)."""
    out = [f"rides__{a}__{b}" for a, b in PAIRS]                        # rides started, by planned destination
    out += [f"started__{s}" for s in IDS] + [f"ended__{s}" for s in IDS]
    out += [f"diverted__{s}" for s in IDS]                               # rides that ended here instead of at a full or closed station
    out += [f"loaded__{s}" for s in IDS] + [f"unloaded__{s}" for s in IDS]
    return out


COUNTERS = counter_ids()


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)       # measured stock -> level at the end of each step
    riding: dict[str, list[int]] = field(default_factory=dict)       # "a__b" -> bikes being ridden from a to b (hidden)
    counters: dict[str, list[int]] = field(default_factory=dict)     # counter -> count in each step
    ended_pair: dict[str, list[int]] = field(default_factory=dict)   # "a__b" -> rides from a planned to b that ended this step
    eras: list[dict] = field(default_factory=list)                   # [{t, label}] t = first step of the era
    ride_steps: dict[str, list[int]] = field(default_factory=dict)   # "a__b" -> realised ride lengths, steps (end step - start step)
    van_trips: list[dict] = field(default_factory=list)
    rides: int = 0


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    assert steps >= 1
    cal = calendar(seed, steps)

    def docks_at(station: str, step: int) -> int:
        return docks(station, step, cal)

    def closed_at(station: str, step: int) -> bool:
        return closed(station, step, cal)

    rng = random.Random(seed)
    res = Result(seed=seed, levels={s: [] for s in MEASURED_STOCKS}, riding={f"{a}__{b}": [] for a, b in PAIRS},
                 counters={c: [0] * steps for c in COUNTERS}, ended_pair={f"{a}__{b}": [0] * steps for a, b in PAIRS},
                 ride_steps={f"{a}__{b}": [] for a, b in PAIRS})
    C = res.counters
    level = {s: STATIONS[s][2] for s in IDS}
    level[VAN] = 0
    riding = {f"{a}__{b}": 0 for a, b in PAIRS}
    due: dict[int, list[tuple[str, str]]] = {}                           # step -> rides ending in it
    sig = math.sqrt(math.log(1 + RIDE_CV ** 2))
    van = {"plan": [], "src": None, "dst": None}                       # a run: a list of (step, action)

    def dock(origin: str, dest: str, i: int) -> None:
        key = f"{origin}__{dest}"
        riding[key] -= 1
        res.ended_pair[key][i] += 1
        at = dest
        for _ in range(len(IDS)):
            if not closed_at(at, i) and level[at] < docks_at(at, i):
                break
            at = STATIONS[at][3]
        else:                                                            # nowhere has room: squeeze in at the planned one
            at = dest
        level[at] += 1
        C[f"ended__{at}"][i] += 1
        if at != dest:
            C[f"diverted__{at}"][i] += 1

    def plan_van(i: int) -> None:
        fill = {s: level[s] / docks_at(s, i) for s in IDS if not closed_at(s, i)}
        src = max(fill, key=fill.get)
        dst = min(fill, key=fill.get)
        if level[VAN] == 0 and (fill[src] < VAN_RULES["full_above"] or fill[dst] > VAN_RULES["empty_below"]):
            return                                                       # nothing worth moving this run
        drive = max(2, round(RIDE_MIN[(src, dst)] * VAN_DRIVE_MIN / STEP_MIN))
        loading = level[VAN] == 0 or fill[src] >= VAN_RULES["full_above"]
        van.update(src=src if loading else None, dst=dst, drive=drive, phase="load" if loading else "drive",
                   wait=0 if loading else max(3, round(15 / STEP_MIN)), start=i, loaded=0, unloaded=0)

    def step_van(i: int) -> None:
        if van.get("phase") is None:
            return
        if van["phase"] == "load":
            s = van["src"]
            floor_ = math.ceil(VAN_RULES["load_down_to"] * docks_at(s, i))
            n = min(VAN_RULES["per_step"], VAN_RULES["capacity"] - level[VAN], level[s] - floor_)
            if n > 0:
                level[s] -= n
                level[VAN] += n
                van["loaded"] += n
                C[f"loaded__{s}"][i] += n
            if n < VAN_RULES["per_step"]:                                      # full, or the station is down to half
                van.update(phase="drive", wait=van["drive"])
        elif van["phase"] == "drive":
            van["wait"] -= 1
            if van["wait"] <= 0:
                van["phase"] = "unload"
        elif van["phase"] == "unload":
            d = van["dst"]
            if closed_at(d, i):
                van["dst"] = d = STATIONS[d][3]
            room = math.floor(VAN_RULES["unload_up_to"] * docks_at(d, i)) - level[d]
            n = min(VAN_RULES["per_step"], level[VAN], room)
            if n > 0:
                level[d] += n
                level[VAN] -= n
                van["unloaded"] += n
                C[f"unloaded__{d}"][i] += n
            if n < VAN_RULES["per_step"] or level[VAN] == 0:
                res.van_trips.append({"t": van["start"] + 1, "from": van["src"], "to": d, "loaded": van["loaded"],
                                      "unloaded": van["unloaded"], "left_on_van": level[VAN], "end_t": i + 1})
                van["phase"] = None

    idle_until = 0
    for i in range(steps):
        # rides that end in this step dock first (their bikes left earlier)
        for origin, dest in due.pop(i, []):
            dock(origin, dest, i)
        # the van
        if van.get("phase") is None and (van_working(i, cal) or level[VAN] > 0) and i >= idle_until:
            plan_van(i)
            if van.get("phase") is None:
                idle_until = i + VAN_RULES["idle_steps"]      # nothing worth moving: look again a little later
        step_van(i)
        # new rides: each bike docked at the end of the last step is taken with the station's hazard
        for s in IDS:
            if closed_at(s, i):
                continue
            prev = res.levels[s][-1] if res.levels[s] else STATIONS[s][2]
            avail = min(prev, level[s])
            h = hazard(s, i, cal)
            n = sum(1 for _ in range(avail) if rng.random() < h)
            if not n:
                continue
            shares = destinations(s, i)
            dests, weights = list(shares), list(shares.values())
            for _ in range(n):
                b = rng.choices(dests, weights)[0]
                level[s] -= 1
                key = f"{s}__{b}"
                riding[key] += 1
                C[f"rides__{key}"][i] += 1
                C[f"started__{s}"][i] += 1
                res.rides += 1
                t0 = (i + rng.random()) * STEP_MIN
                dur = rng.lognormvariate(math.log(RIDE_MIN[(s, b)]) - sig * sig / 2, sig)
                end = int((t0 + dur) // STEP_MIN)
                res.ride_steps[key].append(end - i)
                if end < steps:
                    due.setdefault(end, []).append((s, b))
        for s in MEASURED_STOCKS:
            res.levels[s].append(level[s])
        for k in riding:
            res.riding[k].append(riding[k])

    res.eras = [{"t": d * STEPS_PER_DAY + 1, "label": label} for k in range(len(cal) // DAYS)
                for d, label in schedule(seed, k)["eras"] if d * STEPS_PER_DAY < steps]
    return res


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees of a run: the dashboard's stocks every 5 minutes, and the eras."""
    res = cached(seed) if steps == STEPS else run(seed, steps)
    return {"t": list(range(1, steps + 1)), "levels": {s: list(v) for s, v in res.levels.items()},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras],
            "counters": {k: list(v) for k, v in res.counters.items()}}


def riding_total(res: Result) -> list[int]:
    return [sum(v[i] for v in res.riding.values()) for i in range(len(res.levels[VAN]))]


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict."""
    C, L = res.counters, res.levels
    steps = len(L[VAN])
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None   # noqa: E731
    lv_sum = {s: sum(L[s][:-1]) for s in MEASURED_STOCKS}             # Σ level over the steps before (what k multiplies)

    def k_of(counter: list[int], driver: str) -> float:
        return round(sum(counter[1:]) / max(1, lv_sum[driver]), 5)

    hidden = []
    for a, b in PAIRS:
        key = f"{a}__{b}"
        n = sum(C[f"rides__{key}"])
        if not n:
            continue
        rs = res.ride_steps[key]
        hidden.append({"from": a, "to": b, "shape": "pipe", "delay": round(RIDE_MIN[(a, b)] / STEP_MIN, 2),
                       "delay_realised_steps": mean(rs), "delay_minutes": RIDE_MIN[(a, b)], "cv": RIDE_CV,
                       "share": k_of(C[f"rides__{key}"], a), "holds": mean(res.riding[key]),
                       "rides": n, "per_step": round(n / steps, 4),
                       "what": f"bikes ridden from {STATIONS[a][0]} to {STATIONS[b][0]} (some end at a neighbour when it is full or closed)"})
    hidden.sort(key=lambda h: -h["rides"])
    moves = []
    for s in IDS:
        n = sum(C[f"loaded__{s}"])
        if n:
            moves.append({"from": s, "to": VAN, "form": "constant", "value": round(n / steps, 4), "total": n,
                          "k": k_of(C[f"loaded__{s}"], s),
                          "what": f"the van loads bikes at {STATIONS[s][0]} when it is the fullest station (5 a step, during the crew's shift)"})
    for s in IDS:
        n = sum(C[f"unloaded__{s}"])
        if n:
            moves.append({"from": VAN, "to": s, "form": "proportional", "k": k_of(C[f"unloaded__{s}"], VAN), "total": n,
                          "value": round(n / steps, 4),
                          "what": f"the van unloads at {STATIONS[s][0]} when it is the emptiest station"})
    moves.sort(key=lambda m: -m["total"])
    return {
        "seed": res.seed,
        "steps": steps,
        "step": "5 minutes",
        "days": steps // STEPS_PER_DAY,
        "bikes": BIKES,
        "rides": res.rides,
        "stations": {s: {"name": n, "docks": c, "bikes_at_start": b0, "neighbour": nb,
                         "mean_level": mean(L[s]), "min_level": min(L[s]), "max_level": max(L[s]),
                         "rides_started": sum(C[f"started__{s}"]), "rides_ended": sum(C[f"ended__{s}"]),
                         "diverted_here": sum(C[f"diverted__{s}"]),
                         "van_loaded": sum(C[f"loaded__{s}"]), "van_unloaded": sum(C[f"unloaded__{s}"])}
                     for s, (n, c, b0, nb) in STATIONS.items()},
        "ride_minutes": {f"{a}__{b}": m for (a, b), m in RIDE_MIN.items()},
        "hazard": {"per_step": HAZARD,
                   "time_of_day": "x0.35 at night (21:00-05:30), ramping to x1 by 07:30 and back down 20:00-22:00; weekdays add "
                                  "+0.3 exp(-((h-8)/1)^2) + 0.3 exp(-((h-17.5)/1.2)^2) (rush hours); weekends x0.8 of the plain day"},
        "destinations": {"weekday": DEST, "weekend": WEEKEND_DEST},
        "rain_day": {"day": RAIN_DAY[0], "factor": RAIN_DAY[1]},
        "van": {**VAN_RULES, "shift_hours": {"before_day_11": VAN_SHIFT["day"], "from_day_11": VAN_SHIFT["day and late"]},
                "trips": len(res.van_trips), "bikes_moved": sum(x["unloaded"] for x in res.van_trips),
                "mean_level": mean(L[VAN]), "max_level": max(L[VAN]), "trip_log": res.van_trips},
        "eras": res.eras,
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "sd_structure": {
            "note": "In SD Lab terms, per 5-minute step. 'moves' are real stock-to-stock flows (ratio 1): the van's loading "
                    "and unloading (k = total / Σ the source's level over the steps before, the proportional equivalent). "
                    "'hidden': rides. A bike leaves a station (k x its docked bikes per step = share), is ridden for the pair's ride "
                    "time (pipe-like: lognormal, cv 0.2, so delay = mean minutes / 5 steps) in a stock nobody counts, and docks at "
                    "the destination. The share varies a lot through the day (commutes); 'share' is the run's average. "
                    "Nothing leaves the system and nothing enters it: 'outside' and 'links' are empty.",
            "moves": moves,
            "outside": [],
            "links": [],
            "hidden": hidden,
            "echoes": [],
        },
        "riding_total": {"mean": mean(riding_total(res)), "max": max(riding_total(res))},
        "mean_levels": {s: mean(L[s]) for s in MEASURED_STOCKS},
    }


_cache: dict[int, Result] = {}


def cached(seed: int = SEED) -> Result:
    if seed not in _cache:
        _cache[seed] = run(seed)
    return _cache[seed]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED)
    g = ground_truth(r)
    print(json.dumps({"rides": r.rides, "mean_levels": g["mean_levels"], "riding": g["riding_total"],
                      "van_trips": g["van"]["trips"], "van_moved": g["van"]["bikes_moved"],
                      "stations": {s: {k: v[k] for k in ("min_level", "max_level", "rides_started", "diverted_here", "van_loaded", "van_unloaded")}
                                   for s, v in g["stations"].items()}}, indent=1))
