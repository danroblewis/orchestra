"""Experiments: a staged, editable copy of the system dynamics model that any machine may change
and run three ways (forward, replay, inverse), and commit as a prediction (goals G5, G13, G16).

- ``language``: the equation language every rate is written in;
- ``forms``: the model's equations in that language, and back;
- ``compile``: an equation as numpy closures;
- ``engine``: the stepper that runs a model's equations;
- ``record`` and ``store``: an experiment, kept in the state directory;
- ``edits``: the operations on a draft, checked;
- ``forward``, ``replay``, ``inverse``: the three runs;
- ``commit``: a committed experiment as a prediction (``sd.predictions``);
- ``views``: the model, eras and series as a machine reads them;
- ``service``: all of it as JSON in and out, for the Python API and the HTTP API."""
