from pathlib import Path
from unittest.mock import patch

from web.paths import app_data_dir


def test_source_install_uses_web_directory():
    with patch("web.paths.sys") as mock_sys:
        mock_sys.frozen = False
        del mock_sys.frozen  # getattr(sys, "frozen", False) -> False when absent
        result = app_data_dir()
    assert result == Path(__file__).resolve().parent.parent / "web"


@patch("web.paths.Path.mkdir")
def test_frozen_macos_uses_application_support(mock_mkdir):
    with patch("web.paths.sys") as mock_sys:
        mock_sys.frozen = True
        mock_sys.platform = "darwin"
        result = app_data_dir()
    assert result == Path.home() / "Library" / "Application Support" / "coin-finder"
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


@patch("web.paths.Path.mkdir")
def test_frozen_linux_uses_xdg_style_share_dir(mock_mkdir):
    with patch("web.paths.sys") as mock_sys:
        mock_sys.frozen = True
        mock_sys.platform = "linux"
        result = app_data_dir()
    assert result == Path.home() / ".local" / "share" / "coin-finder"
