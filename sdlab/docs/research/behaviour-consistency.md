# Behaviour-consistency gate against runaway models

**Status:** idea (not started)

## Why
The worst runs are runaways: a found loop grows where nothing in the data grows (v2.1 skill@20:
sd-bakery default -1170%, sd-clinic-doses -602%/-347%, sd-cloud-credits default -859%, sd-print-shop
-529%/-158%, sd-support-tiers default -548%). Four literature traditions recommend rejecting such models
before judging; the System Dynamics field reads behaviour modes off the eigenvalues of the linearised
model. Our data adds a caveat: some truths are unstable in their linear part and held by floors
(sd-manufacturing 1.047) or grow (population), so the test must be on simulated behaviour with floors
and caps, not on the spectral radius alone. Also an acceptance gate for added structure: the
hidden-stocks branch accepted a false hidden stock in sd-population in-sample. Playbook M1.

## How it could be tried
- In `identify()`, before the judge: free runs (H = 100-500) of each candidate from observed states,
  from all stocks at 0 and at 5-10x their observed maximum, with its own inflows, floors and caps;
  reject or penalise candidates that leave a generous multiple of the observed range when the data
  show no comparable growth.
- For a rejected candidate: the dominant eigenvalue of the per-era step matrix I + B and its
  sensitivity to each coefficient name the culprit; refit that row with it bounded (`lsq_linear`) and
  add it as a new candidate.
- Mechanism test: a stock with constant inflow 10 and drain 0.1 near equilibrium on a short run, with a
  trap candidate (positive own-coefficient plus a large constant); the gate rejects the trap, the refit
  recovers 0.1 within 0.02. Controls: a growing population keeps its positive eigenvalue; a floored
  unstable linear part is not rejected.

## Sources
Aguirre and Billings (1995) Physica D 80:26-40, doi:10.1016/0167-2789(95)90053-5; Umenberger et al.
(2018) Automatica 96:280-292, doi:10.1016/j.automatica.2018.06.036; Lacy and Bernstein (2003) IEEE TAC
48(7):1259-1263; Kaptanoglu et al. (2021) Phys. Rev. Fluids 6:094401; Kampmann and Oliva (2008) Syst.
Res. Behav. Sci. 25(4):505-519, doi:10.1002/sres.909; N. B. Forrester (1982) PhD thesis, MIT; Barlas
(1996) SDR 12(3):183-210; Forrester and Senge (1980) TIMS Studies in the Management Sciences 14.
