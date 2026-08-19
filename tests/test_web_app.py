import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app
from web.jobs import list_jobs


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_create_app_rejects_non_loopback_host():
    with pytest.raises(RuntimeError):
        create_app(host="0.0.0.0")


def test_create_app_accepts_localhost():
    create_app(host="localhost")


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_every_page_ships_a_theme_toggle(client):
    """Real ask: this app is dark-by-default but must let the user switch
    to a light theme -- the toggle button + its script must be present on
    every page (base.html), not just some."""
    resp = client.get("/")
    assert b'id="theme-toggle"' in resp.data
    assert b'src="/static/theme.js"' in resp.data
    # uio-02: palette selection is a second orthogonal axis applied the
    # same way -- data-palette must be set (with a default fallback) on
    # every page's pre-first-paint inline script, not just on Settings.
    assert b"data-palette" in resp.data
    assert b"coin-finder-palette" in resp.data
    assert b"archival" in resp.data


def test_settings_page_loads(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_settings_page_lists_all_palettes(client):
    resp = client.get("/settings")
    assert b"Archival" in resp.data
    assert b"Graphite" in resp.data
    assert b"Terminal" in resp.data


def test_settings_page_has_preview_swatches_and_palette_options(client):
    resp = client.get("/settings")
    assert b"data-palette-option=\"archival\"" in resp.data
    assert b"data-palette-option=\"graphite\"" in resp.data
    assert b"data-palette-option=\"terminal\"" in resp.data
    assert b"palette-swatch" in resp.data


def test_settings_page_also_ships_the_theme_toggle_relocated(client):
    """The existing dark/light toggle must also live on Settings (not
    only the top nav) -- same underlying state, so it shares the same
    class-based binding theme.js already uses, just a different id."""
    resp = client.get("/settings")
    assert b"theme-toggle-btn" in resp.data


def test_settings_link_present_in_top_nav_on_every_page(client):
    resp = client.get("/")
    assert b'href="/settings"' in resp.data


def test_default_palette_is_archival_when_nothing_stored(client):
    """theme.js falls back to the "archival" palette (the pre-existing
    warm brass/gold default) when localStorage has no stored palette --
    mirrored here via the inline pre-first-paint script every page ships
    so there's no flash of the wrong palette before JS finishes."""
    resp = client.get("/")
    assert b'localStorage.getItem("coin-finder-palette") || "archival"' in resp.data


def test_unknown_job_returns_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


def test_unknown_job_scan_page_returns_404(client):
    resp = client.get("/scan/does-not-exist")
    assert resp.status_code == 404


def test_browse_endpoint_errors_on_missing_path(client, tmp_path):
    resp = client.get("/api/browse", query_string={"path": str(tmp_path / "nope")})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_browse_endpoint_lists_subdirectories_only(client, tmp_path):
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    (tmp_path / "afile.txt").write_text("x")

    resp = client.get("/api/browse", query_string={"path": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.get_json()
    assert sorted(data["subdirectories"]) == sorted(
        [str(tmp_path / "sub1"), str(tmp_path / "sub2")]
    )


def test_scan_rejects_nonexistent_directory(client):
    resp = client.post("/scan", data={"input_dir": "/definitely/not/a/real/dir"})
    assert resp.status_code == 400


def _wait_for_done(client, job_id):
    job = None
    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        job = status_resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_find_job_lifecycle_reaches_done(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 2, "coin_counts": {"Bitcoin": 3}, "total_address_instances": 3}
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = _wait_for_done(client, job_id)

    assert job["status"] == "done"
    assert job["kind"] == "find"
    mock_pipeline.find.assert_called_once()
    mock_pipeline.check_balances.assert_not_called()
    assert mock_hidden.call_args.args == (str(tmp_path),)


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_find_job_wires_live_progress_from_both_search_and_hidden_volume_stages(mock_pipeline, mock_hidden, client, tmp_path):
    def fake_find(input_dir, out_dir, index_db_path=None, checkpoint_path=None, progress_callback=None, excludes=None):
        progress_callback(3, None, "Searching: 3 potential wallet(s) found so far — /a")
        return {"output_dir": out_dir, "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    def fake_hidden(start_path, progress_callback=None):
        progress_callback(7, None, "0 candidate(s) found so far — /a")
        return []

    mock_pipeline.find.side_effect = fake_find
    mock_hidden.side_effect = fake_hidden

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)

    assert job["status"] == "done"
    # last progress reported wins -- the hidden-volume stage runs after search/analyze
    assert job["progress"] == {"current": 7, "total": None, "message": "Checking for hidden volumes: 0 candidate(s) found so far — /a"}


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_find_status_page_renders_once_done(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    page_resp = client.get(f"/scan/{job_id}")
    assert page_resp.status_code == 200


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_find_job_error_is_reported_not_raised(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.find.side_effect = RuntimeError("boom")
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = _wait_for_done(client, job_id)

    assert job["status"] == "error"
    assert "boom" in job["error"]


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_check_balances_is_not_started_automatically(mock_pipeline, mock_hidden, client, tmp_path):
    """The whole point of the staged split: balance-checking never runs unless you explicitly ask for it."""
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 1, "coin_counts": {"Bitcoin": 5000}, "total_address_instances": 5000}
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    mock_pipeline.check_balances.assert_not_called()


@patch("web.app.record_finding")
@patch("web.app.run_pipeline")
def test_check_balances_records_findings_and_flows_progress(mock_pipeline, mock_record, client, tmp_path):
    output_dir = tmp_path / "out"
    balances_data = {"walletA.dat": {"Bitcoin": {"1abc": 0.5}}}

    def fake_find(input_dir, out_dir, index_db_path=None, checkpoint_path=None, progress_callback=None, excludes=None):
        return {"output_dir": out_dir, "files_found": 1, "coin_counts": {"Bitcoin": 1}, "total_address_instances": 1}

    def fake_check_balances(
        out_dir, progress_callback=None, checkpoint_path=None, global_max_workers=None, per_coin_max_concurrency=None
    ):
        if progress_callback:
            progress_callback(1, 1, "checking addresses")
        checks_dir = Path(out_dir) / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        with open(checks_dir / "wallet_balances.json", "w") as f:
            json.dump(balances_data, f)

    mock_pipeline.find.side_effect = fake_find
    mock_pipeline.check_balances.side_effect = fake_check_balances

    with patch("web.app.scan_for_hidden_volumes", return_value=[]):
        find_resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
        find_job_id = find_resp.headers["Location"].rstrip("/").split("/")[-1]
        _wait_for_done(client, find_job_id)

    balances_resp = client.post(f"/scan/{find_job_id}/check-balances", follow_redirects=False)
    assert balances_resp.status_code == 302
    balances_job_id = balances_resp.headers["Location"].rstrip("/").split("/")[-1]

    job = _wait_for_done(client, balances_job_id)

    assert job["status"] == "done"
    assert job["kind"] == "check-balances"
    assert job["progress"] == {"current": 1, "total": 1, "message": "checking addresses"}
    mock_record.assert_called_once_with("Bitcoin", "1abc", 0.5, source_path="walletA.dat", source_label="scan")


def test_check_balances_404s_for_unknown_job(client):
    resp = client.post("/scan/does-not-exist/check-balances")
    assert resp.status_code == 404


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_check_balances_404s_while_find_job_still_running(mock_pipeline, mock_hidden, client, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def slow_find(input_dir, out_dir, index_db_path=None, checkpoint_path=None, progress_callback=None, excludes=None):
        started.set()
        release.wait(timeout=2)
        return {"output_dir": out_dir, "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    mock_pipeline.find.side_effect = slow_find
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    started.wait(timeout=2)

    balances_resp = client.post(f"/scan/{job_id}/check-balances")
    assert balances_resp.status_code == 404

    release.set()
    _wait_for_done(client, job_id)


@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_check_balances_returns_existing_job_instead_of_duplicating_when_already_running(mock_pipeline, mock_hidden, client, tmp_path):
    """
    sse-05: mirrors
    test_start_scan_returns_existing_job_instead_of_duplicating_when_already_running
    (tests/test_web_app_scan_mounts.py) for the same class of bug, one
    stage later -- nothing stopped two check-balances jobs from racing
    against the same output_dir, last-writer-wins clobbering the same
    checkpoint file and checks/wallet_balances.json. A second request for
    an output_dir that already has a running check-balances job must
    redirect to that same job, not start a duplicate.
    """
    mock_pipeline.find.return_value = {
        "output_dir": str(tmp_path / "out"),
        "files_found": 1,
        "coin_counts": {"Bitcoin": 1},
        "total_address_instances": 1,
    }

    find_resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    find_job_id = find_resp.headers["Location"].rstrip("/").split("/")[-1]
    find_job = _wait_for_done(client, find_job_id)
    assert find_job["status"] == "done"

    release_first_job = threading.Event()

    def _blocking_check_balances(*args, **kwargs):
        release_first_job.wait(timeout=5)
        return {}

    mock_pipeline.check_balances.side_effect = _blocking_check_balances

    first_resp = client.post(f"/scan/{find_job_id}/check-balances", follow_redirects=False)
    assert first_resp.status_code == 302
    first_balances_job_id = first_resp.headers["Location"].rsplit("/", 1)[-1]

    second_resp = client.post(f"/scan/{find_job_id}/check-balances", follow_redirects=False)
    assert second_resp.status_code == 302
    second_balances_job_id = second_resp.headers["Location"].rsplit("/", 1)[-1]

    assert second_balances_job_id == first_balances_job_id

    # Filtered on checkpoint_path (not just kind/status) -- the jobs
    # registry is a real, ambient sqlite db shared across the whole test
    # session, same reason the mirrored find-job test filters on its own
    # unique target: other tests' leftover "running" jobs must never make
    # this assertion pass or fail by coincidence.
    target_checkpoint_path = str(Path(tmp_path / "out") / "checks" / "balance_checkpoint.db")
    running_balance_jobs = [
        j
        for j in list_jobs()
        if j["kind"] == "check-balances" and j.get("checkpoint_path") == target_checkpoint_path and j["status"] == "running"
    ]
    assert len(running_balance_jobs) == 1

    release_first_job.set()
    _wait_for_done(client, first_balances_job_id)


def test_flatten_balance_dict_produces_table_rows():
    from web.app import _flatten_balance_dict

    data = {"walletA.dat": {"Bitcoin": {"1abc": 0.5, "1def": 0.0}}}
    assert _flatten_balance_dict(data) == [
        {"file": "walletA.dat", "coin": "Bitcoin", "address": "1abc", "balance": 0.5},
        {"file": "walletA.dat", "coin": "Bitcoin", "address": "1def", "balance": 0.0},
    ]


def test_flatten_balance_dict_handles_none():
    from web.app import _flatten_balance_dict

    assert _flatten_balance_dict(None) == []


def test_flatten_inconclusive_dict_produces_table_rows():
    from web.app import _flatten_inconclusive_dict

    data = {"walletA.dat": {"Bitcoin": ["1abc", "1def"]}}
    assert _flatten_inconclusive_dict(data) == [
        {"file": "walletA.dat", "coin": "Bitcoin", "address": "1abc"},
        {"file": "walletA.dat", "coin": "Bitcoin", "address": "1def"},
    ]


def test_flatten_inconclusive_dict_handles_none():
    from web.app import _flatten_inconclusive_dict

    assert _flatten_inconclusive_dict(None) == []
