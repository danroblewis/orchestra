# Operationalizing discovered system dynamics models

How SD Lab's discovered models (stocks, flows, rate equations, hidden stocks, declared boundaries) could be used
in day-to-day operations, especially SRE at an organization with hundreds of services. Written 2026-10-22 from a
conversation with the user, a survey of SD Lab's own tools, and a literature search (sources at the end).

## The problem this answers

System dynamics models fall out of sync with the systems they describe. Organizations that use SD keep large
staffs to maintain them. SD Lab automates discovery, but three facts shape how its models can be used:

- **Discovery is slow, and gets slower with size.** On kubernetes rungs 300-311, run time grows roughly with
  the square of the number of flows (milp nearer the 4th power), and long runs take 3-17x the short ones. A
  20-flow model takes 1-30 minutes; the 68-flow 317 is predicted to take hours.
- **Accuracy is uneven and sometimes unknowable.** Some numbers are data-limited (310's OOM table under counting
  noise); some structures cannot be told apart (309's move vs link). A found model can "fit" without being proven.
- **A model reflects its method.** Two strategies can find different, equally fitting models of the same data.

So the realistic goal is not a perfect model in seconds. It is a model that is **always available, always
improving, honest about its confidence, and cheap to check against new data.** The uses below are sorted by
category, and each says what level of trust it needs.

## How much trust a use needs

| level | what you need | examples |
|---|---|---|
| **T1 Orientation** | a model that roughly fits; bias accepted and stated | maps, onboarding, brainstorming, agent orientation |
| **T2 Comparison** | the same method on both sides, so its bias cancels | day-over-day diffs, before/after a change, service vs service |
| **T3 Forecast** | held-out forecast skill with an interval | capacity, risk calendar, error-budget burn |
| **T4 Attribution** | identifiable numbers with standard errors | OKR credit, causal claims, change-risk scores |
| **T5 Proof** | proven structure (`algebra.py` equivalence, Z3 identifiability) | "this flow is new" as an alert, automated rollback |

Most of the value is at T1-T3, which today's models can already reach. T4-T5 need the confidence tooling to work
without the truth (see Foundations).

## Foundations: what every use needs

These are not uses themselves, but most ideas below depend on them. Existing pieces in **bold**; gaps in *italics*.

- **F1. A model registry over time.** Every discovered model stored per system per day, with the data window, the
  strategy, its commit and its confidence. *Gap: the result store is keyed by ladder case, not by real system.*
- **F2. Found-vs-found diff.** **`diff.py` / `sdlab-ladder diff`** already diffs a found model against the truth as
  a git diff with hunks. *Gap: a small adapter to diff two found models (yesterday vs today).*
- **F3. Two-speed maintenance.** A cheap filter tracks the numbers continuously (**`refine.py`** refits numbers on
  a fixed structure; **kalman_lna** has the Kalman machinery); slow structural discovery runs only when the
  filter's errors stay biased. *Gap: no online or streaming estimation yet.*
- **F4. Warm start.** **`opts.known`** already lets discovery explain only what a current model misses. *Gap: no
  strategy starts its search from yesterday's model.* A "one edit away" search (add, drop or swap one flow), as in
  abrupt-SINDy, avoids most of the cost that grows with flows².
- **F5. Confidence without the truth.** **`notruth.py`** (residual whiteness, invariance across eras and halves,
  held-out forecasts), **`evidence_confidence.py`** (P(right), AUC 0.87 on the ladder), **`holdout.py`**.
  *Gap: the push test, Cramér-Rao bound, `analyse` and Z3 identifiability still need the truth; forecasts have no
  intervals; none of this is on the pages yet.*
- **F6. Per-service decomposition.** **Rungs 313-317** and the **`blockwise`** strategy (blocks of ≤ 12 stocks) are
  the start. *Unproven: no system larger than 317 (36 stocks, 68 flows) has been discovered.*
- **F7. Prometheus in, models out.** **`promql.py`**, **`promlab/`** and the cases' `query:` strings exist.
  *Gap: discovery on real Prometheus data has not been shown to work.*

## Ideas

Ideas the user brought are marked **(yours)**. Each gives the trust level it needs and what it builds on.

### A. Change detection and model maintenance

1. **Daily model diff as a change report (yours).** Discover each system daily, diff against yesterday, and list
   typed edits: flow added or removed, a rate's form changed, a number moved beyond its interval, a hidden stock
   appeared. Trace each edit through the model to the stocks it affects. *T2; F1, F2.*
2. **Join diffs to change events.** Attach each edit to that day's deploys, config changes and incidents, as
   Azure's Gandalf does for rollouts. An edit with a matching deploy is explained; one without is a lead. *T2.*
3. **Residual watch on yesterday's model.** Run today's data through yesterday's model and watch where it stops
   fitting. This takes seconds, unlike re-discovery, and the residual sits on one stock's balance, naming which
   flow is wrong or missing. *T3; F3.*
4. **Change points trigger re-discovery.** Run change-point detection on those residuals (**`changes.py`** PELT, or
   Bayesian online change points) and re-discover only the windows and services that changed. *T2; F3, F4.*
5. **Drift before break.** Track each number in the filter; a parameter that drifts steadily (a retry gain
   creeping up) is an early warning before a structural change. *T3; F3.*
6. **Proof-backed alerts.** Raise an alert only when the new structure is proven different (**`algebra.py`** shows the
   net rates differ for some state) and identifiable from the data. Everything else is a note. *T5.*
7. **Cosmetic vs real changes.** Use **`algebra.py`** equivalence to drop diffs that are only a redrawing of the same
   equations (a move vs a link plus drain), so the change report shows only real edits. *T2.*
8. **Model health dashboard.** Per system: last discovery, confidence, forecast skill over the last week, open
   diffs. This replaces the maintenance staff's mental list of which models are stale. *T1.*
9. **Model-maintenance work queue.** When confidence drops or a diff is unexplained, open a ticket for a person (or
   an agent) to confirm, label or reject the edit; labelled edits train the confidence model. *T2.*

### B. Continuous, incremental modelling (the operating mode)

10. **Always-on discovery (yours: continuous refinement).** Keep one discovery process per system running, start
    each run from the current model, and publish a better model whenever one beats it on held-out data. The model
    on hand is always the best so far. *T1-T3; F3, F4.*
11. **Anytime models.** Report a model at every stage of the search with its confidence, so a slow search still
    answers something useful after a minute and improves over hours. milp already improves a best answer until
    its time limit. *T1.*
12. **Budgeted search by value.** Spend discovery CPU where it pays: services with recent incidents, low
    confidence, unexplained diffs, or high business value. *T1.*
13. **Fold in new data automatically.** The editor's **"Keep discovering"** already re-runs as steps arrive; the
    operational version re-fits numbers continuously and re-searches structure on a slower clock. *T3; F3.*
14. **Experiments to settle ambiguity.** When two structures fit equally well (309's move vs link), propose the
    smallest safe experiment that would tell them apart (a load step in staging, a feature-flag toggle) and
    record which one the experiment confirms. *T4.*
15. **Model library across services.** Services built from the same template probably share structure; discover
    one, then start the others from it and only check the numbers. *T2; F4, F6.*

### C. Reliability and incident analysis

16. **Metastability scan.** Look in each model for reinforcing loops (retries → load → latency → retries) and
    their tipping points, and publish a safe-load envelope per service. Metastable failures (Bronson et al.) are
    exactly these loops. *T3.*
17. **Incident replay.** Run the model through an incident's inputs to see which loop drove it and when it could
    have been stopped. *T3.*
18. **Model-backed postmortems.** Use the discovered model as the "process model" in a CAST/STAMP postmortem: what
    the autoscaler or the on-call believed versus what the model says the system did. *T1.*
19. **Detect a hidden stock in production.** A newly inferred hidden stock (as milp found 310's memory leak) points
    at something unmeasured accumulating: a leak, a backlog, a cache. Flag it with the stocks it reads. *T2-T3.*
20. **Early warning from loop dominance.** Watch which loop dominates the dynamics; a shift from a balancing loop
    (autoscaling) to a reinforcing one (retry storm) is a warning before an outage. *T3.*
21. **Alert thresholds from the model.** Set alerts on stocks at the level where the model says a limit will be
    crossed within N minutes, instead of fixed thresholds. *T3.*
22. **Blast-radius map.** From the multi-service models, list which services a stock change propagates to and how
    fast, for incident triage. *T1-T2; F6.*

### D. Capacity and performance planning

23. **Capacity projections (yours).** Run the model forward under forecast traffic to find when each capped flow
    (`min(0.5 × pending, 4 × nodes − ready)`) saturates. *T3.*
24. **Headroom per service.** From the discovered caps and service rates, compute spare capacity and the load at
    which queues start growing (Little's law plus the fitted rates). *T3.*
25. **Autoscaler tuning offline.** Simulate HPA targets, cool-downs and node-pool sizes against real traffic in the
    model before changing production. *T3.*
26. **Scaling curves.** Fit Universal Scalability Law-style curves from the discovered capacity flows to project
    throughput at higher concurrency. *T3.*
27. **Seasonality-aware planning.** Daily and weekly cycles are the most common structure in operations data
    (`docs/research/periodic-inflows.md`); plan capacity on the peak the model projects, not on last week's peak. *T3.*
28. **Cost of capacity (FinOps).** Attach a cost to each stock (nodes, pods, memory) and simulate the cheapest
    configuration that keeps queues bounded. *T3.*

### E. Risk

29. **Risk calendar (yours).** Simulate known future inputs (launches, seasonal peaks, certificate and quota
    expiries, maintenance windows) through the current models and mark the days a stock is projected to cross a
    limit. *T3.*
30. **Change risk for code going to production (yours).** Score a change by how often past deploys to that service
    were followed by a structural edit in its model, and by how close the service runs to a tipping point today. *T2-T3.*
31. **Change-impact preview.** For a planned config change (a timeout, a retry count, a pool size), edit that number
    in the model and simulate the result before rollout. *T3-T4.*
32. **Rollout guard.** During a rollout, compare the canary's fitted numbers with the baseline's; a significant
    difference in a flow's rate is a reason to stop. *T4.*
33. **Dependency risk.** Find services whose stocks feed many others (a shared database, as in 316) and rank them
    by how much a slowdown there spreads. *T2; F6.*
34. **Error budget as a stock.** Model the SLO error budget as an explicit stock drained by incident inflow and
    forecast when it runs out. *T3.*

### F. Measuring outcomes: OKRs, attribution, prioritization

35. **OKR targets from the model (yours).** Set targets on the model's numbers and stocks (retry amplification below
    0.2), with the model's prediction of what that does to user-facing outcomes. *T3-T4.*
36. **Validate outcomes (yours).** After a project ships, compare the before and after models: did the targeted
    number actually move, and did the predicted outcome follow? *T2-T4.*
37. **Causal attribution (yours).** Run the "before" model on the "after" inputs as the counterfactual, and compare
    with what happened (CausalImpact-style intervals). Other services that did not change serve as controls. *T4.*
38. **Leverage ranking.** The editor's **Leverage panel** already ranks flows by how much a 10% change moves the
    goals. Use it to pick small changes with large effects (yours: maximize the impact of small changes). *T3.*
39. **Meadows level per project.** Tag each SRE project by where it intervenes (a number, a buffer, a loop, an
    information flow, a rule) and favour the higher levels. *T1.*
40. **Credit for prevention.** Simulate the incidents a fix avoided, so reliability work that prevents problems
    gets measured credit (Repenning and Sterman, "nobody ever gets credit for fixing problems that never
    happened"). *T3-T4.*

### G. AI agent orchestration

41. **Goals and resources as stocks (yours).** Model what the agents should accomplish (features shipped, incidents
    closed) and what they consume (tokens, CPU, review time) as stocks, and use the model for orientation and
    steering: which goal stock is lagging, which resource will run out. *T1-T3.*
42. **Agents as the machines that cause flows (yours).** Mark the flows an agent is expected to drive, measure the
    actual flow rate per agent-hour, and track effectiveness as a fitted number with an interval. *T3-T4.*
43. **Design agents against the model (yours).** Before building an agent, state how it should change the model
    (this flow up by X, that queue down); after deploying it, discover the model again and compare. This mirrors
    the ladder's own refinement loop. *T2-T4.*
44. **Work as stocks by state.** Tickets in backlog, in progress, in review, merging, done; rework shows up as a
    review → backlog flow. Orchestra's ticket states map directly onto this. *T2-T3.*
45. **WIP control by model.** Set the concurrency dial from Little's law and the fitted service rate, and find the
    bottleneck stage from where queues grow (theory of constraints). *T3.*
46. **Capability-trap monitor.** Track the share of agent effort spent on fixes versus capability work, and whether
    incident inflow falls as capability work accumulates. *T3.*
47. **Model as the planner's objective.** An agent chooses actions by simulating their effect on the goal stocks,
    instead of by prompt alone. *T3.*
48. **Agents maintain the models.** Agents review unexplained diffs (idea 9), propose labels or experiments, and
    write the change report, so the "large staff" that maintains SD models is partly automated. *T1-T2.*

### H. Design, what-if and architecture

49. **Architecture review with a model.** Before splitting or merging services, simulate the proposed structure
    with the current numbers to see new queues and loops. *T3.*
50. **Retry and timeout policy design.** Simulate retry budgets, backoff and timeouts against the discovered retry
    loop to find settings that cannot tip into a storm. *T3.*
51. **Load-shedding and backpressure design.** Test where to add a cap (a `min` flow) to keep the system stable
    under overload. *T3.*
52. **Migration planning.** Model the old and new system during a migration (traffic shifting between two flows)
    and find the safe pace. *T3.*

### I. Observability quality

53. **Find missing metrics.** A hidden stock that discovery keeps inferring points at something worth measuring;
    propose the metric. *T2.*
54. **Find useless or redundant metrics.** Stocks the model never needs, or that are exact copies of others (309's
    near-collinear counters), are candidates to drop. *T2.*
55. **Metric correctness checks.** A stock whose measured balance never closes (inflows minus outflows do not match
    its change) suggests a broken or mislabelled metric. *T2.*
56. **Boundary review.** The declared boundary (`boundary:`) is an explicit statement of what enters and leaves a
    service; review it with the service owners as documentation that can be checked against data. *T1.*

### J. Learning and communication

57. **Game-day microworlds.** Turn each discovered model into a practice environment where engineers run an incident
    with the real dynamics and delays (like the Beer Game). *T1-T3.*
58. **Onboarding maps.** The model's diagram is a map of how a service behaves, generated rather than drawn, and
    kept current by the daily discovery. *T1.*
59. **Plain-language change notes.** Turn each day's diff into a short note for the service's owners ("retries now
    drain 30% slower; started after Tuesday's deploy"). *T2.*
60. **Shared vocabulary across teams.** Stocks and flows give SRE, product and leadership one language for queues,
    capacity and risk. *T1.*

## What to try first

In order, each small enough to do on its own:

1. **Found-vs-found diff (F2)** on two ladder results of the same strategy (for example two commits). The adapter is
   small and enables ideas 1, 2, 7, 36 and 59.
2. **Residual watch (idea 3)** on a kubernetes case: fix the model found on one seed and run it on the next seed with
   a scheduled change. This shows whether a cheap check catches a structural change without re-discovery.
3. **Warm-start search (F4)** in one strategy: start from a given model and search only one edit away. Measure time
   against a full search on rungs 310-312.
4. **One real service (F7):** discover a model from real Prometheus data for one service and look at it with its
   owners. This needs the user's approval (probing a live system, CLAUDE.md rule 16).
5. **Decomposition (F6):** 313-317 test it; the first system larger than 317 would be the first evidence for (or
   against) the per-service approach at work-scale (430 services).

## Sources

From the literature search (2026-10-22); see the conversation for the full notes.

- Struben, Sterman and Keith, parameter estimation and confidence in SD models: https://mitmgmtfaculty.mit.edu/jsterman/parameterandconfidence
- Particle filtering for SD models (2007): https://proceedings.systemdynamics.org/2007/proceed/abstracts/346.htm
- Ward et al., continuous calibration of a digital twin: https://arxiv.org/abs/2011.09810
- Out-of-sync detection for digital twins: https://arxiv.org/pdf/2505.11847
- Quade et al., abrupt-SINDy (fast model recovery after abrupt changes): https://arxiv.org/abs/1803.00894
- Bronson et al., metastable failures in distributed systems: https://brooker.co.za/blog/2021/05/24/metastable/
- Gunther, Guerrilla capacity planning and the Universal Scalability Law: https://highscalability.com/guerrilla-capacity-planning-and-the-law-of-universal-scalabi/
- Google SRE Workbook, error budget policy: https://sre.google/workbook/error-budget-policy/
- Huang, Zhang et al., causal discovery from changing data (CD-NOD): https://jmlr.org/papers/v21/19-232.html
- Gan et al., Sage, causal root cause analysis for microservices: https://www.csl.cornell.edu/~delimitrou/papers/2021.asplos.sage.pdf
- Li et al., Gandalf, safe deployment at Azure: https://www.usenix.org/conference/nsdi20/presentation/li
- Brodersen et al., CausalImpact: https://arxiv.org/abs/1506.00356
- Repenning and Sterman, the capability trap: https://cmr.berkeley.edu/2001/08/43-4-nobody-ever-gets-credit-for-fixing-problems-that-never-happened-creating-and-sustaining-process-improvement
- Meadows, leverage points: https://donellameadows.org/archives/leverage-points-places-to-intervene-in-a-system/
- Nolan, STAMP for SRE: https://www.usenix.net/system/files/login/articles/spring20_10_nolan.pdf
- Control-theoretic views of AI agents (2026): https://arxiv.org/html/2603.10779 and https://arxiv.org/abs/2606.30877
