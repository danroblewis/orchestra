# loop_transit: a hidden stage on a closed loop

**Status:** done for 156 (whole-ladder results below); the hard cases (sd-ev-fleet, sd-recycling) are unchanged  
**Strategy:** `loop_transit` (`sdlab/sdlab/discovery/strategies/loop_transit/`), a copy of
`realistic_hats` at 06b0062 (every module, `transit/` included); code commit c3161de  
**Verdict:** keep as a specialist (156 three of four, nothing lost against realistic_hats; see
Results). The fixes are inside the pair fit and do not depend on 156's shape: they apply to any
hidden stage beside announced injections or a return move.

## Why realistic_hats and hidden_transit failed 156

156 is a fleet of vans on a loop: road `A -> H` 0.2 A, `H -> B` 0.5 H (H not measured), `B -> A`
0.3 B, with four announced additions of 40 to B. Every leader wrote a shortcut `A -> B` 0.2 A plus a
link `outside -> B` reading A and a drain of B (realistic_hats, hidden_transit), or two spurious
delay chains (structures). The data identify the loop: noise-free, each row is exact with H in it.

The diagnosis, with `ht_trace` on realistic_hats' transit (06b0062):

1. **Injections were not in the pair's rows.** On none-long the transit pair `A -> H -> B` fitted
   delay 1.96 and a stray constant into B and was 0.7 short of its BIC margin (gain 32.5, margin
   33.2): each injection was a jump of 40 in B that the pair's filter, without it, could not explain,
   so the noise-free fit was not exact. With the injections added at the start of their step
   (matrix.injected's convention), the gain is 73,706 and the fit exact.
2. **The return move's noise is shared.** On counts the delay came out 1.63-1.69 for 2 on the long
   run. The move `B -> A` (about 10-15 a step) is one Poisson count that leaves B and enters A;
   the pair's filter took A's and B's errors as independent. With a joint 2 x 2 innovation
   (covariance minus the move's variance), and the move's rate refitted with the pair instead of
   held at the main line's (read on rows missing H), counts-long gives delay 1.97, move 0.305.
3. **The main line splits the return move** into the move plus a link `outside -> A` reading B and
   a drain of B at the same rate (a move is a link plus a drain). That echo is now folded into the
   move when the pair's BIC (with the kept flows' numbers counted) prefers it, and B may have no
   drain of its own (kb = 0) when that is better by BIC.

## Results

156 (`uv run sdlab-ladder run --strategies loop_transit --cases 156 ...`, c3161de's code):

| variant | realistic_hats (06b0062) | loop_transit |
|---|---|---|
| none-short | fail | **pass** (delay 2.000, kin 0.2000, move 0.3000) |
| none-long | fail | **pass** (exact) |
| counts-short | fail | fail: delay 1.78 for 2 (11%, tolerance 10%) |
| counts-long | fail | **pass** (delay 1.97, kin 0.202, move 0.305) |

counts-short looks data-limited, not a method fault: on the case's fresh seed (`data.load(...,
fresh=True)`) the same code gives delay 2.04; on the long run the two seeds give 1.97 and 2.02. The
hidden-oracle gives no standard error for this truth, so the scorer's tolerance is the fixed 10%.

Whole ladder (`uv run sdlab-ladder sync --strategies loop_transit --jobs 2 --timeout 300`,
single-threaded): 1318 items in 4439 s (552 pass, 204 equivalent, 510 fail, 52 differs; no errors or timeouts). Paired
with realistic_hats' latest results on the 1218 cells both have (`scratchpad/pair.py loop_transit realistic_hats`):
loop_transit 555 pass / 203 equivalent / 460 fail, realistic_hats 552 / 203 / 463; **4 better, 1 worse**.

- Better: 156 none-short, none-long and counts-long (fail → pass, the target), and 047-random-goal-gap#2
  none-long (fail → equivalent).
- Worse: 045-random-link#7 none-long (equivalent → fail). On noise-free data the pair search accepts a
  hidden stage `B -> B~A -> A` with a stage rate of 0.0002 (found 13 parts against the truth's 8; skill
  still 99.9%). A minimum stage size (the stage's flow as a share of the move it replaces), or the noise-free
  BIC floor at the data's rounding, would stop it; not done.
- realistic_hats' rows are its stored ones (06b0062), so 2 of the 1220 cells it has and loop_transit's 144
  extra cells (cases added since) are not paired.

Hard cases: unchanged against realistic_hats (both still fail every variant, same models). Neither is
blocked by the loop any more but by mechanisms other agents own:
- **sd-recycling**: the stage `bales -> rail -> shelves` sits after an affine release with a co-flow
  (`-40 + 0.2 bales; uses 0.05 wagons`: mechanisms H and 161, cases 158 and 161). On counts-short
  the pair is found (delay 14.5 for 6, with a share of bales' loss to outside standing in for the
  intercept); on counts-long the main line's rates come per announced era ("varies: 41 segments"),
  and the pair search only takes proportional rates, so no pair is tried.
- **sd-ev-fleet**: the main line's model (gaps read as links, co-flows with energy missed, 849
  inflow pieces) has no proportional loss of road beside a receiving queue for a pair to start from.

## What remains

- Pairs on rates given per era (`byTime`): the pair fit would need a kA and kin per era (sd-recycling
  counts-long, sd-eras-like runs).
- A stage after an affine or co-flowed move (158, 161).
