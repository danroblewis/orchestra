"""The on-disk format: one float32 file per metric plus `index.json`.

Every series has one sample per step on the shared grid `start + i*step`,
i = 0..n-1, so series `k` of a metric lives at byte offset `k * n * 4` of
`<metric>.bin`. NaN means no sample.
"""

import json
import mmap
import os
from array import array

FORMAT = 1


class Writer:
    def __init__(self, out: str, start: int, step: int, n: int):
        os.makedirs(out, exist_ok=True)
        self.out, self.start, self.step, self.n = out, start, step, n
        self.metrics: dict[str, dict] = {}
        self.files: dict[str, object] = {}

    def declare(self, name: str, kind: str, help_text: str):
        self.metrics[name] = {"type": kind, "help": help_text, "file": f"{name}.bin", "series": []}
        self.files[name] = open(os.path.join(self.out, f"{name}.bin"), "wb")

    def add(self, name: str, labels: dict, values):
        data = values if isinstance(values, array) and values.typecode == "f" else array("f", values)
        if len(data) != self.n:
            raise ValueError(f"{name}{labels}: {len(data)} samples, expected {self.n}")
        meta = self.metrics[name]
        meta["series"].append({"labels": labels, "offset": len(meta["series"]) * self.n * 4})
        self.files[name].write(data.tobytes())

    def close(self):
        for f in self.files.values():
            f.close()
        index = {
            "format": FORMAT,
            "start": self.start,
            "end": self.start + (self.n - 1) * self.step,
            "step": self.step,
            "n": self.n,
            "metrics": self.metrics,
        }
        with open(os.path.join(self.out, "index.json"), "w") as f:
            json.dump(index, f)


class Series:
    __slots__ = ("metric", "labels", "key", "_mm", "_off")

    def __init__(self, metric, labels, mm, off):
        self.metric = metric
        self.labels = {"__name__": metric, **labels}
        self.key = tuple(sorted(self.labels.items()))
        self._mm, self._off = mm, off

    def read(self, j0: int, j1: int) -> array:
        """Samples j0..j1-1 as float32."""
        a = array("f")
        a.frombytes(self._mm[self._off + j0 * 4 : self._off + j1 * 4])
        return a


class Dataset:
    """Read side: the index in memory, the samples memory-mapped."""

    def __init__(self, path: str):
        with open(os.path.join(path, "index.json")) as f:
            index = json.load(f)
        self.path = path
        self.start, self.end, self.step, self.n = index["start"], index["end"], index["step"], index["n"]
        self.meta = {name: {"type": m["type"], "help": m["help"]} for name, m in index["metrics"].items()}
        self.series: list[Series] = []
        self.by_metric: dict[str, list[Series]] = {}
        self._maps = []
        for name, m in index["metrics"].items():
            with open(os.path.join(path, m["file"]), "rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) if os.fstat(f.fileno()).st_size else b""
            self._maps.append(mm)
            rows = [Series(name, s["labels"], mm, s["offset"]) for s in m["series"]]
            self.by_metric[name] = rows
            self.series.extend(rows)
