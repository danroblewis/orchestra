"""One thread per bench worker: imported before numpy. The bench runs many workers at once (and
experiments run benches side by side); numpy's own threads in each would oversubscribe the cores."""

import os

for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(var, "1")
