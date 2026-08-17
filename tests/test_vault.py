import json
import subprocess
from unittest.mock import MagicMock, patch

from web.vault import (
    PORTUNUS_TIMEOUT_SECONDS,
    add_vault_entry,
    edit_vault_entry,
    list_vault_entries,
    resolve_vault_entries_to_candidates_file,
    resolve_vault_entries_with_values,
    revoke_vault_entry,
)


@patch("web.vault.subprocess.run")
def test_list_vault_entries_parses_json_and_excludes_revoked_by_default(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {"name": "password-1", "state": "enabled", "description": "guess from 2015"},
                {"name": "password-2", "state": "revoked", "description": "old one"},
            ]
        ),
    )

    entries = list_vault_entries()

    assert [e["name"] for e in entries] == ["password-1"]


@patch("web.vault.subprocess.run")
def test_list_vault_entries_include_revoked(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "password-1", "state": "revoked", "description": ""}]),
    )

    entries = list_vault_entries(include_revoked=True)

    assert len(entries) == 1


@patch("web.vault.subprocess.run")
def test_list_vault_entries_never_includes_a_value_field(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "password-1", "state": "enabled", "description": "test"}]),
    )

    entries = list_vault_entries()

    assert "value" not in entries[0]


@patch("web.vault.subprocess.run")
def test_add_vault_entry_drops_then_enables(mock_run, tmp_path):
    value_file = tmp_path / "value.txt"
    value_file.write_text("hunter2")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    add_vault_entry("password-1", str(value_file), description="guess from 2015")

    calls = [c.args[0] for c in mock_run.call_args_list]
    drop_call = next(c for c in calls if "drop" in c)
    assert "--value-file" in drop_call
    assert str(value_file) in drop_call
    enable_call = next(c for c in calls if "state" in c)
    assert "enabled" in enable_call


@patch("web.vault.subprocess.run")
def test_revoke_vault_entry(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    revoke_vault_entry("password-1")

    args = mock_run.call_args.args[0]
    assert args == ["portunus", "state", "password-1", "revoked"]


@patch("web.vault.subprocess.run")
def test_edit_vault_entry_calls_portunus_retag(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    edit_vault_entry("password-1", "updated description")

    args, kwargs = mock_run.call_args
    assert args[0] == ["portunus", "retag", "password-1", "--description", "updated description"]
    assert kwargs.get("stdin") is subprocess.DEVNULL
    assert kwargs.get("timeout") == PORTUNUS_TIMEOUT_SECONDS


@patch("web.vault.shutil.which", return_value=None)
def test_edit_vault_entry_updates_fallback_description(mock_which, tmp_path, monkeypatch):
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")
    value_file = tmp_path / "value.txt"
    value_file.write_text("hunter2")
    add_vault_entry("password-1", str(value_file), description="original")

    edit_vault_entry("password-1", "updated description")

    entries = list_vault_entries()
    assert entries[0]["description"] == "updated description"


@patch("web.vault.subprocess.run")
def test_resolve_vault_entries_combines_into_one_candidates_file(mock_run, tmp_path):
    resolved_1 = tmp_path / "resolved1.txt"
    resolved_1.write_text("hunter2")
    resolved_2 = tmp_path / "resolved2.txt"
    resolved_2.write_text("correcthorse")

    def fake_run(args, **kwargs):
        if args[:2] == ["portunus", "resolve"]:
            template = args[2]
            if "password-1" in template:
                return MagicMock(returncode=0, stdout=str(resolved_1) + "\n", stderr="")
            return MagicMock(returncode=0, stdout=str(resolved_2) + "\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = fake_run

    candidates_path = resolve_vault_entries_to_candidates_file(["password-1", "password-2"])

    with open(candidates_path) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines == ["hunter2", "correcthorse"]


@patch("web.vault.subprocess.run")
def test_resolve_vault_entries_raises_clear_error_on_unknown_reference(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="portunus: unknown reference {{secret:nope}}")

    try:
        resolve_vault_entries_to_candidates_file(["nope"])
        assert False, "expected an error"
    except RuntimeError as e:
        assert "nope" in str(e)


@patch("web.vault.subprocess.run")
def test_resolve_vault_entries_with_values_returns_name_value_pairs(mock_run, tmp_path):
    resolved = tmp_path / "resolved.txt"
    resolved.write_text("hunter2")
    mock_run.return_value = MagicMock(returncode=0, stdout=str(resolved) + "\n", stderr="")

    pairs = resolve_vault_entries_with_values(["password-1"])

    assert pairs == [("password-1", "hunter2")]


@patch("web.vault.subprocess.run")
def test_every_portunus_call_passes_stdin_devnull_and_a_timeout(mock_run, tmp_path):
    """
    Regression test for a real hang hit live: `portunus` inherits whatever
    stdin it's given, and a subprocess spawned from inside the Tauri
    sidecar gets a piped stdin that never produces EOF -- if portunus ever
    tries to read from it, the read blocks forever, freezing the whole
    single-threaded Flask server. Every portunus call must pass
    stdin=DEVNULL (so a read returns EOF immediately) and a timeout (so a
    hang anywhere else in portunus itself can't block forever either).
    """
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps([]), stderr="")
    value_file = tmp_path / "value.txt"
    value_file.write_text("hunter2")

    list_vault_entries()
    add_vault_entry("password-1", str(value_file))
    revoke_vault_entry("password-1")
    try:
        resolve_vault_entries_with_values(["password-1"])
    except Exception:
        pass  # this call's mocked stdout isn't a real resolved-path -- only the call shape matters here

    assert mock_run.call_args_list, "expected at least one portunus call"
    for call in mock_run.call_args_list:
        assert call.kwargs.get("stdin") is subprocess.DEVNULL, f"missing stdin=DEVNULL: {call}"
        assert call.kwargs.get("timeout") == PORTUNUS_TIMEOUT_SECONDS, f"missing/wrong timeout: {call}"


@patch("web.vault.subprocess.run")
def test_list_vault_entries_returns_empty_on_timeout_instead_of_hanging(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["portunus"], timeout=PORTUNUS_TIMEOUT_SECONDS)
    assert list_vault_entries() == []


@patch("web.vault.subprocess.run")
def test_resolve_vault_entries_raises_clear_error_on_timeout_instead_of_hanging(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["portunus"], timeout=PORTUNUS_TIMEOUT_SECONDS)

    try:
        resolve_vault_entries_with_values(["password-1"])
        assert False, "expected an error"
    except RuntimeError as e:
        assert "timed out" in str(e)


@patch("web.vault.shutil.which", return_value=None)
def test_fallback_used_when_portunus_not_installed(mock_which, tmp_path, monkeypatch):
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")
    value_file = tmp_path / "value.txt"
    value_file.write_text("hunter2")

    add_vault_entry("password-1", str(value_file), description="guess from 2015")
    entries = list_vault_entries()
    assert [e["name"] for e in entries] == ["password-1"]

    pairs = resolve_vault_entries_with_values(["password-1"])
    assert pairs == [("password-1", "hunter2")]

    revoke_vault_entry("password-1")
    assert list_vault_entries() == []
    assert [e["name"] for e in list_vault_entries(include_revoked=True)] == ["password-1"]
