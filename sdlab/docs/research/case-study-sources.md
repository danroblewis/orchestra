# Case-study sources: real data and published SD models for harder tests

**Status:** done (survey; research only, no code changed)
**Verdict:** few SD studies publish both the equations *and* measured stock levels; the best
"real" tests come from three places: (1) machine-readable canonical models we simulate ourselves
(PySD reads them), (2) small classic datasets whose accepted equations are SD-shaped (epidemics,
predator-prey and competition experiments, technology diffusion), and (3) public administrative or
engineering data where the stocks *and some flows* are measured, so the flows the engine finds can be
checked against measurements rather than against a modeller's opinion.

Asked by the user: "gather case-studies where system dynamics professionals provide the actual
measurement data and the system dynamics equations they arrived at", plus canonical models in
machine-readable form and physical systems with known equations. Surveyed October 2026 by web
search, GitHub API and CRAN; every claim below links to where it was checked. "Not verified" marks
what was not opened.

## What our discovery can and cannot take today

Discovery reads measured stock levels per step, announced eras, announced injections and units
(`identify(stocks, run, opts)`, CLAUDE.md rule 1). The truth engine (`sdlab/sdtruth.py`,
`sdlab/runner.py`) is discrete (one Euler step of length 1 per sample), every rate is floored at 0,
and rates are `constant`, `proportional`, `gap`, `linear` (in any stocks) or `available`, times
`linear`/`table` effects of one stock's level, with co-flows (`uses`), schedules (eras, announced or
not), injections and hidden stocks (`docs/LADDER.md`, "The format").

Several classic SD structures already fit that format:

| structure | how it is written in our format |
|---|---|
| SIR / SEIR infection `beta*S*I/N` | `S -> I: beta * S * effect(I, linear, normal=N, max=...)` |
| Bass diffusion `(p + q*A/N)*P` | two named flows `P -> A`: `p * P` and `q * P * effect(A, linear, normal=N, max=...)` |
| logistic growth `r*X*(1 - X/K)` | `outside -> X: r * X` and `X -> outside: (r/K) * X * effect(X, linear, normal=1, max=...)` |
| Lotka-Volterra predation `a*H*L` | `H -> outside: a * H * effect(L, linear, normal=1, max=...)` |
| DELAY3 / aging chain | three hidden stocks in a chain, each `k * stock` |
| SMOOTH(X, tau) of a stock | `outside -> S: X / tau` and `S -> outside: S / tau` (the inflow reads X, does not drain it) |
| STEP, policy switch | a schedule change (announced = era) |
| PULSE of material | an injection |

Features the sources below need and **we lack** (adding any to the format or the engine needs the
user's approval, CLAUDE.md rule 2):

1. **Exogenous input series** (a measured inflow that is data, not an equation: pump voltage,
   emissions, rainfall, mint production). Today an outside inflow must be a constant, a scheduled
   constant, or a rate of stocks. This is the most important gap for real data.
2. **Sampling interval vs model step.** Real data is annual (lynx-hare), weekly, daily, or every
   4 s (tanks). The engine assumes one Euler step per sample. Ingesting a continuous-time model needs
   either a sub-step (`dt`) with sparse measurement, or simulating at fine dt and down-sampling.
3. **Nonlinear rate forms** outside the linear-times-effect family: powers (`sqrt(h)` in Torricelli
   outflow), `exp`, `ln`, ratios of two stocks inside a table effect (`effect(A/B, table)`),
   `MIN/MAX` between flows, `IF THEN ELSE` on auxiliaries.
4. **Two-way flows** (rates that go negative; we floor at 0).
5. **Arrays/subscripts** (can be flattened into one stock per element), Stella conveyors/ovens,
   fixed (pipeline) delays `DELAY FIXED` (an infinite-order delay; approximable by a long chain).
6. **Observation models**: a proxy of a stock (pelts traded for hares), a fraction of a stock
   (share of households), or a cumulative flow (reported cases) rather than the stock itself.

## Ranked sources

Value = how much the source tests something the ladder does not (realistic noise, sampling, a
structure set by someone else) and how sure we are of the truth. Effort = work to get it into a
case (download, licence, format features we lack). Score is value (1-5) x (6 - effort (1-5));
rows are ordered by score, then value. The recommendation below departs from the order once: the
cascaded tanks rank lower on effort but are the best physics case.

| # | source | kind | what's there | stocks measured? | SD features | licence | value | effort | score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | [BLS CPS labour force status flows](https://www.bls.gov/cps/cps_flows.htm) | real, stocks + all flows measured | monthly back to the 1990s (BLS historical file; exact start not checked) ([Frazis et al. 2005](https://www.bls.gov/opub/mlr/2005/09/art2full.pdf)); employed, unemployed, not in labour force (16+), and all 6 gross flows between them, seasonally adjusted and reconciled with the stocks | yes (E, U, N) and every flow | 3 stocks, 6 moves, each roughly `k * stock` with k drifting over the business cycle (recessions as unannounced eras) | US public domain | 5 | 2 | 20 |
| 2 | [SDXorg/test-models](https://github.com/SDXorg/test-models) | canonical models | 12 `samples/` models (teacup, SIR, Lotka-Volterra, hares-and-lynxes, population, workforce, pendulum, Roessler, harmonic oscillator, arrays...) and 153 `tests/` models, each one function (delays, smooth, lookups, trend, sqrt, power, subscripts...), in `.mdl`, `.xmile`, `.stmx`, with a canonical `output.csv` | simulated (we choose) | all of Vensim/XMILE, one feature per test | MIT | 4 | 1 | 20 |
| 3 | [gauseR](https://cran.r-project.org/web/packages/gauseR/refman/gauseR.html) (Gause 1934 and others) | real lab experiments, accepted equations | ~40 datasets: yeast and Paramecium logistic growth, two-species competition, Didinium/Paramecium predator-prey, mites with artificial immigration, medium changes, Huffaker mites, Isle Royale wolves/moose | yes (counts or volumes of each species) | logistic, Lotka-Volterra competition and predation; immigration = injections; medium change = era; 1-3 stocks; daily samples, 10-40 points, some replicates | GPL-3 (package; the historical counts are facts, cite Gause) | 4 | 2 | 16 |
| 4 | [PySD-Cookbook](https://github.com/SDXorg/PySD-Cookbook) | models + real data | 25 `.mdl` models (aging chain, delays, capability trap, atmospheric bathtub, emails, SI/SIR, defects, pendulum, penny jar, predator-prey, sales agents, Twitter, teacup...) and data folders: Hudson Bay lynx-hare, Mauna Loa CO2 + global emissions + world population, Ebola in Sierra Leone (WHO), baby names, emails, penny jar + mint production | some (CO2, populations); others are flows or samples | delays, aging chains, SI/SIR, logistic | no licence file (ask, or use the models only as recipes) | 4 | 2 | 16 |
| 5 | Boarding-school influenza 1978 ([BMJ 1978](https://search.r-project.org/CRAN/refmans/pomp/html/bsflu.html); `pomp::bsflu`, `outbreaks::influenza_england_1978_school`) | real epidemic, accepted SIR/SEIR | 14 daily values of boys confined to bed (B) and convalescent (C), N = 763 | yes: B and C are stocks; S and I hidden | SIR-type with one or two hidden stocks; known "enigma": plain SEIR fits badly ([Avilov et al.](https://ira.lib.polyu.edu.hk/bitstream/10397/110074/6/Avilov_1978_English_Boarding.pdf)) | GPL (packages); data from a 1978 BMJ note | 4 | 2 | 16 |
| 6 | US household technology adoption ([OWID](https://ourworldindata.org/grapher/technology-adoption-by-households-in-the-united-states), Comin & Hobijn 2004) | real diffusion, accepted Bass/logistic | share of US households with ~30 technologies, 1860-2019, annual | yes (share adopted = adopters / households) | Bass (expressible, two named flows), logistic, saturation; 2 stocks per technology, ~20-100 points each; many independent series = many cases | OWID charts are CC BY 4.0; check the underlying Comin-Hobijn terms (not verified) | 4 | 2 | 16 |
| 7 | Hudson's Bay lynx-hare (Elton 1925; [tsibbledata::pelt](https://tsibbledata.tidyverts.org/reference/pelt.html), [astsa](https://search.r-project.org/CRAN/refmans/astsa/html/Hare.html), PySD-Cookbook csv; test-models `bpowers-hares_and_lynxes_modules` model) | real, accepted Lotka-Volterra | 91 annual values 1845-1935 of pelts traded | proxies (pelts traded, not populations) | 2 stocks, predation as an effect; well known that LV fits it poorly and that the series is two spliced sources | GPL-3 (package); data public | 3 | 1 | 15 |
| 8 | [JimDuggan/SDMR](https://github.com/JimDuggan/SDMR) (*System Dynamics Modeling with R*) | textbook models + small data | ~40 `.mdl` lecture and chapter models (S-shaped growth, Solow, overshoot, SIR cohort and policy, health, fixed delay); `HPV Ireland` csv; synthetic SIR/logistic csvs | mostly simulated | textbook structures, cohorts | MIT | 3 | 1 | 15 |
| 9 | [Andrade & Duggan 2021, SDR_Bayes](https://github.com/jandraor/SDR_Bayes) (SDR 37(4)); also [JRA-SF_Bayes](https://github.com/jandraor/JRA-SF_Bayes), [delays](https://github.com/jandraor/delays), [preparedness](https://github.com/jandraor/preparedness) (SDR 2024) | published SD model + data | `SEIR.stmx` + `Cumberland_data_1918.csv`; `SEI3RD.stmx` + 1918 San Francisco flu; Stan files, R Markdown that reproduces the paper | no: weekly incidence (a flow) | SEIR, SEI3RD (Erlang delays as stock chains) | no licence in SDR_Bayes (ask); `delays` has a Zenodo DOI | 4 | 3 | 12 |
| 10 | [MetaSD model library](https://metasd.com/model-library/) (Fiddaman) | ~91 replications of published SD models | Vensim `.mdl`/`.vpm`; the [data/calibration category](https://metasd.com/category/model-library/technical/datacalibration/) holds models shipped with data: [opioid epidemic](https://metasd.com/2019/03/opiod-epidemic-dynamics/) (Chen et al., JAMA Netw Open, calibrated 2002-2015), [sea-level rise](https://metasd.com/2010/03/sea-level-rise/) (Rahmstorf 2007 / Grinsted 2009), [Facebook logistic](https://metasd.com/2011/11/facebook-valuation-with-a-logistic-model/), FREE, bathtub statistics | depends: sea level (a stock) yes; opioid deaths (flow) no | delays, lookups, Kalman filtering set-ups; 1 to dozens of stocks | "freely used and distributed, subject to authors' copyright" | 4 | 3 | 12 |
| 11 | HHS COVID hospital capacity by state ([healthdata.gov / data.gov](https://catalog.data.gov/dataset/covid-19-reported-patient-impact-and-hospital-capacity-by-state-timeseries-c6fc8)) | real, stock + inflow measured | daily 2020 - May 2024, per state: patients in hospital with COVID (a stock) and new admissions (its inflow) | yes (census), inflow measured | 1-2 stocks per state; discharge/death as `stock / length of stay`; ICU as a co-stock | US government work | 3 | 2 | 12 |
| 12 | Cascaded tanks ([4TU, DOI 10.4121/12960104](https://data.4tu.nl/datasets/d4810b78-6cdd-48fe-8950-9bd601e5f47f); [nonlinearbenchmark.org](https://www.nonlinearbenchmark.org/)) | real lab rig, physics known | pump input u and lower-tank level; 1024 estimation + 1024 test samples; upper tank **not measured** ([Forgione & Piga 2020](https://arxiv.org/pdf/2006.02915)) | lower tank yes, upper tank hidden | 2 stocks in a chain; Torricelli outflow `k*sqrt(h)`; overflow when a tank is full (a cap); exogenous input | CC BY-SA 4.0 | 5 | 4 | 10 |
| 13 | Reservoir mass balance: [Lake Mead](https://www.usbr.gov/uc/water/hydrodata/reservoir_data/921/dashboard.html) storage and release (daily since 1934, [data.usbr.gov](https://data.usbr.gov/catalog/4370/item/6122)); [USGS evaporation](https://www.usgs.gov/data/evaporation-data-lake-mead-nevada-and-arizona) | real, accounting identity known | daily storage (acre-feet), daily release; monthly evaporation; inflow not found as a series | storage yes; release and evaporation measured | 1 stock, exogenous inflow, a policy-set release (an operator, not a rate law) | US public domain | 3 | 3 | 9 |
| 14 | [Vensim sample models](https://www.vensim.com/documentation/sample_models.html) | canonical models | World3-03 (+ scenarios), market growth, multi-stage project, urban dynamics, workforce-inventory (with a Kalman filtering variant), finance; plus Modeling Guide and function-example folders | simulated | large tables, delays, smooths, IF THEN ELSE; 5-40 stocks | Vensim says its supplied sample models are MIT ([models page](https://www.vensim.com/documentation/models.html)); some are `.vmf` (binary, needs Vensim to export `.mdl`) | 3 | 3 | 9 |
| 15 | Mauna Loa CO2 + Global Carbon Budget emissions (also in PySD-Cookbook `data/Climate`) | real, physics known | monthly/annual atmospheric CO2 (a stock) since 1958; annual fossil + land-use emissions (the inflow) | atmosphere yes; ocean and land sinks hidden | one measured stock, exogenous inflow, 2-4 hidden sink stocks (impulse-response carbon models) | NOAA public domain; GCB CC BY 4.0 (not verified this year) | 4 | 4 | 8 |
| 16 | Eyam plague 1666 ([Raggett 1982 via Whittles & Didelot 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4874723); SD version at [churchmodel.org.uk](https://churchmodel.org.uk/2014/11/20/the-eyam-plague-of-1666-a-system-dynamics-model/)) | real, accepted SIR | ~10 points of S and I (Raggett) or a fuller parish series (Whittles & Didelot) | S yes; I estimated from deaths | SIR, closed population | published tables (facts) | 2 | 2 | 8 |
| 17 | [Rahmandad, Lim & Sterman 2021, CovidGlobal](https://github.com/tseyanglim/CovidGlobal) (SDR 37(1)) | published SD model + its calibration data | full Vensim model (`CovidGlobal-Disaggregate-V60.mdl`), `.vpd` payoffs, `.voc` optimisation controls, csv data for 92 nations, analysis code | no: daily reported cases, deaths, tests (flows); cumulative deaths are a stock-like series | SEIR with behavioural feedback, adherence fatigue, testing, underreporting; subscripted by nation; many hidden stocks | MIT | 5 | 5 | 5 |
| 18 | [dysts](https://github.com/williamgilpin/dysts) and the [PySINDy benchmark](https://pysindy.readthedocs.io/en/latest/examples/16_noise_robustness/example.html) | synthetic ODE corpus | 135 chaotic systems with equations and precomputed trajectories | simulated | polynomial ODEs; mostly not stock-and-flow (states go negative, no conservation) | Apache-2.0 | 1 | 2 | 4 |
| 19 | World3: [pyworld3](https://github.com/cvanwynsberghe/pyworld3), Vensim `wrld3-03`; data in [Herrington 2021](https://dash.harvard.edu/handle/1/37364868) and [Nebel et al. 2023](https://ris.uni-paderborn.de/record/50368) | published model vs historical data | 12 stocks, ~150 auxiliaries, many tables; data are world aggregates (population, industrial output, food, pollution index) | population yes; most others are indices or auxiliaries | everything: tables of ratios, delays, smooths, policy years | CeCILL 2.1 (pyworld3); data compiled from UN / World Bank (not verified) | 2 | 5 | 2 |
| 20 | Other system-identification sets: [DaISy](https://homes.esat.kuleuven.be/~smc/daisy/daisydata.html) (CSTR, pH tank, heat exchanger, dryer, Lake Erie simulation), the rest of nonlinearbenchmark.org | real rigs | input-output records, usually one output | rarely the states | black-box I/O; physics rarely stated | mixed / unstated | 1 | 4 | 2 |

Not available, so not ranked:

- **Sterman, *Business Dynamics*, CD models and data.** No public download was found; the models
  ship on the book's CD. Many are replicated in MetaSD and SDMR.
- **Beer game experimental data** (Sterman 1989; Croson & Donohue). No raw per-player series is
  published as far as the search found; [Dogan & Sterman](https://archives.albany.edu/downloads/mw22vq13m?locale=en)
  and [Kunze 2006](https://proceedings.systemdynamics.org/2006/proceed/papers/KUNZE354.pdf) describe
  data but no files were found. Inventories are stocks, so it is worth asking the authors.
- **The System Dynamics Society model library.** There is no general searchable library; the Society
  sells specific sets (e.g. [Nord's *Growth of a New Product*](https://systemdynamics.org/?p=172833)),
  and a [forum thread](https://discuss.systemdynamics.org/t/is-there-such-a-thing-as-sd-models-pedia/109)
  says a library needs volunteers. Conference papers sometimes attach models
  ([proceedings](https://proceedings.systemdynamics.org/)), but rarely with data.
- **Insight Maker and the isee Exchange.** Thousands of user models (isee's curated sample set alone
  is "nearly 100", per [McMaster's guide](https://library.mcmaster.ca/spark/stella-sample-models)).
  No bulk export or licence for the library was found; the unofficial
  [`insightmaker` npm package](https://www.npmjs.org/package/insightmaker) runs exported files.
  Quality varies; useful later for a "real modellers' structures" corpus, not now.
- **BPTK-Py tutorial** ([transentis/bptk_py_tutorial](https://github.com/transentis/bptk_py_tutorial)):
  a few XMILE models (Bass, beer game); the GitHub API showed no files on the default branch today,
  and no licence.
- **Rahmandad, Oliva & Osgood (eds), *Analytical Methods for Dynamic Modelers*** (MIT Press 2015):
  the book has an online appendix of models and code, but no public link was found.
- **Pruyt, *Small System Dynamics Models for Big Issues*** ([TU Delft](https://simulation.tudelft.nl/SD),
  [PDF](https://simulation.tudelft.nl/SD/CaseBookSD101ErikPruyt_2019a.pdf)): ~90 exercises; the
  models are linked from the book; copyright Pruyt, ask before redistributing.

### Why few "model + its data" pairs exist

The field calibrates hand-built structures to data (Vensim payoffs, Kalman filtering, MCMC; see
[SD-TOOLS-AND-DISCOVERY.md](SD-TOOLS-AND-DISCOVERY.md)), and the data it calibrates against are
usually **flows or reported counts** (cases, deaths, sales, shipments), not stock levels. Of the
published pairs found, only the epidemic models (boarding school B and C), sea-level rise and the
predator-prey sets give stocks directly. Replication studies report that missing data is a main
reason SD models cannot be reproduced
([Tiruvengadam et al. 2019](https://research.tec.mx/vivo-tec/display/AcademicArticleSCO_85086287061)).
So a real-data case usually needs an **observation model** (what was measured, as a function of the
stocks), which our discovery input does not have.

## Recommendation: what to ingest first

1. **SDXorg/test-models + PySD-Cookbook + SDMR, through PySD (synthetic, no engine change).**
   Read each `.mdl`/`.xmile` with PySD ([model loading](https://pysd.readthedocs.io/en/master/python_api/model_loading.html));
   PySD 3 builds an abstract model (`pysd.translators` → `AbstractModel`) whose elements are
   stocks (`INTEG`), flows and auxiliaries as parsed expression trees. A small converter (a new
   script, e.g. `sdlab/ladder/import_pysd.py`, not touching `sdtruth.py`) inlines auxiliaries into
   each stock's net flow, splits the net flow into `FROM -> TO` flows by sign and by which stock it
   also appears in, and pattern-matches each rate onto our forms (constant, `k*X`, `(g-X)/t`,
   linear, `rate*effect(...)`). Anything that does not match (sqrt, ratios in tables, IF THEN
   ELSE, arrays) is reported as "not representable" with the feature named, which itself measures
   the format's coverage. Expect most of the 12 samples and the 25 cookbook models to convert
   except pendulum/Roessler/harmonic oscillator (negative flows) and the subscripted ones. Each
   converted model becomes a new ladder case at a high level (realistic parameters, a modeller's
   structure). Cross-check: simulate with PySD at dt = 1 Euler and with `sdtruth.py`; the
   trajectories must match to rounding before the case is accepted.
2. **BLS labour force flows (real, scored against measured flows).** Three stocks, six measured
   flows, monthly, roughly 350-430 points, public domain. Run discovery on E, U, N levels only; score the
   found moves against the published flows (the flows are measurements, so this is real ground
   truth for the moves, not a modeller's opinion). Recessions are unannounced eras. Needs only a
   loader (a "real-data case" with no `flows:` truth but a measured-flows file for the scorer);
   no engine change. Caveat: seasonally adjusted, reconciled series, so noise is not counts.
3. **gauseR experiments and the boarding-school flu (real, accepted SD-shaped equations).** Small,
   classic, the stocks are measured, and the published equations (logistic, LV competition and
   predation, SIR) are expressible in our format (effects table above). Immigration experiments
   give real injections; medium changes give announced eras. Score by held-out prediction and by
   comparison with the published structure (below). Needs the sampling-interval decision (2 in the
   gaps list) because samples are daily while the processes are continuous; the cheapest route is
   to treat one sample as one step and accept the Euler error, and record that choice in the case.
4. **Technology adoption (OWID) as a parametric family of Bass cases.** ~30 series, one structure;
   discovery should find the same two-flow structure in most of them with different numbers. This
   is the real-data analogue of a parametric case. Needs the observation model "fraction of
   households" (stock = share x households; a units decision, no engine change if we pass shares as
   levels with a fixed total).
5. **Cascaded tanks, as the first case that needs engine features.** Physics, a hidden upper tank,
   real sensor noise, and a train/test split already defined. It needs an exogenous input series and
   a `sqrt` rate. The sqrt may not need an engine change: a constant rate times a table effect of
   the tank's own level, `X -> outside: k * effect(X, table, [[0, 0], [1, 1], [4, 2], [9, 3]])`,
   approximates `k*sqrt(X)`. The overflow of a full tank is a ceiling on a level, which the engine
   does not have (it caps only outflows at what a stock holds). The input series and the ceiling
   need the engine. Propose the input-series feature to the user before starting; it also
   unlocks CO2, reservoirs and the penny jar.

Defer: CovidGlobal and World3 (large, subscripted or table-heavy, data are flows or indices) until
the converter and the observation-model idea exist; the MetaSD data/calibration models after that,
starting with sea level (a measured stock, one or two stocks).

## Scoring real data where the equations are only the modeller's

Our scorer compares numbers against a true model (`docs/LADDER.md`, Scoring). For real data the
"truth" is weaker, so score on several axes and report them separately (never folded into the
ladder's pass rate without the user's approval, CLAUDE.md rule 5):

1. **Held-out prediction (primary).** Fit on the first part of each series, simulate forward from
   the last fitted level with no further data, and compare with the held-out part, against
   persistence (last value) and against the published model refitted on the same training window.
   For multi-unit data (nations, technologies, states, experiment replicates) also hold out whole
   units: find the structure on some, refit numbers only on the others. This is the only axis that
   does not trust anyone's equations.
2. **Measured flows (where they exist).** BLS gross flows, reservoir releases, hospital admissions:
   score found flows against measured flows with the existing parts machinery; this is real truth.
3. **Agreement with the published structure.** Map the published model onto our parts (moves,
   outside flows, links, effects, hidden stocks) and report precision/recall of parts and the
   complexity difference (rule 7). Label it "agreement", not "pass": the modeller's structure is a
   hypothesis that fit the data, and a simpler found model that predicts as well is not wrong.
4. **Semi-synthetic twin (bridges real and synthetic).** Simulate the published model with its
   published (or our refitted) parameters at the real data's length, sampling and noise level,
   run discovery on that, and score against it exactly as on the ladder. If discovery recovers the
   twin but not the real data's published structure, the gap is the data (or the model's misfit),
   not the method. This follows rule 4: diagnose identifiability before calling a failure.
5. **Residual checks** (Oliva 2003; [system-dynamics-field.md](literature/system-dynamics-field.md)):
   Theil inequality shares and autocorrelation of one-step residuals; structure left in the
   residuals says a piece is missing.

## Open questions for the user

- May we add an exogenous input series and a sub-step (`dt`) to the case format and engine? Without
  them, only rows 1-8 of the table (and the stock-only parts of the others) are ingestible.
- Should real-data cases live on the ladder (with their own scoring axes) or in a separate board?
- Several sources have no licence (PySD-Cookbook, SDR_Bayes) or GPL packaging. Fetching the data at
  ingest time from the source (not committing it) avoids redistribution questions; is that acceptable?
