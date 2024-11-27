import json
import re

from config.analysis import CRYPTO_PATTERNS

def analyze_wallet_file(file_path):
    """
    Analyze a single file for cryptocurrency addresses.

    :param file_path: Path to the file to analyze.
    :return: Dictionary of found addresses grouped by cryptocurrency.
    """
    results = {}
    try:
        with open(file_path, "rb") as f:
            content = f.read()
            for crypto, pattern in CRYPTO_PATTERNS.items():
                matches = re.findall(pattern, content.decode(errors="ignore"))
                if matches:
                    results[crypto] = list(set(matches))  # Deduplicate results
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}")
    return results

def analyze_wallets(input_file, output_file):
    """
    Analyze files listed in the input file for cryptocurrency addresses.

    :param input_file: File containing paths of wallet files to analyze.
    :param output_file: File to save the analysis results.
    """
    wallet_analysis = {}

    with open(input_file, "r") as f:
        file_paths = [line.strip() for line in f.readlines()]

    for file_path in file_paths:
        print(f"Analyzing file: {file_path}")
        file_results = analyze_wallet_file(file_path)
        if file_results:
            wallet_analysis[file_path] = file_results

    # Save results to a JSON file
    with open(output_file, "w") as f:
        json.dump(wallet_analysis, f, indent=4)

    print(f"\nAnalysis complete. Results saved to {output_file}.")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze potential wallet files for crypto addresses.")
    parser.add_argument("input_file", help="File containing paths of wallet files to analyze.")
    parser.add_argument("output_file", help="File to save the analysis results.")
    args = parser.parse_args()

    analyze_wallets(args.input_file, args.output_file)
