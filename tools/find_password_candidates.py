"""
Scan a directory for password/credential-shaped text sitting in ordinary
notes/text files.

This is the third file-finder in this project, alongside
tools/search_wallets.py (filename-driven wallet-file discovery) and
tools/find_seed_phrases.py (content-driven, BIP39-checksum-validated seed
phrase discovery). This one is content-driven like find_seed_phrases.py --
it reuses that module's exact file-discovery shape: walk every file under
a path with no filename/extension allowlist at all, skip files over 10MB,
and skip anything that sniffs as binary (see
tools.find_seed_phrases._looks_like_text) before ever trying to match
anything. It deliberately does NOT work like search_wallets.py, which is
purely filename-driven -- a password/credential note has no reason to be
named anything wallet-shaped.

HONEST LIMITATION, stated up front and not papered over anywhere in this
module: unlike a coin address (Base58Check/bech32 checksum) or a BIP39
seed phrase (its own checksum, see find_seed_phrases.py), there is no
structural validator for "this text is a real password." The two
heuristics below (find_candidate_lines()) are genuinely best-effort and
carry a real, non-zero false-positive rate -- see
tests/test_find_password_candidates.py's measured-false-positive-rate
test for the actual numbers against a representative test corpus. This is
exactly why this scanner's output is called "candidates" everywhere (never
"findings"), is surfaced through a human review UI (web/app.py's
password-scan route), and this module never calls record_finding() or
writes to findings.db or any vault store -- its output must never be
mistaken for a verified/recovered balance the way checksum-backed matches
elsewhere in this codebase are.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.search import COIN_NAMES, WALLET_KEYWORDS
from tools.find_seed_phrases import _looks_like_text

DEFAULT_MAX_FILE_SIZE = 10_000_000  # 10 MB -- same cap as find_seed_phrases.py; a
# password/credential note is never legitimately bigger than that.

# Explicit credential labels (case-insensitive), each followed by a ":" or
# "=" separator and a non-whitespace value on the same line. \b...\b
# boundaries keep this from matching "pass" inside "compass" or "pw"
# inside "growpw", etc. The value itself is NOT shape-checked -- an
# explicit label is already a strong signal on its own, unlike the
# coin-proximity path below.
#
# Known residual false-positive class, accepted rather than hidden: "pass"
# is also common English shorthand for pass/fail ("Pass: yes"), so a line
# like that will match here. This is an intentional trade-off -- "pass:"
# is one of the label forms this scanner is required to catch (see the
# story's acceptance criteria), and there is no way to distinguish
# "pass: <grade>" from "pass: <password>" from text shape alone.
_LABEL_RE = re.compile(r"\b(password|passphrase|pwd|pw|pass)\b\s*[:=]\s*(\S+)", re.IGNORECASE)

# Coin/wallet keyword proximity anchor -- reuses config/search.py's
# existing COIN_NAMES/WALLET_KEYWORDS lists verbatim (per the story's
# design decision) rather than duplicating them here.
_COIN_KEYWORDS = sorted(set(COIN_NAMES) | set(WALLET_KEYWORDS), key=len, reverse=True)
_COIN_KEYWORDS_LOWER = {k.lower() for k in _COIN_KEYWORDS}
_COIN_MENTION_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _COIN_KEYWORDS) + r")\b", re.IGNORECASE)

# "Plausible password-shaped token" tuning, used only for the
# coin-proximity path (the label path above doesn't shape-check its
# value). Trimmed of common sentence-boundary punctuation before judging.
_TOKEN_STRIP_CHARS = ".,;:!?()[]{}\"'"
_MIN_TOKEN_LEN = 8
_MAX_TOKEN_LEN = 64
# Plain lowercase-alpha tokens (no digit/special/mixed-case) need to clear
# this length before being treated as password-shaped -- tuned (and
# measured, see tests) so ordinary long English words in prose ("
# characteristically", "internationalization") mostly fall under it, while
# a concatenated passphrase like "correcthorsebatterystaple" (25 chars)
# comfortably clears it. This is a tuning knob, not a guarantee -- some
# rare long English words will still clear it; that residual risk is part
# of the measured false-positive rate, not eliminated by it.
_LONG_WORD_THRESHOLD = 20
_SPECIAL_CHARS = set("!@#$%^&*_-+=.")


def _clean_token(token):
    """Strip common sentence-boundary punctuation from both ends of a whitespace-split token."""
    return token.strip(_TOKEN_STRIP_CHARS)


def _looks_password_shaped(token):
    """
    Best-effort shape heuristic for the coin-proximity path only -- NOT a
    validator (see module docstring). True for a token that "could
    plausibly be a password": within a sane length range, no internal
    whitespace, and either shows real character-class variety (a digit, a
    special character, or mixed upper/lower case) or -- since a real
    passphrase like "correcthorsebatterystaple" can be pure lowercase
    letters with zero digits -- is an unbroken run of lowercase letters
    long enough (see _LONG_WORD_THRESHOLD) that it's unlikely to just be
    an ordinary English word picked up from surrounding prose.
    """
    token = _clean_token(token)
    if not (_MIN_TOKEN_LEN <= len(token) <= _MAX_TOKEN_LEN):
        return False
    if any(ch.isspace() for ch in token):
        return False

    has_digit = any(ch.isdigit() for ch in token)
    has_special = any(ch in _SPECIAL_CHARS for ch in token)
    # Deliberately "internal" uppercase (position 1+), not just "has any
    # uppercase letter" -- a token with only its first letter capitalized
    # ("Bitcoin's", "Foundation") is ordinary English sentence-case/
    # proper-noun capitalization, not a real password-shape signal, and
    # counting it caused measured false positives (see
    # tests/test_find_password_candidates.py's FP-rate test) on coin-name
    # lines that simply capitalize the coin name or a nearby proper noun.
    # A real mixed-case password ("Tr0ub4dor&3", "aXbYcZ12") has a case
    # switch somewhere after the first character.
    has_internal_upper = any(ch.isupper() for ch in token[1:])
    has_lower = any(ch.islower() for ch in token)

    if has_digit or has_special or (has_internal_upper and has_lower):
        return True
    return token.isalpha() and token.islower() and len(token) >= _LONG_WORD_THRESHOLD


def find_candidate_lines(text):
    """
    Scan text line by line for password/credential candidates, using two
    independent heuristics (see module docstring for why there's no
    structural validator to fall back on, unlike find_seed_phrases.py):

      1. "label" -- an explicit credential label ("password:", "pw:",
         "pass:", "passphrase:", "pwd:", case-insensitive) followed by a
         value on the same line.
      2. "coin-proximity" -- a password-shaped token (_looks_password_shaped)
         on a line that also mentions a coin/wallet keyword from
         config/search.py's COIN_NAMES/WALLET_KEYWORDS.

    A single line can produce candidates from both paths independently.

    :return: [{"line_number": int, "line": str, "matched_value": str,
        "match_type": "label"|"coin-proximity", "detail": str}, ...]
        line_number is 1-indexed. "detail" is the matched label word for
        "label" candidates, or the matched coin/wallet keyword for
        "coin-proximity" candidates.
    """
    candidates = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        for match in _LABEL_RE.finditer(line):
            label, value = match.group(1), match.group(2)
            candidates.append(
                {
                    "line_number": line_number,
                    "line": stripped_line,
                    "matched_value": value,
                    "match_type": "label",
                    "detail": label.lower(),
                }
            )

        coin_match = _COIN_MENTION_RE.search(line)
        if coin_match:
            coin_keyword = coin_match.group(1).lower()
            for raw_token in line.split():
                token = _clean_token(raw_token)
                if not token or token.lower() in _COIN_KEYWORDS_LOWER:
                    continue
                if _looks_password_shaped(token):
                    candidates.append(
                        {
                            "line_number": line_number,
                            "line": stripped_line,
                            "matched_value": token,
                            "match_type": "coin-proximity",
                            "detail": coin_keyword,
                        }
                    )

    return candidates


def scan_directory(start_path, max_file_size=DEFAULT_MAX_FILE_SIZE):
    """
    Walk start_path exactly like find_seed_phrases.scan_directory does --
    no filename/extension allowlist, skip files above max_file_size, skip
    anything that sniffs as binary (tools.find_seed_phrases._looks_like_text,
    reused directly rather than reimplemented) -- then run
    find_candidate_lines() against the (errors="ignore") text of every
    file that survives those two filters.

    :return: {file_path: [candidate dicts]} -- files with zero candidates
        are omitted, same convention as find_seed_phrases.scan_directory.
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

            candidates = find_candidate_lines(text)
            if candidates:
                results[file_path] = candidates

    return results


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Scan a directory for password/credential-shaped text candidates (best-effort heuristic, not checksum-validated)."
    )
    parser.add_argument("start_path", help="Directory to scan.")
    parser.add_argument("output_file", help="Output JSON file for found candidates.")
    args = parser.parse_args()

    results = scan_directory(args.start_path)

    with open(args.output_file, "w") as f:
        json.dump(results, f, indent=4)

    # Same discipline as find_seed_phrases.py: never print matched text to
    # stdout/logs. Only counts and the output file path are safe to print.
    total_candidates = sum(len(v) for v in results.values())
    print(f"Found {total_candidates} candidate(s) across {len(results)} file(s). See {args.output_file}.")
    for file_path, candidates in results.items():
        print(f"  {file_path}: {len(candidates)} candidate(s)")
