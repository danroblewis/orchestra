# How work is reviewed

The owner's standard: "clean codebases with nothing unnecessary in them" and reviews that check
"we're doing the right thing," not only that the code is right. Every implementation phase is
followed by reviews that re-engage the implementor until a judge says nothing of weight remains.
The reviews are workflows in `.claude/workflows/`, run with the Workflow tool and a shared brief
that states the scope of each repository and the constraints that bind every agent.

## 1. Layered review (`layered-review.js`)

Four independent reviewers read the same repository, then a triage judge, then the implementor.

| Lens | Asks | Must do |
|---|---|---|
| Code | Is it correct, dead-code free, tested against the real contract, lint clean, one purpose per module? | Run the suites and ruff; read the recent diffs |
| Requirements | Is this the right thing for the end goal? Does the repo contain exactly its scope? Are the README's claims true? | Follow the README as a stranger, timed; test "a machine in a page" by writing one |
| Design | Boundaries, names, contracts and their documentation, config and state layout, error paths, "one reason to exist here" | Check the docs against the code |
| User experience | Can an operator read the state at a glance; do names and badges tell the truth; is anything stale, broken or lying? | Start the demo, screenshot every page at desktop and phone width, judge the CLI too |

The triage judge merges duplicates, confirms each finding against the code (reviewers are wrong
sometimes), drops taste and anything outside the brief or reserved for the owner, and writes a
work list an implementor can execute without reading the reviews. Severity: *must* violates the
brief or breaks the system; *should* a careful owner would insist on; *nice* is dropped unless
trivial beside another fix. Up to three rounds; the next round's reviewers are told what was
fixed and asked what was missed.

## 2. UX review panel (`ux-review.js`)

For user-facing work, a stronger form. Personas use the running UI without reading the code:
a new operator ("is it healthy, what is it doing?"), an SRE on call at 3am ("what is stuck, why,
who acts?"), the owner reviewing the model ("where does each number come from?"), a developer
who wrote a machine ("does it show up, take work, misbehave visibly?"). Each keeps a journey log
with timings and misunderstandings. Then three experts judge the journeys and screenshots:
information design (hierarchy, density, colour for meaning only, consistent names), honesty (does
the UI lie: stale as live, "running" for a dead process, a count that excludes something, an
empty state with no reason), and front-end consistency (components, CSS leaking between plugins,
phone width, console errors). Triage, fix with before/after screenshots, repeat.

## 3. Model acceptance (`model-acceptance.js`)

For discovery and metrics: run a use case from [use-cases.md](use-cases.md), discover, and have a
modeller judge the model against the expected structure, naming the cause of every miss
(discovery bug, metric naming, too little data, wrong expectation). A pass is attacked by three
skeptics from different angles (structure, data sufficiency, honesty) and stands only if two of
three fail to refute it. Confirmed discovery bugs are fixed in Orchestra with a synthetic unit
test; metric naming is fixed in the package that writes the series.

## 4. Subtraction audit (`subtraction-audit.js`)

Before a release or after moving code: one auditor per repository whose only question is "should
this exist here?", with the forbidden words for that repository, a justification for every file,
dead definitions, docs for absent things, unused dependencies; plus an auditor for each contract
between repositories (same names, fields and semantics on both sides; documented once per side).
The judge's default answer is removal; keeping needs a reason the brief supports.

## 5. Expert reviews of a sample

When a sample project is run for real, three experts review the result: a system dynamics
modeller (is the model meaningful by the criteria in use-cases.md; are the series named right),
an observability and information-design expert (does the event map say who publishes and who
listens; are sources and names consistent), and a product reviewer (does the sample show the
good parts; what would a new user do first and where would they get stuck). Same triage and fix.

## 6. The critic

While the owner is away, a critic runs on a timer with the goals file and gathers evidence
itself (greps, tests, git state, journals, screenshots), marks each goal done, partial, not
started or broken, and names the one thing to do in the next hour. It is told to disagree by
default; "probably fine" is not an allowed finding. Its reports accumulate so the next one can
see what has not moved.

## When each runs

| After | Run |
|---|---|
| An implementation phase on any repository | Layered review |
| UI work, or before a release | UX review panel |
| A change to discovery or to any package's metrics | Model acceptance on the affected cases |
| Moving code between repositories; before a release | Subtraction audit |
| A real sample run | Expert reviews |
| Every hour unattended | The critic |

## What a review may not do

Decide the owner's open questions ([decisions.md](decisions.md)); propose features the brief puts
out of scope; tune a model to pass; mark its own work clean. A reviewer writes only in the
scratch directory; only the implementor commits, and nobody pushes.
