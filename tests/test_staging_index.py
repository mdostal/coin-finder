import logging
import shutil
from pathlib import Path
from unittest.mock import patch

from web.staging_index import (
    SIZE_WARNING_THRESHOLD_BYTES,
    get_staged_entry,
    list_staged_entries,
    stage_and_index,
)


def _make_file(path, content=b"wallet contents"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_stage_and_index_copies_file_and_records_entry(tmp_path):
    source = _make_file(tmp_path / "wallet.dat")
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"

    staged_path = stage_and_index(
        str(source), "Bitcoin", "1abc", "scan_wallet_dat", staging_dir=staging_dir, db_path=db_path
    )

    staged = list(staging_dir.iterdir())
    assert len(staged) == 1
    assert staged[0].name.endswith("-wallet.dat")
    assert staged_path == str(staged[0])
    assert staged[0].read_bytes() == b"wallet contents"

    entry = get_staged_entry(staged_path, db_path=db_path)
    assert entry is not None
    assert entry["original_source_path"] == str(source)
    assert entry["coin"] == "Bitcoin"
    assert entry["address"] == "1abc"
    assert entry["source_label"] == "scan_wallet_dat"
    assert entry["decision"] == "undecided"
    assert entry["staged_at"] > 0
    assert entry["size_bytes"] == len(b"wallet contents")


def test_multiple_findings_sharing_one_source_file_stage_it_once(tmp_path):
    """Acceptance: multiple addresses backed by the same real file must only produce one staged copy / one index entry."""
    source = _make_file(tmp_path / "wallet.dat")
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"

    with patch("web.staging_index.shutil.copy2", wraps=shutil.copy2) as mock_copy2:
        first = stage_and_index(str(source), "Bitcoin", "1aaa", "scan", staging_dir=staging_dir, db_path=db_path)
        second = stage_and_index(str(source), "Bitcoin", "1bbb", "scan", staging_dir=staging_dir, db_path=db_path)
        third = stage_and_index(str(source), "Litecoin", "Laaa", "scan", staging_dir=staging_dir, db_path=db_path)

    assert first == second == third
    assert mock_copy2.call_count == 1

    entries = list_staged_entries(db_path=db_path)
    assert len(entries) == 1
    # First call's coin/address wins; later shared-file calls don't overwrite it.
    assert entries[0]["address"] == "1aaa"


def test_two_files_with_same_basename_both_stage_with_distinct_paths(tmp_path):
    source_a = _make_file(tmp_path / "a" / "wallet.dat", content=b"AAAA")
    source_b = _make_file(tmp_path / "b" / "wallet.dat", content=b"BBBB")
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"

    staged_a = stage_and_index(str(source_a), "Bitcoin", "1aaa", "scan", staging_dir=staging_dir, db_path=db_path)
    staged_b = stage_and_index(str(source_b), "Bitcoin", "1bbb", "scan", staging_dir=staging_dir, db_path=db_path)

    assert staged_a != staged_b
    assert Path(staged_a).exists()
    assert Path(staged_b).exists()
    entries = list_staged_entries(db_path=db_path)
    assert len(entries) == 2


def test_same_file_staged_twice_resolves_to_same_path_no_duplicate_copy_or_error(tmp_path):
    source = _make_file(tmp_path / "wallet.dat")
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"

    first = stage_and_index(str(source), "Bitcoin", "1abc", "scan_wallet_dat", staging_dir=staging_dir, db_path=db_path)

    with patch("web.staging_index.shutil.copy2") as mock_copy2:
        second = stage_and_index(
            str(source), "Bitcoin", "1abc", "scan_wallet_dat", staging_dir=staging_dir, db_path=db_path
        )

    assert first == second
    mock_copy2.assert_not_called()
    assert len(list(staging_dir.iterdir())) == 1
    assert len(list_staged_entries(db_path=db_path)) == 1


def test_size_warning_logs_once_when_crossing_1gb_threshold(tmp_path, caplog):
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"

    source_1 = _make_file(tmp_path / "one.dat")
    source_2 = _make_file(tmp_path / "two.dat")
    source_3 = _make_file(tmp_path / "three.dat")

    just_under = SIZE_WARNING_THRESHOLD_BYTES - 100
    pushes_over = 200

    with caplog.at_level(logging.WARNING, logger="web.staging_index"):
        with patch("web.staging_index._file_size", return_value=just_under):
            stage_and_index(str(source_1), "Bitcoin", "1aaa", "scan", staging_dir=staging_dir, db_path=db_path)
        assert not any("1GB" in r.message or "GB" in r.message for r in caplog.records)

        with patch("web.staging_index._file_size", return_value=pushes_over):
            stage_and_index(str(source_2), "Bitcoin", "1bbb", "scan", staging_dir=staging_dir, db_path=db_path)
        assert any("GB" in r.message for r in caplog.records)

        warning_count_after_crossing = len(caplog.records)

        # A further stage call, still over threshold, must NOT log again --
        # this is a "first time it crosses" warning, not a per-call one.
        with patch("web.staging_index._file_size", return_value=pushes_over):
            stage_and_index(str(source_3), "Bitcoin", "1ccc", "scan", staging_dir=staging_dir, db_path=db_path)

        assert len(caplog.records) == warning_count_after_crossing
