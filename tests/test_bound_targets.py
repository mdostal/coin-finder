from unittest.mock import patch

from web.bound_targets import add_target, list_mounted_volumes, list_targets, remove_target


def test_add_target_creates_store_and_lists_it(tmp_path):
    store_path = tmp_path / "bound_targets.json"

    add_target("Old Drive", "/Volumes/OldDrive", "volume", store_path=store_path)

    targets = list_targets(store_path=store_path)
    assert len(targets) == 1
    assert targets[0]["label"] == "Old Drive"
    assert targets[0]["path"] == "/Volumes/OldDrive"
    assert targets[0]["kind"] == "volume"
    assert "added_at" in targets[0]


def test_add_multiple_targets_preserves_order(tmp_path):
    store_path = tmp_path / "bound_targets.json"

    add_target("A", "/a", "local", store_path=store_path)
    add_target("B", "/b", "local", store_path=store_path)

    labels = [t["label"] for t in list_targets(store_path=store_path)]
    assert labels == ["A", "B"]


def test_remove_target_only_removes_the_reference_not_the_path(tmp_path):
    store_path = tmp_path / "bound_targets.json"
    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    (real_dir / "file.txt").write_text("still here")

    add_target("Real", str(real_dir), "local", store_path=store_path)
    remove_target("Real", store_path=store_path)

    assert list_targets(store_path=store_path) == []
    assert real_dir.exists()
    assert (real_dir / "file.txt").read_text() == "still here"


def test_list_targets_on_missing_store_returns_empty_list(tmp_path):
    store_path = tmp_path / "does_not_exist.json"
    assert list_targets(store_path=store_path) == []


@patch("web.bound_targets.os.listdir")
@patch("web.bound_targets.sys.platform", "darwin")
def test_list_mounted_volumes_excludes_boot_volume(mock_listdir, tmp_path):
    mock_listdir.return_value = ["Macintosh HD", "OldDrive", "Backups2024"]

    with patch("web.bound_targets.VOLUMES_ROOT", str(tmp_path)):
        for name in mock_listdir.return_value:
            (tmp_path / name).mkdir()

        volumes = list_mounted_volumes(store_path=tmp_path / "bound_targets.json")

    names = [v["name"] for v in volumes]
    assert "Macintosh HD" not in names
    assert "OldDrive" in names
    assert "Backups2024" in names


@patch("web.bound_targets.os.listdir")
@patch("web.bound_targets.sys.platform", "darwin")
def test_list_mounted_volumes_marks_already_bound_volumes(mock_listdir, tmp_path):
    mock_listdir.return_value = ["OldDrive"]
    store_path = tmp_path / "bound_targets.json"

    with patch("web.bound_targets.VOLUMES_ROOT", str(tmp_path)):
        (tmp_path / "OldDrive").mkdir()
        add_target("Old", str(tmp_path / "OldDrive"), "volume", store_path=store_path)

        volumes = list_mounted_volumes(store_path=store_path)

    assert volumes[0]["is_bound"] is True


def test_list_mounted_volumes_on_non_macos_returns_empty_with_note(tmp_path):
    with patch("web.bound_targets.sys.platform", "linux"):
        volumes = list_mounted_volumes(store_path=tmp_path / "bound_targets.json")
    assert volumes == []
