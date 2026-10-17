# Hospital: the answer key

For graders. The model (`../hospital.json`) is told only what the dashboard shows; this is what
the simulation (`machines/sim.py`, seed 20261016, 60 days, 1-hour steps, 6237 patients) really
does. `python truth.py` regenerates `truth.json` with every hidden level and every true flow per step.

## Structure

```
 outside ─registrations*─▶ [Waiting room] ─start─▶ [In treatment] ─admissions*─▶ [Ward] ─ward discharge─▶ [Discharged home]
                              │      │ ▲               │ ▲ ▲  │  │                  ▲                            ▲
                     abandon  │      │ │               │ │ │  │  └─discharge────────┼────────────────────────────┘
                              ▼      │ │               │ │ │  │                     │
   [Left without being seen]◀┘      │ │               │ │ │  │                     │
                                     │ │               │ │ │  │                     │
             20% at triage           ▼ │               │ │ │  │ 30%, first visits   │
                     ((IMAGING))  ───┼─┼──── 2 h ──────┘ │ │  ▼                     │
                                     │ │                 │ └─((LAB)) exp 4 h ─ 35% ─┘
                                     │ │                 └──────────── 65% ┘
                                     │ │  12% of first visits
                                     │ └─────────── ((FOLLOW-UP)) ◀── In treatment
                                     │                lognormal 120 h ± 36 h
```

The same, edge by edge (`*` measured counter, `(( ))` hidden stock):

| from | to | what |
|---|---|---|
| outside | Waiting room | registrations* (new patients) |
| Waiting room | ((Imaging)) | 20% of new patients, 0.1–0.6 h after arriving |
| ((Imaging)) | In treatment | after uniform 1.75–2.25 h |
| Waiting room | In treatment | start: a staffed bed is free (FIFO) |
| Waiting room | Left without being seen | abandon: patience exp. mean 8 h |
| In treatment | ((Lab)) | 30% of first visits, after exp. mean 1 h of treatment |
| ((Lab)) | In treatment | 65% of results, after exp. mean 4 h |
| ((Lab)) | Ward | 35% of results, after exp. mean 4 h |
| In treatment | Ward | admissions* (22% of finished treatments) |
| In treatment | ((Follow-up)) | 12% of finished first-visit treatments |
| ((Follow-up)) | Waiting room | after lognormal 120 h ± 36 h |
| In treatment | Discharged home | the rest of finished treatments |
| Ward | Discharged home | lognormal stay 96 h ± 60 h, only 08:00–20:00 |

Every patient is always in exactly one of the
eight stocks; `cumulative registrations − Σ measured stocks = Σ hidden stocks` holds exactly at every step.

## Hidden stocks

| hidden stock | leaves (unmeasured) | returns into (unmeasured) | delay | flow in / h | mean level | perfect inference reports |
|---|---|---|---|---|---|---|
| Imaging | Waiting room, 0.875/h | In treatment, 0.874/h | uniform 1.75–2.25 h (mean 2.00): a pipeline | 0.875 | 1.77 (max 9) | a fixed ~2 h delay between *Waiting room → outside* and *outside → In treatment*, holding ~1.8 |
| Lab | In treatment, 1.219/h | In treatment 0.785/h (64.7%), Ward 0.429/h (35.3%) | exponential, mean 4.0 h: first order, drains at 0.25 × level per hour | 1.219 | 4.88 (max 16) | one stock out of *In treatment*, k ≈ 0.25/h, returning 65% to *In treatment* and 35% to *Ward*, holding ~4.9 |
| Follow-up | In treatment, 0.450/h | Waiting room, 0.410/h | lognormal, mean 120 h, sd 36 h (a high-order delay, not exponential) | 0.450 | 51.8 (max 72) | a ~5-day delay between *In treatment → outside* and *outside → Waiting room*, holding ~50–55 |

The follow-up stock fills from zero over the first ~7 days (no one returns before ~2.5 days), so
in the first week what leaves is not yet balanced by what returns; later in/out balance within 10%.
Returning follow-up patients are never booked again, and get no imaging or lab.

## Visible flows (between measured stocks, unmeasured)

| flow | per hour |
|---|---|
| Registrations (measured) outside → Waiting room | 4.33 |
| start: Waiting room → In treatment (FIFO, while occupied beds < staffed beds) | 3.69 |
| abandon: Waiting room → Left without being seen (patience exp. mean 8 h) | 0.176 |
| Admissions (measured) In treatment → Ward, 22% of treatments | 0.874 |
| discharge: In treatment → Discharged home | 2.80 |
| ward discharge: Ward → Discharged home (lognormal LOS 96 h ± 60 h, only 08:00–20:00) | 1.22 |

Patients back from Imaging or the Lab always get a bed (a corridor trolley if need be); only new
starts wait for a free staffed bed. Arrivals are a non-homogeneous Poisson process (daily cycle,
busier Mondays, a flu-season bump of up to +35% from day 25 to 45, a heat wave ×1.8 on day 38),
plus a bus crash (18 patients, day 20 14:00) and a chemical leak (10 patients, day 44 09:00).

Eras (staffed ED beds): 16 from t=1, 12 from t=361 (staff sickness), 16 from t=553, 20 from t=769
(flu season), 16 from t=1201.

## What makes it hard

All three hidden stocks are small or stationary and return patients to *measured* stocks, so
from the levels alone each looks like a direct flow between two measured stocks with a lag:
Imaging as more Waiting room → In treatment, Lab → Ward as more of In treatment → Ward, and Lab →
In treatment cancels itself out (only the ~4.9 patients it holds are missing from the bed count).
The one strong signal is the conservation gap above, which needs the measured registrations
counter; the measured admissions counter is what separates Lab → Ward from Admissions.
