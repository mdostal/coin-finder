import os
from pathlib import Path
import argparse

# Define wallet-related file extensions and keywords
WALLET_EXTENSIONS = ['.dat', '.key', '.wallet', '.json', '.backup']
WALLET_KEYWORDS = ['wallet', 'crypto', 'bitcoin', 'ethereum', 'backup']

def search_for_wallets(start_path, output_file):
    """
    Search for potential cryptocurrency wallet files in the given directory and subdirectories.

    :param start_path: Directory to start searching from.
    :param output_file: File to save the list of potential wallet file paths.
    """
    potential_wallets = []

    # Walk through the directory tree
    for root, dirs, files in os.walk(start_path):
        for file in files:
            # Check file extension
            file_path = Path(root) / file
            if any(file_path.suffix.lower() == ext for ext in WALLET_EXTENSIONS):
                potential_wallets.append(str(file_path))
            # Check file name keywords
            elif any(keyword in file.lower() for keyword in WALLET_KEYWORDS):
                potential_wallets.append(str(file_path))

    # Save results to the output file
    with open(output_file, "w") as f:
        for wallet in potential_wallets:
            f.write(wallet + "\n")

    print(f"Search complete. Found {len(potential_wallets)} potential wallet files.")
    print(f"Results saved to {output_file}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search for potential crypto wallet files.")
    parser.add_argument("start_path", help="Path to start searching from.")
    parser.add_argument("output_file", help="File to save the list of wallet files.")
    args = parser.parse_args()

    search_for_wallets(args.start_path, args.output_file)
