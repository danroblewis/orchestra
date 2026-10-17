# Identifiability: which structures the data cannot tell apart

**Status:** idea (not started)

## Why
Some structures predict identical data (births as a link vs a move when averages fit both; a hidden stock's delay vs a slow drain). Chasing them wastes effort; reporting the equivalence class is honest.

## How it could be tried
Structural identifiability of the linear-in-levels model with conservation; empirical: fit pairs of alternative structures to synthetic data and measure distinguishability; discovery returns alternatives with their evidence.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook I5 (self-consistency: rediscover from data simulated by the found model) and M11 (equivalence rewrites with a declared tie-break; boundary reduction), plus I1's failure class "not supported by the data".
- Godfrey, Chapman (1990). Identifiability and indistinguishability of linear compartmental models. Math. Comput. Simul. 32(3):273-295.
- Davidson et al. (2017). DISTING. Comput. Methods Programs Biomed. 143:129-135.
- Szederkényi, Banga, Alonso (2011). BMC Syst. Biol. 5:177 (a unique topology often cannot be determined even with every variable measured).
- Raue et al. (2009). Profile likelihood. Bioinformatics 25(15):1923-1929.
- Transtrum, Qiu (2014). Model reduction by manifold boundaries. PRL 113:098701.
- Meshkat, Sullivant, Eisenberg (2015). Bull. Math. Biol. 77(8):1620-1651.
