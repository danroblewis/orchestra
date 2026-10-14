(Research agent output, 2026-10-14: the published structures, extracted with sources.)

# System-dynamics models of software development: structure for building one

Conventions: **S** = stock, **F** = flow (from → to), **R** = rate equation in words, **L** = loop (R+ reinforcing, B− balancing). Where I could not reach the primary text (the two books), I say so.

## 1. The project rework cycle (Cooper 1980; Lyneis & Ford 2007)

Origin: Pugh-Roberts' model for Ingalls Shipbuilding's claim against the US Navy, published as Cooper, "Naval Ship Production: A Claim Settled and a Framework Built" (*Interfaces*, 1980). Lyneis & Ford, "System Dynamics Applied to Project Management: A Survey, Assessment, and Directions for Future Research" (*System Dynamics Review* 23, 2007) is the survey; Lyneis' MIT ESD.36 Lectures 7–8 (2012) and Gozluklu & Sterman, "System dynamics to understand and improve the performance of complex projects" (2022) give the canonical diagram.

**Stocks** (Lyneis): Original Work to Do; Work Done; Undiscovered Rework; Rework to Do (= Known Rework). Sterman's naming: Base Work Remaining; Work Completed; Unknown Rework; Known Rework; plus a Work Released/Perceived-Complete output to the next phase or customer.

**Flows**
- Progress: Original Work to Do → (split) Work Done / Undiscovered Rework
- Rework Generation: the incorrect fraction of progress → Undiscovered Rework
- Rework Discovery: Undiscovered Rework → Rework to Do
- Rework Progress: Rework to Do → (split again) Work Done / Undiscovered Rework (tasks can loop many times)

**Rates**
- Gross progress = Effort Applied (staff × workweek) × Productivity. Productivity is "work accomplished per hour of effort, regardless of completeness or correctness".
- Split by **Fraction Correct and Complete** ("work quality", 0–1): correct share → Work Done; (1 − FCC) × progress → Undiscovered Rework. Cooper & Mullen's 1993 survey of 21 software projects gave average FCC ≈ 0.68 commercial, 0.34 defense.
- Rework Discovery = Undiscovered Rework / **Time to Discover Rework** (first-order delay; in Sterman's version a probability-of-defect-discovery that depends on inspection/test effort, and discovery is often tied to milestones or downstream phases).
- Reporting identities: Fraction Reported Complete = (Work Done + Undiscovered Rework)/Initial Work; Fraction Really Complete = Work Done/Initial Work. The gap is the "90% syndrome" and the "lost year".

**Loops** (Lecture 8, slide 25, all drawn around Known Work Remaining → Effort Needed vs Time Remaining → control actions):
- B−: Add People; Work More (overtime); Work Intensity ("work faster or slack off"); Slip Deadline; Cut Scope.
- R+ side effects: Experience Dilution; Congestion & Communication Difficulties; Too Big to Manage; Fatigue; Burnout; Haste Makes Waste (intensity ↓ FCC); Haste Creates Out-of-Sequence Work; Overlap & Concurrence; Errors Build Errors (unknown errors in prior work ↓ FCC of downstream work); Errors Create More Work; Morale/Hopelessness; Increased Turnover; Scope Growth.

**Used to explain**: late discovery of rework as the main driver of overruns, the extended staffing tail/second staffing peak, the 90% syndrome, and claims (which actions by the client caused which overruns). Ford & Sterman's phase-level version ("Overcoming the 90% Syndrome", 2003; "Dynamic modeling of product development processes", SDR 1998) adds, per phase: Work needing Initial Completion → Work needing QA → Work Approved → Work Finished & Released, with Discovery of Needed Rework → Work needing Coordination → Work known to need Rework → back to QA; detection probability falls with concurrence; concurrence relationships gate how much downstream work can start. Rahmandad & Hu ("Modeling the rework cycle: capturing multiple defects per task", SDR 2010) show the binary defective/not-defective task assumption understates overruns caused by a few tasks cycling repeatedly.

## 2. Abdel-Hamid & Madnick, *Software Project Dynamics* (1991)

Verified from their CACM 1989 "Lessons Learned" paper and reproductions (Thakurta & Dasgupta 2011; IARJSET 2016; Iowa State 2019). Four subsystems: **Human Resource Management** (hiring, assimilation, transfer; newly-hired vs experienced stocks, training overhead), **Software Production**, **Control** (perceived vs actual progress; early progress is measured by effort spent, so "status reporting is an echo of the plan"), **Planning** (re-estimation; add people vs slip schedule, with reluctance to hire late).

**Production sector stocks/flows**
- Tasks: Tasks to be Developed → (software development rate) → Tasks Developed → (QA'd, then tested) → Tasks Tested. Discovery rate of new tasks (underestimation fraction) adds scope.
- Errors: Error Generation → **Undetected (potentially detectable) Errors** → (error detection via QA) → **Detected Errors** → (rework) → removed; undetected errors **escape** to testing, where they are found and corrected at a testing cost.
- Iowa State's Vensim transcription of the model: `Undetected Errors = INTEG(error generation rate − error detection rate, 0)`; `schedule pressure = min(2.5, persondays remaining in work / persondays remaining in time)`.

**Parameterisation**
- Error generation rate = software development rate × nominal errors per task × multiplier(schedule pressure) × multiplier(workforce mix, i.e., rookie fraction). Nominal errors fall along an S-curve from ~25 errors/KDSI early (design) to ~12.5 errors/KDSI at coding.
- Error detection rate = f(QA manpower, "QA manpower needed per error"); QA effort is a planned fraction of total effort (QA gets precedence over development in the model). Under schedule pressure QA is skipped/compressed, lowering detection.
- Actual productivity = potential productivity − losses (communication overhead, motivation), after Steiner.
- From the book (not re-verifiable online, from my knowledge of it): escaped errors are split into **active** errors (design-type, which "reproduce": a multiplier on error generation grows with active error density) and **passive** ones (coding-type, do not propagate); active errors retire into passive over time; testing effort per error rises as error density falls; a fixed fraction of fixes are bad fixes that re-enter the error stock. Treat these details as book-sourced.

**Loops**: Brooks' law (hiring → overhead → ↓ productivity → later → more hiring); schedule pressure → ↑ productivity (B−) but → ↑ error rate and ↓ QA → rework (R+); perceived vs real progress → late schedule adjustment.

**Used to explain**: NASA DE-A (24 KDSI; 1,100→2,200 man-days), 90% syndrome, Brooks' law, optimal QA percentage, and that "safety factor" estimates create more expensive projects (a 50% safety factor raised cost from 3,795 to 5,080 man-days).

## 3. Madachy, *Software Process Dynamics* (2008)

**Brooks' law model** (Chapter 1; reproduced with parameters by Farshchi et al., *ComSIS* 2012):
- S: Requirements/Work remaining; Developed Software; New Personnel; Experienced Personnel.
- F: software development rate (work → developed); hiring/allocation → New Personnel; assimilation rate (New → Experienced, first-order delay).
- R: development rate = nominal productivity × (productivity-weighted staff: experienced 1.2×, new 0.8× in Farshchi's reproduction; 0.5× in Abdel-Hamid-style variants) × (1 − communication overhead) − training overhead, with communication overhead = 0.06·n² (fraction), training overhead = 0.25 experienced-person per trainee during assimilation, assimilation time 20 days, nominal productivity 0.1 FP/person-day, 500 FP of work, 20 initial staff. L: B− (add staff to close schedule gap), R+ (communication and training overhead). Result: adding 5 late helped slightly, adding more hurt; "Brooks' law doesn't hold in all situations".

**Defect flow** (Chapter 3 "generic flow processes"/defect co-flows; the ICSE 1996 inspection-based model and the 2010 USC-CSSE "Modeling Software Defect Dynamics" NASA tool): per phase, a task flow with a parallel **defect co-flow**. S per phase: Defects Generated (undetected, in the artifact); Detected Defects; Escaped Defects passed to the next phase; Reworked. F: generation (= development rate × defect density, defects/KSLOC, by phase/type), detection (= inspection/test effort × detection efficiency, or defects/detection delay), rework (= detected × rework effort per defect, phase-dependent, rising for defects found late), escape (= generated − detected at phase exit). Used to explain the cost/benefit of inspections and of removal-technique mixes by ODC defect type. I found **no treatment of a test suite or coverage as a stock** in Madachy; coverage enters only as a detection-efficiency parameter.

## 4. Continuous delivery, queues, technical debt

**DORA** (dora.dev "four keys" guide): change lead time (commit → deployed in production), deployment frequency, change fail rate (deployments needing immediate intervention), failed-deployment recovery time, plus now a fifth, deployment rework rate (unplanned deployments caused by incidents). Stock-and-flow reading: deployment frequency is the outflow of a Deployable-Changes stock; lead time is residence time, by Little's law = WIP / throughput; change-fail rate is (1 − FCC) at the *release* stage; recovery time is the time constant of an Incident/Known-Rework stock; rework rate is the rework-generation flow at the deploy stage.

**Reinertsen** (*Principles of Product Development Flow*, 2009): every queue (backlog, review queue, integration queue, test queue, deploy queue) is a stock whose inflow is upstream throughput and whose outflow is capacity-limited; variability + high utilisation blows up queue length, hence cycle time; batch size sets the oscillation amplitude. This is the SD "aging chain" of Ford & Sterman's phase model with explicit capacity constraints.

**Akerele, Ramachandran & Dixon** ("Evaluating the Impact of Critical Factors in Agile Continuous Delivery Process: A System Dynamics Approach", IJACSA 2014): a four-stage pipeline aging chain: Integrated Stories → Automated-Acceptance-Tested Stories → Manually Tested Stories → Delivery Candidates, with failed-AAT stories → reworked → re-tested; rejection rate driven by TDD, pair programming, customer involvement, tester skill, schedule pressure.

**Technical debt** — Franco et al., "An Analysis of Technical Debt Management Through Resources Allocation Policies in Software Maintenance Process" (SD Conference/arXiv 2016): S: Backlog (FP), Production Library (FP in operation), Technical Debt principal (man-hours), Maintenance Team. F: new requirements = library × 0.07/yr → Backlog; perfective maintenance Backlog → Library at min(effort × productivity, Backlog); preventive maintenance drains Technical Debt; debt accrues as a fraction (0.3) of perfective effort × refactoring overhead (2). R: Maintainability = exp(−k × TechnicalDebt), Productivity = nominal × Maintainability. L: R1 growth; B1 "increasing complexity" (debt → ↓ productivity); B2 repayment policy (allocation shifts to preventive when productivity ratio falls, with a 12-month perception delay). Lavazza, Morasca & Tosi, "Optimized Technical Debt Management in Timed-boxed Development Processes" (2018/2019) model sprint-level fix-now / threshold / debt-sprint policies.

## 5. Synthesis: common core and what a git/gate/deploy/test/event log can measure

**Minimal shared structure.** Every model above is one aging chain with a co-flow of defects:

Work To Do —(progress = effort × productivity)→ Work Done, of which (1 − FCC) is Undiscovered Rework —(discovery, delay τ or probability p per inspection)→ Known Rework —(rework)→ back to Work To Do (or directly re-done). Defect injection = progress × injection density; defect discovery = f(test effort, efficiency); escape = injection − discovery at release. The three parameters that matter everywhere are productivity, FCC (or defect density), and the discovery delay; every named loop modulates one of those three through effort, staffing, pressure, or accumulated debt.

**Mapping to an agentic pipeline with git, merge-gate log, staging-deploy log, test results, event log:**

Directly measurable stocks/flows:
- Work To Do, Work In Progress: ticket/worktree states in the event log (counts and ages).
- Gross progress: merge-gate *landed* events (tasks/time) and diff size (code volume co-flow).
- Known Rework: tickets reopened/returned, *rejected* and *conflict* gate runs, failing tests on landed code, bug tickets; its inflow is the rework-discovery rate.
- Release flow and DORA throughput: staging-deploy log gives deployment frequency; commit timestamp → deploy timestamp gives lead time; deploys followed by *base broken* or rollback give change-fail rate and recovery time.
- Queues (Reinertsen): time-in-state per ticket between events (awaiting review, awaiting gate, awaiting deploy); Little's law checks WIP = throughput × residence time.
- Staffing/effort: agent-run durations and concurrency from the event log; "experience" has no agent analogue, but model/prompt version is the equivalent cohort variable.

Inferred stocks:
- **Undiscovered Rework** cannot be observed; infer it from the discovered-rework series: with first-order discovery, discovered(t) = U(t)/τ, so U ≈ τ × discovery rate, and τ is estimated from the lag between a commit and the first rework event citing it (git blame on fix commits is the standard "defect introduction → detection" interval estimator). Phase-based capture-recapture (defects found by independent reviewers/tests) gives a second estimate of remaining defects.
- **FCC / injection rate**: fraction of landed changes later touched by a fix commit, rejected at gate, or implicated in a broken base. Because discovery is incomplete, the observed discovered-rework rate is a **lower bound** on the injection rate; the gap closes as t → ∞, so estimate FCC on cohorts old enough (> several τ) and correct younger cohorts by the empirical discovery curve (the standard "defect aging"/growth-curve approach from reliability engineering).
- **Escaped defects** (Madachy) at the deploy boundary: incidents/rollbacks per deploy; lower-bound again.
- **Technical debt** (Franco): not a log quantity; proxy by the drift in productivity ratio (landed tasks per agent-hour vs. early baseline) and by rework-per-change trend; refactoring commits are the repayment flow.
- **Test suite as a stock** (absent in the literature): count tests and coverage from test results; its inflow is tests added per landed change; detection efficiency p can then be estimated as (defects caught by gate)/(defects caught by gate + defects discovered later), stratified by coverage, which gives the model the link Madachy only parameterises.

Sources: Cooper (1980) *Interfaces*; Lyneis & Ford (2007) *SDR* 23:157–189; Lyneis, MIT OCW ESD.36 Lectures 7–8 (2012); Ford & Sterman (1998) *SDR* 14:31–68 and (2003) *Concurrent Engineering* 11:177–186; Gozluklu & Sterman (2022); Rahmandad & Hu (2010) *SDR* 26; Abdel-Hamid & Madnick, "Lessons Learned from Modeling the Dynamics of Software Development", *CACM* 32(12), 1989 and *Software Project Dynamics* (1991); Thakurta & Dasgupta (2011) arXiv:1108.1447; Madachy, *Software Process Dynamics* (2008), "System dynamics modeling of an inspection-based process" (ICSE 1996), Madachy, Boehm & Houston, "Modeling Software Defect Dynamics" (USC-CSSE-2010-509); Farshchi, Jusoh & Murad (2012) *ComSIS* 9(2); Akerele, Ramachandran & Dixon (2014) *IJACSA* 5(3); Franco et al. (2016) arXiv:1609.06868; Lavazza, Morasca & Tosi (2018/2019); DORA, "DORA's software delivery metrics: the four keys" (dora.dev); Reinertsen (2009); Little (1961).
