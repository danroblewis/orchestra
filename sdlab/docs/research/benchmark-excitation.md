# Does the ground-truth data keep exercising its model?

**Status:** done  
**Verdict:** yes, except sd-population

## Question
Are the simulations stable and recurrent over time, or do feedback loops settle so that late data
stops exercising the flows? Is it safe to test on fixed-length runs?

## What was done
Measured on the long runs of the v1 examples (main line, `6a275c7`): spread of step changes late vs
early, level spread late vs early, correlation between successive schedule periods, spectral radius
of the true linear part. Added `test_the_data_keeps_exercising_the_model` (50x runs) and the bench
column "truth moved@20".

## Results
- Movement does not decay anywhere (late/early 0.94-1.21); level spread holds (0.71-1.09) except
  **sd-population (0.13)**, which settles near equilibrium after its first transient (strict xfail).
- Schedules recur by construction (period correlation 0.58-1.00; 0.18-0.37 for short noisy periods).
- Linear parts: stable or neutral (0.75-1.00); sd-manufacturing 1.047 (unstable, held by floors).
- Long runs cover >= 10 schedule periods; many default runs cover one (harder, not unstable).
- sd-population long moves 0.07 of its level spread in 20 steps (others 0.6-1.2): a fragile grade.
