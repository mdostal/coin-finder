import json
import os
import subprocess
import sys

from tools.find_password_candidates import (
    _looks_password_shaped,
    find_candidate_lines,
    scan_directory,
)


def test_finds_explicit_label_match_with_file_and_line_context():
    text = "some notes\npassword: hunter2\nmore notes"

    candidates = find_candidate_lines(text)

    assert len(candidates) == 1
    assert candidates[0]["line_number"] == 2
    assert candidates[0]["line"] == "password: hunter2"
    assert candidates[0]["matched_value"] == "hunter2"
    assert candidates[0]["match_type"] == "label"
    assert candidates[0]["detail"] == "password"


def test_label_matching_is_case_insensitive_and_covers_all_required_labels():
    for label in ["password", "pw", "pass", "passphrase", "pwd", "PASSWORD", "Pw"]:
        text = f"{label}: value123"
        candidates = find_candidate_lines(text)
        assert len(candidates) == 1, f"expected a match for label {label!r}"
        assert candidates[0]["match_type"] == "label"


def test_label_regex_does_not_match_inside_unrelated_words():
    # "pass" and "pw" as substrings of other words shouldn't trigger --
    # word-boundary check.
    text = "compass: pointing north\ngrowpw: not a label"

    candidates = find_candidate_lines(text)

    assert candidates == []


def test_finds_coin_name_proximity_match():
    text = "bitcoin backup: correcthorsebatterystaple"

    candidates = find_candidate_lines(text)

    coin_matches = [c for c in candidates if c["match_type"] == "coin-proximity"]
    assert len(coin_matches) == 1
    assert coin_matches[0]["matched_value"] == "correcthorsebatterystaple"
    assert coin_matches[0]["detail"] == "bitcoin"
    assert coin_matches[0]["line_number"] == 1


def test_coin_proximity_does_not_flag_the_coin_or_wallet_keyword_itself():
    text = "my ethereum wallet backup notes are on the shelf"

    candidates = find_candidate_lines(text)

    assert candidates == []


def test_ordinary_prose_produces_zero_candidates():
    text = "The quick brown fox jumps over the lazy dog near the riverbank every single morning."

    candidates = find_candidate_lines(text)

    assert candidates == []


def test_prose_about_passwords_without_a_label_or_coin_mention_produces_zero_candidates():
    text = "Make sure your password is strong and change it every few months for better security."

    candidates = find_candidate_lines(text)

    assert candidates == []


def test_looks_password_shaped_true_for_mixed_character_classes():
    assert _looks_password_shaped("hunter2") is False  # below min length
    assert _looks_password_shaped("Tr0ub4dor&3xyz") is True
    assert _looks_password_shaped("correcthorsebatterystaple") is True  # long pure-lowercase


def test_looks_password_shaped_false_for_short_or_ordinary_words():
    assert _looks_password_shaped("wallet") is False
    assert _looks_password_shaped("backup") is False
    assert _looks_password_shaped("security") is False


def test_scan_directory_finds_only_the_file_with_a_candidate(tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live")
    (tmp_path / "shopping_list.txt").write_text("milk eggs bread butter")

    results = scan_directory(str(tmp_path))

    assert list(results.keys()) == [str(tmp_path / "notes.txt")]
    assert results[str(tmp_path / "notes.txt")][0]["matched_value"] == "hunter2live"


def test_scan_directory_skips_files_above_max_file_size(tmp_path):
    big_file = tmp_path / "big.txt"
    big_file.write_text("password: hunter2live " + ("padding " * 1000))

    results = scan_directory(str(tmp_path), max_file_size=10)

    assert results == {}


def test_scan_directory_skips_binary_files_without_matching_their_content(tmp_path):
    binary_file = tmp_path / "image.png"
    binary_file.write_bytes(b"\x89PNG\x00\x00\x00" + b"password: hunter2live")
    (tmp_path / "notes.txt").write_text("password: hunter2live")

    results = scan_directory(str(tmp_path))

    assert list(results.keys()) == [str(tmp_path / "notes.txt")]


def test_scan_directory_has_no_filename_or_extension_allowlist(tmp_path):
    # Unlike search_wallets.py, this scanner has no filename/extension gate
    # at all -- a password note has no reason to be named anything
    # wallet-shaped. A file with a totally generic name/extension must
    # still be scanned.
    odd_file = tmp_path / "randomfile.xyz123"
    odd_file.write_text("passphrase: correcthorsebatterystaple")

    results = scan_directory(str(tmp_path))

    assert str(odd_file) in results


def test_cli_never_prints_matched_text_to_stdout_but_writes_it_to_output_file(tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live")
    output_file = tmp_path / "found.json"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    result = subprocess.run(
        [sys.executable, "tools/find_password_candidates.py", str(tmp_path), str(output_file)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "hunter2live" not in result.stdout
    assert "hunter2live" not in result.stderr

    data = json.loads(output_file.read_text())
    assert data[str(tmp_path / "notes.txt")][0]["matched_value"] == "hunter2live"


def test_module_never_imports_findings_or_vault_write_functions():
    # This scanner's output is candidates, never findings -- confirm the
    # module never even imports record_finding/add_vault_entry (the two
    # real integration points into findings.db / the vault store), as a
    # static safety net alongside the web-layer test that confirms
    # record_finding is never actually invoked. Checked as an import,
    # not a raw substring search, since this module's own docstrings
    # legitimately name those functions in prose explaining why it never
    # calls them.
    import tools.find_password_candidates as mod

    assert not hasattr(mod, "record_finding")
    assert not hasattr(mod, "add_vault_entry")


# --- False-positive-rate measurement against a realistic test corpus ---
#
# There is no structural validator for "this text is a password" (unlike
# a coin address or a BIP39 seed phrase -- see module docstring). This
# test doesn't just assert "zero false positives and move on" -- it runs
# the real heuristic against a deliberately adversarial mix of ordinary
# notes-shaped prose (including prose that specifically talks about
# passwords/security/wallets/crypto, the exact topics likely to share
# vocabulary with real credential notes) and reports the actual measured
# rate. See the story's completion notes / final summary for the numbers
# this test prints.

# Prose that must NOT be flagged: no explicit "label: value" credential
# line, and no password-shaped token sitting next to a coin/wallet
# keyword. Deliberately includes tricky cases: mentions of "wallet" as a
# literal physical wallet, discussion of password hygiene/managers
# without ever writing a credential down, and long ordinary English words
# on lines that also mention a coin/wallet keyword (the exact combination
# most likely to trip the coin-proximity heuristic).
NEGATIVE_COIN_PROXIMITY_CORPUS = [
    "Make sure your password is strong and unique for every account.",
    "Password managers like 1Password or Bitwarden can generate and store complex passwords for you.",
    "Two-factor authentication adds an extra layer of security beyond just a password.",
    "Never write your password down where someone else could find it.",
    "I keep my leather wallet in my back left pocket most days.",
    "The old wallet on the dresser has some cash and my drivers license in it.",
    "Remember to update your password every few months for better security.",
    "She lost her wallet at the grocery store last Tuesday afternoon.",
    "This document explains best practices for password hygiene and account recovery.",
    "A strong passphrase is usually easier to remember than a random string of characters.",
    "Consider enabling passwordless login using a hardware security key instead.",
    "Backup your important documents regularly in case of hardware failure.",
    "The crypto market has been extremely volatile this quarter, according to analysts.",
    "Bitcoin's price surged after the latest halving event, according to news reports.",
    "Remember to back up your phone before installing the new update.",
    "The Ethereum Foundation announced a new roadmap for scaling the network.",
    "I need to buy a new wallet since mine is falling apart at the seams.",
    "Please review the attached security policy document before your next audit.",
    "Consider using a passphrase generator to create memorable but secure passphrases.",
    "The bank recommends changing your online banking password periodically.",
    "Authentication failures are logged and reviewed weekly by the security team.",
    "Congratulations on completing your certification in cybersecurity fundamentals.",
    "The presentation covered password policies, encryption, and incident response.",
    "Our wallet app redesign focuses on a cleaner checkout experience for users.",
    "He keeps forgetting his password and has to reset it every single week.",
    "Store your backup codes somewhere safe in case you lose access to your authenticator app.",
    "The recommendations include using unique, unpredictable passphrases across every service.",
    "She felt an overwhelming sense of accomplishment after finishing the marathon.",
    "The documentation describes internationalization support added in this release.",
    "Keep your ethereum notes and characteristically detailed transaction logs organized.",
    "Our bitcoin wallet integration required extraordinarily thorough regression testing.",
    "The crypto wallet team is disproportionately focused on onboarding friction this quarter.",
    "Download the wallet app version 2.4.1-beta for the latest security patches.",
    "Set up 2FA before your bitcoin wallet software update to v3.2.0 rolls out.",
    "Bitcoin ATM locations near downtown accept cash deposits up to $3000 daily.",
    "The crypto exchange's outage notice mentioned scheduled maintenance windows.",
    "Our wallet onboarding checklist walks new users through backup best practices.",
]

# Realistic technical false-positive class, reported separately and NOT
# folded into the enforced fp_rate threshold below: transaction hashes,
# addresses, and checksums are themselves long alphanumeric strings, so a
# note that casually mentions one near a coin/wallet word will trip the
# coin-proximity heuristic even though nothing there is a password. This
# is a real, known limitation -- reported honestly rather than hidden --
# not something this heuristic can distinguish from a real password using
# text shape alone (a checksum and a strong password look identical as
# strings).
NEGATIVE_HASH_LOOKS_LIKE_PASSWORD_CORPUS = [
    "The bitcoin transaction id was 3a7f9c1e8b2d4560 according to the block explorer.",
    "My ethereum address is 0x1234567890abcdef1234567890abcdef12345678 for donations.",
    "wallet.dat backup checksum 8f14e45fceea167a5a36dedd4bea2543 -- verify before restoring.",
]

# Lines that SHOULD be flagged -- real credential-labeled lines and real
# coin-proximity password-shaped tokens, mirroring the acceptance
# criteria's positive cases. Used alongside the negative corpus to report
# precision/recall together, not just a false-positive count in isolation.
POSITIVE_CORPUS = [
    "password: hunter2live",
    "pw: Tr0ub4dor&3",
    "pass: correcthorsebatterystaple99",
    "passphrase: nightjar-violet-42-anchor",
    "pwd: qX7!mZ2p9Lk",
    "bitcoin backup: correcthorsebatterystaple",
    "ethereum wallet seed backup phrase: Sw0rdf1sh!!",
    "old crypto wallet password thumbdrive123",
]


def test_measured_false_positive_rate_against_realistic_corpus(capsys):
    false_positive_lines = []
    for line in NEGATIVE_COIN_PROXIMITY_CORPUS:
        if find_candidate_lines(line):
            false_positive_lines.append(line)

    true_positive_count = 0
    for line in POSITIVE_CORPUS:
        if find_candidate_lines(line):
            true_positive_count += 1

    fp_rate = len(false_positive_lines) / len(NEGATIVE_COIN_PROXIMITY_CORPUS)
    tp_rate = true_positive_count / len(POSITIVE_CORPUS)

    hash_false_positives = [line for line in NEGATIVE_HASH_LOOKS_LIKE_PASSWORD_CORPUS if find_candidate_lines(line)]
    hash_fp_rate = len(hash_false_positives) / len(NEGATIVE_HASH_LOOKS_LIKE_PASSWORD_CORPUS)

    print(f"\n[password-candidate FP measurement] negative corpus: {len(NEGATIVE_COIN_PROXIMITY_CORPUS)} lines, "
          f"{len(false_positive_lines)} false positive(s) -- rate {fp_rate:.1%}")
    print(f"[password-candidate FP measurement] positive corpus: {len(POSITIVE_CORPUS)} lines, "
          f"{true_positive_count} correctly flagged -- recall {tp_rate:.1%}")
    print(f"[password-candidate FP measurement] hash/address/checksum-shaped corpus (reported, not enforced): "
          f"{len(NEGATIVE_HASH_LOOKS_LIKE_PASSWORD_CORPUS)} lines, {len(hash_false_positives)} false positive(s) "
          f"-- rate {hash_fp_rate:.1%}")
    for line in false_positive_lines:
        print(f"[password-candidate FP measurement] false positive: {line!r}")
    for line in hash_false_positives:
        print(f"[password-candidate FP measurement] hash-shaped false positive: {line!r}")

    # The real, measured bar for this heuristic (see module docstring: no
    # structural validator exists here, unlike checksum-based matching
    # elsewhere in this codebase). Not zero -- it's the honestly-measured
    # number this test enforces so a future change can't silently regress
    # it without failing CI. The separate hash/address/checksum corpus
    # above is reported but deliberately not enforced here: a checksum and
    # a strong password are literally indistinguishable as text shape, so
    # driving that number down would require rejecting real passwords too
    # (see module comments) -- documented as a known residual limitation
    # instead of hidden.
    assert fp_rate <= 0.10, f"false-positive rate too high: {fp_rate:.1%} ({false_positive_lines})"
    assert tp_rate == 1.0, "every real credential-labeled/coin-proximity line in the positive corpus must be caught"
