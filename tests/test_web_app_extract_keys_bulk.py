import time
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from werkzeug.datastructures import MultiDict

from tests.test_credential_scan_cache import _encrypted_entry, _unencrypted_entry, build_wallet_with_records
from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_terminal(client, job_id, timeout_iterations=200):
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


def _status_index(pairs_by_wallet):
    """
    Builds the exact shape credential_status_index() returns, for
    web.app.credential_status_index mocking -- {wallet_path: {addresses:
    {address: key_type}, extracted_at: {...}}}. pairs_by_wallet:
    {wallet_path: {address: key_type}}.
    """
    return {
        wallet_path: {
            "is_wallet_dat": True,
            "scanned_at": 0,
            "error": None,
            "addresses": dict(addresses),
            "extracted_at": {a: None for a in addresses},
        }
        for wallet_path, addresses in pairs_by_wallet.items()
    }


# --- GET confirm page ---


@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_form_shows_network_status(mock_status, mock_index, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    mock_index.return_value = _status_index({str(wallet): {"1abc": "key"}})

    resp = client.get(f"/extract-keys-bulk?{urlencode({'pair': f'{wallet}\t1abc'})}")

    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data
    assert b"1abc" in resp.data


@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_form_drops_pairs_not_cached_as_key(mock_status, mock_index, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    # Cache only knows this address as ckey (encrypted) -- the GET confirm
    # page must not show it as a row to run.
    mock_index.return_value = _status_index({str(wallet): {"1ckey": "ckey"}})

    resp = client.get(f"/extract-keys-bulk?{urlencode({'pair': f'{wallet}\t1ckey'})}")

    assert resp.status_code == 200
    assert b"No known extractable-key findings selected" in resp.data


# --- POST: offline gate ---


@patch("web.app.extract_wif_for_address")
@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_refused_when_online(mock_status, mock_index, mock_extract, client, tmp_path):
    mock_status.return_value = "ONLINE"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    mock_index.return_value = _status_index({str(wallet): {"1abc": "key"}})

    resp = client.post("/extract-keys-bulk", data={"pair": f"{wallet}\t1abc"})

    assert resp.status_code == 409
    mock_extract.assert_not_called()


@patch("web.app.extract_wif_for_address")
@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_allow_online_checkbox_proceeds_while_online(mock_status, mock_index, mock_extract, client, tmp_path):
    mock_status.return_value = "ONLINE"
    mock_extract.return_value = "5JsomeRealLookingWIFStringHere1234567890abcd"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    mock_index.return_value = _status_index({str(wallet): {"1abc": "key"}})

    resp = client.post(
        "/extract-keys-bulk",
        data={"pair": f"{wallet}\t1abc", "allow_online": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)
    mock_extract.assert_called_once_with(str(wallet), "1abc", allow_online=True)


# --- POST: server-side re-derivation, never trusts the client ---


@patch("web.app.extract_wif_for_address")
@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_server_side_filters_ineligible_pairs(mock_status, mock_index, mock_extract, client, tmp_path):
    """
    Mixed-eligibility selection: client submits two pairs, but the cache
    only currently knows one of them as an extractable "key" -- the other
    is a ckey record. The route must re-derive the real candidate set from
    credential_status_index() itself and drop the ineligible pair, even
    though the client sent it.
    """
    mock_status.return_value = "OFFLINE"
    mock_extract.return_value = "5JsomeRealLookingWIFStringHere1234567890abcd"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    mock_index.return_value = _status_index({str(wallet): {"1extractable": "key", "1encrypted": "ckey"}})

    resp = client.post(
        "/extract-keys-bulk",
        data=MultiDict([("pair", f"{wallet}\t1extractable"), ("pair", f"{wallet}\t1encrypted")]),
        follow_redirects=False,
    )

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_extract.assert_called_once_with(str(wallet), "1extractable", allow_online=False)


@patch("web.app.extract_wif_for_address")
@patch("web.app.credential_status_index")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_no_eligible_pairs_refused_without_starting_a_job(mock_status, mock_index, mock_extract, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    # Cache knows nothing about this pair at all (never scanned / stale).
    mock_index.return_value = {}

    resp = client.post("/extract-keys-bulk", data={"pair": f"{wallet}\t1abc"}, follow_redirects=False)

    assert resp.status_code == 400
    mock_extract.assert_not_called()


# --- End-to-end with real BDB fixtures ---


@patch("web.app.mark_address_extracted")
@patch("web.app.credential_status_index")
@patch("tools.extract_private_key.check_network_status")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_end_to_end_real_bdb_fixture(mock_status, mock_tool_status, mock_index, mock_mark, client, tmp_path):
    # Two separate check_network_status references need patching: the
    # route-level one (web.app.check_network_status, gating the confirm/
    # submit routes themselves) and the one extract_wif_for_address's own
    # offline gate calls internally (tools.extract_private_key.
    # check_network_status) -- this is a genuine end-to-end test, so the
    # real extract_wif_for_address runs unmocked and hits its own gate.
    mock_status.return_value = "OFFLINE"
    mock_tool_status.return_value = "OFFLINE"
    (entry, address) = _unencrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([entry]))
    mock_index.return_value = _status_index({str(wallet_file): {address: "key"}})

    resp = client.post("/extract-keys-bulk", data={"pair": f"{wallet_file}\t{address}"}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    # secret=True jobs never carry their real result through the plain
    # status/poll path -- only consume_job_result() (the once-only result
    # route below) may read it.
    assert job["result"] is None

    first_view = client.get(f"/extract-keys-bulk/result/{job_id}")
    assert first_view.status_code == 200
    assert address.encode() in first_view.data

    second_view = client.get(f"/extract-keys-bulk/result/{job_id}")
    assert second_view.status_code == 404

    mock_mark.assert_called_once_with(str(wallet_file), address)


@patch("web.app.mark_address_extracted")
@patch("web.app.credential_status_index")
@patch("tools.extract_private_key.check_network_status")
@patch("web.app.check_network_status")
def test_extract_keys_bulk_multi_address_same_wallet_produces_independent_rows(mock_status, mock_tool_status, mock_index, mock_mark, client, tmp_path):
    """
    Two extractable addresses in the SAME wallet file must each produce
    their own real, independent extraction (and result row) -- not be
    deduplicated down to one call just because they share a wallet_path.
    """
    mock_status.return_value = "OFFLINE"
    mock_tool_status.return_value = "OFFLINE"
    (entry_a, address_a) = _unencrypted_entry()
    (entry_b, address_b) = _unencrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([entry_a, entry_b]))
    mock_index.return_value = _status_index({str(wallet_file): {address_a: "key", address_b: "key"}})

    resp = client.post(
        "/extract-keys-bulk",
        data=MultiDict([("pair", f"{wallet_file}\t{address_a}"), ("pair", f"{wallet_file}\t{address_b}")]),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    result_view = client.get(f"/extract-keys-bulk/result/{job_id}")
    assert result_view.status_code == 200
    assert address_a.encode() in result_view.data
    assert address_b.encode() in result_view.data

    assert mock_mark.call_count == 2
    mock_mark.assert_any_call(str(wallet_file), address_a)
    mock_mark.assert_any_call(str(wallet_file), address_b)


# --- Job worker: per-pair isolation (a ckey pair must not abort the batch) ---


@patch("web.app.mark_address_extracted")
def test_bulk_extract_job_isolates_a_ckey_failure_without_aborting_the_batch(mock_mark):
    """
    Exercises _run_bulk_extract_key_job directly against a real BDB
    fixture with one genuinely-extractable "key" record and one
    "ckey" (encrypted) record. Even if a ckey pair somehow reaches the
    job (stale cache, race), extract_wif_for_address's own hard refusal
    must be caught per-pair -- a clear per-row error, with the OTHER
    pair's real extraction still succeeding.
    """
    from web.app import _run_bulk_extract_key_job

    with patch("tools.extract_private_key.check_network_status", return_value="OFFLINE"):
        import tempfile
        from pathlib import Path

        (key_entry, key_address) = _unencrypted_entry()
        (ckey_entry, ckey_address) = _encrypted_entry()
        with tempfile.TemporaryDirectory() as tmp:
            wallet_file = Path(tmp) / "wallet.dat"
            wallet_file.write_bytes(build_wallet_with_records([key_entry, ckey_entry]))

            result = _run_bulk_extract_key_job(
                allow_online=False,
                pairs=[(str(wallet_file), key_address), (str(wallet_file), ckey_address)],
            )

    results = result["results"]
    assert results[(str(wallet_file), key_address)]["wif"] is not None
    assert results[(str(wallet_file), key_address)]["error"] is None

    assert results[(str(wallet_file), ckey_address)]["wif"] is None
    assert "ENCRYPTED" in results[(str(wallet_file), ckey_address)]["error"]

    # Only the real success is marked extracted -- the refused ckey pair is not.
    mock_mark.assert_called_once_with(str(wallet_file), key_address)


@patch("tools.extract_private_key.check_network_status")
def test_bulk_extract_job_offline_gate_refusal_isolated_per_pair(mock_status):
    """
    An offline-gate refusal for one pair (network online, allow_online not
    set at the extract_wif_for_address call level -- simulated here by
    forcing check_network_status to report ONLINE) must show up as that
    row's own error, not raise out of the job.
    """
    from web.app import _run_bulk_extract_key_job

    mock_status.return_value = "ONLINE"
    (entry, address) = _unencrypted_entry()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        wallet_file = Path(tmp) / "wallet.dat"
        wallet_file.write_bytes(build_wallet_with_records([entry]))

        with patch("web.app.mark_address_extracted") as mock_mark:
            result = _run_bulk_extract_key_job(allow_online=False, pairs=[(str(wallet_file), address)])

    row = result["results"][(str(wallet_file), address)]
    assert row["wif"] is None
    assert "OFFLINE" in row["error"]
    mock_mark.assert_not_called()
