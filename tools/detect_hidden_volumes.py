import math
import os
from collections import Counter

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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect files that look like encrypted containers (VeraCrypt/TrueCrypt-style)."
    )
    parser.add_argument("file", help="Path to a single file to check.")
    args = parser.parse_args()

    result = looks_like_encrypted_container(args.file)
    if result:
        print(f"Candidate: {result}")
    else:
        print("Not flagged as a likely encrypted container.")
