# A declarative library of SD processes

**Status:** idea (not started)

## Why
Rate forms are hard-coded across `matrix.py` and `flows.py`; co-flows and effects have no path in.
Inductive process modelling, reaction-network inference and SD practice all write a model as a sum of
processes drawn from a library of generic templates with typed slots and constraints, so a new form is
a library entry rather than a code path. A consolidation step after the co-flow, effect, delay and floor
experiments, not a bench mechanism (playbook, consolidation).

## How it could be tried
- Processes: move, inflow, outflow, link, co-flow (`uses`), delay object (T, n), gap, effect multiplier,
  floor/cap; each declares its regression columns, constraints (units, `final`, groups, signs), how it
  is read into SD Lab flows, and its price.
- The stepwise search, the diagnose-and-expand loop and the readers iterate over the library.
- Success: identical bench numbers, fewer special cases; adding a form touches one entry.

## Sources
Bridewell, Langley, Todorovski and Džeroski (2008) Machine Learning 71:1-32,
doi:10.1007/s10994-007-5042-6; Langley and Arvay (2015) AAAI 29(1), doi:10.1609/aaai.v29i1.9219;
Brence, Todorovski and Džeroski (2021) Knowledge-Based Systems 224:107077; Hoffmann, Fröhner and Noé
(2019) J. Chem. Phys. 150:025101; Clark et al. (2008) WRR 44(12):W00B02.
