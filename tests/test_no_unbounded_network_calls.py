"""
Guards against the real bug this project hit: a `requests.get()`/`post()`
call with no `timeout=` can hang forever on a slow/unresponsive API --
Python's `requests` has no default timeout. That silently defeats the
retry/inconclusive-balance handling in tools/check_wallet_balances.py,
since a hung call never returns or raises for the retry loop to react to.
This scans every services/*.py and tools/*.py source file (static text
check, not an import-time check -- deliberately simple and fast) for a
requests call missing `timeout=` on the same line.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CALL_PATTERN = re.compile(r"requests\.(get|post|put|delete|patch|head)\(")


def _source_files():
    for directory in ("services", "tools", "web"):
        yield from (REPO_ROOT / directory).glob("*.py")


@pytest.mark.parametrize("path", list(_source_files()), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_requests_call_has_a_timeout(path):
    text = path.read_text()
    for match in CALL_PATTERN.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if line.strip().startswith("#"):
            continue
        assert "timeout=" in line, f"{path.relative_to(REPO_ROOT)}: requests call with no timeout= -> {line.strip()}"
