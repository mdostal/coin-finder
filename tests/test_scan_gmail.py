import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from tools.scan_gmail import (
    _extract_plain_text,
    _headers_dict,
    _is_wallet_like_attachment,
    _looks_like_google_client_id,
    bind_gmail_account,
    find_addresses_in_payload,
    get_gmail_service,
    is_gmail_bound,
    save_wallet_like_attachments,
    scan_gmail_for_wallet_clues,
    search_message_ids,
    unbind_gmail_account,
)


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_looks_like_google_client_id_accepts_real_suffix():
    assert _looks_like_google_client_id("12345-abc.apps.googleusercontent.com") is True


def test_looks_like_google_client_id_rejects_made_up_value():
    assert _looks_like_google_client_id("my-drive") is False


@patch("tools.scan_gmail.list_vault_entries")
def test_is_gmail_bound_true_when_token_entry_present(mock_list):
    mock_list.return_value = [{"name": "gmail-oauth-token", "state": "enabled"}]
    assert is_gmail_bound() is True


@patch("tools.scan_gmail.list_vault_entries", return_value=[])
def test_is_gmail_bound_false_when_no_entries(mock_list):
    assert is_gmail_bound() is False


def test_bind_gmail_account_rejects_a_bad_client_id():
    result = bind_gmail_account("not-a-real-client-id", "secret")
    assert result["ok"] is False
    assert "apps.googleusercontent.com" in result["report"]


@patch("google_auth_oauthlib.flow.InstalledAppFlow")
@patch("tools.scan_gmail.add_vault_entry")
def test_bind_gmail_account_stores_client_credentials_before_oauth(mock_add_entry, mock_flow_cls):
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = json.dumps({"token": "abc"})
    mock_flow_cls.from_client_config.return_value.run_local_server.return_value = fake_creds

    result = bind_gmail_account("real.apps.googleusercontent.com", "shh")

    assert result["ok"] is True
    stored_names = [call.args[0] for call in mock_add_entry.call_args_list]
    assert stored_names == ["gmail-oauth-client-id", "gmail-oauth-client-secret", "gmail-oauth-token"]


@patch("google_auth_oauthlib.flow.InstalledAppFlow")
@patch("tools.scan_gmail.revoke_vault_entry")
@patch("tools.scan_gmail.add_vault_entry")
def test_bind_gmail_account_unbinds_on_oauth_failure(mock_add_entry, mock_revoke, mock_flow_cls):
    mock_flow_cls.from_client_config.return_value.run_local_server.side_effect = RuntimeError("user closed the browser")

    result = bind_gmail_account("real.apps.googleusercontent.com", "shh")

    assert result["ok"] is False
    assert mock_revoke.call_count == 3


@patch("tools.scan_gmail.is_gmail_bound", return_value=False)
def test_get_gmail_service_raises_when_not_bound(mock_bound):
    with pytest.raises(RuntimeError):
        get_gmail_service()


@patch("googleapiclient.discovery.build")
@patch("google.oauth2.credentials.Credentials")
@patch("tools.scan_gmail.resolve_vault_entries_with_values")
@patch("tools.scan_gmail.is_gmail_bound", return_value=True)
def test_get_gmail_service_builds_client_from_resolved_token(mock_bound, mock_resolve, mock_creds_cls, mock_build):
    token_json = json.dumps({"token": "abc", "refresh_token": "r"})
    mock_resolve.return_value = [("gmail-oauth-token", token_json)]
    fake_creds = MagicMock(valid=True)
    mock_creds_cls.from_authorized_user_info.return_value = fake_creds

    get_gmail_service()

    mock_creds_cls.from_authorized_user_info.assert_called_once_with(json.loads(token_json), ["https://www.googleapis.com/auth/gmail.readonly"])
    mock_build.assert_called_once_with("gmail", "v1", credentials=fake_creds)


@patch("tools.scan_gmail.revoke_vault_entry")
def test_unbind_gmail_account_revokes_all_three_entries(mock_revoke):
    unbind_gmail_account()
    revoked_names = [call.args[0] for call in mock_revoke.call_args_list]
    assert revoked_names == ["gmail-oauth-client-id", "gmail-oauth-client-secret", "gmail-oauth-token"]


def make_list_response(messages, next_page_token=None):
    return {"messages": messages, "nextPageToken": next_page_token}


def test_search_message_ids_paginates():
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.side_effect = [
        make_list_response([{"id": "1"}], next_page_token="page2"),
        make_list_response([{"id": "2"}]),
    ]

    results = search_message_ids(service, "wallet", page_delay_seconds=0)

    assert results == ["1", "2"]


def test_extract_plain_text_from_simple_body():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("hello 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")}}
    assert "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2" in _extract_plain_text(payload)


def test_extract_plain_text_falls_back_to_html_with_tags_stripped():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [{"mimeType": "text/html", "body": {"data": _b64("<p>address: 1abc</p>")}}],
    }
    text = _extract_plain_text(payload)
    assert "<p>" not in text
    assert "1abc" in text


def test_extract_plain_text_walks_nested_multipart():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [{"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/plain", "body": {"data": _b64("nested body text")}}]}],
    }
    assert "nested body text" in _extract_plain_text(payload)


def test_headers_dict_maps_name_to_value():
    payload = {"headers": [{"name": "Subject", "value": "hi"}, {"name": "From", "value": "a@b.com"}]}
    assert _headers_dict(payload) == {"Subject": "hi", "From": "a@b.com"}


def test_find_addresses_in_payload_matches_known_patterns():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("your address is 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 thanks")}}
    found = find_addresses_in_payload(payload)
    assert found.get("Bitcoin") == ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]


def test_find_addresses_in_payload_empty_when_no_match():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("just a normal email, nothing here")}}
    assert find_addresses_in_payload(payload) == {}


def test_is_wallet_like_attachment_matches_extension():
    assert _is_wallet_like_attachment("old_backup.dat") is True


def test_is_wallet_like_attachment_no_match_for_unrelated_file():
    assert _is_wallet_like_attachment("invoice.pdf") is False


def test_save_wallet_like_attachments_downloads_only_matching_files(tmp_path):
    service = MagicMock()
    service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
        "data": _b64("fake wallet bytes")
    }
    payload = {
        "parts": [
            {"filename": "wallet.dat", "body": {"attachmentId": "att1"}},
            {"filename": "invoice.pdf", "body": {"attachmentId": "att2"}},
            {"filename": "", "body": {}},
        ]
    }

    saved = save_wallet_like_attachments(service, "msg1", payload, str(tmp_path))

    assert len(saved) == 1
    assert "wallet.dat" in saved[0]
    assert (tmp_path / "msg1_wallet.dat").read_bytes() == b"fake wallet bytes"


@patch("tools.scan_gmail.get_gmail_service")
@patch("tools.scan_gmail.search_message_ids")
def test_scan_gmail_for_wallet_clues_writes_summary_and_calls_progress(mock_search, mock_get_service, tmp_path):
    service = MagicMock()
    mock_get_service.return_value = service
    mock_search.return_value = ["msg1"]

    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {
            "headers": [{"name": "From", "value": "coinbase.com"}, {"name": "Subject", "value": "Withdrawal confirmed"}],
            "mimeType": "text/plain",
            "body": {"data": _b64("your address is 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")},
        }
    }

    calls = []
    results = scan_gmail_for_wallet_clues(str(tmp_path), queries=["from:coinbase.com"], progress_callback=lambda c, t, m="": calls.append((c, t)))

    assert len(results) == 1
    assert results[0]["from"] == "coinbase.com"
    assert results[0]["addresses"]["Bitcoin"] == ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]
    assert calls == [(1, 1)]

    output_file = tmp_path / "gmail_scan_results.json"
    assert output_file.exists()
    assert json.loads(output_file.read_text())[0]["subject"] == "Withdrawal confirmed"
