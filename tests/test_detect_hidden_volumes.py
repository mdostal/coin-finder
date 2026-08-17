import json
import os
import subprocess
import sys

from tools.detect_hidden_volumes import (
    has_known_signature,
    looks_like_encrypted_container,
    render_hidden_volumes_report,
    scan_for_hidden_volumes,
    shannon_entropy,
)


def test_all_zero_bytes_has_zero_entropy():
    assert shannon_entropy(bytes(4096)) == 0.0


def test_random_bytes_have_high_entropy():
    assert shannon_entropy(os.urandom(4096)) >= 7.9


def test_empty_bytes_has_zero_entropy_without_raising():
    assert shannon_entropy(b"") == 0.0


def test_known_png_signature_is_detected():
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    assert has_known_signature(png_header) == "PNG"


def test_known_zip_signature_is_detected():
    zip_header = b"PK\x03\x04" + b"\x00" * 100
    assert has_known_signature(zip_header) == "ZIP"


def test_unknown_signature_returns_none():
    random_header = os.urandom(64)
    # Extremely unlikely to collide with a known signature by chance.
    assert has_known_signature(random_header) is None


def test_file_below_min_size_is_not_flagged_even_if_high_entropy(tmp_path):
    small_file = tmp_path / "small.bin"
    small_file.write_bytes(os.urandom(512))  # below default 1_000_000 floor

    result = looks_like_encrypted_container(str(small_file))

    assert result is None


def test_file_not_a_multiple_of_512_is_not_flagged(tmp_path):
    odd_file = tmp_path / "odd.bin"
    odd_file.write_bytes(os.urandom(1_000_001))  # large enough, but not % 512 == 0

    result = looks_like_encrypted_container(str(odd_file), min_size_bytes=1_000_000)

    assert result is None


def test_file_with_known_signature_is_not_flagged_even_if_padded_high_entropy(tmp_path):
    signed_file = tmp_path / "signed.bin"
    size = 1_048_576  # 1 MiB, multiple of 512
    content = b"\x89PNG\r\n\x1a\n" + os.urandom(size - 8)
    signed_file.write_bytes(content)

    result = looks_like_encrypted_container(str(signed_file), min_size_bytes=1_000_000)

    assert result is None


def test_large_sector_sized_high_entropy_unsigned_file_is_flagged(tmp_path):
    container_like = tmp_path / "container.bin"
    size = 1_048_576  # 1 MiB, multiple of 512
    container_like.write_bytes(os.urandom(size))

    result = looks_like_encrypted_container(str(container_like), min_size_bytes=1_000_000)

    assert result is not None
    assert result["path"] == str(container_like)
    assert result["size"] == size
    assert result["entropy"] >= 7.9


def test_container_detection_never_reads_more_than_three_samples(tmp_path, monkeypatch):
    container_like = tmp_path / "huge.bin"
    size = 2_097_152  # 2 MiB, multiple of 512
    container_like.write_bytes(os.urandom(size))

    read_calls = []
    real_open = open

    def counting_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        original_read = handle.read

        def counting_read(*a, **kw):
            data = original_read(*a, **kw)
            read_calls.append(len(data))
            return data

        handle.read = counting_read
        return handle

    monkeypatch.setattr("builtins.open", counting_open)

    looks_like_encrypted_container(str(container_like), min_size_bytes=1_000_000, sample_size=65536)

    assert len(read_calls) <= 3
    assert sum(read_calls) <= 3 * 65536


def test_scan_finds_only_the_container_like_file(tmp_path):
    (tmp_path / "notes.txt").write_text("just a normal small text file")
    container_like = tmp_path / "backup.dat"
    container_like.write_bytes(os.urandom(1_048_576))  # 1 MiB, multiple of 512

    results = scan_for_hidden_volumes(str(tmp_path))

    assert len(results) == 1
    assert results[0]["path"] == str(container_like)


def test_scan_returns_empty_list_when_no_candidates(tmp_path):
    (tmp_path / "notes.txt").write_text("just a normal small text file")

    results = scan_for_hidden_volumes(str(tmp_path))

    assert results == []


def test_report_lists_candidate_paths_with_worth_checking_framing():
    candidates = [{"path": "/drive/backup.dat", "size": 1_048_576, "entropy": 7.99}]

    report = render_hidden_volumes_report(candidates)

    assert "/drive/backup.dat" in report
    assert "IS encrypted" not in report
    assert "worth checking" in report.lower() or "candidate" in report.lower()


def test_report_always_includes_manual_mount_guidance_and_no_auto_unlock_statement():
    empty_report = render_hidden_volumes_report([])
    nonempty_report = render_hidden_volumes_report(
        [{"path": "/drive/backup.dat", "size": 1_048_576, "entropy": 7.99}]
    )

    for report in (empty_report, nonempty_report):
        assert "veracrypt" in report.lower()
        assert "does not" in report.lower() or "never" in report.lower()
        assert "unlock" in report.lower() or "crack" in report.lower()


def test_cli_writes_json_and_markdown_report(tmp_path):
    container_like = tmp_path / "backup.dat"
    container_like.write_bytes(os.urandom(1_048_576))
    output_file = tmp_path / "hidden_volumes.json"

    subprocess_result = subprocess.run(
        [sys.executable, "tools/detect_hidden_volumes.py", str(tmp_path), str(output_file)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
    )

    assert subprocess_result.returncode == 0, subprocess_result.stderr
    assert output_file.exists()
    report_file = output_file.with_suffix(".md")
    assert report_file.exists()

    data = json.loads(output_file.read_text())
    assert len(data) == 1
    assert data[0]["path"] == str(container_like)


def test_scan_for_hidden_volumes_reports_indeterminate_progress(tmp_path, monkeypatch):
    import tools.detect_hidden_volumes as detect_hidden_volumes_module

    monkeypatch.setattr(detect_hidden_volumes_module, "PROGRESS_EVERY_SECONDS", 0)

    (tmp_path / "random.bin").write_bytes(os.urandom(4096))

    calls = []
    scan_for_hidden_volumes(str(tmp_path), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls
    assert all(total is None for _, total, _ in calls)
    assert calls[-1][0] == 1  # one file checked
