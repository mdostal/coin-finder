import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from tools.unlock_wallet import check_network_status  # reused, not duplicated


def find_exodus2hashcat_script():
    """Locate vendor/hashcat-tools/exodus2hashcat.py relative to the repo root."""
    candidate = Path(REPO_ROOT) / "vendor" / "hashcat-tools" / "exodus2hashcat.py"
    return str(candidate) if candidate.exists() else None


def extract_exodus_hash(seed_seco_path, script_path=None):
    """
    Run hashcat's own official exodus2hashcat.py against seed.seco, returning
    the EXODUS:... hash line. Safe: reads only public header/salt/KDF-
    parameter metadata (the same class of public data as a bcrypt hash) --
    never a password, never the encrypted seed's plaintext.
    """
    if script_path is None:
        script_path = find_exodus2hashcat_script()
    if script_path is None:
        raise RuntimeError(
            "exodus2hashcat.py is not installed. Run scripts/install_exodus_tools.sh first."
        )

    result = subprocess.run(
        [sys.executable, script_path, seed_seco_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"exodus2hashcat.py failed: {result.stderr.strip()}")
    return result.stdout.strip()


def run_exodus_unlock(seed_seco_path, candidates_file, script_path=None, allow_online=False):
    """
    Test candidate passwords (from candidates_file, one per line -- never a
    CLI argument) against an Exodus wallet's seed.seco, via hashcat mode
    28200. HARD SAFETY GATE: refuses to run (no subprocess invoked) unless
    the machine is verified offline, or allow_online is explicitly set --
    same separation-principle discipline as unlock_wallet.py (BTCRecover),
    applied consistently here even though hashcat doesn't ship its own
    equivalent safety doc.

    :return: subprocess.CompletedProcess for the hashcat crack run.
    :raises RuntimeError: if the safety gate refuses, or a required tool is missing.
    """
    if not allow_online:
        status = check_network_status()
        if status != "OFFLINE":
            raise RuntimeError(
                f"Refusing to run: network status is {status}, not OFFLINE. "
                "Testing real passwords against a real wallet must happen with "
                "network disabled. Disconnect network and try again, or pass "
                "allow_online=True (--allow-online on the CLI) only for known-safe test data."
            )

    hash_string = extract_exodus_hash(seed_seco_path, script_path=script_path)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".hash", delete=False) as hash_file:
        hash_file.write(hash_string + "\n")
        hash_file_path = hash_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as outfile:
        outfile_path = outfile.name

    return subprocess.run(
        [
            "hashcat", "-m", "28200", "-a", "0", "--potfile-disable",
            # scrypt is intentionally memory-hard; some sandboxed/virtualized
            # environments misreport available memory, causing hashcat to
            # refuse to allocate even though there's enough. These flags trade
            # some speed for reliability and are safe defaults everywhere.
            "--backend-devices-keepfree", "5",
            "--scrypt-tmto", "4",
            "-o", outfile_path,
            hash_file_path, candidates_file,
        ],
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test candidate passwords against an Exodus wallet's seed.seco via hashcat (mode 28200). "
        "Candidates come from a file only -- never pass a password as a command-line argument."
    )
    parser.add_argument("seed_seco_path", help="Path to the Exodus wallet's seed.seco file.")
    parser.add_argument("candidates_file", help="File of candidate passwords, one per line.")
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="Override the offline safety gate. Only use this for known-safe test data -- "
        "real wallet recovery must run with network disabled.",
    )
    parser.add_argument("--exodus2hashcat-script", help="Path to exodus2hashcat.py (default: vendor/hashcat-tools/exodus2hashcat.py).")
    args = parser.parse_args()

    try:
        result = run_exodus_unlock(
            args.seed_seco_path,
            args.candidates_file,
            script_path=args.exodus2hashcat_script,
            allow_online=args.allow_online,
        )
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Relay hashcat's own output verbatim, same principle as unlock_wallet.py.
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
