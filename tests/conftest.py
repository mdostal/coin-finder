from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_real_findings_db():
    """
    Safety net: no test may ever write to the real local web/findings.db.

    web/app.py's job functions (_run_scan_job, _run_scan_wallet_dat_job,
    _run_crawl_job, _run_fork_coins_job) call web.findings.record_finding()
    as a side effect of their normal work. Without this, running the test
    suite leaks test fixture addresses (e.g. "1abc") into the real,
    persistent findings database the local web UI actually shows the user
    -- a real bug caught during this project's own development (see
    CHANGELOG's findings-dashboard entry). Autouse so this protection
    covers every test, including ones written after this fixture existed.
    """
    with patch("web.app.record_finding"):
        yield
