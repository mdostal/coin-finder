import json
import re
from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _graph_data_json(resp):
    match = re.search(rb'<script type="application/json" id="graph-data">(.*?)</script>', resp.data, re.S)
    assert match, "graph-data script tag not found in response"
    return json.loads(match.group(1))


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_renders_combined_nodes(mock_data, client):
    mock_data.return_value = {
        "nodes": {
            "1a": {"confidence": "seed", "generation": 0, "balance": 0.5, "last_activity_timestamp": None, "dormant_years": None, "run_id": 1},
            "1b": {"confidence": "seed", "generation": 0, "balance": None, "last_activity_timestamp": None, "dormant_years": None, "run_id": 2},
        },
        "edges": [],
    }

    resp = client.get("/findings/group-view/graph?run_ids=1,2")

    assert resp.status_code == 200
    mock_data.assert_called_once_with([1, 2])
    assert b'id="graph-data"' in resp.data
    assert b"1a" in resp.data
    assert b"1b" in resp.data
    assert b'id="cy"' in resp.data
    assert b"cytoscape.min.js" in resp.data
    assert b"graph.js" in resp.data
    # cytoscape.min.js must load before graph.js references the global it defines
    assert resp.data.index(b"cytoscape.min.js") < resp.data.index(b'src="/static/graph.js"')


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_single_run_id_works(mock_data, client):
    mock_data.return_value = {
        "nodes": {"1a": {"confidence": "seed", "generation": 0, "balance": 0.5, "last_activity_timestamp": None, "dormant_years": None, "run_id": 1}},
        "edges": [],
    }

    resp = client.get("/findings/group-view/graph?run_ids=1")

    assert resp.status_code == 200
    mock_data.assert_called_once_with([1])


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_derives_discovered_via_from_edges(mock_data, client):
    mock_data.return_value = {
        "nodes": {
            "1a": {"confidence": "seed", "generation": 0, "balance": None, "last_activity_timestamp": None, "dormant_years": None, "run_id": 1},
            "1b": {"confidence": "co-spend", "generation": 1, "balance": None, "last_activity_timestamp": None, "dormant_years": None, "run_id": 1},
        },
        "edges": [{"run_id": 1, "from_address": "1a", "to_address": "1b", "edge_type": "co-spend", "txid": "tx1"}],
    }

    resp = client.get("/findings/group-view/graph?run_ids=1")

    data = _graph_data_json(resp)
    assert data["1b"]["discovered_via"] == "1a"
    assert data["1a"]["discovered_via"] is None


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_drops_dangling_edge_endpoint_not_in_node_set(mock_data, client):
    """A run_edges row can reference an address that never made it into
    run_addresses (e.g. it hit the per-run 200-address discovery cap) --
    that must not be handed to Cytoscape as a broken edge reference."""
    mock_data.return_value = {
        "nodes": {"1a": {"confidence": "seed", "generation": 0, "balance": None, "last_activity_timestamp": None, "dormant_years": None, "run_id": 1}},
        "edges": [{"run_id": 1, "from_address": "1not-a-node", "to_address": "1a", "edge_type": "co-spend", "txid": "tx1"}],
    }

    resp = client.get("/findings/group-view/graph?run_ids=1")

    assert resp.status_code == 200
    data = _graph_data_json(resp)
    assert data["1a"]["discovered_via"] is None


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_missing_run_ids_fails_clearly(mock_data, client):
    resp = client.get("/findings/group-view/graph")

    assert resp.status_code == 400
    mock_data.assert_not_called()


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_empty_run_ids_fails_clearly(mock_data, client):
    resp = client.get("/findings/group-view/graph?run_ids=")

    assert resp.status_code == 400
    mock_data.assert_not_called()


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_non_integer_run_ids_fails_clearly(mock_data, client):
    resp = client.get("/findings/group-view/graph?run_ids=abc,2")

    assert resp.status_code == 400
    mock_data.assert_not_called()


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_no_matching_saved_data_fails_clearly(mock_data, client):
    mock_data.return_value = {"nodes": {}, "edges": []}

    resp = client.get("/findings/group-view/graph?run_ids=999")

    assert resp.status_code == 400


@patch("web.app.get_runs_graph_data")
def test_group_view_graph_error_page_is_not_silently_empty(mock_data, client):
    """A failing request must show a clear error, never a 200 with an
    empty-looking graph page."""
    resp = client.get("/findings/group-view/graph?run_ids=not-a-number")

    assert resp.status_code == 400
    assert b'id="graph-data"' not in resp.data
    mock_data.assert_not_called()
