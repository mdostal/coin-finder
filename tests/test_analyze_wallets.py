import json
from unittest.mock import patch

from tools.analyze_wallets import analyze_wallets
from tools.scan_index import is_known


def _write_input_file(tmp_path, file_paths):
    input_file = tmp_path / "search_output.txt"
    input_file.write_text("\n".join(str(p) for p in file_paths))
    return input_file


def test_analyze_wallets_with_no_index_is_unchanged(tmp_path):
    """index_db_path=None (the default) must be a complete no-op --
    byte-identical to pre-dedup behavior."""
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"

    analyze_wallets(str(input_file), str(output_file))

    result = json.loads(output_file.read_text())
    assert str(wallet_file) in result
    assert "Bitcoin" in result[str(wallet_file)]


@patch("tools.analyze_wallets.analyze_wallet_file")
def test_analyze_wallets_skips_regex_for_a_known_hash(mock_analyze_file, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"same content everywhere")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"
    index_db_path = tmp_path / "scan_index.db"

    from tools.scan_index import hash_file_bytes, record_scanned_file

    file_hash = hash_file_bytes(b"same content everywhere")
    record_scanned_file(file_hash, "/some/other/path/wallet.dat", {"Bitcoin": ["1cached"]}, db_path=index_db_path)

    analyze_wallets(str(input_file), str(output_file), index_db_path=index_db_path)

    mock_analyze_file.assert_not_called()
    result = json.loads(output_file.read_text())
    assert result[str(wallet_file)] == {"Bitcoin": ["1cached"]}


def test_analyze_wallets_records_new_files_when_indexing(tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"
    index_db_path = tmp_path / "scan_index.db"

    analyze_wallets(str(input_file), str(output_file), index_db_path=index_db_path)

    file_hash_result = is_known(_sha256_of(wallet_file), db_path=index_db_path)
    assert file_hash_result is not None
    assert "Bitcoin" in file_hash_result


def test_analyze_wallets_recognizes_same_content_at_a_different_path(tmp_path):
    """The actual point of the feature: a copy on a different drive/backup
    (different path, identical bytes) is recognized as a duplicate."""
    content = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    drive_a = tmp_path / "driveA"
    drive_a.mkdir()
    wallet_a = drive_a / "wallet.dat"
    wallet_a.write_text(content)
    index_db_path = tmp_path / "scan_index.db"

    analyze_wallets(str(_write_input_file(tmp_path, [wallet_a])), str(tmp_path / "out_a.json"), index_db_path=index_db_path)

    drive_b = tmp_path / "driveB_backup"
    drive_b.mkdir()
    wallet_b = drive_b / "wallet_copy.dat"
    wallet_b.write_text(content)

    with patch("tools.analyze_wallets.analyze_wallet_file") as mock_analyze_file:
        analyze_wallets(str(_write_input_file(tmp_path, [wallet_b])), str(tmp_path / "out_b.json"), index_db_path=index_db_path)
        mock_analyze_file.assert_not_called()


def _sha256_of(path):
    from tools.scan_index import hash_file_bytes

    return hash_file_bytes(path.read_bytes())
