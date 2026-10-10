"""Pytest fixtures / path setup for orchestrator tests.

Ensures the backend root is importable so ``from orchestrator.merge_queue import ...``
works, mirroring the sys.path insertion in ``orchestrator.py`` itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
