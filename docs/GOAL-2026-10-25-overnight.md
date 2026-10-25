# Overnight goal (2026-10-25)

Run in Claude Code as `/goal <the text below>`.

```
/goal Finish the open Orchestra work on a new branch, unattended, within 8 hours.

Setup: in ~/orchestra_2, commit the current uncommitted work on sd-kernel (sd/simulate.py, /api/dynamics/simulate, background.model rename), then create branch `dynamics-machines-tasks` from it and do everything below there. Commit after each finished item, with clear messages ending in the Co-Authored-By line. Do not push.

1. Dynamics layout keeps its shape:
   - Saved positions merge and never drop nodes that are off screen right now.
   - Cloud ids are stable (keyed by stock and direction, not by flow id), and parallel edges spread their bends.
   - On a structural change (rediscover, timer), nodes that already have a position stay put. Only new nodes settle, placed near their neighbours. Re-fit only when new nodes appear.
   - Dragging moves only the dragged node and never reheats the whole layout.
   - Weak gravity keeps nodes from flying off.
   - A "tidy" button re-runs the layout on purpose.
   - Source clouds are pulled to the top-left, sink clouds to the bottom-right, measured inputs to the left.
2. Stock drawer:
   - Measured level, the simulated level since the era began (sd/simulate.py), and a projection from now.
   - A projection-horizon input (minutes, remembered per viewer).
   - Dashed lines in charts.js.
   - Flows split into inflows (fill it) and outflows (drain it, plotted below zero), plus a net line.
   - Say which flows were replayed, not simulated.
   - Unit tests for sd/simulate.py with known steady states.
3. Machines page: clicking a machine opens a dialog with its instances, mode, publishes and listens-for, its metrics, recent events, and the tail of its log.
   - Logs: a machine announces its log file in orchestra.machine.started (data.log). The bakery's Machine helper sends it from an env var that bin/bakery-ctl sets.
   - The web server reads only regular files whose real path is under the project's repo root or state dir, read-only, and refuses anything else. Reuse core.logs where it fits.
4. Update SPEC.md, AGENTS.md (any rule change stated in the commit) and the handoff doc.
5. Tasking management as a loadable package of machines, in its own local repo (~/orchestra-tasks, never on GitHub), using Orchestra as a library like the bakery. Orchestra's core learns no tickets.
   - Machines: a tracker (its own store, the state transitions, leases), a dispatcher, and a worker that runs a fake or real harness.
   - Events in the CloudEvents envelope.
   - Plain metrics, so discovery finds its stocks (waiting, in progress, in review, done).
   - A ctl script like bakery-ctl.
   - Done when it runs end to end with fake workers, discovery finds its stocks and flows, and the Dynamics and Machines pages show it.

Rules:
- Follow AGENTS.md.
- ~/orchestra/sdlab is read-only.
- Do not touch ~/orchestra-automata or its live `orchestra run`.
- Do not wipe ~/.orchestrator.
- Kill any headless Chrome you start.
- Keep `uv run python -m pytest` passing and ruff clean on new code.
- Check every UI change with Puppeteer screenshots against the running bakery (restart it with bin/bakery-ctl).

Finish with a short report in docs/: what's done, what isn't and why, screenshots' paths, and how to run each thing.
```
