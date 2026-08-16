import json
import math
import os
import time
from collections import Counter

PROGRESS_EVERY_SECONDS = 0.5

# Small table of common file-format magic-byte headers. A match means the file
# is a known, explainable format -- not a hidden-volume candidate, even if its
# payload happens to be high-entropy (e.g. compressed data inside a ZIP).
KNOWN_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"\xff\xd8\xff": "JPEG",
    b"GIF87a": "GIF",
    b"GIF89a": "GIF",
    b"PK\x03\x04": "ZIP",
    b"\x1f\x8b": "GZIP",
    b"%PDF-": "PDF",
    b"\x7fELF": "ELF",
    b"MZ": "PE/EXE",
    b"SQLite format 3\x00": "SQLite",
}


def shannon_entropy(data):
    """
    Byte-level Shannon entropy of data, in bits/byte (0.0-8.0). Empty input
    returns 0.0.
    """
    if not data:
        return 0.0

    length = len(data)
    counts = Counter(data)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def has_known_signature(header_bytes):
    """
    Return the matched format name if header_bytes starts with any known
    magic-byte signature, else None.
    """
    for signature, name in KNOWN_SIGNATURES.items():
        if header_bytes.startswith(signature):
            return name
    return None


def looks_like_encrypted_container(file_path, min_size_bytes=1_000_000, entropy_threshold=7.9, sample_size=65536):
    """
    Heuristically flag a file as a likely encrypted-container candidate
    (VeraCrypt/TrueCrypt-style). Reads only the file's size plus up to three
    samples (head, middle, tail; each capped at sample_size bytes) -- never
    the whole file, so this stays cheap even against multi-GB files.

    Every condition below must hold: this is a "worth checking" signal, not a
    certainty -- some legitimately high-entropy, unsigned files can false
    positive. See docs/design-discussion.md for the known-limitation note.

    :return: {"path", "size", "entropy"} dict when flagged, else None.
    """
    size = os.path.getsize(file_path)

    if size < min_size_bytes:
        return None
    if size % 512 != 0:
        return None

    with open(file_path, "rb") as f:
        head = f.read(sample_size)

        if has_known_signature(head) is not None:
            return None

        samples = [head]
        if size > sample_size:
            middle_offset = max(0, (size // 2) - (sample_size // 2))
            f.seek(middle_offset)
            samples.append(f.read(sample_size))

            tail_offset = max(0, size - sample_size)
            if tail_offset > middle_offset:
                f.seek(tail_offset)
                samples.append(f.read(sample_size))

    combined = b"".join(samples)
    entropy = shannon_entropy(combined)

    if entropy < entropy_threshold:
        return None

    return {"path": file_path, "size": size, "entropy": entropy}


def scan_for_hidden_volumes(start_path, progress_callback=None):
    """
    Recursively walk start_path, applying looks_like_encrypted_container() to
    every file. No upper file-size skip -- unlike tools/search_wallets.py, that
    is the entire point of this tool.

    :param progress_callback: optional callable(current, total, message).
        total is always None -- same reasoning as search_for_wallets.py's
        walk: no way to know the file count ahead of time.
    :return: list of candidate dicts (see looks_like_encrypted_container).
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    candidates = []
    files_checked = 0
    last_progress_at = time.time()

    for root, dirs, files in os.walk(start_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                result = looks_like_encrypted_container(file_path)
            except OSError as e:
                print(f"Error accessing file {file_path}: {e}")
                continue
            if result:
                candidates.append(result)

            files_checked += 1
            if time.time() - last_progress_at >= PROGRESS_EVERY_SECONDS:
                progress_callback(files_checked, None, f"{len(candidates)} candidate(s) found so far — {root}")
                last_progress_at = time.time()

    progress_callback(files_checked, None, f"{len(candidates)} candidate(s) found — scan complete")
    return candidates


def render_hidden_volumes_report(candidates):
    """
    Plain-text report: lists candidates (worth-checking framing, never a
    certainty claim) followed by fixed manual-mount guidance. Always includes
    the guidance block, even with zero candidates, since it also carries the
    explicit no-auto-unlock disclaimer.
    """
    lines = ["# Hidden/Encrypted Volume Detection Report", ""]

    if candidates:
        lines.append(
            f"Found {len(candidates)} file(s) worth checking -- they look like they could be "
            "encrypted containers (no recognized file type, high entropy, sector-aligned size). "
            "This is a heuristic, not a confirmed finding:"
        )
        for candidate in candidates:
            lines.append(
                f"- `{candidate['path']}` -- size {candidate['size']} bytes, "
                f"entropy {candidate['entropy']:.2f}/8.0"
            )
    else:
        lines.append("No candidate files found.")
    lines.append("")

    lines.append("## Attempting to check a candidate")
    lines.append(
        "This tool does not attempt to unlock, guess, or crack anything itself -- it only "
        "detects and flags candidates. If you believe one of the files above is a real "
        "VeraCrypt or TrueCrypt volume, you can attempt to mount it yourself with your own "
        "remembered password using your own VeraCrypt installation, e.g.:"
    )
    lines.append("```")
    lines.append("veracrypt --text --mount <candidate-path>")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect files that look like encrypted containers (VeraCrypt/TrueCrypt-style)."
    )
    parser.add_argument("start_path", help="Directory to scan for candidate files.")
    parser.add_argument("output_file", help="Output JSON file for the candidate list.")
    args = parser.parse_args()

    candidates = scan_for_hidden_volumes(args.start_path)

    with open(args.output_file, "w") as f:
        json.dump(candidates, f, indent=4)

    report_file = os.path.splitext(args.output_file)[0] + ".md"
    with open(report_file, "w") as f:
        f.write(render_hidden_volumes_report(candidates))

    print(f"Found {len(candidates)} candidate(s). JSON saved to {args.output_file}, report saved to {report_file}.")
