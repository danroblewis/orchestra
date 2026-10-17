"""Writes truth.json, the answer key, from truth.model.json (see sdlab/sdtruth.py)."""

from pathlib import Path

from sdlab.sdtruth import Truth, write_truth

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    write_truth(Truth(here / "truth.model.json"), here / "truth.json")
