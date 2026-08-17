from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_real_findings_db():
    """
    Safety net: no test may ever read or write the real local
    web/findings.db -- not even to create an empty one.

    web/app.py's job functions (_run_scan_job, _run_scan_wallet_dat_job,
    _run_crawl_job, _run_fork_coins_job) call web.findings.record_finding()
    as a side effect of their normal work, and the index route calls
    list_findings() on every load. Without this, running the test suite
    either leaks test fixture addresses (e.g. "1abc") into the real,
    persistent findings database the local web UI actually shows the user,
    or (for list_findings(), even when its data isn't asserted on) creates
    a stray real db file as a side effect of connecting to it -- both real
    issues caught during this project's own development (see CHANGELOG's
    findings-dashboard entry). list_findings() defaults to an empty list
    here so routes that just display a count don't need every test to
    override it individually; tests asserting specific findings still
    override with their own @patch. Autouse so this protection covers
    every test, including ones written after this fixture existed.

    _run_crawl_job also calls web.crawl_runs.record_crawl_run() (added by
    the group-view-graph epic) -- same leak risk, same fix: mocked here by
    default, tests asserting on it override with their own @patch.

    _run_find_job also calls web.scan_history.record_scan() (added by the
    durable-scan-history epic) -- same leak risk, same fix: mocked here by
    default, tests asserting on it override with their own @patch.

    _run_auto_unlock_job also calls web.auto_unlock_history.
    record_auto_unlock_run() (added by the auto-unlock-overhaul epic's
    auo-02 story) -- same leak risk, same fix: mocked here by default,
    tests asserting on it override with their own @patch.

    findings_page() also calls web.auto_unlock_history.
    list_auto_unlock_history() and latest_status_by_wallet_path() on every
    load (added by ccu-02, for the per-row unlock badge and the batch
    summary banner) -- same leak risk, same fix: defaulted to "no history"
    here, tests asserting on either override with their own @patch.

    findings_page() also calls web.credential_scan_cache.
    credential_status_index() on every load (added by ccu-03, for the
    key-extractable/encrypted-locked badge) -- same leak risk against the
    real credential_scan_cache.db, same fix: defaulted to "nothing
    scanned yet" here, tests asserting on it override with their own
    @patch.
    """
    with (
        patch("web.app.record_finding"),
        patch("web.app.list_findings", return_value=[]),
        patch("web.app.record_crawl_run"),
        patch("web.app.record_scan"),
        patch("web.app.record_auto_unlock_run"),
        patch("web.app.list_auto_unlock_history", return_value=[]),
        patch("web.app.latest_status_by_wallet_path", return_value={}),
        patch("web.app.credential_status_index", return_value={}),
    ):
        yield
