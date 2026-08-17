from unittest.mock import patch

from tools.generate_wallet_report import build_wallet_report, identify_wallet_software, render_wallet_report

BITCOIN_CORE_MAGIC_HEADER = bytes(12) + b"\x62\x31\x05\x00\x09\x00\x00\x00" + bytes(4)


def test_identify_wallet_software_recognizes_bitcoin_core_magic(tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(BITCOIN_CORE_MAGIC_HEADER)

    assert identify_wallet_software(str(wallet_file)) == "Bitcoin Core (Berkeley DB Btree v9 wallet.dat)"


def test_identify_wallet_software_reports_unknown_for_unrecognized_file(tmp_path):
    wallet_file = tmp_path / "not_a_wallet.dat"
    wallet_file.write_bytes(b"not the right magic bytes at all")

    result = identify_wallet_software(str(wallet_file))
    assert "Unknown" in result


@patch("tools.generate_wallet_report.compute_last_activity_timestamp")
@patch("tools.generate_wallet_report.fetch_address_transactions")
@patch("tools.generate_wallet_report.scan_wallet_for_addresses")
def test_build_wallet_report_includes_metadata_software_and_target_address_activity(
    mock_scan, mock_fetch, mock_last_activity, tmp_path
):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(BITCOIN_CORE_MAGIC_HEADER)

    mock_scan.return_value = {
        "addresses": [
            {"address": "1abc", "source": "name"},
            {"address": "1def", "source": "key"},
        ],
        "encrypted_key_count": 0,
        "unparsed_record_types": {},
    }
    mock_fetch.return_value = [{"fake": "tx"}]
    mock_last_activity.return_value = 1_600_000_000

    report = build_wallet_report(str(wallet_file), target_addresses=["1abc"], now=1_700_000_000)

    assert report["software"] == "Bitcoin Core (Berkeley DB Btree v9 wallet.dat)"
    assert report["encrypted"] is False
    assert report["total_addresses"] == 2
    assert len(report["addresses"]) == 1
    assert report["addresses"][0]["address"] == "1abc"
    assert report["addresses"][0]["dormant_years"] > 0
    mock_fetch.assert_called_once_with("1abc")


@patch("tools.generate_wallet_report.scan_wallet_for_addresses")
def test_build_wallet_report_without_target_addresses_skips_activity_lookup(mock_scan, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(BITCOIN_CORE_MAGIC_HEADER)

    mock_scan.return_value = {
        "addresses": [{"address": "1abc", "source": "name"}],
        "encrypted_key_count": 1,
        "unparsed_record_types": {},
    }

    report = build_wallet_report(str(wallet_file))

    assert report["encrypted"] is True
    assert report["addresses"] == []


def test_render_wallet_report_mentions_recovery_reference_doc():
    report = {
        "metadata": {"path": "/some/wallet.dat", "size_bytes": 1024, "modified_at": "2024-01-01T00:00:00Z"},
        "software": "Bitcoin Core (Berkeley DB Btree v9 wallet.dat)",
        "encrypted": False,
        "encrypted_key_count": 0,
        "total_addresses": 2,
        "addresses": [
            {"address": "1abc", "last_activity_timestamp": 1_600_000_000, "dormant_years": 3.2},
        ],
    }

    rendered = render_wallet_report(report)

    assert "Bitcoin Core" in rendered
    assert "1abc" in rendered
    assert "docs/wallet_recovery_reference.md" in rendered
    assert "not an automated classifier" in rendered.lower() or "cross-check against your own memory" in rendered.lower()
