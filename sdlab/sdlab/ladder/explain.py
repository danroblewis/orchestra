"""Plain-language explanations of the strategies and a glossary of the ladder's words, from
explanations.yaml beside this file (kept out of the strategy packages, whose source the ladder hashes).

    about(name)    the strategy's entry {idea, how, helps_with, builds_on, status, note?} or None
    glossary()     {key: {term, text}}

The file is read once and again only when its modification time changes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PATH = Path(__file__).with_name("explanations.yaml")
_cache: dict = {}


def _load() -> dict:
    mtime = PATH.stat().st_mtime_ns
    if _cache.get("mtime") != mtime:
        doc = yaml.safe_load(PATH.read_text()) or {}
        _cache.update(mtime=mtime, value={"strategies": doc.get("strategies") or {}, "glossary": doc.get("glossary") or {}})
    return _cache["value"]


def about(name: str) -> dict | None:
    entry = _load()["strategies"].get(name)
    return dict(entry) if entry else None


def strategies() -> dict:
    return {k: dict(v) for k, v in _load()["strategies"].items()}


def glossary() -> dict:
    return {k: dict(v) for k, v in _load()["glossary"].items()}
