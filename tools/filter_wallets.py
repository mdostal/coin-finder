import json

def filter_wallet_balances(input_file, output_file):
    """
    Filters wallets to remove entries with zero balances.

    :param input_file: Path to the JSON file with wallet balances.
    :param output_file: Path to save the filtered JSON file.
    """
    try:
        # Load wallet balances from input file
        with open(input_file, "r") as f:
            wallet_data = json.load(f)

        # Filter out zero-balance wallets
        filtered_data = {}
        for file_path, crypto_data in wallet_data.items():
            filtered_crypto_data = {}
            for crypto, addresses in crypto_data.items():
                non_zero_addresses = {addr: balance for addr, balance in addresses.items() if balance and balance > 0}
                if non_zero_addresses:
                    filtered_crypto_data[crypto] = non_zero_addresses
            if filtered_crypto_data:
                filtered_data[file_path] = filtered_crypto_data

        # Save the filtered data to the output file
        with open(output_file, "w") as f:
            json.dump(filtered_data, f, indent=4)

        print(f"Filtered data saved to {output_file}.")
    except Exception as e:
        print(f"Error processing the file: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remove wallets with zero balances from the JSON file.")
    parser.add_argument("input_file", help="Path to the JSON file containing wallet balances.")
    parser.add_argument("output_file", help="Path to save the filtered JSON file.")
    args = parser.parse_args()

    filter_wallet_balances(args.input_file, args.output_file)