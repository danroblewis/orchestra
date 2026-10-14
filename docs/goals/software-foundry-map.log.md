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
