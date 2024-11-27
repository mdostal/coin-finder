import os
from pathlib import Path
from config.search import WALLET_EXTENSIONS, WALLET_KEYWORDS, MAX_FILE_SIZE, MIN_FILE_SIZE, COIN_NAMES

def search_for_wallets(start_path, output_file):
    potential_wallets = []

    for root, dirs, files in os.walk(start_path):
        for file in files:
            file_path = Path(root) / file
            try:
                file_size = file_path.stat().st_size

                # Skip files outside the size range
                if file_size > MAX_FILE_SIZE:
                    print(f"Skipping large file: {file_path} ({file_size / (1024 * 1024):.2f} MB)")
                    continue
                if file_size < MIN_FILE_SIZE:
                    print(f"Skipping empty or very small file: {file_path}")
                    continue

                # Check if the file matches extensions or keywords
                if any(file_path.suffix.lower() == ext for ext in WALLET_EXTENSIONS) or \
                   any(coin_name in file.lower() for coin_name in COIN_NAMES) or \
                   any(keyword in file.lower() for keyword in WALLET_KEYWORDS):
                    potential_wallets.append(str(file_path))
            except Exception as e:
                print(f"Error accessing file {file_path}: {e}")

    # Write results to the output file
    with open(output_file, "w") as f:
        for wallet in potential_wallets:
            f.write(wallet + "\n")

    print(f"Search complete. Found {len(potential_wallets)} potential wallet files.")
    print(f"Results saved to {output_file}.")
    return potential_wallets

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Search for potential crypto wallet files.")
    parser.add_argument("start_path", help="Path to start searching from.")
    parser.add_argument("output_file", help="File to save the list of wallet files.")
    args = parser.parse_args()

    search_for_wallets(args.start_path, args.output_file)