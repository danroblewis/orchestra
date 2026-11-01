"""Serving the web UI's HTML pages: Orchestra's static directory and how a page is rendered."""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent / "static"


def render(file: Path, stylesheets: list[str]) -> str:
    """An HTML page as served: ``{{v}}`` is the newest asset's mtime, so a browser never keeps a
    stale stylesheet or script after an upgrade, and the plugins' stylesheets are linked at the
    end of its head (after Orchestra's own) unless the page links them already."""
    v = str(int(max(p.stat().st_mtime for p in STATIC.glob("*"))))
    html = file.read_text(encoding="utf-8").replace("{{v}}", v)
    links = "".join(f'<link rel="stylesheet" href="{s}">\n' for s in stylesheets if s not in html)
    at = html.find("</head>")
    return html[:at] + links + html[at:] if at >= 0 else links + html
