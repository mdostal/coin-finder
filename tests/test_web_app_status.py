from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.check_network_status")
def test_api_status_reports_network_status(mock_status, client):
    mock_status.return_value = "OFFLINE"
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["network_status"] == "OFFLINE"


@patch("web.app.check_network_status")
def test_api_status_includes_feature_availability_notes(mock_status, client):
    mock_status.return_value = "ONLINE"
    resp = client.get("/api/status")
    data = resp.get_json()
    assert "features" in data
    assert isinstance(data["features"], dict)
