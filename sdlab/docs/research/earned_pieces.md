# Earned pieces: an outside inflow changes only where the data earns it

**Status:** done (ladder; benchmark v2.1; 100 generated models). Strategy `earned_pieces`
(`sdlab/discovery/strategies/earned_pieces/`), tests `tests/test_ladder_earned_pieces.py` (6, pass).
Numbers below are from commit `51a7422` unless a row says otherwise.
**Verdict:** adopt candidate. It passes every counting-noise short variant of 002-020 that `matrix` failed
(and 002 long), with no ladder cell lost on those cases, and it is the first strategy here to pass the
whole of 002-006, 012-014, 019 and 020 in all four variants. On the examples it gains +6.2 / +6.1 points
(skill@20 / @100, Wilcoxon p = 0.043 at @20), with 15 of 62 runs meeting the goal against 12. A handful of
examples still lose (listed below).

## The question
On short counting-noise runs `matrix` fails the simplest chains. `uv run sdlab-ladder show 004-chain-3
--strategy matrix --variant counts-short`: C (no outside inflow) gets 9 chance inflow pieces and a
spurious link from B, and its drain comes out 0.171 against 0.1. A stock that does have a constant
inflow gets chance pieces too (002 long: 30 pieces, drain 0.21 against 0.1). What do `change_price` and
`held_out` do that fixes some of these, and what fixes all of them on principle?

## What change_price and held_out fix, and why each still fails
Per-cell statuses and piece counts below are from the result store (`api.result`), counts variants.

- **change_price** gates pieces at the first pass with the textbook price (2 x log n x the long-run
  variance), but **only for stocks without an outside inflow** (a constant does not beat none beside
  the levels). That fixes the internal stocks: 004, 005, 014 and 019 counts-short pass. It does nothing
  for a stock that does have a constant inflow, whose chance pieces bias its drain through within-piece
  demeaning and through pieces that follow the level's own wanderings: 002 long (A: 30 pieces, drain
  0.21, inflow 42), 006, 012, 013 short (15, 14 and 31 pieces) still fail. 006 also needs the exit (below).
- **held_out** judges candidates by blocked cross-validation. A held-out block cannot be forecast by
  pieces, so it nearly always picks a *constant-inflow* candidate, which removes chance pieces
  everywhere: 002, 004, 013 short, 014 pass. It fails where the inflow really changes (020 counts:
  the constant candidate has no step) and where the constant candidate has another error the judge
  cannot see: 006 short (the matrix's conservation removes A's real exit), 012 short (it picks a
  changing candidate with 20 pieces and a spurious exit), 005 long and 013 long.

So there are three separate faults: (1) chance pieces in stocks with no inflow, (2) chance pieces in
stocks with a constant inflow, which bias the drain, and (3) conservation that overrides a short noisy
run's evidence for an exit (the matrix ties a drain to its receivers unless the source's row objects by
more than log T beyond BIC, using only the source's own uncertainty).

## What it does
Every main-line candidate (`identify.VARIANTS`) is fitted by `matrix.identify_one` with its cheap
pieces, then rebuilt in two steps before the usual behaviour judge chooses among the candidates.

1. **Rows chosen again, pieces only where earned** (`rows.py`). For each row, the matrix's row is
   one candidate. If it has pieces, its levels are chosen again by backward elimination *beside* the
   pieces (so that a change in the inflow cannot hide in a level that happens to follow it), then the
   pieces are dropped (no inflow, or a constant). That row replaces the matrix's only if
   - its residuals are white (Ljung-Box up to lag ceil(sqrt(T)), level 1%): a constant inflow leaves
     nothing slow behind for pieces to explain, and
   - its BIC is lower with every change priced as a value and a place (2 parameters).
   The whiteness test is what keeps real changes: an intake changing every 30 steps (sd-pipeline)
   leaves a slow pattern (Q at lag 45 is 95, p = 1e-5) even though no single change pays a textbook
   price; chance pieces leave white residuals behind (all ladder rows with a constant inflow have p > 0.1).
   A row without pieces is replaced by levels chosen afresh when that has a lower BIC (this fixes
   forward-stepwise rows that took the wrong levels, e.g. 019's per-era move). BIC is floored at the
   data's rounding (levels rounded to 4 decimals in the noise-free variants: below that the residual
   says nothing, and backward elimination otherwise keeps every level on rounding structure).
2. **Conservation decided by all rows at once** (`joint.py`). All rows' numbers are fitted together by
   weighted least squares with optional ties: a tied source's own number is minus what its receivers
   gain from it (receivers: same-unit rows whose total reading of the source is positive; a negative
   reading is a link). Each source is tied or freed greedily by BIC on the **counting likelihood**:
   residuals Gaussian with variance phi x gross throughput (|inflow| + sum |number| x level), phi
   shared by a unit's rows. So the receivers' rows count as evidence for the move, and the residual
   variance counts as evidence for the gross throughput (an exit beside a move adds throughput).
   For a source whose inflow is in pieces, its own drain is not separable from the changes, so when
   tied it is measured by the receivers alone, and its pieces are found again with the drain held.
   Every tie decision is made with changing rows' pieces re-found at the textbook price (cheap pieces
   could stand in for a drain, or co-adapt with a biased one); the reported model then uses the cheap
   pieces (a free row keeps the matrix's, a tied row gets those found with the drain held).

The model is then read off by `matrix.finish` with its own conservation switched off (every stock passed
as final to it), so the ties above are the only conservation applied.

Options (`opts` or the `SDLAB_EARNED` JSON environment variable, for ablations): `joint` (False: step 2
off), `reselect` (False: step 1 off), `counting` (False: plain stacked least squares), `scale`
("row": phi per row), `levels` ("afresh", "both"), `alpha`, `change_params`.

## Ladder
`uv run sdlab-ladder status --strategies matrix,change_price,held_out,earned_pieces` (run at commit
`51a7422`, 2026-10-19; the board marks every row stale because shared code changed after the run, so it
mixes versions). Cells: none-short, none-long, counts-short, counts-long. In "f/p": found flows and inflow
pieces, counts variants (from the store).

| case | matrix | change_price | held_out | earned_pieces | earned_pieces counts-short / -long (truth) |
|---|---|---|---|---|---|
| 002-inflow-outflow | PPPF | PPPF | PPPP | **PPPP** | 2f/1p, 2f/1p (2f/1p) |
| 004-chain-3 | PPFP | PPPP | PPPP | **PPPP** | 4f/1p, 4f/1p (4f/1p) |
| 005-chain-4 | PPFP | PPPP | PPPF | **PPPP** | 5f/1p, 5f/1p |
| 006-chain-exit-middle | PPFF | PPFP | PPFP | **PPPP** | 4f/1p, 4f/1p |
| 012-rework | PPFP | PPFP | PPFP | **PPPP** | 4f/1p, 4f/1p |
| 013-merge | PPFF | PPFF | PPPF | **PPPP** | 5f/2p, 5f/2p |
| 014-split | PPFF | PPPP | PPPP | **PPPP** | 5f/1p, 5f/1p |
| 019-announced-era | FPFP | FPPP | FPPP | **PPPP** | 3f/1p, 3f/1p |
| 020-unannounced-step | PPFP | FPPP | PFFF | **PPPP** | 3f/8p, 3f/27p (real steps kept) |
| 007 / 008 / 009 / 010 / 016 | EEFF, EEFF, EEEF, EEFF, EEFF | | | EEEE each | |
| 011-goal-gap | EEFE | EEFE | EEFE | EEEF | counts-long 0.237 vs 0.2 on the gap: 3.5 SE off in plain OLS too |

Whole ladder (720 cells, same command): earned_pieces 469 pass, 179 equivalent, 72 fail; matrix 345 /
116 / 259; held_out 436 / 169 / 115. Against matrix cell by cell (`api.summary`): 191 cells better, 4
worse: 011 counts-long (E -> F, above), 042-random-two-chains-of-two#5 counts-short (a slow 0.04 drain
lost in 300 steps), 043-random-three-chains-of-two#6 and #8 none-short (noise-free: see open ideas).
027-stepping-inflow-drain counts (PPFF) is not fixed: a single stock with a stepping inflow and no
receivers, where the cheap pieces spiral the drain up (0.36 against 0.1) and nothing ties it.

What fixed what (ablations, `abl.py` over the 26-case ladder of the time, counts of pass/equivalent):
- the honest form price alone (`form_change_params` 2 in the matrix): 45 / 20, fixes 002, 004, 005, 012,
  013, 014, 020 counts-short, but costs the examples -16.5 points (it removes sd-pipeline's real changes);
- + the joint conservation: 46 / 23, fixes 006 counts-short (the exit is kept: A's row says 0.45 +- 0.05,
  B's row says 0.29 +- 0.04, and tied the rows fit clearly worse);
- + rows chosen again: 48 / 23, fixes 019 counts-short (B's per-era move);
- the whiteness test in place of the honest form price: the same ladder, and the examples recover.

## Bench (examples, v2.1 baseline: 29.6% / 29.3% / 12 of 62)
`OMP_NUM_THREADS=1 ... uv run python tests/bench/evaluate.py --strategy earned_pieces --baseline v2.1
--jobs 3 --no-candidates`. All rows are this strategy at the stated stage.

| version | commit | skill@20 | skill@100 | goal | Wilcoxon @20 / @100 |
|---|---|---|---|---|---|
| v1: honest form price + joint + rows | uncommitted (before `8bcc032`) | 13.6% (-16.1) | 8.5% (-20.8) | 9 | 0.055 / 0.022 (worse) |
| ablation: honest form price only | uncommitted (before `8bcc032`) | 13.1% (-16.5) | 5.3% (-24.0) | 9 | |
| v2: whiteness test instead | `8bcc032` | 30.8% (+1.1) | 33.4% (+4.0) | 13 | 0.22 / 0.24 |
| v5: no forced ties, counting likelihood | `86d0394` (`counting` true) | 34.0% (+4.4) | 32.7% (+3.4) | 15 | 0.18 / 0.31 |
| v6: ties decided at the textbook price | `559c670` | 32.8% (+3.1) | 27.5% (-1.9) | 15 | 0.32 / 0.65 |
| **v7: receivers = rows that gain; rounding floor** | **`51a7422`** | **35.8% (+6.2)** | **35.4% (+6.1)** | **15** | **0.043 / 0.11** |
| v7 with phi per row (`scale` "row") | `51a7422` | 33.9% (+4.3) | 31.1% (+1.8) | 13 | 0.16 / 0.41 |

v7: 36 better, 19 worse, 7 same at skill@20 (sign test p = 0.03); fresh runs 34.9% / 36.1%. Big gains:
sd-pipeline default (40 -> 99.6%: the inbox is tied to what working receives), sd-bakery default,
sd-cloud-credits default, sd-eras long, sd-hospital long, sd-learning-curve default, sd-webshop-stock.
Losses beyond 2 points at skill@20 include sd-manufacturing default (65 -> below -100: the counting
likelihood ties inspection, whose real drain goes to an unmeasured stock, because the free row claims
twice the throughput its residuals show), sd-learning-curve long, sd-fishery long, sd-population,
sd-restaurant and several runs that stay below -100% either way. The bench moves by 1-5 points between
principled variants (a few chaotic runs swing by 100+ points), so only v7's paired tests are evidence.

## Bench (generated models)
`... evaluate.py --strategy earned_pieces --generated 100 --jobs 3 --no-candidates` at `51a7422`, and
`matrix` the same way on the same 100 dev models (2026-10-19); paired with
`tests/bench/compare.py <matrix run> <earned_pieces run>`.

| | skill@20 | skill@100 | goal | parts |
|---|---|---|---|---|
| matrix | -52.4% | -48.1% | 7 of 200 | 71.9% |
| earned_pieces | **-41.2% (+11.2)** | **-43.9% (+4.2)** | **12 of 200** | 80.0% |

skill@20: 72 better, 36 worse, 92 same (sign p = 0.0007, Wilcoxon p = 0.009); skill@100: 61 / 47 (p = 0.33);
fresh runs the same (+11.6 / +4.4). Largest motif gains at skill@20: rework +23.6, inflow_season +14.7,
floor +7.8, chain +7.0 (these deltas are against the run evaluate.py compared with, effect_hats gen v3,
not matrix); losses: goal_gap -10.1, reinforcing -7.6. One run raised (gen1-dev-00001 default: SVD did
not converge in the joint fit) and counts as an error in these numbers; `1a086e6` falls back to the
matrix's candidate there (that run now gives skill@20 19.8%); the generated bench was not re-run after it.

## Lessons
- Chance pieces and weak real changes cannot be told apart change by change: in the sd-pipeline shape
  each real change gains about 6 in -2 log L, less than any honest price, while chance pieces gain about
  as much. They differ collectively: a constant inflow leaves autocorrelated residuals where the
  inflow really changes. A whiteness test asks the collective question with one test per row.
- A drain shared with a receiver is measured best by the receiver: its row has no inflow to confound
  the drain with. Pieces bias the source's own estimate (both within-piece demeaning and pieces that
  follow the level), so a tie for a changing source must not be judged with pieces found beside its
  own drain, nor with cheap pieces found beside the tied one (they then absorb a real drain).
- The counting likelihood (variance = gross throughput) is real evidence on count data, and it beat
  plain stacked least squares and a per-row scale on the examples, but it punishes rows that claim too
  much throughput, which can make it prefer removing a real flow (sd-manufacturing).

## Proposed shared changes (not made; this strategy carries local versions)
- `matrix.conserve`: test a tie with both rows' uncertainty and without the extra log T, and do not let
  a negative reading count as a receiver (local: `joint.py`).
- `matrix.fit_row`'s final form choice: replace "pieces if they beat a constant at 1 parameter a change"
  by "a constant (or none) unless its residuals are not white" (local: `rows.py`).
- `regression.bic` / `stepwise`: floor the rss at the data's rounding (`rows.rss_floor`); noise-free
  variants otherwise choose levels on rounding structure.
- `finish` takes a flag to skip conservation rather than the trick of passing every stock as final.

## Measured inputs (2026-10-19, commit 89adae4)

**Bug:** the matrix is called with `keep_fit`/`keep_rows`, and without `input_columns` it gives such a
caller no input columns: the inputs were dropped and the rows explained them with pieces (062
counts-long: 6.5 in pieces and a drain of 0.062 against 2 x pump and 0.08). The judge also stepped
candidates without inputs.
**Fix:** `input_columns: True`; a row's numbers on inputs are read back by the matrix's column names;
re-selected rows may read the inputs (`rows.reselect`, `inputs`); the joint fit refits them as free
numbers (an input is never a source to tie); a local judge with inputs chooses among the candidates.

Before -> after on the cases with measured inputs (variants in the order shown; skill@20 on the run
it saw, none-long):

| case | variants | before | after | skill@20 none-long |
|---|---|---|---|---|
| 062-tank-fed-by-measured-pump | counts-long / counts-short / none-long / none-short | F F F F | P P P P | 0.83 -> 1.00 |
| 105-canonical-inventory-supply-line | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 1.00 -> 1.00 |
| 106-canonical-workforce | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 0.99 -> 0.96 |
| 110-canonical-world3-pollution | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 0.00 -> 0.97 |
| phys-coupled-tanks | meas-long / meas-short / none-long / none-short | F F F F | F P P F | 0.96 -> 0.99 |
| phys-draining-tank | meas-long / meas-short / none-long / none-short | F F F F | P P P P | 1.00 -> 1.00 |
| phys-mass-spring-damper | meas-long / meas-short / none-long / none-short | F F F F | F F P P | 1.00 -> 1.00 |
| phys-newton-cooling | meas-long / meas-short / none-long / none-short | F F F F | P P P P | 1.00 -> 1.00 |
| phys-thermostat | meas-long / meas-short / none-long / none-short | F F F F | F F F F | 0.98 -> 1.00 |

105, 106 and 110 (canonical models whose input drives hidden delay stocks) fail before and after, as
for matrix, lna and combined. phys-thermostat fails its structure for every strategy (the closed loop
all but hides the outside's coupling; its own reference fails), though its skill rose.

**Cells without inputs:** every (case, variant) without a measured input was run before (parent of
`89adae4`) and after, each from an exported copy of the package that differs only in this strategy's
files, single-threaded: 1074 of 1074 cells gave byte-identical flows and the same status, the 62 realistic sd-* cells among them; 3 of them (realistic sd-* counts-long) hit the ladder's per-case timeout under load in one run or both and were re-run without a timeout, before and after: identical too
(script and outputs: the agent's scratchpad `inp/cells.py`, `cmp.py`, `old.jsonl`, `new.jsonl`).

## Open ideas
- 027 (no receiver to tie to): a drain for a changing row without demeaning bias, e.g. the bias
  correction from inflow-attribution, or recession steps.
- 043#6/#8 none-short: noise-free cases still fail on rounding structure; the floor uses the data's
  quantum, but the engine's sub-step arithmetic adds structure above it.
- A Hausman-style check (the constant-inflow drain against the pieces drain) as a second admissibility
  test beside whiteness.
- The judge still prefers candidates whose pieces replay the run (sd-population's 151 pieces); an honest
  judge or a complexity budget would stop it.
- sd-manufacturing: let the counting likelihood see unmeasured receivers (an exit to outside is a flow
  too), or tie only when the tied row fits within its own noise.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (own copy of matrix/boundary.py, wired into this
strategy's search): see [declared-boundary-six.md](declared-boundary-six.md) for the hooks and the paired results.
