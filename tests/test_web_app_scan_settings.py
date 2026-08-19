import time
from unittest.mock import patch

import pytest

from web.app import create_app
from web.scan_settings import get_settings as real_get_settings
from web.scan_settings import set_mode as real_set_mode
from web.scan_settings import set_overrides as real_set_overrides


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_done(client, job_id):
    job = None
    for _ in range(100):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


def _start_find_job(client, tmp_path, files):
    for name, content in files.items():
        (tmp_path / name).write_text(content)

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)
    assert job["status"] == "done"
    return job_id, job["result"]["output_dir"]


@patch("web.app.set_overrides")
@patch("web.app.set_mode")
@patch("web.app.get_settings")
def test_get_scan_settings_route_returns_current_settings(mock_get, mock_set_mode, mock_set_overrides, client):
    mock_get.return_value = {
        "mode": "auto",
        "overrides": {
            "search_walk_threads": None,
            "analyze_processes": None,
            "check_balances_global_workers": None,
            "check_balances_per_coin_concurrency": None,
        },
    }

    resp = client.get("/api/scan-settings")

    assert resp.status_code == 200
    assert resp.get_json()["mode"] == "auto"
    mock_set_mode.assert_not_called()
    mock_set_overrides.assert_not_called()


@patch("web.app.set_overrides")
@patch("web.app.set_mode")
@patch("web.app.get_settings")
def test_post_scan_settings_route_applies_mode_and_overrides(mock_get, mock_set_mode, mock_set_overrides, client):
    mock_get.return_value = {"mode": "custom", "overrides": {"check_balances_global_workers": 20}}

    resp = client.post("/api/scan-settings", json={"mode": "custom", "overrides": {"check_balances_global_workers": 20}})

    assert resp.status_code == 200
    mock_set_mode.assert_called_once_with("custom")
    mock_set_overrides.assert_called_once_with({"check_balances_global_workers": 20})
    assert resp.get_json()["mode"] == "custom"


def test_scan_settings_route_round_trips_through_the_real_store(client, tmp_path):
    """No mocking of web.scan_settings' own logic here -- only the
    on-disk db path is redirected to tmp_path, so this proves the actual
    get/set contract works end-to-end through the route, not just that
    the route calls through to some mock."""
    db_path = tmp_path / "scan_settings.db"

    with patch("web.app.get_settings", side_effect=lambda: real_get_settings(db_path=db_path)), \
         patch("web.app.set_mode", side_effect=lambda mode: real_set_mode(mode, db_path=db_path)), \
         patch("web.app.set_overrides", side_effect=lambda overrides: real_set_overrides(overrides, db_path=db_path)):

        resp = client.post(
            "/api/scan-settings", json={"mode": "custom", "overrides": {"check_balances_global_workers": 20}}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["mode"] == "custom"
        assert body["overrides"]["check_balances_global_workers"] == 20

        resp2 = client.get("/api/scan-settings")
        body2 = resp2.get_json()
        assert body2["mode"] == "custom"
        assert body2["overrides"]["check_balances_global_workers"] == 20


def test_scan_settings_route_rejects_invalid_mode(client, tmp_path):
    db_path = tmp_path / "scan_settings.db"

    with patch("web.app.set_mode", side_effect=lambda mode: real_set_mode(mode, db_path=db_path)):
        resp = client.post("/api/scan-settings", json={"mode": "bogus"})

    assert resp.status_code == 400


def test_scan_settings_route_rejects_unknown_override_key(client, tmp_path):
    db_path = tmp_path / "scan_settings.db"

    with patch("web.app.set_overrides", side_effect=lambda overrides: real_set_overrides(overrides, db_path=db_path)):
        resp = client.post("/api/scan-settings", json={"overrides": {"not_a_real_setting": 1}})

    assert resp.status_code == 400


@patch("web.app.resolve_check_balances_workers")
@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_check_balances_job_dispatch_uses_resolved_worker_counts(mock_pipeline, mock_hidden, mock_resolve, client, tmp_path):
    """The real point of this story's settings plumbing: a custom worker
    count set via the settings route must actually reach the next
    check-balances job dispatch, not just round-trip through get/set."""
    mock_hidden.return_value = []
    mock_resolve.return_value = (7, 3)

    def fake_find(input_dir, out_dir, index_db_path=None, checkpoint_path=None, progress_callback=None, excludes=None, walk_threads=None, processes=None):
        return {"output_dir": out_dir, "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    mock_pipeline.find.side_effect = fake_find
    mock_pipeline.check_balances.return_value = {}

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    balances_resp = client.post(f"/scan/{job_id}/check-balances", follow_redirects=False)
    balances_job_id = balances_resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    assert mock_pipeline.check_balances.call_args.kwargs["global_max_workers"] == 7
    assert mock_pipeline.check_balances.call_args.kwargs["per_coin_max_concurrency"] == 3


@patch("web.app.resolve_check_balances_workers")
@patch("web.app.check_wallet_balances")
def test_check_balances_selected_job_dispatch_uses_resolved_worker_counts(mock_check, mock_resolve, client, tmp_path):
    mock_resolve.return_value = (11, 4)
    mock_check.return_value = {}

    job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})

    selected_path = str(tmp_path / "a.dat")
    balances_resp = client.post(
        f"/scan/{job_id}/check-balances-selected", data={"files": selected_path}, follow_redirects=False
    )
    balances_job_id = balances_resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    assert mock_check.call_args.kwargs["global_max_workers"] == 11
    assert mock_check.call_args.kwargs["per_coin_max_concurrency"] == 4


@patch("web.app.resolve_analyze_processes")
@patch("web.app.resolve_search_walk_threads")
@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_find_job_dispatch_uses_resolved_walk_threads_and_processes(
    mock_pipeline, mock_hidden, mock_resolve_walk_threads, mock_resolve_processes, client, tmp_path
):
    """sse-06's generalization of sse-02's plumbing: a custom
    search_walk_threads/analyze_processes value set via the settings
    route must actually reach the next find (search+analyze) job
    dispatch, not just round-trip through get/set."""
    mock_hidden.return_value = []
    mock_resolve_walk_threads.return_value = 2
    mock_resolve_processes.return_value = 6
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    assert mock_pipeline.find.call_args.kwargs["walk_threads"] == 2
    assert mock_pipeline.find.call_args.kwargs["processes"] == 6


def test_get_scan_settings_route_includes_live_auto_computed_values(client):
    """sse-06 acceptance criterion: a fresh install with no settings
    configured must show mode=auto with live-computed values for all
    four fields, based on the current machine's os.cpu_count() -- not
    just the persisted mode/overrides shape."""
    resp = client.get("/api/scan-settings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] == "auto"
    auto = body["auto"]
    assert set(auto) == {
        "search_walk_threads",
        "analyze_processes",
        "check_balances_global_workers",
        "check_balances_per_coin_concurrency",
    }
    assert all(isinstance(v, int) for v in auto.values())
