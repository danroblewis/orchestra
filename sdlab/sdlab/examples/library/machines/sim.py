"""A seeded, per-book simulation of a public library over one year, in daily steps.

This is the *real system* behind the measured `library` model. The model is told only what the
circulation dashboard shows at the end of every day: books on the shelves, books on loan, books in
the return bin, books on the hold shelf, and reservations waiting (one per book requested). One
more place holds books and nothing counts it:

  van       interlibrary loans: a reservation for a title the library does not own leaves the
            waiting list when the request is sent (weekdays), and the book arrives on the hold
            shelf 4 to 6 days later (uniform; a Sunday arrival waits for Monday), after riding
            in the shared delivery van.

How it works (one step is one day; day 0 is Monday 1 January; closed on 1 January, 25-26 December
and for a renovation week; interlibrary requests go out on weekdays only):

  borrowing     each book on the shelves in the morning is borrowed that day with a chance that
                follows the season and the weekday (summer reading, exam weeks; Saturdays are
                busy, Sundays have short hours)
  loans         a loan lasts up to the loan period (21 days, 28 from 1 July): most come back
                somewhere in the second half of it, some on the last days, 12% late (overdue by
                an exponential 12 days). Returns go into the book drop every day, open or not.
  return bin    staff reshelve each book in the bin with probability 0.6 per open day (it waited
                at least overnight); interlibrary books go back to their owner instead.
  reservations  placed online every day (more in exam weeks). 70% are for titles on our shelves:
                staff pull the book to the hold shelf with probability 0.5 per open day. 30% are
                interlibrary loans (the van, above), sent with probability 0.4 per weekday.
  hold shelf    the patron collects the book with probability 0.3 per open day; after 8 open
                days uncollected it goes back to the shelves (or back to its owner).
  acquisitions  about 8 new books a day reach the shelves on weekdays.

The year starts mid-stream: the same rules (without the year's seasons) run for 150 days first.

Long runs (`run(seed, steps)` with steps > 365): the calendar repeats every 365 days (day 365 is
the next 1 January; weekdays keep counting, so the years start on different weekdays). Each year
has the same holidays, summer reading, exam weeks and a closed week (days 300-306 of the year: the
renovation in the first year, the annual stocktake after it), and the loan period alternates
within the year: 3 weeks from 1 January, 4 weeks from 1 July (from the second year on, "Loan
period back to 3 weeks" is an era on 1 January). The random draws simply continue, so every year
differs; the first 365 days are exactly the default run.

    python sim.py [seed] [steps]  prints a summary of one run
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import deque
from dataclasses import dataclass, field

DAYS = 365                            # one year: the calendar repeats every DAYS days
STEPS = DAYS                          # one step is one day; day 0 is Monday 1 January
LONG_STEPS = 10 * DAYS                # ten years, for long discovery runs
SEED = 20261016
WARMUP = 150

MEASURED_STOCKS = ["reservations", "shelves", "hold_shelf", "on_loan", "return_bin"]
HIDDEN_STOCKS = ["van"]
STOCKS = MEASURED_STOCKS + HIDDEN_STOCKS
MEASURED_FLOWS: list[str] = []

# every true flow: id -> (from, to); None is outside. reservations and books are counted alike:
# one reservation is one book requested.
FLOWS = {
    "acquire": (None, "shelves"),                 # new books
    "borrow": ("shelves", "on_loan"),             # a patron takes a book off the shelf
    "pull": ("shelves", "hold_shelf"),            # staff pull a reserved book
    "pickup": ("hold_shelf", "on_loan"),          # the patron collects a reserved book
    "expire": ("hold_shelf", "shelves"),          # uncollected: back to the shelves
    "expire_ill": ("hold_shelf", None),           # uncollected interlibrary book: back to its owner
    "return": ("on_loan", "return_bin"),          # into the book drop
    "reshelve": ("return_bin", "shelves"),
    "send_back": ("return_bin", None),            # an interlibrary book goes back to its owner
    "reserve": (None, "reservations"),            # a reservation is placed
    "fill": ("reservations", None),               # a local reservation is filled (its book was pulled)
    "ill_request": ("reservations", "van"),       # hidden: an interlibrary request is sent
    "ill_arrive": ("van", "hold_shelf"),          # hidden: the book arrives
}

# the flows the dashboard could count: none goes into or out of the van
COUNTERS = [f for f, (a, b) in FLOWS.items() if a not in HIDDEN_STOCKS and b not in HIDDEN_STOCKS]

P = {
    "collection": 16000,              # books the library owns at the start of the warm-up
    "borrow_share": 0.032,            # each book on the shelves is borrowed with this chance a day (before season and weekday)
    "weekday": [0.95, 1.0, 1.0, 1.0, 1.05, 1.2, 0.8],    # Monday .. Sunday (short hours)
    "loan_days": 21, "loan_days_extended": 28,
    "p_late": 0.12, "late_mean_days": 12.0,
    "p_last_days": 0.13,              # returned in the last 3 days of the loan period
    "early_from": 0.35,               # else uniform between 0.35 and 1.0 of the loan period
    "p_reshelve": 0.6,                # per open day, each book in the bin
    "reserve_per_day": 45.0,          # every day, online
    "p_ill": 0.30,                    # of reservations: a title we do not own
    "p_pull": 0.5,                    # per open day, each local reservation waiting
    "p_ill_send": 0.4,                # per weekday, each interlibrary reservation waiting
    "van_days": (4, 6),               # uniform whole days in the van
    "p_pickup": 0.3,                  # per open day, each book on the hold shelf
    "hold_open_days": 8,              # uncollected after this many open days: back
    "acquire_per_weekday": 8.0,
}

# the calendar, in days of the year (0 = 1 January); it repeats every year
EXTENDED_FROM = 182                   # 1 July: loans last 4 weeks instead of 3 (back to 3 on 1 January)
RENOVATION = (300, 307)               # closed from day 300 (Saturday 27 October) to day 306
HOLIDAYS = {0, 359, 360}              # 1 January, 25 and 26 December
SUMMER = (166, 244, 0.45)             # summer reading: borrowing +45% (mid-June to August)
EXAMS = [(105, 152, 0.6, 0.15), (335, 355, 0.6, 0.15)]   # (from, to, reservations +, borrowing +)
ERAS = [(0, "Start"),
        (EXTENDED_FROM, "Loan period extended to 4 weeks"),
        (RENOVATION[0], "Closed for renovation"),
        (RENOVATION[1], "Reopened after renovation")]
LATER_ERAS = [(0, "Loan period back to 3 weeks"),            # every year after the first
              (EXTENDED_FROM, "Loan period extended to 4 weeks"),
              (RENOVATION[0], "Closed for the annual stocktake"),
              (RENOVATION[1], "Reopened after the stocktake")]


def eras(steps: int = STEPS) -> list[tuple[int, str]]:
    """(first day, label) of every era in a run of `steps` days: the first year's, then each later year's."""
    out = list(ERAS)
    for y in range(1, (steps + DAYS - 1) // DAYS):
        out += [(y * DAYS + d, label) for d, label in LATER_ERAS]
    return [(d, label) for d, label in out if d < steps]


def weekday(day: int) -> int:
    return day % 7                    # 0 = Monday (day 0 is Monday 1 January; warm-up days are negative)


def doy(day: int) -> int:
    return day % DAYS                 # day of the year (only used for days >= 0)


def is_open(day: int) -> bool:
    return day < 0 or (doy(day) not in HOLIDAYS and not RENOVATION[0] <= doy(day) < RENOVATION[1])


def smooth(day: int, a: int, b: int) -> float:
    """1 inside [a, b), ramping over a week at each end."""
    return max(0.0, min(1.0, (day - a + 1) / 7, (b - day) / 7))


def borrow_share(day: int) -> float:
    if not is_open(day):
        return 0.0
    f = 1.0
    if day >= 0:
        d = doy(day)
        f += SUMMER[2] * smooth(d, SUMMER[0], SUMMER[1])
        f += sum(br * smooth(d, a, b) for a, b, _, br in EXAMS)
        f *= 1 + 0.08 * math.cos(2 * math.pi * (day - 15) / 365)     # darker months read a little more
    return P["borrow_share"] * P["weekday"][weekday(day)] * f


def reserve_rate(day: int) -> float:
    f = 1.0
    if day >= 0:
        d = doy(day)
        f += sum(rr * smooth(d, a, b) for a, b, rr, _ in EXAMS) + 0.25 * smooth(d, SUMMER[0], SUMMER[1])
    return P["reserve_per_day"] * f


def loan_days(day: int) -> int:
    return P["loan_days_extended"] if day >= 0 and doy(day) >= EXTENDED_FROM else P["loan_days"]


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    n, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return n
        n += 1


def binomial(rng: random.Random, n: int, p: float) -> int:
    if n <= 0 or p <= 0:
        return 0
    if n > 200:
        return max(0, min(n, round(rng.gauss(n * p, math.sqrt(n * p * (1 - p))))))
    return sum(1 for _ in range(n) if rng.random() < p)


@dataclass
class Result:
    seed: int
    levels: dict[str, list[int]] = field(default_factory=dict)   # stock -> end-of-day level, days 1..steps
    flows: dict[str, list[int]] = field(default_factory=dict)    # flow -> count each day
    eras: list[dict] = field(default_factory=list)               # [{t, label}] t = first step of the era
    loan_lengths: dict[str, list[int]] = field(default_factory=dict)   # "21" / "28" -> realised loan days (loans that ended in the run)
    van_days: list[int] = field(default_factory=list)            # realised days in the van
    start: dict[str, int] = field(default_factory=dict)          # levels at the end of the warm-up (before day 1)


def run(seed: int = SEED, steps: int = STEPS) -> Result:
    """`steps` days (any length >= 1; the calendar repeats yearly). The default is the one-year run."""
    assert steps >= 1
    rng = random.Random(seed)
    res = Result(seed=seed, levels={s: [] for s in STOCKS}, flows={f: [0] * steps for f in FLOWS},
                 loan_lengths={"21": [], "28": []})
    level = {s: 0 for s in STOCKS}
    level["shelves"] = P["collection"]
    loan_start: dict[int, list[tuple[int, int, bool]]] = {}   # return day -> [(borrowed on, loan period, ill)]
    bin_ = {"own": 0, "ill": 0}
    hold: deque[list] = deque()                  # [open days on the shelf, own, ill]
    waiting = {"local": 0, "ill": 0}
    van: dict[int, int] = {}                     # arrival day -> books
    count: dict[str, int] = {}

    def flow(name: str, n: int, day: int) -> None:
        if n <= 0:
            return
        a, b = FLOWS[name]
        if a:
            level[a] -= n
        if b:
            level[b] += n
        assert a is None or level[a] >= 0, (name, day, level)
        if day >= 0:
            res.flows[name][day] += n
        count[name] = count.get(name, 0) + n

    def lend(n_own: int, n_ill: int, day: int, source: str) -> None:
        """n books leave `source` on loan; each gets its return day."""
        flow(source, n_own + n_ill, day)
        D = loan_days(day)
        for ill in [False] * n_own + [True] * n_ill:
            u = rng.random()
            if u < P["p_late"]:
                d = D + 1 + int(rng.expovariate(1 / P["late_mean_days"]))
            elif u < P["p_late"] + P["p_last_days"]:
                d = D - rng.randint(0, 2)
            else:
                d = max(1, round(rng.uniform(P["early_from"] * D, D)))
            loan_start.setdefault(day + d, []).append((day, D, ill))

    for day in range(-WARMUP, steps):
        open_ = is_open(day)
        shelves_morning = level["shelves"]
        # 1. returns into the book drop (any day)
        back = loan_start.pop(day, [])
        if back:
            n_ill = sum(1 for _, _, ill in back if ill)
            flow("return", len(back), day)
            bin_["own"] += len(back) - n_ill
            bin_["ill"] += n_ill
            if day >= 0:
                for t0, D, _ in back:
                    res.loan_lengths[str(D)].append(day - t0)
        # 2. the van arrives (the receiving desk takes deliveries even when the library is closed)
        arr = van.pop(day, 0)
        if arr:
            flow("ill_arrive", arr, day)
            hold.append([0, 0, arr])
        if open_:
            # 3. the bin: each book that was there this morning is reshelved (or sent back) with p
            b_own = binomial(rng, bin_["own"] - sum(1 for _, _, ill in back if not ill), P["p_reshelve"])
            b_ill = binomial(rng, bin_["ill"] - sum(1 for _, _, ill in back if ill), P["p_reshelve"])
            flow("reshelve", b_own, day)
            flow("send_back", b_ill, day)
            bin_["own"] -= b_own
            bin_["ill"] -= b_ill
            # 4. the hold shelf: pickups, then expiry
            for h in hold:
                for j, kind in ((1, False), (2, True)):
                    n = binomial(rng, h[j], P["p_pickup"])
                    if n:
                        h[j] -= n
                        lend(0 if kind else n, n if kind else 0, day, "pickup")
                h[0] += 1
            while hold and hold[0][0] >= P["hold_open_days"]:
                _, own, ill = hold.popleft()
                flow("expire", own, day)
                flow("expire_ill", ill, day)
            # 5. staff pull reserved books from the shelves
            n = binomial(rng, waiting["local"], P["p_pull"])
            n = min(n, level["shelves"])
            if n:
                waiting["local"] -= n
                flow("fill", n, day)
                flow("pull", n, day)
                hold.append([0, n, 0])
            # 6. interlibrary requests go out on weekdays
            if weekday(day) < 5:
                n = binomial(rng, waiting["ill"], P["p_ill_send"])
                if n:
                    waiting["ill"] -= n
                    flow("ill_request", n, day)
                    for _ in range(n):
                        d = rng.randint(*P["van_days"])
                        if weekday(day + d) == 6:
                            d += 1
                        van[day + d] = van.get(day + d, 0) + 1
                        if day >= 0:
                            res.van_days.append(d)
            # 7. borrowing and acquisitions
            lend(binomial(rng, shelves_morning, borrow_share(day)), 0, day, "borrow")
            if weekday(day) < 5:
                flow("acquire", poisson(rng, P["acquire_per_weekday"]), day)
        # 8. reservations are placed online every day
        n = poisson(rng, reserve_rate(day))
        n_ill = binomial(rng, n, P["p_ill"])
        flow("reserve", n, day)
        waiting["local"] += n - n_ill
        waiting["ill"] += n_ill
        assert level["return_bin"] == bin_["own"] + bin_["ill"]
        assert level["hold_shelf"] == sum(h[1] + h[2] for h in hold)
        assert level["reservations"] == waiting["local"] + waiting["ill"]
        assert level["van"] == sum(van.values())
        if day == -1:
            res.start = dict(level)
        if day >= 0:
            for s in STOCKS:
                res.levels[s].append(level[s])

    res.eras = [{"t": d + 1, "label": label} for d, label in eras(steps)]
    return res


def ground_truth(res: Result) -> dict:
    """Everything the model is not told, in one JSON-able dict."""
    L, F = res.levels, res.flows
    n = len(L["shelves"])
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None   # noqa: E731

    def prev(s: str) -> list[int]:
        return [res.start[s], *L[s][:-1]]

    def k_of(f: str, s: str, days: range | list[int] = range(n)) -> float:
        p = prev(s)
        return round(sum(F[f][i] for i in days) / max(1, sum(p[i] for i in days)), 5)

    def per_day(f: str) -> float:
        return round(sum(F[f]) / n, 3)

    before = [d for d in range(n) if loan_days(d) == P["loan_days"]]
    after = [d for d in range(n) if loan_days(d) == P["loan_days_extended"]]
    van_out = per_day("ill_request")
    moves = [
        {"from": "shelves", "to": "on_loan", "form": "proportional", "k": k_of("borrow", "shelves"), "value": per_day("borrow"),
         "k_nominal": P["borrow_share"], "what": "borrowing: each book on the shelves has a chance a day of being borrowed "
                                                 "(x season: summer reading +45%, exam weeks +15%; x weekday)"},
        {"from": "on_loan", "to": "return_bin", "form": "proportional", "k": k_of("return", "on_loan"),
         "k_by_era": {"loans_3_weeks": k_of("return", "on_loan", before), "loans_4_weeks": k_of("return", "on_loan", after)},
         "what": "returns: really a delayed copy of what was lent (mean loan "
                 f"{mean(res.loan_lengths['21'])} days at 3 weeks, {mean(res.loan_lengths['28'])} at 4 weeks), "
                 "close to proportional to what is on loan"},
        {"from": "return_bin", "to": "shelves", "form": "proportional", "k": k_of("reshelve", "return_bin"),
         "k_open_day": P["p_reshelve"], "what": "reshelving: 60% of the bin per open day (none on holidays or during the renovation)"},
        {"from": "hold_shelf", "to": "on_loan", "form": "proportional", "k": k_of("pickup", "hold_shelf"),
         "k_open_day": P["p_pickup"], "what": "a patron collects a reserved book"},
        {"from": "shelves", "to": "hold_shelf", "form": "driven", "driver": "reservations", "k": k_of("pull", "reservations"),
         "value": per_day("pull"), "what": "staff pull reserved books from the shelves: k x reservations waiting (only the local "
                                           "70% of them, at 0.5 per open day)"},
        {"from": "hold_shelf", "to": "shelves", "form": "proportional", "k": k_of("expire", "hold_shelf"), "value": per_day("expire"),
         "what": "uncollected after 8 open days: back to the shelves"},
    ]
    outside = [
        {"to": "reservations", "form": "constant", "value": per_day("reserve"), "what": "reservations placed (more in exam weeks and summer)"},
        {"from": "reservations", "form": "proportional", "k": k_of("fill", "reservations"), "value": per_day("fill"),
         "what": "a local reservation is filled: its book was pulled to the hold shelf (the same count as shelves -> hold shelf)"},
        {"to": "shelves", "form": "constant", "value": per_day("acquire"), "what": "acquisitions (weekdays)"},
        {"from": "return_bin", "form": "proportional", "k": k_of("send_back", "return_bin"), "value": per_day("send_back"),
         "what": "interlibrary books go back to their owner after their loan"},
        {"from": "hold_shelf", "form": "proportional", "k": k_of("expire_ill", "hold_shelf"), "value": per_day("expire_ill"),
         "what": "uncollected interlibrary books go back to their owner"},
    ]
    links = [{"driver": "reservations", "into": "hold_shelf", "k": k_of("pull", "reservations"),
              "what": "the hold shelf's arrivals from the shelves follow the reservations waiting (the books come from the shelves: "
                      "see moves; the reservation itself leaves to outside)"}]
    hidden = [{"from": "reservations", "to": "hold_shelf", "shape": "pipe", "delay": mean(res.van_days),
               "delay_range": list(P["van_days"]), "share": k_of("ill_request", "reservations"), "holds": mean(L["van"]),
               "per_day": van_out,
               "what": "interlibrary loans: the request leaves the waiting list (weekdays, 0.4 of those waiting) and the book "
                       "rides the delivery van 4-6 days (uniform; Sunday arrivals wait for Monday) to the hold shelf"}]
    return {
        "seed": res.seed,
        "steps": n,
        "step": "1 day",
        "parameters": P,
        "calendar": {"day_0": "Monday 1 January", "closed": "1 January, 25-26 December, renovation days 300-306 (Sundays open, short hours)",
                     "summer_reading": {"from_day": SUMMER[0], "to_day": SUMMER[1], "borrowing_plus": SUMMER[2]},
                     "exams": [{"from_day": a, "to_day": b, "reservations_plus": rr, "borrowing_plus": br} for a, b, rr, br in EXAMS],
                     "loan_period_extended_from_day": EXTENDED_FROM, "renovation": list(RENOVATION), "warmup_days": WARMUP},
        "eras": res.eras,
        "measured": {"stocks": MEASURED_STOCKS, "flows": MEASURED_FLOWS},
        "hidden_stocks": {"van": {"between": {"out_of": "reservations", "into": ["hold_shelf"]}, "out_flow": "ill_request",
                                  "in_flows": ["ill_arrive"], "delay": {"dist": "uniform whole days, Sunday arrivals moved to Monday",
                                                                         "low": P["van_days"][0], "high": P["van_days"][1],
                                                                         "realised_mean": mean(res.van_days)},
                                  "kind": "pipeline (fixed delay)", "mean_level": mean(L["van"]), "max_level": max(L["van"])}},
        "loans": {"3_weeks": {"realised_mean_days": mean(res.loan_lengths["21"]), "n": len(res.loan_lengths["21"])},
                  "4_weeks": {"realised_mean_days": mean(res.loan_lengths["28"]), "n": len(res.loan_lengths["28"])}},
        "sd_structure": {
            "note": "In SD Lab terms, per day. k = total over the year / Σ the source's (or driver's) level at the end of the day "
                    "before (the run's average, Sundays and closures included). Reservations and books are counted alike (one "
                    "reservation = one book requested), so an interlibrary request leaving the waiting list and its book arriving on "
                    "the hold shelf are one thing passing through the hidden van.",
            "moves": moves,
            "outside": outside,
            "links": links,
            "hidden": hidden,
            "echoes": [],
        },
        "flows": {f: {"from": a, "to": b, "measured": f in MEASURED_FLOWS, "total": sum(F[f]), "per_step_mean": per_day(f),
                      "per_step": F[f]} for f, (a, b) in FLOWS.items()},
        "start_levels": res.start,
        "levels": L,
        "mean_levels": {s: mean(L[s]) for s in STOCKS},
    }


def measured(seed: int = SEED, steps: int = STEPS) -> dict:
    """What SD Lab sees of a run: the measured levels per day, the eras, and the counts of the
    flows the dashboard could count (none goes into or out of the van). The levels and eras are
    exactly what history.py prints."""
    res = cached(seed) if steps == STEPS else run(seed, steps)
    return {"t": list(range(1, steps + 1)),
            "levels": {s: res.levels[s] for s in MEASURED_STOCKS},
            "eras": [{"start": e["t"], "label": e["label"]} for e in res.eras],
            "counters": {f: res.flows[f] for f in COUNTERS}}


_cache: dict[int, Result] = {}


def cached(seed: int = SEED) -> Result:
    if seed not in _cache:
        _cache[seed] = run(seed)
    return _cache[seed]


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else SEED, int(sys.argv[2]) if len(sys.argv) > 2 else STEPS)
    g = ground_truth(r)
    print(json.dumps({"start": r.start, "mean_levels": g["mean_levels"], "max": {s: max(v) for s, v in r.levels.items()},
                      "min": {s: min(v) for s, v in r.levels.items()},
                      "per_day": {f: v["per_step_mean"] for f, v in g["flows"].items()}, "loans": g["loans"],
                      "van": g["hidden_stocks"]["van"]["delay"]}, indent=1))
