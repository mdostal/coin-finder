import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import REQUEST_TIMEOUT_SECONDS
from services.bitcoin import BitcoinService

MAX_FETCH_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
CHECKPOINT_EVERY_ADDRESSES = 10
CHECKPOINT_EVERY_SECONDS = 15
SECONDS_PER_YEAR = 365.25 * 24 * 3600


def fetch_address_transactions(address, max_retries=MAX_FETCH_RETRIES, backoff_seconds=RETRY_BACKOFF_SECONDS):
    """
    Fetch up to 25 recent confirmed transactions for a Bitcoin address from the
    Blockstream API, retrying on failure (never on a valid-but-empty result).

    :return: list of transaction dicts (Blockstream's /address/{addr}/txs shape).
    """
    url = f"https://blockstream.info/api/address/{address}/txs"
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
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


def compute_last_activity_timestamp(transactions):
    """
    Return the most recent confirmed block_time among transactions, or None
    if there are no confirmed transactions.
    """
    confirmed_times = [
        tx["status"]["block_time"]
        for tx in transactions
        if tx.get("status", {}).get("confirmed") and tx["status"].get("block_time") is not None
    ]
    return max(confirmed_times) if confirmed_times else None


def dormancy_years(last_activity_timestamp, now=None):
    """
    Years elapsed since last_activity_timestamp, or None when last activity is
    unknown. `now` is injectable for testability; defaults to the real time.
    """
    if last_activity_timestamp is None:
        return None
    if now is None:
        now = time.time()
    return (now - last_activity_timestamp) / SECONDS_PER_YEAR


def _crawl_checkpoint_key(seed_addresses, max_generations, max_addresses):
    return {"seed_addresses": sorted(seed_addresses), "max_generations": max_generations, "max_addresses": max_addresses}


def _load_crawl_checkpoint(checkpoint_path, key):
    if not checkpoint_path or not Path(checkpoint_path).exists():
        return None
    try:
        with open(checkpoint_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("key") != key:
        return None
    return data


def crawl_wallet_cluster(
    seed_addresses,
    max_generations=2,
    max_addresses=200,
    balance_threshold=1.0,
    now=None,
    edges_out=None,
    checkpoint_path=None,
    progress_callback=None,
):
    """
    BFS outward from seed_addresses using co-spend clustering (always followed)
    and bounded output-following (capped, lower confidence). Stops admitting
    new addresses once max_addresses total have been discovered (the current
    generation still finishes). Checks balance and last-activity/dormancy for
    every discovered address via the existing BitcoinService.

    :param edges_out: optional list -- when given, every distinct
        relationship observed (not just the first one that discovers a
        new address) is appended as {"from", "to", "type": "co-spend"|
        "output", "txid"}. None (the default) is a complete no-op --
        every existing caller is unaffected. Co-spend is symmetric
        evidence (same-tx common-input ownership), so from/to are
        sorted before appending -- otherwise the SAME real transaction,
        observed once from each side's own transaction fetch, would
        record as two directionally-swapped duplicates. Output keeps
        sender->receiver direction as-is (a real transfer has real
        directionality). Deduplicated by (from, to, type, txid) within
        this call.
    :param checkpoint_path: optional -- makes this resumable across a
        quit/update/crash, same idea as search_for_wallets/check_wallet_
        balances. Two different granularities for the two different-
        shaped phases: BFS discovery checkpoints after each full
        generation completes (a partial generation restarts from its own
        beginning, not the whole crawl); the balance/dormancy pass --
        the dominant cost for a realistic address count -- checkpoints
        per address, same as check_wallet_balances, and skips addresses
        already confirmed on resume.
    :param progress_callback: optional callable(current, total, message).
    :return: {address: {"confidence": "seed"|"co-spend"|"output",
                         "generation": int, "discovered_via": str | None,
                         "balance": float | None,
                         "last_activity_timestamp": int | None,
                         "dormant_years": float | None}}
        discovered_via is the specific frontier address this one was
        found from (None for seeds) -- lets a caller draw real edges, not
        just generation rings.
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    key = _crawl_checkpoint_key(seed_addresses, max_generations, max_addresses)
    checkpoint = _load_crawl_checkpoint(checkpoint_path, key)

    def _flush(discovered, frontier, generation, bfs_done):
        if not checkpoint_path:
            return
        with open(checkpoint_path, "w") as f:
            json.dump(
                {
                    "key": key,
                    "discovered": discovered,
                    "frontier": sorted(frontier),
                    "generation": generation,
                    "bfs_done": bfs_done,
                    "edges": edges_out if edges_out is not None else [],
                },
                f,
            )

    if checkpoint:
        discovered = checkpoint["discovered"]
        frontier = set(checkpoint["frontier"])
        start_generation = checkpoint["generation"]
        bfs_done = checkpoint["bfs_done"]
        if edges_out is not None:
            for edge in checkpoint.get("edges", []):
                if edge not in edges_out:
                    edges_out.append(edge)
        print(f"Resuming crawl: {len(discovered)} address(es) already discovered, generation {start_generation}.")
    else:
        discovered = {addr: {"confidence": "seed", "generation": 0, "discovered_via": None} for addr in seed_addresses}
        frontier = set(seed_addresses)
        start_generation = 1
        bfs_done = False

    tx_cache = {}

    def record_edge(edge):
        if edges_out is not None and edge not in edges_out:
            edges_out.append(edge)

    if not bfs_done:
        for generation in range(start_generation, max_generations + 1):
            if not frontier:
                break

            ordered_frontier = sorted(frontier)
            next_frontier = set()
            for i, address in enumerate(ordered_frontier, start=1):
                txs = fetch_address_transactions(address)
                tx_cache[address] = txs
                for tx in txs:
                    for co_spend in find_co_spend_addresses(tx, address):
                        record_edge({"from": min(address, co_spend), "to": max(address, co_spend), "type": "co-spend", "txid": tx["txid"]})
                        if co_spend not in discovered and len(discovered) >= max_addresses:
                            continue
                        if co_spend not in discovered:
                            discovered[co_spend] = {"confidence": "co-spend", "generation": generation, "discovered_via": address}
                            next_frontier.add(co_spend)

                    for output_addr in find_output_addresses(tx, address):
                        record_edge({"from": address, "to": output_addr, "type": "output", "txid": tx["txid"]})
                        if output_addr not in discovered and len(discovered) >= max_addresses:
                            continue
                        if output_addr not in discovered:
                            discovered[output_addr] = {"confidence": "output", "generation": generation, "discovered_via": address}
                            next_frontier.add(output_addr)

                progress_callback(i, len(ordered_frontier), f"Generation {generation}: {address}")

            frontier = next_frontier
            _flush(discovered, frontier, generation + 1, bfs_done=False)

        bfs_done = True
        _flush(discovered, set(), max_generations + 1, bfs_done=True)

    service = BitcoinService()
    already_finalized = {addr for addr, info in discovered.items() if "balance" in info}
    remaining = [addr for addr in discovered if addr not in already_finalized]
    total = len(discovered)
    checked = len(already_finalized)
    last_checkpoint_at = time.time()

    for i, address in enumerate(remaining, start=1):
        info = discovered[address]
        info["balance"] = service.check_balance(address)

        txs = tx_cache.get(address)
        if txs is None:
            txs = fetch_address_transactions(address)
        last_activity = compute_last_activity_timestamp(txs)
        info["last_activity_timestamp"] = last_activity
        info["dormant_years"] = dormancy_years(last_activity, now=now)

        checked += 1
        progress_callback(checked, total, f"Checking balance: {address}")
        if checkpoint_path and (i % CHECKPOINT_EVERY_ADDRESSES == 0 or time.time() - last_checkpoint_at >= CHECKPOINT_EVERY_SECONDS):
            _flush(discovered, set(), max_generations + 1, bfs_done=True)
            last_checkpoint_at = time.time()

    if checkpoint_path:
        Path(checkpoint_path).unlink(missing_ok=True)

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

        dormant_years = info.get("dormant_years")
        if dormant_years is not None:
            activity_str = f", last activity {dormant_years:.1f} years ago"
            if dormant_years >= 5:
                activity_str += " (dormant 5+ years -- verify this matches what you expected)"
        else:
            activity_str = ", last activity unknown"

        lines.append(
            f"- {tag}`{address}` -- confidence: {info['confidence']}, "
            f"generation: {info['generation']}, balance: {balance_str}{activity_str}"
        )

    lines.append("")
    return "\n".join(lines)


def load_seed_addresses(arg):
    """
    Accept either a single literal address, or the path to a file of
    addresses (one per line; blank lines and lines starting with '#'
    ignored) -- lets a run mix addresses found on disk with addresses the
    user currently holds/knows about into one combined seed set. Auto-
    detected: if arg resolves to an existing file, read it as a list;
    otherwise treat arg itself as a single address.
    """
    if os.path.isfile(arg):
        with open(arg, "r") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    return [arg]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Crawl the Bitcoin transaction graph from one or more known addresses to discover likely same-owner addresses."
    )
    parser.add_argument(
        "seed_address_or_file",
        help="A single starting Bitcoin address, or a path to a file of addresses (one per line) -- "
        "mix addresses found on disk with addresses you currently hold/know about.",
    )
    parser.add_argument("output_file", help="Output JSON file for the cluster results.")
    parser.add_argument("--generations", type=int, default=2, help="Max BFS generations (default 2).")
    parser.add_argument("--max-addresses", type=int, default=200, help="Max addresses to discover (default 200).")
    parser.add_argument("--threshold", type=float, default=1.0, help="Balance (BTC) to flag as significant (default 1.0).")
    args = parser.parse_args()

    seed_addresses = load_seed_addresses(args.seed_address_or_file)

    results = crawl_wallet_cluster(
        seed_addresses,
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
