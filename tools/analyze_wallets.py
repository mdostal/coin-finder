import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.analysis import CRYPTO_PATTERNS
from tools.scan_index import hash_file_bytes, is_known, record_scanned_file

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

def analyze_wallets(input_file, output_file, index_db_path=None):
    """
    Analyze files listed in the input file for cryptocurrency addresses.

    :param input_file: File containing paths of wallet files to analyze.
    :param output_file: File to save the analysis results.
    :param index_db_path: optional -- when given, skips the regex pass
        entirely for a file whose exact content has already been analyzed
        (by any prior scan, at any path), reusing its recorded result.
        Content-hash based, so a copy on a different drive/backup is
        recognized regardless of its current path. None (the default) is
        a complete no-op -- byte-identical to not having this parameter.
    """
    wallet_analysis = {}

    with open(input_file, "r") as f:
        file_paths = [line.strip() for line in f.readlines()]

    for file_path in file_paths:
        if index_db_path is not None:
            try:
                with open(file_path, "rb") as fh:
                    content = fh.read()
            except OSError as e:
                print(f"Error reading {file_path}: {e}")
                content = None

            if content is not None:
                file_hash = hash_file_bytes(content)
                cached_result = is_known(file_hash, db_path=index_db_path)
                if cached_result is not None:
                    print(f"Already scanned (duplicate content): {file_path} -- reusing prior result")
                    if cached_result:
                        wallet_analysis[file_path] = cached_result
                    continue

        print(f"Analyzing file: {file_path}")
        file_results = analyze_wallet_file(file_path)
        if file_results:
            wallet_analysis[file_path] = file_results

        if index_db_path is not None and content is not None:
            record_scanned_file(file_hash, file_path, file_results, db_path=index_db_path)

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
