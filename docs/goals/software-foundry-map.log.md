# Software foundry map: review rounds

Each round: a fresh expert reviewer in a real browser against the live automata project,
then fixes, tests, a web restart, and a commit.

## Round 0 (build, 2026-10-14)

Spec step 1 built: `foundry.py`, `foundrygit.py`, `foundrymetrics.py`, `/api/foundry`, the
Agents page section "The foundry". Own screenshot pass fixed a global `svg { min-height:600px }`
rule, label collisions, and box heights before the first review.

## Round 1 (2026-10-14)

Reviewer's verdict: not understandable and correct. Numbers reproduced from the log, but:
review send-backs were mostly reviewer timeouts counted as rejections (44% pass shown, ~91%
on evidence); the 7 gate "defects" were one test on one ticket; rework arrows left valves,
not a stock; W in commits with ticket flows; restarts counted as starts; K was "REJECTED now";
L showed a 24h flow as a level; losses drawn as a stock; pre-review check missing; three
"unattended" flows had agents bound; the section rebuilt every 16 s and closed disclosures;
loop rows had no hover; B3/B1 "observed" on event presence; no signal direction; label
collisions, overflow, 7.7 px type; duplicated readings; B5 citation mismatch.

Fixed: send-back causes from reviewer verdict notes (defect vs no verdict) with re-runs after
no-verdict counted as a loss; genuine starts vs re-pickups; K = defect send-backs pending
re-submission; L = commits on main as a level with the day's landings on the pipe; A read
from the deployed build's run with main's latest beside it; B deployed-at from the event;
gate defects concentrated by ticket and failing test (from the stage logs); bad-fix fraction
over fix rounds; U drained into K by the inspections and after landing, injected from W;
pre-review check valve; losses as per-machine sinks; agents on flows derived from wake rules
(`foundry.bound_agents`); signals over the previous window with direction, hints only when
adverse and rising; B3 observed only on system-made capacity changes; loop-row hover; redraw
signature excludes agent time and clock labels and restores disclosure state; width 1400,
labels with units, distinct activity colours; clickable valves only where a drawer exists.

Declined for now: keyboard/touch alternatives to title tooltips (noted, later pass); B5
source kept as Abdel-Hamid (errors build errors is the mechanism; the loop drawn is the
pause-and-repair response).

## Round 2 (2026-10-14)

Reviewer's verdict: not understandable and correct. Confirmed: cause split, gate
classification, U honestly not estimable, the B2 hint, estimators in tooltips, per-machine
sinks. Found: every MERGING→REJECTED was labelled a gate defect, so 4 timeouts and a start
failure leaked into fix rounds (17 vs 11), rework share (47% vs 40%), K's balance; a
same-second tie in History.previous made starts 11 instead of 4; the review pass rate
counted no-verdict reviews as passes (91% vs 80% on verdicts); the seven gate "defects" are
one defect detected seven times; loop-row hover broke on attribute quoting; the chain drew a
post-deploy verification that does not exist; the worker sat on the start flow; two rates on
one pipe; "inspects" and "strengthens" shared one encoding; improve/add-tests solid without a
rate; B5 citation; directions not coloured by adversity; label collisions and 9 px type;
duplicated readings; the hours lost to timeouts not promoted.

Fixed so far (metrics, uncommitted at the time of this entry): gate send-backs classified by
their run's outcome; previous() by log order; review pass on verdicts; distinct defects
beside detections; timeout share per machine; lead-time values.

Direction change from Daniel during this round: the model is data in the repo written by
`orchestra init` (template), curated by agents; and the loops must be *detected* from
agents, events, and stocks, not asserted. A golden test (`tests/unit/test_foundry_golden.py`)
now drives the detector (`foundrygraph.detect`) and the reference configuration together.
The page work (worker valve on implement, verify inside the gate, encodings, per-loop
graphs) follows once the detector passes its golden case, so that the map draws what was
detected.

## Round 3 build (2026-10-14, commit 47d410d)

The model is data (`.orchestra/model/` in the repo, written by `orchestra init` / `orchestra
model init`; the automata repo has it), flows are never declared, and loops are detected by
`foundrygraph` from the stocks and the org. `tests/unit/test_foundry_golden.py` is the
reference configuration and passes: rework cycles through the hidden stock, capability
(with a keeper), earlier detection (with a test author), broken base, re-planning; the WIP
limit is a documented gap. Supervisor tools: list_model, add_model_element,
update_model_element, remove_model_element; org guide section added. Round-2 metric fixes
in. The page draws the detected graph (stocks by row, agents over what wakes them, every
derived link with its sign and the day's count) and each loop as its own ring, detected or
hypothesis, with its signal's direction and a hint only when adverse. On the automata org 4
of 7 expected loops are detected; capability and earlier detection are hypotheses because
the keeper and the QA engineer emit no declared event that fills a stock.

Declined from round 2 for now: keyboard/touch tooltips; a queue-age stock (the spec's W
absorbs the states; ages are on the drill-down).

## Round 3 (2026-10-14)

Reviewer's verdict: not understandable and correct. Readings matched the raw data in every
check but one (resources counted undecided lesson drafts: the declared globs were ignored).
Rejected: the detector's sign assignment (parallel links collapsed by a tie-break; the rework
cycle labelled R because polarity depended on which agent emits the draining transition;
wake-by-outflow as −); map arrow numbers were event-type totals, not attributable flows;
stock declarations off the literature (U drained by APPROVED; L drained by deploy; tests
and really-done filled by gate_landed; no visible review queue); "detected" meant closable
by declaration, not observed; distinct defects counted failing tests; the gate-stage hint
fired on direction, not level; label collisions, nine-pixel type, dash styles with three
meanings, unnamed cards diluting the loops; loop-card hover highlighted an off-screen map;
hypothesis hover missed agents; probe estimators never ran; several hard-coded names.

Fixed: parallel links signed by the dominant mechanism (window event counts), + by default;
conserved material loops (every stock in the cycle filled and drained by agents in it) are
balancing by construction and say so ("B · conserved transfer"); stocks corrected (awaiting
review added; U drained by discovery only; L has no outflow; tests filled by test authoring;
really done by deploy); link numbers only when the log attributes the event to that agent
(by, author, or the transition's source state, REJECTED split by cause); cycles carry
observed/closable from log evidence; distinct defects = tickets with a failing stage; a
"defects found by stage" tile; hints on level conditions; resources honour declared globs;
model probes registered with the Prober; operator capacity changes named as the WIP
controller acting by hand; unnamed cycles collapsed; hypothesis hover fixed; one meaning per
dash style; 10.5 px labels; rows laid out sequentially by hint order so nothing overlaps.

Declined for now: pinning the map while hovering a loop card (the card's own ring is the
primary view); keyboard/touch tooltips; renaming-proof tiles (the tile row reads the
template's stock keys; a project that renames them loses the tiles, noted as a limit in the
guide's next revision).

## Round 4 (2026-10-14)

Reviewer's verdict: not understandable and correct. 16 of 18 readings matched. Found: main's
test state read from a base_broken run's failed candidate instead of its base check (main
has 14 failing, not 1); BLOCKED→OPEN attributed to Orchestra when the coordinator made them
(re-planning shown unseen though it ran 12 times); "observed" required every parallel
mechanism; wake-on-departure as − double-counted the drain's sign; conserved material loops
drawn with + signs and tagged B contradict Sterman (a material circuit has no causal
polarity); dominant-mechanism voting made polarity a function of the window; map link
numbers were event totals that break the design's own balance rule; WIP's declared flows
contradicted its git estimator; rework share's denominator included re-run losses; the 4 s
refresh destroyed hovers; the guide's worked example produced a negative stock (outflow
counted every ticket_created); playable_features duplicated really done; unnamed list had
duplicates; unattached agents looked attached; design section 5 still named flows and old
tool names; the automata model directory is untracked.

Fixed: main's state from base_check; attribution by evidence (the author of a note seconds
before an unblock or cancel) over the table; observed = one mechanism per step, wakes and
triggers included; departures wake +; material circuits carry no polarity and are drawn as
pipes, with "source says B" beside; parallel links are indeterminate from structure, with
the window's dominant sign named; link labels are the design's flows with losses named,
drawn once per mechanism; WIP drained by landing; rework share over productive hours with
re-runs shown as the loss; no rebuild while the pointer is over the section; events
estimator counts an outflow only when a consumer caused it; propose_model no longer offers
a duplicate acceptance stock or a ticket_created outflow; unnamed cycles deduplicated by
members; unattached agents drawn hollow and labelled; the valve reading is the share of
turns that time out; spec section 5 aligned.

Declined: committing `.orchestra/model/` in the automata checkout (it sits on a ticket
branch; Orchestra's store refuses to commit there and says so; Daniel's call); residence
times per queue (next round if asked; the drill-down has the ticket ages).

## Round 5 (2026-10-14)

Reviewer's verdict: not understandable and correct; no arithmetic errors in 17 readings.
Found: the material-circuit rule matched by membership, not path, so broken base and
re-planning lost their polarity; first-order pairs (the balancing drains the rework cycle
rests on) suppressed; departure wakes drawn as + from the stock; parallel-link "?" an
artefact of walking nodes; the agent node conflates rate and quality; wakes counted bare
event totals as evidence; a base check with 17 pytest errors on a commit that had landed
clean reported as "main broken"; change failure 100% from health restarts of a passing
build; agent time declared as a stock; map label collisions and the merge-gate hub; "up"
for a dead staging process (health check 1.5 h stale); custom agents could not declare
emits through the tools, so no loop through a custom agent could ever close by curation;
gap advice proposing Orchestra's own events to custom agents; environment_keeper never
mentioned though unattached.

Fixed: material circuits judged on the path (filled by the agent before, drained by the
agent after each stock); departures reach the woken agent as a − trigger from the agent
that caused them, never as a + from the level; agent-only loops that act on a stock are
kept and the stock is a member; a stock-lowering trigger outranks a plain one on the same
pair; first-order pairs listed with their polarity; main's state read from the base check
with errors shown and "errors on a commit that landed clean: the gate host, not the code"
instead of red paint; staging "up" only with a health check in the last 10 minutes, else
"last healthy N ago"; change-failure tile names health restarts vs failures; agent time is
a rate reading, no longer a stock; custom agents take `emits` (validated against their
team's types and the events their tools cause) and the detector uses effective emits
(tools and team chain), so a product owner with the tickets tool fills demand and the
devex keeper with the events tool closes capability; gap advice never names Orchestra's
own events to a custom agent; unattached custom agents named in advice; mini loops use the
map's text; information links hidden until hover; agents evenly spaced on two rows; label
collision avoidance; window and pause note in the legend.

Declined: one node per rate instead of per agent (a larger modelling change; the consumer
sign is documented as a declared effect, not a derivation); histogram tiles as bars.

## Round 6 (2026-10-14)

Reviewer's verdict: not understandable and correct; 16 readings matched. Found: "after
landing" was a constant zero while the staging build crash-restarted 16 times and bug
tickets cited shipped work; the change-failure tile contradicted its caption; the staging
death had no event, so the pipeline manager's loop was "observed" while unserved;
gate_base_broken as the build's outflow pulled undiscovered into broken base; the
template's tests and resources were filled only by events nobody emits, so loops closing
through the world showed as hypotheses; the material rule passed on coincidence (different
events draining and filling); a single agent filling and draining a stock counted as a
circuit; re-planning matched a cycle that bypassed demand; reads counted as observed by
declaration; label collisions and 7.6 px type; orange meant three things; 66 unnamed
cycles listed raw; the refresh signature froze ages; the pause reason missing; advice told
the Supervisor the wrong call order and never named qa_engineer.

Fixed: an escape estimator (tickets created in the window citing a DONE ticket or landed
commit; builds the health loop restarted, one defect per build) and the discovery share
with it; change failure defined as deploys whose build crash-restarted or failed, tile and
caption agreeing; staging emits staging_failed when its health check goes unanswered for
ten minutes, then restarts; build's outflow is staging_failed only; tests and resources
also filled by landings, landed also by DONE; material circuits require the same event to
carry the material on, otherwise "co-flow", both without polarity; a controller pair is
never a circuit; declared loops match cycles carrying their stocks as nodes; reads count
as evidence only when the consumer acted; gap advice gives the store's call order and the
role-prompt change and names the woken existing agents (qa_engineer, product_owner); the
discovery tile says where and why; negative links are blue, orange is adverse only; type
raised; unnamed cycles grouped by the loop they extend; the refresh signature includes the
window minute and the ages; the pause reason shown.

Declined: committing the automata model directory (ticket-branch checkout); replacing the
agent node with one node per rate.

## Round 7 (2026-10-14)

Reviewer's verdict: not understandable and correct; every reading matched the raw data.
Found: transitions matched by target state only, so the gate "drained" the review queue and
each gate send-back was two arrows; one event drawn as a departure (−) and a trigger (+);
broken base signed by a mechanism never seen while "observed" on the opposite one, and the
design's parallel-links rule contradicted by the departs tie-break; polarity through agent
nodes produced sixty meaningless B/R variants; the escape estimate double-counted the
crash (ticket and builds) and counted a gate-host flake; "the gate host, not the code"
asserted from a heuristic; three contradictory statements about post-landing discovery;
the producer flow missing (the worker makes every WIP commit and has no link to WIP); the
keeper's and QA's real products attributed to the gate; capability and earlier detection
"hypothesis" while closing through the repository; labels on the wrong edge; lines through
boxes; legend text stale; loop-card hover off-screen; mini-loop overflow; card order; the
WIP-limit advice naming a mechanism that cannot close the loop; the timeout loss and
missing discovery not placed on the page.

Fixed: declared transitions carry their source state ("ticket_transition:IN_REVIEW>REJECTED")
and fit only the agent that owns that transition; one link per event; the departs
tie-break removed, so opposite mechanisms are indeterminate and the card names each
mechanism with how often the window saw it (broken base is now "?" with staging_failed as
the − mechanism, not yet seen); polarity is computed only for declared loops and
stock-draining pairs, unnamed cycles are paths; the escape estimate folds the crashing
service and tickets about it into one defect; the environment caption says what is known
("the same commit passed the gate earlier; pytest errors, not failures: a flaky start or the
host is likely, not proven"); the undiscovered stock's reason names its measured outflows;
defect_escaped is an event type and an outflow of undiscovered; a stock-to-stock gap exists
only when no agent joins the two; same-event conversions drawn as pipes with the agent as
valve, hollow pipes for expected flows no agent closes; one label per event on its chain
stock; rework cards first; a machine-loss card and a missing-discovery card; WIP-limit
advice names the capacity_changed mechanism; mini-loop boxes widened; type larger.

Declined: a per-rate node model (the agent node stays; polarity is restricted instead);
pinning the map on card hover; the demand open-milestone filter (all milestones open).

## Round 8 (2026-10-14)

Reviewer's verdict: not understandable and correct; every recomputed headline matched.
Found: the bad-fix estimator stopped at the reviewer's verdict, so fixes the gate then
rejected counted as good (10% shown, ≥50% true); review misses (approvals the gate then
rejected) not shown; the fix flow landed in undiscovered rework instead of the review queue,
making K→U a "conserved" step; blocked tickets had no flow between WIP and demand; the
build stock had no outflow for restarts and restarts were attributed to the pipeline
manager; broken base had no stock to balance through; gate_rejected counted machine
failures as discovery in the graph's evidence; verified behaviour read a base-check with
host errors as lost tests; cancelled tickets padded the rounds histogram; pipes shared one
line per row and opposite directions shared a line; agents not over the stocks that wake
them; polarity tags truncated; the paused pipeline only in the legend; unknown stock
fields silently dropped.

Fixed: a fix round is followed through review and the gate; review misses on the review
tile with Ford & Sterman's 1 − p_detect; the template follows the design's flow table
(blocked tickets leave WIP into demand; restarts drain the build and belong to Orchestra;
a pipeline_blocked stock filled by a broken base or a pause and drained by the manager's
resume, so broken base is balancing by its link signs; rework loops route through the
review queue with the defect as a declared co-flow); a material circuit needs two stocks;
gate rejections from timeouts and start failures attributed apart from inspections;
verified behaviour from the last landing's run; rounds histogram without cancelled
tickets; one slot per pipe per row with opposite directions apart; indeterminate basis
shown in full; the gate circle says "paused: main fails the gate"; the loss tile first
after really done; unknown stock and loop fields rejected.

Declined: placing agents over their waking stocks (even spacing keeps names legible; the
legend says so); residence-time-per-machine readings beyond "oldest" (next round if
asked).

## Round 9 (2026-10-14)

Reviewer's verdict: not understandable and correct; 24 of 26 checks matched. Found: the
blocked-pipeline level double-counted (a broken base raised two inflow events per incident);
template stocks carried inflow types the store refuses, so the Supervisor could not edit
them; broken base signed B by the departs convention alone; "source says" shown when it
agreed; really done had no outflow and sat at 21 beside a dead build; verified behaviour and
the really-done tile told two stories about main; escapes departed from the design (one per
service, keyword folding); the loss tile's hint about the 15 m limit was stale (the limit
had been 30 m for eight hours with no timeout since); loop signal keys unvalidated and
undocumented; sixteen restarts woke nobody and nothing showed it; a clipped label; the
rework row's stub pipes; links carry no weight; the missing-discovery card said "zero by
construction".

Fixed: one pause event per incident and the pipeline manager wakes on it; template inflows
are events that exist (a team's own events are added when it declares them, and the
capability and earlier-detection hints say exactly how); really done drains when the build
fails, restarts, or main breaks; verified behaviour and really done read the same landing
run; a cycle whose only negative is a departure is "closed; the balancing is in the
first-order pair", with the pair listed as B; "source says" only when it differs; escapes
per build as the design says, a ticket naming a crashing build counted as that build's;
the loss tile and card say when the limit has since changed and when the last timeout was,
and stop flagging adverse; signal keys validated against the catalogue, which the guide and
the model README now list; stock outflows that happened and woke nobody are drawn as hollow
stubs (sixteen staging restarts); Orchestra's own bindings consume gate results; links are
weighted by their attributed count and declared-but-unseen links drawn faint; the
missing-discovery text no longer contradicts the tile.

Declined: a per-build escape that also folds tickets by keyword (the design's rule stands);
pipes of real length between adjacent rework boxes; touch-reachable tooltips.

## Round 10 (2026-10-14)

Reviewer's verdict: not understandable and correct; every recomputed number matched, "mostly
yes" on the one-minute test. Found: really done and verified behaviour did not respond to
their declared outflows (21 passing beside a dead build and a failing main; tests read the
last landing, not main's latest check); three consecutive crashing builds counted as three
escapes; a blocked ticket stayed in known rework and in WIP; the pipeline tool group implied
drains by the product team that never happened; "? · indeterminate" shown for the
departs-only case and a − drawn on that ring edge; agents not over their waking stocks; a
duplicate clipped stub; pipes without direction; 87 unnamed cycles; the silent scheduled
lead not named; no flow table on the page; the guide lacking a closing-a-loop sequence.

Fixed: gate-test stocks carry served / not served (build down, main's check failed) and the
tile and box say "at the last landing · not served now"; verified behaviour reads main's
latest check with the last landing's count beside it; consecutive crashing builds with no
healthy build between are one escape; a ticket blocked back to the planner leaves known
rework and WIP; only the tickets tool group implies an emit; the departs-only case reads
"closed · balancing in its first-order pair" with no sign on that edge; agents sit over the
mean of the stocks that wake them, pushed apart on two rows; one stub per event; pipes show
their direction; unnamed cycles limited to short observed ones with the rest counted; a
scheduled agent whose emits fill no stock is named in the advice; a flows-and-machines table
on the page; the guide has a four-step closing-a-loop recipe with a list_model check after
each.

Declined: excluding reads from cycle closure (the capability loop closes through a read).

## Round 11 (2026-10-14)

Reviewer's verdict: not understandable and correct; every recomputed number matched the raw
data. Found: a ticket sent back seven times read as "0 known rework, bad fixes 1 of 5"
because a block cleared the pending defect and a no-verdict review broke the bad-fix chain;
labels rendered at 7–8 px at 1280 (the canvas was 1965 units wide); demand and WIP used the
plain `IN_PROGRESS` transition, so a fix's pickup counted as a start; edge tooltips and
weights looked up attributed counts by the from-state key and found nothing; the flow table
listed landing → resources and landing → tests as conversions; two recommendations per gap
that named different agents; the loss card last and in the warning colour at any size; a
phantom `defect_escaped` outflow; the escape rule for consecutive crashes not in the spec;
WIP's description and reading disagreed about blocked tickets; broken base cited
Abdel-Hamid for Orchestra's own controller; T's not-served reason said the build was down
when main's check had failed; the guide's worked example appended to wake_on instead of
replacing it.

Fixed: known rework survives a block and is cleared only by a re-submission, landing or
cancellation, with the tickets whose send-back has not yet been followed by a landing shown
beside it; a fix round is followed to the defect's next verdict (a defect rejection makes it
bad, a landing good; approvals, no-verdict reviews, blocks and further re-submissions decide
nothing), with a unit test for the seven-send-back shape; demand and WIP use
`OPEN>IN_PROGRESS` and `REJECTED>IN_PROGRESS`; the WIP description now says blocked
tickets' commits wait with the ticket in demand, matching the reading and keeping the
re-planning circuit; stock readings wrap inside capped boxes so the canvas is 1350 units and
every label renders at 10.8–11.7 px at 1280 (measured in the browser); agents sit over the
stock they drain; flow labels sit in a band above the chain row and move up, never into the
boxes; tooltips and weights use the plain event key; conversions never run into a capability
stock; the flow table's wake-on column carries the from-state; the template hint shows only
for a loop that exists, so a gap has one recommendation (the detector's); the loss card is
first and warns only past the same third as its tile; `defect_escaped` removed from the
template and the escape rule (consecutive crashing builds are one surviving defect) written
into the spec; broken base cites Orchestra's own controller; T's reason names main's check
when that is what failed; the guide says wake_on, emits and inflows are replaced, not
appended, and the worked example passes full lists.

Declined: clearing known rework when a blocked ticket returns within the hour (a block is a
turn-limit escape on this org; the defect is the same until a verdict says otherwise, so no
timer); `staging_failed` emission is live only after the runner restarts, which is the
operator's call.

## Round 12 (2026-10-14)

Reviewer's verdict: not understandable and correct; every recomputed number matched,
including fix rounds, bad fixes, causes and hours, and the refresh was honest. Found: the
page drew a model older than the template, because the project's `.orchestra/model/` files
were never updated once written (five round-11 claims were true of the template and false of
the page); the flow table counted events, not flows (demand → wip 102/d where the map said
4 starts; known rework → awaiting review 33/d where 10 were fix rounds); the map was a
hairball of 92 paths with every agent drawn to every stock it touches, labels crossed by
lines, hollow pipes running behind the agents; pipes did not isolate on hover; the mini loop
diagrams rendered at 7–8 px; `staging_restarted` declared on the pipeline manager when the
health loop emits it; the not-served reason preferred main's check over a dead build; review
misses counted one defect six times; time to restore ignored restarts; no flag for a median
turn at the limit; "3 builds" for a four-build surviving defect; the machine-loss warning
suppressed because the limit had changed; the rework cards never showed the source's B; the
broken-base tag read as a disagreement; the "orchestra" fallback under built-in agents read
as a team; unnamed cycles printed sorted member sets with arrows; level and age not encoded.

Fixed: every template element carries a `template_hash`; `orchestra run`, `orchestra web`
and `model init` replace an element that still reads as the template wrote it, keep a
curated one, and report an unmarked one on the page and in `model init` (test added); the
automata project's model was brought to the current template on its main; attributed counts
carry the from-state form, the flow table and the pipes show the design's label for the
flow (4 starts · 67 re-picks; 10 fix rounds · 8 later found bad) and the conversions count
by the from-state event; the map draws each conversion as one pipe with the agent as its
valve and suppresses that agent's own lines to the two stocks (36 visible paths, down from
92), ticket creators share one inlet into demand, hollow pipes are two labelled stubs at the
source and the target that light together, pipes have a wide hover target and isolate like
stocks and agents, opposite pipes are offset, a pipe passing over a box names its source,
cross-row pipe labels sit in a wider band; the loop grid is three columns at 1280 and the
minis' text is 11.5 px in their viewBox; the health loop emits `staging_restarted` and
`staging_failed`, the pipeline manager does not; the not-served reason names the dead build
first; misses are shown as distinct defects missed in N approvals (test added); time to
restore runs from an outage's first trouble to the deploy that stayed healthy (test added);
an agent whose median turn is at the limit says so; the escape text says "one defect, 4
consecutive crashing builds"; the loss tile and card warn past a third whatever the limit
did; the rework cards say "source: B, in its first-order pair" and the broken-base tag
"(B, as the source says)"; built-in agents read "built in"; unnamed cycles print their path;
a tracker stock carries a residence bar (a day wide, amber past eight hours) and names the
ticket on its highest review round. A declared loop now matches a cycle with at most two
members beyond its own nodes, since the health loop's new emits closed an eight-node cycle
through the capability loop's stocks.

Declined: dropping the known rework → undiscovered pipe (the design draws re-submission as
the flow that carries the defect on; it now reads "10 fix rounds · 8 later found bad");
choosing one agent in the gap advice (the detector lists every agent the structure permits,
and which one should emit is the operator's call); a residence-time distribution per queue
(the readings carry median and oldest; a profile needs the event store's history, step 2).
