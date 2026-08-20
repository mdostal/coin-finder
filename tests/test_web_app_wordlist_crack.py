import io
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from web.app import create_app, _run_wordlist_crack_job
from web.vault import list_vault_entries, resolve_vault_entries_with_values


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


# --- rtpc-02: confirm-to-vault with provenance -------------------------


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_review_shows_add_to_vault_button_when_found(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'hunter2!!'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"hunter2!!\n", filename="my-wordlist.txt")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/wordlist-crack/review/{job_id}")
    html = view.data.decode()

    assert view.status_code == 200
    assert "Add to vault" in html
    # provenance carried forward as hidden fields on the confirm form
    assert 'name="job_id"' in html
    assert f'value="{job_id}"' in html
    assert 'name="wallet_path"' in html
    assert str(wallet_file) in html
    assert 'name="wordlist_filename"' in html
    assert 'value="my-wordlist.txt"' in html
    assert 'name="found_at"' in html
    assert 'name="value"' in html
    assert 'value="hunter2!!"' in html


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_review_no_add_to_vault_button_when_not_found(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"wrong-1\nwrong-2\n")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/wordlist-crack/review/{job_id}")
    assert view.status_code == 200
    assert b"Add to vault" not in view.data


@patch("web.app.add_vault_entry")
def test_wordlist_crack_confirm_adds_to_vault_with_provenance_tags(mock_add, client):
    captured = {}

    def _capture(name, value_file_path, description="", tags=None):
        with open(value_file_path) as f:
            captured["value"] = f.read()
        captured["name"] = name
        captured["tags"] = tags
        assert Path(value_file_path).exists(), "value file must exist while add_vault_entry runs"

    mock_add.side_effect = _capture

    resp = client.post(
        "/wordlist-crack/confirm",
        data={
            "job_id": "abc123",
            "wallet_path": "/wallets/locked.dat",
            "value": "hunter2!!",
            "wordlist_filename": "my-wordlist.txt",
            "found_at": "2026-08-19T01:02:03Z",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    mock_add.assert_called_once()
    assert captured["value"] == "hunter2!!"
    assert captured["tags"] == {
        "wordlist": "my-wordlist.txt",
        "method": "btcrecover-wordlist-crack",
        "found_at": "2026-08-19T01:02:03Z",
        "wallet_path": "/wallets/locked.dat",
    }
    assert b"Added to the vault" in resp.data


@patch("web.app.add_vault_entry")
def test_wordlist_crack_confirm_writes_value_to_temp_file_then_cleans_it_up(mock_add, client):
    captured = {}

    def _capture(name, value_file_path, description="", tags=None):
        captured["path"] = value_file_path

    mock_add.side_effect = _capture

    client.post(
        "/wordlist-crack/confirm",
        data={"job_id": "abc123", "wallet_path": "/wallets/locked.dat", "value": "hunter2!!"},
        follow_redirects=False,
    )

    assert "path" in captured
    assert not os.path.exists(captured["path"]), "temp value file must be deleted after add_vault_entry returns"


def test_wordlist_crack_confirm_rejects_missing_fields(client):
    resp = client.post("/wordlist-crack/confirm", data={"job_id": "", "wallet_path": "", "value": ""})
    assert resp.status_code == 400


@patch("web.vault.shutil.which", return_value=None)
def test_wordlist_crack_confirm_double_click_does_not_duplicate(mock_which, client, tmp_path, monkeypatch):
    """
    rtpc-02: double-confirming the exact same crack result (same job_id,
    e.g. a double-click submitting the form twice) must not crash and
    must not create a second vault entry -- the entry name is
    deterministic from job_id, so the second add overwrites the first
    in place. Forces the JSON fallback path so this can assert the real
    persisted entry count directly.
    """
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")

    data = {
        "job_id": "same-job-id-123",
        "wallet_path": "/wallets/locked.dat",
        "value": "hunter2!!",
        "wordlist_filename": "my-wordlist.txt",
        "found_at": "2026-08-19T01:02:03Z",
    }

    resp1 = client.post("/wordlist-crack/confirm", data=data, follow_redirects=False)
    resp2 = client.post("/wordlist-crack/confirm", data=data, follow_redirects=False)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert b"Added to the vault" in resp1.data
    assert b"Added to the vault" in resp2.data

    entries = list_vault_entries()
    assert len(entries) == 1
    assert entries[0]["name"].startswith("wordlist-crack-")


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_wordlist_crack_confirm_end_to_end_from_real_review_page(mock_status, mock_run_unlock, client, tmp_path, monkeypatch):
    """
    rtpc-02, full acceptance-criteria flow: crack a real job, land on the
    once-only review page, and confirm using exactly the hidden-field
    values that page renders (not hand-constructed ones) -- proving the
    review page and the confirm route actually agree on what data flows
    between them, end to end.
    """
    monkeypatch.setattr("web.vault.shutil.which", lambda *_: None)
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")

    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: 'correct-horse-battery-staple'", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = _post_crack(client, wallet_file, b"correct-horse-battery-staple\n", filename="grandpas-list.txt")
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/wordlist-crack/review/{job_id}")
    html = view.data.decode()

    def _hidden_value(field_name):
        match = re.search(rf'name="{field_name}" value="([^"]*)"', html)
        assert match is not None, f"expected a hidden field named {field_name}"
        return match.group(1)

    confirm_resp = client.post(
        "/wordlist-crack/confirm",
        data={
            "job_id": _hidden_value("job_id"),
            "wallet_path": _hidden_value("wallet_path"),
            "value": _hidden_value("value"),
            "wordlist_filename": _hidden_value("wordlist_filename"),
            "found_at": _hidden_value("found_at"),
        },
        follow_redirects=False,
    )

    assert confirm_resp.status_code == 200
    entries = list_vault_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["tags"]["wallet_path"] == str(wallet_file)
    assert entry["tags"]["wordlist"] == "grandpas-list.txt"
    assert entry["tags"]["method"] == "btcrecover-wordlist-crack"
    assert entry["tags"]["found_at"]  # non-empty -- a real timestamp was recorded

    pairs = resolve_vault_entries_with_values([entry["name"]])
    assert pairs == [(entry["name"], "correct-horse-battery-staple")]
