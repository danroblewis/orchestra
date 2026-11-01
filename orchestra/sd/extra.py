"""``orchestra[sd]``: numpy, scipy and SD Lab's other dependencies (pyproject.toml's ``sd`` extra).

Without it Orchestra still runs: the host, the Core page, and conservation discovery need none of
it (AGENTS.md rule 8). What steps the simulator (behaviour trust, simulation, divergence,
observability, experiments, SD Lab's strategies) is skipped or answered with ``message``. Nothing
on the always-imported path imports these modules at module level."""

from __future__ import annotations

MODULES = {"numpy", "scipy", "numba", "highspy", "sympy"}
INSTALL = "pip install 'orchestra[sd]'"


def installed() -> bool:
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        return True
    except ImportError:
        return False


def message(what: str = "this") -> str:
    return f"{what} needs orchestra[sd] installed ({INSTALL})"


def missing(e: BaseException) -> bool:
    """Whether ``e`` is an import of one of the extra's modules failing."""
    return isinstance(e, ImportError) and (getattr(e, "name", None) or "").split(".")[0] in MODULES
