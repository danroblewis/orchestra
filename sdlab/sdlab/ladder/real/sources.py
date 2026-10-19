"""Where the real data come from, and the local cache that holds them.

Four sources (docs/research/case-study-sources.md, "Recommendation"):

| source | what | licence | how it is kept |
|---|---|---|---|
| `bls` | US CPS labour force status flows: the levels E, U, N (16+, seasonally adjusted) and the gross flows between them, monthly from 1990 (api.bls.gov) | US public domain | committed: `data/bls_cps_flows.csv` (small) |
| `gauseR` | Gause's and others' lab populations (R package gauseR, CRAN) | GPL-3 | downloaded at ingest into the cache, never committed |
| `pomp` | the 1978 boarding-school influenza, `bsflu` (R package pomp, CRAN) | GPL | downloaded at ingest into the cache, never committed |
| `owid` | share of US households owning each technology (Our World in Data, Comin and Hobijn 2004 and others) | CC BY 4.0 | downloaded at ingest into the cache, never committed |

The cache is `$SDLAB_REAL_CACHE` (default `~/.cache/sdlab/real/`). Nothing is fetched while a case is
loaded or run: `python -m sdlab.ladder.real fetch` downloads (and, for the R packages, converts each
`.rda` into a JSON table with the optional `rdata` package: `uv run --with rdata ...`). A case whose
data are not in the cache is skipped with a message naming that command, never a crash.

Downloads are untrusted data: archives are extracted with tarfile's "data" filter into a fresh
folder, and only the R data files are read (parsed by `rdata`, which only reads them).
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLS_SNAPSHOT = HERE / "data" / "bls_cps_flows.csv"
AGENT = "sdlab-research/0.1 (SD Lab real-data cases)"
TIMEOUT = 60

SOURCES = {
    "bls": {"url": "https://api.bls.gov/publicAPI/v2/timeseries/data/", "licence": "US public domain (Bureau of Labor Statistics)",
            "cite": "BLS, Current Population Survey, labor force status flows (https://www.bls.gov/cps/cps_flows.htm)"},
    "gauseR": {"url": "https://cran.r-project.org/src/contrib/gauseR_1.3.tar.gz",
               "fallback": "https://cran.r-project.org/src/contrib/Archive/gauseR/gauseR_1.3.tar.gz",
               "licence": "GPL-3 (the package); the counts are Gause's published observations",
               "cite": "Muhlbauer, Gause, Clark: gauseR (CRAN); Gause (1934) The Struggle for Existence, and Gause's papers named per dataset"},
    "pomp": {"url": "https://cran.r-project.org/src/contrib/pomp_6.4.tar.gz",
             "fallback": "https://cran.r-project.org/src/contrib/Archive/pomp/pomp_6.4.tar.gz",
             "licence": "GPL (the package); the counts are from Anonymous (1978), BMJ 1(6112):587",
             "cite": "King et al., pomp (CRAN), dataset bsflu; Anonymous (1978) Influenza in a boarding school, BMJ 1:587"},
    "owid": {"url": "https://ourworldindata.org/grapher/technology-adoption-by-households-in-the-united-states.csv?v=1&csvType=full&useColumnShortNames=true",
             "licence": "CC BY 4.0 (Our World in Data)",
             "cite": "Our World in Data, Technology adoption by households in the United States (Comin and Hobijn 2004, and others)"},
}

# BLS series: the levels and the flows (LNS17... are the labour force status flows, seasonally adjusted,
# thousands of persons; "other" is BLS's marginal inflow: people entering the 16+ population and other changes)
BLS_SERIES = {
    "E": "LNS12000000", "U": "LNS13000000", "N": "LNS15000000",
    "EE": "LNS17000000", "UE": "LNS17100000", "NE": "LNS17200000", "OE": "LNS17300000",
    "EU": "LNS17400000", "UU": "LNS17500000", "NU": "LNS17600000", "OU": "LNS17700000",
    "EN": "LNS17800000", "UN": "LNS17900000", "NN": "LNS18000000", "ON": "LNS18100000",
}


class Missing(Exception):
    """A real case's data are not in the cache (or differ from what the case was built from)."""


def cache_root() -> Path:
    return Path(os.environ.get("SDLAB_REAL_CACHE") or Path.home() / ".cache" / "sdlab" / "real")


def fetch_hint(source: str) -> str:
    extra = "--with rdata " if source in ("gauseR", "pomp") else ""
    return f"uv run {extra}python -m sdlab.ladder.real fetch {source}"


# ---- reading what is cached ----

def table(source: str, name: str) -> list[dict]:
    """A cached table as a list of records: an R dataset (gauseR, pomp) or the OWID csv. Missing if absent."""
    if source == "bls":
        return bls_rows()
    path = cache_root() / source / (f"{name}.json" if source in ("gauseR", "pomp") else f"{name}.csv")
    if not path.exists():
        raise Missing(f"{source} data are not downloaded ({path} is missing): run `{fetch_hint(source)}`")
    if path.suffix == ".json":
        return json.loads(path.read_text())
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def bls_rows(path: Path | None = None) -> list[dict]:
    """The committed BLS snapshot: one record per month {month, E, U, N, EE, ...} (numbers; None where BLS has none)."""
    p = path or BLS_SNAPSHOT
    if not p.exists():
        raise Missing(f"the BLS snapshot {p} is missing: run `{fetch_hint('bls')}`")
    with p.open(newline="") as f:
        return [{k: (v if k == "month" else (float(v) if v not in ("", None) else None)) for k, v in r.items()} for r in csv.DictReader(f)]


# ---- downloading ----

def _get(url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:          # noqa: S310  (fixed https URLs above)
        return r.read()


def fetch(source: str) -> str:
    """Download one source into the cache (BLS: rewrite the committed snapshot). Returns what was done."""
    if source == "bls":
        return fetch_bls()
    if source in ("gauseR", "pomp"):
        return fetch_rpackage(source)
    if source == "owid":
        dest = cache_root() / "owid" / "technology-adoption.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = _get(SOURCES["owid"]["url"])
        _atomic(dest, body)
        return f"owid: {len(body.splitlines()) - 1} rows -> {dest}"
    raise ValueError(f"unknown source {source!r} (have: {', '.join(SOURCES)})")


def fetch_bls(first: int = 1990, last: int | None = None, dest: Path | None = None) -> str:
    """The BLS series, 10 years per request (the public API's limit without a key), into the snapshot csv."""
    import datetime

    last = last or datetime.date.today().year
    ids = {v: k for k, v in BLS_SERIES.items()}
    got: dict[str, dict[str, float]] = {}
    for y0 in range(first, last + 1, 10):
        body = json.dumps({"seriesid": list(ids), "startyear": str(y0), "endyear": str(min(last, y0 + 9))}).encode()
        r = json.loads(_get(SOURCES["bls"]["url"], body, {"Content-Type": "application/json"}))
        if r.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API: {r.get('status')}: {r.get('message')}")
        for s in r["Results"]["series"]:
            for x in s["data"]:
                if x["period"].startswith("M") and x["period"] != "M13" and x["value"] not in ("-", ""):
                    got.setdefault(f"{x['year']}-{x['period'][1:]}", {})[ids[s["seriesID"]]] = float(x["value"])
    cols = list(BLS_SERIES)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["month"] + cols)
    for m in sorted(got):
        w.writerow([m] + [_num(got[m].get(c)) for c in cols])
    p = dest or BLS_SNAPSHOT
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic(p, out.getvalue().encode())
    return f"bls: {len(got)} months -> {p}"


def _num(v):
    return "" if v is None else (str(int(v)) if float(v).is_integer() else repr(float(v)))


def fetch_rpackage(source: str) -> str:
    """An R package's data/*.rda, each converted to a JSON table (needs the optional package rdata)."""
    try:
        import rdata  # noqa: F401
    except ImportError:
        raise SystemExit(f"{source}: converting R data needs the optional package rdata: `{fetch_hint(source)}`") from None
    info = SOURCES[source]
    try:
        body = _get(info["url"])
    except Exception:                                                 # noqa: BLE001  (moved to the archive)
        body = _get(info["fallback"])
    dest = cache_root() / source
    dest.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"sdlab-real-{source}-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
            members = [m for m in tf.getmembers() if m.isfile() and "/data/" in m.name and m.name.endswith(".rda")]
            tf.extractall(work, members=members, filter="data")
        n = 0
        for p in sorted(work.rglob("*.rda")):
            for name, frame in _read_rda(p).items():
                _atomic(dest / f"{name}.json", json.dumps(frame, separators=(",", ":")).encode())
                n += 1
        _atomic(dest / "SOURCE.json", json.dumps({"url": info["url"], "licence": info["licence"], "sha256": _sha(body)}).encode())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return f"{source}: {n} tables -> {dest}"


def _read_rda(path: Path) -> dict[str, list[dict]]:
    """An .rda file's data frames as lists of records (R's NA as None; factors as their labels; dates as day numbers)."""
    import math

    import rdata

    parsed = rdata.parser.parse_file(path)
    conv = rdata.conversion.convert(parsed, default_encoding="utf8")
    out = {}
    for name, df in conv.items():
        if not hasattr(df, "to_dict"):
            continue
        recs = []
        for row in df.to_dict(orient="records"):
            rec = {}
            for k, v in row.items():
                if hasattr(v, "item"):
                    v = v.item()
                if isinstance(v, float) and math.isnan(v):
                    v = None
                elif v is not None and not isinstance(v, (int, float, str, bool)):
                    v = str(v)
                rec[str(k)] = v
            recs.append(rec)
        out[name] = recs
    return out


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _atomic(path: Path, body: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
