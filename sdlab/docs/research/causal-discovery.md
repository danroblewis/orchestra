# Causal discovery on time series (PCMCI+, Granger)

**Status:** idea (not started)

## Why
As a reference or a prior for which stocks affect which.

## How it could be tried
Run PCMCI+ (note Tigramite is GPL-3.0: use as an offline baseline only) and Granger tests; grade the implied graphs.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook section 6: in closed-loop, strongly forced systems Granger tests, transfer entropy and convergent cross mapping add little to the regression or point the wrong way (McCracken, Weigel 2014, Phys. Rev. E 90:062903; Sugihara et al. 2012, Science 338:496-500). Use only as a sanity baseline.
- [Causal inference](literature/causal-inference.md), section 2.2. Under causal sufficiency, no instantaneous effects and one graph over time, our row regression already *is* time-series causal discovery (Peters, Janzing, Schölkopf 2017; Eichler 2012; Eichler, Didelez 2010, Lifetime Data Anal. 16:3-32). PCMCI (Runge et al. 2019, Sci. Adv. 5:eaau4996), tsFCI (Entner, Hoyer 2010), SVAR-FCI and VAR-LiNGAM (Hyvärinen et al. 2010, JMLR 11:1709-1731) are graph-only, need faithfulness (which balancing loops break: Andersen 2013, Phil. Sci. 80:672-683), and ignore conservation. Keep them as an offline baseline. The one possible use is a latent-variable method (LPCMCI, tsFCI) flagging confounded pairs as a hint of a hidden stock or a shared unannounced inflow. The causal ideas worth running use injections and eras instead: [injection-response-judge](injection-response-judge.md), [injection-instruments](injection-instruments.md), [invariant-rows](invariant-rows.md), [probe-design](probe-design.md).
