import json
import os
import subprocess
import sys

from tools.find_seed_phrases import extract_words, find_candidate_phrases, scan_directory

# Well-known PUBLIC BIP39 test vector -- a standard fixture used throughout
# BIP39 tooling and documentation, not a real wallet. Safe to use in tests.
TEST_VECTOR = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


def test_extract_words_lowercases_and_strips_punctuation():
    text = "Hello, World! This -- is a test."

    words = extract_words(text)

    assert words == ["hello", "world", "this", "is", "a", "test"]


def test_finds_valid_test_vector_embedded_in_prose():
    text = f"Here are some notes: {TEST_VECTOR} and that's everything."

    candidates = find_candidate_phrases(text)

    assert len(candidates) == 1
    assert candidates[0]["phrase"] == TEST_VECTOR
    assert candidates[0]["word_count"] == 12


def test_wordlist_words_without_valid_checksum_are_not_candidates():
    # 12 words all in the BIP39 wordlist, but not a valid mnemonic (bad checksum).
    text = "abandon ability able about above absent absorb abstract absurd abuse access accident"

    candidates = find_candidate_phrases(text)

    assert candidates == []


def test_ordinary_prose_has_no_candidates():
    text = "The quick brown fox jumps over the lazy dog near the riverbank every single morning."

    candidates = find_candidate_phrases(text)

    assert candidates == []


def test_scan_directory_finds_only_the_file_with_a_valid_phrase(tmp_path):
    (tmp_path / "notes.txt").write_text(f"backup phrase: {TEST_VECTOR}")
    (tmp_path / "shopping_list.txt").write_text("milk eggs bread butter")

    results = scan_directory(str(tmp_path))

    assert list(results.keys()) == [str(tmp_path / "notes.txt")]
    assert results[str(tmp_path / "notes.txt")][0]["phrase"] == TEST_VECTOR


def test_scan_directory_skips_files_above_max_file_size(tmp_path):
    big_file = tmp_path / "big.txt"
    big_file.write_text(TEST_VECTOR + " " + ("padding " * 1000))

    results = scan_directory(str(tmp_path), max_file_size=10)

    assert results == {}


def test_cli_never_prints_phrase_text_to_stdout_but_writes_it_to_output_file(tmp_path):
    (tmp_path / "notes.txt").write_text(f"backup phrase: {TEST_VECTOR}")
    output_file = tmp_path / "found.json"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    result = subprocess.run(
        [sys.executable, "tools/find_seed_phrases.py", str(tmp_path), str(output_file)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert TEST_VECTOR not in result.stdout
    assert TEST_VECTOR not in result.stderr

    data = json.loads(output_file.read_text())
    assert data[str(tmp_path / "notes.txt")][0]["phrase"] == TEST_VECTOR
