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
- discover flows from the stock levels alone, which subtracts what the measured flows (and the model's own equations) already explain, so it finds what the model is missing. Discovery runs on the server, in the Python engine in `sdlab/discovery` (the same one the bench measures), as a background job: the page stays responsive and shows the last findings while a new search runs, and "keep discovering" repeats it as data arrives;
- see where more speed would help a goal most (each flow made 10% faster in turn);
- import a measured history, for models whose stocks are read by sensor programs.

An **AI agent** is a machine with kind `agent`, program `agents/llm` and a prompt. It is given the items it took, the stocks it may write to and a glance at the stocks around it, and it calls an OpenAI-compatible model (`SDLAB_LLM_URL`, default the local server at `http://127.0.0.1:8081/v1`).

The model format is described in [MODEL.md](MODEL.md).

The research view (`/research`, the 🔬 button) shows discovery's research: the topics in `docs/research/` with their status and verdict, and the bench's saved runs over time (`~/.cache/sdlab/bench/runs`, or `$SDLAB_BENCH_CACHE/runs`), one run example by example, and two runs compared.

```
uv run sdlab --port 8020          # http://127.0.0.1:8020
uv run pytest -q                  # server, engine and discovery tests
node --test tests/*.mjs           # the page's simulator, simplify and teaching examples
uv run python tests/bench/evaluate.py   # the discovery bench (docs/DISCOVERY-LOOP.md)
```

Models are stored as JSON in `~/.sdlab/models/` (override with `SDLAB_HOME`). The examples in `sdlab/examples/` are read-only: they open as shipped, and the first change saves a copy among your models. The public URL is https://sdlab.dansproject.space, served through the `sdlab` cloudflared tunnel (`~/.cloudflared/sdlab.yaml`).
