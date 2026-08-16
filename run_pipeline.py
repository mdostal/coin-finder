import json
import os
from pathlib import Path
# Add the project root to the Python path
# sys.path.append(str(Path(__file__).resolve().parent))

from tools.search_wallets import search_for_wallets
from tools.analyze_wallets import analyze_wallets
from tools.check_wallet_balances import check_wallet_balances
from tools.filter_wallets import filter_wallet_balances
from tools.build_wallet_graph import build_relationship_graph, render_graph_report


def _paths(output_dir):
    sub_dir = os.path.join(output_dir, "checks")
    return {
        "sub_dir": sub_dir,
        "search_output": os.path.join(sub_dir, "wallet_search_output.txt"),
        "analyze_output": os.path.join(sub_dir, "wallet_analysis.json"),
        "scan_output": os.path.join(sub_dir, "wallet_balances.json"),
        "filter_output": os.path.join(output_dir, "filtered_wallets.json"),
    }


def find(input_dir, output_dir, index_db_path=None):
    """
    Stage 1 -- search + analyze only. No network calls, so it's fast
    regardless of how many addresses turn up. Returns a summary (files
    found, per-coin address-instance counts) so a caller can show real
    results and let a human decide whether the slow stage (check_balances)
    is even worth running before committing to it -- a loosely-matching
    coin regex pointed at a directory full of source/doc text can produce
    tens of thousands of garbage "address" matches, and there's no way to
    tell without seeing the count first.

    :param index_db_path: optional -- see tools.analyze_wallets.analyze_wallets().
        None (default) skips a file already analyzed in a prior scan
        (elsewhere, at any path) from being re-analyzed here.
    :return: {"output_dir", "files_found", "coin_counts", "total_address_instances"}
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = _paths(output_dir)
    Path(paths["sub_dir"]).mkdir(parents=True, exist_ok=True)

    print("Running wallet search...")
    search_for_wallets(input_dir, paths["search_output"])

    print("Running wallet analysis...")
    analyze_wallets(paths["search_output"], paths["analyze_output"], index_db_path=index_db_path)

    with open(paths["analyze_output"]) as f:
        analysis = json.load(f)

    coin_counts = {}
    for coins in analysis.values():
        for coin, addresses in coins.items():
            coin_counts[coin] = coin_counts.get(coin, 0) + len(addresses)

    return {
        "output_dir": output_dir,
        "files_found": len(analysis),
        "coin_counts": coin_counts,
        "total_address_instances": sum(coin_counts.values()),
    }


def check_balances(output_dir, progress_callback=None):
    """
    Stage 2 -- the slow part (real network calls, one per matched
    address). Requires find() to have already run against this exact
    output_dir; reads its wallet_analysis.json as input.
    """
    paths = _paths(output_dir)

    print("Running wallet balance check...")
    check_wallet_balances(paths["analyze_output"], paths["scan_output"], progress_callback=progress_callback)
    inconclusive_output = os.path.join(paths["sub_dir"], "inconclusive_balances.json")
    if os.path.exists(inconclusive_output):
        print(f"Some addresses are still inconclusive after retries -- see {inconclusive_output}.")

    print("Running wallet filter...")
    filter_wallet_balances(paths["scan_output"], paths["filter_output"])

    print("Building wallet relationship graph...")
    relationships_output = os.path.join(paths["sub_dir"], "wallet_relationships.json")
    relationships_report = os.path.join(output_dir, "wallet_relationships.md")
    with open(paths["scan_output"], "r") as f:
        scan_data = json.load(f)
    graph = build_relationship_graph(scan_data)
    with open(relationships_output, "w") as f:
        json.dump(graph, f, indent=4)
    with open(relationships_report, "w") as f:
        f.write(render_graph_report(graph))

    print(f"\nPipeline complete. Filtered wallets saved to {paths['filter_output']}.")
    print(f"Relationship report saved to {relationships_report}.")

    return {"output_dir": output_dir}


def main(input_dir, output_dir, progress_callback=None):
    """CLI/backward-compatible entry point -- runs both stages back to back, same behavior as before the find()/check_balances() split."""
    find(input_dir, output_dir)
    check_balances(output_dir, progress_callback=progress_callback)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the wallet processing pipeline.")
    parser.add_argument("input_dir", help="Input directory to search for wallets.")
    parser.add_argument("output_dir", help="Output directory to save results.")
    args = parser.parse_args()

    main(args.input_dir, args.output_dir)
