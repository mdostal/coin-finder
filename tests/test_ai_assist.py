from unittest.mock import MagicMock, patch

import pytest

from web import ai_assist


@patch("web.ai_assist.list_vault_entries")
def test_has_api_key_false_when_not_saved(mock_list):
    mock_list.return_value = []
    assert ai_assist.has_api_key() is False


@patch("web.ai_assist.list_vault_entries")
def test_has_api_key_true_when_enabled(mock_list):
    mock_list.return_value = [{"name": ai_assist.VAULT_KEY_NAME, "state": "enabled"}]
    assert ai_assist.has_api_key() is True


@patch("web.ai_assist.list_vault_entries")
def test_has_api_key_false_when_revoked(mock_list):
    mock_list.return_value = [{"name": ai_assist.VAULT_KEY_NAME, "state": "revoked"}]
    assert ai_assist.has_api_key() is False


@patch("web.ai_assist.add_vault_entry")
def test_set_api_key_stores_via_vault(mock_add):
    ai_assist.set_api_key("sk-ant-abc123")

    mock_add.assert_called_once()
    assert mock_add.call_args[0][0] == ai_assist.VAULT_KEY_NAME


@patch("web.ai_assist.revoke_vault_entry")
def test_clear_api_key_revokes_via_vault(mock_revoke):
    ai_assist.clear_api_key()
    mock_revoke.assert_called_once_with(ai_assist.VAULT_KEY_NAME)


@patch("web.ai_assist.has_api_key")
def test_ask_raises_without_a_saved_key(mock_has_key):
    mock_has_key.return_value = False

    with pytest.raises(RuntimeError, match="No API key saved"):
        ai_assist.ask("what scope should I pick?")


@patch("web.ai_assist.requests.post")
@patch("web.ai_assist.resolve_vault_entries_with_values")
@patch("web.ai_assist.has_api_key")
def test_ask_calls_anthropic_and_returns_text(mock_has_key, mock_resolve, mock_post):
    mock_has_key.return_value = True
    mock_resolve.return_value = [(ai_assist.VAULT_KEY_NAME, "sk-ant-real-key")]
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"content": [{"type": "text", "text": "Use drive.readonly."}]},
    )

    answer = ai_assist.ask("what scope should I pick?")

    assert answer == "Use drive.readonly."
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "sk-ant-real-key"
    assert call_kwargs["timeout"] == ai_assist.LLM_REQUEST_TIMEOUT_SECONDS
    assert call_kwargs["json"]["messages"][0]["content"] == "what scope should I pick?"


@patch("web.ai_assist.requests.post")
@patch("web.ai_assist.resolve_vault_entries_with_values")
@patch("web.ai_assist.has_api_key")
def test_ask_raises_on_non_200(mock_has_key, mock_resolve, mock_post):
    mock_has_key.return_value = True
    mock_resolve.return_value = [(ai_assist.VAULT_KEY_NAME, "sk-ant-real-key")]
    mock_post.return_value = MagicMock(status_code=401, text="invalid api key")

    with pytest.raises(RuntimeError, match="401"):
        ai_assist.ask("hello")
