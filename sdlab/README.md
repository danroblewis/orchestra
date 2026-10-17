# SD Lab

Design a system dynamics model, then apply machines to its flows.

- **Stocks** are the measurable things.
- **Flows** say how stocks change, through an equation: a constant rate, a rate proportional to a stock, or a rate that closes the gap to a goal.
- **Machines** (people, AI agents, programs) are defined separately and applied to flows. A flow takes its machine's colour.
- A flow with no machine does not run. A flow applied to the **environment** happens on its own, such as spoilage or customers arriving.
- A machine shares its capacity across its flows. When the work asked of it is more than its capacity, all its flows slow down.

Stocks can also shape flows they are not part of: an **effect** speeds a flow up or slows it down with a stock's level, a **use** (co-flow) means each unit moved uses up some of another stock, and a machine's **capacity** can be per unit of a stock (per worker, per bit).

The page has two modes: **Edit** (stocks, flows, machines) and **Run**. Run shows what really happened in a live run beside what the model projects, by era (every change to the system's configuration starts one). From a run you can:

- fit each flow's equation to what happened, or fit them all;
- discover flows from the stock levels alone, which subtracts what the measured flows already explain, so it finds what the model is missing; flows leaving the model and flows arriving that match up hint at a stock nobody measures;
- see where more speed would help a goal most (each flow made 10% faster in turn);
- import a measured history, for models whose stocks are read by sensor programs.

An **AI agent** is a machine with kind `agent`, program `agents/llm` and a prompt. It is given the items it took, the stocks it may write to and a glance at the stocks around it, and it calls an OpenAI-compatible model (`SDLAB_LLM_URL`, default the local server at `http://127.0.0.1:8081/v1`).

The model format is described in [MODEL.md](MODEL.md).

```
uv run sdlab --port 8020          # http://127.0.0.1:8020
uv run pytest -q                  # server tests
node --test tests/sim.test.mjs    # simulator tests
```

Models are stored as JSON in `~/.sdlab/models/` (override with `SDLAB_HOME`). The examples in `sdlab/examples/` are copied there on first start. The public URL is https://sdlab.dansproject.space, served through the `sdlab` cloudflared tunnel (`~/.cloudflared/sdlab.yaml`).
