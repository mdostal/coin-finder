import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

from tools.match_seed_phrases import (
    check_derived_balances,
    derive_candidate_addresses,
    load_phrases_from_file,
    match_phrases,
    render_match_report,
)

# Well-known PUBLIC BIP39 test vector -- a standard fixture used throughout
# BIP39/BIP44 tooling and documentation, not a real wallet. Safe to use in
# tests. Its derived addresses below are the publicly documented test-vector
# addresses for this exact mnemonic (verified live during epic research).
TEST_VECTOR = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

EXPECTED_BIP44_BTC_0 = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"
EXPECTED_BIP49_BTC_0 = "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"
EXPECTED_BIP84_BTC_0 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
EXPECTED_BIP44_ETH_0 = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"


def test_derive_candidate_addresses_matches_known_test_vectors():
    derived = derive_candidate_addresses(TEST_VECTOR, num_addresses=1)

    addresses = {(d["scheme"], d["coin"]): d["address"] for d in derived}
    assert addresses[("BIP44", "Bitcoin")] == EXPECTED_BIP44_BTC_0
    assert addresses[("BIP49", "Bitcoin")] == EXPECTED_BIP49_BTC_0
    assert addresses[("BIP84", "Bitcoin")] == EXPECTED_BIP84_BTC_0
    assert addresses[("BIP44", "Ethereum")].lower() == EXPECTED_BIP44_ETH_0.lower()


def test_derive_candidate_addresses_never_includes_private_key_material():
    derived = derive_candidate_addresses(TEST_VECTOR, num_addresses=1)

    for entry in derived:
        assert "private_key" not in entry
        assert "wif" not in entry
        assert set(entry.keys()) == {"scheme", "coin", "index", "address"}


def test_derive_candidate_addresses_respects_num_addresses():
    derived = derive_candidate_addresses(TEST_VECTOR, num_addresses=3)

    btc44_indices = sorted(d["index"] for d in derived if d["scheme"] == "BIP44" and d["coin"] == "Bitcoin")
    assert btc44_indices == [0, 1, 2]


@patch("tools.match_seed_phrases.load_service_for_coin")
def test_check_derived_balances_populates_balance_field(mock_load_service):
    fake_service = MagicMock()
    fake_service.check_balance.return_value = 1.5
    mock_load_service.return_value = fake_service

    derived = [{"scheme": "BIP44", "coin": "Bitcoin", "index": 0, "address": "1abc"}]
    result = check_derived_balances(derived)

    assert result[0]["balance"] == 1.5


@patch("tools.match_seed_phrases.load_service_for_coin")
def test_check_derived_balances_skips_gracefully_when_service_unavailable(mock_load_service):
    mock_load_service.return_value = None

    derived = [{"scheme": "BIP44", "coin": "Ethereum", "index": 0, "address": "0xabc"}]
    result = check_derived_balances(derived)

    assert result[0]["balance"] is None


def test_load_phrases_from_find_seed_phrases_output_shape(tmp_path):
    input_file = tmp_path / "found.json"
    input_file.write_text(json.dumps({
        "/some/file.txt": [{"phrase": TEST_VECTOR, "word_count": 12}],
        "/other/file.txt": [{"phrase": TEST_VECTOR, "word_count": 12}],
    }))

    phrases = load_phrases_from_file(str(input_file))

    assert phrases == [TEST_VECTOR]


def test_load_phrases_from_plain_newline_file(tmp_path):
    input_file = tmp_path / "phrases.txt"
    input_file.write_text(f"{TEST_VECTOR}\n")

    phrases = load_phrases_from_file(str(input_file))

    assert phrases == [TEST_VECTOR]


def test_report_includes_phrase_text_only_for_findings():
    results = {
        TEST_VECTOR: [
            {"scheme": "BIP44", "coin": "Bitcoin", "index": 0, "address": "1abc", "balance": 2.0},
        ],
        "some other non finding phrase words here twelve total words padded": [
            {"scheme": "BIP44", "coin": "Bitcoin", "index": 0, "address": "1def", "balance": 0.0},
        ],
    }

    report = render_match_report(results)

    assert TEST_VECTOR in report
    assert "some other non finding phrase words here twelve total words padded" not in report
    assert "no balance found" in report.lower()


@patch("tools.match_seed_phrases.load_service_for_coin")
def test_cli_never_prints_phrase_text_to_stdout(mock_load_service, tmp_path):
    fake_service = MagicMock()
    fake_service.check_balance.return_value = 0.0
    mock_load_service.return_value = fake_service

    phrases_file = tmp_path / "phrases.txt"
    phrases_file.write_text(f"{TEST_VECTOR}\n")
    output_file = tmp_path / "matches.json"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Note: this subprocess call is not mocked (real bip_utils derivation,
    # but check_derived_balances is exercised via the CLI's own import of
    # load_service_for_coin -- since we can't patch across a subprocess
    # boundary, this test only checks stdout safety with real (fast, offline)
    # derivation and accepts real network calls for the balance step.
    result = subprocess.run(
        [sys.executable, "tools/match_seed_phrases.py", str(phrases_file), str(output_file)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert TEST_VECTOR not in result.stdout
    assert TEST_VECTOR not in result.stderr
