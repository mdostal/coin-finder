import io
import os
import re
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from web.app import create_app, _run_wordlist_crack_job


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_terminal(client, job_id, timeout_iterations=100):
    """Polls /api/jobs/<job_id> (the non-consuming status path) until terminal."""
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


def _post_crack(client, wallet_path, wordlist_bytes, allow_online=False, filename="wordlist.txt"):
    data = {
        "wallet_path": str(wallet_path),
        "wordlist": (io.BytesIO(wordlist_bytes), filename),
    }
    if allow_online:
        data["allow_online"] = "1"
    return client.post(
        "/wordlist-crack",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )


# --- form page ---------------------------------------------------------


@patch("web.app.check_network_status")
def test_wordlist_crack_form_shows_current_network_status(mock_status, client):
    mock_status.return_value = "OFFLINE"
    resp = client.get("/wordlist-crack")
    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data


# --- offline gate --------------------------------------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_post_wordlist_crack_refused_when_online(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "ONLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"guess1\nguess2\n")

    assert resp.status_code == 409
    mock_run_unlock.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_post_wordlist_crack_with_allow_online_checkbox_proceeds_while_online(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "ONLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"guess1\nguess2\n", allow_online=True)

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    assert mock_run_unlock.call_args.kwargs.get("allow_online") is True


def test_wordlist_crack_job_offline_gate_not_bypassed(tmp_path):
    """
    rtpc-01: the real proof the offline gate isn't bypassed by this new
    path -- calls the actual job function with tools/unlock_wallet.py's
    OWN check_network_status (not web.app's route-level pre-check) forced
    ONLINE, and confirms it refuses before ever invoking subprocess.
    """
    candidates_file = tmp_path / "wordlist.txt"
    candidates_file.write_text("guess1\nguess2\n")
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    with (
        patch("tools.unlock_wallet.check_network_status", return_value="ONLINE"),
        patch("tools.unlock_wallet.subprocess.run") as mock_subprocess_run,
    ):
        with pytest.raises(RuntimeError):
            _run_wordlist_crack_job(str(wallet_file), str(candidates_file), allow_online=False)
        mock_subprocess_run.assert_not_called()

    # cleaned up even though the gate refused to run at all
    assert not candidates_file.exists()


# --- validation ------------------------------------------------------------


def test_post_wordlist_crack_rejects_missing_wallet_file(client, tmp_path):
    with patch("web.app.check_network_status", return_value="OFFLINE"):
        resp = _post_crack(client, tmp_path / "nope.dat", b"guess1\n")
    assert resp.status_code == 400


@patch("web.app.check_network_status")
def test_post_wordlist_crack_rejects_missing_wordlist_file(mock_status, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/wordlist-crack",
        data={"wallet_path": str(wallet_file)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert b"wordlist" in resp.data.lower()


# --- match found / not found ------------------------------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_finds_real_password_in_uploaded_wordlist(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'correct-horse-battery-staple'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"wrong-1\ncorrect-horse-battery-staple\nwrong-2\n")
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    view = client.get(f"/wordlist-crack/review/{job_id}")
    assert view.status_code == 200
    assert b"correct-horse-battery-staple" in view.data


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_no_match_reported_clearly_not_as_error(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"wrong-1\nwrong-2\n")
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"  # not "error" -- a clean miss isn't a failure

    view = client.get(f"/wordlist-crack/review/{job_id}")
    assert view.status_code == 200
    assert b"no match" in view.data.lower()
    assert b"banner error" not in view.data


# --- secret=True / once-only ------------------------------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_result_not_visible_via_plain_status_endpoint(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'hunter2!!'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"hunter2!!\n")
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    # the plain polling path must never carry the secret result
    assert job["result"] is None
    assert "hunter2" not in str(job)


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_review_delivered_once_then_gone(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'hunter2!!'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"hunter2!!\n")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    first_view = client.get(f"/wordlist-crack/review/{job_id}")
    assert first_view.status_code == 200
    assert b"hunter2" in first_view.data

    second_view = client.get(f"/wordlist-crack/review/{job_id}")
    assert second_view.status_code == 404


def test_wordlist_crack_review_unknown_job_is_404(client):
    resp = client.get("/wordlist-crack/review/does-not-exist")
    assert resp.status_code == 404


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_review_masks_password_by_default_with_reveal_toggle(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'hunter2!!'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"hunter2!!\n")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/wordlist-crack/review/{job_id}")
    html = view.data.decode()

    assert 'data-secret="hunter2!!"' in html

    match = re.search(r'<code class="secret-mask"[^>]*>([^<]*)</code>', html)
    assert match is not None, "expected a masked secret-mask element"
    visible_text = match.group(1)
    assert "hunter2!!" not in visible_text
    assert visible_text.strip() != ""

    assert 'class="secret-reveal-btn' in html


# --- uploaded wordlist cleanup -----------------------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_uploaded_file_deleted_after_match_found(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'hunter2!!'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"hunter2!!\n")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    candidates_path = mock_run_unlock.call_args[0][1]
    assert not os.path.exists(candidates_path)


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_uploaded_file_deleted_after_no_match(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"wrong-1\nwrong-2\n")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    candidates_path = mock_run_unlock.call_args[0][1]
    assert not os.path.exists(candidates_path)


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_uploaded_file_deleted_when_run_unlock_raises(mock_status, mock_run_unlock, client, tmp_path):
    """
    Explicit failure-path cleanup test -- a run_unlock exception (offline
    gate refusal, vendor script missing, whatever) must not leak the
    uploaded wordlist file on disk.
    """
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.side_effect = RuntimeError("boom")
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"wrong-1\nwrong-2\n")
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "error"

    candidates_path = mock_run_unlock.call_args[0][1]
    assert not os.path.exists(candidates_path)


def test_run_wordlist_crack_job_deletes_file_directly_on_exception(tmp_path):
    """Unit-level version of the same cleanup guarantee, no Flask/job-thread involved."""
    candidates_file = tmp_path / "wordlist.txt"
    candidates_file.write_text("wrong-1\nwrong-2\n")
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    with patch("web.app.run_unlock", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            _run_wordlist_crack_job(str(wallet_file), str(candidates_file), allow_online=True)

    assert not candidates_file.exists()


# --- never logs the wordlist's contents -------------------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_never_logs_uploaded_wordlist_contents(mock_status, mock_run_unlock, client, tmp_path, caplog):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    sentinel = "SUPER-SECRET-CANDIDATE-PATTERN-XYZ"
    with caplog.at_level("DEBUG"):
        resp = _post_crack(client, wallet_file, f"wrong-1\n{sentinel}\nwrong-2\n".encode())
        job_id = _job_id_from_redirect(resp)
        _wait_for_terminal(client, job_id)
        client.get(f"/wordlist-crack/review/{job_id}")

    assert sentinel not in caplog.text
