"""The model does not lean on the web pages: no module under orchestra/sd imports orchestra.web
(the web server reads the model, never the other way round)."""

import re
from pathlib import Path

SD = Path(__file__).resolve().parents[2] / "orchestra" / "sd"
WEB = re.compile(r"^\s*(from\s+(\.{2,}web\b|orchestra\.web\b)|import\s+orchestra\.web\b)", re.MULTILINE)


def test_no_sd_module_imports_the_web_package():
    found = [f"{p.relative_to(SD.parent)}: {m.group(0).strip()}" for p in sorted(SD.rglob("*.py"))
             for m in WEB.finditer(p.read_text(encoding="utf-8"))]
    assert not found, found
