# The declared boundary in structures, blockwise, censored, earned_pieces, gap_prior, schedules

**Status:** built (commits be38330, 58b9634, df9faf5, 00d89da, 90f90e0, then 728efec: kinds read as the cases declare them, and f76591e: schedules' and gap_prior's main line chosen among guarded candidates); paired results below.

The approved change (the user, 2026-10-20; CLAUDE.md invariant 2, docs/LADDER.md "The boundary"):
outside flows are a modelling decision the case makes, not something discovery may invent. Each of
these six strategies now carries its own copy of `matrix/boundary.py` **at 723f72c** (HIDDEN_PRICE 0: a
hidden stock pays only for its numbers; CLAIM_PRICE 2 log T per outside flow when no boundary is
declared), as [declared-boundary.md](declared-boundary.md) "For copiers" asks, and uses it in its
**own search**, not only as a final guard. Nothing branches on the case type: the strategy reads
`run["boundary"]` / `run["boundary_declared"]` like eras and inputs.

| strategy | commit | where the boundary enters the search |
|---|---|---|
| `earned_pieces` | be38330 | rows refitted inside it (`rows.reselect(pieces_ok, exclude)`: an outside term only on an estimate side, measured inputs only on a measured side, other-unit columns only on an estimate side; reselect also runs when a boundary is declared); sources with no estimated outflow tied in the joint fit (`joint.decide(forced)`); every candidate guarded before the judge; `boundary.apply` on the answer |
| `blockwise` | be38330 | small models: the same hooks on its `earned*` copy. Large models (>= 15 stocks): each row's columns and inflow form restricted to declared sides (`inflow: none` where no estimate side; input columns only where measured; other-unit levels and their delayed copies only where estimated; read as links, another stock's level only where an estimated inflow is); every candidate (variants, refinements, the block join) guarded before the judge |
| `censored` | 58b9634 | the `earned*` copy as above; its row rewrites (floors, links, gaps, exact rows, caps) are offered only when every outside flow they write is on a declared side of a declared kind |
| `schedules` | df9faf5 | its censored copy guards the (shared) main line's answer and offers only rewrites inside the boundary; its beam search skips every step that leaves it (`search(inside=...)`) |
| `gap_prior` | 00d89da | its lna copy gets an `atoms` hook: an atom from outside into s (in, link, grow, gap) only where s may have an outside inflow of its kind, one from s to outside (out, drain) only where an outflow is; the gap swaps check the same (`d.atom_ok`); the main-line fallback is kept inside by the final guard |
| `structures` | 90f90e0 | `discover.term_filter` on the search's Problem: the term library, the rowwise starts, the base's inflow pieces, the multi-stock gap blocks, the chain terms and the chain fold hold outside terms only on declared sides (moves, chains between stocks and chain contents always allowed); its combined base is guarded before the comparison |

Every strategy ends with `boundary.apply(result, stocks, run, opts)`: declared, the guard (any flow
still outside becomes its best-priced alternative: dropped, a move, a link made a move, an inflow
reading the input, a gap inflow) and the anti-correlated pairs tried as moves; undeclared, the moves
and each outside flow priced as a boundary claim, listed in `r["boundary_claims"]`. The optional passes
stop after `MAX_FITS = 120` refits (deterministic), as in matrix.

Tests: `tests/test_boundary_six_copies.py` (each copy has HIDDEN_PRICE 0; each strategy keeps a split
`A -> outside` + `outside -> B` chain inside a declared boundary, finds the move `A -> B`, and lists
claims where none is declared). `tests/test_ladder_earned_pieces.py` now gives its runs the case's
announced boundary, as the ladder does (its 006 test failed when run without it: the true exit of A
became an unearned claim).

## Limits

- **Composites' copies of other strategies.** `structures` carries a copy of `combined` (and of lna,
  lna_stack, ...); `schedules` and `gap_prior` start from the shared main line (`identify.identify`,
  pinned). Those copies were not rewired; their answers are guarded (`final=False`) before use, so an
  invented boundary never survives, but their own searches still fit with every outside flow open.
- **Hidden stocks.** blockwise's stages and structures' chains are hidden stocks; `boundary.Fit`
  cannot refit them, so the guard just drops an offending flow there, and `pair_moves` and
  `price_claims` skip a model with hidden stocks (claims are then only listed).
- **Cost.** The guard has no refit budget of its own (one pass per violating flow); on the large
  undeclared models the passes are bounded by MAX_FITS. 316 and 317 were not part of this test.

## Two fixes found by the paired run

- **Kinds (728efec).** The reference `boundary.py` (matrix at 723f72c) calls any outside flow reading a
  measured input "measured" and keeps input columns off "estimate" sides. The cases declare "measured"
  only for an outside inflow whose rate reads *only* measured inputs, and "estimate" for every other
  outside flow (docs/LADDER.md, "Declared"). So in 208 (`H -> outside = demand`, valve
  `75 - 0.25 H + 0.8 demand`, both declared estimate) the true flows were read as outside the boundary,
  and all six lost 208 (equivalent -> fail on 2-4 variants each, jobs 38 vs 43). These copies now
  follow the case convention (`kind_of`, `may`, `inputs_ok`; test
  `test_kinds_are_read_as_the_cases_declare_them`). **matrix's reference has the same reading** and
  probably the same 208 loss; it was not changed here.
- **The start (f76591e).** schedules (through its censored copy) and gap_prior (lna's fallback)
  start from the pinned main line. Guarding only its chosen answer left nothing where that candidate
  fit only through an undeclared outside flow (055#6 counts-short: `outside -> B` only, dropped;
  schedules pass -> fail). Now every main-line candidate is guarded and judged again, the best one
  is the start.

## Results

Pool jobs (2026-10-20). Before: 38 (Tests cells) and 47 (kubernetes 300-305) at 7d2a370, where the six
are unchanged. After: 113 / 114 at 728efec (earned_pieces, blockwise, censored, structures) and
115 / 116 at f76591e (schedules, gap_prior). Tests cells: 10 cases x {counts-long, counts-short,
none-long, none-short} = 40 per strategy (seed 20261020 among the declared Tests cases all six have
stored results for: 055#6, 137, 195, 203, 208, where stored answers break the boundary, and 035, 044#8,
049#8, 112, 123). Pass counts pass + equivalent. Statuses from `uv run sdlab-ladder job ID --json`, paired by
(case, variant, strategy).

| strategy | Tests: pass before -> after | invented boundary | kubernetes 300-305 | invented boundary |
|---|---|---|---|---|
| earned_pieces | 20 -> 20 | 5 -> 0 | 27 -> 27 | 1 -> 0 |
| blockwise | 20 -> 20 (1 timeout -> 0) | 4 -> 0 | 27 -> 27 | 1 -> 0 |
| censored | 21 -> 22 (1 timeout -> 0) | 5 -> 0 | 27 -> 27 | 1 -> 0 |
| schedules | 22 -> 23 | 6 -> 0 | 27 -> 26 | 1 -> 0 |
| gap_prior | 19 -> 20 | 5 -> 0 | 25 -> 27 | 3 -> 0 |
| structures | 26 -> 27 | 1 -> 0 | 25 -> 26 | 3 -> 0 |

Flips. Gains: 055#6 none-long (censored), counts-long (gap_prior, structures); 195 counts-short
(schedules); 305 none-long (earned_pieces, blockwise, censored, gap_prior, structures), none-short
(gap_prior, structures), counts-long (gap_prior), counts-short (schedules, fail -> equivalent). All are
cells whose earlier answer had an invented boundary. Losses:

- **303 meas-long, all six (pass -> fail).** Same structure before and after; the numbers moved from
  7% low to 13.5% high (earned_pieces: 0.680 / 0.568 / 1.135 for 0.6 / 0.5 / 1). Before, the candidate
  carried invented `outside -> inflight` flows, and the errors-in-variables step (eiv.py) refitted and
  kept its instrumented numbers while dropping them. Now the candidate is already inside, eiv
  computes nearly the same instrumented numbers (0.559 / 0.466 / 0.933) but its judge rejects them
  (0.2093 vs 0.2124), so the measurement-noise bias stays. The loss is eiv's acceptance rule, not the
  boundary search; not changed here.
- **305 counts-long, schedules (pass -> fail).** The beam's joint refit puts the declared give-up
  outflow at 0 and `retries -> queue` at 0.949 (true 0.6, se 0.075): the k305 problem (a stock that
  empties every step; k305-r1.md) in schedules' own refit. Keeping the declared side from being
  dropped (tried) leaves the flow at ~0 and does not save the cell.

Not tested here: 316-317 (the largest kubernetes models, where matrix's boundary passes timed out).
