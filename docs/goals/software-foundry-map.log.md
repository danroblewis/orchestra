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
