"""The equation language and running a model's equations: what prediction judging, the
divergence check and the held-out behaviour trust need (the experiments that once edited copies
of the model here were removed on 2026-11-01, the owner).

- ``language``: the equation language every rate is written in;
- ``forms``: the model's equations in that language, and back;
- ``compile``: an equation as numpy closures;
- ``engine``: the stepper that runs a model's equations;
- ``history``: the model's series over a window, as the runs read them;
- ``heldout``: each stock's held-out replay error (``sd.behaviour``);
- ``forward``: a model and a draft of it run forward with a band (``sd.judge``, ``sd.diverge``);
- ``predicted``: the draft a prediction's expected edits make of a model (``sd.judge``);
- ``views``: the model as a machine reads it (``sd.reads``)."""
