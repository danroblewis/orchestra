# 308 (k8s-hpa): structures, the noise-free and counts variants

**Status:** 3 of 4 pass; counts-short fails on a data limit. 2026-10-21, agent k8s-308-structures (structures lock held
for the work, released after the commit).

## Before (store, code dfd94cb)

`uv run sdlab-ladder show 308 --strategy structures --variant V`: all four FAIL. In every variant the two HPA flows
(`outside -> ready`, `ready -> outside`, whole flows) were fitted as linear drifts (e.g. none-short
`outside -> ready = 0.00292 inflight`, `ready -> outside = 0.00248 queue + 0.0429 ready`; amount errors 98-1974%).
Everything else was right on none-short, none-long and counts-long. No strategy passed any variant of 308 (store, 174 cells).

## Diagnosis (rule 4b)

1. **HPA flows: method fault.** `ready` is a whole number at every step, and its changes are whole numbers.
   In-process check (scratchpad dump.py): on all four variants the truth's rule on the measured levels at step t reproduces
   every step's change of ready exactly (counts too: the controller flows are exact, and cpu is measured), so the form and its
   numbers are identifiable from the data. structures' families have no form that can say "jump to a target", only rates.
2. **counts-short retries split: data limit.** `uv run sdlab-ladder analyse 308 --variant counts-short`: DATA-LIMITED,
   p 0.094; retries -> queue bound SE 0.13 (allowed 0.06, p 0.36), retries -> outside bound SE 0.115 (allowed 0.0465, p 0.31).
   Found errors 0.10-0.13 and 0.16-0.19: about one bound SE. Not fixed (no unbiased method passes it reliably).
3. **counts-short on node2 (job 248): a spurious move `inflight -> queue = 0.0908 traffic`** beside the right
   `queue -> inflight` (which became 0.666 queue, whole flow error 11%). The Mac's run of the same commit does not have it
   (machine numerics change the base's choice). Probe (scratchpad t4.py): dropping it and refitting with combined's refit lowers
   combined's BIC by 0.14 and puts queue -> inflight right (0.603), but the cell still fails on the retries split (point 2).
   Not fixed in this round: proposed below (flow-earn).

## Fix kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| controller-form | a stock whose levels and changes are whole numbers gets a discrete target-tracking rule as its outside flows when one reproduces every step exactly: target T = ceil(x / a) for any other measured stock or input x (a link, may cross units), clamped by a ceiling H (inflow) or floor L (outflow) only when the data need one (the extreme level reached); inflow the whole gap `max(0, min(H, T) - s)` or one unit `1 * (s < min(H, T))`, outflow likewise; each step is a whole-number constraint on T, so a's consistent values are one interval (a >= x/m for T <= m, a < x/(m-1) for T >= m); preference: no clamp, whole gap before one unit, narrowest interval among drivers; a written with fewest significant digits in its interval. Only when the stock has no move with another stock and the declared boundary has the side. | 288841e | `structures/controller.py`, called last in `__init__.identify` (after capmin.restore) | copy `controller.py` (no dependencies beyond numpy) into the package and wrap the final identify: `controller.apply(result, stocks, run, opts)`. It only touches whole-number stocks whose every change it reproduces exactly, so it is inert elsewhere. |

Found on 308 (in-process, same commit): none-short/none-long `outside -> ready = max(0, min(16, ceil(cpu / 192.5)) - ready)`,
`ready -> outside = 1 * (ready > ceil(cpu / 157.5))` (the floor 3 is not needed by those runs); counts-long adds
`max(3, ...)` (ready sat at 3 there); counts-short a = 192 and 157.6 (inside their intervals). Unit test:
`tests/test_structures_controller.py`.

## After (pool job 248, commit 288841e, node2)

`uv run sdlab-ladder submit --strategies structures --cases 308 --variants none-short,none-long,counts-short,counts-long --priority 400`,
`uv run sdlab-ladder job 248 --wait`: none-short PASS, none-long PASS (211 s), counts-long PASS (116 s), counts-short FAIL
(retries split, data-limited; plus the node2-only spurious move of point 3).

## Proposed, not made

| type | mechanism | how another strategy adopts it |
|---|---|---|
| flow-earn | after the fit, each flow that is not a declared boundary flow, an input flow or an expression is dropped in turn, the rest refitted (combined's refit.py) and kept dropped when combined's BIC (judge.score) is lower; repeat. Declared outside flows must be exempt: on counts-short the judge would also drop `retries -> outside` (-3.0 BIC). | a post-pass over the final flows with the strategy's own judge |
