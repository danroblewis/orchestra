"""The core pages load every script and stylesheet from Orchestra itself (web/static/vendor/ for
d3, elkjs and GridStack), so they draw behind a proxy that blocks the CDNs; each vendored library
ships with its licence."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "orchestra" / "web" / "static"
EXTERNAL = re.compile(r"""<(?:script[^>]*\ssrc|link[^>]*\shref)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE)


def test_every_page_references_only_local_scripts_and_stylesheets():
    pages = sorted(STATIC.glob("*.html"))
    assert pages
    offenders = {p.name: EXTERNAL.findall(p.read_text()) for p in pages}
    assert not {k: v for k, v in offenders.items() if v}, offenders


def test_the_vendored_files_are_there_with_their_licences():
    v = STATIC / "vendor"
    for f in ("d3.min.js", "elk.bundled.js", "gridstack-all.js", "gridstack.min.css",
              "d3.LICENSE", "elkjs.LICENSE.md", "gridstack.LICENSE"):
        assert (v / f).is_file() and (v / f).stat().st_size > 0, f
    assert (v / "d3.min.js").read_text().startswith("// https://d3js.org v7.9.0")
    assert "Eclipse Public License - v 2.0" in (v / "elkjs.LICENSE.md").read_text()
    for page, lib in (("index.html", "/static/vendor/gridstack-all.js"), ("machines.html", "/static/vendor/d3.min.js"),
                      ("dynamics.html", "/static/vendor/d3.min.js"), ("dynamics.html", "/static/vendor/elk.bundled.js")):
        assert lib in (STATIC / page).read_text(), (page, lib)
