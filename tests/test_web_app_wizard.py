from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_wizard_start_page_loads(client):
    resp = client.get("/wizard")
    assert resp.status_code == 200


def test_wizard_choose_local_hands_off_to_scan_form(client):
    resp = client.post("/wizard/choose", data={"target_type": "local"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_wizard_choose_volume_hands_off_to_targets_page(client):
    resp = client.post("/wizard/choose", data={"target_type": "volume"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/targets"


def test_wizard_choose_gdrive_hands_off_to_cloud_explainer(client):
    resp = client.post("/wizard/choose", data={"target_type": "gdrive"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/cloud" in resp.headers["Location"]
    assert "kind=gdrive" in resp.headers["Location"]


@patch("web.app.ai_assist.has_api_key", return_value=False)
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_wizard_cloud_page_surfaces_install_step_when_rclone_not_set_up(mock_installed, mock_remotes, mock_ai_key, client):
    mock_installed.return_value = False
    mock_remotes.return_value = []

    resp = client.get("/wizard/cloud?kind=gdrive")

    assert resp.status_code == 200
    assert b"Install now" in resp.data
    assert b"/mounts/install-rclone" in resp.data


@patch("web.app.ai_assist.has_api_key", return_value=False)
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_wizard_cloud_page_links_to_mounts_when_remotes_exist(mock_installed, mock_remotes, mock_ai_key, client):
    mock_installed.return_value = True
    mock_remotes.return_value = ["gdrive"]

    resp = client.get("/wizard/cloud?kind=gdrive")

    assert resp.status_code == 200
    assert b"/mounts" in resp.data


@patch("web.app.ai_assist.has_api_key", return_value=False)
def test_wizard_never_claims_mount_success_itself(mock_ai_key, client):
    """The wizard's cloud page must never render a hardcoded success claim --
    only /mounts (which does the real is_mounted() check) may."""
    resp = client.get("/wizard/cloud?kind=gdrive")
    assert b"Drive mounted!" not in resp.data
    assert b"Successfully mounted" not in resp.data


@patch("web.app.ai_assist.has_api_key", return_value=False)
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_wizard_cloud_page_offers_connect_form_not_a_terminal_instruction(mock_installed, mock_remotes, mock_ai_key, client):
    """Direct regression test for the reported bug: this page must not tell
    the user to go run `rclone config` in a terminal -- it must offer a
    real in-app form that POSTs to the connect route."""
    mock_installed.return_value = True
    mock_remotes.return_value = []

    resp = client.get("/wizard/cloud?kind=gdrive")

    assert resp.status_code == 200
    assert b"/wizard/cloud/connect" in resp.data
    assert b"<pre>rclone config</pre>" not in resp.data


@patch("web.app.start_job")
@patch("web.app.create_job")
def test_wizard_cloud_connect_starts_a_background_job(mock_create_job, mock_start_job, client):
    mock_create_job.return_value = "job-123"

    resp = client.post(
        "/wizard/cloud/connect",
        data={"kind": "gdrive", "remote_name": "gdrive", "scope": "drive.readonly"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/item-result/job-123"
    mock_create_job.assert_called_once_with(kind="connect-remote", label="gdrive")
    mock_start_job.assert_called_once()


@patch("web.app.ai_assist.has_api_key", return_value=False)
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_wizard_cloud_connect_requires_a_name(mock_installed, mock_remotes, mock_ai_key, client):
    mock_installed.return_value = True
    mock_remotes.return_value = []

    resp = client.post("/wizard/cloud/connect", data={"kind": "gdrive"})

    assert resp.status_code == 400
    assert b"Enter a name" in resp.data


@patch("web.app.ai_assist.has_api_key")
def test_ai_assist_status_reports_whether_a_key_is_saved(mock_has_key, client):
    mock_has_key.return_value = True
    resp = client.get("/ai-assist/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"has_key": True}


@patch("web.app.ai_assist.ask")
def test_ai_assist_ask_returns_answer_as_json(mock_ask, client):
    mock_ask.return_value = "Use drive.readonly."

    resp = client.post("/ai-assist/ask", json={"question": "what scope?"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "answer": "Use drive.readonly."}
    mock_ask.assert_called_once_with("what scope?")


def test_ai_assist_ask_requires_a_question(client):
    resp = client.post("/ai-assist/ask", json={"question": "  "})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


@patch("web.app.ai_assist.ask")
def test_ai_assist_ask_surfaces_runtime_errors_as_json(mock_ask, client):
    mock_ask.side_effect = RuntimeError("No API key saved yet -- add one below first.")

    resp = client.post("/ai-assist/ask", json={"question": "what scope?"})

    assert resp.status_code == 400
    assert resp.get_json() == {"ok": False, "error": "No API key saved yet -- add one below first."}


@patch("web.app.ai_assist.set_api_key")
def test_ai_assist_key_saves_and_redirects_back_to_wizard(mock_set_key, client):
    resp = client.post("/ai-assist/key", data={"kind": "gdrive", "api_key": "sk-ant-abc"}, follow_redirects=False)

    assert resp.status_code == 302
    assert "/wizard/cloud" in resp.headers["Location"]
    mock_set_key.assert_called_once_with("sk-ant-abc")


@patch("web.app.ai_assist.set_api_key")
def test_ai_assist_key_ignores_blank_submission(mock_set_key, client):
    client.post("/ai-assist/key", data={"kind": "gdrive", "api_key": "  "})
    mock_set_key.assert_not_called()


@patch("web.app.ai_assist.clear_api_key")
def test_ai_assist_key_clear_revokes_and_redirects(mock_clear_key, client):
    resp = client.post("/ai-assist/key/clear", data={"kind": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 302
    assert "/wizard/cloud" in resp.headers["Location"]
    mock_clear_key.assert_called_once()
