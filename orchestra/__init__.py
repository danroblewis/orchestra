"""Orchestra: a multi-layer, AI-driven software development workflow orchestrator.

This package is the public CLI surface. It wraps the existing ``backend`` code
(the shared repository layer, the orchestrator, and the read-only web viewer) and
adds orchestration state living outside the target repo, in ``~/.orchestra/``.

The package layout:

- :mod:`orchestra.project`  -- resolve the target repo + ``~/.orchestra/<slug>`` state.
- :mod:`orchestra.gitops`   -- git worktree management (one worktree per ticket).
- :mod:`orchestra.config`   -- ``config.json`` schema, load/save, defaults.
- :mod:`orchestra.cli`      -- the ``orchestra`` command line (``run`` / ``web`` / ...).
"""

from __future__ import annotations

__version__ = "0.3.0"

# ``backend`` holds the legacy shared/orchestrator/web code. We import lazily from
# the submodules that need it so the CLI stays import-light and testable.

__all__ = ["__version__"]
