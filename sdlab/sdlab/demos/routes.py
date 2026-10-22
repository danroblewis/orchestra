"""/api/demos: the demos' JSON (docs/DEMOS.md). Read only: nothing here writes the store, a case or a strategy."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import demos as D

router = APIRouter(prefix="/api/demos")
STATIC = Path(__file__).resolve().parent.parent / "static"
CORE = {"demos", "engine", "routes", "scenarios", "__init__"}


def _call(fn, *a, **k):
    try:
        return D.__dict__[fn](*a, **k) if isinstance(fn, str) else fn(*a, **k)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


@router.get("")
def overview() -> dict:
    return D.overview()


@router.get("/{name}/model")
def model(name: str) -> dict:
    return _call(D.model, name)


@router.get("/{name}/residual")
def residual(name: str, change: str, noise: bool = False, seed: int = 7) -> dict:
    return _call(D.residual, name, change, noise=noise, seed=seed)


@router.get("/{name}/whatif")
def whatif(name: str, key: str, value: float, steps: int = 1000) -> dict:
    return _call(D.whatif, name, key, value, steps=max(50, min(steps, 2000)))


@router.get("/{name}/leverage")
def leverage(name: str, goal: str) -> dict:
    return _call(D.leverage, name, goal)


@router.get("/{name}/hidden")
def hidden(name: str) -> dict:
    return _call(D.hidden, name)


@router.get("/manifest")
def manifest() -> dict:
    """The page's extra demos: every static/demos-<name>.js, loaded after demos.js (each registers its own tab)."""
    files = sorted(STATIC.glob("demos-*.js"))
    return {"scripts": [f"/static/{p.name}" for p in files],                       # the addresses
            "load": [f"/static/{p.name}?v={int(p.stat().st_mtime)}" for p in files],  # with their change time: what the page loads (the CDN keeps /static/* for hours)
            "broken": BROKEN}


# every other module in this package with a `router` (one demo each) adds its routes under /api/demos
BROKEN: dict[str, str] = {}                 # a demo module that fails to import is skipped (the server still starts)
for _m in pkgutil.iter_modules([str(Path(__file__).resolve().parent)]):
    if _m.name not in CORE:
        try:
            _mod = importlib.import_module(f"{__package__}.{_m.name}")
        except Exception as e:                                  # noqa: BLE001
            BROKEN[_m.name] = f"{type(e).__name__}: {e}"
            continue
        if isinstance(getattr(_mod, "router", None), APIRouter):
            router.include_router(_mod.router)
