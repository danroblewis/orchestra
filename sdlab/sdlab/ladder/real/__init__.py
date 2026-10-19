"""Real-data cases on the ladder (tag `real`): measured series with a published model, scored apart from the tests.

CLAUDE.md invariant 3: real-data cases are additional information beside the formal tests, scored by
held-out prediction and agreement with the published model, and never counted in the Tests pass rate.

    sources.py   where the data come from, the cache (~/.cache/sdlab/real), fetching
    loaders.py   a cached table -> one case's series (levels, injections, measured flows)
    models.py    the published structures as SD Lab models, and their case-format text
    fit.py       running a model over the samples; refitting a published structure on the training part
    build.py     the catalogue, and writing cases/real/<id>.yaml (python -m sdlab.ladder.real build)
    case.py      a case file as a ladder case (variants `real` and `twin`, the hash)
    data.py      the variants' data (the series from the cache; the twin from the engine)
    score.py     held-out prediction, agreement, measured flows, the twin's equation score; summary cells
    report.py    the leaders' results as a table (python -m sdlab.ladder.real report)

docs/LADDER.md, "Real-data cases", explains the design.
"""

from .case import TAG, is_real  # noqa: F401
