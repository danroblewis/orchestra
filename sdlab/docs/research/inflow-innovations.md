# Outside-input changes estimated on innovations, jointly with the dynamics

**Status:** idea (not started)

## Why
Outside-inflow pieces absorb internal dynamics (sd-population's 151 pieces on v1; pieces into internal
stocks in sd-support-tiers), and the textbook price does not cure it ([change-price](change-price.md)):
a misspecified drain leaves autocorrelated residuals, which makes any fixed penalty wrong, and an intake
that changes at a steady rate breaks the fixed-count assumption. The change-point literature detects
changes on innovations, chooses the penalty from the whole penalty path, and estimates breaks jointly
with the slopes. Short pieces bias a row's own coefficient by about (1 + a)/(m - 1) (change-price open
ideas; a 10-step minimum gave 73.2% vs 70.8% on v1). Playbook M6.

## How it could be tried
- Fit AR(1) to the row's residual and run PELT on the innovations (or a DeCAFS-style cost).
- CROPS over a range of penalties; take the elbow per stock.
- Minimum piece length tied to the row's time constant: max(5, c / own drain).
- After the fit, regress piece means on every other level's means over the same segments; a strong
  relation proposes that level as a column (generalises level-for-pieces); check that a structural
  addition removes the pieces.
- Mechanism tests: the change-price chain (the downstream stock gets no pieces, the inbox keeps its
  real ones); a misspecified drain with AR residuals (no spurious pieces); control: a genuine
  steady-rate intake keeps its pieces.
- Combine with [complexity-budget](complexity-budget.md) (this decides how changes are found, the
  budget how many may be kept).

## Sources
Romano, Rigaill, Runge and Fearnhead (2022) JASA 117(540):2147-2162, doi:10.1080/01621459.2021.1909598;
Haynes, Eckley and Fearnhead (2017) JCGS 26(1):134-143, doi:10.1080/10618600.2015.1116445; Killick,
Fearnhead and Eckley (2012) JASA 107(500):1590-1598; Bai and Perron (1998) Econometrica 66(1):47-78;
Ohlsson, Ljung and Boyd (2010) Automatica 46(6):1107-1111; Chen and Liu (1993) JASA 88(421):284-297;
Kirchner (2009) WRR 45(2):W02429; Lyneis (2000) SDR 16(1):3-25.
