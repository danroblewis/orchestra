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

## Round 13 (2026-10-14)

Reviewer's verdict: not understandable and correct; all twenty-five readings recomputed from
the log, the store and the repository matched, and the one-minute test passed for what the
foundry produces, where work piles up and where defects are found. Found: the progress flow
was missing and a false one drawn in its place (WIP was drained only by the landing, so every
submission left Known rework and a Known rework → Undiscovered pipe carried "10 fix rounds");
one landing and each rejection drawn twice (the change and its co-flow as equal pipes);
pipe hover lit the wrong pipe for seven of eleven (labels drawn above the hit twins; opposite
pipes offset less than the hit width); card hover dimmed the loop's own pipes; the loop files
claimed B where the detector found a material circuit; the broken-base ring showed two plus
signs and a blank edge because the detected path was the wake path, not the controller;
three different 21s on the chain row; Verified behaviour led with the suspect check; CA-39 in
two stocks without saying so; the merge gate still declared `staging_failed`; "n/a" for a
39-hour open outage; the block not re-rendering on the poll; unnamed tooltip directions; the
worker's reading running into the merge gate's; hollow-stub labels floating over the wrong
box; the loop grid two-thirds empty; mini rings carrying no counts; seven amber tiles; one
style for team names and readings; a flush-left label; the activity bar's last label at the
border; no statement of the machine's state or of where the hours go.

Fixed: WIP drains on the submission (and the reading counts the branches of tickets
IN_PROGRESS), so Work in progress → Awaiting review is a pipe labelled "32 submitted · 9 of
them fixes"; the detector's conversions mark co-flows (through the hidden stock) and keep
one flow per event per agent along the product's path, the page draws pipes from that list
(test added), co-flows as thin dashed twins with no count; the landing is approved → landed
once; hit twins are drawn above the labels, labels take no pointer events, opposite pipes
are offset 16 (verified: eleven of eleven pipes light under a real mouse); card hover keeps a
pipe whose valve is a member and that reaches a member stock; the template declares the
rework cycles with no polarity and broken base as the pair pipeline blocked ↔ pipeline
manager, so the ring carries its minus and "B · link signs" (golden test updated); the
really-done tile reads "21 tests pass · 21 DONE" and names perceived against actual;
Verified behaviour leads with the last clean check when the latest check looks like the
host; Known rework says "CA-39 (blocked, in demand)"; the merge gate no longer emits
`staging_failed`; an open outage's age is shown on the tile and in a banner; the pipeline
pause is a banner above the map that says it comes before any new agent; the block
re-renders when the window moves a minute, and the legend calls the window a sliding one;
tooltip directions name their signal; agents sit on three rows with readings and team names
styled apart and unattached agents showing what they produced; hollow-stub labels are short
and anchored to their stub; loop cards size to their content; mini rings carry the counts on
their flows; at most three tiles are amber; the left-most label is inset and the activity
bar's last label anchored; the section is titled "Stocks and flows"; a "where the day goes"
line orders the hours and the defects above the cards; the inferred review cause is named
in the Known rework estimator.

Declined: choosing one agent in the earlier-detection advice (the detector names every
agent the structure permits; which one should author tests is the operator's call); a
residence-time distribution per queue (median and oldest are read; a profile needs the
history store of step 2).

## Round 14 (2026-10-14)

Reviewer's verdict: not understandable and correct; every number recomputed from the log,
the store and git matched, and the page's honesty (not estimable, not served, host suspect,
losses named) was praised. Found: the rework flow itself (Known rework → work) was not drawn,
K's only drain folded into the W → Q pipe, so Known rework read as a sink; the chain changed
unit at every pipe and 16 commits on approved branches were in no stock (WIP read 0); the
escape entered no stock and L → K had no hollow stub; Really done kept 21 while its drains
fired; Verified behaviour substituted the clean check for the latest; the discovery share by
distinct defect hid the weight of one defect cycling; first-order pairs labelled "B or R";
re-planning detected without the coordinator; loop rings carried the product's counts (32
submissions, not the loop's 7 fix rounds); agent readings touched neighbours' names; eight
long diagonals from the gate and the loop crossed the right half; one landing drawn twice
(DONE and gate_landed); amber on the first three tiles, not the worst; uneven tile heights;
co-flows on one segment; the pause banner without an age; the unconsumed stub without hover.

Fixed: Known rework drains on the fix pickup (REJECTED → IN_PROGRESS), a pipe K → W with
"30 fix pickups" by Orchestra; its level is the send-backs awaiting a fix, with the ones not
yet re-submitted and not yet landed beside it (blocked ones marked); the rework cycles are
declared through the pickup (K → Orchestra → W → worker → Q → reviewer → K) and detected as
material circuits; conversions are grouped by the declared event form so the pickup and the
start are two flows (test updated); WIP is counted in changes (tickets IN_PROGRESS) and
every chain stock shows the commits ahead on its tickets' branches, so the 16 commits at the
gate are seen; a "discovery after landing" loop (build → known rework → … → gate) is in the
template, so the map carries hollow stubs at the build and at known rework; Really done
reads 0 served with the count at the last deploy beside it while the build is down; Verified
behaviour reads the latest check with the host-suspect flag and the last clean count as
context; the discovery tile shows the share by distinct defect and by finding; pairs read
"two loops: B through what it drains, R through what it fills"; re-planning is declared with
the coordinator (demand → coordinator → Orchestra → W → worker → demand) and detected so;
loop rings count the loop's own flow by the state the ticket came from (the log attributes
each transition by its previous state): the review ring reads 21 pickups after review
rejections, 7 fix submissions, 4 rejections, the gate ring 9 pickups after gate rejections;
agents sit on three rows 70 apart with the at-limit flag on its own line and no reading
touching a name (checked in the DOM); flows no pipe carries are short labelled stubs at the
stock with the agent's line on hover, so the diagonals are gone; DONE is no longer a second
inflow of landed; amber marks the three tiles furthest past their threshold; co-flows run at
mid-height; the pause banner carries its age from the log; the unconsumed stub hovers;
labels never land on a box or an agent (checked in the DOM). The automata model on main
follows the template.

Declined: a cost per recipe (the "where the day goes" line gives the hours and defects each
recipe would address; attributing them to one binding would be a claim the data cannot
support); calling out the pipeline manager's dead wake rule on `staging_failed` (that event
is live after the runner restart; the model inspection tools now say what an event's
emitters are).

## Round 15 (2026-10-14)

Reviewer's verdict: not understandable and correct; every reading but one recomputed from
the log, the store and git matched (the inlet left out the pipeline manager's ticket).
Found: Known rework did not integrate (ten defect send-backs in, thirty pickups out, twenty
of them after no-verdict reviews or lost runs, which the design calls machine loss); lost
gate runs and conflicts drained the gate queue into nothing; re-planning was detected
through a cancel and tagged co-flow; the rings' counts were the loop's own only at the
pickup; U never receives landed defects; the additions' inflows carried the wrong unit;
pairs' "R" needed the word formal; a hollow-stub label 280 px from its stub and a pipe label
130 px from its pipe; three arrowheads on one anchor; two co-flows on one segment;
duplicated stub labels; agents not over what they drain; a stub arrow through text; two
notations for one window; card hover over-lighting; a hit twin covering a neighbouring pipe;
the pause banner without its age (not passed through); the at-limit flag against the old
limit; two gap recipes naming Orchestra's own events and processes; the product tile's
bright 0.

Fixed: a stock *Returned without a verdict* (no-verdict reviews, lost gate runs, conflicts;
a machine loss) filled by the same events as Known rework and drained by the re-pick, so the
pipes split by cause ("3 defects in 4 rejections" / "17 reviews with no verdict (loss)";
"1 defect in 6 runs" / "3 lost gate runs (loss)"; "11 fix pickups" / "19 re-picks (loss)")
and Known rework integrates; every transition after a send-back carries its cause in the
attribution, a pending defect's cause surviving later no-verdict send-backs, and a
transition out of a working spell is attributed to the state the spell began from, past the
restarts (test added); a *Blocked* stock, so re-planning is the conserved circuit W →
Blocked → Demand → W with the coordinator and Orchestra as valves, detected as a material
circuit; co-flow is a tag only for a circuit through the hidden stock; the rings count the
loop's own flow with its cause (review ring 5 pickups after review defects, 1 fix
submission, 4 rejections; gate ring 6, 6, 4, 11; re-planning 10 re-planned, 9 starts, 5
blocks); cycles are enumerated in passes of growing length so the pairs and the short loops
are never pushed out by the budget, and a declared loop's match is bounded by its path, not
by the stocks its events touch; gap advice never names Orchestra's processes or events, and
a hypothesis card shows the template's recipe with the detector's facts beside it, the
separate missing-discovery card gone where the loop is declared; labels stay within a few
steps of their geometry (both directions, then where they belong), cross-row pipes fan
across a box edge, co-flows on one pair are offset, stubs are drawn once per agent and event
and not into the additions, one notation (counts in the window), the unconsumed note folded
into its drain stub; agents sit over what they drain and are relaxed apart only as far as
names need, with the legend saying so; the pause age is passed through and shown; the
at-limit flag uses the limit in force; the inlet counts every creator the log credits; pipe
labels are keyed by destination first; card hover lights only the loop's own edges; pairs
read "formally, by link signs"; the product tile leads with the last deploy's count and says
"build down, 0 served now"; U's recipe names the finding event as its outflow too; the
design's B1 row now matches the rules. The automata model on main follows the template.

Declined: a recovery estimate per recipe (the "where the day goes" line gives the hours and
defects; attributing them to one binding would be a claim the data cannot support);
surfacing read-based pairs for B2 (a loop needs its author; the hypothesis card says so);
"how late" as a time interval (the discovery delay needs the commit-to-finding join of step
2).

## Round 16 (2026-10-14)

Reviewer's verdict: not understandable and correct; every reading recomputed matched its
source, and the round-15 fixes were verified present. Found: a co-flow from undiscovered
rework into Returned (a no-verdict return finds nothing); Known rework's level was the
pickup queue (0) while three defects were open; "66 re-picks (loss)" counted nine starts
after a re-plan as losses; the rings undercounted the loop's own flow (9 fix rounds on the
map, 1 + 4 on the rings) because a cause was dropped when a spell began from OPEN after a
block; Really done read 0 when the staging process was down and Verified behaviour printed a
level it disowned; the WIP-limit hint asserted a false fact; a label column detached from
eight crossing diagonals; the orchestra circle over a stock it does not touch; a hollow-stub
label under the wrong box; three unlabelled 21s; the flow table keyed by source and listing
co-flows; hit twins over boxes and over shorter pipes; the broken-base card hover lighting
one edge; the at-limit flag against today's limit; the histogram's scope unstated; no
discovery delay anywhere.

Fixed: a `loss` flag on a stock, and no co-flow between the hidden stock and a loss stock;
the cause a transition carries is decided by its kind (a send-back its own verdict, a
pickup the send-back it follows, a submission the pending defect through blocks, re-plans
and restarts, a verdict on a fix the defect not yet landed), the pending check made strictly
before the transition, and a ring step with a cause counts every transition that carried it,
so the rings read 5 → 3 → 4 and 6 → 6 → 6 → 8 and the fix submissions sum to the 9 fix
rounds; starts split into first starts, starts after a re-plan and re-picks after a restart,
only the last a loss; Known rework's level is the defects not yet landed with the pickup
queue beside it; Really done keeps what the last deploy proved and reads "unverified: the
deployed build is down"; Verified behaviour reads the last clean check marked stale when the
latest check failed on a suspect host; the discovery tile is second and carries the median
delay from submission to verdict by stage and from deploy to first trouble; cross-row pipes
run orthogonally, each on its own band with its label on the horizontal run (no label is
crossed by a line, checked at 1280 and 1600); agents sit over the pipes they are the valve
on; the flow table is keyed by destination and lists no co-flows; hit twins are under the
boxes, long pipes first, none for co-flows (every pipe's midpoint resolves to its own twin);
hollow source-stub labels lie under their own box; every big number carries its unit; the
WIP-limit hint is unconditional ("when conflicts outnumber landings…"); pairs read "B
through what it drains; its wake on arrival carries no sign"; the at-limit flag is judged
against the limit the median was measured under or the one in force; card hover lights a
loop's stubs too; the histogram says "cancelled excluded". The automata model on main
follows the template.

Declined: computing polarity over level-dependent links only (a wake on arrival is how an
agent's rate follows a stock on this machine; the pairs now say the wake carries no sign,
and the loops' polarity rests on drains); a recovery estimate per recipe (as before); a
split of every headline at the limit change (the loss tile and card date the change; a
two-window page is a different page).

## Round 17 (2026-10-14)

Reviewer's verdict: not understandable and correct; every number traced matched its
definition and every interaction worked; the defects were definitions, labels and layout.
Found: "pending" meant two things (the level used not-landed, fix rounds and fix hours
used not-re-submitted, and the tooltip described the first); Known rework in send-backs;
no-verdict send-backs given the reviewer as their machine; the restart drawn as a drain of
a one-unit stock; the outage that can never close and "down" inferred from silence without
saying so; the rounds histogram called review rounds; "how late" named discovery delay when
it is verdict latency; two units side by side on the product tile; headline numbers wrapped
into paragraphs; labels crossed by lines (44 pairs); six hollow stubs with four wordings and
no loop name; three 56s; six agents piled at the left; the legend a paragraph; co-flows
unlabelled.

Fixed: one meaning of rework, on the model's terms: a fix round is every re-submission of a
change whose defect has not landed, a fix turn likewise, a fix is judged by the defect's
next verdict, and the tooltip says so (29 fix rounds, 13 bad, rework share 84%); the
submission's cause follows the unlanded defect so the rings sum to the fix rounds; Known
rework in changes; the histogram labelled send-backs per ticket; "verdict latency" with n,
and the defect's age named as what it is not; the product tile holds one number with its
unit and the perceived count in the caption, the discovery tile "3 · 1 · 1"; the no-verdict
pipe's valve reads "turn limit"; the restart stub reads "crash proxy"; the build box reads
"inferred: no health answer for 7.1h" and the banner says what the outage is; pipes along a
row run above it with their labels above them, cross-row pipes keep their own bands below,
labels sit beside the vertical runs that pass their height when that keeps them within
reach of their pipe (crossings down from 44 to 9, every remaining one under a halo); hollow
stubs carry their loop's name; agents on no pipe spread over the width instead of piling at
their fill target, and their sub-lines are readings or the team only; the co-flow is
labelled once; the legend is a two-column key; pairs on the hidden stock are not listed;
earlier detection declared B as the design's table says; no label overlaps any other at 1280
or 1600 and every pipe's midpoint resolves to its own hover target (DOM checks). The
automata model on main follows the template.

Declined: a recovery estimate per recipe, the drill-down's denominators (another section),
the 0.2 h of pipeline-manager time (the activity map already counts it as plan; the
difference is the reviewer's pairing slack), and reviewer utilisation beside the queue (the
queue's residence time and the reviewer's in-use count are both on the map).

## Round 18 (2026-10-14)

Reviewer's verdict: not understandable and correct; every windowed number reproduced from
the log, and the one mismatch was provenance (the rounds histogram from the tracker's
counter, 15·6·3·5, against the log's 11·9·3·6). Found: Known rework's level (defects not
landed) put the same change in two boxes and did not integrate with its pipes; restarts drawn
as a creation into Demand with no return out of W; the no-verdict valve still the reviewer
(the round-17 rule never fired because the reviewer also gave verdicts); split pipes'
tooltips and weights carrying the undivided count; the deploy L → B missing from the map;
earlier detection's signal moving against its mechanism; along-row labels 60–106 px above
their pipes; the build stub's label 98 px from its stub under seven pipes; the co-flow label
struck through; arrowheads through text; a "—" for zero re-run hours; duplicated box
sub-lines; the gate card's hover lighting a pipe not on the ring.

Fixed: Known rework's level is the fix queue again, drained by the pickup, with the defects
not yet landed as a count beside it (the design says why both numbers exist); the rounds
histogram counts send-backs per ticket from the log; conversions are counted by the causes
the destination stock splits on, and when the agent on the pipe moved none of them and
Orchestra did the valve reads "turn limit" (the map, the tooltip and the flow table agree);
a stock may declare events that carry its content on without draining it and the stock each
delivers to, so landed → build is a pipe ("2 deployed") and main keeps its commits; a
restart is a pipe W → D labelled as a loss, so Demand is filled from W and the two "?" pairs
are B; earlier detection's signal is defects after landing (adverse up) and its structure
says what it does; along-row labels wrap at the dots to fit their gap and stack from their
pipe; a stub into a bottom-row stock enters from below with its label below; the co-flow is
explained in the key only; the re-run tile prints 0 for zero; a box with one state shows the
state once; the loop-card hover lights a pipe only where the ring runs source → agent →
destination. Labels crossed by lines: 8, each under a halo; no label overlaps another at
1280 or 1600; every pipe's midpoint resolves to its own hover target. The automata model on
main follows the template.

Declined: W from git (the chain is in changes by round 14's decision; the commits ahead are
beside every chain stock); a recovery and a cost per recipe (as before); the mini rings'
label collisions (the rings are read with their cards' text); the worker drawer's "last
woken: never" (outside this section, and true: workers are started, not woken).

## Round 19 (2026-10-14)

Reviewer's verdict: not understandable and correct; 26 of 27 checks matched (the plan
roles' timeouts over by two: a timeout within seconds of a settle was matched to two turns)
and the hover, click and refresh mechanics all worked. Found: the gate → Returned pipe
counted 6 with the gate as valve because the attribution wrote the lost runs under a
different key; three 900-second gate timeouts on one change were filed as machine loss
when they are a hang in the change (a defect); the drill-down loop table's rows D–J threw on
hover (double quotes in an attribute); the Fix queue read 0 with three unfixed defects and
was still named Known rework; earlier detection declared B while its links multiply to R;
every band label struck through with no halo showing; the found tile's 15-line caption;
agent sub-labels touching; mini-ring counts on names; a four-item list where "blocked"
qualified one ticket; the design contradicting itself on restarts and on Really done's
level, and the page on the deploy's valve; a wake rule on an event never emitted drawn as
live.

Fixed: the gate's send-backs carry their cause in the attribution (gate, lost, conflict),
so the pipe reads 0 lost gate runs with the turn limit as valve when that is what moved the
change; a timeout that recurs for one change at one stage others finish is a hang, a defect
named on the gate's label ("2 defects in 9 runs · 3 hung (CA-24)") and counted in the
misses (2 defects missed in 7 approvals) with a unit test; each turn limit ends one turn;
the drill-down rows quote their handler safely; the stock is named Fix queue, "known rework
waiting pickup", with the defects not yet landed listed beside it ("CA-39 (blocked)");
earlier detection claims no polarity and its structure says why; every label is drawn above
every line so the halo shows; the found tile's prose is its tooltip; the at-limit line sits
lower and the rows further apart; the ring counts sit further from the names; a wake rule on
an event the window never saw is drawn faint and its tooltip says latent; first-order pairs
are B through their drain in the detector, not only in the text; the design says a restart
returns the change to Demand, that Really done's level is a state, and that the deploy's
valve is the gate. The automata model on main follows the template.

Declined: a recovery per recipe (as before); re-levelling the Fix queue to the unlanded
count (round 18 asked for conservation; the name now says what the level is and the
unlanded defects are listed beside it); reconciling the re-planning ring's 10 → 9 → 5 (each
step counts the loop's own flow for the window, and the card's tooltip says so).

## Round 20 (2026-10-14)

Reviewer's verdict: not understandable and correct; every headline number recomputed
matched but one, with a clear cause (a no-verdict send-back and its re-pick logged in the
same second, which a strict time comparison put out of order: 14 fix pickups where the log
says 13), and the round-19 fixes were all verified. Found: a rework map that read 0 / 0 / 0
on an 88%-rework day because the Fix queue's level is the pickup queue; Demand mixing
tickets ready for pickup with tickets waiting on a dependency (all four waited on CA-18), so
its amber residence bar pointed at the wrong constraint; the review card's signal and hint
blaming the reviewer's feedback when the gate was the one rejecting; two numbers for one
quantity ("CA-18 ×28" from the log, "round 27" from the tracker); the inlet's arrow and
words on the restart pipe; hollow-stub labels trailing under neighbouring boxes; agents on
no pipe spread between the valves against the design and none drawn hollow; labels wrapped
inside a count and its noun; labels not hover targets; no evaluation of the limit change.

Fixed: every "what came before" rule takes the transitions logged before the named one, ties
in log order (test added: the same-second re-pick is a re-pick); bad fixes are split by the
verdict that judged them, the review loop's signal is the reviewer's share and the gate
loop's readings carry the gate's; the Fix queue shows its level and, in amber, the defects
not yet landed with their tickets; Demand says how many tickets are ready and what the rest
wait on, with the residence time of the ready part ("0 ready · 4 waiting on CA-18"); the
worst ticket's round comes from the log; the inlet enters the box's side with its words
above; hollow-stub words sit centred under their own box, two lines when long, and a stub
leaving a chain-row box keeps only its tick and tooltip; agents on no pipe sit at the right,
hollow when they drain nothing, and the key says so; labels wrap at the dots only; every
pipe label is a hover target for its pipe with the pipe's tooltip; the loss tile says how
many turns have run since the last timeout. The automata model on main follows the template.

Declined: a second box for the defects not landed (the Fix queue's amber second number is
that box); a recovery figure per recipe (the readings line on each card is the magnitude the
recipe addresses); the three 21s (each carries its unit, and the DONE count is the design's
perceived progress beside actual); naming the Supervisor's tools as not live (a runner
matter, not the page's).

## Round 21 (2026-10-14)

Reviewer's verdict: not understandable and correct; every one of twenty-plus numbers
derived independently matched, every round-20 fix was verified, and the page's honesty was
praised. Found: the central stock read 0 on an 88%-rework day because its level was the
pickup queue (a wire, not a stock on a machine that re-picks in seconds), while the two
defective changes hid in "Awaiting the gate" unmarked; the rework rings and their cards on
different bases (4 on the ring, 6 of 29 on the card); the product's own path drawn as 24-px
stubs with labels floating 70 px away; cross-row bands without a destination in their
labels; a stale red "median turn at the limit" 166 turns after the last timeout; the review
tile amber for a number in its small print; "down" in the success colour; 21 tests beside
21 tickets DONE; a duplicated "2 deployed"; states drawn in the stock grammar; stub, inlet
and hollow labels not hover targets; the flow table's rows not lighting their pipe.

Fixed: Known rework's level is the changes with an unlanded defect, named with where each
sits, and the pickup queue is its small line; every chain box says how many of its changes
carry an unlanded defect; fix rounds and bad fixes belong to the loop they were on, so the
rings' counts and the cards' fractions share a denominator; a pipe along a row is a hump
over its gap with the label on the run, so the chain reads as one line; cross-row pipes take
neighbouring bands by destination and every band label says where it goes; the at-limit
alarm retires once the limit in force has gone twenty turns unhit; the review tile leads
with the adverse number when the miss rate is the adverse one, and the loss tile's severity
counts the hours; the perceived count left the product tile's caption; "down" is red; a
state is marked ◇ with a dashed box and the key says its flows are never summed; an event a
pipe carries is not a stub's label too; stub, inlet and hollow labels light their line, and
the flow table's rows light their pipe. The automata model on main follows the template.

Declined: a separate FCC variable in the graph (the consumer link's sign is the design's
convention for the effect on injection, and the capability loop's B rests on it as the
design says); per-stage arrivals, residence and utilisation over the window and a series
longer than two days (step 2's history store); thinning the merge gate's hover (it lights
what the gate touches, which is the fact about this org).

## Round 22 (2026-10-14)

Reviewer's verdict: not understandable and correct; every number checked reproduced from the
raw log, and the round-21 fixes were verified in place. Found: Known rework's level (changes
with an unlanded defect) was not the integral of its drawn flows (send-backs in, pickups out)
and the design said two things about it; the capability stocks were declared filled by
landings while the gap advice said no agent fills them; undiscovered rework had no
post-landing outflow in the data; "where the day goes" summed overlapping categories past
the total; the gate tile hid the hang reclassification; the drill-down's review rate was a
second rate with no label; the miss rate printed as a fraction; the discovery label clipped
by the agent-time bar; the restart hump's label pushed up to the agent band and the start
label caught inside the restart hump; a shadowed hit twin; the map rebuilt on every refresh
because the outage counter was in its signature; pipe widths too flat to show 70 against 2.

Fixed: Known rework is a stock of open defects, filled by a send-back for a defect and
drained by the landing of the fix, so its level is the integral of its own flows in its own
unit; the fix pickup is drawn on W as W's inflow; the rework cycles are declared through the
worker (who reads the open defects and re-submits) and reinforcing, as task cycling is, and
a link one agent both fills and drains is signed by the mechanism the window saw most (the
gate's: 9 rejections against 2 landings), with the card saying so; the design tells one
story; the capability stocks have no landing inflow, so the model and the gap advice agree;
undiscovered rework's post-landing outflows are the crash proxies; the day's hours say how
many fix hours ended in a timeout instead of summing twice; the gate tile names the hangs;
the drill-down's rate is "sent back from review (all causes)"; rates print as percentages;
the review tile's tooltip says how a verdict is read; the humps rise from the box centres
with labels narrower than the gap, the inlet's words sit under its box, and the canvas has
room under the bottom row; pipe widths span 1 to 6 px on the log of the count; the refresh
signature rounds the outage to ten minutes. No label overlaps another at 1280 or 1600, none
is clipped, and every pipe's midpoint resolves to its own hover target. The automata model
on main follows the template.

Declined: a value per gap and a way to try a binding from the page (the card's readings are
the magnitude; what-if belongs to the Supervisor's tools by invariant 7); thinner hover on
the gate; colour by band.

## Round 23 (2026-10-14)

Reviewer's verdict: not understandable and correct; 24 of 24 numbers matched, and hover,
click and refresh were sound. Found: the rework flow K → W (13 fix pickups) was not drawn,
so W's drawn inflows fell 13 short of its outflows and Known rework read as a sink with an
unlabelled drain; the design still told three stories about K; the rework cycles were signed
R by the detector's default (every queue chain through agents multiplies to R) while the
re-planning loop of the same shape was a material circuit, and the gate's link was signed by
an event vote; the worker step on both rings counted every submission (32); rework share
counted the wall time of turns the limit killed; "0 h/d re-runs" sat beside 17 re-picks;
five agents on the inlet were told they sit on no flow; the restart drained three stocks;
the drill-down's review row described all send-backs as the reviewer's; labels collided at
the right and at demand ↔ work in progress; the gate card's badge clipped; the capability
gap named two agents.

Fixed: the fix pickup is a carrying link out of Known rework into W (the defect stays open),
drawn as the pipe "13 fix pickups", and K's drain is labelled ("fixes landed"); the rework
cycles are declared through the pickup and detected as conserved circuits of the change,
no polarity, their balancing the pair of K and the gate that lands the fix (carrying links
count as the thing moving on for the material rule; test updated), so the two rework loops
and re-planning are judged alike and no link is signed by a vote; the rings count the loop's
own flow again (5 → 4 → 4 and 9 → 25 → 8); rework share is effort, net of the turns the
limit killed, with the wall-time share beside it (test updated); the re-run tile text says
that a re-run on a change with an open defect counts as a fix; agents on the inlet read
"fills only" or "4 tickets" with a tooltip that says so, and agents on no pipe share the
right-hand width; the restart is not an outflow of undiscovered rework; the drill-down's
review row says it counts every send-back, verdict or none; labels wrap at words too but
never between a count and its noun; the hollow stub's tooltip is the loop's own recipe; the
design has one definition of K in its table, its rules and its loop table. The automata
model on main follows the template.

Declined: a tests-over-tickets ratio (no unit; the perceived count is in the tooltip); the
duplicated hollow labels at both ends (each end names its gap); a page affordance to try a
binding (invariant 7).

## Round 24 (2026-10-14)

Reviewer's verdict: not understandable and correct; the headline numbers reconciled with the
log to the unit and no functional defect was found. Found: "0 fixes landed" (the label read a
cause the attribution never writes on gate_landed; CA-37 landed with its defect, so 1);
"56 restarts after a turn limit" where 13 were interrupts (loop stops, resets, errors, the
operator's capacity changes); the cancel stub drawn on Blocked for a cancel that left Demand
(the plain count stood in for the from-state count); the rework cards claiming "balancing in
its first-order pairs" where the detector found no pair on Known rework; a pair signed R by
the window's vote; re-planning's signal (starts, adverse down) flagging a card over one fewer
first start; the review tile's headline swapping metrics; a zero-count pipe labelled across
the map; agents on the inlet captioned so close they read as one phrase; the failing test
only in a tooltip; the pre-limit-change loss shown as current on the agents.

Fixed: "fixes landed" reads the DONE transition's cause (1); restarts are split into those
within ten seconds of a turn limit and interrupts ("43 restarts after a turn limit · 13
interrupted"); a stub counts its own transition form, so the cancel sits on Demand; the
material tag names the balancing pairs the detector actually finds on the loop's stocks
(reviewer ↔ awaiting review, worker ↔ work in progress, merge gate ↔ approved) or says it
finds none; a pair is its drain's and is never signed by the window's vote; re-planning's
signal is re-plans (adverse past five); one metric per headline (pass rate), with the miss
rate in the caption; a pipe nothing moved through keeps its tooltip and loses its label;
agents on no pipe take a row of their own spread over the width; the failing test is on the
gate tile's face; a timeout share from before the limit change says so; escapes ride with
the landing as an uncounted co-flow from undiscovered rework; the design records the
restart split, the pair rule and the inlet agents. The automata model on main follows the
template.

Declined: declaring the design's R1 and R2 loops in the template (a hypothesis loop draws
hollow stubs that would say "no agent" for a causal effect no agent closes; the rework-share
tile carries Repenning's threshold as its signal); a recovery estimate per recipe (as
before); Demand in changes (tickets become changes at the pickup, which the pipe says).

## Round 25 (2026-10-14)

Reviewer's verdict: not understandable and correct; all 28 numbers checked reconciled to the
unit, hover, click and refresh sound. Found: Known rework drawn on the material circuit but
counted in open defects, so the "conserved" circuit changed unit at one stock; the rework
cards' tag naming one set of balancing pairs while the loop's prose asserted another (K ↔ gate,
a pair the detector never found); K's level of 3 counting two changes whose fixes were
approved and waiting for the gate; the pipeline manager's one post-landing defect ticket
(CA-37) ignored by the detector because built-in agents contribute only their declared
emits, so the page said nobody closes discovery after landing; the new material tag
overflowing its card at both widths and over the WIP-limit card; "1 CANCELLED → coordinator"
struck through by the start pipe; the two orchestra labels at the Demand corner reading as one
block with a hump through "3 starts"; two stub labels with no tooltip; "1 fixes landed"; the
discovery tile wrapping mid-phrase at 1280; the gate ring's agent label on the arc; the
WIP-limit card claiming the operator's hand without landings to judge by; the page not saying
the Supervisor can inspect the model or try a what-if; the ring's "8" resting on an unstated
attribution rule.

Fixed: Known rework is a stock of changes, the changes sent back for a defect and waiting for
the fix pickup (Ford and Sterman's work known to need rework); the pickup drains it into W
(Cooper's rework progress) so the circuits conserve the change, and the detector finds the
orchestra ↔ known rework pair; the open defects and where each change sits are listed beside
the level, not as the level; the loop prose claims no pair and the tag names the pairs found,
on a line of its own that wraps; the pipeline manager declares ticket_created (it has the
tickets tools); main failing the base check and the build failing in service are declared
discoveries (outflows of U), and a cycle closed by a discovery event is a co-flow with no
polarity, so discovery after landing is now a detected loop through the pipeline manager
("closable, not yet seen": CA-37's creation has left the window) and the card says only a
failure discovers anything; stubs leave every box downward, wrap at the arrow when wider than
the box, and carry tooltips, so the cancel sits under Demand with nothing through it; hump
slots are 82 px apart and the chain and rework rows sit 30 px lower, so each orchestra label
stands above its own hump; "found: review · gate · after landing"; the WIP-limit card reads
landings beside conflicts per landing; the intro says the Supervisor can inspect any stock,
agent or event and try a what-if agent; the ring tooltip states that a verdict on a fix
belongs to its latest pending defect; the design records K's unit, the discovery rule and the
co-flow rule. Unit tests: the golden org's field-discovery loop is a co-flow, the K level is
the changes awaiting a pickup.

Declined: the gate ring's agent label touching the arc (the mini ring places names under
circles; moving one label special-cases a loop); a magnitude per gap on the hypothesis cards
(as in rounds 19 to 24: the readings beside each card already carry the counts).

## Round 26 (2026-10-15)

Reviewer's verdict: not understandable and correct. All 18 numbers checked matched the raw data or
came within the reviewer's own method's slack; hover, click and refresh sound. Found: the
broken-base loop shown healthy ("closable, not yet seen", signal "base broken 1") while the
pipeline manager had crashed fifteen minutes after waking on the break and the pause stood 14 h;
round 25's discovery-after-landing loop closed through a base check that failed on the host,
counted as a found defect, with a ring counting every approval and a "co-flow" label for a cycle
closed by information links; the hidden stock waking the reviewer and Orchestra (a decision on a
stock nobody can see), which produced 18 "variants" of that loop including the main chain; U
co-flowing into landed software through the landing, against its own definition; U in commits in
the design and defects in the template; the flows table advising a wake on every start for the fix
pickup and the re-pick; the timeout tile calling 18-hour-old history "the largest loss on this
page"; the gate tile's failing test overflowing; the discovery tile still wrapping; the Supervisor's
caption clipped; the inlet arrow off the canvas and its label struck; two band labels crossed by
verticals; Demand ↔ work in progress drawn on shared verticals; a shared stub label under the wrong
box; orange arrowheads on blue links; "1 pauses", "pipeline_paused", "CANCELLED"; known rework's
defect list breaking into fragments.

Fixed: a resident agent with no live session reads "not running" on the map and on every loop card
it sits on, naming what nothing now drains ("pipeline_manager is not running: … nothing drains
pipeline blocked"); the Supervisor, which the loop restarts on a human message, reads "starts on a
message"; the broken-base loop's signal is the design's B5, hours since main broke with nothing
landed (14.6 h, adverse past one hour); a failing build or base check no longer drains U (either can
be the host); U wakes nobody, and the agent whose verdict drains it inspects it (one link, reviewer);
U no longer co-flows into landed; U is in defects in the design; a declared loop matches only a
cycle with every declared stock on its path, so discovery after landing is a hypothesis again with
hollow stubs at the build and at demand, and its card says the pipeline manager files tickets by
hand; a cycle closed by a declared finding is "no causal polarity: balancing through undiscovered
rework, which the graph cannot see"; wake rules accept a from>to form at runtime and the flows table
advises it (REJECTED>IN_PROGRESS for the fix pickup); the timeout tile says "history: none since the
change" and carries no severity once the new limit has gone twenty turns unhit; the failing test
wraps; the discovery headline is the three counts; rows sit lower and the map has a left margin with
the inlet's label in it; along-row humps leave right of a box's centre and arrive left of it, each
slot on its own vertical; band and hollow labels fold onto narrower lines until they clear the
verticals (one label remains over a thin dashed co-flow, under its halo); a stub label sits under its
own box and a shared event is labelled at its leftmost box; negative arrowheads are blue; units are
singular at one; stub labels use words; known rework groups its open defects by where each change
sits ("CA-18, CA-24 at the gate · CA-39 blocked"). Unit tests: the hidden stock's only link, the
from>to wake rule and the flows table's advice, the broken-base signal.

Declined: a separate open-defects stock (the defect is an attribute of the change, a co-flow by
definition in a different unit; the known-rework box lists the open defects beside its level);
re-planning's tickets ↔ changes (a ticket becomes a change at the pickup one-for-one, so the circuit
conserves the count; the units name what each stock holds); bad-fix fraction per verdict rather than
per submission (each submission is an attempt an inspection judges, Rahmandad and Hu's rework
attempt; restarts do not create submissions).

## Round 27 (2026-10-15)

Reviewer's verdict: not understandable and correct. The headline numbers matched the raw log.
Found: the stoppage diagnosed two ways (the banner and the gate's caption "main fails the gate,
repair main"; the tests box "a suspect host"), while the run that paused had a candidate, CA-18,
failing the same acceptance stage again and never sent back; crash-restarting builds still counted
as escapes (round 26 had moved the rule into the model but not into the count); the
discovery-after-landing loop's members skipping Orchestra and work in progress, which produced the
gap advice "worker must wake on ticket_created" for a built-in process; gate send-backs counted
three ways (runs by start time in the tile, transitions in the ring, a lower dashboard by runs
started); the from>to wake advice unable to separate a fix pickup from a re-pick, or a defect from a
no-verdict return; a cancel stub on work in progress counted from Demand's cancel; only the reviewer
inspecting undiscovered rework; observed cycles through the hidden stock; rounds per ticket counting
machine losses; "commits on main" for gate landings; the turn-limit wording describing a silence
timeout as a cap, and its alarm retired on coordinator turns; labels travelling far from their pipes
or onto an unseen pipe; a hollow label detached from its stub; raw keys in hollow labels, the pairs
line and the flows table; the stub arrow grammar unexplained; the blue box border unexplained;
the broken-base mini ring's orange head and names on the arcs; "CA-18 ×2 runs" for two tickets;
drawers saying "last woken: never" beside runs, and promising a wake to a stopped agent.

Fixed: the readings carry one diagnosis of the pausing run (main's check, the candidate's own
failure and how many earlier rejections failed the same stage), and the banner, the gate caption
("paused: base check failed (host suspect)") and the broken-base hint all say it; escapes count
tickets citing shipped work only, the crash groups stay a proxy; the discovery loop names Orchestra
and work in progress; gap advice never asks Orchestra's own processes to change; gate runs are
windowed by when their result was known, so tile, pipe and ring agree, and the lower dashboard's
tile says it counts every run started; the flows table names stocks, shows wake events as code,
and where one wake event serves two flows says so and how an agent tells them apart until the event
carries its cause; a from>to wake form is noted as needing a loop started with this release; a
plain transition on a tracker stock counts only transitions out of that stock's states; every agent
whose verdict drains the hidden stock inspects it (reviewer and gate), and no cycle through it is
observed; rounds count defect send-backs only ("CA-18 sent back 12× for defects"); Landed reads gate
landings; turns were capped at 15 m then and are uncapped now, ended after 30 m of silence, the
"at the limit" flag needs a cap, and the alarm retires after ten worker and reviewer turns; labels
stay within 140 px of their pipe and fold rather than travel; a pipe nothing moved through is not
drawn (the flows table keeps it) and no stub stands in for it; labels keep off horizontal runs; the
hollow label sits by its own stub and uses stock names; the legend explains the stub arrows and the
blue border; mini-ring names face away from the ring and negative heads are blue; every gate
defect ticket is listed; the agent rows start below the capability row's labels; drawers say a
pickup woke the worker and that a stopped resident receives no wake-up. Unit tests: the pause
diagnosis, defect-only rounds, the inspection links and unobservable hidden cycles.

Declined: the "+" on the broken-base wake (a wake from a stock is a positive link: more paused,
more resume action; the drain is the negative one, so the pair is B); undiscovered rework's
declared outflow naming every review rejection (the event carries no cause yet, so the declaration
cannot filter it; the estimator and every label apply the cause, and the description says only
defect verdicts drain it); Orchestra writing its model template to the repository's main (the user
asked for the model to be tracked there; it is Orchestra's own file, not an agent's change);
five parallel verticals between Demand, work in progress and Blocked (each is a distinct flow,
now each on its own line; hover isolates one); a separate note on the page when the loop process is
older than the code (Orchestra has no version stamp on its process; the flows table says what the
from>to form needs). One label still crosses a vertical under its halo.

## Round 28 (2026-10-15)

Reviewer's verdict: not understandable and correct. Sixteen of seventeen numbers matched the raw log
and one came within method slack. Found: defects after landing 0 where CA-39, a ticket filed against
a crashing build, is a finding (round 27 dropped findings with the symptom); the pause diagnosed
one-sidedly as the host when the base log shows the server under test refusing connections, and
staging on main's build restarted three times during the check; "main needs no repair" and "the
server did not start" unsupported; Working build "up" in the level colour beside 14 restarts, and an
outage that can only close on a new deploy, so it grows without limit while the gate is paused; no
loop owning the 61% rework share (firefighting); capability closing through a ticket (CA-40)
undetected; earlier detection's wording; raw keys on hypothesis cards; gate wake advice pointing at a
review note; a label on a horizontal run, another crossed, stub labels missing or detached, humps
running through their labels; FCC's "n/a" set as a headline; "7 of them" without a noun; hovering a
zero-count flows-table row blanking the map; hovering an agent lighting every ticket creator through
the shared inlet; the worker drawer's built-in wording contradicting the map.

Fixed: escapes count every ticket citing shipped work, a crashing build's included (CA-39: 1), with
the crash groups a proxy beside it; the pause diagnosis is two-sided (for the host: the same commit
passed the gate before; for main: staging on main's build failed N times while the check ran;
"undetermined" when both), the unsupported claims are gone, the gate's caption reads "paused: main's
base check failed", and the tests box says "host or main undetermined"; an outage closes after an
hour without a restart or failure; a build that is up but restarted in the window reads "up" in amber
with its restarts; a signal-only firefighting loop (R) carries the rework share against Repenning's
tipping point and fix rounds and bad fixes, with a recipe, and is never drawn; earlier detection says
earlier than the field, not than review; hypothesis cards use stock names and name the custom agents
on no flow that could take a gap (qa_engineer, among others); the flows table's gate events point at
the gate run's stage result; humps are 96 px apart and the rows lower, so each hump label stands
above its own hump; tall labels search further for free space; every stub is labelled (the agent at
the first box, the count and event at the others) and stays within 60 px of its arrow; FCC reads "—"
with the reason in the caption; hours of turns that ended in a timeout say "h/d"; a zero-count row
lights its stocks and valve; an inlet no longer pulls in every other creator on hover; the drawer says
the loop wakes built-ins itself and the map draws the same rules. Unit tests: the outage rule, the
pause's staging evidence.

Declined: capability detected through ticket text (the detector reads bindings, never ticket prose; a
keeper that declares lesson_decided closes it, and the card says so); a debt-drag loop (no reading
measures debt yet; FCC landed is not measurable until a landing is fourteen days old); Orchestra's
model-template commits on main (as round 27: the user asked for the model to be tracked there; Landed
counts gate landings and says so); what each recipe would recover and cost per agent (as in rounds
19 to 24; the readings beside each card carry the counts); the pipeline manager's "repeated gate
rejections" trigger (a condition in the role's text, not an event; the drawer states it); the uneven
card grid; the re-planning ring's 3 of 7 (its tooltip says it counts blocks on this loop). One label
crosses a vertical under its halo.
