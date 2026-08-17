from unittest.mock import MagicMock, patch

from tools.scan_google_drive import (
    download_file,
    is_wallet_like_filename,
    list_wallet_like_files,
    scan_drive_for_wallets,
)


def test_is_wallet_like_filename_matches_extension():
    assert is_wallet_like_filename("backup wallet.dat") is True


def test_is_wallet_like_filename_matches_coin_name():
    assert is_wallet_like_filename("helium-wallet") is True


def test_is_wallet_like_filename_matches_keyword():
    assert is_wallet_like_filename("crypto_stuff.json") is True


def test_is_wallet_like_filename_no_match_for_unrelated_file():
    assert is_wallet_like_filename("vacation_photo.jpg") is False


def make_files_list_response(files, next_page_token=None):
    return {"files": files, "nextPageToken": next_page_token}


def test_list_wallet_like_files_filters_by_name_and_skips_native_google_docs():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = make_files_list_response([
        {"id": "1", "name": "diamond backup wallet.dat", "size": "65536", "mimeType": "application/octet-stream"},
        {"id": "2", "name": "vacation_photo.jpg", "size": "500000", "mimeType": "image/jpeg"},
        {"id": "3", "name": "Circles wallet", "size": "1024", "mimeType": "application/vnd.google-apps.document"},
    ])

    results = list_wallet_like_files(service, page_delay_seconds=0)

    assert [f["id"] for f in results] == ["1"]


def test_list_wallet_like_files_paginates():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = [
        make_files_list_response(
            [{"id": "1", "name": "wallet1.dat", "size": "1000", "mimeType": "application/octet-stream"}],
            next_page_token="page2",
        ),
        make_files_list_response(
            [{"id": "2", "name": "wallet2.dat", "size": "1000", "mimeType": "application/octet-stream"}],
        ),
    ]

    results = list_wallet_like_files(service, page_delay_seconds=0)

    assert [f["id"] for f in results] == ["1", "2"]


def test_list_wallet_like_files_respects_size_bounds():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = make_files_list_response([
        {"id": "1", "name": "wallet_tiny.dat", "size": "0", "mimeType": "application/octet-stream"},
        {"id": "2", "name": "wallet_huge.dat", "size": str(10**9), "mimeType": "application/octet-stream"},
        {"id": "3", "name": "wallet_normal.dat", "size": "65536", "mimeType": "application/octet-stream"},
    ])

    results = list_wallet_like_files(service, page_delay_seconds=0)

    assert [f["id"] for f in results] == ["3"]


@patch("tools.scan_google_drive.MediaIoBaseDownload")
def test_download_file_writes_directly_to_local_disk(mock_downloader_cls, tmp_path):
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (None, True)
    mock_downloader_cls.return_value = mock_downloader

    service = MagicMock()
    destination = tmp_path / "downloaded.dat"

    download_file(service, "fake-file-id", str(destination))

    service.files.return_value.get_media.assert_called_once_with(fileId="fake-file-id")
    mock_downloader.next_chunk.assert_called()


@patch("tools.scan_google_drive.download_file")
@patch("tools.scan_google_drive.list_wallet_like_files")
def test_scan_drive_for_wallets_downloads_every_candidate_and_returns_a_manifest(
    mock_list, mock_download, tmp_path
):
    mock_list.return_value = [
        {"id": "1", "name": "wallet1.dat"},
        {"id": "2", "name": "wallet2.dat"},
    ]

    service = MagicMock()
    manifest = scan_drive_for_wallets(service, str(tmp_path))

    assert mock_download.call_count == 2
    assert len(manifest) == 2
    assert all(entry["local_path"].startswith(str(tmp_path)) for entry in manifest)


def test_list_wallet_like_files_reports_progress_per_page():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = [
        make_files_list_response(
            [{"id": "1", "name": "wallet1.dat", "size": "1000", "mimeType": "application/octet-stream"}],
            next_page_token="page2",
        ),
        make_files_list_response(
            [{"id": "2", "name": "wallet2.dat", "size": "1000", "mimeType": "application/octet-stream"}],
        ),
    ]

    calls = []
    list_wallet_like_files(service, page_delay_seconds=0, progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls == [(1, None, "1 wallet-like file(s) found so far"), (2, None, "2 wallet-like file(s) found so far")]


@patch("tools.scan_google_drive.download_file")
@patch("tools.scan_google_drive.list_wallet_like_files")
def test_scan_drive_for_wallets_reports_determinate_download_progress(mock_list, mock_download, tmp_path):
    mock_list.return_value = [
        {"id": "1", "name": "wallet1.dat"},
        {"id": "2", "name": "wallet2.dat"},
    ]

    calls = []
    scan_drive_for_wallets(MagicMock(), str(tmp_path), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls == [(1, 2, "Downloading: wallet1.dat"), (2, 2, "Downloading: wallet2.dat")]
