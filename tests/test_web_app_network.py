import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_network_page_loads(client):
    resp = client.get("/network")
    assert resp.status_code == 200
    assert b"8.8.8.8" in resp.data
