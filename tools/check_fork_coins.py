import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.check_wallet_balances import _check_balance_with_retries, load_service

# Coins that fork-shared Bitcoin's address format at the time of their split
# -- the same private key that controls a BTC address controls the identical
# address on these chains too, so any BTC address is worth checking on all
# of them for free (no new derivation needed). This matters even for an
# address whose BTC balance is now zero: if the BTC was spent *after* a
# fork's snapshot block, the fork-coin balance at snapshot time is
# untouched on that fork's own chain unless it was separately moved there.
# Other, smaller/less liquid forks (Bitcoin Diamond, Bitcoin Private, Super
# Bitcoin, etc.) are a known, stated gap -- no service exists here for them,
# generally because they lack a stable public balance-check API.
FORK_COINS = ["Bitcoin Cash", "Bitcoin Gold", "Bitcoin SV"]


def check_fork_coin_balances(address, coins=None):
    """
    Check address's balance on every fork coin in `coins` (default
    FORK_COINS), reusing the existing per-coin services and retry helper.

    :return: {coin_name: balance | None}
    """
    coins = coins if coins is not None else FORK_COINS
    results = {}
    for coin in coins:
        service = load_service(coin)
        results[coin] = _check_balance_with_retries(service, address) if service else None
    return results


def check_fork_coins_for_addresses(addresses, coins=None):
    """
    :return: {address: {coin_name: balance | None}}
    """
    return {address: check_fork_coin_balances(address, coins=coins) for address in addresses}


def load_addresses_from_file(path):
    """
    Tolerant loader accepting scan_wallet_dat.py's output shape
    ({"results": [{"address": ...}, ...]}), crawl_transaction_graph.py's
    output shape ({address: {...}}), or a plain newline-separated address
    list. Returns a list of address strings.
    """
    with open(path, "r") as f:
        content = f.read()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [line.strip() for line in content.splitlines() if line.strip()]

    if isinstance(data, dict) and "results" in data:
        return [entry["address"] for entry in data["results"]]
    if isinstance(data, dict):
        return list(data.keys())
    if isinstance(data, list):
        return [entry.get("address", entry) if isinstance(entry, dict) else entry for entry in data]
    return [line.strip() for line in content.splitlines() if line.strip()]


def render_fork_coin_report(results, balance_threshold=0.0):
    """Plain-text report; any non-zero fork-coin balance is called out."""
    lines = [
        "# Fork Coin Report",
        "",
        f"Checked: {', '.join(FORK_COINS)} (same address/keys as Bitcoin -- Bitcoin SV shares "
        "the format too but has no service in this project yet, a known gap).",
        "",
    ]

    for address, coin_balances in results.items():
        significant = {c: b for c, b in coin_balances.items() if b is not None and b > balance_threshold}
        if significant:
            for coin, balance in significant.items():
                lines.append(f"- SIGNIFICANT -- `{address}` has {balance} {coin} -- worth checking.")
        else:
            lines.append(f"- `{address}`: nothing found on {', '.join(FORK_COINS)}.")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Check Bitcoin addresses for balances on fork coins that share the same address/keys (Bitcoin Cash, Bitcoin Gold)."
    )
    parser.add_argument(
        "addresses_file",
        help="File of addresses -- accepts scan_wallet_dat.py or crawl_transaction_graph.py JSON output, or a plain newline-separated list.",
    )
    parser.add_argument("output_file", help="Output JSON file for results.")
    args = parser.parse_args()

    addresses = load_addresses_from_file(args.addresses_file)
    results = check_fork_coins_for_addresses(addresses)

    with open(args.output_file, "w") as f:
        json.dump(results, f, indent=4)

    report_file = args.output_file.rsplit(".", 1)[0] + ".md"
    with open(report_file, "w") as f:
        f.write(render_fork_coin_report(results))

    significant_count = sum(
        1 for coin_balances in results.values() if any(b is not None and b > 0 for b in coin_balances.values())
    )
    print(f"Checked {len(addresses)} address(es) across {len(FORK_COINS)} fork coin(s). {significant_count} with a balance. See {report_file}.")
