# Invariance across eras and probes: which rows an era changed, and which predictors are real

**Status:** idea (not started)

## Why
Two uses of the same causal principle: a true mechanism stays the same across environments, and a
spurious one does not (invariant causal prediction, Peters, Bühlmann and Meinshausen 2016).

1. **Era targets.** An announced era says *when* something changed, not *what*. The "numbers per
   era" variant gives every level a row uses (and the row's own level) its own number in every
   configuration (`matrix.py`, `split_eras`). That multiplies the parameters in rows the era never
   touched, and lets noise in on short runs. Joint causal inference (Mooij, Magliacane and Claassen
   2020) and CD-NOD (Huang et al. 2020) treat era indicators as context variables and *find their
   targets*. The rows whose equation changes at the era are the ones that fail invariance.
   Conservation pairs a failing source row with a failing receiving row, which names the changed
   flow.
2. **Spurious predictors.** A link chosen because two stocks share an unannounced inflow fits the
   calm data but breaks when probes shift the predictor's distribution. Injections never change an
   equation, so they are valid environments for every row. ICP's answer is the intersection of the
   predictor sets that stay invariant. When the data cannot decide, it returns an empty set, which
   is an honest "not supported by the data" signal for [bench-instrumentation](bench-instrumentation.md).

Eras are not valid ICP environments for the rows they change: ICP needs the target row's own
mechanism to be invariant. Use eras for (1), and injections, plus eras on rows found unchanged, for
(2).

## How it could be tried
- (1) Strategy `era_targets`.
  - For each row and each announced era with at least 30 steps on each side, test the row's
    coefficients for change: a Chow test, weighted by counting variance, of shared versus per-era
    numbers.
  - Holm-correct across rows. Split numbers per era only in rows that fail, and only for the levels
    whose coefficients changed.
  - Pair failing rows by conservation (opposite-signed change in the same level's coefficient) to
    name the changed flow, and report it.
  - Mechanism test: a chain a -> b -> c with an outside inflow into a; an announced era at t = 500
    changes only b -> c from 0.2 to 0.4; 1000 steps, counting noise.
    - Pass: rows b and c flagged and a not, in at least 9 of 10 seeds; the b -> c move named;
      coefficient error and skill@100 better than the split-everything variant.
    - Control: an era announced with no change flags nothing in at least 95% of seeds.
  - Bench: the era examples (sd-eras, sd-ci, sd-restaurant, sd-university, sd-support-tiers,
    sd-sawmill, sd-learning-curve), against the main line.
- (2) Strategy `invariant_links` (needs `--probes K`; see [injection-response-judge](injection-response-judge.md)).
  - For each row, take the candidate predictor sets from the variants' chosen sets and their subsets
    of size at most one less.
  - For each set, fit it on the pooled data. Test equality of the residual mean and variance between
    windows just after probes and calm windows (Levene and t, or a permutation test).
  - Keep the intersection of accepted sets. Drop from the chosen model any link outside it, refit,
    and enter the result as a candidate.
  - Mechanism test: b and c share an unannounced inflow (pieces); the truth has no c -> b link; the
    main line picks a spurious c -> b link. With 10 probes into c, the intersection excludes c, and
    the refitted model's skill@20 on a fresh probed run beats the main line's.
  - Control: the true links stay in the intersection in at least 95% of seeds.

## Sources
- Literature report [causal inference](literature/causal-inference.md), sections 3.1, 3.3 and 5 (idea 3).
- Peters, Bühlmann, Meinshausen (2016). Causal inference by using invariant prediction. JRSS B 78(5):947-1012. doi:10.1111/rssb.12167
- Pfister, Bühlmann, Peters (2019). Invariant causal prediction for sequential data. JASA 114(527):1264-1276. doi:10.1080/01621459.2018.1491403
- Mooij, Magliacane, Claassen (2020). Joint causal inference from multiple contexts. JMLR 21(99):1-108.
- Huang et al. (2020). Causal discovery from heterogeneous/nonstationary data. JMLR 21(89):1-53.
- Pfister, Bauer, Peters (2019). Learning stable and predictive structures in kinetic systems. PNAS 116(51):25405-25411. doi:10.1073/pnas.1905688116 (invariance across experiments for kinetic models)
- Christiansen, Peters (2020). Switching regression models and causal inference in the presence of discrete latent variables. JMLR 21(41):1-46 (for unannounced regimes; see [latent-eras](latent-eras.md)).
