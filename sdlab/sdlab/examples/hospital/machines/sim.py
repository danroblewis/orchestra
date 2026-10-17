"""A seeded, per-patient simulation of a hospital's emergency department and ward over 60 days.

This is the *real system* behind the measured `hospital` model. The model is told about five
stocks a dashboard shows (Waiting room, In treatment, Ward, Discharged home, Left without being
seen) and two counters (new registrations, admissions from the ED). Three more places hold
patients, and nothing measures them:

  imaging   ordered at triage: a patient leaves the Waiting room for radiology and comes back
            straight into a treatment bed about 2 hours later (uniform 1.75-2.25 h: a pipeline)
  lab       blood work sent out during treatment: the patient leaves the bed for the results
            lounge (exponential, mean 4 h); on the results 65% come back to a treatment bed and
            35% are admitted straight to the Ward (one outflow, two delayed returns)
  followup  released with a booked review: the patient leaves In treatment and comes back to the
            Waiting room days later (lognormal, mean 120 h, sd 36 h)

Everything is discrete-event in continuous hours; `run()` cuts it into 1-hour steps and returns
the end-of-step level of every stock and the count of every true flow in every step.

    python sim.py [seed]          prints a summary of one run
"""

from __future__ import annotations

import heapq
import json
import math
import random
import sys
from dataclasses import dataclass, field

DAYS = 60
STEPS = DAYS * 24                     # one step is one hour
SEED = 20261016

MEASURED_STOCKS = ["waiting", "treatment", "ward", "discharged", "lwbs"]
HIDDEN_STOCKS = ["imaging", "lab", "followup"]
STOCKS = MEASURED_STOCKS + HIDDEN_STOCKS
MEASURED_FLOWS = ["arrivals", "admissions"]

# every true flow: id -> (from, to); None is outside
FLOWS = {
    "arrivals": (None, "waiting"),            # new patients registering (measured)
    "start": ("waiting", "treatment"),        # a bed is free: treatment starts
    "abandon": ("waiting", "lwbs"),           # gave up waiting
    "to_imaging": ("waiting", "imaging"),     # hidden
    "imaging_back": ("imaging", "treatment"),  # hidden
    "to_lab": ("treatment", "lab"),           # hidden
    "lab_back": ("lab", "treatment"),         # hidden
    "lab_admit": ("lab", "ward"),             # hidden
    "admissions": ("treatment", "ward"),      # admitted from a bed (measured)
    "discharge": ("treatment", "discharged"),
    "to_followup": ("treatment", "followup"),  # hidden
    "followup_back": ("followup", "waiting"),  # hidden
    "ward_discharge": ("ward", "discharged"),
}

P = {
    "base_arrivals_per_hour": 4.0,
    "p_imaging": 0.20,                 # of new patients, imaging ordered at triage
    "triage_hours": (0.1, 0.6),        # uniform: time in the waiting room before going to radiology
    "imaging_hours": (1.75, 2.25),     # uniform: the pipeline
    "p_lab": 0.30,                     # of first visits that start treatment, blood work sent out
    "lab_mean_hours": 4.0,             # exponential
    "p_lab_admit": 0.35,               # on results: straight to the ward; else back to a bed
    "first_part_mean_hours": 1.0,      # exponential: treatment before the bloods are sent
    "treat_mean_hours": 2.5,           # lognormal mean (sd 1.5 h): a treatment (or what remains of one)
    "treat_sd_hours": 1.5,
    "p_admit": 0.22,                   # disposition after treatment
    "p_followup": 0.12,                # first visits only; returning patients are never booked again
    "followup_mean_hours": 120.0,      # lognormal
    "followup_sd_hours": 36.0,
    "patience_mean_hours": 8.0,        # exponential: waiting this long, a patient walks out
    "ward_mean_hours": 96.0,           # lognormal length of stay (sd 60 h); discharges 08:00-20:00
    "ward_sd_hours": 60.0,
}

# staffed ED beds by day: the eras. Patients returning from imaging or the lab always get a bed
# (a corridor trolley if need be); new treatment starts only while fewer beds are occupied.
BEDS = [(0, 16, "16 staffed ED beds"),
        (15, 12, "Staff sickness: 12 staffed ED beds"),
        (23, 16, "Back to 16 staffed ED beds"),
        (32, 20, "Flu-season staffing: 20 ED beds"),
        (50, 16, "Back to 16 staffed ED beds")]

SURGES = [(20 * 24 + 14, 1.5, 18, "bus crash"),          # (hour, over how many hours, extra patients)
          (44 * 24 + 9, 1.0, 10, "chemical leak")]
HEAT = (38 * 24 + 10, 38 * 24 + 22, 1.8)                 # a heat wave: arrivals x1.8 for 12 hours
FLU = (25 * 24, 45 * 24, 0.35)                           # flu season: ramps up to +35% and back


def arrival_rate(h: float) -> float:
    """New patients per hour at hour h (not counting surges)."""
    hod, dow = h % 24, int(h // 24) % 7                  # day 0 is a Monday
    daily = 1 + 0.6 * math.sin(2 * math.pi * (hod - 8) / 24) + 0.15 * math.sin(4 * math.pi * (hod - 10) / 24)
    weekly = [1.15, 1.05, 1.0, 1.0, 1.0, 0.9, 0.9][dow]
    a, b, amp = FLU
    flu = 1 + amp * max(0.0, math.sin(math.pi * (h - a) / (b - a))) if a <= h <= b else 1.0
    heat = HEAT[2] if HEAT[0] <= h < HEAT[1] else 1.0
    return P["base_arrivals_per_hour"] * max(0.15, daily) * weekly * flu * heat


def beds_at(h: float) -> int:
    n = BEDS[0][1]
    for day, beds, _ in BEDS:
        if h >= day * 24:
            n = beds
    return n


def lognormal(rng: random.Random, mean: float, sd: float) -> float:
    s2 = math.log(1 + (sd / mean) ** 2)
    return rng.lognormvariate(math.log(mean) - s2 / 2, math.sqrt(s2))


@dataclass
class Patient:
    pid: int
    where: str
    first_visit: bool = True
    lab_done: bool = False
    imaging: bool = False
    queued_at: float = 0.0


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)       # stock -> end-of-step level, steps 1..STEPS
    flows: dict[str, list[int]] = field(default_factory=dict)        # flow -> count in each step
    eras: list[dict] = field(default_factory=list)                   # [{t, label}] t = first step of the era
    delays: dict[str, list[float]] = field(default_factory=dict)     # every realised delay, hours
    patients: int = 0


def run(seed: int = SEED) -> Result:
    rng = random.Random(seed)
    ev: list[tuple[float, int, int, str, int]] = []   # (time, ticks first, order, kind, patient)
    seq = 0

    def at(t: float, kind: str, pid: int = -1) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, 0 if kind == "tick" else 1, seq, kind, pid))

    horizon = float(STEPS)
    patients: dict[int, Patient] = {}
    level = {s: 0 for s in STOCKS}
    queue: list[int] = []                                            # FIFO of patients waiting for a bed
    res = Result(seed=seed, levels={s: [] for s in STOCKS}, flows={f: [0] * STEPS for f in FLOWS},
                 delays={"imaging": [], "lab": [], "followup": []})

    # arrivals: thinning of the non-homogeneous Poisson process, plus the surges
    lam_max = P["base_arrivals_per_hour"] * 1.8 * 1.15 * 1.35 * HEAT[2]
    t = 0.0
    while True:
        t += rng.expovariate(lam_max)
        if t >= horizon:
            break
        if rng.random() < arrival_rate(t) / lam_max:
            at(t, "arrive")
    for h, span, n, _ in SURGES:
        for _ in range(n):
            at(h + rng.uniform(0, span), "arrive")
    for day, _, _ in BEDS[1:]:
        at(day * 24.0, "beds")
    for k in range(1, STEPS + 1):
        at(float(k), "tick")

    def move(p: Patient, to: str, flow: str, now: float) -> None:
        assert FLOWS[flow] == (p.where if p.where in STOCKS else None, to), (flow, p.where, to)
        if p.where in STOCKS:
            level[p.where] -= 1
        level[to] += 1
        p.where = to
        res.flows[flow][min(STEPS - 1, int(now))] += 1

    def occupied() -> int:
        return level["treatment"]

    def start_treatments(now: float) -> None:
        while queue and occupied() < beds_at(now):
            p = patients[queue.pop(0)]
            move(p, "treatment", "start", now)
            begin_treatment(p, now)

    def begin_treatment(p: Patient, now: float) -> None:
        if p.first_visit and not p.lab_done and rng.random() < P["p_lab"]:
            at(now + rng.expovariate(1 / P["first_part_mean_hours"]), "send_lab", p.pid)
        else:
            at(now + lognormal(rng, P["treat_mean_hours"], P["treat_sd_hours"]), "done", p.pid)

    def wait(p: Patient, now: float) -> None:
        p.queued_at = now
        queue.append(p.pid)
        at(now + rng.expovariate(1 / P["patience_mean_hours"]), "patience", p.pid)

    def hour_of_ward_discharge(now: float) -> float:
        t = now + lognormal(rng, P["ward_mean_hours"], P["ward_sd_hours"])
        hod = t % 24
        if hod < 8:
            t += 8 - hod + rng.uniform(0, 4)
        elif hod >= 20:
            t += 24 - hod + 8 + rng.uniform(0, 4)
        return t

    while ev:
        now, _, _, kind, pid = heapq.heappop(ev)
        if kind == "tick":
            for s in STOCKS:
                res.levels[s].append(level[s])
            continue
        if now >= horizon:
            continue
        p = patients.get(pid)
        if kind == "arrive":
            p = patients[len(patients)] = Patient(pid=len(patients), where="outside")
            move(p, "waiting", "arrivals", now)
            if rng.random() < P["p_imaging"]:
                p.imaging = True                     # waits for the porter, not for a bed
                at(now + rng.uniform(*P["triage_hours"]), "send_imaging", p.pid)
            else:
                wait(p, now)
                start_treatments(now)
        elif kind == "send_imaging":
            move(p, "imaging", "to_imaging", now)
            d = rng.uniform(*P["imaging_hours"])
            res.delays["imaging"].append(d)
            at(now + d, "imaging_back", p.pid)
        elif kind == "imaging_back":
            move(p, "treatment", "imaging_back", now)
            begin_treatment(p, now)
        elif kind == "patience":
            if p.where == "waiting" and pid in queue:
                queue.remove(pid)
                move(p, "lwbs", "abandon", now)
        elif kind == "send_lab":
            p.lab_done = True
            move(p, "lab", "to_lab", now)
            d = rng.expovariate(1 / P["lab_mean_hours"])
            res.delays["lab"].append(d)
            at(now + d, "lab_back", p.pid)
            start_treatments(now)
        elif kind == "lab_back":
            if rng.random() < P["p_lab_admit"]:
                move(p, "ward", "lab_admit", now)
                at(hour_of_ward_discharge(now), "ward_out", p.pid)
            else:
                move(p, "treatment", "lab_back", now)
                begin_treatment(p, now)
        elif kind == "done":
            u = rng.random()
            if u < P["p_admit"]:
                move(p, "ward", "admissions", now)
                at(hour_of_ward_discharge(now), "ward_out", p.pid)
            elif p.first_visit and u < P["p_admit"] + P["p_followup"]:
                move(p, "followup", "to_followup", now)
                d = lognormal(rng, P["followup_mean_hours"], P["followup_sd_hours"])
                res.delays["followup"].append(d)
                at(now + d, "followup_back", p.pid)
            else:
                move(p, "discharged", "discharge", now)
            start_treatments(now)
        elif kind == "followup_back":
            p.first_visit, p.lab_done, p.imaging = False, False, False
            move(p, "waiting", "followup_back", now)
            wait(p, now)
            start_treatments(now)
        elif kind == "ward_out":
            move(p, "discharged", "ward_discharge", now)
        elif kind == "beds":
            start_treatments(now)

    res.patients = len(patients)
    res.eras = [{"t": int(day * 24) + 1, "label": label} for day, _, label in BEDS]
    return res


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict."""
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None   # noqa: E731
    levels = res.levels
    hidden_flows = {f: v for f, v in FLOWS.items() if f not in MEASURED_FLOWS}
    lab_out = sum(res.flows["lab_back"]) + sum(res.flows["lab_admit"])
    return {
        "seed": res.seed,
        "steps": STEPS,
        "step": "1 hour",
        "patients": res.patients,
        "parameters": P,
        "beds": [{"day": d, "beds": b, "label": lab} for d, b, lab in BEDS],
        "surges": [{"hour": h, "over_hours": s, "patients": n, "what": w} for h, s, n, w in SURGES],
        "measured": {"stocks": MEASURED_STOCKS, "flows": MEASURED_FLOWS},
        "hidden_stocks": {
            "imaging": {"between": {"out_of": "waiting", "into": ["treatment"]},
                        "out_flow": "to_imaging", "in_flows": ["imaging_back"],
                        "delay": {"dist": "uniform", "low": P["imaging_hours"][0], "high": P["imaging_hours"][1],
                                  "mean": sum(P["imaging_hours"]) / 2, "realised_mean": mean(res.delays["imaging"])},
                        "kind": "pipeline (fixed delay)", "mean_level": mean(levels["imaging"]), "max_level": max(levels["imaging"])},
            "lab": {"between": {"out_of": "treatment", "into": ["treatment", "ward"]},
                    "out_flow": "to_lab", "in_flows": ["lab_back", "lab_admit"],
                    "delay": {"dist": "exponential", "mean": P["lab_mean_hours"], "realised_mean": mean(res.delays["lab"])},
                    "branch_shares": {"treatment": round(sum(res.flows["lab_back"]) / max(1, lab_out), 4),
                                      "ward": round(sum(res.flows["lab_admit"]) / max(1, lab_out), 4),
                                      "probabilities": {"treatment": 1 - P["p_lab_admit"], "ward": P["p_lab_admit"]}},
                    "kind": "first-order (drained in proportion to its level)", "mean_level": mean(levels["lab"]), "max_level": max(levels["lab"])},
            "followup": {"between": {"out_of": "treatment", "into": ["waiting"]},
                         "out_flow": "to_followup", "in_flows": ["followup_back"],
                         "delay": {"dist": "lognormal", "mean": P["followup_mean_hours"], "sd": P["followup_sd_hours"],
                                   "realised_mean": mean(res.delays["followup"])},
                         "kind": "higher-order delay (lognormal, cv 0.3)", "mean_level": mean(levels["followup"]), "max_level": max(levels["followup"])},
        },
        "flows": {f: {"from": a, "to": b, "measured": f in MEASURED_FLOWS, "total": sum(res.flows[f]),
                      "per_step_mean": round(sum(res.flows[f]) / STEPS, 4), "per_step": res.flows[f]}
                  for f, (a, b) in FLOWS.items()},
        "unmeasured_flows": sorted(hidden_flows),
        "levels": levels,
        "mean_levels": {s: mean(levels[s]) for s in STOCKS},
        "eras": res.eras,
    }


_cache: dict[int, Result] = {}


def cached(seed: int = SEED) -> Result:
    if seed not in _cache:
        _cache[seed] = run(seed)
    return _cache[seed]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED)
    g = ground_truth(r)
    print(json.dumps({"patients": r.patients, "mean_levels": g["mean_levels"],
                      "totals": {f: v["total"] for f, v in g["flows"].items()},
                      "hidden": {k: {"mean_level": v["mean_level"], "delay": v["delay"]} for k, v in g["hidden_stocks"].items()}}, indent=1))
