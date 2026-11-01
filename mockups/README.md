# Page mockups: expected stocks and proposed machines

High-fidelity mockups of two proposed extensions, to `/dynamics` and `/machines`, for the owner's
scenario of 2026-10-31:

> "Ok I already have a task workflow that processes tickets and merges them to main, now I want a
> feedback loop where once per day an agent runs and tries to improve how many features get
> delivered per day. I think we need to start tracking features, then, because we currently
> aren't. I'm going to create a Features stock."

They are made from the real pages: the HTML `orchestra web` served, the real
`orchestra/web/static/*.js` and `style.css` from this checkout, and the plugins' scripts as they
were served. Only the server is missing. Every API answer comes from fixtures captured from the
agents demo (`--dummy`, with about 30 extra shell tickets so discovery finds a model). The
additions live in two files: `additions.css` and `additions.js`.

## Re-render

From the repository root:

    node mockups/tools/render.cjs                 # every frame, to mockups/out/
    node mockups/tools/render.cjs D2 E1 E4        # some frames

The script starts `tools/serve.py` on port 8187, renders each frame in headless Chrome for Testing
(puppeteer-core from `~/.npm/_npx`, Chrome from `~/.cache/puppeteer`; set `PC` and `CH` to use
others) at 1440 px wide, and writes `out/<frame>.png` (the full page) and `out/<frame>-1440x900.png`
(the first screen). It stops the server and its own Chrome when it is done. To look at a frame
live, run `python mockups/tools/serve.py` and open `http://127.0.0.1:8187/dynamics?frame=D2`.

## How it works

| file | what it is |
|---|---|
| `tools/capture.cjs` | logs in to a running demo, loads `/dynamics` and `/machines`, opens a stock drawer and a few machine dialogs, and records every same-origin response and the saved graph layouts |
| `tools/split.py` | turns the capture into `fixtures/api/*.json` (one per answer, readable), `fixtures/served/*.html`, `fixtures/plugins/` and `fixtures/bundle.js` |
| `tools/serve.py` | serves the served HTML with the mockup's scripts added, `/static/` from `orchestra/web/static`, `/plugins/` from the fixtures |
| `shim.js` | runs first: answers `fetch` from the fixtures (after every script has run, so `additions.js` can edit an answer per frame), stops the clock at the capture's moment, seeds `Math.random` and the saved layouts |
| `additions.js` | the frames: edits the fixtures' answers where the scenario changes what the server says, wraps the page's own functions (`SDGraph.build`, `tables`, `versionBar`, `draw`, `cards`, `NetGraph.create`'s `render`) to add the new marks, and draws the new panels in the pages' own markup |
| `additions.css` | the new marks, in the pages' tokens |
| `tools/render.cjs` | renders the frames |

Both graphs are pinned where a person would have dragged them (`MOCK.layout` in `additions.js`), so
every frame of a page has the same layout and nothing depends on the force or ELK layout settling.

## The visual language

- **ghost**: expected but absent from the inferred model. The same shape, dashed, at reduced
  opacity, its label readable, with a tag saying why: "expected · not in v15" for a part a version
  lost; **"not measured"** for a declared stock with no series (Features), never "not in v15".
- **candidate**: under a ghost, in italics, "may be: <stock>, recorded by <instrument> · ask the
  Supervisor to link". Linking is the Supervisor's (`link`), never a control on the page.
- **new in v15**: added by inference since the previous version. An accent ring and a "new in v15"
  tag (blue: inferred).
- **unconfirmed**: proposed by the Supervisor or added by you and not yet declared. Dashed violet,
  an "unconfirmed" tag; its confirm and discard *ask the Supervisor* (requests, P2 §6.2).
- **declared · never heard**: a declared machine nothing has been heard from. An outline with no
  fill, no halo, no links; with a "declared · measured" tag when instruments are attached (E4).
- **removed**: gone since the previous version. A faint dashed line, its label struck through.
- **expected**: a person said to always show it. A small gold pin.
- **read-only**: every field of the machine panels and D1's options is a value, not an input: a
  plain value with a rule at its left, indicator pills for a choice (●), and a dashed violet
  "✎ ask the Supervisor" where the frames used to offer "+ argument" or an input box. The only
  controls on the pages are P2 §6.2's closed list: expect, ignore, the D3 switch (observations),
  and confirm, discard and the Universal | Programmatic switch (requests to the Supervisor).
- On the Machines page, a change asked for in the Supervisor's chat is green ("+ added just now",
  "+ new link") or struck through ("− removed"), and gold for "changed just now".

## The frames

`base_dynamics` and `base_machines` are the pages as they are today, from the same fixtures.

| frame | page | what it shows |
|---|---|---|
| **D1** | /dynamics | "Features" declared. The diagram with every stock, plus **Features** beside DONE as a ghost, tagged "expected · declared by you · 2 min ago" and "not measured". The Features drawer: status "not measured → recording into a draft", "beside DONE (placed by the Supervisor)", the Supervisor's four options, each with its **cost** and **clearance** line (a: passing acceptance tests on main, from the JUnit report CI publishes; b: e2e the same way; c: tickets labelled `feature` reaching DONE, from the task system's counters; d: a simulated ramp). The radios are read-only indicators ("tell the Supervisor to switch"); a is "recording · draft", "recording since … · draft, expires in 24 h unless kept · instrument features.acceptance · 3 points", a sparkline, and the collapsed script "written by the Supervisor · ~/.orchestrator/&lt;key&gt;/agents/instruments/features_acceptance.sh" with its `[[collect]]` entry (`draft = true`). |
| D1-closed | /dynamics | D1 with the drawer closed: the ghost on the diagram, and the Stocks table's **Expected** group (Features: "not measured → recording into a draft"). |
| **D2** | /dynamics | After rediscovery, the diff view: "changes since v14" on; the new stock **acceptance tests passing** ringed "new in v15" with its fitted flow from DONE; Features a ghost "expected · not measured" with its **candidate line** ("may be: acceptance tests passing, recorded by features.acceptance · ask the Supervisor to link"); the removed flow files → commits struck through. The **Changes since v14** panel: + stock with expect / ignore, + flow with no buttons ("with its stock"), − flow, ○ Features with its candidate line, collapsed "came and went" and "ignored", and "Against version 14, saved 18:59 (2 h ago)" from the base version's save time. |
| **D3** | /dynamics | The stock drawer of acceptance tests passing with the switch "Expected: always show this stock" (on; an observation, allowed on the page) and its provenance. |
| D3-closed | /dynamics | D3 closed: the stock with the gold "expected" pin; Features still a ghost, "not measured", with its candidate line; the Expected group listing both. |
| **E1** | /machines | **feature_count_improver** proposed: dashed, "unconfirmed", the highlight (full, .45, shadowed). The panel: title, its id and bus source, the status strip whose confirm / discard ask the Supervisor, the owner's quote, then separate rows for **kind** (Universal \| Programmatic, "described by what it achieves: its steps, its invariants and what it uses"), **managed** (orchestra \| external) and **engagement** (ad hoc \| continuous \| scheduled); read-only title, description, tags; invariants, steps, **uses** (what it may act on), receives (each "a guess"), emits `work.improvement_proposed` ("new type", nobody listens yet), reads, and the expected effect per P4 §2.5 (Features ↑ "waits for a series", DONE inflow ×1.2, gate rejections ×0.8, a flow that appears into the coordinator's queue; horizon 7 days). Footnote: "Confirm asks the Supervisor". Its card heads the grid, kind "universal". |
| **E2** | /machines | Refined in conversation: receives `changes.requested`, `gate.rejected`, `gate.landed` "+ added just now", `session.settled` and `task.reported` struck through; the coordinator to listen for `work.improvement_proposed` ("+ added just now", a green dashed link); engagement **scheduled · daily at 00:00 · America/Los_Angeles**, "changed just now", "was continuous: …" (`latest.before`); the steps rewritten. |
| **E3** | /machines | **nightly_metrics**, added by you: kind Programmatic, managed orchestra, engagement **ad hoc** (indicator); the box under it is that mode's interface: command, arguments, environment ("✎ ask the Supervisor to add one" instead of "+ argument" / "+ variable"), stdin, exit. |
| E3-continuous | /machines | The same, continuous: command (a daemon), protocol, listens on, send, receive (poll `getTasks()` every 10 s), health. |
| E3-external | /machines | The same with **managed: external** (shown in the managed row, not as a tab) and engagement continuous: no command, its source `nightly_metrics`, where it runs, its log not readable. |
| **E4** | /machines | A declared existing machine **sail** (SAIL, the company's landing queue), measured and never heard: on the map an outline, "declared · never heard", no halo, no links (the rest shadowed by the highlight rule); its card "seen: never heard · measured by 1 instrument · 3 instances (last hour) · last measured 1m ago" and a "measured ×3" row; the panel's kind / managed (external) / engagement rows, "Instances: none heard on the bus", and the **Measured by** section (P5 §3): the instrument `company_prom` (`[[sources]]`), its match, instance label `runner`, the series it matches, and the three measured runners with their last values (runner-3 `sail_up = 0`: measured, not up); Flows "none hypothesised yet"; Log not readable. |

## What changed on 2026-11-01, and why

The frames were brought in line with the accepted proposals (`docs/proposals/intended-model.md`,
P2; `machine-design.md`, P4; `instruments-on-machines.md`, P5) so that C2 and C3 compare the
built pages with correct targets.

- **Only the closed list of controls** (P2 §6.2, §7 "Read-only renderings"): every E panel field,
  E3's "+ argument", "+ variable" and input boxes, and D1's option radios became read-only
  indicators with "ask the Supervisor" / "tell the Supervisor to switch". Confirm and discard on a
  machine, and the kind switch, are requests: "confirm asks the Supervisor" (E1's footnote no
  longer says it starts the machine under the agents' host).
- **The envelope** (P2 §2, P4 §2.3): kind (universal \| programmatic), managed (orchestra \|
  external) and engagement (ad hoc \| continuous \| scheduled) are three rows; E3's tabs are the
  interface for the engagement mode, and external is shown by the managed row, never as a tab. Ids
  follow `^[a-z][a-z0-9_]{1,40}$`: `feature_count_improver`, `nightly_metrics`. A Universal
  Machine is not described in AI terms (P4 §2.3): "an AI agent: a prompt, its tools and its events"
  became "described by what it achieves: its steps, its invariants and what it uses". The
  Universal `uses` row (what it may act on) was added (P2's envelope dropped it to P4's `spec`;
  goal log 2026-11-01).
- **The improver's own event type** (P4 §2.6, "Where this differs from the frames"): it emits
  `work.improvement_proposed`, new, with no listener in E1; E2's refinement adds the coordinator as
  its listener. Its expected effect is in rates (P4 §2.5), with Features "waits for a series".
- **D1** (P4 §2.2 and "Where this differs"): "as the Supervisor wrote them on DEMO-35" became
  "written by the Supervisor · ~/.orchestrator/&lt;key&gt;/agents/instruments/…"; the chosen
  option is "recording · draft" until kept; every option has its cost and clearance; option a
  reads CI's JUnit report rather than running the suite in the working tree; "where you said it
  belongs" became "placed by the Supervisor" (the owner's quote did not name the place).
- **D2, D3** (P2 §3.2, §6.1, §7): a declared stock with no series is "not measured"; the ghost has
  its candidate line; the + flow row has no buttons and says "with its stock" (the coordinator's
  judges' list; P2 §7 still lists expect / ignore on every + row, see below); the base version's
  save time comes from `since_saved_at`; collapsed came-and-went and ignored rows.
- **E4** is new (P5 §3): a declared machine measured and never heard.

## Where the mockups depart from the scenario

- The demo's model has **READY FOR REVIEW**, not IN REVIEW (that is what discovery found from the
  captured data).
- Times are relative to the capture's moment (20:58 local), so "recording since" reads 20:27
  rather than 14:02.
- Model versions 1 to 14 are the captured version 1 repeated (the demo saved one version); the
  removed flow files → commits never existed in the demo and is drawn only as v14's ghost.
- The new stock's series, flow and fit (a net flow, `0.034 × DONE`, from correlation) are made up
  in `additions.js` from the DONE stock's shape; the drawer's level chart runs them.
- The proposed machines are added to the `/api/machines` answer; nothing like them ran. SAIL's
  owner quote, its instrument `company_prom` and its runners' values are made up in `additions.js`.
- **E1 is continuous** with "was continuous" in E2, as P2 §7 and the judges' list keep it; P4 §2.6
  has the improver scheduled daily from the first turn (time a guess), so that E2 would read "was
  daily, time a guess". The frames keep the approved story.
- **The + flow row** follows the judges' list ("with its stock", no buttons); P2 §7 lists expect /
  ignore on every + row. One of the two should be amended.
- The map draws `work.improvement_proposed` and E2's coordinator link from the declaration
  (`intended_edges`), though nobody listens for it yet and the page today hides events nobody
  listens for.
