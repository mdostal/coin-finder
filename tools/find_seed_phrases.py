import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mnemonic import Mnemonic

VALID_WORD_COUNTS = [12, 15, 18, 21, 24]
DEFAULT_MAX_FILE_SIZE = 10_000_000  # 10 MB -- unlikely a short handwritten note is bigger

_mnemo = Mnemonic("english")


def extract_words(text):
    """Tokenize text into lowercase words, stripping punctuation."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def find_candidate_phrases(text):
    """
    Slide a window over every valid BIP39 mnemonic length (12/15/18/21/24
    words) across text's tokenized words, keeping only windows that pass
    BIP39 checksum validation -- a real, strong filter (random wordlist-only
    text almost never satisfies it), not just "all words are in the wordlist."

    :return: [{"phrase": str, "word_count": int}, ...]
    """
    words = extract_words(text)
    candidates = []

    for length in VALID_WORD_COUNTS:
        for start in range(0, len(words) - length + 1):
            window = words[start : start + length]
            phrase = " ".join(window)
            if _mnemo.check(phrase):
                candidates.append({"phrase": phrase, "word_count": length})

    return candidates


def _looks_like_text(sample_bytes):
    """
    Cheap binary-vs-text pre-filter: a null byte anywhere in a sample is
    the standard signal a file is binary (the same heuristic git and
    `grep -I` use) -- a real seed phrase (space-separated lowercase
    wordlist words) cannot meaningfully appear in true binary data, so
    binary files are skipped entirely before the much more expensive
    tokenize + per-window BIP39 checksum pass runs.

    This matters at scale: scanning a large drive means most bytes belong
    to files (images, video, compiled binaries, archives) that could never
    contain a real candidate, and the checksum check is comparatively
    expensive -- skipping them here is a real, measured throughput win, not
    a correctness trade-off (no text file this project cares about
    legitimately contains a null byte).
    """
    return b"\x00" not in sample_bytes


def scan_directory(start_path, max_file_size=DEFAULT_MAX_FILE_SIZE):
    """
    Walk start_path, running find_candidate_phrases() against every
    text-looking file's content (read with errors="ignore"). Files above
    max_file_size, and files that look binary (see _looks_like_text), are
    skipped before any expensive tokenization/checksum work.

    :return: {file_path: [candidate phrase dicts]} -- files with zero
        candidates are omitted.
    """
    results = {}

    for root, dirs, files in os.walk(start_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                if os.path.getsize(file_path) > max_file_size:
                    continue
                with open(file_path, "rb") as f:
                    sample = f.read(8192)
                if not _looks_like_text(sample):
                    continue
                with open(file_path, "r", errors="ignore") as f:
                    text = f.read()
            except OSError as e:
                print(f"Error accessing file {file_path}: {e}")
                continue

            candidates = find_candidate_phrases(text)
            if candidates:
                results[file_path] = candidates

    return results


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Scan a directory for candidate BIP39 seed phrases (checksum-validated)."
    )
    parser.add_argument("start_path", help="Directory to scan.")
    parser.add_argument("output_file", help="Output JSON file for found candidate phrases.")
    args = parser.parse_args()

    results = scan_directory(args.start_path)

    with open(args.output_file, "w") as f:
        json.dump(results, f, indent=4)

    # Security: never print phrase text to stdout/logs -- it's real private-key
    # material. Only counts and the output file path are safe to print.
    total_candidates = sum(len(v) for v in results.values())
    print(f"Found {total_candidates} candidate phrase(s) across {len(results)} file(s). See {args.output_file}.")
    for file_path, candidates in results.items():
        print(f"  {file_path}: {len(candidates)} candidate(s)")
