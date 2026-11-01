"""The Instruments page's intro explains only columns the table has: each <b>term</b> it defines
is one of the table's header labels."""

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "orchestra" / "web" / "static" / "instruments.html"


def test_every_column_the_intro_defines_is_a_column():
    html = PAGE.read_text()
    intro = re.search(r'<div class="intro">(.*?)</div>', html, re.DOTALL).group(1)
    terms = {t.lower() for t in re.findall(r"<b>([^<]+)</b>", intro)}
    headers = {h.lower() for h in re.findall(r"<th>([^<]+)</th>", html)}
    assert terms and headers, (terms, headers)
    assert terms <= headers, f"the intro defines {sorted(terms - headers)}, which the table does not have: {sorted(headers)}"
