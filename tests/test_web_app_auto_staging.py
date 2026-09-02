"""
Coverage for scpi-01's auto-staging hook: the 3 record_finding() call
sites that pass a real source_path (_run_scan_wallet_dat_job,
_run_check_balances_job, _run_check_balances_selected_job) must stage and
index the backing file exactly once per distinct real file; the other 3
call sites (crawl, fork-coin check, quick lookup) never have a real file
and must never stage or index anything.

tests/conftest.py's autouse fixture already mocks web.app.record_finding
and web.app.stage_and_index for every test (so nothing here can leak a
real file copy or db row) -- each test below re-patches stage_and_index
locally to assert on how it was called.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from web import app as app_module


@patch("web.app.stage_and_index")
@patch("web.app.check_addresses_balances")
@patch("web.app.scan_wallet_for_addresses")
def test_scan_wallet_dat_job_stages_real_source_path_once(mock_scan, mock_check, mock_stage, tmp_path):
    wallet_path = tmp_path / "wallet.dat"
    wallet_path.write_bytes(b"fake wallet contents")

    mock_scan.return_value = {"addresses": ["1aaa", "1bbb"], "encrypted_key_count": 0}
    mock_check.return_value = {
        "results": [
            {"address": "1aaa", "balance": 0.5},
            {"address": "1bbb", "balance": None},
        ],
        "total_available": 2,
    }

    app_module._run_scan_wallet_dat_job(str(wallet_path), "job-1")

    # Two findings share one real file -- staged once, not twice.
    mock_stage.assert_called_once_with(
        str(wallet_path), "Bitcoin", "1aaa", "scan_wallet_dat", staging_dir=app_module.DEFAULT_STAGING_DIR
    )


@patch("web.app.stage_and_index")
@patch("web.app.check_addresses_balances")
@patch("web.app.scan_wallet_for_addresses")
def test_scan_wallet_dat_job_does_not_stage_a_nonexistent_source_path(mock_scan, mock_check, mock_stage, tmp_path):
    missing_path = str(tmp_path / "does_not_exist.dat")

    mock_scan.return_value = {"addresses": ["1aaa"], "encrypted_key_count": 0}
    mock_check.return_value = {"results": [{"address": "1aaa", "balance": 0.5}], "total_available": 1}

    app_module._run_scan_wallet_dat_job(missing_path, "job-1")

    mock_stage.assert_not_called()


def _write_balances_json(output_dir, balances):
    checks_dir = Path(output_dir) / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    with open(checks_dir / "wallet_balances.json", "w") as f:
        json.dump(balances, f)


@patch("web.app.stage_and_index")
@patch("web.app.resolve_check_balances_workers", return_value=(1, 1))
@patch("web.app.run_pipeline")
def test_check_balances_job_stages_each_distinct_file_once(mock_run_pipeline, mock_workers, mock_stage, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    file_a = tmp_path / "a.dat"
    file_a.write_bytes(b"file a")
    file_b = tmp_path / "b.dat"
    file_b.write_bytes(b"file b")

    # file_a backs two different findings (two coins) -- must stage once.
    _write_balances_json(
        output_dir,
        {
            str(file_a): {"Bitcoin": {"1aaa": 0.1}, "Litecoin": {"Laaa": 0.2}},
            str(file_b): {"Bitcoin": {"1bbb": 0.3}},
        },
    )

    app_module._run_check_balances_job(str(output_dir), "job-1")

    staged_sources = [call.args[0] for call in mock_stage.call_args_list]
    assert staged_sources.count(str(file_a)) == 1
    assert staged_sources.count(str(file_b)) == 1
    assert mock_stage.call_count == 2
    for call in mock_stage.call_args_list:
        assert call.kwargs["staging_dir"] == app_module.DEFAULT_STAGING_DIR


@patch("web.app.stage_and_index")
@patch("web.app.resolve_check_balances_workers", return_value=(1, 1))
@patch("web.app.run_pipeline")
def test_check_balances_job_does_not_stage_missing_files(mock_run_pipeline, mock_workers, mock_stage, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    missing_file = tmp_path / "gone.dat"  # never created

    _write_balances_json(output_dir, {str(missing_file): {"Bitcoin": {"1aaa": 0.1}}})

    app_module._run_check_balances_job(str(output_dir), "job-1")

    mock_stage.assert_not_called()


@patch("web.app.stage_and_index")
@patch("web.app.check_wallet_balances")
@patch("web.app.resolve_check_balances_workers", return_value=(1, 1))
def test_check_balances_selected_job_stages_each_distinct_file_once(mock_workers, mock_check, mock_stage, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "checks").mkdir()

    file_a = tmp_path / "a.dat"
    file_a.write_bytes(b"file a")

    analysis = {str(file_a): {"some": "analysis"}}
    with open(output_dir / "checks" / "wallet_analysis.json", "w") as f:
        json.dump(analysis, f)

    def fake_check_wallet_balances(input_path, output_path, **kwargs):
        with open(output_path, "w") as f:
            json.dump(
                {str(file_a): {"Bitcoin": {"1aaa": 0.1}, "Litecoin": {"Laaa": 0.2}}},
                f,
            )

    mock_check.side_effect = fake_check_wallet_balances

    app_module._run_check_balances_selected_job(str(output_dir), [str(file_a)], "job-1")

    staged_sources = [call.args[0] for call in mock_stage.call_args_list]
    assert staged_sources == [str(file_a)]
    assert mock_stage.call_count == 1


@patch("web.app.record_finding")
@patch("web.app.stage_and_index")
@patch("web.app.resolve_check_balances_workers", return_value=(1, 1))
@patch("web.app.run_pipeline")
def test_check_balances_job_wires_finding_callback_to_record_finding(
    mock_run_pipeline, mock_workers, mock_stage, mock_record_finding, tmp_path
):
    """
    ibc-01: _run_check_balances_job must pass run_pipeline.check_balances()
    a finding_callback that actually persists to findings.db via
    record_finding(), the same call the end-of-run pass below already
    makes -- run_pipeline itself is fully mocked here, so the assertion is
    on the callback web/app.py handed it, invoked exactly as
    check_wallet_balances() would invoke it for a real confirmed balance.
    """
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    # run_pipeline is fully mocked, so its check_balances() never actually
    # runs check_wallet_balances() or writes wallet_balances.json -- write
    # it directly so the (unrelated) end-of-run record_finding() pass has
    # something to read, keeping this test's only assertion on the
    # finding_callback kwarg itself.
    _write_balances_json(output_dir, {})

    app_module._run_check_balances_job(str(output_dir), "job-1")

    finding_callback = mock_run_pipeline.check_balances.call_args.kwargs["finding_callback"]
    mock_record_finding.reset_mock()  # drop any end-of-run calls from the empty balances write above

    finding_callback("walletA.dat", "Bitcoin", "1aaa", 0.5)

    mock_record_finding.assert_called_once_with(
        "Bitcoin", "1aaa", 0.5, source_path="walletA.dat", source_label="scan"
    )


@patch("web.app.record_finding")
@patch("web.app.stage_and_index")
@patch("web.app.check_wallet_balances")
@patch("web.app.resolve_check_balances_workers", return_value=(1, 1))
def test_check_balances_selected_job_wires_finding_callback_to_record_finding(
    mock_workers, mock_check, mock_stage, mock_record_finding, tmp_path
):
    """Same wiring as _run_check_balances_job's own test above, for the
    selected-files variant, which calls check_wallet_balances() directly
    rather than through run_pipeline.check_balances()."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "checks").mkdir()

    file_a = tmp_path / "a.dat"
    file_a.write_bytes(b"file a")
    analysis = {str(file_a): {"some": "analysis"}}
    with open(output_dir / "checks" / "wallet_analysis.json", "w") as f:
        json.dump(analysis, f)

    def fake_check_wallet_balances(input_path, output_path, **kwargs):
        with open(output_path, "w") as f:
            json.dump({}, f)

    mock_check.side_effect = fake_check_wallet_balances

    app_module._run_check_balances_selected_job(str(output_dir), [str(file_a)], "job-1")

    finding_callback = mock_check.call_args.kwargs["finding_callback"]
    mock_record_finding.reset_mock()

    finding_callback(str(file_a), "Bitcoin", "1aaa", 0.5)

    mock_record_finding.assert_called_once_with(
        "Bitcoin", "1aaa", 0.5, source_path=str(file_a), source_label="scan"
    )


@patch("web.app.stage_and_index")
@patch("web.app.crawl_wallet_cluster")
@patch("web.app.load_seed_addresses")
def test_crawl_job_never_stages_or_indexes_anything(mock_load_seeds, mock_crawl, mock_stage, tmp_path):
    mock_load_seeds.return_value = ["1aaa"]
    mock_crawl.return_value = {"1aaa": {"balance": 0.5, "confidence": "seed", "generation": 0}}

    app_module._run_crawl_job(["1aaa"], job_id="job-1")

    mock_stage.assert_not_called()


@patch("web.app.stage_and_index")
@patch("web.app.check_fork_coins_for_addresses")
def test_fork_coins_job_never_stages_or_indexes_anything(mock_check_fork, mock_stage):
    mock_check_fork.return_value = {"1aaa": {"Litecoin": 0.1}}

    app_module._run_fork_coins_job(["1aaa"])

    mock_stage.assert_not_called()


@patch("web.app.stage_and_index")
@patch("web.app._check_balance_with_retries")
@patch("web.app.load_service")
def test_quick_lookup_job_never_stages_or_indexes_anything(mock_load_service, mock_check_balance, mock_stage):
    mock_load_service.return_value = object()
    mock_check_balance.return_value = 0.1

    app_module._run_quick_lookup_job("Bitcoin", "1aaa")

    mock_stage.assert_not_called()
