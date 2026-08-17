import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.crawl_transaction_graph import compute_last_activity_timestamp, dormancy_years, fetch_address_transactions
from tools.scan_wallet_dat import EXPECTED_MAGIC, scan_wallet_for_addresses


def identify_wallet_software(wallet_path):
    """
    Best-effort software identification from file structure alone --
    deterministic where possible (a Bitcoin Core wallet.dat's magic bytes are
    unambiguous), "Unknown" otherwise. Never guesses which *service* a
    balance belongs to -- see docs/wallet_recovery_reference.md for why that
    needs the user's own memory, not automated classification.
    """
    try:
        with open(wallet_path, "rb") as f:
            f.seek(12)
            magic = f.read(8)
    except OSError:
        return "Unknown -- could not read file"

    if magic == EXPECTED_MAGIC:
        return "Bitcoin Core (Berkeley DB Btree v9 wallet.dat)"
    return "Unknown -- not a recognized Bitcoin Core wallet.dat structure"


def _file_metadata(wallet_path):
    st = os.stat(wallet_path)
    return {
        "path": str(wallet_path),
        "size_bytes": st.st_size,
        "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


def build_wallet_report(wallet_path, target_addresses=None, now=None):
    """
    Combines deterministic file-structure identification, encryption status,
    and (only for target_addresses, to avoid an accidental full-wallet
    on-chain crawl) public on-chain dormancy for specific addresses of
    interest -- typically the ones a balance check already found.

    :param target_addresses: addresses to fetch on-chain activity for. None
        (default) skips on-chain lookups entirely -- metadata/software/
        encryption status only.
    :return: {"metadata", "software", "encrypted", "encrypted_key_count",
              "total_addresses", "addresses": [{"address",
              "last_activity_timestamp", "dormant_years"}, ...]}
    """
    metadata = _file_metadata(wallet_path)
    software = identify_wallet_software(wallet_path)
    scan = scan_wallet_for_addresses(wallet_path)

    addresses_info = []
    for target in target_addresses or []:
        txs = fetch_address_transactions(target)
        last_activity = compute_last_activity_timestamp(txs)
        addresses_info.append(
            {
                "address": target,
                "last_activity_timestamp": last_activity,
                "dormant_years": dormancy_years(last_activity, now=now) if last_activity else None,
            }
        )

    return {
        "metadata": metadata,
        "software": software,
        "encrypted": scan["encrypted_key_count"] > 0,
        "encrypted_key_count": scan["encrypted_key_count"],
        "total_addresses": len(scan["addresses"]),
        "addresses": addresses_info,
    }


def render_wallet_report(report):
    """Plain-text/Markdown report -- a decision aid, not a verdict."""
    lines = [
        "# Wallet Recoverability Report",
        "",
        f"File: `{report['metadata']['path']}`",
        f"Size: {report['metadata']['size_bytes']} bytes",
        f"Last modified (filesystem, not on-chain): {report['metadata']['modified_at']}",
        f"Identified software: {report['software']}",
        f"Encrypted: {'yes' if report['encrypted'] else 'no'} ({report['encrypted_key_count']} encrypted key record(s))",
        f"Total addresses found in this file: {report['total_addresses']}",
        "",
    ]

    if report["addresses"]:
        lines.append("## On-chain activity for addresses of interest")
        lines.append("")
        for entry in report["addresses"]:
            if entry["last_activity_timestamp"] is None:
                lines.append(f"- `{entry['address']}`: no confirmed on-chain activity found.")
            else:
                last_seen = datetime.fromtimestamp(entry["last_activity_timestamp"], tz=timezone.utc).isoformat()
                lines.append(
                    f"- `{entry['address']}`: last on-chain activity {last_seen} "
                    f"({entry['dormant_years']:.1f} years dormant)."
                )
        lines.append("")

    lines.append(
        "This report identifies *software* deterministically from file structure, and *on-chain "
        "activity* from public blockchain data. It cannot tell you whether an address was ever "
        "self-custody vs. a custodial/exchange balance -- that judgment needs your own memory "
        "alongside docs/wallet_recovery_reference.md (a reference for you to cross-check against "
        "your own memory, not an automated classifier)."
    )

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate a recoverability report for a Bitcoin Core wallet.dat.")
    parser.add_argument("wallet_path", help="Path to the wallet.dat file.")
    parser.add_argument("output_file", help="Output Markdown file for the report.")
    parser.add_argument(
        "--address",
        action="append",
        dest="target_addresses",
        help="Address to fetch on-chain activity for (repeatable). Omit to skip on-chain lookups.",
    )
    args = parser.parse_args()

    report = build_wallet_report(args.wallet_path, target_addresses=args.target_addresses)

    with open(args.output_file, "w") as f:
        f.write(render_wallet_report(report))

    print(f"Report written to {args.output_file}.")
