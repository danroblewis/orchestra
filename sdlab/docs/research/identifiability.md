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
- [Causal inference](literature/causal-inference.md), sections 1.4-1.6 and 5 (idea 5): a causal identifiability report. Unroll the chosen structure in time, with hidden stocks and shared unannounced inflows as latent nodes, and decide per link (backdoor; front door through measured flows; instruments from eras and injections) whether its effect is identified from the data, identified only through an instrument, or not identifiable ("an injection into A would identify it"). Causal-effect identifiability is not parameter identifiability: a hidden stock leaves the total effect identified even when its internal numbers are not. The do-calculus is complete for this question (Huang, Valtorta 2006, UAI; Shpitser, Pearl 2006, AAAI). Feeds [probe-design](probe-design.md).
