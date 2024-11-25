import os
from pathlib import Path
# Add the project root to the Python path
# sys.path.append(str(Path(__file__).resolve().parent))

from tools.search_wallets import search_for_wallets
from tools.analyze_wallets import analyze_wallets
from tools.check_wallet_balances import check_wallet_balances
from tools.filter_wallets import filter_wallet_balances

def main(input_dir, output_dir):
    # make output dir if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    sub_dir_name = "/checks"
    sub_dir = output_dir+sub_dir_name
    # make sub dir if it doesn't exist
    Path(sub_dir).mkdir(parents=True, exist_ok=True)
    search_output = os.path.join(sub_dir, "wallet_search_output.txt")
    analyze_output = os.path.join(sub_dir, "wallet_analysis.json")
    scan_output = os.path.join(sub_dir, "wallet_balances.json")
    filter_output = os.path.join(output_dir, "filtered_wallets.json")

    print("Running wallet search...")
    search_for_wallets(input_dir, search_output)

    print("Running wallet analysis...")
    analyze_wallets(search_output, analyze_output)

    print("Running wallet balance check...")
    check_wallet_balances(analyze_output, scan_output)

    print("Running wallet filter...")
    filter_wallet_balances(scan_output, filter_output)

    print(f"\nPipeline complete. Filtered wallets saved to {filter_output}.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the wallet processing pipeline.")
    parser.add_argument("input_dir", help="Input directory to search for wallets.")
    parser.add_argument("output_dir", help="Output directory to save results.")
    args = parser.parse_args()

    main(args.input_dir, args.output_dir)