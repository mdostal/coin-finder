import json
from unittest.mock import patch

from tools.analyze_wallets import analyze_wallet_file, analyze_wallets
from tools.scan_index import is_known

# Tonight's real garbage: Rust mangled-symbol strings from a prior scan's
# own output file (wallet_analysis.json), re-scanned as if it were wallet
# content -- shape-matched Digibyte/Diamond Coin/Ripple with zero
# checksum verification. See config/address_validators.py and
# tests/test_address_validators.py for the offline validator these must
# now be filtered through.
GARBAGE_DIGIBYTE_AND_DIAMOND = "d6thread6Thread5cname17hd86fb86E"
GARBAGE_DIGIBYTE_ONLY = "df29a6dde7b3e33ab57f416f11"
REAL_BITCOIN_ADDRESS = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"


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


def test_analyze_wallets_reports_determinate_progress(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("nothing interesting here")
    input_file = _write_input_file(tmp_path, [wallet_a, wallet_b])
    output_file = tmp_path / "analysis.json"

    calls = []
    analyze_wallets(str(input_file), str(output_file), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls == [(1, 2, str(wallet_a)), (2, 2, str(wallet_b))]


def test_analyze_wallet_file_filters_out_garbage_matches(tmp_path):
    """End-to-end regression test for tonight's bug report: a file
    containing both a real, checksum-valid Bitcoin address and the actual
    garbage strings a prior scan's own output produced. Only the real
    address may survive -- garbage must never reach the returned dict,
    which is what tools/analyze_wallets.py:analyze_wallets() writes
    straight to wallet_analysis.json (and from there feeds real
    balance-check API calls and web/app.py's record_finding())."""
    wallet_file = tmp_path / "prior_scan_output.json"
    wallet_file.write_text(
        f"{REAL_BITCOIN_ADDRESS} {GARBAGE_DIGIBYTE_AND_DIAMOND} {GARBAGE_DIGIBYTE_ONLY}"
    )

    result = analyze_wallet_file(str(wallet_file))

    assert result.get("Bitcoin") == [REAL_BITCOIN_ADDRESS]
    for matches in result.values():
        assert GARBAGE_DIGIBYTE_AND_DIAMOND not in matches
        assert GARBAGE_DIGIBYTE_ONLY not in matches


def test_analyze_wallets_reports_progress_for_a_dedup_cache_hit_too(tmp_path):
    content = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text(content)
    index_db_path = tmp_path / "scan_index.db"
    analyze_wallets(str(_write_input_file(tmp_path, [wallet_a])), str(tmp_path / "out_a.json"), index_db_path=index_db_path)

    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text(content)  # identical content -- a cache hit this time

    calls = []
    analyze_wallets(
        str(_write_input_file(tmp_path, [wallet_b])),
        str(tmp_path / "out_b.json"),
        index_db_path=index_db_path,
        progress_callback=lambda c, t, m="": calls.append((c, t, m)),
    )

    assert calls == [(1, 1, str(wallet_b))]
