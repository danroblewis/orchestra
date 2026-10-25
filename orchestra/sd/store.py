"""Model store: models as JSON under the project's state directory (``<state>/models/<id>.json``).

Declared structure and fitted equations live together in one file per model; every equation
carries its origin, so a reader can always tell a fit from an assumption."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Model


class ModelStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def path(self, model_id: str) -> Path:
        return self.dir / f"{model_id}.json"

    def save(self, model: Model) -> Path:
        errs = model.check()
        if errs:
            raise ValueError("; ".join(errs))
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.path(model.id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(model.to_json(), indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)
        return p

    def load(self, model_id: str) -> Model | None:
        p = self.path(model_id)
        return Model.from_json(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json")) if self.dir.exists() else []
