# A system-dynamics view of an AI software foundry

(Independent answer from a research agent given the same question as `foundry-sd-gemini.md`, 2026-10-14.)

## 1. Is it a good idea?

Yes, with one caveat. System dynamics (SD) is the right tool for exactly the question you are asking: not "which task next" but "which policies and feedback loops produce good software at a steady rate." Software management has been modeled this way for 40 years, and the central lesson of that literature is precisely your instinct about tickets. Cooper's rework cycle (1993) splits "work done" into *work really done* and *undiscovered rework*; a ticket closing moves work into the first stock from the manager's point of view, but part of it actually lands in the second. Your foundry's whole design problem is to make that hidden stock visible early.

The caveat: SD models aggregates (rates per week, not individual agents). It is a policy design tool, not a scheduler. Use it to decide which agents and gates to add; use the loop itself to dispatch.

## 2. Prior models and their actual structure

**Abdel-Hamid and Madnick, *Software Project Dynamics* (1991).** Four interlocking subsystems: human resources, software production, control, and planning (100+ causal links). Stocks: tasks not yet developed, tasks developed, tasks tested; errors as a chain of *undetected active errors* (which generate further errors) and *passive errors*, flowing through *detected errors* and *reworked errors* via error-generation, detection, and rework rates; workforce split into *newly hired* and *experienced*, with an assimilation flow and training overhead (Brooks's law). The control subsystem compares *perceived* progress to the plan; the gap drives schedule pressure, which raises productivity but also error generation. Key loops: schedule pressure → corner-cutting → more errors → more rework → more pressure (reinforcing); hiring → training drag → slower (balancing, then reinforcing). Their finding: built-in management policies can guarantee the schedule is missed.

**Cooper's rework cycle (1993) and Lyneis and Ford, "System Dynamics Applied to Project Management," *System Dynamics Review* 23 (2007).** Four stocks: *Original work to do → Work done*, but work done splits by a quality fraction into *Work really done* and *Undiscovered rework*; a discovery flow (with a long delay) moves undiscovered rework into *Rework to do*, which feeds back into the work queue. Ripple-effect loops: schedule pressure lowers quality; fatigue, experience dilution, and out-of-sequence work lower productivity. Lyneis calls undiscovered rework the single most important driver of overruns. Rahmandad and Hu (2010) extended it to multiple defects per task, showing a few tasks cycling repeatedly can dominate duration.

**Madachy, *Software Process Dynamics* (2008; dissertation 1994).** Reusable building blocks: a Brooks's-law model; an error chain of *generation → undetected errors → detection (by inspection or test) → rework*; and an inspection model estimating effort and efficiency of different defect-removal practices. His 2006 NASA tool is explicitly a defect-generation-and-detection simulator.

**Repenning and Sterman, "Nobody ever gets credit for fixing problems that never happened" (2001; *ASQ* 2002), and Repenning, Gonçalves and Black, "Past the Tipping Point" (2001).** Stocks: *process capability* and *performance*. Two loops driven by a performance gap: *work harder* (fast, balancing, but erodes capability) and *work smarter* (slow, invests in capability). Because improvement benefits are delayed, working harder wins and capability decays: the capability trap. The firefighting model adds a threshold: above a resource-utilization level, firefighting spreads from one project to the whole portfolio and becomes self-sustaining.

**Cao, Ramesh and Abdel-Hamid, "Modeling Dynamics in Agile Software Development," *ACM TMIS* (2010).** Sub-models for planning/control, refactoring and design quality, change management, and customer behavior. Delayed refactoring raises change cost cyclically; customer-feedback quality is critical.

**Technical-debt SD models.** Lavazza, Morasca and Tosi (2018–19) simulate debt-removal policies in time-boxed sprints (fix immediately, threshold, dedicated sprint). An AnyLogic model (arXiv 1609.06868, 2016) uses four stocks—backlog, production library, technical debt, maintenance team—and shows perfective work crowding out preventive work raises debt and backlog.

## 3. A stock-and-flow model for the foundry

Every stock below is counted from git, the gate log, test results, or the agent event log.

| Stock | How measured |
|---|---|
| **S1 Specified, not implemented** | Acceptance tests (or spec items) that exist on main but are failing/skipped, from the latest acceptance run. |
| **S2 Work in progress** | Worktrees with commits ahead of main; agent event log shows an owner. |
| **S3 Submitted, awaiting gate** | Builds in the gate queue, from the gate log. |
| **S4 Landed on main** | Commits merged by the gate (gate log joined to git). |
| **S5 Accepted features** | Acceptance tests passing against the staged artifact. |
| **S6 Known defects** | Tests that passed on a prior main build and fail now, plus gate rejections not yet resubmitted. |
| **S7 Rework in flight** | Commits touching lines added in the last N days (GitClear's churn definition) and resubmissions after gate failure. |
| **S8 Test capital** | Count of tests, line coverage, and mutation score on main. |
| **S9 Debt proxies** | Duplicate blocks ≥5 lines, complexity, lint violations, TODOs, from static analysis per main commit. |
| **S10 Agent capacity** | Agent-minutes (or tokens) per week, bucketed by activity (implement / test / review / fix) from the event log. |

Flows: spec→S1 (acceptance tests authored), S1→S2 (start), S2→S3 (submit), S3→S4 (gate pass) or S3→S7 (gate fail), S4→S5 (acceptance pass), S4→S6 (regression discovery), S6→S7→S2 (fix), S4→S9 (debt accrual), S9↓ (refactor commits).

## 4. Hidden stocks and how prior models estimate them

- **Undiscovered rework / latent defects** (the Cooper stock). Abdel-Hamid assumes an error-generation rate per task that rises with schedule pressure and a detection rate set by QA effort; Lyneis and Ford calibrate the discovery delay by fitting simulated to actual cumulative rework. Practical estimators: capture–recapture from the overlap between independent reviewers (Eick et al. 1992; Briand et al. 2000 warn it is noisy), time-shifted escape ratio (defects found at stage *k+1* that stage *k* should have caught), and mutation score as an estimate of how much the test suite cannot see.
- **True completion fraction.** Abdel-Hamid separates *perceived* from *actual* progress; the "90% syndrome" is their gap. Your version: ticket-closed count vs. acceptance-tests-passing count.
- **Design quality / debt.** Cao et al. and Lavazza et al. model it as a stock that raises change cost; observable only through its effect: lead time per accepted feature rising while feature size is constant.
- **Agent capability.** Repenning and Sterman's capability stock; observable via first-pass gate rate per role over time.

## 5. The loops and the signal for each

**B1 Defect removal.** S6 → fix work → S6 falls. Signal: median time from regression-introducing commit to fixing commit; it should be short and stable.

**B2 Discovery pull-forward.** Test capital grows → defects found earlier. Signal: histogram of *where* defects are caught (worktree tests, gate, acceptance, post-merge) shifting left; discovery delay falling.

**B3 WIP limit.** Gate queue grows → pause new workers. Signal: S3 bounded; gate wait time not trending up.

**R1 Firefighting spiral** (Repenning). Rework consumes S10 → less test authoring → more latent defects → more rework. Signal: rework share of agent-minutes rising week over week; churn above baseline (GitClear reports roughly doubled churn in AI-era repositories).

**R2 Debt drag** (Cao; Lavazza). Duplication raises change cost → throughput per agent-minute falls → pressure → more corner-cutting. Signal: duplicate-block ratio rising with lead time per accepted feature.

**R3 Capability reinvestment** (the good loop). Investment in tests and tooling → higher first-pass gate rate → freed capacity → more investment. Signal: first-pass gate rate rising while S10 is constant.

Two AI-specific priors: METR's 2025 RCT found experienced developers 19% slower with AI tools while believing they were 20% faster, and Veracode's 2025 report found LLMs chose the insecure option in 45% of cases. Both say the same thing in SD terms: the AI-agent foundry has a *larger* undiscovered-rework fraction than a human one and a bigger perceived-vs-actual gap, so the discovery loops matter more than throughput loops.

## 6. What an operator should look at first

Look at the **defect-discovery histogram and rework share** before anything else, because a new agent is a new flow and it should be attached where the largest hidden stock sits:

1. If most defects surface after the gate (acceptance or post-merge), add a reviewer or test-author agent upstream of the gate; B2 is weak.
2. If gate first-pass rate is low and failures are test-related, add a test-author agent that writes acceptance tests before implementation (fills S1 properly).
3. If churn concentrates in code under a week old, agents are patching their own work: tighten the worker's definition of done or add a pre-submit reviewer.
4. If duplication rises and lead time per feature rises, add a refactor agent with a debt threshold policy (Lavazza et al. show timing matters).
5. If rework share of agent-minutes exceeds roughly a third and climbs, you are past Repenning's tipping point: reduce intake (B3) before adding any producer.

Tickets measure *work done*. Acceptance tests passing on a gated build measure *work really done*. Build the model around the second, and treat every other stock as an estimate of how far the two have drifted.

Sources: Abdel-Hamid & Madnick 1991 (https://archives.albany.edu/downloads/bc3872781); Lyneis & Ford 2007 via MIT ESD.36 (https://ocw.mit.edu/courses/esd-36-system-project-management-fall-2012/554b8ec26c472d4d43f0f2b19b4899b0_MITESD_36F12_Lec08.pdf); Rahmandad & Hu 2008/2010 (https://proceedings.systemdynamics.org/2008/proceed/abstracts/386.html); Madachy, Software Process Dynamics 2008; Repenning & Sterman working paper (https://dspace.mit.edu/bitstream/handle/1721.1/1815/4372-02.pdf); Past the Tipping Point (https://cmr-mig.berkeley.edu/2001/08/43-4-past-the-tipping-point-the-persistence-of-firefighting-in-product-development); Cao, Ramesh & Abdel-Hamid 2010 (https://calhoun.nps.edu/entities/publication/bd84e2c3-2e50-4feb-bafe-8d13ba3bc02c); Lavazza et al. (https://irinsubria.uninsubria.it/handle/11383/2082134); TD maintenance model arXiv 1609.06868; capture-recapture (https://www.lunduniversity.lu.se/lup/publication/282e2518-f7d2-49e0-bd9c-49934bcf9849); DORA metrics history (https://dora.dev/guides/dora-metrics/history/); DORA rework rate (https://cd.foundation/blog/2025/10/16/dora-5-metrics/); GitClear churn (https://leaddev.com/software-quality/how-ai-generated-code-accelerates-technical-debt); METR RCT arXiv 2507.09089; Veracode 2025 report.
