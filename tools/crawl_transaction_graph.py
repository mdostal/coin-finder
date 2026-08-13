import time

import requests

from services.bitcoin import BitcoinService

MAX_FETCH_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def fetch_address_transactions(address, max_retries=MAX_FETCH_RETRIES, backoff_seconds=RETRY_BACKOFF_SECONDS):
    """
    Fetch up to 25 recent confirmed transactions for a Bitcoin address from the
    Blockstream API, retrying on failure (never on a valid-but-empty result).

    :return: list of transaction dicts (Blockstream's /address/{addr}/txs shape).
    """
    url = f"https://blockstream.info/api/address/{address}/txs"
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException as e:
            print(f"Error fetching transactions for {address}: {e}")
        if attempt < max_retries:
            time.sleep(backoff_seconds)
    return []


def _tx_input_addresses(tx):
    return {
        vin["prevout"]["scriptpubkey_address"]
        for vin in tx.get("vin", [])
        if vin.get("prevout", {}).get("scriptpubkey_address")
    }


def find_co_spend_addresses(tx, known_address):
    """
    Return every OTHER input address on tx when known_address is also an input
    -- the common-input-ownership heuristic: building a transaction requires
    the private key for every input, so co-spending is strong evidence of
    common ownership.
    """
    input_addresses = _tx_input_addresses(tx)
    if known_address not in input_addresses:
        return set()
    return input_addresses - {known_address}


def find_output_addresses(tx, known_address, max_outputs=20):
    """
    Return output addresses on tx when known_address is an input AND the tx
    has at most max_outputs outputs -- transactions with more outputs than
    that are the mining-pool/exchange-batch pattern, not a personal transfer,
    and are skipped entirely (not partially followed).
    """
    input_addresses = _tx_input_addresses(tx)
    if known_address not in input_addresses:
        return set()

    outputs = tx.get("vout", [])
    if len(outputs) > max_outputs:
        return set()

    return {
        vout["scriptpubkey_address"]
        for vout in outputs
        if vout.get("scriptpubkey_address") and vout["scriptpubkey_address"] != known_address
    }


def crawl_wallet_cluster(seed_addresses, max_generations=2, max_addresses=200, balance_threshold=1.0):
    """
    BFS outward from seed_addresses using co-spend clustering (always followed)
    and bounded output-following (capped, lower confidence). Stops admitting
    new addresses once max_addresses total have been discovered (the current
    generation still finishes). Checks balance for every discovered address via
    the existing BitcoinService.

    :return: {address: {"confidence": "seed"|"co-spend"|"output",
                         "generation": int, "balance": float | None}}
    """
    discovered = {addr: {"confidence": "seed", "generation": 0} for addr in seed_addresses}
    frontier = set(seed_addresses)

    for generation in range(1, max_generations + 1):
        if not frontier:
            break

        next_frontier = set()
        for address in frontier:
            for tx in fetch_address_transactions(address):
                for co_spend in find_co_spend_addresses(tx, address):
                    if co_spend not in discovered and len(discovered) >= max_addresses:
                        continue
                    if co_spend not in discovered:
                        discovered[co_spend] = {"confidence": "co-spend", "generation": generation}
                        next_frontier.add(co_spend)

                for output_addr in find_output_addresses(tx, address):
                    if output_addr not in discovered and len(discovered) >= max_addresses:
                        continue
                    if output_addr not in discovered:
                        discovered[output_addr] = {"confidence": "output", "generation": generation}
                        next_frontier.add(output_addr)

        frontier = next_frontier

    service = BitcoinService()
    for address, info in discovered.items():
        info["balance"] = service.check_balance(address)

    return discovered


def render_cluster_report(results, balance_threshold=1.0):
    """
    Plain-text report of a wallet cluster, sorted by balance descending
    (None/0 last). Entries at or above balance_threshold are called out as
    SIGNIFICANT. Confidence-tagged throughout -- these are discovery
    candidates, not certain findings.
    """
    lines = ["# Transaction Graph Cluster Report", ""]

    def sort_key(item):
        _, info = item
        balance = info.get("balance")
        return balance if balance is not None else -1

    sorted_results = sorted(results.items(), key=sort_key, reverse=True)

    for address, info in sorted_results:
        balance = info.get("balance")
        balance_str = f"{balance:.8f} BTC" if balance is not None else "unknown (inconclusive)"
        tag = "SIGNIFICANT -- " if balance is not None and balance >= balance_threshold else ""
        lines.append(
            f"- {tag}`{address}` -- confidence: {info['confidence']}, "
            f"generation: {info['generation']}, balance: {balance_str}"
        )

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Crawl the Bitcoin transaction graph from a known address to discover likely same-owner addresses."
    )
    parser.add_argument("seed_address", help="Starting Bitcoin address.")
    parser.add_argument("output_file", help="Output JSON file for the cluster results.")
    parser.add_argument("--generations", type=int, default=2, help="Max BFS generations (default 2).")
    parser.add_argument("--max-addresses", type=int, default=200, help="Max addresses to discover (default 200).")
    parser.add_argument("--threshold", type=float, default=1.0, help="Balance (BTC) to flag as significant (default 1.0).")
    args = parser.parse_args()

    results = crawl_wallet_cluster(
        [args.seed_address],
        max_generations=args.generations,
        max_addresses=args.max_addresses,
        balance_threshold=args.threshold,
    )

    with open(args.output_file, "w") as f:
        json.dump(results, f, indent=4)

    report_file = args.output_file.rsplit(".", 1)[0] + ".md"
    with open(report_file, "w") as f:
        f.write(render_cluster_report(results, balance_threshold=args.threshold))

    print(f"Discovered {len(results)} address(es). JSON saved to {args.output_file}, report saved to {report_file}.")
