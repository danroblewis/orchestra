# Goal: the Agents page shows the software foundry's stocks and flows, understandably and correctly, in the automata project

Build `docs/proposals/software-foundry-model.md` (read it first; it is the design) and keep
iterating until an independent review agent, using a real browser against the live automata
project, says the model is understandable and correct and lists no defects. Then stop.

The product of this foundry is good software, not tickets. The map must show what the foundry
holds and produces (demand, work in progress, known and undiscovered rework, landed software,
the working build, verified behaviour, environment resources, agent capacity) and the loops
that govern it, with every number traceable to the event log, the gate, the repo, or a
declared estimator. The ticket-state pipeline is a drill-down, not the map.

## The cycle

1. Spawn a fresh `general-purpose` review subagent each round (never reuse one, never a fork).
   Give it the "Reviewer brief" below verbatim plus a short list of what changed since the
   last round.
2. Read its findings. Fix every defect it reports. For anything you decline, write one sentence
   of why in `docs/goals/software-foundry-map.log.md`.
3. Run `uv run pytest tests/unit -q` in `~/orchestra-wt/harness`; all must pass. Every metric,
   estimator, or detection change gets a unit test (`tests/unit/test_foundry.py`,
   `test_eventgraph.py`, `test_eventmap.py`); use the real event shapes from the demo log.
4. Restart only the web process on port 8003, never the runner:
   `kill $(pgrep -f "orchestra web --port 8003"); cd ~/orchestra-automata && nohup ~/orchestra-wt/harness/.venv/bin/orchestra web --port 8003 >> ~/Library/Logs/orchestra-automata/web.log 2>&1 &`
5. Commit on `harness-agnostic` in `~/orchestra-wt/harness` and push.
6. Append a round entry to `docs/goals/software-foundry-map.log.md`: round number, the
   reviewer's verdict, what was fixed, what was declined and why.
7. Repeat. The goal is met only when two consecutive rounds, from two different reviewers, end
   with "understandable and correct" and no defects.

Build order, from the spec's section 7: metrics and built-in stock definitions first, then the
gate's test counts and diff sizes, then the git estimator, then declared stocks with the
Supervisor tools and `stock_measured` events, then the page. Do not start the page before the
numbers behind it exist and are tested. If a reviewer finding needs a declared stock, build the
smallest version the spec describes, never a special case. Keep the spec in step with what is
built; when the build teaches something the spec got wrong, change the spec in the same commit
and say so in the log.

## What "understandable and correct" means

- A reader who knows what a merge gate and a test suite are, but has never seen Orchestra, can
  say within a minute what the foundry is producing, where work is piling up, where defects are
  being found and how late, and which agent sits on which flow.
- The headline readings (FCC first pass, discovery split, discovery delay, rework share, landed
  per day, lead time, change failure, time to restore) are present, each with a tooltip stating
  its exact estimator and window, and the reviewer can reproduce at least four of them from
  `~/.orchestrator/orchestra-automata-db8ce182/events.jsonl`, `tickets.json`, or the repo.
- Hidden stocks (undiscovered rework) are shown as estimates with a range, or as "not yet
  estimable" with the reason, never as a count.
- Mass balance holds for the directly measured stocks over the window.
- The loop table lists the six literature loops and every Supervisor-named loop with its
  signal's current reading and direction, and shows the "what to add" hint only when the
  signal is adverse.
- Declared stocks, if any exist in the automata project, appear where their producers and
  consumers put them; if none exist, the page says how one is declared.
- Nothing is duplicated, clipped, overlapping, or illegible at 1280 and 1600 px wide. Hover
  isolates the right things; clicking an agent opens its drawer; the page updates live.

## Reviewer brief (give verbatim)

> You are a senior consultant in software engineering management and system dynamics. You
> have twenty years of modelling software organisations in the tradition of Abdel-Hamid and
> Madnick, Cooper's rework cycle, Lyneis and Ford, Madachy, and Repenning and Sterman, and you
> have run delivery organisations that lived by the DORA keys. You know what a stock, a flow,
> a delay, and a loop polarity mean, and you have seen many dashboards that used the words
> without the discipline. You are also fluent in the craft of quantitative display (Tufte,
> Few, Cleveland): you judge encodings, not decoration. You have never seen this product.
>
> You are reviewing the "Stocks and flows" section at the top of http://127.0.0.1:8003/agents,
> a system-dynamics view of an AI software foundry called Orchestra: AI agents are the machines,
> the product is good software. The design it implements is
> `~/orchestra-wt/harness/docs/proposals/software-foundry-model.md`; read it first, and judge
> the page against both the design and the published rework-cycle literature it cites
> (`docs/research/` beside it). Use a real browser: the Playwright venv at
> `/private/tmp/claude-501/-Users-daniellewis-orchestra/30b084ac-356e-4334-af44-251920c53fe1/scratchpad/pw/.venv/bin/python`
> (chromium headless; screenshot at 1280 and 1600 px wide; hover stocks, valves, agents and
> loop rows and screenshot those; click an agent; reload after 30 s and confirm numbers move
> or stay as the log says they should). Look at every screenshot yourself. Fetch
> http://127.0.0.1:8003/api/eventmap and http://127.0.0.1:8003/api/state, and check at least
> four headline numbers against the raw data for the stated window:
> `~/.orchestrator/orchestra-automata-db8ce182/events.jsonl` (`ticket_transition` with `from`
> and `to`; `gate_*` with `gate_run` and `tickets`; `staging_*`; `session_*`; `turn_timed_out`;
> `note_added` with `author` and `kind`), `tickets.json` there, and the repo `~/orchestra-automata`
> (`git log main`, `tests/`). Code: `~/orchestra-wt/harness/orchestra/loopmetrics.py`,
> `orchestra/foundry.py`, `orchestra/eventgraph.py`, `orchestra/api_org.py`,
> `orchestra/web/static/agents.html` (`eventMap`, `loopTable`). Do not change any file.
> Report: (1) whether a newcomer can say in one minute what the foundry produces, where work
> piles up, where defects are found and how late, and which agent sits on which flow;
> (2) every number you checked, how you computed it, and whether it matched; (3) every place
> the model departs from the rework-cycle structure or mislabels a stock, flow, or loop
> polarity; (4) every visual defect (overlap, clipping, illegible text, duplicated
> information, misleading encoding) with the screenshot that shows it; (5) every functional
> defect (hover, click, refresh, stale data); (6) whether an operator could decide from this
> page where to add an agent or an event binding, and what is missing for that; (7) your
> verdict: "understandable and correct" with no defects, or a prioritised list of what must
> change. Write as you would to a client who is paying for your judgement: specific, direct,
> with the reasoning a practitioner would give. Vague praise is useless; so is a defect
> without the evidence for it.

## Constraints

- Work in `~/orchestra-wt/harness` on branch `harness-agnostic`. Never merge or touch `pair-spike`.
- Never restart the automata runner (`orchestra run`); it cuts running agent turns. The web
  process on 8003 may be restarted freely.
- Do not change ticket state in, or talk to the Supervisor of, the automata project.
- Follow `AGENTS.md`: only Orchestra changes ticket state; state goes through the store; roles,
  agents, teams, and now stocks are data behind the store; keep modules small and
  single-purpose (metrics in `loopmetrics.py`, built-in stock definitions in `foundry.py`,
  graph in `eventgraph.py`, estimators that run commands under the `Prober`).
- An AI judge estimator, if built, pins its model and rubric, asks for a class from a fixed
  list, samples N times, records the mode and the agreement, and starts a new series when the
  instrument changes.
