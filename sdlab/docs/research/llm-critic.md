# An LLM structural critic in the loop

**Status:** idea (not started)

## Why
The structural mistakes in failing runs are obvious to a person reading the found model with the
stocks' names and units: "customers drains faster when new_tickets is high" (sd-support-tiers), "done
drains faster when toner is high" (sd-print-shop), "None -> adults, link from in_port" (sd-fishery). So
far humans have run the diagnose-and-expand loop between experiments.

A language model can be given:
- the found flows;
- the stocks' names, units, groups and `final`;
- per-row residual statistics and the judge's per-stock errors.

It proposes a short list of typed edits, and each edit is fitted by our own fitter and kept only if
the judge (and the behaviour gate) improves. That is "generate broadly, verify strictly", as in
FunSearch and LLM-guided equation discovery. [llm-priors](llm-priors.md) differs: it is a prior on
names before fitting, never seeing the fit or its failures. Discovery is allowed to see names; it is
never allowed to see the truth.

## How it could be tried
- Strategy `llm_critic`. `discovery/critic.py` builds a compact JSON prompt and calls a Claude model
  through the Anthropic API at temperature 0. Responses are cached by a hash of the prompt, so bench
  runs can be repeated exactly.
- Edits come in a fixed schema:
  - redirect a flow;
  - merge an outflow and a link into a paced move;
  - add a hidden stock between A and B;
  - add `uses`;
  - add an effect of C on a flow;
  - change a stock's inflow form.
- `discovery/edits.py` applies an edit (shared with structure search's edit moves where possible) and
  refits the numbers with the column set fixed. At most 3 rounds.
- Leakage and honesty: the bench reports the critic with real names and with names scrambled (the
  gap is what names contribute), and the I1 permutation check holds with the critic off.
- Mechanism test, offline with a recorded response: on the paced-move synthetic model, the critic's
  merge edit yields the move. Control: on a correct model, every proposed edit is rejected by the judge.
  Plus unit tests of the edit applier, one per edit type.
- Targets: sd-print-shop, sd-support-tiers, sd-moderation, sd-fishery, sd-housing long, sd-ev-fleet.

## Sources
Romera-Paredes et al. (2024) Nature 625:468-475 (FunSearch); Shojaee et al. (2025) LLM-SR, ICLR,
arXiv:2404.18400; Schoenberg et al. (2025) sd-ai, arXiv:2503.15580; literature report
[research process](literature/research-process.md) section 9 (search and verify).
