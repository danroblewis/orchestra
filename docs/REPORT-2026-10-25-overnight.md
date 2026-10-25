# Overnight report (2026-10-25)

The plan was `docs/GOAL-2026-10-25-overnight.md`. All five items are done. Orchestra's work is on
branch `dynamics-machines-tasks` (from `sd-kernel`). The bakery and the new task system are in
their own local repos. Nothing was pushed.

## What's done

| Item | Where | Commits |
|---|---|---|
| Setup: the simulator work committed on `sd-kernel`, then the branch | Orchestra | `6122d56` |
| 1. The Dynamics layout keeps its shape | `orchestra/web/static/netgraph.js`, `dynamics.html` | `10e8868`, `5565c5b` |
| 2. A stock's drawer: simulation, projection, inflows and outflows | `orchestra/sd/simulate.py`, `static/dynamics-live.js`, `static/charts.js` | `6122d56`, `b91f4ac` |
| 3. A dialog per machine, with its log | `orchestra/web/machines.py`, `web/machine_logs.py`, `static/machines.html`; the bakery's `bakery/machine.py`, `bin/bakery-ctl` | `a4480af`; bakery `536ae77`, `77744fe` |
| 4. SPEC, AGENTS (invariant 2), handoff | `SPEC.md` §2 and §10, `AGENTS.md`, `docs/HANDOFF-2026-10-25.md` | `a4480af` |
| 5. Task management as a package of machines | `~/orchestra-tasks` (new, local) | tasks `7efd467` |

Tests: 77 passed and 39 skipped in Orchestra (the skips are server backends that run only when
asked), and 7 passed in orchestra-tasks. Ruff is clean on the new code. Two older warnings remain
in `web/app.py`.

### 1. The layout

- **When nodes move:** the forces place nodes only when they have to:
  - every node, the first time;
  - after a rediscovery or the timer, only the new nodes, each started next to its neighbours, while every known node is held still;
  - every node again, only when you click **tidy** (it lays out around the nodes you placed) or **reset** (it starts from scratch).
- **Saved positions:** a position is kept for every node ever placed, not only the ones on screen, so a stock that drops out of one discovery comes back to its spot.
- **Dragging** moves only the node you drag. Before, it restarted the whole layout.
- **Weak gravity** replaces the centring force, so nothing flies off.
- **Clouds:** each stock has one source cloud and one sink cloud. Their ids come from the stock, because flow ids change between discoveries. Sources are pulled top left and sinks bottom right; measured inputs sit to the left.
- **Smaller fixes:** parallel arrows spread apart, long equation labels are shortened on the diagram, and "fit" includes the system's frame.
- **A bug the Machines page showed:** a redraw every 5 s stopped a layout that was still settling, so the graph froze half placed. A layout in progress now carries on through redraws.

**Checked by:** `pptr/layout.mjs`. It drags a stock, removes it and its flows, brings them back, and reloads. Nothing else moves, the dragged stock returns to where it was dropped, and no node ends up far off.

### 2. A stock's drawer

- **Three lines on the level chart:**
  - the measured level;
  - **the equations**: the level they give, starting from the measured levels when the era began (the start of the window the model was fitted on), with nothing else but the measured inputs;
  - **projected**: the level from now, as far ahead as you choose. The minutes ahead are remembered per browser.
- **The simulator:** both runs use SD Lab's simulator (`orchestra/sdlab/discovery/simulate.py`). It handles effects and measured inputs, and nothing leaves a stock that isn't there.
- **Replayed flows:** a flow with no form the simulator can step (an SD Lab expression, or no equation) is replayed from its observed rate, and the drawer names those flows.
- **Inflows and outflows:** listed separately ("fills it", "drains it") and charted with inflows above zero, outflows below, and a net line.
- **Tests:** `tests/unit/test_simulate.py` checks known steady states, rates per step versus per minute, that no stock goes below zero, and replay.

### 3. A dialog per machine

- **Opening it:** click a machine's card, or its node on the event map.
- **Contents:**
  - its instances;
  - how it is engaged;
  - what it publishes and listens for;
  - its series' latest values;
  - its last events (envelope only: Orchestra still never reads the `data`);
  - the tail of its log, with a button per instance, refreshed every 5 s.
- **Logs:** an instance may say where its log is (`data.log` in `orchestra.machine.started`).
  - **Why reads are restricted:** anything that can publish could name any file.
  - **The rule:** the web server reads a log only when its real path (links followed) is a regular file inside the project's repository or state directory. Everything else is refused. `tests/unit/test_machine_logs.py` covers climbing out with `..`, symlinks and directories.
  - **Orchestra's host:** its dialog shows its own log.
- **Bakery side:** the bakery's machines now announce their log (`bakery-ctl` tells each one its file) and log every event they publish. `bakery-ctl restart <name>` restarts a single process.

### 4. Docs

AGENTS.md invariant 2 now says an instance's announcement may include where its log is, and how that log is read. SPEC §2 and §10 describe the dialog, the simulation and the layout rules.

### 5. Task management (`~/orchestra-tasks`)

- **Machines:**
  - **planner:** tasks arrive at random, at a rate that rises and falls over 40 minutes.
  - **tracker:** the only machine that changes a task's state, by a transition table, with a lease on every assignment.
  - **dispatcher:** offers waiting tasks to free workers; the tracker accepts or declines.
  - **worker ×3 and reviewer ×2:** each runs an agent per task through Orchestra's Claude Code harness.
- **Agents:** by default the binary is `bin/fake-claude`. It speaks Claude Code's stream-json protocol, writes a transcript where the harness reads it, takes about as long as the task's size says, and sometimes fails, wanders off past its lease, or rejects. `TASKS_REAL_AGENT=1` uses the real `claude`, which costs money.
- **Metrics:** every state is a gauge and every transition a counter, so Orchestra can discover the stocks.
- **Status:** it runs end to end; tasks go from created to done through work, review, rework and expired leases. The Machines page shows the whole system and its feedback loops.

**Discovery on about 15 minutes of data** (`orchestra sd discover --strategy conservation --minutes 20`):

- **Found:** the stocks `tasks_waiting`, `tasks_in_review` and `tasks_done`, with the tracker's counters attached to the tracker. The review stage has the right shape: tasks enter at the rate they are submitted, and `approved` (2.5 × in review per minute) and `rejected` (0.95 × in review per minute) drain it in proportion to how many are in it.
- **Noise:** it also took the planner's demand gauge and the count of free reviewers as stocks, and some fits read the demand. That is too little data. The waiting queue is also growing (29 waiting), because demand at its peak is more than three workers can do, which is by design.
- **Next look:** after an hour or more of data.

## What isn't done, and why

- **Version churn:** with `kalman_lna`, nearly every rediscovery saves a new model version, because the structure changes a little each time. The bakery is at version 79 after about 7 hours. That is a discovery question (when a change in structure is real), not a UI one, so I left it. The layout fixes stop it from scrambling the diagram.
- **Odd fits:** some SD Lab fits are nonsense on short windows, such as a hidden stock with a rate of −2,607,029. The drawer shows them as they are.
- **Real agents:** I didn't run the task system with real `claude`. It is wired and tested only against the fake.
- **Lost events:** in the task system, an event published while the tracker is down is lost. The README lists this.

## Screenshots

In `/private/tmp/claude-501/-Users-daniellewis-orchestra-2/70d7e325-aa39-4e7c-89bf-424dc180d7a7/scratchpad/`:

| File | What it shows |
|---|---|
| `lay-0.png` | Dynamics: first layout |
| `lay-1.png` | After a drag, a structure change and a reload |
| `lay-reset.png` | After "reset" |
| `drawer-stock.png` | Stock drawer: measured, the equations, the projection; inflows and outflows |
| `machine-baker.png` | The baker's dialog |
| `machine-host.png` | The host's dialog |
| `tasks-machines.png` | The task system's event map |
| `tasks-worker.png` | A worker's dialog |
| `tasks-dynamics.png` | The task system's Dynamics page after 9 minutes (`kalman_lna`) |

The scripts that took them are in `…/scratchpad/pptr/`: `layout.mjs`, `drawer.mjs`, `mdlg.mjs`, `tmach.mjs`.

## How to run each thing

    # Orchestra's tests
    cd ~/orchestra_2 && uv run python -m pytest

    # the bakery: web on :8050
    cd ~/orchestra-bakery && bin/bakery-ctl start | stop | status | restart <name>

    # the task system: web on :8060
    cd ~/orchestra-tasks && bin/tasks-ctl start | stop | status | restart <name>
    .venv/bin/tasks status                                   # tasks per state
    .venv/bin/python -m pytest
    .venv/bin/orchestra sd discover --strategy conservation --minutes 30

Both systems are running now. They need the demo stack (`deploy/dev/compose.yaml`: Redis and
VictoriaMetrics).
