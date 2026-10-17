"""A seeded, stochastic simulation of a flu season in a town of 50,000, day by day for 200 days.

This is the *real system* behind the measured `flu` model. The model is told only the five counts
the town's public-health dashboard shows at the end of every day: susceptible, sick at home, in
hospital, recovered (immune after an illness) and vaccinated. It is never told how people move
between them; that is the answer key (sdlab/examples/flu/README.md, truth.json).

How it works (a chain-binomial model: every transition is a binomial draw from the start-of-day
counts, all applied together at the end of the day, so the town always holds exactly 50,000):

  infection      each susceptible person catches flu with probability 1 - exp(-force), where
                 force = beta(t) x sick / N + import (people catching it outside town); beta(t)
                 drops during school holidays (fewer contacts)
  illness        a new case is mild (97%) or severe (3%). A mild case recovers with a daily
                 probability of 1/5 (geometric, mean 5 days). A severe case gets worse through two
                 stages of mean 1.5 days each (erlang-2-like, mean 3 days) and is then admitted
  hospital       a stay ends with a daily probability of 1/7 (mean 7 days): recovered
  waning         recovered people lose their immunity with a daily probability of 1/120 (months)
  vaccination    from day 60, the clinic vaccinates a fixed daily number of susceptible people
                 (Poisson around its capacity); vaccine immunity lasts the whole season

Long runs (`run(steps=...)`, `measured(steps=...)`, up to years): the first 200 days are always
the season above, draw for draw. The town's year is 365 days; days 201-365 of the first year add
summer holidays. Every later year is a new season with fresh draws (its own random stream, so the
first year never changes): a new strain arrives (contacts x 0.8-1.25 for the year, which only
scales the eras' contact factor), last season's vaccine stops protecting (everyone vaccinated is
susceptible again on the year's first day: the `vaccine_expiry` counter, vaccinated ->
susceptible, which never moves anyone in the first year), school holidays in autumn, spring and
summer, and an autumn vaccination campaign with one clinic and then two (capacities drawn per
year). Waning keeps refilling the susceptible from the recovered, so the epidemic comes back.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field

DAYS = 200
STEPS = DAYS                          # one step is one day
YEAR = 365                            # long runs: a new season every year
LONG_STEPS = 10 * YEAR                # ten years, for the discovery test bed
SEED = 20261016
N = 50_000

MEASURED_STOCKS = ["susceptible", "sick", "hospital", "recovered", "vaccinated"]
# the sick are mild, or severe in one of two stages before admission: one measured stock
SICK_PARTS = ["mild", "severe1", "severe2"]

# every true flow: id -> (from, to); all of them are counted (see COUNTERS)
FLOWS = {
    "infections": ("susceptible", "sick"),
    "recoveries": ("sick", "recovered"),
    "admissions": ("sick", "hospital"),
    "discharges": ("hospital", "recovered"),
    "waning": ("recovered", "susceptible"),
    "vaccinations": ("susceptible", "vaccinated"),
}
COUNTERS = list(FLOWS)
# long runs only: last season's vaccine stops protecting on the first day of each later year
EXPIRY = {"vaccine_expiry": ("vaccinated", "susceptible")}

P = {
    "beta": 0.40,                     # contacts x transmission per day, in term time
    "holiday_contacts": 0.55,         # beta x this during school holidays
    "import_per_day": 4e-5,           # chance a susceptible person catches it outside town, per day
    "p_severe": 0.03,                 # share of cases that end in hospital
    "mild_days": 5.0,                 # exponential: daily hazard 1/5
    "severe_stage_days": 1.5,         # two stages: erlang-2, mean 3 days before admission
    "hospital_days": 7.0,             # exponential
    "immunity_days": 120.0,           # exponential waning of natural immunity
}

INITIAL = {"susceptible": 37_950, "mild": 40, "severe1": 1, "severe2": 1, "hospital": 0,
           "recovered": 12_008, "vaccinated": 0}           # 24% immune from last winter

# (first day, label, contact factor, vaccines a day): the eras
ERAS = [(1, "Term time", 1.0, 0),
        (41, "School holidays: fewer contacts", P["holiday_contacts"], 0),
        (55, "Schools reopen", 1.0, 0),
        (61, "Vaccination campaign: 120 a day", 1.0, 120),
        (101, "Second clinic opens: 200 vaccinations a day", 1.0, 200),
        (121, "Spring holidays: fewer contacts", P["holiday_contacts"], 200),
        (131, "Schools reopen", 1.0, 200),
        (161, "Vaccination campaign ends", 1.0, 0)]


# the first year after day 200 (only long runs get there)
FIRST_SUMMER = [(216, "Summer holidays: fewer contacts", P["holiday_contacts"], 0),
                (256, "Schools reopen", 1.0, 0)]


def era_at(day: int) -> tuple:
    cur = ERAS[0]
    for e in ERAS:
        if day >= e[0]:
            cur = e
    return cur


def year_eras(seed: int, year: int) -> list[tuple]:
    """The eras of year `year` (0 is the first): the first is ERAS and the first summer; every
    later one is a new season drawn from its own stream, `contacts` scaled by the year's strain."""
    if year == 0:
        return ERAS + FIRST_SUMMER
    rng = random.Random(f"flu:{seed}:{year}")
    d0, strain, hol = year * YEAR, round(rng.uniform(0.8, 1.25), 2), P["holiday_contacts"]
    cap1 = rng.choice([80, 100, 120, 150])
    cap2 = cap1 + rng.choice([60, 80, 100])
    autumn = rng.randint(38, 44)
    reopen = autumn + 14
    campaign = reopen + rng.randint(3, 10)
    clinic = campaign + rng.randint(30, 45)
    spring = clinic + rng.randint(15, 25)
    back = spring + 10
    ends = back + rng.randint(25, 35)
    summer = rng.randint(210, 220)
    return [(d0 + 1, f"New season: a new strain (contacts x{strain:g}); last season's vaccine no longer protects", strain, 0),
            (d0 + autumn, "School holidays: fewer contacts", round(hol * strain, 4), 0),
            (d0 + reopen, "Schools reopen", strain, 0),
            (d0 + campaign, f"Vaccination campaign: {cap1} a day", strain, cap1),
            (d0 + clinic, f"Second clinic opens: {cap2} vaccinations a day", strain, cap2),
            (d0 + spring, "Spring holidays: fewer contacts", round(hol * strain, 4), cap2),
            (d0 + back, "Schools reopen", strain, cap2),
            (d0 + ends, "Vaccination campaign ends", strain, 0),
            (d0 + summer, "Summer holidays: fewer contacts", round(hol * strain, 4), 0),
            (d0 + summer + 40, "Schools reopen", strain, 0)]


def schedule(seed: int, steps: int) -> list[tuple]:
    """Every era that starts within `steps` days: (first day, label, contact factor, vaccines a day)."""
    return [e for y in range((steps - 1) // YEAR + 1) for e in year_eras(seed, y) if e[0] <= steps]


def hazard(days: float) -> float:
    """The daily probability of leaving a stage whose mean length is `days` (geometric: the
    whole-day version of exponential)."""
    return 1 / days


def binom(rng: random.Random, n: int, p: float) -> int:
    return rng.binomialvariate(n, p) if n > 0 and p > 0 else 0


def poisson(rng: random.Random, lam: float) -> int:
    """Poisson by a fine binomial (stdlib has no Poisson draw)."""
    return binom(rng, int(lam * 20), 0.05) if lam > 0 else 0


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)    # stock (measured and parts) -> end-of-day level
    counters: dict[str, list[int]] = field(default_factory=dict)  # flow -> people moved that day
    force: list[float] = field(default_factory=list)              # the infection force each day
    eras: list[dict] = field(default_factory=list)


def flows(steps: int = STEPS) -> dict:
    """The true flows a run of `steps` days counts: the vaccine expires only in long runs."""
    return FLOWS | (EXPIRY if steps > YEAR else {})


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    assert steps >= 1
    rng = random.Random(seed)
    x = dict(INITIAL)
    parts = ["susceptible", *SICK_PARTS, "hospital", "recovered", "vaccinated"]
    res = Result(seed=seed, levels={s: [] for s in [*MEASURED_STOCKS, *SICK_PARTS]}, counters={f: [] for f in flows(steps)})
    eras = schedule(seed, steps)
    era = iter(eras[1:])
    cur, nxt = eras[0], next(era, None)
    for day in range(1, steps + 1):
        if nxt and day >= nxt[0]:
            cur, nxt = nxt, next(era, None)
        _, _, contacts, vaccines = cur
        expiry = x["vaccinated"] if day % YEAR == 1 and day > 1 else 0
        sick = x["mild"] + x["severe1"] + x["severe2"]
        force = P["beta"] * contacts * sick / N + P["import_per_day"]
        res.force.append(force)
        infections = binom(rng, x["susceptible"], 1 - math.exp(-force))
        severe = binom(rng, infections, P["p_severe"])
        vaccinations = min(poisson(rng, vaccines), x["susceptible"] - infections)
        recoveries = binom(rng, x["mild"], hazard(P["mild_days"]))
        worse = binom(rng, x["severe1"], hazard(P["severe_stage_days"]))
        admissions = binom(rng, x["severe2"], hazard(P["severe_stage_days"]))
        discharges = binom(rng, x["hospital"], hazard(P["hospital_days"]))
        waning = binom(rng, x["recovered"], hazard(P["immunity_days"]))
        x["susceptible"] += waning - infections - vaccinations + expiry
        x["mild"] += infections - severe - recoveries
        x["severe1"] += severe - worse
        x["severe2"] += worse - admissions
        x["hospital"] += admissions - discharges
        x["recovered"] += recoveries + discharges - waning
        x["vaccinated"] += vaccinations - expiry
        assert sum(x[p] for p in parts) == N and min(x.values()) >= 0, (day, x)
        for f, v in (("infections", infections), ("recoveries", recoveries), ("admissions", admissions),
                     ("discharges", discharges), ("waning", waning), ("vaccinations", vaccinations)):
            res.counters[f].append(v)
        if "vaccine_expiry" in res.counters:
            res.counters["vaccine_expiry"].append(expiry)
        x["sick"] = x["mild"] + x["severe1"] + x["severe2"]
        for s in res.levels:
            res.levels[s].append(x[s])
        del x["sick"]
    res.eras = [{"t": d, "label": label} for d, label, _, _ in eras]
    return res


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees over `steps` days: the dashboard's five counts (what history.py prints for
    the default length), the eras, and the simulator's daily counter of every true flow."""
    res = run(seed, steps)
    return {"t": list(range(1, steps + 1)), "levels": {s: res.levels[s] for s in MEASURED_STOCKS},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras], "counters": res.counters}


def fit_k(flow: list[int], level: list[int], lag: int = 0, days=None) -> float:
    """Least-squares k in flow(day) = k x level(day - 1 - lag), over `days` (all by default): what a
    proportional equation would read."""
    days = days or range(2 + lag, len(flow) + 1)
    pairs = [(flow[d - 1], level[d - 2 - lag]) for d in days if d >= 2 + lag]
    den = sum(b * b for _, b in pairs)
    return round(sum(a * b for a, b in pairs) / den, 5) if den else 0.0


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict."""
    C, L = res.counters, res.levels
    mean = lambda xs: round(sum(xs) / len(xs), 3)                    # noqa: E731
    total = {f: sum(v) for f, v in C.items()}
    # the linear reading of infection: the force is beta x S / N per sick person, and S moves slowly
    s_mean = mean(L["susceptible"])
    k_inf = fit_k(C["infections"], L["sick"])
    vacc_eras = [{"from_day": d, "per_day": v, "label": lab} for d, lab, _, v in ERAS]
    contacts = [{"from_day": d, "contact_factor": c, "label": lab} for d, lab, c, _ in ERAS]
    era_k = []
    for i, (d, lab, c, _) in enumerate(ERAS):
        end = ERAS[i + 1][0] if i + 1 < len(ERAS) else DAYS + 1
        days = range(max(2, d), end)
        s = sum(L["susceptible"][t - 2] for t in days) / len(days)
        era_k.append({"from_day": d, "label": lab, "beta": round(P["beta"] * c, 4), "mean_susceptible": round(s),
                      "k_per_sick": round(P["beta"] * c * s / N, 4),
                      "k_fitted": fit_k(C["infections"], L["sick"], days=days)})
    mild_share = 1 - P["p_severe"]
    sick_days = mild_share * P["mild_days"] + P["p_severe"] * 2 * P["severe_stage_days"]
    sd = {
        "note": "In SD Lab terms, per day. 'moves' are real flows between measured stocks (ratio 1). Infection is "
                "nonlinear: susceptible -> sick at beta x S x sick / N per day; while S changes slowly a linear "
                "discovery should read it as k x sick (a term on the TARGET's level), k = beta x S / N, lower in "
                "holidays and falling as S falls (k per era in infection_by_era). sick -> hospital waits ~3 days inside "
                "the measured sick stock (erlang-2), so it shows as a lagged proportional drain of sick, not as a hidden "
                "stock. Nothing enters or leaves the town: no flows to or from outside, no hidden stocks, no echoes.",
        "moves": [
            {"from": "susceptible", "to": "sick", "form": "linear in the target (nonlinear in truth)",
             "equation": "beta x susceptible x sick / N + import x susceptible", "beta": P["beta"],
             "beta_in_holidays": round(P["beta"] * P["holiday_contacts"], 4), "N": N,
             "k": round(P["beta"] * s_mean / N, 4), "k_fitted": k_inf, "term": "sick (the target)",
             "import_per_day": round(P["import_per_day"] * s_mean, 2),
             "what": "infection: a rate that follows the number sick"},
            {"from": "sick", "to": "recovered", "form": "proportional", "k": round(hazard(P["mild_days"]) * mild_share * P["mild_days"] / sick_days, 4),
             "k_fitted": fit_k(C["recoveries"], L["sick"]), "hazard_mild": round(hazard(P["mild_days"]), 4),
             "what": "mild cases recover (exponential, ~5 days)"},
            {"from": "sick", "to": "hospital", "form": "proportional (lagged ~3 days)", "k": round(P["p_severe"] / sick_days, 5),
             "k_fitted": fit_k(C["admissions"], L["sick"]), "k_fitted_3_day_lag": fit_k(C["admissions"], L["sick"], 3),
             "delay": 2 * P["severe_stage_days"], "shape": "erlang", "share_of_cases": P["p_severe"],
             "what": "severe cases are admitted ~3 days after falling ill"},
            {"from": "hospital", "to": "recovered", "form": "proportional", "k": round(hazard(P["hospital_days"]), 4),
             "k_fitted": fit_k(C["discharges"], L["hospital"]), "what": "hospital stays end (exponential, ~7 days)"},
            {"from": "recovered", "to": "susceptible", "form": "proportional", "k": round(hazard(P["immunity_days"]), 5),
             "k_fitted": fit_k(C["waning"], L["recovered"]), "what": "natural immunity wanes (exponential, ~120 days)"},
            {"from": "susceptible", "to": "vaccinated", "form": "constant", "value": "per era: 0, 120, 200, 0",
             "per_era": vacc_eras, "what": "vaccination campaign at the clinics' daily capacity"},
        ],
        "outside": [],
        "links": [],
        "hidden": [],
        "echoes": [],
        "infection_by_era": era_k,
        # runs longer than a year also have this one: protection wears off on each new year's first day
        "in_long_runs": {"moves": [{"from": "vaccinated", "to": "susceptible", "form": "yearly pulse",
                                    "what": "vaccine protection wears off on the first day of each year after the first"}]},
    }
    return {
        "seed": res.seed,
        "steps": STEPS,
        "step": "1 day",
        "population": N,
        "parameters": P,
        "initial": INITIAL,
        "eras": res.eras,
        "contacts": contacts,
        "measured": {"stocks": MEASURED_STOCKS, "flows": []},
        "counters": {f: {"from": a, "to": b, "total": total[f], "per_day_mean": round(total[f] / STEPS, 3)}
                     for f, (a, b) in FLOWS.items()},
        "sd_structure": sd,
        "mean_levels": {s: mean(L[s]) for s in MEASURED_STOCKS},
        "max_levels": {s: max(L[s]) for s in MEASURED_STOCKS},
        "peak_sick_day": L["sick"].index(max(L["sick"])) + 1,
        "attack": {"infections": total["infections"], "share_of_town": round(total["infections"] / N, 4)},
    }


_cache: dict[tuple[int, int], Result] = {}


def cached(seed: int = SEED, steps: int = STEPS) -> Result:
    if (seed, steps) not in _cache:
        _cache[seed, steps] = run(seed, steps)
    return _cache[seed, steps]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED)
    g = ground_truth(r)
    print(json.dumps({k: g[k] for k in ("mean_levels", "max_levels", "peak_sick_day", "attack", "counters")}, indent=1))
    for i in range(0, STEPS, 10):
        print(i + 1, {s: r.levels[s][i] for s in MEASURED_STOCKS})
