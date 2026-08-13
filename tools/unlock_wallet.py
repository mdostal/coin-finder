import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)

# Mirrors BTCRecover's own utilities/net_check.py approach exactly: short TCP
# connections to well-known public DNS resolvers, reachable from almost any
# online network and unreachable when truly offline. Sends no wallet/secret
# data anywhere.
NET_CHECK_PROBES = [
    ("8.8.8.8", 53),
    ("1.1.1.1", 53),
    ("9.9.9.9", 53),
]


def check_network_status(timeout=2):
    """
    :return: "OFFLINE" (safe to proceed), "ONLINE" (do not proceed), or
        "UNKNOWN" (could not determine -- treat as unsafe).
    """
    reachable = 0
    unreachable = 0
    for host, port in NET_CHECK_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                reachable += 1
        except OSError:
            unreachable += 1

    if reachable > 0:
        return "ONLINE"
    if unreachable == len(NET_CHECK_PROBES):
        return "OFFLINE"
    return "UNKNOWN"


def find_btcrecover_script():
    """
    Locate vendor/btcrecover/btcrecover.py relative to the repo root.
    :return: path string, or None if not installed.
    """
    candidate = Path(REPO_ROOT) / "vendor" / "btcrecover" / "btcrecover.py"
    return str(candidate) if candidate.exists() else None


def run_unlock(wallet_path, candidates_file, btcrecover_script=None, allow_online=False):
    """
    Run BTCRecover against wallet_path with candidate passwords from
    candidates_file. HARD SAFETY GATE: refuses to run (no subprocess
    invoked) unless the machine is verified offline, or allow_online is
    explicitly set -- implements the separation principle documented in
    BTCRecover's own upstream SKILL.md: a single online session must never
    combine a wallet file with password candidates in a way that could
    unlock funds while online.

    :return: subprocess.CompletedProcess (stdout/stderr captured as text).
    :raises RuntimeError: if the safety gate refuses, or btcrecover_script
        cannot be resolved.
    """
    if not allow_online:
        status = check_network_status()
        if status != "OFFLINE":
            raise RuntimeError(
                f"Refusing to run: network status is {status}, not OFFLINE. "
                "Testing real passwords against a real wallet must happen with "
                "network disabled -- see vendor/btcrecover/SKILL.md. "
                "Disconnect network and try again, or pass allow_online=True "
                "(--allow-online on the CLI) only for known-safe test data."
            )

    if btcrecover_script is None:
        btcrecover_script = find_btcrecover_script()
    if btcrecover_script is None:
        raise RuntimeError(
            "BTCRecover is not installed. Run scripts/install_btcrecover.sh first."
        )

    return subprocess.run(
        [sys.executable, btcrecover_script, "--wallet", wallet_path, "--passwordlist", candidates_file, "--no-progress"],
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test candidate passwords against a wallet file via BTCRecover. "
        "Candidates come from a file only -- never pass a password as a command-line argument."
    )
    parser.add_argument("wallet_path", help="Path to the wallet file.")
    parser.add_argument("candidates_file", help="File of candidate passwords, one per line.")
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="Override the offline safety gate. Only use this for known-safe test data -- "
        "real wallet recovery must run with network disabled.",
    )
    parser.add_argument("--btcrecover-script", help="Path to btcrecover.py (default: vendor/btcrecover/btcrecover.py).")
    args = parser.parse_args()

    try:
        result = run_unlock(
            args.wallet_path,
            args.candidates_file,
            btcrecover_script=args.btcrecover_script,
            allow_online=args.allow_online,
        )
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Relay BTCRecover's own output verbatim -- do not condense or paraphrase.
    # Its output includes the donation/tip-address block, which should reach
    # the user intact per BTCRecover's own SKILL.md guidance.
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
