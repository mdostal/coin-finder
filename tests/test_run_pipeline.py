import json
import os
from unittest.mock import patch

import run_pipeline


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

        mock_build_graph.return_value = graph
        mock_render_report.return_value = report_text

        def fake_check(input_file, output_file):
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
