"""External data for the reader (read.py): GET XLS / GET DIRECT CONSTANTS, DATA and LOOKUPS, read
through PySD itself, so the numbers are exactly the ones PySD's run uses.

    ext = External(path)                         # the model's folder is copied (the data sit beside it)
    ext.values(name, coord, times)  -> [floats]  # a constant or a data series at the given times
    ext.lookup(py, coord)           -> (xs, ys)  # an external lookup's points

A constant becomes a number; a data series becomes a lookup of TIME through its values at every Euler
step, which pysd_import turns into a measured input (one value per recorded step), like any other
function of time; an external lookup becomes a lookup table. Data from a model's own .vdf/.tab files
(a DATA variable without GET) needs PySD's data_files and stays blocked.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def copy_folder(path: Path, into: Path) -> Path:
    """The model's folder copied into `into` (PySD writes its translation beside the model); the copy's
    model path."""
    for p in path.parent.iterdir():
        if p.is_file():
            shutil.copy(p, into / p.name)
        elif p.is_dir() and not p.name.startswith("."):
            shutil.copytree(p, into / p.name, dirs_exist_ok=True)
    return into / path.name


class External:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._model = None
        self._dir = None

    def model(self):
        if self._model is None:
            import pysd

            self._dir = tempfile.TemporaryDirectory()
            p = copy_folder(self.path, Path(self._dir.name))
            self._model = pysd.read_vensim(str(p)) if p.suffix.lower() == ".mdl" else pysd.read_xmile(str(p))
        return self._model

    def values(self, name: str, coord: tuple, times: list[float]) -> list[float]:
        from .arrays import label

        df = self.model().run(return_timestamps=list(times), return_columns=[name], progress=False)
        col = label(name, coord)
        if col not in df.columns:
            col = name
        return [float(x) for x in df[col].to_numpy()]

    def lookup(self, py: str, coord: tuple) -> tuple[list[float], list[float]]:
        ext = getattr(self.model().components, f"_ext_lookup_{py}")
        data = ext.data
        sel = {}
        for d in data.dims:
            if d == "lookup_dim":
                continue
            vals = [str(v) for v in data.coords[d].values]
            e = next((e for e in coord if e in vals), None)
            if e is None:
                raise KeyError(d)
            sel[d] = e
        if sel:
            data = data.sel(sel)
        pts = [(float(x), float(y)) for x, y in zip(data.coords["lookup_dim"].values, data.values) if x == x and y == y]
        return [x for x, _ in pts], [y for _, y in pts]

    def close(self):
        if self._dir is not None:
            self._dir.cleanup()
            self._dir, self._model = None, None
