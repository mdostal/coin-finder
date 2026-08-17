from web.scan_excludes import add_exclude, list_excludes, remove_exclude


def test_add_exclude_creates_store_and_lists_it(tmp_path):
    store_path = tmp_path / "scan_excludes.json"

    add_exclude("/Volumes/OldDrive/junk", store_path=store_path)

    excludes = list_excludes(store_path=store_path)
    assert len(excludes) == 1
    assert excludes[0]["path"] == "/Volumes/OldDrive/junk"
    assert "added_at" in excludes[0]


def test_add_exclude_is_idempotent(tmp_path):
    store_path = tmp_path / "scan_excludes.json"

    add_exclude("/a", store_path=store_path)
    add_exclude("/a", store_path=store_path)

    assert len(list_excludes(store_path=store_path)) == 1


def test_remove_exclude_removes_only_the_matching_entry(tmp_path):
    store_path = tmp_path / "scan_excludes.json"
    add_exclude("/a", store_path=store_path)
    add_exclude("/b", store_path=store_path)

    remove_exclude("/a", store_path=store_path)

    paths = [e["path"] for e in list_excludes(store_path=store_path)]
    assert paths == ["/b"]


def test_fresh_store_starts_empty_no_built_in_blocklist(tmp_path):
    store_path = tmp_path / "scan_excludes.json"
    assert list_excludes(store_path=store_path) == []
