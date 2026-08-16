import json
import os
from unittest.mock import patch

import run_pipeline


def _fake_analyze(analysis_data):
    def _write(input_file, output_file, index_db_path=None):
        with open(output_file, "w") as f:
            json.dump(analysis_data, f)

    return _write


def test_pipeline_wires_relationship_graph_from_scan_output(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    scan_data = {"walletA.dat": {"Bitcoin": {"1abc": 0.5}}}
    graph = {"nodes": {}, "edges": {}, "signals": {}}
    report_text = "# Wallet Relationship Report\n"

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances") as mock_check, \
         patch("run_pipeline.filter_wallet_balances") as mock_filter, \
         patch("run_pipeline.build_relationship_graph") as mock_build_graph, \
         patch("run_pipeline.render_graph_report") as mock_render_report:

        mock_analyze.side_effect = _fake_analyze({"walletA.dat": {"Bitcoin": ["1abc"]}})
        mock_build_graph.return_value = graph
        mock_render_report.return_value = report_text

        def fake_check(input_file, output_file, progress_callback=None, checkpoint_path=None):
            with open(output_file, "w") as f:
                json.dump(scan_data, f)

        mock_check.side_effect = fake_check

        run_pipeline.main(str(input_dir), str(output_dir))

    mock_build_graph.assert_called_once_with(scan_data)

    relationships_json = output_dir / "checks" / "wallet_relationships.json"
    relationships_md = output_dir / "wallet_relationships.md"
    assert relationships_json.exists()
    assert relationships_md.exists()
    assert json.loads(relationships_json.read_text()) == graph
    assert relationships_md.read_text() == report_text


def test_pipeline_forwards_progress_callback_to_check_wallet_balances(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    scan_data = {}

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances") as mock_check, \
         patch("run_pipeline.filter_wallet_balances"), \
         patch("run_pipeline.build_relationship_graph", return_value={"nodes": {}, "edges": {}, "signals": {}}), \
         patch("run_pipeline.render_graph_report", return_value=""):

        mock_analyze.side_effect = _fake_analyze({})

        def fake_check(input_file, output_file, progress_callback=None, checkpoint_path=None):
            with open(output_file, "w") as f:
                json.dump(scan_data, f)

        mock_check.side_effect = fake_check
        sentinel_callback = lambda current, total, message="": None

        run_pipeline.main(str(input_dir), str(output_dir), progress_callback=sentinel_callback)

    assert mock_check.call_args.kwargs["progress_callback"] is sentinel_callback


def test_find_returns_summary_without_checking_balances(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances") as mock_check:
        mock_analyze.side_effect = _fake_analyze(
            {"walletA.dat": {"Bitcoin": ["1abc", "1def"]}, "walletB.dat": {"Bitcoin": ["1ghi"], "Litecoin": ["Labc"]}}
        )

        summary = run_pipeline.find(str(input_dir), str(output_dir))

    mock_search.assert_called_once()
    mock_analyze.assert_called_once()
    mock_check.assert_not_called()
    assert summary == {
        "output_dir": str(output_dir),
        "files_found": 2,
        "coin_counts": {"Bitcoin": 3, "Litecoin": 1},
        "total_address_instances": 4,
        "files": [
            {"path": "walletA.dat", "coins": {"Bitcoin": ["1abc", "1def"]}},
            {"path": "walletB.dat", "coins": {"Bitcoin": ["1ghi"], "Litecoin": ["Labc"]}},
        ],
    }
    assert (output_dir / "checks" / "wallet_analysis.json").exists()


def test_find_sorts_files_by_total_address_count_descending(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances"):
        mock_analyze.side_effect = _fake_analyze(
            {
                "sparse.dat": {"Bitcoin": ["1a"]},
                "dense.dat": {"Bitcoin": ["1b", "1c"], "Litecoin": ["Lb", "Lc", "Ld"]},
                "medium.dat": {"Bitcoin": ["1d", "1e"]},
            }
        )

        summary = run_pipeline.find(str(input_dir), str(output_dir))

    paths_in_order = [f["path"] for f in summary["files"]]
    assert paths_in_order == ["dense.dat", "medium.dat", "sparse.dat"]


def test_find_files_summary_includes_the_actual_addresses_not_just_counts(tmp_path):
    """A caller (e.g. a selective graph/fork-coins action) needs the real
    addresses, not just how many were found -- same analysis dict is
    already in memory, no reason to only expose counts."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances"):
        mock_analyze.side_effect = _fake_analyze({"wallet.dat": {"Bitcoin": ["1abc", "1def"]}})

        summary = run_pipeline.find(str(input_dir), str(output_dir))

    assert summary["files"][0]["coins"]["Bitcoin"] == ["1abc", "1def"]


def test_find_files_summary_never_includes_a_zero_coin_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets") as mock_analyze, \
         patch("run_pipeline.check_wallet_balances"):
        mock_analyze.side_effect = _fake_analyze({"empty.dat": {}, "real.dat": {"Bitcoin": ["1a"]}})

        summary = run_pipeline.find(str(input_dir), str(output_dir))

    paths = [f["path"] for f in summary["files"]]
    assert paths == ["real.dat"]


def test_check_balances_requires_a_prior_find(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "checks").mkdir(parents=True)  # what a prior find() call would have left behind

    with patch("run_pipeline.check_wallet_balances") as mock_check, \
         patch("run_pipeline.filter_wallet_balances"), \
         patch("run_pipeline.build_relationship_graph", return_value={"nodes": {}, "edges": {}, "signals": {}}), \
         patch("run_pipeline.render_graph_report", return_value=""):
        mock_check.side_effect = lambda input_file, output_file, progress_callback=None, checkpoint_path=None: open(
            output_file, "w"
        ).write("{}")

        run_pipeline.check_balances(str(output_dir))

    mock_check.assert_called_once()
    called_analyze_input = mock_check.call_args[0][0]
    assert called_analyze_input == str(output_dir / "checks" / "wallet_analysis.json")
