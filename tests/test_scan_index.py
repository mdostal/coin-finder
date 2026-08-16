from tools.scan_index import (
    clear_scan_index,
    hash_file_bytes,
    is_known,
    list_scanned_files,
    record_scanned_file,
)


def test_hash_file_bytes_is_deterministic_and_content_based():
    h1 = hash_file_bytes(b"hello wallet")
    h2 = hash_file_bytes(b"hello wallet")
    h3 = hash_file_bytes(b"different content")
    assert h1 == h2
    assert h1 != h3


def test_is_known_returns_none_for_unseen_hash(tmp_path):
    db_path = tmp_path / "scan_index.db"
    assert is_known("deadbeef", db_path=db_path) is None


def test_record_then_is_known_returns_the_result(tmp_path):
    db_path = tmp_path / "scan_index.db"
    file_hash = hash_file_bytes(b"wallet content")
    results = {"Bitcoin": ["1abc"]}

    record_scanned_file(file_hash, "/path/a/wallet.dat", results, db_path=db_path)

    assert is_known(file_hash, db_path=db_path) == results


def test_same_content_different_path_is_recognized_as_duplicate(tmp_path):
    """The whole point: a copy of the same file on a different drive/backup
    must be recognized by content, regardless of where it now lives."""
    db_path = tmp_path / "scan_index.db"
    content = b"identical wallet bytes"
    file_hash = hash_file_bytes(content)
    record_scanned_file(file_hash, "/driveA/wallet.dat", {"Bitcoin": ["1abc"]}, db_path=db_path)

    # A second "discovery" of the same content at a different path resolves
    # to the same hash and is recognized without re-recording.
    assert is_known(hash_file_bytes(content), db_path=db_path) == {"Bitcoin": ["1abc"]}


def test_list_scanned_files_returns_metadata(tmp_path):
    db_path = tmp_path / "scan_index.db"
    record_scanned_file(hash_file_bytes(b"a"), "/a.dat", {}, db_path=db_path)
    record_scanned_file(hash_file_bytes(b"b"), "/b.dat", {"Bitcoin": ["1x"]}, db_path=db_path)

    files = list_scanned_files(db_path=db_path)

    assert len(files) == 2
    paths = {f["file_path"] for f in files}
    assert paths == {"/a.dat", "/b.dat"}


def test_clear_scan_index_deletes_everything(tmp_path):
    db_path = tmp_path / "scan_index.db"
    record_scanned_file(hash_file_bytes(b"a"), "/a.dat", {}, db_path=db_path)

    clear_scan_index(db_path=db_path)

    assert list_scanned_files(db_path=db_path) == []
    assert is_known(hash_file_bytes(b"a"), db_path=db_path) is None


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "scan_index.db"
    record_scanned_file(hash_file_bytes(b"a"), "/a.dat", {}, db_path=db_path)
    assert db_path.exists()
