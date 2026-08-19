import json
import os
from unittest.mock import patch

import run_pipeline


def _fake_analyze(analysis_data):
    def _write(input_file, output_file, index_db_path=None, progress_callback=None):
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


def test_find_threads_checkpoint_path_into_analyze_wallets_call(tmp_path):
    """sse-01: analyze_wallets previously never received checkpoint_path at
    all -- only search_for_wallets did. find() must now derive a sibling
    checkpoint file for analyze (not reuse search's own path, which gets
    deleted by search_for_wallets on clean completion) and thread it, and
    processes, through."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    checkpoint_path = tmp_path / "scan_checkpoint.db"

    def fake_analyze(input_file, output_file, index_db_path=None, progress_callback=None, checkpoint_path=None, processes=None):
        with open(output_file, "w") as f:
            json.dump({}, f)
        fake_analyze.received = {"checkpoint_path": checkpoint_path, "processes": processes}

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets", side_effect=fake_analyze), \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir), checkpoint_path=str(checkpoint_path), processes=4)

    assert fake_analyze.received["checkpoint_path"] == str(tmp_path / "analyze_checkpoint.db")
    assert fake_analyze.received["checkpoint_path"] != str(checkpoint_path)
    assert fake_analyze.received["processes"] == 4


def test_find_does_not_pass_checkpoint_path_or_processes_to_analyze_when_absent(tmp_path):
    """Existing callers that never pass checkpoint_path/processes to
    find() (every current caller) must see analyze_wallets invoked exactly
    as before this story -- no new kwargs at all -- so any existing mock
    with the old, narrower signature keeps working unchanged."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets"), \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})) as mock_analyze, \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir))

    mock_analyze.assert_called_once()
    assert "checkpoint_path" not in mock_analyze.call_args.kwargs
    assert "processes" not in mock_analyze.call_args.kwargs


def test_find_threads_walk_threads_into_search_for_wallets_call(tmp_path):
    """sse-06: find() must forward walk_threads through to
    search_for_wallets() unchanged, the same way processes already gets
    forwarded to analyze_wallets()."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})), \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir), walk_threads=5)

    assert mock_search.call_args.kwargs["walk_threads"] == 5


def test_find_does_not_pass_walk_threads_to_search_for_wallets_when_absent(tmp_path):
    """Existing callers that never pass walk_threads to find() must see
    search_for_wallets invoked exactly as before this story -- no new
    kwarg at all -- so search_for_wallets' own DEFAULT_WALK_THREADS
    default keeps applying unchanged."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})), \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir))

    assert "walk_threads" not in mock_search.call_args.kwargs


def test_find_forwards_progress_callback_with_stage_prefixes(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    def fake_search(start_path, output_file, checkpoint_path=None, progress_callback=None, excludes=None):
        progress_callback(3, None, "3 potential wallet(s) found so far — /a")
        with open(output_file, "w") as f:
            pass

    with patch("run_pipeline.search_for_wallets", side_effect=fake_search), \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})), \
         patch("run_pipeline.check_wallet_balances"):
        calls = []
        run_pipeline.find(str(input_dir), str(output_dir), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls[0] == (3, None, "Searching: 3 potential wallet(s) found so far — /a")


def test_find_does_not_pass_mount_health_check_to_search_when_absent(tmp_path):
    """
    sse-05: existing callers that never pass mount_health_check to find()
    (every current caller) must see search_for_wallets invoked exactly as
    before this story -- no new kwarg at all -- so any existing mock with
    the narrower pre-sse-05 signature keeps working unchanged."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})), \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir))

    mock_search.assert_called_once()
    assert "mount_health_check" not in mock_search.call_args.kwargs


def test_find_threads_mount_health_check_into_search_call_when_given(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    sentinel = lambda: True

    with patch("run_pipeline.search_for_wallets") as mock_search, \
         patch("run_pipeline.analyze_wallets", side_effect=_fake_analyze({})), \
         patch("run_pipeline.check_wallet_balances"):
        run_pipeline.find(str(input_dir), str(output_dir), mount_health_check=sentinel)

    assert mock_search.call_args.kwargs["mount_health_check"] is sentinel


def test_check_balances_does_not_pass_mount_health_check_when_absent(tmp_path):
    """Mirrors test_find_does_not_pass_mount_health_check_to_search_when_absent
    for check_balances()/check_wallet_balances()."""
    output_dir = tmp_path / "output"
    (output_dir / "checks").mkdir(parents=True)

    with patch("run_pipeline.check_wallet_balances") as mock_check, \
         patch("run_pipeline.filter_wallet_balances"), \
         patch("run_pipeline.build_relationship_graph", return_value={"nodes": {}, "edges": {}, "signals": {}}), \
         patch("run_pipeline.render_graph_report", return_value=""):
        mock_check.side_effect = lambda input_file, output_file, progress_callback=None, checkpoint_path=None: open(
            output_file, "w"
        ).write("{}")

        run_pipeline.check_balances(str(output_dir))

    mock_check.assert_called_once()
    assert "mount_health_check" not in mock_check.call_args.kwargs


def test_check_balances_threads_mount_health_check_into_check_wallet_balances_call(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "checks").mkdir(parents=True)
    sentinel = lambda: True

    with patch("run_pipeline.check_wallet_balances") as mock_check, \
         patch("run_pipeline.filter_wallet_balances"), \
         patch("run_pipeline.build_relationship_graph", return_value={"nodes": {}, "edges": {}, "signals": {}}), \
         patch("run_pipeline.render_graph_report", return_value=""):
        mock_check.side_effect = lambda input_file, output_file, **k: open(output_file, "w").write("{}")

        run_pipeline.check_balances(str(output_dir), mount_health_check=sentinel)

    assert mock_check.call_args.kwargs["mount_health_check"] is sentinel
