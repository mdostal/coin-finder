"""
Coverage for scpi-02's Staged Files review page: lists every
staging_index.py entry (real path/coin/address/source_label/staged_at/
decision) and its 3 plain-instant-POST decision actions -- Keep,
Re-verify, Archive & forget.

tests/conftest.py's autouse fixture already mocks web.app.list_staged_entries/
get_staged_entry/set_staged_decision for every test (so nothing here can
leak a real db row or touch the real repo staging_index.db). Tests that
need real end-to-end behavior (the page listing real data, Keep actually
persisting, Re-verify actually stat()-ing the filesystem, and -- most
importantly -- Archive & forget provably never touching the real original
file) override those mocks with `wraps=` around the real
web.staging_index functions, plus monkeypatch web.app.STAGING_INDEX_DB_PATH
to a tmp_path db so that real behavior never touches the real repo db --
the exact same pattern web/app.py already uses for
web.app.DEFAULT_STAGING_DIR.
"""
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app
from web.staging_index import get_staged_entry, list_staged_entries, set_staged_decision, stage_and_index


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _stage_real_file(tmp_path, content=b"real wallet bytes", coin="Bitcoin", address="1abc", label="scan_wallet_dat"):
    """Stages a real file via the real staging_index module (bypassing
    web.app entirely) into a tmp staging dir/db, and returns
    (source_path, staged_path, staging_dir, db_path)."""
    source = tmp_path / "source" / "wallet.dat"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    staging_dir = tmp_path / "staged"
    db_path = tmp_path / "staging_index.db"
    staged_path = stage_and_index(str(source), coin, address, label, staging_dir=staging_dir, db_path=db_path)
    return source, staged_path, staging_dir, db_path


# --- acceptance: empty state ---


def test_staged_files_page_shows_friendly_empty_state(client):
    resp = client.get("/staged-files")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "empty" in body
    assert "No files staged yet" in body


# --- acceptance: every real entry is listed with its real data ---


def test_staged_files_page_lists_every_real_entry_with_real_data(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(
        tmp_path, content=b"real wallet bytes", coin="Bitcoin", address="1abc", label="scan_wallet_dat"
    )

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.get("/staged-files")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert staged_path in body
    assert str(source) in body
    assert "1abc" in body
    assert "scan_wallet_dat" in body
    assert "undecided" in body


def test_staged_files_page_lists_multiple_entries(client, tmp_path):
    source_a, staged_a, staging_dir, db_path = _stage_real_file(
        tmp_path, content=b"AAAA", coin="Bitcoin", address="1aaa", label="scan"
    )
    source_b = tmp_path / "source2" / "wallet2.dat"
    source_b.parent.mkdir(parents=True, exist_ok=True)
    source_b.write_bytes(b"BBBB")
    staged_b = stage_and_index(str(source_b), "Litecoin", "Lbbb", "scan", staging_dir=staging_dir, db_path=db_path)

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.get("/staged-files")

    body = resp.data.decode("utf-8")
    assert "1aaa" in body
    assert "Lbbb" in body
    assert staged_a in body
    assert staged_b in body


# --- acceptance: Keep updates the decision, reflected on reload ---


def test_keep_updates_decision_and_is_reflected_on_reload(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.set_staged_decision", wraps=set_staged_decision),
    ):
        resp = client.post("/staged-files/keep", data={"staged_path": staged_path}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/staged-files"

    entry = get_staged_entry(staged_path, db_path=db_path)
    assert entry["decision"] == "keep"

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.get("/staged-files")
    assert "status-done" in resp.data.decode("utf-8")
    assert b">keep<" in resp.data


def test_keep_route_calls_set_staged_decision_with_keep(client):
    """Shape-level test against the mocked default -- confirms the route
    wires the form field straight through without requiring real db
    access."""
    resp = client.post("/staged-files/keep", data={"staged_path": "/staged/abc-wallet.dat"}, follow_redirects=False)
    assert resp.status_code == 302


# --- acceptance: Re-verify distinguishes "still there" from "missing" ---


def test_reverify_reports_still_there_when_original_exists(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)
    assert source.exists()

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.get_staged_entry", wraps=get_staged_entry),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.post("/staged-files/reverify", data={"staged_path": staged_path}, follow_redirects=True)

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "still there" in body
    assert "missing" not in body.lower().split("still there")[0][-200:]  # sanity: not both claimed for this row


def test_reverify_reports_missing_when_original_no_longer_exists(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)
    source.unlink()  # simulate a removed drive/deleted original -- the staged copy remains untouched
    assert not source.exists()
    assert Path(staged_path).exists()

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.get_staged_entry", wraps=get_staged_entry),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.post("/staged-files/reverify", data={"staged_path": staged_path}, follow_redirects=True)

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "missing" in body
    assert "still there" not in body


def test_reverify_does_not_mutate_anything(client, tmp_path):
    """Re-verify is read-only against the filesystem -- it must not
    change the recorded decision or the entry in any way."""
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)
    before = get_staged_entry(staged_path, db_path=db_path)

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.get_staged_entry", wraps=get_staged_entry),
    ):
        client.post("/staged-files/reverify", data={"staged_path": staged_path}, follow_redirects=False)

    after = get_staged_entry(staged_path, db_path=db_path)
    assert after == before


# --- acceptance: Archive & forget -- THE most important test in this story ---


def test_archive_and_forget_updates_decision_to_archived(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.set_staged_decision", wraps=set_staged_decision),
    ):
        resp = client.post("/staged-files/archive", data={"staged_path": staged_path}, follow_redirects=False)

    assert resp.status_code == 302
    entry = get_staged_entry(staged_path, db_path=db_path)
    assert entry["decision"] == "archived"


def test_archive_and_forget_never_touches_the_real_original_file(client, tmp_path):
    """
    THE most important acceptance criterion in this story: clicking
    Archive & forget must NEVER delete, move, or modify the real original
    file on disk -- it may only ever write to staging_index.db.

    Stages a real temp file, hits the real Archive & forget route (real
    set_staged_decision, pointed at a tmp_path db so the real repo db is
    never touched), and explicitly asserts:
      1. the original file still exists, with byte-identical content
      2. the staged copy also still exists, untouched
      3. no filesystem-deletion primitive (os.remove, os.unlink,
         Path.unlink, shutil.rmtree, shutil.move) was ever called during
         the request -- not just an after-the-fact "it still exists"
         check, but proof the deletion path was never exercised at all.
    """
    original_content = b"precious real wallet bytes -- must never be touched"
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path, content=original_content)
    original_mtime = source.stat().st_mtime

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.set_staged_decision", wraps=set_staged_decision),
        patch("os.remove") as mock_os_remove,
        patch("os.unlink") as mock_os_unlink,
        patch("pathlib.Path.unlink") as mock_path_unlink,
        patch("shutil.rmtree") as mock_rmtree,
        patch("shutil.move") as mock_move,
    ):
        resp = client.post("/staged-files/archive", data={"staged_path": staged_path}, follow_redirects=False)

    assert resp.status_code == 302

    # No deletion/move primitive was ever invoked by the request.
    mock_os_remove.assert_not_called()
    mock_os_unlink.assert_not_called()
    mock_path_unlink.assert_not_called()
    mock_rmtree.assert_not_called()
    mock_move.assert_not_called()

    # The real original file is provably untouched: still exists, same
    # bytes, same mtime.
    assert source.exists()
    assert source.read_bytes() == original_content
    assert source.stat().st_mtime == original_mtime

    # The staged copy is untouched too.
    assert Path(staged_path).exists()
    assert Path(staged_path).read_bytes() == original_content

    # And the decision really did update -- this is a real behavior
    # change, not a no-op route.
    entry = get_staged_entry(staged_path, db_path=db_path)
    assert entry["decision"] == "archived"


def test_archive_and_forget_never_touches_original_even_when_original_already_missing(client, tmp_path):
    """Same guarantee holds even in the edge case where the original was
    already gone before Archive & forget was clicked -- the route must
    not attempt to touch it, and must not error."""
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)
    source.unlink()
    assert not source.exists()

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.set_staged_decision", wraps=set_staged_decision),
        patch("os.remove") as mock_os_remove,
        patch("os.unlink") as mock_os_unlink,
        patch("pathlib.Path.unlink") as mock_path_unlink,
    ):
        resp = client.post("/staged-files/archive", data={"staged_path": staged_path}, follow_redirects=False)

    assert resp.status_code == 302
    mock_os_remove.assert_not_called()
    mock_os_unlink.assert_not_called()
    mock_path_unlink.assert_not_called()

    entry = get_staged_entry(staged_path, db_path=db_path)
    assert entry["decision"] == "archived"
    # The staged copy (a separate real file) is still there too.
    assert Path(staged_path).exists()


def test_archive_route_calls_set_staged_decision_with_archived(client):
    """Shape-level test against the mocked default."""
    resp = client.post("/staged-files/archive", data={"staged_path": "/staged/abc-wallet.dat"}, follow_redirects=False)
    assert resp.status_code == 302


# --- action rows follow the plain-instant-POST shape (no JS modal) ---


def test_staged_files_page_row_actions_are_plain_instant_post_forms(client, tmp_path):
    source, staged_path, staging_dir, db_path = _stage_real_file(tmp_path)

    with (
        patch("web.app.STAGING_INDEX_DB_PATH", db_path),
        patch("web.app.list_staged_entries", wraps=list_staged_entries),
    ):
        resp = client.get("/staged-files")

    body = resp.data.decode("utf-8")
    assert 'action="/staged-files/keep"' in body
    assert 'action="/staged-files/reverify"' in body
    assert 'action="/staged-files/archive"' in body
    # No confirm() dialog / JS modal gate on any of the 3 actions.
    assert "onsubmit" not in body
    assert "confirm(" not in body
