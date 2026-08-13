import json
from collections import defaultdict

from config.wallet import WALLET_SERVICES


def _normalize(wallet_data):
    """
    Normalize either analyze_wallets.py's shape ({file: {coin: [address, ...]}})
    or check_wallet_balances.py's shape ({file: {coin: {address: balance}}}) into
    a common {file: {coin: {address: balance_or_None}}} representation.
    """
    normalized = {}
    for file_path, coins in wallet_data.items():
        normalized[file_path] = {}
        for coin, addresses in coins.items():
            if isinstance(addresses, dict):
                normalized[file_path][coin] = dict(addresses)
            else:
                normalized[file_path][coin] = {address: None for address in addresses}
    return normalized


def build_relationship_graph(wallet_data):
    """
    Correlate wallet data across files and coins to surface relationship signals:
    duplicate addresses (same address in 2+ files), multi-coin files (2+ coins in
    one file), and coverage gaps (supported coins not found in a given file).

    :param wallet_data: dict shaped like wallet_analysis.json or wallet_balances.json.
    :return: dict with "nodes", "edges", and "signals" keys.
    """
    normalized = _normalize(wallet_data)

    files = set()
    addresses = set()
    coins = set()
    file_has_address = []
    address_is_coin = set()
    address_to_files = defaultdict(set)
    file_to_coins = defaultdict(set)

    for file_path, coin_map in normalized.items():
        files.add(file_path)
        for coin, address_map in coin_map.items():
            coins.add(coin)
            file_to_coins[file_path].add(coin)
            for address, balance in address_map.items():
                addresses.add(address)
                address_is_coin.add((address, coin))
                address_to_files[address].add(file_path)
                file_has_address.append(
                    {"file": file_path, "address": address, "coin": coin, "balance": balance}
                )

    duplicate_addresses = {
        address: sorted(files_for_address)
        for address, files_for_address in address_to_files.items()
        if len(files_for_address) >= 2
    }

    multi_coin_files = {
        file_path: sorted(coins_for_file)
        for file_path, coins_for_file in file_to_coins.items()
        if len(coins_for_file) >= 2
    }

    supported_coins = set(WALLET_SERVICES.keys())
    coverage_gaps = {}
    for file_path, coins_for_file in file_to_coins.items():
        missing = sorted(supported_coins - coins_for_file)
        if missing:
            coverage_gaps[file_path] = {
                "found": sorted(coins_for_file),
                "missing_supported_coins": missing,
            }

    return {
        "nodes": {
            "files": sorted(files),
            "addresses": sorted(addresses),
            "coins": sorted(coins),
        },
        "edges": {
            "file_has_address": file_has_address,
            "address_is_coin": [
                {"address": address, "coin": coin} for address, coin in sorted(address_is_coin)
            ],
        },
        "signals": {
            "duplicate_addresses": duplicate_addresses,
            "multi_coin_files": multi_coin_files,
            "coverage_gaps": coverage_gaps,
        },
    }


def render_graph_report(graph):
    """
    Render a plain-text summary of a relationship graph, ordered by signal
    strength: duplicate addresses first, then multi-coin files, then coverage
    gaps (phrased as a nudge to double-check, never as an assertion).

    :param graph: dict as returned by build_relationship_graph().
    :return: str report.
    """
    lines = ["# Wallet Relationship Report", ""]

    lines.append("## Duplicate Addresses")
    duplicates = graph["signals"]["duplicate_addresses"]
    if duplicates:
        lines.append("The same address was found in more than one file -- strong evidence it's a real wallet:")
        for address, files in sorted(duplicates.items()):
            lines.append(f"- `{address}` found in: {', '.join(files)}")
    else:
        lines.append("No duplicate addresses found across files.")
    lines.append("")

    lines.append("## Multi-Coin Files")
    multi_coin = graph["signals"]["multi_coin_files"]
    if multi_coin:
        lines.append("These files yielded addresses for more than one coin, suggesting a multi-coin wallet backup:")
        for file_path, coins in sorted(multi_coin.items()):
            lines.append(f"- `{file_path}`: {', '.join(coins)}")
    else:
        lines.append("No multi-coin files found.")
    lines.append("")

    lines.append("## Coverage Gaps")
    coverage_gaps = graph["signals"]["coverage_gaps"]
    if coverage_gaps:
        lines.append(
            "These files matched at least one supported coin -- you might want to double-check "
            "them for the other supported coins listed below (not a confirmed finding, just worth checking):"
        )
        for file_path, gap in sorted(coverage_gaps.items()):
            missing = ", ".join(gap["missing_supported_coins"])
            lines.append(f"- `{file_path}` found {', '.join(gap['found'])} -- worth checking for: {missing}?")
    else:
        lines.append("No coverage gaps to report.")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a relationship graph across discovered wallet files/addresses/coins."
    )
    parser.add_argument("input_file", help="Input JSON file (wallet_analysis.json or wallet_balances.json).")
    parser.add_argument("output_file", help="Output JSON file for the relationship graph.")
    args = parser.parse_args()

    with open(args.input_file, "r") as f:
        wallet_data = json.load(f)

    graph = build_relationship_graph(wallet_data)

    with open(args.output_file, "w") as f:
        json.dump(graph, f, indent=4)

    print(f"Relationship graph saved to {args.output_file}.")
