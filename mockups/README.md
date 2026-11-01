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
    node mockups/tools/render.cjs D2 E1           # some frames

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
  opacity, its label readable, with a tag saying why ("expected · not in v15").
- **new in v15**: added by inference since the previous version. An accent ring and a "new in v15"
  tag (blue: inferred).
- **unconfirmed**: made by a person or the Supervisor and not yet real. Dashed violet, an
  "unconfirmed" tag, confirm and discard in its panel or drawer.
- **removed**: gone since the previous version. A faint dashed line, its label struck through.
- **expected**: a person said to always show it. A small gold pin.
- On the Machines page, a change asked for in the Supervisor's chat is green ("+ added just now",
  "+ new link") or struck through ("− removed"), and gold for "changed just now".

## The frames

`base_dynamics` and `base_machines` are the pages as they are today, from the same fixtures.

| frame | page | what it shows |
|---|---|---|
| **D1** | /dynamics | "Features" declared. The diagram with every stock (OPEN, IN PROGRESS, READY FOR REVIEW, DONE, commits, files, test report files), plus **Features** beside DONE as a ghost, tagged "expected · declared by you · 2 min ago". The Features drawer is open: status "no series yet → recording", the Supervisor's four ways to measure it (a: passing acceptance tests on main, a `[[collect]]` script running `pytest tests/acceptance --junitxml` every 15 min, chosen; b: e2e tests; c: tickets labelled `feature` reaching DONE, from the task system's counters; d: a simulated placeholder ramp), with the chosen one "recording since … · instrument features.acceptance · 3 points", a sparkline, and the collapsed script with its first lines and its `[[collect]]` entry. |
| D1-closed | /dynamics | D1 with the drawer closed: the ghost on the diagram, and the Stocks table's new **Expected** group (Features: "no series yet → recording"). |
| **D2** | /dynamics | After rediscovery, the diff view. The version bar's real controls ("version 15 of 15 · current … 3m ago") and a new "changes since v14" switch, on. The new stock **acceptance tests passing** (found from the recorded series) with its ring and "new in v15" tag, and its fitted flow from DONE (accent, "new in v15"). Features stays a ghost: "expected · not in v15". The removed flow files → commits as a struck-through ghost. A **Changes since v14** panel beside the loops (+ stock with expect / ignore, + flow, − flow, ○ expected-but-missing Features). Four new legend entries. The tables mark the new stock and flow, and list the removed flow struck through. |
| **D3** | /dynamics | The real stock drawer of acceptance tests passing (balance, trust, behaviour, level chart: unchanged), with a new switch at the top, "Expected: always show this stock" (on), and "confirmed expected · present in v15 · tracked by inference since v15". |
| D3-closed | /dynamics | D3 with the drawer closed: the stock without its "new" tag, with the gold "expected" pin; Features still a ghost with "your note · waiting for a flow"; the Stocks table's Expected group listing both. |
| **E1** | /machines | The map "with event types". A new **feature-count-improver** node, dashed and tagged "unconfirmed", linked to the events the Supervisor guessed (listens for `session.settled` and `task.reported`, publishes `work.requested`). Its neighbourhood is at full colour, the next ring at .45, the rest shadowed (the page's own `ng-dim`, .1). A **details panel** on the right of the map: proposed by the Supervisor, confirm / discard, the **Universal \| Programmatic** switch on Universal, title, description, tags, engagement (continuous), invariants, five steps, receives, emits, reads (Features, acceptance tests passing) and the **expected effect** (Features ↑, DONE tickets ↑, gate rejections ↓, each linking to the Dynamics page; "a prediction, judged later"). Its card heads the card grid, "unconfirmed". |
| **E2** | /machines | Refined in conversation. The panel shows the live diff: receives `changes.requested`, `gate.rejected`, `gate.landed` "+ added just now", `session.settled` and `task.reported` struck through ("− removed"); emits `work.requested` to the coordinator; engagement **scheduled · daily at 00:00**, "changed just now"; the steps rewritten. On the map the removed links fade to ghost lines, the new ones are green with a ring and "+ new link" on their event types, and the node reads "scheduled · daily". |
| **E3** | /machines | The panel switched to **Programmatic**, for `nightly-metrics` (added by you, unconfirmed): command `python -m tools.nightly_metrics`, mode tabs **ad hoc \| continuous \| external** with ad hoc selected: arguments, environment variables, stdin "JSON of the offer", exit codes. |
| E3-continuous | /machines | The same, continuous selected: protocol HTTP / GraphQL / gRPC / other, send events `POST /events`, receive events poll `getTasks()` every 10 s or push. |
| E3-external | /machines | The same, external selected: "not managed by `orchestra run`: a continuous machine with no command; known only by its events", with its source name. |

## Where the mockups depart from the scenario

- The demo's model has **READY FOR REVIEW**, not IN REVIEW (that is what discovery found from the
  captured data).
- Times are relative to the capture's moment (20:58 local), so "recording since" reads 20:27
  rather than 14:02.
- Model versions 1 to 14 are the captured version 1 repeated (the demo saved one version); the
  removed flow files → commits never existed in the demo and is drawn only as v14's ghost.
- The new stock's series, flow and fit (a net flow, `0.034 × DONE`, from correlation) are made up
  in `additions.js` from the DONE stock's shape; the drawer's level chart runs them.
- The proposed machines are added to the `/api/machines` answer; nothing like them ran.
