from unittest.mock import MagicMock, patch

from web.update import check_for_update, get_current_version, perform_update


def test_get_current_version_parses_first_versioned_changelog_heading(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [0.24.0] - 2026-08-14\n\n### Added\n")

    assert get_current_version(changelog_path=changelog) == "0.24.0"


@patch("web.update.requests.get")
def test_check_for_update_reports_update_available(mock_get, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n\n## [0.24.0] - 2026-08-14\n")
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"tag_name": "v0.25.0"})

    result = check_for_update(changelog_path=changelog)

    assert result == {"current": "0.24.0", "latest": "0.25.0", "update_available": True}


@patch("web.update.requests.get")
def test_check_for_update_reports_up_to_date(mock_get, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n\n## [0.24.0] - 2026-08-14\n")
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"tag_name": "v0.24.0"})

    result = check_for_update(changelog_path=changelog)

    assert result == {"current": "0.24.0", "latest": "0.24.0", "update_available": False}


@patch("web.update.requests.get")
def test_check_for_update_handles_github_unreachable(mock_get, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n\n## [0.24.0] - 2026-08-14\n")
    mock_get.side_effect = Exception("network unreachable")

    result = check_for_update(changelog_path=changelog)

    assert result == {"current": "0.24.0", "latest": None, "update_available": False, "error": "network unreachable"}


@patch("web.update.subprocess.run")
def test_perform_update_fetches_and_fast_forwards(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="Updating abc123..def456\nFast-forward\n", stderr="")

    result = perform_update()

    assert result["ok"] is True
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "fetch", "origin", "main"] in calls
    assert ["git", "merge", "--ff-only", "origin/main"] in calls


@patch("web.update.subprocess.run")
def test_perform_update_reports_failure_without_raising(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: Not possible to fast-forward, aborting.")

    result = perform_update()

    assert result["ok"] is False
    assert "fast-forward" in result["output"]


def test_get_current_version_returns_none_when_changelog_missing(tmp_path):
    assert get_current_version(changelog_path=tmp_path / "does-not-exist.md") is None


@patch("web.update.subprocess.run")
def test_perform_update_refuses_outside_a_git_checkout(mock_run, tmp_path):
    with patch("web.update.REPO_ROOT", tmp_path):
        result = perform_update()

    assert result["ok"] is False
    assert "git checkout" in result["output"]
    mock_run.assert_not_called()
