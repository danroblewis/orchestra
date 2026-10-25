"""SD Lab's discovery research, brought into Orchestra: about fifty strategies for inferring system
dynamics models (stocks, flows, equations, hidden stocks, eras) from measured levels.

Copied from the SD Lab repository (``~/orchestra/sdlab``, commit 7edb72d, 2026-10-24): the
``sdlab.discovery`` package and ``sdlab.sdtruth_expr``, with imports rewritten from ``sdlab.`` to
``orchestra.sdlab.``. Nothing else changed. Orchestra calls it through ``orchestra.sd.strategies``.
Needs the ``sd`` extra (numpy, scipy, numba, highspy, sympy); a few research strategies need
``sd-research`` too. See README.md."""
