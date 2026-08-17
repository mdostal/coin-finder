import re
import time
from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_terminal(client, job_id, timeout_iterations=100):
    job = None
    for _ in range(timeout_iterations):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


def _job_id_from_redirect(resp):
    return resp.headers["Location"].rstrip("/").split("/")[-1]


@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings", return_value=[{"coin": "Bitcoin", "address": "1abc", "source_path": "/w.dat", "status": "new"}])
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_form_shows_offline_status_and_known_wallets(mock_status, mock_findings, mock_vault, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value[0]["source_path"] = str(wallet_file)

    resp = client.get("/auto-unlock")

    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data
    assert str(wallet_file).encode() in resp.data


@patch("web.app.list_vault_entries")
@patch("web.app.list_findings", return_value=[])
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_form_never_calls_list_vault_entries(mock_status, mock_findings, mock_vault, client):
    """
    Regression test for a real bug hit live: list_vault_entries() can take
    10-15s from this app's own subprocess context (same root cause as the
    0.32.2 wizard-page fix), and this app's server is single-threaded --
    calling it inline on this page's GET would block the whole app for
    that long on every page view. The real check still happens in
    auto_unlock_submit() (POST), which is a less frequent action.
    """
    client.get("/auto-unlock")
    mock_vault.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.check_network_status", return_value="ONLINE")
def test_post_auto_unlock_refused_when_online(mock_status, mock_run_unlock, client):
    resp = client.post("/auto-unlock", data={})
    assert resp.status_code == 409
    mock_run_unlock.assert_not_called()


@patch("web.app.list_vault_entries", return_value=[])
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_post_auto_unlock_requires_at_least_one_vault_entry(mock_status, mock_vault, client):
    resp = client.post("/auto-unlock", data={})
    assert resp.status_code == 400
    assert b"vault" in resp.data.lower()


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_tries_every_known_wallet_against_vault(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Bitcoin", "address": "1b", "source_path": str(wallet_b), "status": "archived"},
    ]
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)

    assert job["status"] == "done"
    assert mock_run_unlock.call_count == 2
    tried_paths = {c.args[0] for c in mock_run_unlock.call_args_list}
    assert tried_paths == {str(wallet_a), str(wallet_b)}
    # every call reuses the same shared candidates file
    candidate_paths = {c.args[1] for c in mock_run_unlock.call_args_list}
    assert len(candidate_paths) == 1


@patch("web.app.run_exodus_unlock")
@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_routes_seco_files_to_exodus_runner(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, mock_run_exodus, client, tmp_path):
    seco_file = tmp_path / "seed.seco"
    seco_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(seco_file), "status": "new"}]
    mock_run_exodus.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_run_exodus.assert_called_once()
    mock_run_unlock.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_result_delivered_once_then_gone(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_file), "status": "new"}]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    assert "hunter2" not in str(job)  # plain status/poll path never carries the secret

    first_view = client.get(f"/auto-unlock/result/{job_id}")
    assert first_view.status_code == 200
    assert b"password-1" in first_view.data  # matched label shown, for context
    assert b"hunter2!!" in first_view.data  # AND the real matched value -- the actual ask

    second_view = client.get(f"/auto-unlock/result/{job_id}")
    assert second_view.status_code == 404  # once-only guarantee unchanged


@patch("web.app.check_network_status", return_value="OFFLINE")
@patch("web.app.list_findings")
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.run_unlock")
def test_auto_unlock_result_shows_no_match_not_a_blank_cell(mock_run_unlock, mock_resolve, mock_vault, mock_findings, mock_status, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_file), "status": "new"}]
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/auto-unlock/result/{job_id}")
    assert view.status_code == 200
    assert b"no match" in view.data.lower()


def test_auto_unlock_result_unknown_job_is_404(client):
    resp = client.get("/auto-unlock/result/does-not-exist")
    assert resp.status_code == 404


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_result_masks_password_by_default_with_eye_toggle(
    mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path
):
    """
    ccu-01: the Password column must not paint the real secret as its
    default visible text -- it renders behind a masked placeholder with
    an eye-toggle button, and the real value is present in the page's
    initial HTML (a data attribute) so the client-side reveal needs no
    second request.
    """
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_file), "status": "new"}]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/auto-unlock/result/{job_id}")
    assert view.status_code == 200
    html = view.data.decode()

    # The real value is still in the page's initial HTML (no second
    # request needed to reveal it) -- but as a data attribute, not as
    # the default visible text.
    assert 'data-secret="hunter2!!"' in html

    # The visible text content of the masked element must NOT be the
    # raw secret -- it's a bullet/dot placeholder instead.
    match = re.search(r'<code class="secret-mask"[^>]*>([^<]*)</code>', html)
    assert match is not None, "expected a masked secret-mask element in the Password column"
    visible_text = match.group(1)
    assert "hunter2!!" not in visible_text
    assert visible_text.strip() != ""

    # An eye-toggle button must be present next to it to reveal in place.
    assert 'class="secret-reveal-btn' in html


@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_form_scopes_to_one_wallet_via_query_param(mock_status, mock_findings, mock_vault, client, tmp_path):
    """
    Regression test for the real, repeated ask: click a specific found
    wallet's "Try unlock" action, land on a page scoped to just that
    wallet -- not the full list requiring you to already know its path.
    """
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Bitcoin", "address": "1b", "source_path": str(wallet_b), "status": "new"},
    ]

    resp = client.get(f"/auto-unlock?wallet_path={str(wallet_a)}")

    assert resp.status_code == 200
    assert str(wallet_a).encode() in resp.data
    assert str(wallet_b).encode() not in resp.data


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_submit_scopes_to_one_wallet_via_hidden_field(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Bitcoin", "address": "1b", "source_path": str(wallet_b), "status": "new"},
    ]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)

    resp = client.post("/auto-unlock", data={"wallet_path": str(wallet_a)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_run_unlock.assert_called_once()
    assert mock_run_unlock.call_args[0][0] == str(wallet_a)


@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_form_scopes_to_multiple_wallets_via_repeated_query_param(mock_status, mock_findings, mock_vault, client, tmp_path):
    """
    The bulk "Try unlock selected" action on Findings reuses this exact
    scoping mechanism, just with more than one wallet_path -- repeated
    query params, same as a single one.
    """
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    wallet_c = tmp_path / "c.dat"
    wallet_c.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Ethereum", "address": "0xb", "source_path": str(wallet_b), "status": "new"},
        {"coin": "Bitcoin", "address": "1c", "source_path": str(wallet_c), "status": "new"},
    ]

    resp = client.get(f"/auto-unlock?wallet_path={wallet_a}&wallet_path={wallet_b}")

    assert resp.status_code == 200
    assert str(wallet_a).encode() in resp.data
    assert str(wallet_b).encode() in resp.data
    assert str(wallet_c).encode() not in resp.data


@patch("web.app.run_exodus_unlock")
@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_submit_scopes_to_multiple_wallets_via_repeated_hidden_field(
    mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, mock_run_exodus, client, tmp_path
):
    """
    The bulk Try-unlock action submits multiple wallet_path hidden fields
    (one per selected finding with a source_path) -- the job must run
    against exactly that set, not every known wallet.
    """
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    wallet_c = tmp_path / "c.dat"
    wallet_c.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Ethereum", "address": "0xb", "source_path": str(wallet_b), "status": "new"},
        {"coin": "Bitcoin", "address": "1c", "source_path": str(wallet_c), "status": "new"},
    ]
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={"wallet_path": [str(wallet_a), str(wallet_b)]}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    assert mock_run_unlock.call_count == 2
    tried_paths = {c.args[0] for c in mock_run_unlock.call_args_list}
    assert tried_paths == {str(wallet_a), str(wallet_b)}
    mock_run_exodus.assert_not_called()


@patch("web.app.list_findings")
def test_findings_page_bulk_try_unlock_links_to_auto_unlock_confirm(mock_findings, client):
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": "/real/wallet.dat", "status": "new", "balance": 0.0, "watched": 0, "watch_note": ""},
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'id="bulk-try-unlock"' in resp.data
    assert b'data-unlock-confirm-url="/auto-unlock/confirm"' in resp.data
    assert b'data-source-path="/real/wallet.dat"' in resp.data


@patch("web.app.list_findings")
def test_auto_unlock_confirm_post_scopes_to_submitted_wallet_paths(mock_findings, client):
    """
    Regression test for a real bug hit live: bulk 'Try unlock selected'
    against a large selection built a GET URL with one repeated
    ?wallet_path=... query param per finding, which exceeded the
    server's URI-length limit (414 URI Too Long) before Flask ever saw
    the request. The confirm step must travel via POST body instead,
    which has no comparable practical size ceiling.
    """
    mock_findings.return_value = []
    with patch("web.app._known_wallet_paths", return_value={"/a/wallet.dat", "/b/wallet.dat", "/c/wallet.dat"}):
        resp = client.post("/auto-unlock/confirm", data=MultiDict([
            ("wallet_path", "/a/wallet.dat"),
            ("wallet_path", "/b/wallet.dat"),
            ("wallet_path", "/not-known.dat"),
        ]))

    assert resp.status_code == 200
    assert b"/a/wallet.dat" in resp.data
    assert b"/b/wallet.dat" in resp.data
    assert b"/not-known.dat" not in resp.data


def test_auto_unlock_confirm_get_is_not_registered(client):
    # /auto-unlock/confirm is POST-only -- the GET confirm page is still
    # the original /auto-unlock route, unchanged.
    resp = client.get("/auto-unlock/confirm")
    assert resp.status_code == 405


@patch("web.app.list_findings")
def test_findings_page_shows_try_unlock_action_for_wallets_with_source_path(mock_findings, client):
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": "/real/wallet.dat", "status": "new", "balance": 0.0, "watched": 0, "watch_note": ""},
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b"/auto-unlock?wallet_path=" in resp.data
